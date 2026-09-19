"""
The fee engine (ERP phase 4).

Three operations carry the module, and each has one property that matters more
than anything else about it:

    generate_vouchers  — re-runnable. A month already billed is skipped, never
                         billed twice, so pressing the button again is safe.
    receive_payment    — idempotent on the bank's reference. A bank file
                         imported twice must not take a parent's money twice.
    resolve_concession — reads family and student together, so adding a third
                         child re-evaluates the sibling discount without anyone
                         remembering to.

All money is `Decimal`, quantised to two places at every boundary. Not because
rounding is hard, but because a statement that is off by a paisa costs more
trust than the whole module earns.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import Enrollment, Family, SchoolClass, Section, StudentProfile
from models.erp_fees import (
    CONCESSION_FIXED, CONCESSION_PERCENT, HEAD_ONE_TIME, OPEN_VOUCHER_STATES,
    VOUCHER_CANCELLED, VOUCHER_PAID, VOUCHER_PARTIAL, VOUCHER_UNPAID,
    Concession, FeeHead, FeeStructure, LedgerEntry, Receipt, StudentFeeAccount,
    StudentFeeOverride, Voucher, VoucherLine, VoucherRun,
)
from models.models import User
from services.erp import audit, events, numbering
from services.erp.setup import current_session

logger = logging.getLogger("agent")

ZERO = Decimal("0.00")


class FeeError(RuntimeError):
    """Something the accounts office needs to fix, phrased for them."""


def money(value) -> Decimal:
    """Two decimal places, half-up — the way a cashier rounds."""
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def month_start(value: date) -> date:
    return value.replace(day=1)


# ─── Concessions ──────────────────────────────────────────────────────────────

async def active_concessions(
    db: AsyncSession, *, student_user_id: str, family_id: str | None, on_date: date,
) -> list[Concession]:
    """Every discount in force for this child on this date.

    Family-level and student-level together: a sibling discount lives on the
    family, a merit scholarship on the child, and a child can hold both.
    """
    conditions = [Concession.student_user_id == student_user_id]
    if family_id:
        conditions.append(Concession.family_id == family_id)

    result = await db.execute(
        select(Concession).where(
            Concession.is_active.is_(True),
            or_(*conditions),
            or_(Concession.effective_from.is_(None), Concession.effective_from <= on_date),
            or_(Concession.effective_to.is_(None), Concession.effective_to >= on_date),
        )
    )
    return list(result.scalars().all())


def concession_for_head(concessions: list[Concession], head_id: str, amount: Decimal) -> Decimal:
    """What comes off one line.

    Concessions add up, and the total is capped at the amount charged — a
    hundred percent discount plus a fixed one cannot produce a negative fee
    that the school then appears to owe the parent.
    """
    total = ZERO
    for concession in concessions:
        if concession.head_id not in (None, head_id):
            continue
        if concession.concession_type == CONCESSION_PERCENT:
            total += money(amount * money(concession.value) / Decimal("100"))
        elif concession.concession_type == CONCESSION_FIXED:
            total += money(concession.value)
    return min(money(total), money(amount))


# ─── Voucher generation ───────────────────────────────────────────────────────

async def _student_rows(db, session_id, class_id, section_id):
    stmt = (
        select(User, StudentProfile, Enrollment)
        .join(Enrollment, Enrollment.student_user_id == User.id)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(
            Enrollment.session_id == session_id,
            Enrollment.status == "enrolled",
            User.is_active.is_(True),
        )
        .order_by(User.name)
    )
    if class_id:
        stmt = stmt.where(Enrollment.class_id == class_id)
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)
    result = await db.execute(stmt)
    return result.all()


async def generate_vouchers(
    db: AsyncSession,
    *,
    month: date,
    class_id: str | None = None,
    section_id: str | None = None,
    due_days: int = 10,
    actor: User | None = None,
) -> dict:
    """Bill a month for a class, a section, or the whole school.

    Re-runnable by design: a child already billed for this month is skipped.
    The office will press this twice — once because they are not sure it
    worked, and once next month by mistake.
    """
    session = await current_session(db)
    if session is None:
        raise FeeError("There is no active academic session.")

    month = month_start(month)
    rows = await _student_rows(db, session.id, class_id, section_id)
    if not rows:
        raise FeeError("No students found for that class or section.")

    # Everything the loop needs, fetched once.
    result = await db.execute(select(FeeHead).where(FeeHead.is_active.is_(True)).order_by(FeeHead.sort_order))
    heads = {h.id: h for h in result.scalars().all()}
    if not heads:
        raise FeeError("No fee heads are set up yet. Add them under Fee setup first.")

    result = await db.execute(select(FeeStructure).where(FeeStructure.session_id == session.id))
    structures: dict[tuple[str, str], Decimal] = {
        (s.class_id, s.head_id): money(s.amount) for s in result.scalars().all()
    }

    result = await db.execute(
        select(StudentFeeOverride).where(StudentFeeOverride.session_id == session.id)
    )
    overrides: dict[tuple[str, str], Decimal] = {
        (o.student_user_id, o.head_id): money(o.amount) for o in result.scalars().all()
    }

    student_ids = [s.id for s, _, _ in rows]
    result = await db.execute(
        select(Voucher.student_user_id).where(
            Voucher.session_id == session.id,
            Voucher.month == month,
            Voucher.status != VOUCHER_CANCELLED,
        )
    )
    already_billed = {row[0] for row in result.all()}

    run = VoucherRun(
        session_id=session.id, month=month, class_id=class_id, section_id=section_id,
        run_by=actor.id if actor else None,
    )
    db.add(run)
    # Flushed so the run has its id before anything reports it — the id is a
    # column default, so it does not exist until the row reaches the database.
    await db.flush()

    created = skipped = 0
    total_amount = ZERO
    issue_date = date.today()
    due_date = issue_date + timedelta(days=due_days)

    # One block of numbers for the whole run, rather than a row lock per child.
    to_bill = [r for r in rows if r[0].id not in already_billed]
    numbers = await numbering.allocate(
        db, numbering.SCOPE_VOUCHER, count=len(to_bill), session_name=session.name,
    ) if to_bill else []

    for (student, profile, enrollment), voucher_no in zip(to_bill, numbers):
        concessions = await active_concessions(
            db,
            student_user_id=student.id,
            family_id=profile.family_id if profile else None,
            on_date=month,
        )

        voucher = Voucher(
            voucher_no=voucher_no,
            student_user_id=student.id,
            session_id=session.id,
            class_id=enrollment.class_id,
            section_id=enrollment.section_id,
            month=month,
            issue_date=issue_date,
            due_date=due_date,
            generated_by=actor.id if actor else None,
        )
        db.add(voucher)
        await db.flush()

        gross = concession_total = ZERO
        for head in heads.values():
            # A one-time head is not billed every month. It reaches a voucher
            # through a student override, which is how admission fee and
            # security land on the first bill only.
            amount = overrides.get((student.id, head.id))
            if amount is None:
                if head.head_type == HEAD_ONE_TIME:
                    continue
                amount = structures.get((enrollment.class_id, head.id))
            if amount is None or amount <= ZERO:
                continue

            discount = concession_for_head(concessions, head.id, amount)
            net = money(amount - discount)
            db.add(VoucherLine(
                voucher_id=voucher.id, head_id=head.id, head_name=head.name,
                amount=amount, concession=discount, net=net,
            ))
            gross += amount
            concession_total += discount

        account = await _account_for(db, student.id)
        arrears = money(account.outstanding)

        voucher.gross = money(gross)
        voucher.concession = money(concession_total)
        # A snapshot for the printed voucher — "you also owe this much from
        # before". It is deliberately *not* added to `payable`: summing three
        # months of payable would then count February's unpaid fee three times.
        voucher.arrears = arrears
        voucher.payable = money(gross - concession_total)

        # An empty voucher helps nobody — it is a bill for zero that someone
        # has to explain. A child with no fee structure yet simply is not
        # billed, and appears on the exceptions list instead.
        if voucher.gross <= ZERO and arrears <= ZERO:
            await db.delete(voucher)
            skipped += 1
            continue

        await _post_ledger(
            db, student_user_id=student.id, entry_date=issue_date,
            description=f"Fee for {month.strftime('%B %Y')} ({voucher.voucher_no})",
            debit=voucher.payable, credit=ZERO,
            source_type="voucher", source_id=voucher.id,
        )
        await _recalculate_account(db, student.id)

        created += 1
        total_amount += voucher.payable

    skipped += len(rows) - len(to_bill)
    run.created_count = created
    run.skipped_count = skipped
    run.total_amount = money(total_amount)

    audit.record(
        db, actor=actor, entity_type="fee_voucher", action="generated",
        entity_id=run.id,
        new_value={"month": month.isoformat(), "created": created,
                   "skipped": skipped, "total": str(money(total_amount))},
    )
    return {"run_id": run.id, "month": month.isoformat(), "created": created,
            "skipped": skipped, "total_amount": str(money(total_amount))}


# ─── Payment ──────────────────────────────────────────────────────────────────

async def receive_payment(
    db: AsyncSession,
    *,
    student_user_id: str,
    amount,
    method: str,
    voucher_id: str | None = None,
    bank_reference: str | None = None,
    received_on: date | None = None,
    note: str | None = None,
    actor: User | None = None,
) -> dict:
    """Take a payment. Safe to call twice with the same bank reference.

    Overpayment is kept as an advance rather than refused — a parent who pays a
    round figure should not be turned away at the counter — and it comes off
    the next voucher automatically as arrears go negative.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise FeeError("The amount must be more than zero.")

    if bank_reference:
        result = await db.execute(
            select(Receipt).where(Receipt.bank_reference == bank_reference)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # Not an error. The same payment arriving twice is the normal
            # consequence of a retry or a re-imported bank file.
            return {**existing.to_dict(), "duplicate": True}

    result = await db.execute(select(User).where(User.id == student_user_id))
    student = result.scalar_one_or_none()
    if student is None:
        raise FeeError("That student was not found.")

    received_on = received_on or date.today()
    receipt_no = await numbering.allocate_one(db, numbering.SCOPE_RECEIPT)

    receipt = Receipt(
        receipt_no=receipt_no,
        student_user_id=student_user_id,
        voucher_id=voucher_id,
        amount=amount,
        method=method,
        bank_reference=bank_reference,
        received_on=received_on,
        received_by=actor.id if actor else None,
        note=note,
    )
    db.add(receipt)
    await db.flush()

    await _apply_to_vouchers(db, student_user_id, amount, preferred_voucher_id=voucher_id)

    await _post_ledger(
        db, student_user_id=student_user_id, entry_date=received_on,
        description=f"Payment received ({receipt_no})",
        debit=ZERO, credit=amount,
        source_type="receipt", source_id=receipt.id,
    )
    account = await _recalculate_account(db, student_user_id)
    account.last_payment_on = received_on
    account.last_payment_amount = amount

    events.emit(
        db, events.PAYMENT_RECEIVED,
        {"student_user_id": student_user_id, "receipt_id": receipt.id,
         "amount": str(amount), "method": method},
        dedupe_key=f"payment:{receipt.id}",
    )
    audit.record(
        db, actor=actor, entity_type="fee_receipt", action="received",
        entity_id=receipt.id,
        new_value={"student": student.name, "amount": str(amount), "method": method,
                   "receipt_no": receipt_no},
    )

    return {**receipt.to_dict(), "duplicate": False,
            "outstanding_after": str(account.outstanding)}


async def _apply_to_vouchers(db, student_user_id, amount, *, preferred_voucher_id=None):
    """Settle the oldest bills first, which is what a parent expects and what
    keeps the aging report honest."""
    remaining = money(amount)

    stmt = (
        select(Voucher)
        .where(
            Voucher.student_user_id == student_user_id,
            Voucher.status.in_(OPEN_VOUCHER_STATES),
        )
        .order_by(Voucher.month)
    )
    result = await db.execute(stmt)
    vouchers = list(result.scalars().all())

    if preferred_voucher_id:
        vouchers.sort(key=lambda v: (v.id != preferred_voucher_id, v.month))

    for voucher in vouchers:
        if remaining <= ZERO:
            break
        owed = money(voucher.payable - voucher.paid)
        if owed <= ZERO:
            voucher.status = VOUCHER_PAID
            continue
        applied = min(owed, remaining)
        voucher.paid = money(voucher.paid + applied)
        remaining = money(remaining - applied)
        voucher.status = VOUCHER_PAID if voucher.paid >= voucher.payable else VOUCHER_PARTIAL

    return remaining


async def reverse_receipt(
    db: AsyncSession, *, receipt_id: str, reason: str, actor: User | None = None,
) -> dict:
    """Undo a payment without deleting it.

    A bounced cheque, a payment posted to the wrong child. The original stays
    exactly where it is and a negative receipt sits beside it, because the
    question afterwards is always "what happened", not "what is the total now".
    """
    result = await db.execute(select(Receipt).where(Receipt.id == receipt_id))
    original = result.scalar_one_or_none()
    if original is None:
        raise FeeError("That receipt was not found.")
    if original.amount < ZERO:
        raise FeeError("That is already a reversal.")

    result = await db.execute(select(Receipt).where(Receipt.reversal_of == receipt_id))
    if result.scalar_one_or_none():
        raise FeeError("That receipt has already been reversed.")

    receipt_no = await numbering.allocate_one(db, numbering.SCOPE_RECEIPT)
    reversal = Receipt(
        receipt_no=receipt_no,
        student_user_id=original.student_user_id,
        voucher_id=original.voucher_id,
        amount=money(-original.amount),
        method=original.method,
        received_on=date.today(),
        received_by=actor.id if actor else None,
        reversal_of=original.id,
        reversal_reason=reason,
    )
    db.add(reversal)
    await db.flush()

    # Unwind the settlement, newest first.
    result = await db.execute(
        select(Voucher)
        .where(Voucher.student_user_id == original.student_user_id, Voucher.paid > 0)
        .order_by(Voucher.month.desc())
    )
    remaining = money(original.amount)
    for voucher in result.scalars().all():
        if remaining <= ZERO:
            break
        taken = min(money(voucher.paid), remaining)
        voucher.paid = money(voucher.paid - taken)
        remaining = money(remaining - taken)
        voucher.status = VOUCHER_UNPAID if voucher.paid <= ZERO else (
            VOUCHER_PAID if voucher.paid >= voucher.payable else VOUCHER_PARTIAL
        )

    await _post_ledger(
        db, student_user_id=original.student_user_id, entry_date=date.today(),
        description=f"Payment reversed ({receipt_no}) — {reason}",
        debit=money(original.amount), credit=ZERO,
        source_type="receipt", source_id=reversal.id,
    )
    await _recalculate_account(db, original.student_user_id)

    audit.record(
        db, actor=actor, entity_type="fee_receipt", action="reversed",
        entity_id=original.id,
        old_value={"receipt_no": original.receipt_no, "amount": str(original.amount)},
        new_value={"reversal_no": receipt_no}, reason=reason,
    )
    return reversal.to_dict()


# ─── Ledger and account ───────────────────────────────────────────────────────

async def _post_ledger(db, *, student_user_id, entry_date, description, debit, credit,
                       source_type, source_id):
    result = await db.execute(
        select(LedgerEntry.balance)
        .where(LedgerEntry.student_user_id == student_user_id)
        .order_by(LedgerEntry.entry_date.desc(), LedgerEntry.created_at.desc())
        .limit(1)
    )
    previous = money(result.scalar_one_or_none() or ZERO)
    balance = money(previous + money(debit) - money(credit))

    db.add(LedgerEntry(
        student_user_id=student_user_id, entry_date=entry_date,
        description=description, debit=money(debit), credit=money(credit),
        balance=balance, source_type=source_type, source_id=source_id,
    ))
    return balance


async def _account_for(db, student_user_id) -> StudentFeeAccount:
    result = await db.execute(
        select(StudentFeeAccount).where(StudentFeeAccount.student_user_id == student_user_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = StudentFeeAccount(student_user_id=student_user_id)
        db.add(account)
        await db.flush()
    return account


async def _recalculate_account(db, student_user_id) -> StudentFeeAccount:
    """Recompute from the vouchers and receipts rather than nudging a counter.

    Slower per payment, and still correct after a reversal, a cancellation or a
    hand correction — which three separate increments would not be.

    `payable` holds one month's charge, so summing it is the total ever billed;
    receipts are the total ever received; the difference is the position. The
    ledger's closing balance equals this by construction.
    """
    account = await _account_for(db, student_user_id)

    result = await db.execute(
        select(func.coalesce(func.sum(Voucher.payable), 0)).where(
            Voucher.student_user_id == student_user_id,
            Voucher.status != VOUCHER_CANCELLED,
        )
    )
    billed = money(result.scalar_one())

    # Receipts, not the sum of voucher.paid: an overpayment is real money that
    # was received even though no voucher claimed it.
    result = await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0))
        .where(Receipt.student_user_id == student_user_id)
    )
    received = money(result.scalar_one())

    position = money(billed - received)
    account.total_billed = billed
    account.total_paid = received
    account.outstanding = position if position > ZERO else ZERO
    account.advance = money(-position) if position < ZERO else ZERO

    result = await db.execute(
        select(func.min(Voucher.month), func.count())
        .where(
            Voucher.student_user_id == student_user_id,
            Voucher.status.in_(OPEN_VOUCHER_STATES),
        )
    )
    oldest, unpaid_count = result.one()
    account.oldest_unpaid_month = oldest
    account.unpaid_months = int(unpaid_count or 0)
    return account


async def student_ledger(db: AsyncSession, *, student_user_id: str) -> dict:
    result = await db.execute(
        select(LedgerEntry)
        .where(LedgerEntry.student_user_id == student_user_id)
        .order_by(LedgerEntry.entry_date, LedgerEntry.created_at)
    )
    entries = [e.to_dict() for e in result.scalars().all()]
    account = await _account_for(db, student_user_id)
    return {"account": account.to_dict(), "entries": entries}


# ─── Defaulters ───────────────────────────────────────────────────────────────

AGING_BUCKETS = ((0, 30), (31, 60), (61, 90), (91, 180), (181, 99999))


def _bucket_for(days: int) -> str:
    for low, high in AGING_BUCKETS:
        if low <= days <= high:
            return f"{low}-{high}" if high < 99999 else "180+"
    return "0-30"


async def defaulters(
    db: AsyncSession,
    *,
    class_id: str | None = None,
    section_id: str | None = None,
    min_amount: Decimal | None = None,
    include_inactive: bool = False,
) -> dict:
    """Defaulter List — All (Active).

    One indexed scan. The specification wants the whole school with minimal
    clicks, and it is the report the office runs most often, so it is built to
    return while somebody is still looking at the screen.
    """
    session = await current_session(db)
    if session is None:
        return {"total": 0, "students": [], "total_outstanding": "0.00"}

    stmt = (
        select(User, StudentProfile, StudentFeeAccount, Enrollment, SchoolClass, Section)
        .join(StudentFeeAccount, StudentFeeAccount.student_user_id == User.id)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .join(
            Enrollment,
            and_(Enrollment.student_user_id == User.id, Enrollment.session_id == session.id),
            isouter=True,
        )
        .join(SchoolClass, SchoolClass.id == Enrollment.class_id, isouter=True)
        .join(Section, Section.id == Enrollment.section_id, isouter=True)
        .where(StudentFeeAccount.outstanding > 0)
    )
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    if class_id:
        stmt = stmt.where(Enrollment.class_id == class_id)
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)
    if min_amount is not None:
        stmt = stmt.where(StudentFeeAccount.outstanding >= money(min_amount))

    result = await db.execute(stmt.order_by(StudentFeeAccount.outstanding.desc()))
    rows = result.all()

    today = date.today()
    students = []
    total = ZERO
    for student, profile, account, enrollment, school_class, section in rows:
        days = (today - account.oldest_unpaid_month).days if account.oldest_unpaid_month else 0
        students.append({
            "id": student.id,
            "name": student.name,
            "father_name": student.father_name,
            "gr_no": profile.gr_no if profile else None,
            "admission_no": profile.admission_no if profile else None,
            "family_id": profile.family_id if profile else None,
            "class_name": school_class.canonical_name if school_class else student.class_name,
            "section_name": section.name if section else student.section,
            "outstanding": str(account.outstanding),
            "unpaid_months": account.unpaid_months,
            "oldest_unpaid_month": account.oldest_unpaid_month.isoformat() if account.oldest_unpaid_month else None,
            "days_overdue": max(days, 0),
            "aging": _bucket_for(max(days, 0)),
            "last_payment_on": account.last_payment_on.isoformat() if account.last_payment_on else None,
            "last_payment_amount": str(account.last_payment_amount) if account.last_payment_amount else None,
        })
        total += account.outstanding

    buckets: dict[str, int] = {}
    for entry in students:
        buckets[entry["aging"]] = buckets.get(entry["aging"], 0) + 1

    return {
        "total": len(students),
        "total_outstanding": str(money(total)),
        "aging": buckets,
        "students": students,
    }


async def collection_summary(db: AsyncSession, *, on_date: date | None = None) -> dict:
    """What came in today, and what is still out there."""
    target = on_date or date.today()

    result = await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0), func.count())
        .where(Receipt.received_on == target)
    )
    today_amount, today_count = result.one()

    result = await db.execute(
        select(func.coalesce(func.sum(StudentFeeAccount.outstanding), 0), func.count())
        .select_from(StudentFeeAccount)
        .join(User, User.id == StudentFeeAccount.student_user_id)
        .where(StudentFeeAccount.outstanding > 0, User.is_active.is_(True))
    )
    outstanding, defaulter_count = result.one()

    result = await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0))
        .where(Receipt.received_on >= month_start(target))
    )
    month_amount = result.scalar_one()

    return {
        "date": target.isoformat(),
        "collected_today": str(money(today_amount)),
        "receipts_today": int(today_count),
        "collected_this_month": str(money(month_amount)),
        "outstanding": str(money(outstanding)),
        "defaulters": int(defaulter_count),
    }
