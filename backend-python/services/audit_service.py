"""
Audit trail for reviewable content (lesson plans, question papers).

Every meaningful event on a plan or paper is appended to `content_revisions`,
which serves three purposes at once:

  * version history   — each content change bumps `version` and stores a snapshot
  * approval log      — approvals, rejections and their notes
  * AI generation log — the parameters a generated version came from

Call `record_change` when the *content* moved (created, edited, regenerated) and
`record_event` for status-only transitions (approved, published, archived …).
Neither ever raises into the caller's request: an audit failure must not lose a
teacher's work, so problems are logged and swallowed.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ContentRevision, LessonPlan, QuestionPaper, User

LESSON_PLAN = "lesson_plan"
QUESTION_PAPER = "question_paper"

CONTENT_MODELS = {
    LESSON_PLAN: LessonPlan,
    QUESTION_PAPER: QuestionPaper,
}

# Content changed (bumps the version) vs. status changed (does not).
CONTENT_ACTIONS = ("created", "updated", "regenerated")
STATUS_ACTIONS = (
    "approved", "rejected", "published", "unpublished",
    "archived", "restored", "deleted",
)


def model_for(content_type: str):
    model = CONTENT_MODELS.get(content_type)
    if model is None:
        raise ValueError(f"Unknown content type: {content_type}")
    return model


def _snapshot(record) -> dict:
    """The content of a record as stored, small enough to keep per version."""
    if isinstance(record, LessonPlan):
        return {
            "title": record.title, "subject": record.subject,
            "class_name": record.class_name, "section": record.section,
            "plan_type": record.plan_type, "board": record.board,
            "book_name": record.book_name,
            "academic_session": record.academic_session,
            "start_date": record.start_date, "end_date": record.end_date,
            "plan_data": record.plan_data or {},
        }
    return {
        "title": record.title, "subject": record.subject,
        "class_name": record.class_name, "section": record.section,
        "paper_type": record.paper_type,
        "total_marks": record.total_marks,
        "duration_minutes": record.duration_minutes,
        "instructions": record.instructions,
        "academic_session": record.academic_session,
        "questions": record.questions or [],
        "answer_key": record.answer_key or [],
    }


def _add(
    db: AsyncSession,
    *,
    content_type: str,
    content_id: str,
    version: int,
    action: str,
    actor: User | None,
    note: str | None,
    snapshot: dict | None,
    ai_inputs: dict | None,
) -> None:
    db.add(ContentRevision(
        id=str(uuid.uuid4()),
        content_type=content_type,
        content_id=content_id,
        version=version,
        action=action,
        actor_id=actor.id if actor else None,
        actor_name=actor.name if actor else None,
        actor_role=actor.role if actor else None,
        note=note,
        snapshot=snapshot,
        ai_inputs=ai_inputs,
    ))


def record_change(
    db: AsyncSession,
    record,
    *,
    content_type: str,
    action: str,
    actor: User | None,
    note: str | None = None,
    ai_inputs: dict | None = None,
) -> None:
    """Log a content change, bumping the record's version and last editor.

    Flushes nothing: the caller's own commit persists both the record and its
    revision, so the audit trail can never disagree with the content.
    """
    try:
        if action == "created":
            record.version = 1
        else:
            record.version = (record.version or 1) + 1
        if actor is not None:
            record.updated_by = actor.id

        _add(
            db,
            content_type=content_type, content_id=record.id,
            version=record.version, action=action, actor=actor,
            note=note, snapshot=_snapshot(record), ai_inputs=ai_inputs,
        )
    except Exception as exc:  # pragma: no cover - never lose work over audit
        print(f"[audit] could not record {action} on {content_type} {getattr(record, 'id', '?')}: {exc}")


def record_event(
    db: AsyncSession,
    record,
    *,
    content_type: str,
    action: str,
    actor: User | None,
    note: str | None = None,
) -> None:
    """Log a status transition that leaves the content untouched."""
    try:
        _add(
            db,
            content_type=content_type, content_id=record.id,
            version=record.version or 1, action=action, actor=actor,
            note=note, snapshot=None, ai_inputs=None,
        )
    except Exception as exc:  # pragma: no cover
        print(f"[audit] could not record {action} on {content_type} {getattr(record, 'id', '?')}: {exc}")


async def list_revisions(
    db: AsyncSession,
    content_type: str,
    content_id: str,
    *,
    limit: int = 100,
) -> list[dict]:
    """Full history for one record, newest first."""
    result = await db.execute(
        select(ContentRevision)
        .where(
            ContentRevision.content_type == content_type,
            ContentRevision.content_id == content_id,
        )
        .order_by(ContentRevision.created_at.desc(), ContentRevision.version.desc())
        .limit(limit)
    )
    return [r.to_dict() for r in result.scalars().all()]


async def get_revision(
    db: AsyncSession,
    content_type: str,
    content_id: str,
    revision_id: str,
) -> dict | None:
    """One revision including its stored snapshot."""
    result = await db.execute(
        select(ContentRevision).where(
            ContentRevision.id == revision_id,
            ContentRevision.content_type == content_type,
            ContentRevision.content_id == content_id,
        )
    )
    revision = result.scalar_one_or_none()
    return revision.to_dict(include_snapshot=True) if revision else None


async def backfill_creation(db: AsyncSession, record, content_type: str) -> bool:
    """Give a pre-existing record a 'created' revision if it has no history.

    Content created before the audit trail existed would otherwise show an empty
    history; this keeps the admin view honest without inventing an actor.
    """
    count = await db.execute(
        select(func.count(ContentRevision.id)).where(
            ContentRevision.content_type == content_type,
            ContentRevision.content_id == record.id,
        )
    )
    if count.scalar_one():
        return False

    revision = ContentRevision(
        id=str(uuid.uuid4()),
        content_type=content_type, content_id=record.id,
        version=record.version or 1, action="created",
        actor_id=record.teacher_id,
        note="Recorded retrospectively — created before the audit trail existed.",
        snapshot=_snapshot(record),
    )
    revision.created_at = record.created_at
    db.add(revision)
    return True
