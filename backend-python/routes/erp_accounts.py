"""
Accounting API (ERP phase 6).

Most of what reaches the ledger arrives through the event outbox without any
request at all — a fee received posts itself, an approved payroll posts itself.
What is left is what a human genuinely does: record an expense, look at a
statement, close a month.

There is deliberately no "create journal entry" endpoint for everyday use.
`accounts.post` refuses an unbalanced entry and the database refuses it too;
manual entries go through the same service, with a reason, and only for people
who may post.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from models.erp_accounts import (
    ACCOUNT_TYPES, PERIOD_LOCKED, PERIOD_OPEN,
    AccountingPeriod, Expense, GLAccount, Journal, JournalLine, Vendor,
)
from models.models import User
from routes.erp import erp_available
from services.erp import accounts as accounting, audit, numbering
from services.erp.accounts import AccountingError
from services.erp.fees import money
from services.erp.permissions import require_permission

router = APIRouter(prefix="/erp/accounts", tags=["erp-accounts"])


def _fail(exc: AccountingError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ─── Chart of accounts ────────────────────────────────────────────────────────

@router.get("/chart")
async def chart(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GLAccount).order_by(GLAccount.code))
    return {"accounts": [a.to_dict() for a in result.scalars().all()]}


class AccountRequest(BaseModel):
    code: str
    name: str
    account_type: str
    is_postable: bool = True


@router.post("/chart")
async def create_account(
    body: AccountRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.post")),
    db: AsyncSession = Depends(get_db),
):
    if body.account_type not in ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown account type: {body.account_type}")

    result = await db.execute(select(GLAccount).where(GLAccount.code == body.code))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Account {body.code} already exists.")

    account = GLAccount(**body.model_dump())
    db.add(account)
    await db.flush()
    audit.record(db, actor=user, entity_type="gl_account", action="created",
                 entity_id=account.id, new_value=account.to_dict())
    await db.commit()
    return account.to_dict()


# ─── Expenses ─────────────────────────────────────────────────────────────────

class ExpenseRequest(BaseModel):
    expense_date: date
    account_id: str
    amount: Decimal
    paid_from: str = "cash"
    vendor_id: str | None = None
    reference: str | None = None
    description: str | None = None


@router.get("/expenses")
async def list_expenses(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(100, le=500),
):
    stmt = select(Expense, GLAccount).join(GLAccount, GLAccount.id == Expense.account_id)
    if from_date:
        stmt = stmt.where(Expense.expense_date >= from_date)
    if to_date:
        stmt = stmt.where(Expense.expense_date <= to_date)

    result = await db.execute(stmt.order_by(Expense.expense_date.desc()).limit(limit))
    rows = result.all()
    total = sum((money(e.amount) for e, _ in rows), money(0))

    return {
        "total": str(total),
        "expenses": [
            {**expense.to_dict(), "account_name": account.name, "account_code": account.code}
            for expense, account in rows
        ],
    }


@router.post("/expenses")
async def record_expense(
    body: ExpenseRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.post")),
    db: AsyncSession = Depends(get_db),
):
    """Record an expense. The accounting entry writes itself."""
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="The amount must be more than zero.")

    result = await db.execute(select(GLAccount).where(GLAccount.id == body.account_id))
    account = result.scalar_one_or_none()
    if account is None or not account.is_postable:
        raise HTTPException(status_code=400, detail="Choose an account expenses can be posted to.")

    expense_no = await numbering.allocate_one(db, numbering.SCOPE_EXPENSE)
    expense = Expense(
        expense_no=expense_no,
        recorded_by=user.id,
        **body.model_dump(),
    )
    db.add(expense)
    await db.flush()

    try:
        journal = await accounting.post_expense(
            db,
            expense_id=expense.id,
            account_id=body.account_id,
            amount=body.amount,
            paid_from=body.paid_from,
            entry_date=body.expense_date,
            memo=body.description or f"{account.name} — {expense_no}",
            actor=user,
        )
    except AccountingError as exc:
        await db.rollback()
        raise _fail(exc)

    expense.journal_id = journal.id if journal else None
    audit.record(db, actor=user, entity_type="expense", action="recorded",
                 entity_id=expense.id,
                 new_value={"amount": str(body.amount), "account": account.name})
    await db.commit()
    return expense.to_dict()


# ─── Vendors ──────────────────────────────────────────────────────────────────

class VendorRequest(BaseModel):
    name: str
    code: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    tax_number: str | None = None


@router.get("/vendors")
async def list_vendors(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Vendor).where(Vendor.is_active.is_(True)).order_by(Vendor.name))
    return {"vendors": [v.to_dict() for v in result.scalars().all()]}


@router.post("/vendors")
async def create_vendor(
    body: VendorRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.post")),
    db: AsyncSession = Depends(get_db),
):
    code = (body.code or body.name[:6].upper().replace(" ", "")).strip()
    result = await db.execute(select(Vendor).where(Vendor.code == code))
    if result.scalar_one_or_none():
        code = f"{code}-{int(date.today().strftime('%j'))}"

    vendor = Vendor(**{**body.model_dump(), "code": code})
    db.add(vendor)
    await db.flush()
    await db.commit()
    return vendor.to_dict()


# ─── Statements ───────────────────────────────────────────────────────────────

@router.get("/trial-balance")
async def trial_balance(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
    upto: date | None = None,
):
    return await accounting.trial_balance(db, upto=upto)


@router.get("/profit-and-loss")
async def profit_and_loss(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
    from_date: date | None = None,
    to_date: date | None = None,
):
    end = to_date or date.today()
    start = from_date or date(end.year if end.month >= 4 else end.year - 1, 4, 1)
    return await accounting.profit_and_loss(db, from_date=start, to_date=end)


@router.get("/balance-sheet")
async def balance_sheet(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
    upto: date | None = None,
):
    return await accounting.balance_sheet(db, upto=upto or date.today())


@router.get("/ledger/{account_id}")
async def account_ledger(
    account_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
    from_date: date | None = None,
    to_date: date | None = None,
):
    end = to_date or date.today()
    start = from_date or (end - timedelta(days=90))
    try:
        return await accounting.ledger_for_account(
            db, account_id=account_id, from_date=start, to_date=end,
        )
    except AccountingError as exc:
        raise _fail(exc)


@router.get("/journals")
async def list_journals(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=200),
):
    result = await db.execute(select(Journal).order_by(Journal.created_at.desc()).limit(limit))
    journals = list(result.scalars().all())

    result = await db.execute(
        select(JournalLine, GLAccount)
        .join(GLAccount, GLAccount.id == JournalLine.account_id)
        .where(JournalLine.journal_id.in_([j.id for j in journals]))
    ) if journals else None

    lines_by_journal: dict[str, list] = {}
    if result is not None:
        for line, account in result.all():
            lines_by_journal.setdefault(line.journal_id, []).append({
                **line.to_dict(), "account_name": account.name, "account_code": account.code,
            })

    return {
        "journals": [
            {**j.to_dict(), "lines": lines_by_journal.get(j.id, [])}
            for j in journals
        ]
    }


# ─── Periods ──────────────────────────────────────────────────────────────────

@router.get("/periods")
async def list_periods(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.view")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AccountingPeriod).order_by(AccountingPeriod.period.desc()))
    return {"periods": [p.to_dict() for p in result.scalars().all()]}


class PeriodRequest(BaseModel):
    period: str
    lock: bool = True


@router.post("/periods")
async def set_period(
    body: PeriodRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("accounts.post")),
    db: AsyncSession = Depends(get_db),
):
    """Close a month, or reopen one.

    Closing stops anything else being posted into it. A correction afterwards
    is a reversal plus a re-post in an open month — never an edit, because an
    audit that finds a changed figure with no trail stops believing the rest.
    """
    result = await db.execute(select(AccountingPeriod).where(AccountingPeriod.period == body.period))
    period = result.scalar_one_or_none()
    if period is None:
        period = AccountingPeriod(period=body.period)
        db.add(period)

    from models.models import utcnow
    period.status = PERIOD_LOCKED if body.lock else PERIOD_OPEN
    period.locked_by = user.id if body.lock else None
    period.locked_at = utcnow() if body.lock else None

    audit.record(db, actor=user, entity_type="accounting_period",
                 action="locked" if body.lock else "reopened",
                 entity_id=body.period)
    await db.commit()
    return period.to_dict()
