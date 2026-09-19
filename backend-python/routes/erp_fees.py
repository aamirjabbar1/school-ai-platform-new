"""
Fees API (ERP phase 4).

Four screens' worth of endpoints: set up what the school charges, generate a
month, take money at the counter, and chase what is owed. The engine in
`services/erp/fees.py` does the arithmetic; this layer decides who may ask.

Collecting money and setting fee policy are deliberately different permissions.
A cashier takes payments all day and can change nothing about what anyone owes.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.erp import SchoolClass, Section, StudentProfile
from models.erp_fees import (
    CONCESSION_CATEGORIES, OPEN_VOUCHER_STATES, VOUCHER_CANCELLED,
    Concession, FeeHead, FeeStructure, Receipt, StudentFeeAccount,
    Voucher, VoucherLine,
)
from models.models import User
from routes.erp import erp_available
from services.erp import audit, fees as fee_service
from services.erp.fees import FeeError, money
from services.erp.permissions import permissions_for, require_permission
from services.erp.setup import current_session

router = APIRouter(prefix="/erp/fees", tags=["erp-fees"])


def _fail(exc: FeeError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ─── Fee heads ────────────────────────────────────────────────────────────────

class HeadRequest(BaseModel):
    code: str
    name: str
    head_type: str = "recurring"
    is_refundable: bool = False
    sort_order: int = 0


@router.get("/heads")
async def list_heads(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FeeHead).order_by(FeeHead.sort_order, FeeHead.name))
    return [h.to_dict() for h in result.scalars().all()]


@router.post("/heads")
async def create_head(
    body: HeadRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.structure")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FeeHead).where(FeeHead.code == body.code.strip()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"A fee head with code {body.code} already exists.")

    head = FeeHead(**body.model_dump())
    head.code = head.code.strip()
    db.add(head)
    await db.flush()
    audit.record(db, actor=user, entity_type="fee_head", action="created",
                 entity_id=head.id, new_value=head.to_dict())
    await db.commit()
    return head.to_dict()


@router.put("/heads/{head_id}")
async def update_head(
    head_id: str,
    body: HeadRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.structure")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FeeHead).where(FeeHead.id == head_id))
    head = result.scalar_one_or_none()
    if not head:
        raise HTTPException(status_code=404, detail="Fee head not found")

    before = head.to_dict()
    for field, value in body.model_dump().items():
        setattr(head, field, value)
    old, new = audit.diff(before, head.to_dict())
    if new:
        audit.record(db, actor=user, entity_type="fee_head", action="updated",
                     entity_id=head.id, old_value=old, new_value=new)
    await db.commit()
    return head.to_dict()


# ─── Fee structure ────────────────────────────────────────────────────────────

@router.get("/structure")
async def get_structure(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
):
    """The whole fee table at once: classes down the side, heads across.

    One call, because this is a grid — fetching it row by row would be a
    request per class for a screen that is useless until all of it has arrived.
    """
    session = await current_session(db)
    if session is None:
        raise HTTPException(status_code=400, detail="There is no active academic session.")

    result = await db.execute(select(SchoolClass).order_by(SchoolClass.sort_order))
    classes = [c.to_dict() for c in result.scalars().all()]
    result = await db.execute(
        select(FeeHead).where(FeeHead.is_active.is_(True)).order_by(FeeHead.sort_order, FeeHead.name)
    )
    heads = [h.to_dict() for h in result.scalars().all()]

    result = await db.execute(select(FeeStructure).where(FeeStructure.session_id == session.id))
    amounts = {f"{s.class_id}:{s.head_id}": str(s.amount) for s in result.scalars().all()}

    return {"session": session.to_dict(), "classes": classes, "heads": heads, "amounts": amounts}


class StructureEntry(BaseModel):
    class_id: str
    head_id: str
    amount: Decimal


class StructureRequest(BaseModel):
    entries: list[StructureEntry]


@router.put("/structure")
async def set_structure(
    body: StructureRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.structure")),
    db: AsyncSession = Depends(get_db),
):
    """Save the grid. Only what changed is written, and each change is audited."""
    session = await current_session(db)
    if session is None:
        raise HTTPException(status_code=400, detail="There is no active academic session.")

    result = await db.execute(select(FeeStructure).where(FeeStructure.session_id == session.id))
    existing = {(s.class_id, s.head_id): s for s in result.scalars().all()}

    changed = 0
    for entry in body.entries:
        amount = money(entry.amount)
        if amount < 0:
            raise HTTPException(status_code=400, detail="A fee cannot be negative.")

        row = existing.get((entry.class_id, entry.head_id))
        if row is None:
            if amount == 0:
                continue
            db.add(FeeStructure(
                session_id=session.id, class_id=entry.class_id,
                head_id=entry.head_id, amount=amount, effective_from=date.today(),
            ))
            changed += 1
        elif money(row.amount) != amount:
            audit.record(
                db, actor=user, entity_type="fee_structure", action="updated",
                entity_id=row.id,
                old_value={"amount": str(row.amount)}, new_value={"amount": str(amount)},
            )
            row.amount = amount
            changed += 1

    await db.commit()
    return {"changed": changed}


class IncreaseRequest(BaseModel):
    percent: Decimal
    class_id: str | None = None
    head_id: str | None = None
    preview_only: bool = True


@router.post("/structure/increase")
async def apply_increase(
    body: IncreaseRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.structure")),
    db: AsyncSession = Depends(get_db),
):
    """An approved fee rise (§B3).

    Always previewed first: the old figure, the new figure, and how many
    children it lands on. Applying a percentage across a school without seeing
    that first is how a school discovers it has doubled its nursery fee.
    """
    session = await current_session(db)
    if session is None:
        raise HTTPException(status_code=400, detail="There is no active academic session.")

    stmt = select(FeeStructure).where(FeeStructure.session_id == session.id)
    if body.class_id:
        stmt = stmt.where(FeeStructure.class_id == body.class_id)
    if body.head_id:
        stmt = stmt.where(FeeStructure.head_id == body.head_id)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    result = await db.execute(select(SchoolClass))
    class_names = {c.id: c.canonical_name for c in result.scalars().all()}
    result = await db.execute(select(FeeHead))
    head_names = {h.id: h.name for h in result.scalars().all()}

    changes = []
    for row in rows:
        old_amount = money(row.amount)
        new_amount = money(old_amount * (Decimal("100") + money(body.percent)) / Decimal("100"))
        if new_amount == old_amount:
            continue
        changes.append({
            "structure_id": row.id,
            "class_name": class_names.get(row.class_id),
            "head_name": head_names.get(row.head_id),
            "old": str(old_amount), "new": str(new_amount),
            "increase": str(money(new_amount - old_amount)),
        })

    if body.preview_only:
        return {"preview": True, "percent": str(body.percent), "changes": changes}

    by_id = {r.id: r for r in rows}
    for change in changes:
        row = by_id[change["structure_id"]]
        row.amount = money(Decimal(change["new"]))
    audit.record(
        db, actor=user, entity_type="fee_structure", action="increased",
        new_value={"percent": str(body.percent), "rows": len(changes)},
    )
    await db.commit()
    return {"preview": False, "applied": len(changes)}


# ─── Concessions ──────────────────────────────────────────────────────────────

class ConcessionRequest(BaseModel):
    scope: str = "student"
    student_user_id: str | None = None
    family_id: str | None = None
    head_id: str | None = None
    concession_type: str = "percent"
    value: Decimal
    category: str = "other"
    effective_from: date | None = None
    effective_to: date | None = None
    reason: str | None = None


@router.get("/concessions")
async def list_concessions(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
    student_user_id: str | None = None,
    family_id: str | None = None,
):
    stmt = select(Concession).where(Concession.is_active.is_(True))
    if student_user_id:
        stmt = stmt.where(Concession.student_user_id == student_user_id)
    if family_id:
        stmt = stmt.where(Concession.family_id == family_id)
    result = await db.execute(stmt.order_by(Concession.created_at.desc()))
    return {"categories": list(CONCESSION_CATEGORIES),
            "concessions": [c.to_dict() for c in result.scalars().all()]}


@router.post("/concessions")
async def create_concession(
    body: ConcessionRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.concession")),
    db: AsyncSession = Depends(get_db),
):
    if body.scope == "student" and not body.student_user_id:
        raise HTTPException(status_code=400, detail="Choose a student for a student concession.")
    if body.scope == "family" and not body.family_id:
        raise HTTPException(status_code=400, detail="Choose a family for a family concession.")
    if body.concession_type == "percent" and not (0 < body.value <= 100):
        raise HTTPException(status_code=400, detail="A percentage discount must be between 1 and 100.")
    if body.category not in CONCESSION_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown concession category: {body.category}")

    concession = Concession(**body.model_dump(), approved_by=user.id)
    db.add(concession)
    await db.flush()
    audit.record(db, actor=user, entity_type="fee_concession", action="granted",
                 entity_id=concession.id, new_value=concession.to_dict(),
                 reason=body.reason)
    await db.commit()
    return concession.to_dict()


@router.delete("/concessions/{concession_id}")
async def end_concession(
    concession_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.concession")),
    db: AsyncSession = Depends(get_db),
):
    """Ends it from today. The record stays, because next year somebody will
    ask why this child paid less in March."""
    result = await db.execute(select(Concession).where(Concession.id == concession_id))
    concession = result.scalar_one_or_none()
    if not concession:
        raise HTTPException(status_code=404, detail="Concession not found")

    concession.is_active = False
    concession.effective_to = date.today()
    audit.record(db, actor=user, entity_type="fee_concession", action="ended",
                 entity_id=concession_id, old_value=concession.to_dict())
    await db.commit()
    return {"message": "Concession ended"}


# ─── Vouchers ─────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    month: date
    class_id: str | None = None
    section_id: str | None = None
    due_days: int = 10


@router.post("/vouchers/generate")
async def generate(
    body: GenerateRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.voucher")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await fee_service.generate_vouchers(
            db, month=body.month, class_id=body.class_id,
            section_id=body.section_id, due_days=body.due_days, actor=user,
        )
    except FeeError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return result


@router.get("/vouchers")
async def list_vouchers(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
    student_user_id: str | None = None,
    class_id: str | None = None,
    month: date | None = None,
    status: str | None = None,
    limit: int = Query(100, le=500),
):
    stmt = select(Voucher, User).join(User, User.id == Voucher.student_user_id)
    if student_user_id:
        stmt = stmt.where(Voucher.student_user_id == student_user_id)
    if class_id:
        stmt = stmt.where(Voucher.class_id == class_id)
    if month:
        stmt = stmt.where(Voucher.month == fee_service.month_start(month))
    if status == "open":
        stmt = stmt.where(Voucher.status.in_(OPEN_VOUCHER_STATES))
    elif status:
        stmt = stmt.where(Voucher.status == status)

    result = await db.execute(stmt.order_by(Voucher.month.desc(), User.name).limit(limit))
    return {
        "vouchers": [
            {**voucher.to_dict(), "student_name": student.name}
            for voucher, student in result.all()
        ]
    }


@router.get("/vouchers/{voucher_id}")
async def get_voucher(
    voucher_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
):
    """One voucher, with the breakdown a parent reads."""
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    result = await db.execute(select(VoucherLine).where(VoucherLine.voucher_id == voucher_id))
    lines = [line.to_dict() for line in result.scalars().all()]

    result = await db.execute(select(User).where(User.id == voucher.student_user_id))
    student = result.scalar_one_or_none()
    result = await db.execute(
        select(StudentProfile).where(StudentProfile.user_id == voucher.student_user_id)
    )
    profile = result.scalar_one_or_none()
    result = await db.execute(select(SchoolClass).where(SchoolClass.id == voucher.class_id))
    school_class = result.scalar_one_or_none()

    return {
        **voucher.to_dict(),
        "lines": lines,
        "student": {
            "id": student.id if student else None,
            "name": student.name if student else None,
            "father_name": student.father_name if student else None,
            "gr_no": profile.gr_no if profile else None,
            "class_name": school_class.canonical_name if school_class else None,
        },
    }


class CancelRequest(BaseModel):
    reason: str


@router.post("/vouchers/{voucher_id}/cancel")
async def cancel_voucher(
    voucher_id: str,
    body: CancelRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.structure")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    if money(voucher.paid) > 0:
        raise HTTPException(
            status_code=400,
            detail="Money has been received against this voucher. Reverse the payment first.",
        )

    voucher.status = VOUCHER_CANCELLED
    voucher.cancelled_reason = body.reason
    audit.record(db, actor=user, entity_type="fee_voucher", action="cancelled",
                 entity_id=voucher_id, reason=body.reason)
    await fee_service._recalculate_account(db, voucher.student_user_id)
    await db.commit()
    return voucher.to_dict()


# ─── Payments ─────────────────────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    student_user_id: str
    amount: Decimal
    method: str = "cash"
    voucher_id: str | None = None
    bank_reference: str | None = None
    received_on: date | None = None
    note: str | None = None


@router.post("/payments")
async def receive_payment(
    body: PaymentRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.collect")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await fee_service.receive_payment(
            db,
            student_user_id=body.student_user_id,
            amount=body.amount,
            method=body.method,
            voucher_id=body.voucher_id,
            bank_reference=body.bank_reference,
            received_on=body.received_on,
            note=body.note,
            actor=user,
        )
    except FeeError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return result


class ReverseRequest(BaseModel):
    reason: str


@router.post("/payments/{receipt_id}/reverse")
async def reverse_payment(
    receipt_id: str,
    body: ReverseRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.collect")),
    db: AsyncSession = Depends(get_db),
):
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="Please give a reason for the reversal.")
    try:
        result = await fee_service.reverse_receipt(
            db, receipt_id=receipt_id, reason=body.reason.strip(), actor=user,
        )
    except FeeError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return result


@router.get("/payments")
async def list_payments(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
    student_user_id: str | None = None,
    on_date: date | None = None,
    limit: int = Query(100, le=500),
):
    stmt = select(Receipt, User).join(User, User.id == Receipt.student_user_id)
    if student_user_id:
        stmt = stmt.where(Receipt.student_user_id == student_user_id)
    if on_date:
        stmt = stmt.where(Receipt.received_on == on_date)
    result = await db.execute(stmt.order_by(Receipt.created_at.desc()).limit(limit))
    return {
        "receipts": [
            {**receipt.to_dict(), "student_name": student.name}
            for receipt, student in result.all()
        ]
    }


# ─── Ledger, defaulters, summary ──────────────────────────────────────────────

@router.get("/ledger/{student_user_id}")
async def ledger(
    student_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A child's statement. A student may read their own."""
    held = await permissions_for(db, user)
    if user.id != student_user_id and "fee.report" not in held:
        raise HTTPException(status_code=403, detail="You may only see your own fee account.")
    return await fee_service.student_ledger(db, student_user_id=student_user_id)


@router.get("/defaulters")
async def defaulters(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
    class_id: str | None = None,
    section_id: str | None = None,
    min_amount: Decimal | None = None,
    include_inactive: bool = False,
):
    """Defaulter List — All (Active), the report the office runs most."""
    return await fee_service.defaulters(
        db, class_id=class_id, section_id=section_id,
        min_amount=min_amount, include_inactive=include_inactive,
    )


@router.get("/summary")
async def summary(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
    on_date: date | None = None,
):
    return await fee_service.collection_summary(db, on_date=on_date)


@router.get("/search-student")
async def search_student(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.collect")),
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1),
):
    """The counter's search: type a GR number or a name, get the child and what
    they owe, in one call."""
    from sqlalchemy import or_

    pattern = f"%{q.strip()}%"
    result = await db.execute(
        select(User, StudentProfile, StudentFeeAccount)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .join(StudentFeeAccount, StudentFeeAccount.student_user_id == User.id, isouter=True)
        .where(
            User.role == "student",
            or_(
                User.name.ilike(pattern),
                User.father_name.ilike(pattern),
                User.login_id.ilike(pattern),
                StudentProfile.gr_no.ilike(pattern),
                StudentProfile.admission_no.ilike(pattern),
            ),
        )
        .order_by(User.name)
        .limit(20)
    )
    return {
        "students": [
            {
                "id": student.id,
                "name": student.name,
                "father_name": student.father_name,
                "gr_no": profile.gr_no if profile else None,
                "class_name": student.class_name,
                "outstanding": str(account.outstanding) if account else "0.00",
            }
            for student, profile, account in result.all()
        ]
    }


# ─── Printing ─────────────────────────────────────────────────────────────────

class PrintRequest(BaseModel):
    voucher_ids: list[str]


@router.post("/vouchers/print")
async def print_vouchers(
    body: PrintRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.voucher")),
    db: AsyncSession = Depends(get_db),
):
    """The printable PDF: one page per voucher, three copies across it."""
    from fastapi.responses import Response
    from services.erp import voucher_print

    if not body.voucher_ids:
        raise HTTPException(status_code=400, detail="Choose at least one voucher to print.")
    if len(body.voucher_ids) > 400:
        raise HTTPException(
            status_code=400,
            detail="That is more than 400 vouchers. Print one class at a time.",
        )

    try:
        pdf = await voucher_print.render_vouchers(db, voucher_ids=body.voucher_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="fee-vouchers.pdf"'},
    )


@router.get("/voucher-settings")
async def get_voucher_settings(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.report")),
    db: AsyncSession = Depends(get_db),
):
    from services.erp import voucher_print
    config = await voucher_print.settings(db)
    await db.commit()
    return config.to_dict()


class VoucherSettingsRequest(BaseModel):
    school_name: str | None = None
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    campus_code: str | None = None
    post_to: str | None = None
    bank_line: str | None = None
    note: str | None = None
    late_fine_per_day: Decimal | None = None
    valid_days_after_due: int | None = None
    kuickpay_prefix: str | None = None


@router.put("/voucher-settings")
async def update_voucher_settings(
    body: VoucherSettingsRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("fee.structure")),
    db: AsyncSession = Depends(get_db),
):
    """The bank, the account, the note — school policy, changed without a deploy."""
    from services.erp import voucher_print

    config = await voucher_print.settings(db)
    before = config.to_dict()
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(config, field, value)
    config.updated_by = user.id

    old, new = audit.diff(before, config.to_dict())
    if new:
        audit.record(db, actor=user, entity_type="voucher_settings", action="updated",
                     old_value=old, new_value=new)
    await db.commit()
    return config.to_dict()
