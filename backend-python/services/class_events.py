"""
Structured classroom event recorder.

Every meaningful classroom action is written here as it happens: pages
presented, resources opened, boards saved, microphones granted, students
removed. Two reasons this matters beyond an audit trail:

  * The lesson record and the AI layer are built from these rows. Because the
    application already knows what happened, nothing has to be inferred later —
    and specifically, nothing has to be inferred from what anyone said. There is
    no Speech-to-Text in this system, by design.
  * It gives administrators a truthful account of a class (who started it, what
    was shown, what failed) without recording anything private.

Writes are deliberately forgiving: an event that cannot be recorded must never
take a live classroom down with it.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.online_classes import OnlineClassEvent

logger = logging.getLogger("agent")

# Event vocabulary — kept here so producers and consumers agree on the spelling.
CLASS_STARTED = "class_started"
CLASS_ENDED = "class_ended"
TOKEN_ISSUED = "token_issued"
JOIN_DENIED = "join_denied"
HAND_RAISED = "hand_raised"
HAND_LOWERED = "hand_lowered"
MIC_GRANTED = "mic_granted"
MIC_REVOKED = "mic_revoked"
MUTE_ALL = "mute_all"
STUDENT_MUTED = "student_muted"
STUDENT_REMOVED = "student_removed"
CLASS_LOCKED = "class_locked"
CAMERAS_LOCKED = "cameras_locked"
STAGE_CHANGED = "stage_changed"
BOOK_OPENED = "book_opened"
PAGE_PRESENTED = "page_presented"
RESOURCE_OPENED = "resource_opened"
WHITEBOARD_SAVED = "whiteboard_saved"
SCREEN_SHARE_STARTED = "screen_share_started"
SCREEN_SHARE_STOPPED = "screen_share_stopped"
VIDEO_SHARED = "video_shared"
RECORDING_STARTED = "recording_started"
RECORDING_STOPPED = "recording_stopped"
ADMIN_OBSERVED = "admin_observed"
TEACHER_DISCONNECTED = "teacher_disconnected"
TEACHER_RECONNECTED = "teacher_reconnected"


async def record(
    db: AsyncSession,
    session_id: str,
    event_type: str,
    *,
    actor_id: str | None = None,
    actor_role: str | None = None,
    payload: dict[str, Any] | None = None,
    commit: bool = False,
) -> OnlineClassEvent | None:
    """Append one classroom event. Never raises."""
    try:
        event = OnlineClassEvent(
            session_id=session_id,
            actor_id=actor_id,
            actor_role=actor_role,
            type=event_type,
            payload=payload or {},
        )
        db.add(event)
        if commit:
            await db.commit()
        return event
    except Exception as exc:  # pragma: no cover - logging must not break a class
        logger.warning("[CLASS EVENT] failed to record %s for %s: %s", event_type, session_id, exc)
        return None
