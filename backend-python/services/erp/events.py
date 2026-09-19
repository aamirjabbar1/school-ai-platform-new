"""
Domain events, as a transactional outbox (blueprint §1.7).

The specification's promise is "enter information once and the whole system
knows". That only holds if the knowing is reliable — an admission that creates
a student but silently fails to open a fee account is worse than one that
failed outright.

So an event row is written *in the same transaction* as the business change.
Either both land or neither does. A Celery beat task drains the outbox
afterwards and runs the handlers, which are idempotent and keyed on
`dedupe_key`, so a retry cannot bill a student twice.

No new infrastructure: Celery and Redis are already deployed.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import DomainEvent, EVENT_DONE, EVENT_FAILED, EVENT_PENDING
from models.models import utcnow

logger = logging.getLogger("agent")


# The events named in the specification (§75). Handlers register against these.
STUDENT_ADMISSION_CONFIRMED = "STUDENT_ADMISSION_CONFIRMED"
STUDENT_ENROLLED = "STUDENT_ENROLLED"
STUDENT_WITHDRAWN = "STUDENT_WITHDRAWN"
TEACHER_APPOINTED = "TEACHER_APPOINTED"
PAYROLL_APPROVED = "PAYROLL_APPROVED"
PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
RESULT_PUBLISHED = "RESULT_PUBLISHED"
SESSION_ACTIVATED = "SESSION_ACTIVATED"

Handler = Callable[[AsyncSession, DomainEvent], Awaitable[None]]

_HANDLERS: dict[str, list[Handler]] = {}


def on(event_type: str):
    """Register a handler. Handlers must be idempotent — a retry re-runs them."""
    def decorator(fn: Handler) -> Handler:
        _HANDLERS.setdefault(event_type, []).append(fn)
        return fn
    return decorator


def emit(
    db: AsyncSession,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
) -> DomainEvent:
    """Append an event to the caller's transaction. The caller commits."""
    event = DomainEvent(
        event_type=event_type,
        payload=payload or {},
        dedupe_key=dedupe_key,
    )
    db.add(event)
    return event


async def drain(db: AsyncSession, *, limit: int = 50) -> dict[str, int]:
    """Run pending handlers. Called by the beat worker; safe to call twice.

    One failing handler must not stall the queue behind it, so each event is
    committed on its own and a failure is recorded on the row rather than
    raised.
    """
    result = await db.execute(
        select(DomainEvent)
        .where(DomainEvent.status == EVENT_PENDING)
        .order_by(DomainEvent.occurred_at)
        .limit(limit)
    )
    events = list(result.scalars().all())
    done = failed = 0

    for event in events:
        handlers = _HANDLERS.get(event.event_type, [])
        try:
            for handler in handlers:
                await handler(db, event)
            event.status = EVENT_DONE
            event.processed_at = utcnow()
            done += 1
        except Exception as exc:                      # noqa: BLE001 — recorded, not hidden
            event.attempts = (event.attempts or 0) + 1
            event.last_error = str(exc)[:2000]
            # Give up after five attempts and surface it on the exceptions
            # screen. Retrying forever just hides the problem.
            if event.attempts >= 5:
                event.status = EVENT_FAILED
            failed += 1
            logger.warning("Event %s (%s) failed: %s", event.id, event.event_type, exc)

        await db.commit()

    return {"processed": done, "failed": failed, "picked_up": len(events)}
