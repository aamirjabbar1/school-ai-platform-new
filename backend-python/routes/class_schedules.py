"""
Class scheduling (spec §20).

Two ways to teach: START NOW, or a timetable. A scheduled class appears on the
student's dashboard as UPCOMING and turns into 🔴 LIVE the moment the teacher
starts it — the student never has to know which of the two happened.

Schedules describe intent; sessions are what actually ran. A weekly slot is
materialised into a session shortly before it is due, so "what was supposed to
happen" and "what did happen" stay separable in the record.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from models.models import User, utcnow
from models.online_classes import (
    SESSION_CANCELLED,
    SESSION_LIVE,
    SESSION_SCHEDULED,
    OnlineClassSchedule,
    OnlineClassSession,
)
from services import class_matching
from services import livekit_service as lk
from services.online_class_config import get_settings
from services.student_excel_import_service import normalize_class, normalize_section

router = APIRouter(prefix="/online-classes", tags=["online-classes"])


class ScheduleRequest(BaseModel):
    subject: str
    class_name: str
    section: str | None = None
    title: str | None = None
    recurrence: str = "weekly"          # weekly | once
    weekday: int | None = None          # 0 = Monday … 6 = Sunday
    class_date: date | None = None      # for a one-off
    start_time: time
    duration_minutes: int = 40
    start_date: date | None = None
    end_date: date | None = None
    recording_enabled: bool = False


# ─── Teacher / admin management ───────────────────────────────────────────────

@router.get("/schedules")
async def list_schedules(
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(OnlineClassSchedule).where(OnlineClassSchedule.is_active == True)  # noqa: E712
    if user.role == "teacher":
        query = query.where(OnlineClassSchedule.teacher_id == user.id)
    result = await db.execute(query.order_by(OnlineClassSchedule.weekday, OnlineClassSchedule.start_time))
    return {"schedules": [s.to_dict() for s in result.scalars().all()]}


@router.post("/schedules")
async def create_schedule(
    body: ScheduleRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    class_name = normalize_class(body.class_name) or body.class_name.strip()
    section = normalize_section(body.section)

    if user.role == "teacher":
        allowed, reason = class_matching.teacher_may_teach(user, class_name, section, body.subject)
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

    if body.recurrence == "weekly" and body.weekday is None:
        raise HTTPException(status_code=400, detail="A weekly class needs a day of the week.")
    if body.recurrence == "once" and not body.class_date:
        raise HTTPException(status_code=400, detail="A one-off class needs a date.")

    schedule = OnlineClassSchedule(
        teacher_id=user.id,
        subject=body.subject,
        class_name=class_name,
        section=section,
        title=body.title,
        recurrence=body.recurrence,
        weekday=body.weekday,
        class_date=body.class_date,
        start_time=body.start_time,
        duration_minutes=max(5, min(300, body.duration_minutes)),
        start_date=body.start_date,
        end_date=body.end_date,
        recording_enabled=body.recording_enabled,
        created_by=user.id,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule.to_dict()


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    schedule = (await db.execute(
        select(OnlineClassSchedule).where(OnlineClassSchedule.id == schedule_id)
    )).scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if user.role == "teacher" and schedule.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="This is not your class.")

    schedule.is_active = False
    # Planned sessions that have not started yet go with it; a cancelled slot
    # must not keep appearing on a student's dashboard.
    upcoming = (await db.execute(
        select(OnlineClassSession).where(
            OnlineClassSession.schedule_id == schedule.id,
            OnlineClassSession.status == SESSION_SCHEDULED,
        )
    )).scalars().all()
    for session in upcoming:
        session.status = SESSION_CANCELLED
    await db.commit()
    return {"message": "Schedule removed."}


@router.get("/upcoming")
async def upcoming_classes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What is coming up — for whichever dashboard is asking."""
    horizon = utcnow() + timedelta(hours=24)
    result = await db.execute(
        select(OnlineClassSession)
        .where(
            OnlineClassSession.status == SESSION_SCHEDULED,
            OnlineClassSession.scheduled_start.is_not(None),
            OnlineClassSession.scheduled_start <= horizon,
        )
        .order_by(OnlineClassSession.scheduled_start)
    )
    sessions = list(result.scalars().all())

    if user.role == "student":
        sessions = [s for s in sessions if class_matching.student_may_join(user, s)[0]]
    elif user.role == "teacher":
        sessions = [s for s in sessions if s.teacher_id == user.id]

    return {"upcoming": [s.to_dict() for s in sessions]}


# ─── Materialisation ──────────────────────────────────────────────────────────

async def materialize_due_sessions(db: AsyncSession, *, horizon_minutes: int = 120) -> int:
    """Create the sessions for schedules that are about to come round.

    Called by the beat worker. A session is created once per schedule per day,
    so a student sees one UPCOMING card rather than a duplicate for every sweep.
    """
    settings = await get_settings(db)
    now = utcnow()
    horizon = now + timedelta(minutes=horizon_minutes)
    created = 0

    schedules = (await db.execute(
        select(OnlineClassSchedule).where(OnlineClassSchedule.is_active == True)  # noqa: E712
    )).scalars().all()

    for schedule in schedules:
        start_at = _next_occurrence(schedule, now)
        if not start_at or start_at > horizon:
            continue

        existing = (await db.execute(
            select(OnlineClassSession).where(
                OnlineClassSession.schedule_id == schedule.id,
                OnlineClassSession.scheduled_start == start_at,
            )
        )).scalar_one_or_none()
        if existing:
            continue

        teacher = (await db.execute(
            select(User).where(User.id == schedule.teacher_id)
        )).scalar_one_or_none()

        session = OnlineClassSession(
            schedule_id=schedule.id,
            teacher_id=schedule.teacher_id,
            teacher_name=teacher.name if teacher else None,
            subject=schedule.subject,
            class_name=schedule.class_name,
            section=schedule.section,
            title=schedule.title or f"{schedule.subject} — {schedule.class_name}",
            status=SESSION_SCHEDULED,
            room_name="",
            scheduled_start=start_at,
            planned_duration_minutes=schedule.duration_minutes or 40,
            young_mode=class_matching.is_young_class(schedule.class_name, settings.young_classes),
            recording_enabled=bool(schedule.recording_enabled or settings.recording_default_on),
        )
        db.add(session)
        await db.flush()
        session.room_name = lk.room_name_for(session.id)
        created += 1

    if created:
        await db.commit()
    return created


def _next_occurrence(schedule: OnlineClassSchedule, now: datetime) -> datetime | None:
    """When this schedule next runs, or None if it has finished."""
    if schedule.recurrence == "once":
        if not schedule.class_date:
            return None
        start_at = datetime.combine(schedule.class_date, schedule.start_time)
        return start_at if start_at >= now - timedelta(hours=2) else None

    if schedule.weekday is None:
        return None
    if schedule.start_date and now.date() < schedule.start_date:
        return None
    if schedule.end_date and now.date() > schedule.end_date:
        return None

    days_ahead = (schedule.weekday - now.weekday()) % 7
    candidate = datetime.combine(now.date() + timedelta(days=days_ahead), schedule.start_time)
    if candidate < now - timedelta(hours=2):
        candidate += timedelta(days=7)
    return candidate


# ─── Starting a scheduled class ───────────────────────────────────────────────

@router.post("/schedules/{session_id}/start")
async def start_scheduled(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Turn an UPCOMING class into a live one, keeping the link to the plan."""
    from routes.online_classes import _issue_token, TEACHER_SOURCES

    session = (await db.execute(
        select(OnlineClassSession).where(OnlineClassSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")
    if user.role == "teacher" and session.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="This is not your class.")
    if session.status not in (SESSION_SCHEDULED, SESSION_LIVE):
        raise HTTPException(status_code=409, detail="This class can no longer be started.")

    if session.status == SESSION_SCHEDULED:
        from services import class_events

        session.status = SESSION_LIVE
        session.actual_start = utcnow()
        if not session.room_name:
            session.room_name = lk.room_name_for(session.id)
        await class_events.record(
            db, session.id, class_events.CLASS_STARTED,
            actor_id=user.id, actor_role=user.role, payload={"from_schedule": True},
        )
        await db.commit()
        await db.refresh(session)

    payload = await _issue_token(session, user, role="teacher", sources=TEACHER_SOURCES)
    payload["session"] = session.to_dict(include_state=True)
    return payload
