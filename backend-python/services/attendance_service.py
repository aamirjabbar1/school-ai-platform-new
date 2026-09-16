"""
Automatic attendance (spec §13).

Attendance is assembled from the media server's own join and leave webhooks —
plain application logic over timestamps, with no AI involved and nothing for a
teacher to tick off. A student who drops out and comes back is credited for the
time they were actually connected, which is the whole point on connections that
fluctuate:

    Joined 08:03 · disconnected 08:37 · rejoined 08:40 · left 08:48
    → 42 minutes of a 45-minute class → 93.3% → present

Two rules keep the numbers honest:

  * Every join/leave is appended to `online_class_attendance_events`, so a
    disputed register can always be traced back to the raw evidence.
  * `total_seconds` only ever accumulates *closed* intervals. A student still
    connected has their live interval added on read, so the register is never
    inflated by a session that was never properly closed.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import User, utcnow
from models.online_classes import (
    ATTEND_ABSENT,
    ATTEND_LATE,
    ATTEND_PARTIAL,
    ATTEND_PRESENT,
    OnlineClassAttendanceEvent,
    OnlineClassParticipant,
    OnlineClassSession,
)
from services import class_matching
from services.online_class_config import get_settings

logger = logging.getLogger("agent")


# ─── Recording presence ───────────────────────────────────────────────────────

async def _get_or_create_participant(
    db: AsyncSession,
    session: OnlineClassSession,
    user: User | None,
    user_id: str,
    role: str,
) -> OnlineClassParticipant:
    result = await db.execute(
        select(OnlineClassParticipant).where(
            OnlineClassParticipant.session_id == session.id,
            OnlineClassParticipant.user_id == user_id,
        )
    )
    participant = result.scalar_one_or_none()
    if participant:
        return participant

    participant = OnlineClassParticipant(
        session_id=session.id,
        user_id=user_id,
        role=role,
        user_name=user.name if user else None,
        class_name=(user.class_name if user else None) or session.class_name,
        section=(user.section if user else None) or session.section,
    )
    db.add(participant)
    await db.flush()
    return participant


async def record_join(
    db: AsyncSession,
    session: OnlineClassSession,
    user_id: str,
    *,
    role: str = "student",
    participant_sid: str | None = None,
    at=None,
) -> OnlineClassParticipant:
    """Register that a user connected (or reconnected)."""
    at = at or utcnow()

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    participant = await _get_or_create_participant(db, session, user, user_id, role)

    is_rejoin = participant.first_join_at is not None
    if not is_rejoin:
        participant.first_join_at = at
    else:
        participant.rejoin_count = (participant.rejoin_count or 0) + 1

    participant.last_join_at = at
    participant.is_connected = True

    db.add(OnlineClassAttendanceEvent(
        session_id=session.id,
        user_id=user_id,
        event="rejoin" if is_rejoin else "join",
        at=at,
        participant_sid=participant_sid,
    ))
    return participant


async def record_leave(
    db: AsyncSession,
    session: OnlineClassSession,
    user_id: str,
    *,
    reason: str | None = None,
    at=None,
) -> OnlineClassParticipant | None:
    """Close a connected interval and bank the time it was worth."""
    at = at or utcnow()

    result = await db.execute(
        select(OnlineClassParticipant).where(
            OnlineClassParticipant.session_id == session.id,
            OnlineClassParticipant.user_id == user_id,
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        return None

    if participant.is_connected and participant.last_join_at:
        seconds = int((at - participant.last_join_at).total_seconds())
        if seconds > 0:
            participant.total_seconds = (participant.total_seconds or 0) + seconds

    participant.is_connected = False
    participant.last_leave_at = at

    db.add(OnlineClassAttendanceEvent(
        session_id=session.id,
        user_id=user_id,
        event="leave",
        at=at,
        reason=reason,
    ))
    return participant


# ─── Scoring ──────────────────────────────────────────────────────────────────

def connected_seconds(participant: OnlineClassParticipant, now=None) -> int:
    """Banked time plus the interval currently in progress, if any."""
    total = participant.total_seconds or 0
    if participant.is_connected and participant.last_join_at:
        total += max(0, int(((now or utcnow()) - participant.last_join_at).total_seconds()))
    return total


def score(
    participant: OnlineClassParticipant,
    session: OnlineClassSession,
    settings,
    now=None,
) -> tuple[float, str]:
    """Return (percentage of the whole class, status) for one participant.

    The distinction that matters to a teacher is *why* a student's percentage is
    low. Someone who joined twenty minutes into a forty-minute class and then
    stayed to the end attended everything that was left — that is lateness, not
    partial attendance, even though they can never reach the present threshold.
    So lateness is judged against the class that remained after they arrived,
    while partial means they drifted in and out of the time they were there.
    """
    duration = max(1, session.duration_seconds)
    seconds = connected_seconds(participant, now=now)
    percent = min(100.0, (seconds / duration) * 100.0)

    present_min = settings.present_min_percent or 75.0
    partial_min = settings.partial_min_percent or 25.0
    late_after = (settings.late_after_minutes or 10) * 60

    start = session.actual_start
    joined_late = bool(
        start and participant.first_join_at
        and (participant.first_join_at - start).total_seconds() > late_after
    )

    if percent >= present_min:
        return percent, ATTEND_LATE if joined_late else ATTEND_PRESENT

    # Did they attend most of what was still left when they arrived? Only once
    # they were there for a meaningful share of the lesson: appearing for the
    # final three minutes is technically "all that remained", and is absence.
    if joined_late and percent >= partial_min:
        end = session.actual_end or (now or utcnow())
        available = max(1, int((end - participant.first_join_at).total_seconds()))
        if (seconds / available) * 100.0 >= present_min:
            return percent, ATTEND_LATE

    if percent >= partial_min:
        return percent, ATTEND_PARTIAL

    return percent, ATTEND_ABSENT


# ─── Finalisation ─────────────────────────────────────────────────────────────

async def finalize_session(db: AsyncSession, session: OnlineClassSession) -> int:
    """Close the register when a class ends.

    Closes anyone still connected, scores every participant, and writes an
    explicit absent row for each enrolled student who never joined — an
    attendance register that only lists the people who turned up is not a
    register. Returns the number of rows finalised.
    """
    settings = await get_settings(db)
    now = session.actual_end or utcnow()

    result = await db.execute(
        select(OnlineClassParticipant).where(
            OnlineClassParticipant.session_id == session.id
        )
    )
    participants = list(result.scalars().all())

    for participant in participants:
        if participant.is_connected:
            await record_leave(db, session, participant.user_id, reason="class_ended", at=now)
        percent, status = score(participant, session, settings, now=now)
        participant.attendance_percent = percent
        participant.status = status if participant.role == "student" else ATTEND_PRESENT
        participant.finalized = True

    known = {p.user_id for p in participants}
    for student in await enrolled_students(db, session):
        if student.id in known:
            continue
        db.add(OnlineClassParticipant(
            session_id=session.id,
            user_id=student.id,
            role="student",
            user_name=student.name,
            class_name=student.class_name,
            section=student.section,
            total_seconds=0,
            attendance_percent=0.0,
            status=ATTEND_ABSENT,
            finalized=True,
        ))

    await db.commit()
    return len(participants)


async def enrolled_students(db: AsyncSession, session: OnlineClassSession) -> list[User]:
    """Active students belonging to this session's class and section.

    Filtered in Python rather than SQL because class names are written
    differently across the app ("Grade 5" vs "Class 5"); the shared normalizer
    is the only thing that compares them correctly.
    """
    result = await db.execute(
        select(User).where(User.role == "student", User.is_active == True)  # noqa: E712
    )
    out = []
    for student in result.scalars().all():
        if not class_matching.same_class(student.class_name, session.class_name):
            continue
        if not class_matching.same_section(session.section, student.section):
            continue
        out.append(student)
    return out


# ─── Reads ────────────────────────────────────────────────────────────────────

async def attendance_for_session(db: AsyncSession, session: OnlineClassSession) -> list[dict]:
    """The register, live-scored while the class is still running."""
    settings = await get_settings(db)
    result = await db.execute(
        select(OnlineClassParticipant)
        .where(OnlineClassParticipant.session_id == session.id)
        .order_by(OnlineClassParticipant.role.desc(), OnlineClassParticipant.user_name)
    )

    rows = []
    for participant in result.scalars().all():
        data = participant.to_dict()
        if not participant.finalized:
            percent, status = score(participant, session, settings)
            data["attendance_percent"] = round(percent, 1)
            data["status"] = status
            data["total_seconds"] = connected_seconds(participant)
            data["total_minutes"] = round(data["total_seconds"] / 60, 1)
        rows.append(data)
    return rows
