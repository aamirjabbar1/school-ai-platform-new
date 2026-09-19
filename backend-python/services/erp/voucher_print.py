"""
Turning stored vouchers into the printed voucher.

`voucher_pdf` knows the layout; this knows where each number on it comes from,
and the two are separate because the layout is LSS's and the arithmetic is the
ledger's.

The totals follow the sample exactly:

    Tuition        8,085
    Taekwondo        200
    Total          8,060     = 8,285 − 525 discount + 300 late fine

so `Total` is what the parent hands over, after the discount and including the
fine that applies once the due date has passed. `Net Bal.` repeats it, less
anything already paid.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import SchoolClass, Section, StudentProfile
from models.erp_fees import (
    Voucher, VoucherLine, VoucherSettings,
)
from models.models import User
from services.erp import numbering, voucher_pdf
from services.erp.fees import ZERO, money

logger = logging.getLogger("agent")


DEFAULT_NOTE = (
    "Parents are requested to clear all dues before 10th, otherwise late fee "
    "will be charged as Rs.50/- per day after due date. Dues once paid are not "
    "refundable at all i.e, Tuition Fee, Admission Fee and Annual Fee."
)


async def settings(db: AsyncSession) -> VoucherSettings:
    """The one settings row, created with the school's own wording on first use."""
    result = await db.execute(select(VoucherSettings).limit(1))
    row = result.scalar_one_or_none()
    if row:
        return row

    row = VoucherSettings(
        school_name="Lahore School System",
        email="info@lss.edu.pk",
        website="www.lss.edu.pk",
        bank_name="BankIslami",
        bank_account="3087-000-6416-0001",
        campus_code="CAMPUS-02",
        post_to="POST TO CMD",
        bank_line="CAMPUS-02 / BANK ISLAMI / 3087-000-6416-0001 / All Over Pakistan",
        note=DEFAULT_NOTE,
        late_fine_per_day=Decimal("50"),
        valid_days_after_due=5,
        challan_pattern="{seq:09d}",
    )
    db.add(row)
    await db.flush()
    return row


def late_fine_for(
    *, due_date: date, valid_till: date | None, per_day: Decimal, as_at: date | None = None,
) -> Decimal:
    """What the fine will be if the voucher is paid at the last valid moment.

    The sample shows a fine of 300 on a voucher due on the 10th and valid till
    the 15th, at Rs.50/- per day — six days inclusive. It is printed when the
    voucher is issued, so a parent knows what late payment costs before they
    are late, not afterwards.
    """
    if valid_till is None or valid_till <= due_date:
        return ZERO
    days = (valid_till - due_date).days + 1
    return money(Decimal(days) * money(per_day))


async def voucher_data(db: AsyncSession, voucher: Voucher, config: VoucherSettings) -> dict:
    """Everything one printed copy needs."""
    result = await db.execute(select(User).where(User.id == voucher.student_user_id))
    student = result.scalar_one_or_none()

    result = await db.execute(
        select(StudentProfile).where(StudentProfile.user_id == voucher.student_user_id)
    )
    profile = result.scalar_one_or_none()

    result = await db.execute(
        select(VoucherLine).where(VoucherLine.voucher_id == voucher.id)
    )
    lines = list(result.scalars().all())

    class_label = ""
    if voucher.class_id:
        result = await db.execute(select(SchoolClass).where(SchoolClass.id == voucher.class_id))
        school_class = result.scalar_one_or_none()
        class_label = school_class.canonical_name if school_class else ""
    if voucher.section_id:
        result = await db.execute(select(Section).where(Section.id == voucher.section_id))
        section = result.scalar_one_or_none()
        if section:
            class_label = f"{class_label}-{section.name}" if class_label else section.name

    # "Child # 1" — which of this family's children the voucher belongs to,
    # counted in admission order so it does not move when a sibling joins.
    child_number = voucher.child_number
    if child_number is None and profile and profile.family_id:
        result = await db.execute(
            select(StudentProfile.user_id)
            .where(StudentProfile.family_id == profile.family_id)
            .order_by(StudentProfile.created_at)
        )
        siblings = [row[0] for row in result.all()]
        if voucher.student_user_id in siblings:
            child_number = siblings.index(voucher.student_user_id) + 1

    gross = money(voucher.gross)
    discount = money(voucher.concession)
    fine = money(voucher.late_fee) if money(voucher.late_fee) > ZERO else late_fine_for(
        due_date=voucher.due_date,
        valid_till=voucher.valid_till,
        per_day=config.late_fine_per_day,
    )
    previous = money(voucher.arrears)
    paid = money(voucher.paid)

    total = money(gross - discount + fine)
    net_balance = money(total + previous - paid)

    months = voucher.month.strftime("%b %Y") if voucher.month else ""

    return {
        "challan_no": voucher.challan_no or voucher.voucher_no,
        "kuickpay_id": voucher.kuickpay_id or "",
        # The `or ""` has to wrap the whole conditional: a father's name is
        # nullable, and `x if s else "" or ""` binds the fallback to the else
        # branch, so a missing father crashed the print rather than printing
        # an empty box.
        "student_name": ((student.name if student else "") or "").upper(),
        "father_name": ((student.father_name if student else "") or "").upper(),
        "issue_date": voucher.issue_date,
        "due_date": voucher.due_date,
        "valid_till": voucher.valid_till,
        "registration_no": (profile.registration_no if profile else None)
                           or (student.login_id if student else ""),
        "gr_no": profile.gr_no if profile else "",
        "class_name": class_label,
        "child_number": child_number,
        "months": months,
        "lines": [{"head": line.head_name or "", "amount": line.net} for line in lines],
        "total": total,
        "late_fine": fine,
        "discount": discount,
        "previous_balance": previous,
        "paid": paid,
        "net_balance": net_balance,
    }


async def ensure_print_numbers(db: AsyncSession, voucher: Voucher, config: VoucherSettings) -> None:
    """Give a voucher its challan number and valid-till date the first time it
    is printed, and never again — a reprint must be the same piece of paper."""
    if voucher.valid_till is None and voucher.due_date:
        voucher.valid_till = voucher.due_date + timedelta(days=config.valid_days_after_due or 0)

    if not voucher.challan_no:
        try:
            voucher.challan_no = await numbering.allocate_one(db, numbering.SCOPE_CHALLAN)
        except Exception as exc:                     # noqa: BLE001
            logger.warning("voucher: challan number not allocated: %s", exc)
            voucher.challan_no = voucher.voucher_no

    if not voucher.kuickpay_id and config.kuickpay_prefix:
        # KuickPay quotes one id per voucher. Until LSS confirms how theirs is
        # composed, it is the configured institute prefix followed by the
        # challan's digits — visible, stable, and easy to change.
        digits = "".join(c for c in (voucher.challan_no or "") if c.isdigit())
        voucher.kuickpay_id = f"{config.kuickpay_prefix}{digits}"[-10:]


async def render_vouchers(
    db: AsyncSession, *, voucher_ids: list[str],
) -> bytes:
    """The printable PDF for one or many vouchers, three copies each."""
    config = await settings(db)

    result = await db.execute(
        select(Voucher).where(Voucher.id.in_(voucher_ids)).order_by(Voucher.voucher_no)
    )
    vouchers = list(result.scalars().all())
    if not vouchers:
        raise ValueError("No vouchers to print.")

    pages = []
    for voucher in vouchers:
        await ensure_print_numbers(db, voucher, config)
        pages.append(await voucher_data(db, voucher, config))

    await db.commit()
    return voucher_pdf.render(pages, config.to_dict())
