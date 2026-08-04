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
  * classwork recorded in an uploaded Lesson Planner
  * bookwork from the approved textbook
  * end-of-chapter exercises
  * end-of-book exercises
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import LessonPlan
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
    """Lesson planners for this class and subject, newest first.

    Planners that have not started yet are dropped outright — nothing in them
    has been taught, so nothing in them may be examined.
    """
    as_of = as_of or date.today()

    result = await db.execute(
        select(LessonPlan)
        .where(LessonPlan.is_archived.is_(False))
        .order_by(LessonPlan.created_at.desc())
    )
    plans = list(result.scalars().all())

    def matches(plan: LessonPlan) -> bool:
        same_class = (plan.class_name or "").strip().lower() == (class_level or "").strip().lower()
        same_subject = (plan.subject or "").strip().lower() == (subject or "").strip().lower()
        return same_class and same_subject

    scoped = [p for p in plans if matches(p)]

    usable: list[dict] = []
    for plan in scoped:
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
            "plan_data": plan.plan_data or {},
        })
    return usable


def build_planner_context(planners: list[dict], as_of: date | None = None) -> str:
    """Format planners for the prompt, flagging how much of each was taught."""
    if not planners:
        return ""
    as_of = as_of or date.today()
    from services.lesson_plan_store import _flatten  # same readable rendering

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
        meta = [item["plan_type"].replace("_", " ").title() + " planner"]
        if item.get("book_name"):
            meta.append(f"Book: {item['book_name']}")
        if item.get("start_date") or item.get("end_date"):
            meta.append(f"{item.get('start_date') or '?'} → {item.get('end_date') or '?'}")
        header = (
            f'[LESSON PLANNER: "{item["title"]}" — {", ".join(meta)}]\n'
            f'[{notes[item["status"]]}]'
        )
        blocks.append(f"{header}\n{_flatten(item['plan_data'])}")
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


def require_planners(planners: list[dict], subject: str, class_level: str) -> None:
    """Refuse to generate at all when no planner covers this class and subject."""
    if planners:
        return
    raise CurriculumComplianceError(
        f"No lesson planner has been uploaded for {subject}, {class_level}. Papers for "
        "Grades 1 and 2 may only be built from lessons recorded as taught in a lesson "
        "planner, so generation has been stopped. Generate or upload the lesson planner "
        "for this class and subject, then try again."
    )


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
