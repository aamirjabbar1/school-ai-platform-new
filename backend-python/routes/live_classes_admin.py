"""
Admin — Live Classes control room (spec §14).

What an administrator needs during a school day: which classes are running,
who is in them, whether anything is failing, and the ability to step in. Every
figure here comes from the classroom's own records; nothing is estimated and
nothing is produced by an AI.

Observation is deliberately noisy: when an administrator joins a class, the
class is told. Silent supervision of a room full of children is not a feature.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import require_roles
from models.models import User, utcnow
from models.online_classes import (
    SESSION_ENDED,
    SESSION_LIVE,
    OnlineClassEvent,
    OnlineClassParticipant,
    OnlineClassRecording,
    OnlineClassSession,
)
from services import attendance_service, class_events, classroom_state
from services import livekit_service as lk
from services.online_class_config import get_settings

logger = logging.getLogger("agent")

router = APIRouter(prefix="/admin", tags=["online-classes-admin"])


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/live-classes")
async def live_classes(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Everything happening right now, with the counts a head teacher asks for."""
    result = await db.execute(
        select(OnlineClassSession)
        .where(OnlineClassSession.status == SESSION_LIVE)
        .order_by(OnlineClassSession.actual_start)
    )
    sessions = list(result.scalars().all())

    classes = []
    students_online = 0
    for session in sessions:
        connected = (await db.execute(
            select(func.count())
            .select_from(OnlineClassParticipant)
            .where(
                OnlineClassParticipant.session_id == session.id,
                OnlineClassParticipant.is_connected == True,  # noqa: E712
                OnlineClassParticipant.role == "student",
            )
        )).scalar() or 0
        students_online += connected

        classes.append({
            **session.to_dict(),
            "students_online": connected,
            "minutes_running": round(session.duration_seconds / 60, 1),
            "hands_raised": len(await classroom_state.list_hands(session.id)),
        })

    return {
        "counts": {
            "live_classes": len(sessions),
            "students_online": students_online,
            "teachers_online": len({s.teacher_id for s in sessions}),
        },
        "classes": classes,
        "media_server_configured": lk.is_configured(),
        "recording_configured": lk.recording_configured(),
    }


@router.get("/live-classes/history")
async def class_history(
    days: int = 7,
    class_name: str | None = None,
    teacher_id: str | None = None,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Finished classes, for the "did this actually happen?" question."""
    since = utcnow() - timedelta(days=max(1, min(days, 120)))
    query = select(OnlineClassSession).where(
        OnlineClassSession.status == SESSION_ENDED,
        OnlineClassSession.actual_start >= since,
    )
    if class_name:
        query = query.where(OnlineClassSession.class_name == class_name)
    if teacher_id:
        query = query.where(OnlineClassSession.teacher_id == teacher_id)

    result = await db.execute(query.order_by(OnlineClassSession.actual_start.desc()).limit(300))
    sessions = list(result.scalars().all())

    out = []
    for session in sessions:
        total = (await db.execute(
            select(func.count()).select_from(OnlineClassParticipant).where(
                OnlineClassParticipant.session_id == session.id,
                OnlineClassParticipant.role == "student",
            )
        )).scalar() or 0

        attended = (await db.execute(
            select(func.count()).select_from(OnlineClassParticipant).where(
                OnlineClassParticipant.session_id == session.id,
                OnlineClassParticipant.role == "student",
                OnlineClassParticipant.status != "absent",
            )
        )).scalar() or 0

        recording = (await db.execute(
            select(OnlineClassRecording).where(
                OnlineClassRecording.session_id == session.id,
                OnlineClassRecording.deleted_at.is_(None),
            ).limit(1)
        )).scalar_one_or_none()

        out.append({
            **session.to_dict(),
            "students_on_register": total,
            "students_attended": attended,
            "attendance_rate": round((attended / total) * 100, 1) if total else 0.0,
            "recording": recording.to_dict() if recording else None,
        })
    return {"classes": out}


@router.get("/live-classes/{session_id}")
async def class_detail(
    session_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """One class in full: register, event log, recording, live participants."""
    session = (await db.execute(
        select(OnlineClassSession).where(OnlineClassSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")

    events = (await db.execute(
        select(OnlineClassEvent)
        .where(OnlineClassEvent.session_id == session.id)
        .order_by(OnlineClassEvent.at)
        .limit(500)
    )).scalars().all()

    recordings = (await db.execute(
        select(OnlineClassRecording).where(OnlineClassRecording.session_id == session.id)
    )).scalars().all()

    connected = []
    if session.status == SESSION_LIVE:
        try:
            connected = await lk.list_participants(session.room_name)
        except Exception as exc:
            logger.warning("[ADMIN] live participants unavailable: %s", exc)

    return {
        "session": session.to_dict(include_state=True),
        "attendance": await attendance_service.attendance_for_session(db, session),
        "events": [e.to_dict() for e in events],
        "recordings": [r.to_dict() for r in recordings],
        "connected": connected,
        "hands": await classroom_state.list_hands(session.id),
    }


# ─── Intervening ──────────────────────────────────────────────────────────────

@router.post("/live-classes/{session_id}/observe")
async def observe_class(
    session_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Join a live class as an observer.

    The observer publishes nothing, and — unless the school turns the
    announcement off — the class is told an administrator is watching. Both the
    join and who made it are written to the audit log.
    """
    session = (await db.execute(
        select(OnlineClassSession).where(OnlineClassSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")
    if session.status != SESSION_LIVE:
        raise HTTPException(status_code=409, detail="This class is not live.")

    settings = await get_settings(db)
    if not settings.allow_admin_observe:
        raise HTTPException(status_code=403, detail="Observation is disabled for this school.")

    announce = bool(settings.announce_admin_observe)
    # Same reason as a teacher's or student's join (see lk.ensure_room): the
    # room may not exist yet — an admin can be the first to open a live class
    # whose participants have all dropped, and a token for a room that does not
    # exist is refused.
    try:
        await lk.ensure_room(session.room_name, metadata={
            "session_id": session.id,
            "class_name": session.class_name,
            "section": session.section,
            "subject": session.subject,
        })
    except Exception as exc:
        logger.error("[LIVE CLASSES] could not open room %s: %s", session.room_name, exc)
        raise HTTPException(
            status_code=503,
            detail="The classroom could not be opened. Please try again in a moment.",
        )

    token = lk.create_access_token(
        identity=user.id,
        display_name=f"{user.name} (Administrator)",
        room=session.room_name,
        can_publish=False,
        can_publish_data=False,
        # Hidden only when the school has chosen not to announce observation;
        # the audit trail records it either way.
        hidden=not announce,
        metadata={"role": "observer"},
        ttl_hours=1,
    )

    await class_events.record(
        db, session.id, class_events.ADMIN_OBSERVED,
        actor_id=user.id, actor_role="admin",
        payload={"announced": announce}, commit=True,
    )
    if announce:
        await lk.broadcast_safely(session.room_name, {
            "t": "observer", "name": user.name, "active": True,
        })

    return {
        "token": token,
        "url": lk.public_url(),
        "announced": announce,
        "session": session.to_dict(include_state=True),
    }


@router.post("/live-classes/{session_id}/end")
async def force_end(
    session_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """End a class from the control room — for the lesson nobody closed."""
    from routes.online_classes import _end_session

    session = (await db.execute(
        select(OnlineClassSession).where(OnlineClassSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")
    if session.status != SESSION_LIVE:
        return {"message": "Class already ended."}

    await _end_session(db, session, reason="admin", actor=user)
    return {"message": "Class ended.", "session": session.to_dict()}


# ─── Logs and reports ─────────────────────────────────────────────────────────

@router.get("/live-classes-logs")
async def classroom_logs(
    hours: int = 24,
    event_type: str | None = None,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Recent classroom events across the school — who started what, what was
    presented, what failed. Deliberately free of anything private: it records
    actions, not what anyone said."""
    since = utcnow() - timedelta(hours=max(1, min(hours, 720)))
    query = (
        select(OnlineClassEvent, OnlineClassSession)
        .join(OnlineClassSession, OnlineClassEvent.session_id == OnlineClassSession.id)
        .where(OnlineClassEvent.at >= since)
    )
    if event_type:
        query = query.where(OnlineClassEvent.type == event_type)

    rows = (await db.execute(query.order_by(OnlineClassEvent.at.desc()).limit(500))).all()
    return {
        "events": [
            {
                **event.to_dict(),
                "class_name": session.class_name,
                "section": session.section,
                "subject": session.subject,
                "teacher_name": session.teacher_name,
            }
            for event, session in rows
        ]
    }


@router.get("/online-classes/report")
async def usage_report(
    days: int = 30,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Teaching volume and attendance by teacher and by class."""
    since = utcnow() - timedelta(days=max(1, min(days, 365)))

    by_teacher = (await db.execute(
        select(
            OnlineClassSession.teacher_id,
            OnlineClassSession.teacher_name,
            func.count(OnlineClassSession.id),
        )
        .where(OnlineClassSession.actual_start >= since)
        .group_by(OnlineClassSession.teacher_id, OnlineClassSession.teacher_name)
        .order_by(func.count(OnlineClassSession.id).desc())
    )).all()

    by_class = (await db.execute(
        select(
            OnlineClassSession.class_name,
            OnlineClassSession.section,
            func.count(OnlineClassSession.id),
        )
        .where(OnlineClassSession.actual_start >= since)
        .group_by(OnlineClassSession.class_name, OnlineClassSession.section)
        .order_by(func.count(OnlineClassSession.id).desc())
    )).all()

    attendance_avg = (await db.execute(
        select(func.avg(OnlineClassParticipant.attendance_percent))
        .select_from(OnlineClassParticipant)
        .join(OnlineClassSession, OnlineClassParticipant.session_id == OnlineClassSession.id)
        .where(
            OnlineClassSession.actual_start >= since,
            OnlineClassParticipant.role == "student",
            OnlineClassParticipant.finalized == True,  # noqa: E712
        )
    )).scalar()

    return {
        "days": days,
        "average_attendance_percent": round(float(attendance_avg or 0), 1),
        "by_teacher": [
            {"teacher_id": tid, "teacher_name": name, "classes": count}
            for tid, name, count in by_teacher
        ],
        "by_class": [
            {"class_name": cls, "section": section, "classes": count}
            for cls, section, count in by_class
        ],
    }


# ─── Settings (spec §19F) ─────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    teacher_grace_minutes: int | None = None
    join_early_minutes: int | None = None
    young_classes: list[str] | None = None
    present_min_percent: float | None = None
    partial_min_percent: float | None = None
    late_after_minutes: int | None = None
    recording_enabled_globally: bool | None = None
    recording_default_on: bool | None = None
    recording_retention_days: int | None = None
    max_concurrent_recordings: int | None = None
    allow_admin_observe: bool | None = None
    announce_admin_observe: bool | None = None
    ai_class_summary_enabled: bool | None = None
    ai_coverage_analysis_enabled: bool | None = None
    ai_revision_notes_enabled: bool | None = None
    ai_ask_enabled: bool | None = None
    ai_teacher_assistant_enabled: bool | None = None
    ai_daily_budget_usd: float | None = None
    ai_monthly_budget_usd: float | None = None
    ai_max_questions_per_student_per_day: int | None = None
    ai_max_calls_per_session: int | None = None
    ai_model_routing: dict | None = None


@router.get("/online-classes/health")
async def module_health(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Operational health of the Online Classes module (spec §29).

    Answers the question an administrator actually asks when something feels
    wrong: is the media server reachable, are attendance webhooks arriving, is
    anything failing? Deliberately free of student names.
    """
    from models.online_classes import OnlineClassAttendanceEvent, OnlineClassRecording

    since = utcnow() - timedelta(hours=1)

    live_count = (await db.execute(
        select(func.count()).select_from(OnlineClassSession)
        .where(OnlineClassSession.status == SESSION_LIVE)
    )).scalar() or 0

    recent_attendance = (await db.execute(
        select(func.count()).select_from(OnlineClassAttendanceEvent)
        .where(OnlineClassAttendanceEvent.at >= since)
    )).scalar() or 0

    failed_joins = (await db.execute(
        select(func.count()).select_from(OnlineClassEvent)
        .where(OnlineClassEvent.type == "join_denied", OnlineClassEvent.at >= since)
    )).scalar() or 0

    disconnects = (await db.execute(
        select(func.count()).select_from(OnlineClassAttendanceEvent)
        .where(
            OnlineClassAttendanceEvent.at >= since,
            OnlineClassAttendanceEvent.event == "leave",
            OnlineClassAttendanceEvent.reason == "disconnected",
        )
    )).scalar() or 0

    rejoins = (await db.execute(
        select(func.count()).select_from(OnlineClassAttendanceEvent)
        .where(OnlineClassAttendanceEvent.at >= since, OnlineClassAttendanceEvent.event == "rejoin")
    )).scalar() or 0

    recording_failures = (await db.execute(
        select(func.count()).select_from(OnlineClassRecording)
        .where(OnlineClassRecording.status == "failed",
               OnlineClassRecording.created_at >= utcnow() - timedelta(days=1))
    )).scalar() or 0

    media_reachable = None
    if lk.is_configured():
        try:
            await lk.list_participants("health-probe-nonexistent-room")
            media_reachable = True
        except lk.LiveKitUnavailable:
            media_reachable = False
        except Exception:
            # A "room not found" answer still proves the server answered.
            media_reachable = True

    warnings = []
    if live_count and not recent_attendance:
        warnings.append(
            "Classes are live but no join/leave events have arrived in the last hour — "
            "check that the media server can reach the webhook URL."
        )
    if media_reachable is False:
        warnings.append("The media server is not responding.")
    if recording_failures:
        warnings.append(f"{recording_failures} recording(s) failed in the last day.")

    return {
        "media_server_configured": lk.is_configured(),
        "media_server_reachable": media_reachable,
        "recording_configured": lk.recording_configured(),
        "live_classes": live_count,
        "last_hour": {
            "attendance_events": recent_attendance,
            "join_denied": failed_joins,
            "disconnects": disconnects,
            "rejoins": rejoins,
        },
        "recording_failures_24h": recording_failures,
        "warnings": warnings,
        "speech_to_text": "not implemented — classroom audio is never transcribed",
    }


@router.get("/online-classes/ai-usage")
async def ai_usage(
    days: int = 30,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """AI spend and volume (spec §19G).

    There is no transcription line here because there is no transcription: the
    only AI cost this module can incur is text-to-text.
    """
    from services import lss_ai_service

    settings = await get_settings(db)
    summary = await lss_ai_service.usage_summary(db, days=days)

    daily_budget = settings.ai_daily_budget_usd or 0
    monthly_budget = settings.ai_monthly_budget_usd or 0
    summary["budgets"] = {
        "daily_usd": daily_budget,
        "monthly_usd": monthly_budget,
        "daily_used_percent": round((summary["today_usd"] / daily_budget) * 100, 1) if daily_budget else 0,
        "monthly_used_percent": round((summary["month_usd"] / monthly_budget) * 100, 1) if monthly_budget else 0,
    }
    # Warn before the school hits a wall, not after.
    summary["alerts"] = [
        text for text, tripped in (
            ("Daily AI budget is nearly used up.", summary["budgets"]["daily_used_percent"] >= 80),
            ("Monthly AI budget is nearly used up.", summary["budgets"]["monthly_used_percent"] >= 80),
            ("Some AI requests are failing — check the provider key.",
             any(row["status"] == "failed" for row in summary["non_ok"])),
        ) if tripped
    ]
    summary["models"] = {
        "capable": lss_ai_service.model_for(settings, lss_ai_service.ASK_AI),
        "fast": lss_ai_service.model_for(settings, lss_ai_service.CLASS_SUMMARY),
    }
    return summary


@router.get("/online-classes/settings")
async def read_settings(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_settings(db)
    return settings.to_dict()


@router.put("/online-classes/settings")
async def update_settings(
    body: SettingsUpdate,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_settings(db)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, field, value)
    settings.updated_by = user.id
    await db.commit()
    await db.refresh(settings)
    return settings.to_dict()
