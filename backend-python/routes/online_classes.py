"""
Online Classes — teacher and student API (Phase 1: core classroom).

The whole module exists to keep two buttons honest:

    Teacher → START CLASS
    Student → JOIN CLASS

Everything else (rooms, tokens, permissions, attendance) happens server-side.
Nobody is ever asked for a meeting ID, a password or a link, and no browser is
ever trusted with room-admin rights: a teacher's control is a request to this
API, which checks who they are before acting on the room.

Not in this module, deliberately: any call to an AI provider, and any handling
of classroom audio. Starting, joining, muting and attendance are ordinary
application logic and consume zero AI tokens (spec §19A).

No `from __future__ import annotations` here, and it must not be added back:
the rate limiter wraps these endpoints with `functools.wraps`, which cannot
carry `__globals__` across. String annotations would then be resolved by
FastAPI inside *slowapi's* namespace, where `StartClassRequest` does not
exist — and an unresolvable body model is silently demoted to a query
parameter, so every POST fails validation with 422. See
`tests/test_route_wiring.py`, which fails if that ever comes back.
"""
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from middleware.rate_limit import limiter
from models.models import User, utcnow
from models.online_classes import (
    SESSION_ENDED,
    SESSION_LIVE,
    OnlineClassParticipant,
    OnlineClassSession,
)
from services import attendance_service, class_events, class_matching, classroom_state
from services import livekit_service as lk
from services.classroom_access import get_session, require_host
from services.online_class_config import get_settings
from services.student_excel_import_service import normalize_class, normalize_section

logger = logging.getLogger("agent")

router = APIRouter(prefix="/online-classes", tags=["online-classes"])

TEACHER_SOURCES = ["microphone", "camera", "screen_share"]


# ─── Request bodies ───────────────────────────────────────────────────────────

class StartClassRequest(BaseModel):
    class_name: str
    section: str | None = None
    subject: str
    title: str | None = None
    planned_duration_minutes: int = 40
    lesson_plan_id: str | None = None


class HandRequest(BaseModel):
    raised: bool = True


class PermissionRequest(BaseModel):
    user_id: str
    mic: bool = False
    camera: bool = False


class TargetRequest(BaseModel):
    user_id: str


class ToggleRequest(BaseModel):
    locked: bool


# ─── Helpers ──────────────────────────────────────────────────────────────────

_get_session = get_session
_require_host = require_host


async def _close_if_abandoned(db: AsyncSession, session: OnlineClassSession, settings) -> bool:
    """End a class whose teacher disconnected and never came back.

    Checked lazily on read instead of by a background sweeper: a class only
    matters when somebody is looking at it, and this keeps Phase 1 free of a
    scheduler. Returns True if the session was closed.
    """
    if session.status != SESSION_LIVE or not session.teacher_disconnected_at:
        return False

    grace = timedelta(minutes=settings.teacher_grace_minutes or 5)
    if utcnow() - session.teacher_disconnected_at < grace:
        return False

    await _end_session(db, session, reason="grace_timeout", actor=None)
    return True


async def _end_session(
    db: AsyncSession,
    session: OnlineClassSession,
    *,
    reason: str,
    actor: User | None,
) -> None:
    """Close a class: finalise the register, then tear the room down."""
    session.status = SESSION_ENDED
    session.actual_end = utcnow()
    session.end_reason = reason

    await class_events.record(
        db, session.id, class_events.CLASS_ENDED,
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else "system",
        payload={"reason": reason},
    )
    # finalize_session commits — the register is the part that must not be lost.
    await attendance_service.finalize_session(db, session)

    await classroom_state.clear_session(session.id)
    await lk.broadcast_safely(session.room_name, {"t": "ended", "reason": reason})
    try:
        await lk.end_room(session.room_name)
    except Exception as exc:
        logger.warning("[ONLINE CLASS] room teardown failed for %s: %s", session.id, exc)


async def _issue_token(
    session: OnlineClassSession,
    user: User,
    *,
    role: str,
    sources: list[str],
) -> dict:
    """Build the join payload a browser needs — and nothing more."""
    # The room must exist before the browser dials it; see lk.ensure_room. A
    # token for a room that was never created is refused with a 404 the user
    # reads as "Could not connect to the class", so a failure here has to stop
    # the join rather than hand out a token that cannot work.
    try:
        await lk.ensure_room(session.room_name, metadata={
            "session_id": session.id,
            "class_name": session.class_name,
            "section": session.section,
            "subject": session.subject,
        })
    except lk.LiveKitUnavailable:
        raise HTTPException(
            status_code=503,
            detail="The class server is unavailable right now. Please try again in a moment.",
        )
    except Exception as exc:
        logger.error("[ONLINE CLASS] could not create room %s: %s", session.room_name, exc)
        raise HTTPException(
            status_code=503,
            detail="The classroom could not be opened. Please try again in a moment.",
        )

    token = lk.create_access_token(
        identity=user.id,
        display_name=user.name,
        room=session.room_name,
        can_publish=bool(sources),
        can_publish_data=True,
        metadata={
            "role": role,
            "class_name": session.class_name,
            "section": session.section,
            "young_mode": bool(session.young_mode),
        },
    )
    return {
        "token": token,
        "url": lk.public_url(),
        "identity": user.id,
        "role": role,
        "can_speak": "microphone" in sources,
        "can_camera": "camera" in sources,
        "can_share_screen": "screen_share" in sources,
    }


def _matches_student(session: OnlineClassSession, user: User) -> bool:
    """Class/section matching runs in Python because "Grade 5" and "Class 5"
    are the same class and SQL cannot know that."""
    allowed, _ = class_matching.student_may_join(user, session)
    return allowed


# ─── Teacher: start / end ─────────────────────────────────────────────────────

@router.post("/start")
@limiter.limit("20/minute")
async def start_class(
    request: Request,
    body: StartClassRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """START CLASS. Creates the room, or rejoins the one already running."""
    class_name = normalize_class(body.class_name) or body.class_name.strip()
    section = normalize_section(body.section)
    subject = (body.subject or "").strip()
    if not class_name or not subject:
        raise HTTPException(status_code=400, detail="Class and subject are required.")

    if user.role == "teacher":
        allowed, reason = class_matching.teacher_may_teach(user, class_name, section, subject)
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

    settings = await get_settings(db)

    # Pressing START twice must not open a second room.
    existing = (await db.execute(
        select(OnlineClassSession).where(
            OnlineClassSession.teacher_id == user.id,
            OnlineClassSession.status == SESSION_LIVE,
        )
    )).scalars().all()

    session = next(
        (s for s in existing
         if class_matching.same_class(s.class_name, class_name)
         and class_matching.section_key(s.section) == class_matching.section_key(section)
         and s.subject == subject),
        None,
    )

    if session is None:
        # A teacher can only be in one classroom at a time; close any other.
        for stale in existing:
            await _end_session(db, stale, reason="teacher_started_another", actor=user)

        session = OnlineClassSession(
            teacher_id=user.id,
            teacher_name=user.name,
            subject=subject,
            class_name=class_name,
            section=section,
            title=(body.title or "").strip() or f"{subject} — {class_name}",
            status=SESSION_LIVE,
            room_name="",  # filled once the id exists
            actual_start=utcnow(),
            planned_duration_minutes=max(5, min(300, body.planned_duration_minutes or 40)),
            young_mode=class_matching.is_young_class(class_name, settings.young_classes),
            mic_locked=True,
            lesson_plan_id=body.lesson_plan_id,
        )
        db.add(session)
        await db.flush()
        session.room_name = lk.room_name_for(session.id)

        await class_events.record(
            db, session.id, class_events.CLASS_STARTED,
            actor_id=user.id, actor_role=user.role,
            payload={"class_name": class_name, "section": section, "subject": subject},
        )
        await db.commit()
        await db.refresh(session)

    payload = await _issue_token(session, user, role="teacher", sources=TEACHER_SOURCES)
    payload["session"] = session.to_dict(include_state=True)
    return payload


@router.post("/{session_id}/end")
async def end_class(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """END CLASS FOR EVERYONE."""
    session = await _get_session(db, session_id)
    _require_host(session, user)

    if session.status == SESSION_ENDED:
        return {"message": "Class already ended.", "session": session.to_dict()}

    await _end_session(db, session, reason=user.role, actor=user)
    return {"message": "Class ended.", "session": session.to_dict()}


@router.get("/teacher/sessions")
async def teacher_sessions(
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """The teacher's live class (if any) plus what they taught today."""
    settings = await get_settings(db)
    since = utcnow() - timedelta(hours=24)

    result = await db.execute(
        select(OnlineClassSession)
        .where(
            OnlineClassSession.teacher_id == user.id,
            OnlineClassSession.created_at >= since,
        )
        .order_by(OnlineClassSession.created_at.desc())
    )
    sessions = list(result.scalars().all())

    closed_any = False
    for session in sessions:
        closed_any = await _close_if_abandoned(db, session, settings) or closed_any
    if closed_any:
        await db.commit()

    live = [s.to_dict() for s in sessions if s.status == SESSION_LIVE]
    recent = [s.to_dict() for s in sessions if s.status != SESSION_LIVE]
    return {"live": live, "recent": recent}


# ─── Student: today's classes / join ──────────────────────────────────────────

@router.get("/student/today")
async def student_today(
    user: User = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    """TODAY'S CLASSES — what this student can join right now, and what is done."""
    settings = await get_settings(db)
    since = utcnow() - timedelta(hours=16)

    result = await db.execute(
        select(OnlineClassSession)
        .where(OnlineClassSession.created_at >= since)
        .order_by(OnlineClassSession.created_at.desc())
    )
    sessions = [s for s in result.scalars().all() if _matches_student(s, user)]

    closed_any = False
    for session in sessions:
        closed_any = await _close_if_abandoned(db, session, settings) or closed_any
    if closed_any:
        await db.commit()

    return {
        "young_mode": class_matching.is_young_class(user.class_name, settings.young_classes),
        "live": [s.to_dict() for s in sessions if s.status == SESSION_LIVE],
        "finished": [s.to_dict() for s in sessions if s.status == SESSION_ENDED],
    }


@router.post("/{session_id}/join")
@limiter.limit("30/minute")
async def join_class(
    request: Request,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """JOIN CLASS. The student presses one button; everything else is checked here."""
    session = await _get_session(db, session_id)
    settings = await get_settings(db)

    if await _close_if_abandoned(db, session, settings):
        await db.commit()

    if session.status != SESSION_LIVE:
        raise HTTPException(status_code=409, detail="This class is not live.")

    # The teacher rejoining their own room (e.g. after a reconnect).
    if user.id == session.teacher_id:
        payload = await _issue_token(session, user, role="teacher", sources=TEACHER_SOURCES)
        payload["session"] = session.to_dict(include_state=True)
        return payload

    allowed, reason = class_matching.student_may_join(user, session)
    if not allowed:
        await class_events.record(
            db, session.id, class_events.JOIN_DENIED,
            actor_id=user.id, actor_role=user.role, payload={"reason": reason},
            commit=True,
        )
        raise HTTPException(status_code=403, detail=reason)

    # A locked classroom stops new entrants, not someone reconnecting.
    if session.is_locked:
        already = (await db.execute(
            select(OnlineClassParticipant).where(
                OnlineClassParticipant.session_id == session.id,
                OnlineClassParticipant.user_id == user.id,
            )
        )).scalar_one_or_none()
        if not already:
            raise HTTPException(status_code=403, detail="The teacher has locked this class.")

    # An individual grant survives a reconnect: a student who was allowed to
    # answer a question should not be silenced by their own connection dropping,
    # and the room-wide microphone lock is exactly what the grant overrides.
    grant = await classroom_state.get_grant(session.id, user.id)
    sources = classroom_state.publish_sources(grant, cameras_locked=session.cameras_locked)

    payload = await _issue_token(session, user, role="student", sources=sources)
    payload["session"] = session.to_dict(include_state=True)

    await class_events.record(
        db, session.id, class_events.TOKEN_ISSUED,
        actor_id=user.id, actor_role=user.role, commit=True,
    )
    return payload


@router.post("/{session_id}/leave")
async def leave_class(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Best-effort leave notice. The media server's webhook is authoritative;
    this just closes the interval immediately when the browser is polite."""
    session = await _get_session(db, session_id)
    await attendance_service.record_leave(db, session, user.id, reason="left")
    await classroom_state.lower_hand(session.id, user.id)
    await db.commit()
    return {"message": "Left the class."}


# ─── Raise hand ───────────────────────────────────────────────────────────────

@router.post("/{session_id}/hand")
@limiter.limit("30/minute")
async def raise_hand(
    request: Request,
    session_id: str,
    body: HandRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    if session.status != SESSION_LIVE:
        raise HTTPException(status_code=409, detail="This class is not live.")

    if user.role == "student":
        allowed, reason = class_matching.student_may_join(user, session)
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

    if body.raised:
        await classroom_state.raise_hand(session.id, user.id, user.name)
    else:
        await classroom_state.lower_hand(session.id, user.id)

    await class_events.record(
        db, session.id,
        class_events.HAND_RAISED if body.raised else class_events.HAND_LOWERED,
        actor_id=user.id, actor_role=user.role, commit=True,
    )

    hands = await classroom_state.list_hands(session.id)
    await lk.broadcast_safely(session.room_name, {"t": "hands", "hands": hands})
    return {"raised": body.raised, "hands": hands}


# ─── Live state (polling fallback for the realtime channel) ───────────────────

@router.get("/{session_id}/state")
async def class_state(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current classroom state.

    Clients receive state changes instantly over the data channel; this is the
    fallback they poll on a slow timer and re-read after a reconnect, so a
    dropped message never leaves a classroom out of step.
    """
    session = await _get_session(db, session_id)

    is_host = user.role == "admin" or session.teacher_id == user.id
    if not is_host and user.role == "student":
        allowed, reason = class_matching.student_may_join(user, session)
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

    settings = await get_settings(db)
    state = {
        "session": session.to_dict(include_state=True),
        "hands": await classroom_state.list_hands(session.id),
        # Drives whether the classroom shows a Record button at all. A control
        # that only fails when pressed is worse than no control (spec §9).
        "recording_available": bool(
            settings.recording_enabled_globally and lk.recording_configured()
        ),
    }

    if is_host:
        state["grants"] = await classroom_state.list_grants(session.id)
        state["attendance"] = await attendance_service.attendance_for_session(db, session)
        try:
            state["connected"] = await lk.list_participants(session.room_name)
        except Exception as exc:
            logger.warning("[ONLINE CLASS] participant list unavailable: %s", exc)
            state["connected"] = []
    else:
        state["grant"] = await classroom_state.get_grant(session.id, user.id)

    return state


# ─── Teacher classroom controls (spec §12) ────────────────────────────────────

@router.post("/{session_id}/controls/mute-all")
async def mute_all(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    _require_host(session, user)

    session.mic_locked = True
    await classroom_state.clear_grants(session.id)

    muted = 0
    try:
        for participant in await lk.list_participants(session.room_name):
            if participant["identity"] == session.teacher_id:
                continue
            await lk.set_participant_permissions(session.room_name, participant["identity"], sources=[])
            muted += await lk.mute_participant(session.room_name, participant["identity"], muted=True)
    except lk.LiveKitUnavailable:
        raise HTTPException(status_code=503, detail="The classroom server is unavailable.")
    except Exception as exc:
        logger.warning("[ONLINE CLASS] mute-all partial failure: %s", exc)

    await class_events.record(
        db, session.id, class_events.MUTE_ALL,
        actor_id=user.id, actor_role=user.role, payload={"tracks_muted": muted}, commit=True,
    )
    await lk.broadcast_safely(session.room_name, {"t": "mute_all"})
    return {"message": "All students muted.", "tracks_muted": muted}


@router.post("/{session_id}/controls/permissions")
async def set_permissions(
    session_id: str,
    body: PermissionRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Allow or withdraw one student's microphone / camera."""
    session = await _get_session(db, session_id)
    _require_host(session, user)

    # An individual grant overrides the room-wide microphone lock — that is
    # precisely what "allow this student to answer" means. A room-wide camera
    # lock is not overridden: it exists to keep 30 video streams off the wire.
    mic = bool(body.mic)
    camera = bool(body.camera) and not session.cameras_locked

    sources = []
    if mic:
        sources.append("microphone")
    if camera:
        sources.append("camera")

    await classroom_state.set_grant(session.id, body.user_id, mic=mic, camera=camera)

    try:
        await lk.set_participant_permissions(session.room_name, body.user_id, sources=sources)
        if not mic:
            await lk.mute_participant(session.room_name, body.user_id, muted=True)
    except lk.LiveKitUnavailable:
        raise HTTPException(status_code=503, detail="The classroom server is unavailable.")
    except Exception as exc:
        logger.warning("[ONLINE CLASS] permission update failed: %s", exc)

    await classroom_state.lower_hand(session.id, body.user_id)
    await class_events.record(
        db, session.id,
        class_events.MIC_GRANTED if mic else class_events.MIC_REVOKED,
        actor_id=user.id, actor_role=user.role,
        payload={"student_id": body.user_id, "mic": mic, "camera": camera},
        commit=True,
    )

    await lk.broadcast_safely(session.room_name, {
        "t": "grant", "user_id": body.user_id, "mic": mic, "camera": camera,
    })
    await lk.broadcast_safely(session.room_name, {
        "t": "hands", "hands": await classroom_state.list_hands(session.id),
    })
    return {"user_id": body.user_id, "mic": mic, "camera": camera}


@router.post("/{session_id}/controls/mute")
async def mute_student(
    session_id: str,
    body: TargetRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    _require_host(session, user)

    await classroom_state.set_grant(session.id, body.user_id, mic=False, camera=False)
    try:
        await lk.set_participant_permissions(session.room_name, body.user_id, sources=[])
        await lk.mute_participant(session.room_name, body.user_id, muted=True)
    except lk.LiveKitUnavailable:
        raise HTTPException(status_code=503, detail="The classroom server is unavailable.")

    await class_events.record(
        db, session.id, class_events.STUDENT_MUTED,
        actor_id=user.id, actor_role=user.role, payload={"student_id": body.user_id}, commit=True,
    )
    await lk.broadcast_safely(session.room_name, {
        "t": "grant", "user_id": body.user_id, "mic": False, "camera": False,
    })
    return {"message": "Student muted."}


@router.post("/{session_id}/controls/lock")
async def lock_classroom(
    session_id: str,
    body: ToggleRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    _require_host(session, user)

    session.is_locked = bool(body.locked)
    await class_events.record(
        db, session.id, class_events.CLASS_LOCKED,
        actor_id=user.id, actor_role=user.role, payload={"locked": session.is_locked}, commit=True,
    )
    return {"locked": session.is_locked}


@router.post("/{session_id}/controls/cameras")
async def lock_cameras(
    session_id: str,
    body: ToggleRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Disable (or re-allow) student cameras for the whole class."""
    session = await _get_session(db, session_id)
    _require_host(session, user)

    session.cameras_locked = bool(body.locked)
    if session.cameras_locked:
        grants = await classroom_state.list_grants(session.id)
        for user_id, grant in grants.items():
            await classroom_state.set_grant(session.id, user_id, mic=bool(grant.get("mic")), camera=False)
            try:
                sources = ["microphone"] if grant.get("mic") else []
                await lk.set_participant_permissions(session.room_name, user_id, sources=sources)
            except Exception as exc:
                logger.warning("[ONLINE CLASS] camera lock failed for %s: %s", user_id, exc)

    await class_events.record(
        db, session.id, class_events.CAMERAS_LOCKED,
        actor_id=user.id, actor_role=user.role, payload={"locked": session.cameras_locked}, commit=True,
    )
    await lk.broadcast_safely(session.room_name, {"t": "cameras", "locked": session.cameras_locked})
    return {"cameras_locked": session.cameras_locked}


@router.post("/{session_id}/controls/remove")
async def remove_student(
    session_id: str,
    body: TargetRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    _require_host(session, user)

    if body.user_id == session.teacher_id:
        raise HTTPException(status_code=400, detail="The teacher cannot be removed.")

    try:
        await lk.remove_participant(session.room_name, body.user_id)
    except lk.LiveKitUnavailable:
        raise HTTPException(status_code=503, detail="The classroom server is unavailable.")
    except Exception as exc:
        logger.warning("[ONLINE CLASS] remove failed for %s: %s", body.user_id, exc)

    await attendance_service.record_leave(db, session, body.user_id, reason="removed")
    await classroom_state.set_grant(session.id, body.user_id, mic=False, camera=False)
    await classroom_state.lower_hand(session.id, body.user_id)
    await class_events.record(
        db, session.id, class_events.STUDENT_REMOVED,
        actor_id=user.id, actor_role=user.role, payload={"student_id": body.user_id}, commit=True,
    )
    return {"message": "Student removed from the class."}


@router.post("/{session_id}/controls/hand")
async def lower_student_hand(
    session_id: str,
    body: TargetRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    _require_host(session, user)

    await classroom_state.lower_hand(session.id, body.user_id)
    hands = await classroom_state.list_hands(session.id)
    await lk.broadcast_safely(session.room_name, {"t": "hands", "hands": hands})
    return {"hands": hands}


# ─── Attendance ───────────────────────────────────────────────────────────────

@router.get("/{session_id}/attendance")
async def session_attendance(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_session(db, session_id)
    _require_host(session, user)
    return {
        "session": session.to_dict(),
        "rows": await attendance_service.attendance_for_session(db, session),
    }
