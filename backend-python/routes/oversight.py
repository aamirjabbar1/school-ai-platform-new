"""
Admin oversight of teacher-authored content.

Lesson plans and question papers stay teacher-owned and their existing
workflows are untouched; this module is the administration's read/act layer on
top of them:

  * every record is visible centrally, filterable by teacher, class, section,
    subject, academic session, status and date
  * administrators can approve, reject, edit, regenerate, archive or delete
  * every action lands in the audit trail (services/audit_service.py), which
    also carries version history and AI generation history

Review status is deliberately independent of `is_published`: teachers publish
as they always did, and admins review before or after that happens.
"""
from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import require_roles
from models.models import (
    LessonPlan, QuestionPaper, REVIEW_APPROVED, REVIEW_PENDING, REVIEW_REJECTED,
    User,
)
from services import audit_service
from services.exam_patterns import paper_total_marks

router = APIRouter(prefix="/admin/content", tags=["admin-content"])

# URL segment → audit content type. Keeps the API readable while the audit
# trail keeps its own singular, snake_case vocabulary.
_TYPES = {
    "lesson-plans": audit_service.LESSON_PLAN,
    "question-papers": audit_service.QUESTION_PAPER,
}


def _content_type(segment: str) -> str:
    if segment not in _TYPES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown content type '{segment}'. Expected one of: {', '.join(_TYPES)}",
        )
    return _TYPES[segment]


class ReviewRequest(BaseModel):
    # "approved" | "rejected" | "pending" (pending re-opens a decided record)
    decision: str
    note: str | None = None


class EditRequest(BaseModel):
    title: str | None = None
    # Lesson plans carry plan_data; papers carry questions/answer_key.
    plan_data: dict | None = None
    questions: list | None = None
    answer_key: list | None = None
    instructions: str | None = None
    note: str | None = None


class ArchiveRequest(BaseModel):
    archived: bool = True
    note: str | None = None


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _get_record(db: AsyncSession, content_type: str, record_id: str):
    model = audit_service.model_for(content_type)
    result = await db.execute(select(model).where(model.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


async def _teacher_names(db: AsyncSession, ids: set[str]) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    result = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {row.id: row.name for row in result}


def _decorate(records: list, names: dict[str, str]) -> list[dict]:
    items = []
    for record in records:
        item = record.to_dict()
        item["teacher_name"] = names.get(record.teacher_id)
        item["reviewed_by_name"] = names.get(record.reviewed_by)
        item["updated_by_name"] = names.get(record.updated_by)
        # Keep listings light — the detail endpoint carries the full content.
        item.pop("plan_data", None)
        item.pop("questions", None)
        item.pop("answer_key", None)
        item.pop("inputs", None)
        items.append(item)
    return items


def _apply_filters(query, model, *, teacher_id, subject, class_name, section,
                   academic_session, review_status, is_published, is_archived,
                   record_type, date_from, date_to, q):
    if teacher_id:
        query = query.where(model.teacher_id == teacher_id)
    if subject:
        query = query.where(model.subject == subject)
    if class_name:
        query = query.where(model.class_name == class_name)
    if section:
        query = query.where(model.section == section)
    if academic_session:
        query = query.where(model.academic_session == academic_session)
    if review_status:
        query = query.where(model.review_status == review_status)
    if is_published is not None:
        query = query.where(model.is_published.is_(is_published))
    # Archived records are hidden unless explicitly asked for, so the default
    # view is the live one while the history stays reachable.
    if is_archived is None:
        query = query.where(model.is_archived.is_(False))
    else:
        query = query.where(model.is_archived.is_(is_archived))
    if record_type:
        column = model.plan_type if model is LessonPlan else model.paper_type
        query = query.where(column == record_type)
    if date_from:
        query = query.where(model.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(model.created_at <= datetime.combine(date_to, time.max))
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(or_(
            model.title.ilike(needle),
            model.subject.ilike(needle),
            model.class_name.ilike(needle),
        ))
    return query


# ─── listings ─────────────────────────────────────────────────────────────────

@router.get("/summary")
async def content_summary(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Headline counts for the oversight dashboard."""
    out: dict = {}
    for segment, content_type in _TYPES.items():
        model = audit_service.model_for(content_type)
        result = await db.execute(
            select(
                func.count(model.id).label("total"),
                func.count(model.id).filter(model.review_status == REVIEW_PENDING).label("pending"),
                func.count(model.id).filter(model.review_status == REVIEW_APPROVED).label("approved"),
                func.count(model.id).filter(model.review_status == REVIEW_REJECTED).label("rejected"),
                func.count(model.id).filter(model.is_published.is_(True)).label("published"),
                func.count(model.id).filter(model.is_archived.is_(True)).label("archived"),
            )
        )
        row = result.mappings().first()
        counts = {k: int(v or 0) for k, v in dict(row).items()}
        # Archived records are excluded from the live totals.
        counts["total"] = counts["total"] - counts["archived"]
        out[segment] = counts
    return out


@router.get("/filters")
async def filter_options(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Distinct values behind the filter bar, drawn from actual records."""
    teachers = await db.execute(
        select(User.id, User.name)
        .where(User.role.in_(("teacher", "admin")))
        .order_by(User.name)
    )

    def _values(column, model):
        return select(column).where(column.isnot(None), column != "").distinct()

    options: dict[str, set[str]] = {
        "subjects": set(), "classes": set(), "sections": set(), "sessions": set(),
    }
    for model in (LessonPlan, QuestionPaper):
        for key, column in (
            ("subjects", model.subject), ("classes", model.class_name),
            ("sections", model.section), ("sessions", model.academic_session),
        ):
            result = await db.execute(_values(column, model))
            options[key].update(v for (v,) in result if v)

    plan_types = await db.execute(
        select(LessonPlan.plan_type).where(LessonPlan.plan_type.isnot(None)).distinct())
    paper_types = await db.execute(
        select(QuestionPaper.paper_type).where(QuestionPaper.paper_type.isnot(None)).distinct())

    return {
        "teachers": [{"id": r.id, "name": r.name} for r in teachers],
        **{k: sorted(v) for k, v in options.items()},
        "plan_types": sorted(v for (v,) in plan_types if v),
        "paper_types": sorted(v for (v,) in paper_types if v),
    }


@router.get("/{segment}")
async def list_content(
    segment: str,
    teacher_id: str | None = None,
    subject: str | None = None,
    class_name: str | None = None,
    section: str | None = None,
    academic_session: str | None = None,
    review_status: str | None = None,
    is_published: bool | None = None,
    is_archived: bool | None = None,
    record_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Every record of one type, filtered and paginated."""
    model = audit_service.model_for(_content_type(segment))
    filters = dict(
        teacher_id=teacher_id, subject=subject, class_name=class_name,
        section=section, academic_session=academic_session,
        review_status=review_status, is_published=is_published,
        is_archived=is_archived, record_type=record_type,
        date_from=date_from, date_to=date_to, q=q,
    )

    total = await db.execute(
        _apply_filters(select(func.count(model.id)), model, **filters))
    rows = await db.execute(
        _apply_filters(select(model), model, **filters)
        .order_by(model.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = list(rows.scalars().all())
    names = await _teacher_names(
        db,
        {r.teacher_id for r in records}
        | {r.reviewed_by for r in records}
        | {r.updated_by for r in records},
    )
    return {
        "items": _decorate(records, names),
        "total": int(total.scalar_one() or 0),
        "page": page,
        "page_size": page_size,
    }


@router.get("/{segment}/{record_id}")
async def get_content(
    segment: str,
    record_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """One record in full, with the names behind its audit fields."""
    content_type = _content_type(segment)
    record = await _get_record(db, content_type, record_id)

    # Records that predate the audit trail get a retrospective creation entry so
    # their history is never misleadingly empty.
    if await audit_service.backfill_creation(db, record, content_type):
        await db.commit()

    names = await _teacher_names(db, {record.teacher_id, record.reviewed_by, record.updated_by})
    item = record.to_dict()
    item["teacher_name"] = names.get(record.teacher_id)
    item["reviewed_by_name"] = names.get(record.reviewed_by)
    item["updated_by_name"] = names.get(record.updated_by)
    item["revisions"] = await audit_service.list_revisions(db, content_type, record_id)
    return item


@router.get("/{segment}/{record_id}/revisions")
async def list_revisions(
    segment: str,
    record_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """History for a record — deliberately still readable after it is deleted,
    since the trail of a removed plan or paper is what an audit needs most."""
    return await audit_service.list_revisions(db, _content_type(segment), record_id)


@router.get("/{segment}/{record_id}/revisions/{revision_id}")
async def get_revision(
    segment: str,
    record_id: str,
    revision_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """One historical version, including the content snapshot taken at the time."""
    content_type = _content_type(segment)
    revision = await audit_service.get_revision(db, content_type, record_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


# ─── administrative actions ───────────────────────────────────────────────────

@router.post("/{segment}/{record_id}/review")
async def review_content(
    segment: str,
    record_id: str,
    body: ReviewRequest,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Approve, reject, or re-open a record for review."""
    decision = (body.decision or "").strip().lower()
    if decision not in (REVIEW_APPROVED, REVIEW_REJECTED, REVIEW_PENDING):
        raise HTTPException(
            status_code=400,
            detail=f"decision must be one of: {REVIEW_APPROVED}, {REVIEW_REJECTED}, {REVIEW_PENDING}",
        )
    if decision == REVIEW_REJECTED and not (body.note or "").strip():
        raise HTTPException(
            status_code=400,
            detail="A rejection needs a note so the teacher knows what to change.",
        )

    content_type = _content_type(segment)
    record = await _get_record(db, content_type, record_id)

    record.review_status = decision
    record.review_note = (body.note or "").strip() or None
    if decision == REVIEW_PENDING:
        record.reviewed_by = None
        record.reviewed_at = None
    else:
        record.reviewed_by = user.id
        record.reviewed_at = datetime.utcnow()

    audit_service.record_event(
        db, record, content_type=content_type,
        action=decision if decision != REVIEW_PENDING else "restored",
        actor=user, note=record.review_note,
    )
    await db.commit()
    await db.refresh(record)
    return record.to_dict()


@router.patch("/{segment}/{record_id}")
async def edit_content(
    segment: str,
    record_id: str,
    body: EditRequest,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin edit. Bumps the version and snapshots the result."""
    content_type = _content_type(segment)
    record = await _get_record(db, content_type, record_id)

    changed = False
    if body.title is not None:
        record.title = body.title
        changed = True
    if isinstance(record, LessonPlan):
        if body.plan_data is not None:
            record.plan_data = body.plan_data
            changed = True
    else:
        if body.questions is not None:
            record.questions = body.questions
            # Keep the printed total honest against the questions that remain.
            record.total_marks = paper_total_marks(body.questions) or record.total_marks
            changed = True
        if body.answer_key is not None:
            record.answer_key = body.answer_key
            changed = True
        if body.instructions is not None:
            record.instructions = body.instructions
            changed = True

    if not changed:
        raise HTTPException(status_code=400, detail="No changes supplied")

    audit_service.record_change(
        db, record, content_type=content_type, action="updated",
        actor=user, note=(body.note or "").strip() or "Edited by administrator",
    )
    await db.commit()
    await db.refresh(record)
    return record.to_dict()


@router.post("/{segment}/{record_id}/archive")
async def archive_content(
    segment: str,
    record_id: str,
    body: ArchiveRequest,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Archive or restore. Archived records leave the live lists but keep their history."""
    content_type = _content_type(segment)
    record = await _get_record(db, content_type, record_id)

    record.is_archived = bool(body.archived)
    audit_service.record_event(
        db, record, content_type=content_type,
        action="archived" if record.is_archived else "restored",
        actor=user, note=(body.note or "").strip() or None,
    )
    await db.commit()
    await db.refresh(record)
    return record.to_dict()


@router.post("/{segment}/{record_id}/regenerate")
async def regenerate_content(
    segment: str,
    record_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the AI over the record's original inputs, in place.

    The previous version stays in the audit trail, so a regeneration is always
    reversible by inspection.
    """
    content_type = _content_type(segment)
    record = await _get_record(db, content_type, record_id)

    inputs = dict(record.inputs or {})
    if not inputs:
        raise HTTPException(
            status_code=400,
            detail=(
                "This record has no stored generation inputs — it was written by hand "
                "or created before regeneration was supported, so it cannot be regenerated."
            ),
        )

    if content_type == audit_service.LESSON_PLAN:
        await _regenerate_lesson_plan(record, inputs, db)
    else:
        await _regenerate_question_paper(record, inputs, db)

    audit_service.record_change(
        db, record, content_type=content_type, action="regenerated",
        actor=user, note="Regenerated by administrator", ai_inputs=inputs,
    )
    await db.commit()
    await db.refresh(record)

    # Refresh the plan's Knowledge Base copy so curriculum-coverage checks read
    # the regenerated content rather than the superseded version.
    if content_type == audit_service.LESSON_PLAN:
        from services.lesson_plan_store import publish_plan_safely
        await publish_plan_safely(db, record, uploaded_by=record.teacher_id)
        await db.refresh(record)

    return record.to_dict()


async def _regenerate_lesson_plan(plan: LessonPlan, inputs: dict, db: AsyncSession) -> None:
    from services.ai_service import generate_lesson_plan

    try:
        result = await generate_lesson_plan({
            "subject": inputs.get("subject") or plan.subject,
            "class_level": inputs.get("class_name") or plan.class_name,
            "plan_type": inputs.get("plan_type") or plan.plan_type,
            **{k: inputs.get(k) for k in (
                "board", "book_name", "academic_session", "start_date", "end_date",
                "num_weeks", "days_per_week", "periods_per_week", "chapters", "topics",
                "learning_objectives", "bloom_level", "methodology", "resources",
                "homework_pref", "assessment_pref", "holidays", "exam_schedule",
                "revision_week", "teacher_notes",
            )},
        }, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    plan.plan_data = result["plan_data"]


async def _regenerate_question_paper(paper: QuestionPaper, inputs: dict, db: AsyncSession) -> None:
    from services.ai_service import generate_question_paper

    try:
        result = await generate_question_paper({
            "subject": inputs.get("subject") or paper.subject,
            "class_level": inputs.get("class_name") or paper.class_name,
            "paper_type": inputs.get("paper_type") or paper.paper_type,
            "total_marks": inputs.get("total_marks") or paper.total_marks,
            "duration_minutes": inputs.get("duration_minutes") or paper.duration_minutes,
            "topics": inputs.get("topics") or [],
            "difficulty_distribution": inputs.get("difficulty_distribution")
            or {"easy": 30, "medium": 50, "hard": 20},
            "generation_mode": inputs.get("generation_mode", "standard"),
            "use_past_papers": inputs.get("use_past_papers", True),
        }, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    paper.questions = result["questions"]
    paper.answer_key = result["answer_key"]
    paper.total_marks = paper_total_marks(result["questions"]) or paper.total_marks


@router.delete("/{segment}/{record_id}")
async def delete_content(
    segment: str,
    record_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a record. Its revision history is deliberately kept."""
    content_type = _content_type(segment)
    record = await _get_record(db, content_type, record_id)

    audit_service.record_event(
        db, record, content_type=content_type, action="deleted",
        actor=user, note="Record deleted by administrator",
    )
    await db.delete(record)
    await db.commit()
    return {"message": "Record deleted", "id": record_id}
