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
from config.database import async_session

logger = logging.getLogger("agent")


@celery_app.task(name="tasks.erp_tasks.drain_domain_events")
def drain_domain_events():
    """Run any event handlers waiting in the outbox.

    Safe to run concurrently with itself: each event is committed individually
    and handlers are keyed on `dedupe_key`, so the worst a double run costs is
    a wasted query.
    """
    async def run():
        from services.erp import events
        async with async_session() as db:
            return await events.drain(db, limit=100)

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
