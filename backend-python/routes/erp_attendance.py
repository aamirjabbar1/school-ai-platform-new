"""
Attendance API (ERP phase 3).

Shaped for a phone. `my-classes` and `roster` between them are everything the
teacher's screen needs, and `save` takes the whole register in one request —
because a teacher on a corridor connection should spend one round trip, not
twenty-four.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.erp import SchoolClass, Section
from models.models import User
from routes.erp import erp_available
from services.erp import attendance as attendance_service
from services.erp.attendance import AttendanceError
from services.erp.permissions import permissions_for, require_permission

router = APIRouter(prefix="/erp/attendance", tags=["erp-attendance"])


@router.get("/my-classes")
async def my_classes(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The classes this teacher can take a register for, with today's state.

    An office user with attendance.view sees every class, because chasing a
    missing register is their job.
    """
    held = await permissions_for(db, user)
    if "attendance.mark" not in held and "attendance.view" not in held:
        raise HTTPException(status_code=403, detail="You do not take attendance.")

    classes = await attendance_service.classes_for_teacher(db, user)

    # The office sees everything; a teacher sees theirs.
    if not classes and "attendance.view" in held:
        result = await db.execute(select(SchoolClass).order_by(SchoolClass.sort_order))
        all_classes = list(result.scalars().all())
        result = await db.execute(select(Section))
        sections = list(result.scalars().all())
        classes = []
        for school_class in all_classes:
            class_sections = [s for s in sections if s.class_id == school_class.id]
            if class_sections:
                classes.extend({
                    "class_id": school_class.id, "class_name": school_class.canonical_name,
                    "section_id": s.id, "section_name": s.name, "students": 0,
                    "label": f"{school_class.canonical_name} — {s.name}",
                } for s in class_sections)
            else:
                classes.append({
                    "class_id": school_class.id, "class_name": school_class.canonical_name,
                    "section_id": None, "section_name": None, "students": 0,
                    "label": school_class.canonical_name,
                })

    return {"today": date.today().isoformat(), "classes": classes}


@router.get("/roster")
async def roster(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    class_id: str = Query(...),
    section_id: str | None = None,
    on_date: date | None = None,
):
    held = await permissions_for(db, user)
    if "attendance.mark" not in held and "attendance.view" not in held:
        raise HTTPException(status_code=403, detail="You do not take attendance.")

    if "attendance.view" not in held and not await attendance_service.may_take_register(
        db, user, class_id, section_id
    ):
        raise HTTPException(status_code=403, detail="This is not one of your classes.")

    try:
        return await attendance_service.roster(
            db, class_id=class_id, section_id=section_id, on_date=on_date or date.today(),
        )
    except AttendanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class Mark(BaseModel):
    student_id: str
    status: str
    note: str | None = None


class SaveRegisterRequest(BaseModel):
    class_id: str
    section_id: str | None = None
    on_date: date | None = None
    marks: list[Mark]


@router.post("/save")
async def save_register(
    body: SaveRegisterRequest,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    held = await permissions_for(db, user)
    on_date = body.on_date or date.today()

    may_mark = "attendance.mark" in held and await attendance_service.may_take_register(
        db, user, body.class_id, body.section_id
    )
    may_correct = "attendance.correct" in held
    if not (may_mark or may_correct):
        raise HTTPException(status_code=403, detail="This is not one of your classes.")

    try:
        result = await attendance_service.save_register(
            db,
            class_id=body.class_id,
            section_id=body.section_id,
            on_date=on_date,
            marks=[m.model_dump() for m in body.marks],
            actor=user,
        )
    except AttendanceError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()
    return result


@router.get("/missing")
async def missing(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("attendance.view")),
    db: AsyncSession = Depends(get_db),
    on_date: date | None = None,
):
    """Which registers have not been taken. Empty on a good day."""
    target = on_date or date.today()
    rows = await attendance_service.missing_registers(db, on_date=target)
    return {"date": target.isoformat(), "missing": rows}


@router.get("/report/class")
async def class_report(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("attendance.view")),
    db: AsyncSession = Depends(get_db),
    class_id: str = Query(...),
    section_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
):
    end = to_date or date.today()
    start = from_date or (end - timedelta(days=30))
    rows = await attendance_service.class_summary(
        db, class_id=class_id, section_id=section_id, from_date=start, to_date=end,
    )
    return {"from": start.isoformat(), "to": end.isoformat(), "students": rows}


@router.get("/report/student/{student_user_id}")
async def student_report(
    student_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    from_date: date | None = None,
    to_date: date | None = None,
):
    """A child's own attendance.

    A student may always read their own; anyone else needs permission. Parents
    reach it the same way once parent accounts exist.
    """
    held = await permissions_for(db, user)
    if user.id != student_user_id and "attendance.view" not in held:
        raise HTTPException(status_code=403, detail="You may only see your own attendance.")

    end = to_date or date.today()
    start = from_date or (end - timedelta(days=90))
    return await attendance_service.student_summary(
        db, student_user_id=student_user_id, from_date=start, to_date=end,
    )
