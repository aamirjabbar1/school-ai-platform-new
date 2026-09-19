"""
ERP background work.

One job so far: empty the event outbox. `services/erp/events.py` writes an
event in the same transaction as the business change that caused it, which
makes the record reliable — but a record nobody reads is just a table. This is
the other half.

It runs on the ordinary Celery worker beside document ingestion and the online
class jobs. Nothing here calls an AI model, and nothing here is allowed to take
long enough to matter.
"""
from __future__ import annotations

import asyncio
import logging

from celery_app import celery_app

logger = logging.getLogger("agent")


def _session_factory():
    """A fresh engine per task, disposed at the end.

    `asyncio.run()` closes its loop when it returns, and asyncpg connections
    are bound to the loop that opened them. The shared engine from
    `config.database` therefore works exactly once per worker process and then
    fails with "attached to a different loop" — which, for a beat task running
    every sixty seconds, means every run after the first. The rest of the
    codebase already learned this (see tasks/online_class_tasks.py); this
    follows it.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from config.settings import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@celery_app.task(name="tasks.erp_tasks.drain_domain_events")
def drain_domain_events():
    """Run any event handlers waiting in the outbox.

    Safe to run concurrently with itself: each event is committed individually
    and handlers are keyed on `dedupe_key`, so the worst a double run costs is
    a wasted query.
    """
    async def run():
        from services.erp import events
        # Importing the accounting module registers its posting rules. A
        # handler that is never imported is a handler that never runs, and the
        # ledger would silently stay empty.
        from services.erp import accounts  # noqa: F401

        engine, session_factory = _session_factory()
        try:
            async with session_factory() as db:
                return await events.drain(db, limit=100)
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(run())
        if result.get("picked_up"):
            logger.info("ERP events drained: %s", result)
        return result
    except Exception as exc:                     # noqa: BLE001 — logged, never raised into beat
        # A failure here must not stop the beat schedule that also closes
        # abandoned classrooms and expires recordings.
        logger.warning("ERP event drain failed: %s", exc)
        return {"error": str(exc)}
