"""
Lesson-planner-sourced examination papers for Grades 1 and 2.

Papers for the youngest grades are held to a stricter standard than the rest of
the school: every question must come from material the class has actually been
taught, traceable to a named source, and nothing may be invented. This module
holds that policy end to end — which classes it covers, what counts as an
approved source, which planners count as taught, and the validation that runs
before a paper is accepted.

Grades 3-10 do not pass through here at all; `applies_to()` is the only gate,
and the generator falls back to its existing behaviour for every other class.

Approved sources (nothing else may be used):
  * classwork recorded in a Lesson Planner
  * bookwork from the approved textbook
  * end-of-chapter exercises
  * end-of-book exercises

A lesson planner reaches this module by either route, and neither is preferred:
the Lesson Plan module on the teacher dashboard, or an administrator upload to
the Knowledge Base — a plan written by hand or in another tool counts once it
has been filed there. The second route is open to Grades 1 and 2 only.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Document, DocumentChunk, LessonPlan
from services.exam_patterns import class_number

logger = logging.getLogger("agent")

# The grades this policy governs. Deliberately explicit rather than a range, so
# widening it is a conscious edit.
PRIMARY_GRADES = (1, 2)

# Machine values for a question's source, and how they read to an administrator.
SOURCE_LABELS: dict[str, str] = {
    "lesson_planner_classwork": "Lesson Planner — Classwork",
    "bookwork": "Bookwork",
    "end_of_chapter_exercise": "End-of-Chapter Exercise",
    "end_of_book_exercise": "End-of-Book Exercise",
}
APPROVED_SOURCES = tuple(SOURCE_LABELS)

# Where a lesson planner came from. Recorded on the generated paper so an
# administrator can see which route supplied the material.
ORIGIN_LESSON_PLAN_MODULE = "lesson_plan_module"
ORIGIN_KNOWLEDGE_BASE = "knowledge_base"

ORIGIN_LABELS: dict[str, str] = {
    ORIGIN_LESSON_PLAN_MODULE: "generated in the Lesson Plan module",
    ORIGIN_KNOWLEDGE_BASE: "uploaded to the Knowledge Base by the administrator",
}

# Ceilings on the uploaded planners admitted to one prompt. Uploads are whole
# documents rather than a structured plan, so without a cap a single long file
# could crowd out the textbook extracts.
_MAX_UPLOADED_PLANNERS = 4
_MAX_CHUNKS_PER_UPLOAD = 60


def applies_to(class_name: str | None) -> bool:
    """True when this class is governed by the Grades 1-2 sourcing policy."""
    return class_number(class_name) in PRIMARY_GRADES


def source_label(value: str | None) -> str:
    return SOURCE_LABELS.get((value or "").strip().lower(), "Unverified source")


# ─── Lesson planner retrieval ─────────────────────────────────────────────────

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y")


def parse_plan_date(value: str | None) -> date | None:
    """Best-effort parse of a planner's free-text start/end date."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Fall back to a leading ISO-ish date inside a longer string.
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def teaching_status(plan: LessonPlan, as_of: date) -> str:
    """Whether a planner's lessons are finished, still running, or not started.

    Planner dates are free text, so this is best-effort: a planner we cannot
    date is reported as `undated` and the model is told to rely on the planner's
    own week/day markers rather than assume the whole plan was taught.
    """
    start = parse_plan_date(plan.start_date)
    end = parse_plan_date(plan.end_date)
    if end and end < as_of:
        return "completed"
    if start and start > as_of:
        return "not_started"
    if start or end:
        return "in_progress"
    return "undated"


async def fetch_lesson_planners(
    db: AsyncSession,
    *,
    subject: str,
    class_level: str,
    as_of: date | None = None,
) -> list[dict]:
    """Lesson planners for this class and subject, generated ones first.

    Both routes to a planner are honoured and neither is preferred:

      * a plan generated in the Lesson Plan module (`lesson_plans`)
      * a plan an administrator uploaded to the Knowledge Base, whoever wrote it
        and in whatever tool (`documents`, type `lesson_plan`)

    The uploaded route is open to Grades 1 and 2 only — `applies_to` gates it —
    so no other class's sourcing is affected.

    Planners that have not started yet are dropped outright — nothing in them
    has been taught, so nothing in them may be examined.
    """
    as_of = as_of or date.today()

    # Every plan, archived included: the archived ones are excluded from the
    # results below but still needed to recognise their Knowledge Base mirrors.
    result = await db.execute(select(LessonPlan).order_by(LessonPlan.created_at.desc()))
    plans = list(result.scalars().all())

    planners = _generated_planners(plans, subject=subject, class_level=class_level, as_of=as_of)

    if applies_to(class_level):
        planners += await _uploaded_planners(
            db, subject=subject, class_level=class_level,
            exclude=_mirrored_document_ids(plans),
        )
    return planners


def _generated_planners(
    plans: list[LessonPlan],
    *,
    subject: str,
    class_level: str,
    as_of: date,
) -> list[dict]:
    """Planners produced by the Lesson Plan module on the teacher dashboard."""
    from services.lesson_plan_store import _flatten  # readable rendering of plan_data

    def matches(plan: LessonPlan) -> bool:
        same_class = (plan.class_name or "").strip().lower() == (class_level or "").strip().lower()
        same_subject = (plan.subject or "").strip().lower() == (subject or "").strip().lower()
        return same_class and same_subject

    usable: list[dict] = []
    for plan in plans:
        if plan.is_archived or not matches(plan):
            continue
        status = teaching_status(plan, as_of)
        if status == "not_started":
            logger.info("[PRIMARY] skipping planner %r — starts after %s", plan.title, as_of)
            continue
        usable.append({
            "id": plan.id,
            "title": plan.title,
            "plan_type": plan.plan_type,
            "book_name": plan.book_name,
            "academic_session": plan.academic_session,
            "start_date": plan.start_date,
            "end_date": plan.end_date,
            "status": status,
            "origin": ORIGIN_LESSON_PLAN_MODULE,
            "text": _flatten(plan.plan_data or {}),
        })
    return usable


def _mirrored_document_ids(plans: list[LessonPlan]) -> set[str]:
    """Knowledge Base documents that are copies of rows in `lesson_plans`.

    The Lesson Plan module mirrors every plan it generates into the Knowledge
    Base under the same document type, so without this one plan would be offered
    twice — once per route — and counted twice in the prompt. Archived plans are
    matched too: a plan withdrawn from circulation must not return via its copy.
    """
    from services.lesson_plan_store import KB_DOCUMENT_KEY

    ids = {(plan.inputs or {}).get(KB_DOCUMENT_KEY) for plan in plans}
    return {doc_id for doc_id in ids if doc_id}


def _upload_matches(doc: Document, *, subject: str, class_level: str) -> bool:
    """Whether an uploaded plan belongs to this class and subject.

    Classes compare by grade number, because a plan filed as "Class 1" has to be
    found for a paper requested as "Grade 1" — both vocabularies are in use. A
    document whose class label carries no grade ("All Classes") is rejected: a
    Grades 1-2 paper may only be sourced from that grade's own plan.
    """
    grade = class_number(class_level)
    if grade is None or class_number(doc.class_level) != grade:
        return False
    return (doc.subject or "").strip().lower() == (subject or "").strip().lower()


async def _uploaded_planners(
    db: AsyncSession,
    *,
    subject: str,
    class_level: str,
    exclude: set[str],
) -> list[dict]:
    """Lesson plans an administrator filed in the Knowledge Base, newest first.

    Read whole from PostgreSQL rather than through semantic search: what has
    been taught is the shape of the entire plan, not the chunks that happen to
    match a topic query.

    An upload carries no structured teaching dates, so it is reported `undated`
    and the prompt directs the model to the plan's own week/day markers — the
    same treatment a generated plan without dates already gets.
    """
    from services.lesson_plan_store import KB_DOCUMENT_TYPE

    result = await db.execute(
        select(Document)
        .where(
            Document.document_type == KB_DOCUMENT_TYPE,
            Document.is_ingested.is_(True),
        )
        .order_by(Document.created_at.desc())
    )
    docs = [
        d for d in result.scalars().all()
        if d.id not in exclude and _upload_matches(d, subject=subject, class_level=class_level)
    ]

    planners: list[dict] = []
    for doc in docs[:_MAX_UPLOADED_PLANNERS]:
        chunk_rows = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
            .limit(_MAX_CHUNKS_PER_UPLOAD)
        )
        text = "\n\n".join(c.chunk_text for c in chunk_rows.scalars().all()).strip()
        if not text:
            logger.info("[PRIMARY] uploaded planner %r has no indexed text yet", doc.title)
            continue
        planners.append({
            "id": doc.id,
            "title": doc.title,
            # An upload is a document, not one of the module's plan types.
            "plan_type": "",
            "book_name": doc.chapter or "",
            "academic_session": doc.academic_year or "",
            "start_date": None,
            "end_date": None,
            "status": "undated",
            "origin": ORIGIN_KNOWLEDGE_BASE,
            "text": text,
        })

    if planners:
        logger.info("[PRIMARY] %d uploaded lesson planner(s) admitted for %s %s",
                    len(planners), subject, class_level)
    return planners


def build_planner_context(planners: list[dict], as_of: date | None = None) -> str:
    """Format planners for the prompt, flagging how much of each was taught."""
    if not planners:
        return ""
    as_of = as_of or date.today()

    notes = {
        "completed": "COMPLETED — every lesson in this planner has been taught.",
        "in_progress": (
            "IN PROGRESS — only the days/weeks dated on or before "
            f"{as_of.isoformat()} have been taught. Do not examine later ones."
        ),
        "undated": (
            "UNDATED — use the planner's own week/day markers to judge what has "
            "been taught, and leave out anything you cannot confirm was covered."
        ),
    }

    blocks = []
    for item in planners:
        # Both routes are equally valid sources, so the origin is stated as
        # provenance only — never as a reason to trust one planner over another.
        meta = [ORIGIN_LABELS.get(item.get("origin"), "lesson planner")]
        if item.get("plan_type"):
            meta.insert(0, item["plan_type"].replace("_", " ").title() + " planner")
        if item.get("book_name"):
            meta.append(f"Book: {item['book_name']}")
        if item.get("start_date") or item.get("end_date"):
            meta.append(f"{item.get('start_date') or '?'} → {item.get('end_date') or '?'}")
        header = (
            f'[LESSON PLANNER: "{item["title"]}" — {", ".join(meta)}]\n'
            f'[{notes[item["status"]]}]'
        )
        blocks.append(f"{header}\n{item['text']}")
    return "\n\n---\n\n".join(blocks)


_SCHOOL_WIDE = {"", "all classes", "all", "general", "all class"}


def filter_in_syllabus(results: list[dict], *, subject: str, class_level: str) -> list[dict]:
    """Keep only knowledge-base chunks belonging to this class and subject.

    `search_knowledge_base` widens its filters when a narrow query finds nothing,
    which is helpful elsewhere but would drop, say, Class 9 Chemistry text into
    the context of a Class 1 Maths paper. Nothing outside the approved syllabus
    may sit in front of the model here, so the widening is undone.
    """
    wanted_class = (class_level or "").strip().lower()
    wanted_subject = (subject or "").strip().lower()

    kept = []
    for r in results or []:
        chunk_class = (r.get("class_level") or "").strip().lower()
        chunk_subject = (r.get("subject") or "").strip().lower()
        if chunk_class not in _SCHOOL_WIDE and chunk_class != wanted_class:
            continue
        if chunk_subject and wanted_subject and chunk_subject != wanted_subject:
            continue
        kept.append(r)

    dropped = len(results or []) - len(kept)
    if dropped:
        logger.info("[PRIMARY] dropped %d out-of-syllabus chunk(s) for %s %s",
                    dropped, subject, class_level)
    return kept


# ─── Validation ───────────────────────────────────────────────────────────────

class CurriculumComplianceError(ValueError):
    """A paper could not be produced within the Grades 1-2 sourcing rules."""


async def require_planners(
    db: AsyncSession,
    planners: list[dict],
    subject: str,
    class_level: str,
) -> None:
    """Refuse to generate at all when no planner covers this class and subject."""
    if planners:
        return

    # A plan uploaded moments ago is not searchable until the ingestion worker
    # has chunked it. Saying so beats "no lesson planner was found", which reads
    # as though the upload never happened.
    still_indexing = await _uploads_awaiting_ingestion(
        db, subject=subject, class_level=class_level)
    if still_indexing:
        raise CurriculumComplianceError(
            f"The lesson plan for {subject}, {class_level} is still being indexed "
            f"({', '.join(still_indexing)}). Generation has been stopped because none of "
            "its content is searchable yet. This usually takes a minute — try again "
            "shortly, or check the Knowledge Base if it does not finish."
        )

    raise CurriculumComplianceError(
        f"No lesson planner was found for {subject}, {class_level}. Papers for Grades 1 "
        "and 2 may only be built from lessons recorded as taught in a lesson planner, so "
        "generation has been stopped. Either generate the plan in the Lesson Plan module, "
        "or ask the administrator to upload the lesson plan for this class and subject to "
        "the Knowledge Base, then try again."
    )


async def _uploads_awaiting_ingestion(
    db: AsyncSession,
    *,
    subject: str,
    class_level: str,
) -> list[str]:
    """Titles of matching uploaded plans that have not finished ingesting.

    Only consulted on the refusal path, so the successful path pays nothing.
    """
    if not applies_to(class_level):
        return []
    from services.lesson_plan_store import KB_DOCUMENT_TYPE

    result = await db.execute(
        select(Document).where(
            Document.document_type == KB_DOCUMENT_TYPE,
            Document.is_ingested.is_(False),
            Document.ingestion_error.is_(None),
        )
    )
    return [
        d.title for d in result.scalars().all()
        if _upload_matches(d, subject=subject, class_level=class_level)
    ]


def validate_paper(paper_data: dict, *, subject: str, class_level: str) -> list[dict]:
    """Check every question is sourced; return the flattened questions.

    Raises CurriculumComplianceError listing precisely what failed, so the
    administrator is told why no paper was produced instead of receiving one
    that quietly breaches the sourcing rules.
    """
    sections = paper_data.get("sections") or []
    if not sections:
        raise CurriculumComplianceError(
            f"The generated paper for {subject}, {class_level} contained no questions."
        )

    problems: list[str] = []
    checked: list[dict] = []

    for section in sections:
        for question in section.get("questions") or []:
            number = question.get("number", "?")
            source = question.get("source") or {}
            source_type = (source.get("type") or "").strip().lower()
            reference = (source.get("reference") or "").strip()

            if source_type not in APPROVED_SOURCES:
                problems.append(
                    f"Q{number}: source '{source_type or 'missing'}' is not an approved "
                    f"source ({', '.join(APPROVED_SOURCES)})."
                )
            if not reference:
                problems.append(f"Q{number}: no reference given for its source.")
            if not source.get("taught_confirmation"):
                problems.append(
                    f"Q{number}: not confirmed as already taught in the lesson planner."
                )
            checked.append(question)

    if problems:
        raise CurriculumComplianceError(
            f"Paper generation stopped for {subject}, {class_level}: the sourcing checks "
            "required for Grades 1 and 2 did not pass.\n- " + "\n- ".join(problems[:12])
            + ("\n- …and further issues." if len(problems) > 12 else "")
        )

    logger.info("[PRIMARY] %d questions validated against approved sources", len(checked))
    return checked


def strip_sources(questions: list[dict]) -> list[dict]:
    """Question list with the internal source references removed.

    Source metadata is for administrators; it must never reach a student's copy
    of the paper.
    """
    return [{k: v for k, v in q.items() if k != "source"} for q in questions or []]
