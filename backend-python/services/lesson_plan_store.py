"""
Mirror generated lesson plans into the Knowledge Base.

When a teacher generates a plan in the Lesson Plan module it is saved to
`lesson_plans` as it always was; this module additionally copies it into the
Knowledge Base (`documents` + MinIO + the ingestion pipeline) so the plan is
immediately available for curriculum validation, lesson-coverage checks and
retrieval by `search_curriculum` — with no upload step for anyone.

The copy is kept in step with the plan: republishing an already-published plan
refreshes the same Knowledge Base document rather than piling up duplicates,
which matters because a stale copy would quietly undermine coverage checks.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Document, LessonPlan
from services import storage_service

logger = logging.getLogger("agent")

# Knowledge-base document type for a stored plan. Distinct from "notes" so plans
# can be filtered apart from curriculum material.
KB_DOCUMENT_TYPE = "lesson_plan"

# Where the link to the Knowledge Base copy is recorded on the plan. It lives in
# `inputs` (already a free-form JSON bag) to avoid a migration for one pointer.
KB_DOCUMENT_KEY = "kb_document_id"


async def publish_plan_safely(db: AsyncSession, plan: LessonPlan, *, uploaded_by: str) -> str | None:
    """Publish a plan to the Knowledge Base, swallowing failures.

    Generating a lesson plan is a long, expensive operation; losing it because
    the object store or the index was briefly unavailable would be far worse
    than a plan that is momentarily missing from search. Failures are logged and
    reported as None so the caller can tell the teacher.
    """
    try:
        return await publish_to_knowledge_base(db, plan, uploaded_by=uploaded_by)
    except Exception as exc:  # pragma: no cover - never lose a generated plan
        logger.warning("[LESSON PLAN] knowledge-base publish failed for %s: %s", plan.id, exc)
        return None


async def publish_to_knowledge_base(
    db: AsyncSession,
    plan: LessonPlan,
    *,
    uploaded_by: str,
) -> str:
    """Copy a stored lesson plan into the Knowledge Base and queue ingestion.

    Returns the knowledge-base document id. The plan is written as UTF-8 text so
    the ingestion pipeline reads it directly instead of going through vision
    extraction.
    """
    from tasks.document_tasks import ingest_document_task

    body = _plan_text(plan)
    if not body.strip():
        raise ValueError("Lesson plan has no text to index")

    doc = await _existing_document(db, plan)
    if doc is None:
        doc = Document(uploaded_by=uploaded_by, file_path="")
        db.add(doc)

    doc.title = plan.title
    doc.subject = plan.subject
    doc.class_level = plan.class_name
    doc.description = (
        f"{plan.plan_type.replace('_', ' ').title()} lesson plan generated in the "
        "Lesson Plan module and saved automatically."
    )
    doc.document_type = KB_DOCUMENT_TYPE
    doc.language = "English"
    doc.academic_year = plan.academic_session
    doc.chapter = plan.book_name
    doc.file_name = f"{_safe_stem(plan.title)}.txt"
    doc.file_type = "txt"
    doc.file_size = len(body.encode("utf-8"))
    # Re-ingestion replaces the chunks and vectors for this document id.
    doc.is_ingested = False
    doc.ingestion_error = None
    await db.flush()

    unique = f"{int(time.time())}-{random.randint(0, 999_999_999)}"
    object_name = storage_service.make_object_name(
        doc.id, f"{_safe_stem(plan.title)}-{unique}.txt")
    await asyncio.to_thread(
        storage_service.upload_file, object_name, body.encode("utf-8"), "text/plain")

    previous_object = doc.file_path
    doc.file_path = object_name

    inputs = dict(plan.inputs or {})
    inputs[KB_DOCUMENT_KEY] = doc.id
    plan.inputs = inputs

    await db.commit()

    if previous_object and previous_object != object_name:
        try:
            await asyncio.to_thread(storage_service.delete_file, previous_object)
        except Exception as exc:  # pragma: no cover - orphan object is harmless
            logger.info("[LESSON PLAN] could not remove superseded object %s: %s",
                        previous_object, exc)

    # Chunking + embedding run in the Celery worker so generation never waits
    # on indexing.
    ingest_document_task.delay(doc.id)
    logger.info("[LESSON PLAN] %s published to knowledge base as document %s", plan.id, doc.id)
    return doc.id


async def _existing_document(db: AsyncSession, plan: LessonPlan) -> Document | None:
    """The Knowledge Base copy of this plan, if one was published before."""
    document_id = (plan.inputs or {}).get(KB_DOCUMENT_KEY)
    if not document_id:
        return None
    result = await db.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


def _safe_stem(title: str) -> str:
    stem = "".join(c if c.isalnum() else "_" for c in (title or "lesson_plan"))
    return stem.strip("_")[:80] or "lesson_plan"


def _plan_text(plan: LessonPlan) -> str:
    """Flatten a plan into indexable text, whatever shape its data takes."""
    header = [
        f"# {plan.title}",
        f"Subject: {plan.subject}",
        f"Class: {plan.class_name}" + (f" - {plan.section}" if plan.section else ""),
        f"Plan type: {plan.plan_type.replace('_', ' ').title()}",
    ]
    if plan.board:
        header.append(f"Board: {plan.board}")
    if plan.book_name:
        header.append(f"Book: {plan.book_name}")
    if plan.academic_session:
        header.append(f"Academic session: {plan.academic_session}")

    return "\n".join(header) + "\n\n" + _flatten(plan.plan_data or {})


def _flatten(value, depth: int = 0) -> str:
    """Render nested plan data as readable indented text for indexing.

    Top-level sections are separated by a blank line. The ingestion chunker
    splits on blank lines, so without them a whole plan collapses into one
    oversized chunk and retrieval degrades to all-or-nothing.
    """
    pad = "  " * depth
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            label = str(key).replace("_", " ").title()
            rendered = _flatten(item, depth + 1)
            if not rendered.strip():
                continue
            if "\n" in rendered.strip():
                parts.append(f"{pad}{label}:\n{rendered}")
            else:
                parts.append(f"{pad}{label}: {rendered.strip()}")
        return ("\n\n" if depth == 0 else "\n").join(parts)
    if isinstance(value, list):
        rendered = [r for r in (_flatten(v, depth) for v in value) if r.strip()]
        # Structured entries (a methodology stage, a day of the week plan) are
        # their own blocks; plain strings stay one per line. Without this the
        # biggest section becomes a single chunk and can hit the size cap, which
        # splits it mid-sentence.
        separator = "\n\n" if any(isinstance(v, dict) for v in value) else "\n"
        return separator.join(rendered)
    return f"{pad}{value}" if value not in (None, "") else ""
