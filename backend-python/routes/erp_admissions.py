"""
Admissions and families API (ERP phase 2).

The shape of these endpoints is the shape of the admission desk. A clerk with a
paper form in front of them types the child's details once, the server offers
the families that child might belong to, and one confirmation turns the form
into a student who can log in.

Everything the specification lists as automatic — GR number, admission number,
family link, account, class placement, dashboard access — happens inside
`confirm`, and none of it appears as a question on a screen.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from models.erp import (
    ADMISSION_APPROVED, ADMISSION_CANCELLED, ADMISSION_CONFIRMED,
    ADMISSION_OPEN_STATES, ADMISSION_REJECTED, Admission, Enrollment, Family,
    Guardian, SchoolClass, Section, StudentProfile,
)
from models.models import User
from routes.erp import erp_available
from services.erp import admissions as admissions_service, audit
from services.erp.admissions import AdmissionError
from services.erp.permissions import require_permission

router = APIRouter(prefix="/erp", tags=["erp-admissions"])


def _fail(exc: AdmissionError) -> HTTPException:
    """An admission error is always something the clerk can fix, so it comes
    back as a 400 with the sentence they need — not a stack trace."""
    return HTTPException(status_code=400, detail=str(exc))


# ─── Families ─────────────────────────────────────────────────────────────────

class FamilySuggestRequest(BaseModel):
    father_name: str | None = None
    phone: str | None = None
    cnic: str | None = None


@router.post("/families/suggest")
async def suggest_families(
    body: FamilySuggestRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("family.view")),
    db: AsyncSession = Depends(get_db),
):
    """Which existing family this child probably belongs to.

    Called as the clerk types, so it must stay cheap and must never write.
    """
    return await admissions_service.suggest_families(
        db, father_name=body.father_name, phone=body.phone, cnic=body.cnic,
    )


@router.get("/families")
async def list_families(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("family.view")),
    db: AsyncSession = Depends(get_db),
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Family)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Family.family_code.ilike(pattern),
            Family.father_name.ilike(pattern),
            Family.mother_name.ilike(pattern),
            Family.phone.ilike(pattern),
            Family.cnic.ilike(pattern),
        ))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    result = await db.execute(stmt.order_by(Family.father_name).limit(limit).offset(offset))
    families = list(result.scalars().all())

    # Children per family in one query rather than one per row — a family list
    # that fires fifty queries is how a page starts taking four seconds.
    counts: dict[str, int] = {}
    if families:
        result = await db.execute(
            select(StudentProfile.family_id, func.count())
            .where(StudentProfile.family_id.in_([f.id for f in families]))
            .group_by(StudentProfile.family_id)
        )
        counts = {row[0]: int(row[1]) for row in result.all()}

    return {
        "total": total,
        "families": [{**f.to_dict(), "children": counts.get(f.id, 0)} for f in families],
    }


@router.get("/families/{family_id}")
async def get_family(
    family_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("family.view")),
    db: AsyncSession = Depends(get_db),
):
    """One family, with every child in it — the screen the specification asks
    for: open a family, see all the children."""
    result = await db.execute(select(Family).where(Family.id == family_id))
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="Family not found")

    result = await db.execute(select(Guardian).where(Guardian.family_id == family_id))
    guardians = [g.to_dict() for g in result.scalars().all()]

    result = await db.execute(
        select(User, StudentProfile, SchoolClass, Section)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .join(Enrollment, Enrollment.student_user_id == User.id, isouter=True)
        .join(SchoolClass, SchoolClass.id == Enrollment.class_id, isouter=True)
        .join(Section, Section.id == Enrollment.section_id, isouter=True)
        .where(StudentProfile.family_id == family_id)
        .order_by(User.name)
    )
    children = [
        {
            "id": student.id, "name": student.name,
            "gr_no": profile.gr_no, "admission_no": profile.admission_no,
            "class_name": school_class.canonical_name if school_class else student.class_name,
            "section_name": section.name if section else student.section,
            "is_active": bool(student.is_active),
            "status": profile.status,
        }
        for student, profile, school_class, section in result.all()
    ]

    return {**family.to_dict(), "guardians": guardians, "children": children}


class FamilyRequest(BaseModel):
    father_name: str | None = None
    mother_name: str | None = None
    phone: str | None = None
    cnic: str | None = None
    email: str | None = None
    address: str | None = None


@router.post("/families")
async def create_family(
    body: FamilyRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("family.edit")),
    db: AsyncSession = Depends(get_db),
):
    family = await admissions_service.create_family(
        db, father_name=body.father_name, mother_name=body.mother_name,
        phone=body.phone, cnic=body.cnic, email=body.email, address=body.address,
        actor=user,
    )
    await db.commit()
    return family.to_dict()


@router.post("/families/{family_id}/add-child/{student_user_id}")
async def link_child(
    family_id: str,
    student_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("family.edit")),
    db: AsyncSession = Depends(get_db),
):
    """Attach an existing student to a family — how siblings already in the
    school get joined up after setup."""
    result = await db.execute(select(Family).where(Family.id == family_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Family not found")

    result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == student_user_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Student not found")

    before = profile.family_id
    profile.family_id = family_id
    audit.record(db, actor=user, entity_type=audit.STUDENT, action="family_linked",
                 entity_id=student_user_id,
                 old_value={"family_id": before}, new_value={"family_id": family_id})
    await db.commit()
    return {"message": "Linked"}


# ─── Admissions ───────────────────────────────────────────────────────────────

class AdmissionRequest(BaseModel):
    student_name: str
    father_name: str | None = None
    mother_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    b_form: str | None = None
    phone: str | None = None
    address: str | None = None
    previous_school: str | None = None
    previous_class: str | None = None
    class_applied_id: str | None = None
    section_id: str | None = None
    family_id: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None
    emergency_contact: str | None = None
    emergency_phone: str | None = None
    remarks: str | None = None
    inquiry_source: str | None = None
    status: str | None = None


@router.get("/admissions")
async def list_admissions(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("admission.view")),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Admission)
    if status == "open":
        stmt = stmt.where(Admission.status.in_(ADMISSION_OPEN_STATES))
    elif status:
        stmt = stmt.where(Admission.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Admission.student_name.ilike(pattern),
            Admission.father_name.ilike(pattern),
            Admission.application_no.ilike(pattern),
            Admission.phone.ilike(pattern),
        ))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    result = await db.execute(stmt.order_by(Admission.created_at.desc()).limit(limit).offset(offset))
    rows = list(result.scalars().all())

    result = await db.execute(select(SchoolClass.id, SchoolClass.canonical_name))
    class_names = {row[0]: row[1] for row in result.all()}

    return {
        "total": total,
        "admissions": [
            {**a.to_dict(), "class_name": class_names.get(a.class_applied_id)}
            for a in rows
        ],
    }


@router.post("/admissions")
async def create_admission(
    body: AdmissionRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("admission.create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        admission = await admissions_service.create_admission(
            db, data=body.model_dump(exclude_unset=True), actor=user,
        )
    except AdmissionError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return admission.to_dict()


@router.put("/admissions/{admission_id}")
async def update_admission(
    admission_id: str,
    body: AdmissionRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("admission.create")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Admission).where(Admission.id == admission_id))
    admission = result.scalar_one_or_none()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")
    if admission.status == ADMISSION_CONFIRMED:
        raise HTTPException(
            status_code=400,
            detail="This admission is confirmed. Edit the student record instead.",
        )

    before = admission.to_dict()
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(admission, field, value)

    old, new = audit.diff(before, admission.to_dict())
    if new:
        audit.record(db, actor=user, entity_type="admission", action="updated",
                     entity_id=admission.id, old_value=old, new_value=new)
    await db.commit()
    return admission.to_dict()


@router.post("/admissions/{admission_id}/confirm")
async def confirm_admission(
    admission_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("admission.confirm")),
    db: AsyncSession = Depends(get_db),
):
    """The one press that creates a student.

    The response carries the temporary password, and it is the only time it
    exists in readable form — it is hashed on the way into the database and is
    never logged, so the office prints the slip now or resets it later.
    """
    result = await db.execute(select(Admission).where(Admission.id == admission_id))
    admission = result.scalar_one_or_none()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")

    try:
        credentials = await admissions_service.confirm_admission(db, admission, actor=user)
    except AdmissionError as exc:
        await db.rollback()
        raise _fail(exc)
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    return credentials


class RejectRequest(BaseModel):
    reason: str | None = None


@router.post("/admissions/{admission_id}/reject")
async def reject_admission(
    admission_id: str,
    body: RejectRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("admission.confirm")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Admission).where(Admission.id == admission_id))
    admission = result.scalar_one_or_none()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")
    if admission.status == ADMISSION_CONFIRMED:
        raise HTTPException(status_code=400, detail="This student has already been admitted.")

    admission.status = ADMISSION_REJECTED
    admission.rejected_reason = body.reason
    audit.record(db, actor=user, entity_type="admission", action="rejected",
                 entity_id=admission.id, new_value={"reason": body.reason})
    await db.commit()
    return admission.to_dict()
