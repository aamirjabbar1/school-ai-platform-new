"""
Scheduled housekeeping for Online Classes.

Run by the `celery_beat` service. Everything here is ordinary bookkeeping —
closing classes whose teacher never came back, reminding students that a lesson
is about to start, deleting recordings whose retention period has passed. None
of it calls an AI model, and none of it touches classroom audio.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from celery_app import celery_app

logger = logging.getLogger("agent")

# How far past its planned end a live class may run before an empty room is
# treated as abandoned. Generous on purpose: a lesson that overruns is normal,
# and closing one that is still being taught would be far worse than leaving a
# stale card up for another half hour.
OVERRUN_GRACE = timedelta(minutes=30)


def is_overrun(session, now) -> bool:
    """Has this class outlived its own period by more than the grace window?

    A predicate rather than an inline condition so the rule can be tested
    without a database, a Celery worker or a media server.
    """
    if not session.actual_start:
        return False
    planned = timedelta(minutes=session.planned_duration_minutes or 40)
    return now >= session.actual_start + planned + OVERRUN_GRACE


def _run(coro):
    """Each task gets its own loop and engine — see tasks/document_tasks.py for
    why a shared engine cannot be reused across `asyncio.run()` calls."""
    return asyncio.run(coro)


def _session_factory():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from config.settings import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ─── Abandoned classes ────────────────────────────────────────────────────────

@celery_app.task(name="tasks.online_class_tasks.close_abandoned_classes")
def close_abandoned_classes():
    return _run(_close_abandoned_classes())


async def _close_abandoned_classes() -> dict:
    """End classes whose teacher disconnected and did not return.

    The room deliberately survives a teacher's connection dropping, because on a
    home connection that happens routinely mid-lesson. This closes the ones that
    were genuinely abandoned, so the register is finalised and the class stops
    showing as live to students.
    """
    from sqlalchemy import select
    from models.models import utcnow
    from models.online_classes import SESSION_LIVE, OnlineClassSession
    from services import attendance_service, class_events, classroom_state
    from services import livekit_service as lk
    from services.online_class_config import get_settings

    engine, session_factory = _session_factory()
    closed = 0
    try:
        async with session_factory() as db:
            settings = await get_settings(db)
            grace = timedelta(minutes=settings.teacher_grace_minutes or 5)
            cutoff = utcnow() - grace

            result = await db.execute(
                select(OnlineClassSession).where(
                    OnlineClassSession.status == SESSION_LIVE,
                    OnlineClassSession.teacher_disconnected_at.is_not(None),
                    OnlineClassSession.teacher_disconnected_at < cutoff,
                )
            )
            for session in result.scalars().all():
                session.status = "ended"
                session.actual_end = utcnow()
                session.end_reason = "grace_timeout"
                await class_events.record(
                    db, session.id, class_events.CLASS_ENDED,
                    actor_role="system", payload={"reason": "grace_timeout"},
                )
                await attendance_service.finalize_session(db, session)
                await classroom_state.clear_session(session.id)
                try:
                    await lk.end_room(session.room_name)
                except Exception as exc:
                    logger.warning("[BEAT] room teardown failed for %s: %s", session.id, exc)
                closed += 1

            # Classes that ran far past their planned length with nobody in them
            # are also stale; finalising them keeps the live list truthful.
            #
            # The sweep above only sees teachers who connected and then dropped.
            # A class whose teacher never connected at all has no
            # `teacher_disconnected_at`, so nothing above matches it and it stays
            # "live" forever — showing a JOIN CLASS card to a class of children
            # for a lesson that is not happening.
            overrun = (await db.execute(
                select(OnlineClassSession).where(
                    OnlineClassSession.status == SESSION_LIVE,
                    OnlineClassSession.actual_start.is_not(None),
                )
            )).scalars().all()

            for session in overrun:
                if not is_overrun(session, utcnow()):
                    continue  # still within its own period, plus room to run over

                # "With nobody in them" is checked against the media server, not
                # guessed: a long lesson that is genuinely still being taught
                # must never be closed underneath the class. An unreachable
                # media server means we do not know, so nothing is closed.
                try:
                    connected = await lk.list_participants(session.room_name)
                except Exception as exc:
                    logger.warning("[BEAT] cannot check %s, leaving it alone: %s", session.id, exc)
                    continue
                if connected:
                    continue

                session.status = "ended"
                session.actual_end = utcnow()
                session.end_reason = "overrun_empty"
                await class_events.record(
                    db, session.id, class_events.CLASS_ENDED,
                    actor_role="system", payload={"reason": "overrun_empty"},
                )
                await attendance_service.finalize_session(db, session)
                await classroom_state.clear_session(session.id)
                try:
                    await lk.end_room(session.room_name)
                except Exception as exc:
                    logger.warning("[BEAT] room teardown failed for %s: %s", session.id, exc)
                closed += 1

            await db.commit()
    finally:
        await engine.dispose()
        await _close_media_client()

    return {"closed": closed}


# ─── Timetable materialisation (spec §20) ─────────────────────────────────────

@celery_app.task(name="tasks.online_class_tasks.materialize_schedules")
def materialize_schedules():
    return _run(_materialize_schedules())


async def _materialize_schedules() -> dict:
    """Turn timetable entries that are coming up into UPCOMING classes."""
    from routes.class_schedules import materialize_due_sessions

    engine, session_factory = _session_factory()
    try:
        async with session_factory() as db:
            created = await materialize_due_sessions(db)
    finally:
        await engine.dispose()
    return {"created": created}


# ─── Reminders (spec §21) ─────────────────────────────────────────────────────

@celery_app.task(name="tasks.online_class_tasks.send_class_reminders")
def send_class_reminders():
    return _run(_send_class_reminders())


async def _send_class_reminders() -> dict:
    """Tell students about a scheduled class shortly before it starts.

    One notification per class per student, and only for classes that are
    actually scheduled — a stream of reminders trains people to ignore them.
    """
    from sqlalchemy import select
    from models.models import Notification, utcnow
    from models.online_classes import SESSION_SCHEDULED, OnlineClassSession
    from services import attendance_service

    engine, session_factory = _session_factory()
    sent = 0
    try:
        async with session_factory() as db:
            now = utcnow()
            window_end = now + timedelta(minutes=10)

            result = await db.execute(
                select(OnlineClassSession).where(
                    OnlineClassSession.status == SESSION_SCHEDULED,
                    OnlineClassSession.scheduled_start.is_not(None),
                    OnlineClassSession.scheduled_start > now,
                    OnlineClassSession.scheduled_start <= window_end,
                )
            )
            sessions = list(result.scalars().all())

            for session in sessions:
                marker = f"online-class:{session.id}"
                already = (await db.execute(
                    select(Notification).where(
                        Notification.action_url == marker,
                        Notification.type == "class_reminder",
                    ).limit(1)
                )).scalar_one_or_none()
                if already:
                    continue

                minutes = max(1, int((session.scheduled_start - now).total_seconds() // 60))
                for student in await attendance_service.enrolled_students(db, session):
                    db.add(Notification(
                        user_id=student.id,
                        title=f"{session.subject} class starting soon",
                        message=(
                            f"Your {session.class_name} {session.subject} class "
                            f"starts in {minutes} minutes."
                        ),
                        type="class_reminder",
                        action_url=marker,
                    ))
                    sent += 1
            await db.commit()
    finally:
        await engine.dispose()

    return {"notifications": sent}


# ─── Post-class AI summary (spec §19E) ────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="tasks.online_class_tasks.generate_class_summary",
    max_retries=1,
    default_retry_delay=120,
)
def generate_class_summary_task(self, session_id: str):
    """One controlled AI job per class, after the teacher confirms the record.

    Deliberately not per student: the summary is generated once here and read
    from storage by everyone. Runs in the background so a teacher pressing
    "Confirm" never waits on a model, and failure is silent — the classroom and
    the lesson record are already complete without it.
    """
    return _run(_generate_class_summary(session_id))


async def _generate_class_summary(session_id: str) -> dict:
    from sqlalchemy import select
    from models.online_classes import OnlineClassSession
    from routes.class_ai import _cached, _generate_summary
    from services.lss_ai_service import AIUnavailable

    engine, session_factory = _session_factory()
    try:
        async with session_factory() as db:
            session = (await db.execute(
                select(OnlineClassSession).where(OnlineClassSession.id == session_id)
            )).scalar_one_or_none()
            if not session:
                return {"generated": False, "reason": "session missing"}

            existing = await _cached(db, session.id, "summary")
            if existing and not existing.is_stale:
                return {"generated": False, "reason": "already current"}

            try:
                await _generate_summary(db, session, None)
            except AIUnavailable as exc:
                logger.info("[BEAT] summary skipped for %s: %s", session_id, exc)
                return {"generated": False, "reason": str(exc)}
            return {"generated": True}
    finally:
        await engine.dispose()


# ─── Recording retention (spec §15) ───────────────────────────────────────────

@celery_app.task(name="tasks.online_class_tasks.expire_recordings")
def expire_recordings():
    return _run(_expire_recordings())


async def _expire_recordings() -> dict:
    """Delete recordings whose retention period has passed.

    Storage is the one part of this module that grows without limit, and these
    are recordings of children: keeping them longer than the school's policy
    says is a privacy problem, not just a disk-space one.
    """
    from sqlalchemy import select
    from models.models import utcnow
    from models.online_classes import OnlineClassRecording
    from services import storage_service

    engine, session_factory = _session_factory()
    deleted = 0
    try:
        async with session_factory() as db:
            result = await db.execute(
                select(OnlineClassRecording).where(
                    OnlineClassRecording.expires_at.is_not(None),
                    OnlineClassRecording.expires_at < utcnow(),
                    OnlineClassRecording.deleted_at.is_(None),
                )
            )
            for recording in result.scalars().all():
                if recording.object_name:
                    try:
                        await asyncio.to_thread(
                            storage_service.delete_file,
                            recording.object_name,
                            recording.bucket,
                        )
                    except Exception as exc:
                        logger.warning("[BEAT] recording delete failed %s: %s", recording.id, exc)
                        continue
                recording.deleted_at = utcnow()
                recording.status = "deleted"
                deleted += 1
            await db.commit()
    finally:
        await engine.dispose()

    return {"deleted": deleted}


async def _close_media_client() -> None:
    from services import livekit_service
    try:
        await livekit_service.close_client()
    except Exception:  # pragma: no cover - shutdown best effort
        pass
