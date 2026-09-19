"""
The posting service (ERP phase 6).

Staff perform business actions; accounting happens to them. Receive a fee,
approve a payroll, record an expense — each has a posting rule here, driven off
the event outbox, and nobody in the school ever types a journal entry to record
a fee.

`post()` is the only way anything reaches the ledger. It refuses an unbalanced
entry, and the database refuses it too: `journals` carries its own totals with
a CHECK that they are equal, so an unbalanced row cannot exist whatever the
application believes about itself.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp_accounts import (
    ACCOUNT_TYPES, ASSET, CREDIT_NATURED, DEBIT_NATURED, EQUITY, EXPENSE,
    INCOME, LIABILITY, PERIOD_LOCKED, PERIOD_OPEN,
    AccountingPeriod, GLAccount, Journal, JournalLine,
)
from models.models import User
from services.erp import audit, events, numbering
from services.erp.fees import ZERO, money

logger = logging.getLogger("agent")


class AccountingError(RuntimeError):
    """Something accounts needs to fix, phrased for accounts."""


# ─── Chart of accounts ────────────────────────────────────────────────────────
# A school's chart, not a generic one. Codes follow the usual convention:
# 1 assets, 2 liabilities, 3 equity, 4 income, 5 expenses.

STANDARD_CHART: list[tuple[str, str, str, bool]] = [
    ("1000", "Assets", ASSET, False),
    ("1100", "Cash in Hand", ASSET, True),
    ("1200", "Bank", ASSET, True),
    ("1300", "Fees Receivable", ASSET, True),
    ("1400", "Advances to Staff", ASSET, True),
    ("1500", "Furniture & Equipment", ASSET, True),

    ("2000", "Liabilities", LIABILITY, False),
    ("2100", "Salaries Payable", LIABILITY, True),
    ("2200", "Accounts Payable", LIABILITY, True),
    ("2300", "Security Deposits Held", LIABILITY, True),
    ("2400", "Fees Received in Advance", LIABILITY, True),
    ("2500", "Tax Payable", LIABILITY, True),

    ("3000", "Equity", EQUITY, False),
    ("3100", "Capital", EQUITY, True),
    ("3200", "Retained Surplus", EQUITY, True),

    ("4000", "Income", INCOME, False),
    ("4100", "Tuition Fee Income", INCOME, True),
    ("4200", "Admission Fee Income", INCOME, True),
    ("4300", "Examination Fee Income", INCOME, True),
    ("4400", "Transport Income", INCOME, True),
    ("4900", "Other Income", INCOME, True),

    ("5000", "Expenses", EXPENSE, False),
    ("5100", "Salaries & Wages", EXPENSE, True),
    ("5200", "Utilities", EXPENSE, True),
    ("5300", "Rent", EXPENSE, True),
    ("5400", "Repairs & Maintenance", EXPENSE, True),
    ("5500", "Printing & Stationery", EXPENSE, True),
    ("5600", "Transport & Fuel", EXPENSE, True),
    ("5700", "Marketing", EXPENSE, True),
    ("5800", "IT & Software", EXPENSE, True),
    ("5900", "Other Expenses", EXPENSE, True),
]

# Where money lands for each business event.
ACCOUNT_CASH = "1100"
ACCOUNT_BANK = "1200"
ACCOUNT_FEES_RECEIVABLE = "1300"
ACCOUNT_SALARIES_PAYABLE = "2100"
ACCOUNT_FEE_INCOME = "4100"
ACCOUNT_SALARY_EXPENSE = "5100"


async def ensure_chart(db: AsyncSession) -> int:
    """Seed the chart of accounts. Idempotent, and safe on every boot."""
    result = await db.execute(select(GLAccount.code))
    existing = {row[0] for row in result.all()}

    created = 0
    by_code: dict[str, GLAccount] = {}
    for code, name, account_type, postable in STANDARD_CHART:
        if code in existing:
            continue
        account = GLAccount(code=code, name=name, account_type=account_type,
                            is_postable=postable)
        db.add(account)
        await db.flush()
        by_code[code] = account
        created += 1

    # Parent the leaves under their heading — 5100 under 5000, and so on.
    if created:
        result = await db.execute(select(GLAccount))
        all_accounts = {a.code: a for a in result.scalars().all()}
        for account in all_accounts.values():
            if account.parent_id or account.code.endswith("000"):
                continue
            heading = all_accounts.get(account.code[0] + "000")
            if heading:
                account.parent_id = heading.id

    return created


async def account_by_code(db: AsyncSession, code: str) -> GLAccount:
    result = await db.execute(select(GLAccount).where(GLAccount.code == code))
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountingError(f"Account {code} is missing from the chart of accounts.")
    return account


# ─── Posting ──────────────────────────────────────────────────────────────────

def period_of(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


async def period_is_locked(db: AsyncSession, period: str) -> bool:
    result = await db.execute(
        select(AccountingPeriod).where(AccountingPeriod.period == period)
    )
    row = result.scalar_one_or_none()
    return bool(row and row.status == PERIOD_LOCKED)


async def post(
    db: AsyncSession,
    *,
    entry_date: date,
    lines: list[dict],
    memo: str,
    source_type: str | None = None,
    source_id: str | None = None,
    dedupe_key: str | None = None,
    actor: User | None = None,
) -> Journal | None:
    """Write one balanced entry. The only way into the ledger.

    Returns None when `dedupe_key` has already been posted — that is a replayed
    event, not an error, and it is precisely what makes the outbox safe to
    retry.
    """
    if dedupe_key:
        result = await db.execute(select(Journal).where(Journal.dedupe_key == dedupe_key))
        if result.scalar_one_or_none():
            return None

    period = period_of(entry_date)
    if await period_is_locked(db, period):
        raise AccountingError(
            f"{period} is closed. Post the correction in an open period instead."
        )

    total_debit = sum((money(line.get("debit", 0)) for line in lines), ZERO)
    total_credit = sum((money(line.get("credit", 0)) for line in lines), ZERO)

    if total_debit != total_credit:
        raise AccountingError(
            f"This entry does not balance: debits {total_debit}, credits {total_credit}."
        )
    if total_debit <= ZERO:
        raise AccountingError("An entry with no amount cannot be posted.")

    journal_no = await numbering.allocate_one(db, numbering.SCOPE_JOURNAL)
    journal = Journal(
        journal_no=journal_no,
        entry_date=entry_date,
        period=period,
        source_type=source_type,
        source_id=source_id,
        dedupe_key=dedupe_key,
        memo=memo,
        total_debit=total_debit,
        total_credit=total_credit,
        posted_by=actor.id if actor else None,
    )
    db.add(journal)
    await db.flush()

    for line in lines:
        db.add(JournalLine(
            journal_id=journal.id,
            account_id=line["account_id"],
            debit=money(line.get("debit", 0)),
            credit=money(line.get("credit", 0)),
            memo=line.get("memo"),
        ))

    return journal


async def reverse(
    db: AsyncSession, *, journal_id: str, reason: str, actor: User | None = None,
) -> Journal:
    """Undo an entry with its mirror image, never by deleting it."""
    result = await db.execute(select(Journal).where(Journal.id == journal_id))
    original = result.scalar_one_or_none()
    if original is None:
        raise AccountingError("That entry was not found.")

    result = await db.execute(select(Journal).where(Journal.reversal_of == journal_id))
    if result.scalar_one_or_none():
        raise AccountingError("That entry has already been reversed.")

    result = await db.execute(select(JournalLine).where(JournalLine.journal_id == journal_id))
    lines = [
        {"account_id": line.account_id, "debit": line.credit, "credit": line.debit,
         "memo": f"Reversal: {line.memo or ''}".strip()}
        for line in result.scalars().all()
    ]

    journal = await post(
        db,
        entry_date=date.today(),
        lines=lines,
        memo=f"Reversal of {original.journal_no} — {reason}",
        source_type="reversal",
        source_id=original.id,
        actor=actor,
    )
    journal.reversal_of = original.id
    journal.reversal_reason = reason

    audit.record(db, actor=actor, entity_type="journal", action="reversed",
                 entity_id=original.id, reason=reason,
                 new_value={"reversal_no": journal.journal_no})
    return journal


# ─── Posting rules ────────────────────────────────────────────────────────────
# Business events post themselves. These handlers run from the outbox, are
# idempotent on the event's dedupe key, and are the only accounting anyone in
# the school ever performs.

@events.on(events.PAYMENT_RECEIVED)
async def _post_fee_receipt(db: AsyncSession, event) -> None:
    """Fee received: cash (or bank) goes up, fee income goes up."""
    payload = event.payload or {}
    amount = money(payload.get("amount", 0))
    if amount <= ZERO:
        return

    method = payload.get("method", "cash")
    cash_account = await account_by_code(db, ACCOUNT_BANK if method in ("bank", "online") else ACCOUNT_CASH)
    income_account = await account_by_code(db, ACCOUNT_FEE_INCOME)

    await post(
        db,
        entry_date=date.today(),
        lines=[
            {"account_id": cash_account.id, "debit": amount, "credit": ZERO,
             "memo": "Fee received"},
            {"account_id": income_account.id, "debit": ZERO, "credit": amount,
             "memo": "Fee income"},
        ],
        memo=f"Fee received — receipt {payload.get('receipt_id', '')[:8]}",
        source_type="fee_receipt",
        source_id=payload.get("receipt_id"),
        dedupe_key=f"gl:{event.dedupe_key or event.id}",
    )


@events.on(events.PAYROLL_APPROVED)
async def _post_payroll(db: AsyncSession, event) -> None:
    """Payroll approved: salary expense goes up, salaries payable goes up.

    Payment to staff is a separate entry when the run is marked paid — the
    school owes the money the moment payroll is approved, whether or not the
    transfer has left the bank.
    """
    payload = event.payload or {}
    amount = money(payload.get("total_net", 0))
    if amount <= ZERO:
        return

    expense_account = await account_by_code(db, ACCOUNT_SALARY_EXPENSE)
    payable_account = await account_by_code(db, ACCOUNT_SALARIES_PAYABLE)

    await post(
        db,
        entry_date=date.today(),
        lines=[
            {"account_id": expense_account.id, "debit": amount, "credit": ZERO,
             "memo": f"Salaries for {payload.get('month')}"},
            {"account_id": payable_account.id, "debit": ZERO, "credit": amount,
             "memo": f"Salaries payable for {payload.get('month')}"},
        ],
        memo=f"Payroll {payload.get('month')} — {payload.get('employees')} staff",
        source_type="payroll_run",
        source_id=payload.get("run_id"),
        dedupe_key=f"gl:{event.dedupe_key or event.id}",
    )


async def post_expense(
    db: AsyncSession,
    *,
    expense_id: str,
    account_id: str,
    amount,
    paid_from: str,
    entry_date: date,
    memo: str,
    actor: User | None = None,
) -> Journal | None:
    """Expense recorded: the expense goes up, cash or bank goes down."""
    amount = money(amount)
    cash_account = await account_by_code(db, ACCOUNT_BANK if paid_from in ("bank", "cheque") else ACCOUNT_CASH)

    return await post(
        db,
        entry_date=entry_date,
        lines=[
            {"account_id": account_id, "debit": amount, "credit": ZERO, "memo": memo},
            {"account_id": cash_account.id, "debit": ZERO, "credit": amount, "memo": memo},
        ],
        memo=memo,
        source_type="expense",
        source_id=expense_id,
        dedupe_key=f"gl:expense:{expense_id}",
        actor=actor,
    )


# ─── Statements ───────────────────────────────────────────────────────────────

async def trial_balance(db: AsyncSession, *, upto: date | None = None) -> dict:
    """Every account with its balance. Debits must equal credits."""
    stmt = (
        select(
            GLAccount.id, GLAccount.code, GLAccount.name, GLAccount.account_type,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == GLAccount.id, isouter=True)
        .join(Journal, Journal.id == JournalLine.journal_id, isouter=True)
        .group_by(GLAccount.id, GLAccount.code, GLAccount.name, GLAccount.account_type)
        .order_by(GLAccount.code)
    )
    if upto:
        stmt = stmt.where((Journal.entry_date <= upto) | (Journal.id.is_(None)))

    result = await db.execute(stmt)
    rows = []
    total_debit = total_credit = ZERO

    for _id, code, name, account_type, debit, credit in result.all():
        debit, credit = money(debit), money(credit)
        if debit == ZERO and credit == ZERO:
            continue
        # Shown on its natural side, which is how an accountant reads it.
        balance = money(debit - credit) if account_type in DEBIT_NATURED else money(credit - debit)
        rows.append({
            "code": code, "name": name, "type": account_type,
            "debit": str(debit), "credit": str(credit), "balance": str(balance),
        })
        total_debit += debit
        total_credit += credit

    return {
        "rows": rows,
        "total_debit": str(total_debit),
        "total_credit": str(total_credit),
        "balanced": total_debit == total_credit,
    }


async def profit_and_loss(db: AsyncSession, *, from_date: date, to_date: date) -> dict:
    """Income less expenses for a period."""
    result = await db.execute(
        select(
            GLAccount.code, GLAccount.name, GLAccount.account_type,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == GLAccount.id)
        .join(Journal, Journal.id == JournalLine.journal_id)
        .where(
            GLAccount.account_type.in_((INCOME, EXPENSE)),
            Journal.entry_date >= from_date,
            Journal.entry_date <= to_date,
        )
        .group_by(GLAccount.code, GLAccount.name, GLAccount.account_type)
        .order_by(GLAccount.code)
    )

    income, expenses = [], []
    total_income = total_expense = ZERO
    for code, name, account_type, debit, credit in result.all():
        debit, credit = money(debit), money(credit)
        if account_type == INCOME:
            amount = money(credit - debit)
            income.append({"code": code, "name": name, "amount": str(amount)})
            total_income += amount
        else:
            amount = money(debit - credit)
            expenses.append({"code": code, "name": name, "amount": str(amount)})
            total_expense += amount

    return {
        "from": from_date.isoformat(), "to": to_date.isoformat(),
        "income": income, "expenses": expenses,
        "total_income": str(total_income),
        "total_expenses": str(total_expense),
        "surplus": str(money(total_income - total_expense)),
    }


async def balance_sheet(db: AsyncSession, *, upto: date) -> dict:
    """What the school owns, owes, and is worth."""
    result = await db.execute(
        select(
            GLAccount.code, GLAccount.name, GLAccount.account_type,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == GLAccount.id)
        .join(Journal, Journal.id == JournalLine.journal_id)
        .where(
            GLAccount.account_type.in_((ASSET, LIABILITY, EQUITY)),
            Journal.entry_date <= upto,
        )
        .group_by(GLAccount.code, GLAccount.name, GLAccount.account_type)
        .order_by(GLAccount.code)
    )

    assets, liabilities, equity = [], [], []
    total_assets = total_liabilities = total_equity = ZERO

    for code, name, account_type, debit, credit in result.all():
        debit, credit = money(debit), money(credit)
        if account_type == ASSET:
            amount = money(debit - credit)
            assets.append({"code": code, "name": name, "amount": str(amount)})
            total_assets += amount
        elif account_type == LIABILITY:
            amount = money(credit - debit)
            liabilities.append({"code": code, "name": name, "amount": str(amount)})
            total_liabilities += amount
        else:
            amount = money(credit - debit)
            equity.append({"code": code, "name": name, "amount": str(amount)})
            total_equity += amount

    # The year's surplus is equity that has not been closed out yet, so the
    # sheet balances during the year and not only after a year-end entry.
    year_start = date(upto.year if upto.month >= 4 else upto.year - 1, 4, 1)
    pl = await profit_and_loss(db, from_date=year_start, to_date=upto)
    surplus = money(Decimal(pl["surplus"]))

    return {
        "as_at": upto.isoformat(),
        "assets": assets, "total_assets": str(total_assets),
        "liabilities": liabilities, "total_liabilities": str(total_liabilities),
        "equity": equity, "total_equity": str(total_equity),
        "surplus_this_year": str(surplus),
        "balanced": total_assets == money(total_liabilities + total_equity + surplus),
    }


async def ledger_for_account(
    db: AsyncSession, *, account_id: str, from_date: date, to_date: date,
) -> dict:
    """Every movement on one account, with a running balance."""
    result = await db.execute(select(GLAccount).where(GLAccount.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountingError("That account was not found.")

    result = await db.execute(
        select(Journal, JournalLine)
        .join(JournalLine, JournalLine.journal_id == Journal.id)
        .where(
            JournalLine.account_id == account_id,
            Journal.entry_date >= from_date,
            Journal.entry_date <= to_date,
        )
        .order_by(Journal.entry_date, Journal.created_at)
    )

    entries = []
    balance = ZERO
    for journal, line in result.all():
        debit, credit = money(line.debit), money(line.credit)
        movement = money(debit - credit) if account.account_type in DEBIT_NATURED \
            else money(credit - debit)
        balance = money(balance + movement)
        entries.append({
            "date": journal.entry_date.isoformat(),
            "journal_no": journal.journal_no,
            "memo": line.memo or journal.memo,
            "debit": str(debit), "credit": str(credit),
            "balance": str(balance),
        })

    return {"account": account.to_dict(), "entries": entries, "closing_balance": str(balance)}
