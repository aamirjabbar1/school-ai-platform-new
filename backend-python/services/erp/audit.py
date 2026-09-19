"""
ERP audit trail (blueprint §1.6).

One rule distinguishes this from `services/audit_service.py`, which serves
lesson plans and question papers: **that one swallows failures, this one does
not.** Losing the audit row for a regenerated lesson plan is a nuisance; losing
it for a salary revision or a fee reversal is a missing answer to "who changed
this, and why".

So `record()` only adds to the caller's session and the caller commits. The
change and its audit row land together or not at all.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import AuditLog
from models.models import User


# Entity names used across the ERP. Free strings would drift into
# "student"/"Student"/"students" within a month.
STUDENT = "student"
EMPLOYEE = "employee"
FAMILY = "family"
ENROLLMENT = "enrollment"
SESSION = "academic_session"
CLASS = "school_class"
SECTION = "section"
SUBJECT = "subject"
NUMBER_SERIES = "number_series"
ROLE = "role"
USER_ROLE = "user_role"
FEATURE_FLAG = "feature_flag"
SETUP = "setup"


def _jsonable(value: Any) -> Any:
    """Make a value safe for a JSON column without losing its meaning."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)          # not float — a rounded rupee is a wrong rupee
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def record(
    db: AsyncSession,
    *,
    actor: User | None,
    entity_type: str,
    action: str,
    entity_id: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: str | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append an audit row to the current transaction. The caller commits."""
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_name=actor.name if actor else None,
        actor_role=actor.role if actor else None,
        ip=ip,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=_jsonable(old_value),
        new_value=_jsonable(new_value),
        reason=reason,
    )
    db.add(entry)
    return entry


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    """Only what actually changed, so an audit row is readable at a glance.

    A row that records forty unchanged fields buries the one that moved.
    """
    old: dict = {}
    new: dict = {}
    for key in set(before) | set(after):
        b, a = before.get(key), after.get(key)
        if b != a:
            old[key] = _jsonable(b)
            new[key] = _jsonable(a)
    return old, new
