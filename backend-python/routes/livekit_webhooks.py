"""
LiveKit webhook receiver — the source of truth for attendance.

The media server reports every join and leave here, which is why online
attendance needs nobody to mark a register: the same events that move a student
into a room move them into the attendance ledger.

This endpoint is deliberately not bearer-authenticated — it is called by the
media server, not by a user — so it authenticates the *delivery* instead: each
request carries a JWT signed with the LiveKit API secret whose digest must match
the body. An unsigned or tampered request is rejected before it can touch the
database.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from models.models import utcnow
from models.online_classes import SESSION_ENDED, SESSION_LIVE, OnlineClassSession
from services import attendance_service, class_events, classroom_state
from services import livekit_service as lk

logger = logging.getLogger("agent")

router = APIRouter(prefix="/livekit", tags=["online-classes"])


def _event_time(payload: dict):
    """Use the media server's own timestamp when it sends one.

    Attendance arithmetic should reflect when a student actually dropped, not
    when the notification happened to reach us over a shaky link.
    """
    raw = payload.get("createdAt") or payload.get("created_at")
    try:
        if raw:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        pass
    return utcnow()


def _participant_role(participant: dict, session, identity: str) -> str:
    """Who just joined, according to the token we minted for them.

    An observing administrator must not land in the attendance register as if
    they were a pupil, so the role travels in the token's metadata rather than
    being guessed from who is not the teacher.
    """
    if identity == session.teacher_id:
        return "teacher"

    raw = participant.get("metadata")
    if raw:
        try:
            role = json.loads(raw).get("role")
            if role in ("teacher", "student", "observer"):
                return role
        except (ValueError, AttributeError):
            pass
    return "student"


async def _session_for_room(db: AsyncSession, room_name: str) -> OnlineClassSession | None:
    if not room_name:
        return None
    result = await db.execute(
        select(OnlineClassSession).where(OnlineClassSession.room_name == room_name)
    )
    return result.scalar_one_or_none()


@router.post("/webhook")
async def livekit_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    try:
        payload = lk.verify_webhook(body, authorization)
    except ValueError as exc:
        logger.warning("[LIVEKIT WEBHOOK] rejected: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    except lk.LiveKitUnavailable as exc:
        logger.warning("[LIVEKIT WEBHOOK] not configured: %s", exc)
        raise HTTPException(status_code=503, detail="Online Classes is not configured")

    event = payload.get("event")
    room = (payload.get("room") or {}).get("name")
    participant = payload.get("participant") or {}
    identity = participant.get("identity")
    at = _event_time(payload)

    session = await _session_for_room(db, room)
    if not session:
        # Rooms we do not own (or a class already purged) are simply ignored.
        return {"handled": False}

    if event == "participant_joined" and identity:
        role = _participant_role(participant, session, identity)
        await attendance_service.record_join(
            db, session, identity, role=role, participant_sid=participant.get("sid"), at=at,
        )
        if role == "teacher" and session.teacher_disconnected_at:
            session.teacher_disconnected_at = None
            await class_events.record(
                db, session.id, class_events.TEACHER_RECONNECTED,
                actor_id=identity, actor_role="teacher",
            )
        await db.commit()
        return {"handled": True}

    if event == "participant_left" and identity:
        await attendance_service.record_leave(db, session, identity, reason="disconnected", at=at)
        await classroom_state.lower_hand(session.id, identity)

        if identity == session.teacher_id and session.status == SESSION_LIVE:
            # The class survives a teacher's connection dropping: the room stays
            # open for the configured grace period so a reconnect lands the
            # students back in the same lesson instead of an empty screen.
            session.teacher_disconnected_at = at
            await class_events.record(
                db, session.id, class_events.TEACHER_DISCONNECTED,
                actor_id=identity, actor_role="teacher",
            )
        await db.commit()
        return {"handled": True}

    if event and event.startswith("egress_"):
        await _handle_egress(db, session, event, payload)
        return {"handled": True}

    if event == "room_finished":
        if session.status == SESSION_LIVE:
            # The room ended without anyone pressing End Class (server restart,
            # last participant gone). Close the register so the class is not
            # left hanging in a live state forever.
            session.status = SESSION_ENDED
            session.actual_end = at
            session.end_reason = session.end_reason or "room_finished"
            await class_events.record(
                db, session.id, class_events.CLASS_ENDED,
                actor_role="system", payload={"reason": "room_finished"},
            )
            await attendance_service.finalize_session(db, session)
            await classroom_state.clear_session(session.id)
        return {"handled": True}

    return {"handled": False, "event": event}


async def _handle_egress(db: AsyncSession, session, event: str, payload: dict) -> None:
    """Track a recording through its lifecycle.

    The recorder uploads the file itself, so all we learn here is whether it
    worked, how long it ran and how big it is. The file is never opened by this
    application, and never handed to an AI service.
    """
    from sqlalchemy import select as sa_select
    from models.online_classes import OnlineClassRecording

    info = payload.get("egressInfo") or payload.get("egress_info") or {}
    egress_id = info.get("egressId") or info.get("egress_id")
    if not egress_id:
        return

    recording = (await db.execute(
        sa_select(OnlineClassRecording).where(OnlineClassRecording.egress_id == egress_id)
    )).scalar_one_or_none()
    if not recording:
        return

    if event == "egress_started":
        recording.status = "recording"
        session.recording_status = "recording"

    elif event == "egress_updated":
        state = str(info.get("status") or "")
        if "ACTIVE" in state:
            recording.status = "recording"

    elif event == "egress_ended":
        state = str(info.get("status") or "")
        results = info.get("fileResults") or info.get("file_results") or []
        first = results[0] if results else {}

        if "COMPLETE" in state and first:
            recording.status = "ready"
            recording.size_bytes = _as_int(first.get("size"))
            # LiveKit reports duration in nanoseconds.
            duration_ns = _as_int(first.get("duration"))
            recording.duration_seconds = int(duration_ns / 1_000_000_000) if duration_ns else None
            if first.get("filename"):
                recording.object_name = str(first["filename"]).lstrip("/")
            session.recording_status = "done"
        else:
            recording.status = "failed"
            recording.error = str(info.get("error") or state or "Recording failed")[:1000]
            session.recording_status = "failed"

        recording.ended_at = recording.ended_at or utcnow()

    await db.commit()


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
