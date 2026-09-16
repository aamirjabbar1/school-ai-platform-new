"""
Class recordings (spec §15).

A recording is an ordinary audio/video file of a lesson. The recorder writes it
straight to object storage; this module starts and stops it, decides who may
watch it, and streams it back.

What it deliberately does not do: transcribe. No recording is sent to any
speech, translation or AI service — there is no code path from this module to
the AI layer, which is the only way to make that guarantee mean something.

Access is by class and section, and every playback URL is a short-lived token
rather than a public link: these are recordings of children.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from config.settings import RECORDING_BUCKET
from middleware.auth import create_scoped_token, get_current_user, require_roles, user_from_request
from models.models import User, utcnow
from models.online_classes import (
    SESSION_LIVE,
    OnlineClassRecording,
    OnlineClassSession,
)
from services import class_events, class_matching, storage_service
from services import livekit_service as lk
from services.classroom_access import get_session, require_host
from services.online_class_config import get_settings

logger = logging.getLogger("agent")

router = APIRouter(prefix="/online-classes", tags=["online-classes"])


def _object_key(session: OnlineClassSession) -> str:
    """Recordings are filed the way a school thinks about them: session, then
    class, subject and date — so the storage layout is browsable by a human."""
    date = (session.actual_start or utcnow()).strftime("%Y/%m/%d")
    safe_subject = "".join(c if c.isalnum() else "_" for c in (session.subject or "class"))
    return f"{date}/{session.class_name}/{safe_subject}/{session.id}.mp4"


# ─── Start / stop ─────────────────────────────────────────────────────────────

@router.post("/{session_id}/recording/start")
async def start_recording(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_host(session, user)

    if session.status != SESSION_LIVE:
        raise HTTPException(status_code=409, detail="This class is not live.")

    settings = await get_settings(db)
    if not settings.recording_enabled_globally:
        raise HTTPException(status_code=403, detail="Recording is switched off for the school.")
    if not lk.recording_configured():
        raise HTTPException(status_code=503, detail="Recording storage is not configured.")

    if session.recording_status in ("starting", "recording"):
        return {"status": session.recording_status, "message": "Already recording."}

    # Each recording occupies a whole CPU on the media host; without a cap, a
    # busy period would starve the live classes of the capacity they need.
    active = (await db.execute(
        select(OnlineClassRecording).where(
            OnlineClassRecording.status.in_(("starting", "recording"))
        )
    )).scalars().all()
    if len(active) >= (settings.max_concurrent_recordings or 2):
        raise HTTPException(
            status_code=429,
            detail="Too many classes are recording right now. Please try again shortly.",
        )

    object_key = _object_key(session)
    try:
        egress_id = await lk.start_recording(session.room_name, object_key)
    except lk.LiveKitUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.warning("[RECORDING] start failed for %s: %s", session.id, exc)
        raise HTTPException(status_code=502, detail="The recorder could not be started.")

    retention = settings.recording_retention_days or 30
    recording = OnlineClassRecording(
        session_id=session.id,
        egress_id=egress_id,
        bucket=RECORDING_BUCKET,
        object_name=object_key,
        status="recording",
        started_at=utcnow(),
        retention_days=retention,
        # Retention of 0 means "keep until an administrator deletes it".
        expires_at=(utcnow() + timedelta(days=retention)) if retention else None,
    )
    db.add(recording)

    session.recording_enabled = True
    session.recording_status = "recording"
    await class_events.record(
        db, session.id, class_events.RECORDING_STARTED,
        actor_id=user.id, actor_role=user.role, payload={"egress_id": egress_id},
    )
    await db.commit()

    await lk.broadcast_safely(session.room_name, {"t": "recording", "active": True})
    return {"status": "recording", "recording_id": recording.id}


@router.post("/{session_id}/recording/stop")
async def stop_recording(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_host(session, user)

    recording = (await db.execute(
        select(OnlineClassRecording)
        .where(
            OnlineClassRecording.session_id == session.id,
            OnlineClassRecording.status.in_(("starting", "recording")),
        )
        .order_by(OnlineClassRecording.created_at.desc())
    )).scalars().first()

    if not recording:
        session.recording_status = "off"
        await db.commit()
        return {"status": "off", "message": "Nothing was recording."}

    try:
        await lk.stop_recording(recording.egress_id)
    except Exception as exc:
        logger.warning("[RECORDING] stop failed for %s: %s", recording.id, exc)

    recording.status = "processing"
    recording.ended_at = utcnow()
    session.recording_status = "stopping"
    await class_events.record(
        db, session.id, class_events.RECORDING_STOPPED,
        actor_id=user.id, actor_role=user.role,
    )
    await db.commit()

    await lk.broadcast_safely(session.room_name, {"t": "recording", "active": False})
    return {"status": "processing"}


# ─── Watching ─────────────────────────────────────────────────────────────────

@router.get("/recordings")
async def list_recordings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """RECORDED CLASSES — only the ones this person is entitled to see."""
    result = await db.execute(
        select(OnlineClassRecording, OnlineClassSession)
        .join(OnlineClassSession, OnlineClassRecording.session_id == OnlineClassSession.id)
        .where(
            OnlineClassRecording.status == "ready",
            OnlineClassRecording.deleted_at.is_(None),
        )
        .order_by(OnlineClassSession.actual_start.desc())
        .limit(200)
    )

    out = []
    for recording, session in result.all():
        if not _may_watch(user, session):
            continue
        out.append({
            **recording.to_dict(),
            "subject": session.subject,
            "class_name": session.class_name,
            "section": session.section,
            "teacher_name": session.teacher_name,
            "class_date": session.actual_start.isoformat() if session.actual_start else None,
            "session_id": session.id,
        })
    return {"recordings": out}


def _may_watch(user: User, session: OnlineClassSession) -> bool:
    if user.role == "admin":
        return True
    if user.role == "teacher":
        return session.teacher_id == user.id
    allowed, _ = class_matching.student_may_join(user, session)
    return allowed


@router.get("/recordings/{recording_id}/token")
async def recording_token(
    recording_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A short-lived key so a <video> element can stream the file directly."""
    recording, session = await _recording_with_session(db, recording_id)
    if not _may_watch(user, session):
        raise HTTPException(status_code=403, detail="This recording is not for your class.")

    return {
        "token": create_scoped_token(
            user.id, scope="resource", session_id=recording.id, minutes=180
        ),
        "url": f"/online-classes/recordings/{recording.id}/stream",
    }


@router.get("/recordings/{recording_id}/stream")
async def stream_recording(
    request: Request,
    recording_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Stream a recording, honouring range requests so students can seek."""
    recording, session = await _recording_with_session(db, recording_id)
    user = await user_from_request(request, db, session_id=recording.id)
    if not _may_watch(user, session):
        raise HTTPException(status_code=403, detail="This recording is not for your class.")
    if recording.deleted_at or not recording.object_name:
        raise HTTPException(status_code=404, detail="This recording is no longer available.")

    bucket = recording.bucket or RECORDING_BUCKET
    try:
        stat = await asyncio.to_thread(storage_service.stat_object, recording.object_name, bucket)
        size = int(stat.size)
    except Exception:
        raise HTTPException(status_code=404, detail="This recording is no longer available.")

    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        start, end = _parse_range(range_header, size)
        if start is None:
            raise HTTPException(status_code=416, detail="Invalid range")
        # Cap a single response so one student seeking does not pull a whole
        # lesson through the API container in one request.
        end = min(end, start + 4 * 1024 * 1024 - 1)
        chunk = await asyncio.to_thread(
            storage_service.read_range, recording.object_name, start, end - start + 1, bucket
        )
        return Response(
            content=chunk,
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
                "Cache-Control": "private, max-age=600",
            },
        )

    data = await asyncio.to_thread(storage_service.download_file, recording.object_name, bucket)
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=600"},
    )


async def _recording_with_session(db: AsyncSession, recording_id: str):
    row = (await db.execute(
        select(OnlineClassRecording, OnlineClassSession)
        .join(OnlineClassSession, OnlineClassRecording.session_id == OnlineClassSession.id)
        .where(OnlineClassRecording.id == recording_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    return row[0], row[1]


def _parse_range(header: str, size: int) -> tuple[int | None, int | None]:
    try:
        spec = header.split("=", 1)[1].split(",")[0].strip()
        start_text, _, end_text = spec.partition("-")
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            start = max(0, size - int(end_text))
            end = size - 1
        if start > end or start >= size:
            return None, None
        return start, min(end, size - 1)
    except (ValueError, IndexError):
        return None, None
