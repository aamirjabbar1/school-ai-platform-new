"""
What the AI is allowed to know about a class.

Everything here is written or structured: the lesson plan a teacher approved,
the pages the classroom actually displayed, the boards that were saved, the
record the teacher confirmed, and Knowledge Base passages retrieved for the
question at hand.

Nothing here comes from listening. The AI is never told what was *said* in the
lesson, because nothing in this system converts speech to text — so a summary
must not imply otherwise, and the prompts below say so explicitly rather than
leaving it to the model's discretion.

Retrieval happens before generation and is scoped to the class and subject, so
a question about photosynthesis does not drag the whole library into a prompt.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import LessonPlan
from models.online_classes import (
    OnlineClassEvent,
    OnlineClassLessonRecord,
    OnlineClassResource,
    OnlineClassSession,
    OnlineClassWhiteboard,
)
from services.curriculum_service import resolve_curriculum_class

logger = logging.getLogger("agent")

# Caps chosen so a prompt stays small enough to be cheap and focused. Sending
# more material does not make an answer better; it makes it vaguer.
MAX_KB_PASSAGES = 6
MAX_PLAN_CHARS = 2500
MAX_CONTEXT_CHARS = 14000

# Stated in every system prompt. A model that implies it heard the lesson would
# be lying to a child about what the school knows.
NO_SPEECH_RULE = (
    "You did not attend the class and you have no recording, transcript or any "
    "record of what anyone said. Never claim or imply that you know what the "
    "teacher explained aloud. Work only from the written records below, and if "
    "they do not cover something, say plainly that it is not in the class "
    "record and answer from the approved textbook material instead."
)


# ─── Structured class facts ───────────────────────────────────────────────────

async def collect_class_facts(db: AsyncSession, session: OnlineClassSession) -> dict[str, Any]:
    """Everything the application already knows about this class."""
    resources = (await db.execute(
        select(OnlineClassResource)
        .where(OnlineClassResource.session_id == session.id)
        .order_by(OnlineClassResource.first_shown_at)
    )).scalars().all()

    boards = (await db.execute(
        select(OnlineClassWhiteboard).where(OnlineClassWhiteboard.session_id == session.id)
    )).scalars().all()

    record = (await db.execute(
        select(OnlineClassLessonRecord).where(OnlineClassLessonRecord.session_id == session.id)
    )).scalar_one_or_none()

    plan = None
    if session.lesson_plan_id:
        plan = (await db.execute(
            select(LessonPlan).where(LessonPlan.id == session.lesson_plan_id)
        )).scalar_one_or_none()

    events = (await db.execute(
        select(OnlineClassEvent)
        .where(
            OnlineClassEvent.session_id == session.id,
            OnlineClassEvent.type.in_(("screen_share_started", "whiteboard_saved", "book_opened")),
        )
        .order_by(OnlineClassEvent.at)
        .limit(80)
    )).scalars().all()

    return {
        "session": {
            "subject": session.subject,
            "class_name": session.class_name,
            "section": session.section,
            "teacher": session.teacher_name,
            "date": session.actual_start.strftime("%d %B %Y") if session.actual_start else None,
            "minutes": round(session.duration_seconds / 60) if session.actual_start else None,
        },
        "resources": [
            {
                "title": r.title,
                "type": r.resource_type,
                "pages_presented": r.pages_presented or [],
            }
            for r in resources
        ],
        "whiteboards_saved": len(boards),
        "lesson_plan": _plan_extract(plan, session.lesson_plan_ref),
        "lesson_record": record.to_dict() if record else None,
        "activity": [{"type": e.type, "payload": e.payload or {}} for e in events],
    }


def _plan_extract(plan: LessonPlan | None, ref: str | None) -> dict | None:
    """The part of a lesson plan relevant to this class, not the whole term."""
    if not plan:
        return None

    data = plan.plan_data or {}
    lessons = data.get("lessons") or []
    chosen = None
    if ref:
        chosen = next(
            (l for l in lessons if str(l.get("id")) == ref or str(l.get("title")) == ref),
            None,
        )
    if chosen is None and lessons:
        chosen = lessons[0]

    return {
        "title": plan.title,
        "book": plan.book_name,
        "board": plan.board,
        "lesson": _truncate_json(chosen, MAX_PLAN_CHARS) if chosen else None,
        "summary": _truncate_json(data.get("summary"), 800) if data.get("summary") else None,
    }


def _truncate_json(value, limit: int) -> str:
    """Render a plan fragment as text, capped. A plan can be a term's worth of
    lessons; the prompt only needs today's."""
    import json

    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "… (truncated)"


# ─── Knowledge Base retrieval ─────────────────────────────────────────────────

async def retrieve_supporting_material(
    db: AsyncSession,
    session: OnlineClassSession,
    query: str,
    *,
    limit: int = MAX_KB_PASSAGES,
) -> list[dict]:
    """Approved textbook passages for this class, chosen for this question.

    Retrieval is scoped to the class (through the Pre-Board curriculum mapping,
    so a class studying next year's syllabus gets the right book) and the
    subject. Never the whole Knowledge Base.
    """
    from services.document_service import search_knowledge_base

    kb_class = await resolve_curriculum_class(session.class_name, db)
    try:
        return await search_knowledge_base(
            query=query,
            subject=session.subject,
            class_level=kb_class,
            limit=limit,
        )
    except Exception as exc:
        logger.warning("[CLASS CONTEXT] retrieval failed for %s: %s", session.id, exc)
        return []


# ─── Prompt assembly ──────────────────────────────────────────────────────────

def render_facts(facts: dict) -> str:
    """The structured record, written out for a language model to read."""
    s = facts["session"]
    lines = [
        "CLASS RECORD (structured data recorded by the system, not speech):",
        f"- Subject: {s['subject']}",
        f"- Class: {s['class_name']}" + (f" section {s['section']}" if s.get("section") else ""),
        f"- Teacher: {s['teacher'] or 'Not recorded'}",
        f"- Date: {s['date'] or 'Not recorded'}",
        f"- Length: {s['minutes']} minutes" if s.get("minutes") else "- Length: not recorded",
    ]

    if facts["resources"]:
        lines.append("\nMATERIAL PRESENTED IN CLASS:")
        for r in facts["resources"]:
            pages = r["pages_presented"]
            page_text = f" — pages {_page_ranges(pages)}" if pages else ""
            lines.append(f"- {r['title']}{page_text}")
        lines.append(
            "(A page being displayed means it was shown on screen. It does not prove "
            "every part of it was taught.)"
        )
    else:
        lines.append("\nMATERIAL PRESENTED IN CLASS: none recorded.")

    if facts["whiteboards_saved"]:
        lines.append(f"\nWHITEBOARDS SAVED: {facts['whiteboards_saved']} board(s) kept with this lesson.")

    plan = facts.get("lesson_plan")
    if plan:
        lines.append("\nAPPROVED LESSON PLAN:")
        lines.append(f"- Plan: {plan['title']}" + (f" (book: {plan['book']})" if plan.get("book") else ""))
        if plan.get("lesson"):
            lines.append(f"- Planned for this lesson: {plan['lesson']}")

    record = facts.get("lesson_record")
    if record and record.get("is_confirmed"):
        lines.append("\nTEACHER-CONFIRMED LESSON RECORD (authoritative):")
        if record.get("topics_covered"):
            lines.append(f"- Topics covered: {', '.join(record['topics_covered'])}")
        if record.get("pages_covered"):
            lines.append(f"- Pages covered: {_page_ranges(record['pages_covered'])}")
        if record.get("homework"):
            lines.append(f"- Homework set: {record['homework']}")
        if record.get("teacher_notes"):
            lines.append(f"- Teacher's notes: {record['teacher_notes']}")
    elif record:
        lines.append(
            "\nLESSON RECORD: drafted but not yet confirmed by the teacher — treat as provisional."
        )
    else:
        lines.append("\nLESSON RECORD: the teacher has not confirmed one yet.")

    return "\n".join(lines)


def _page_ranges(pages: list[int]) -> str:
    """"24-27, 31" rather than a list of numbers a reader has to scan."""
    if not pages:
        return ""
    ordered = sorted({int(p) for p in pages})
    spans, start, previous = [], ordered[0], ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        spans.append((start, previous))
        start = previous = page
    spans.append((start, previous))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


def render_sources(passages: list[dict]) -> tuple[str, list[dict]]:
    """Textbook passages plus the citation list shown to the reader."""
    from services.document_service import build_context

    if not passages:
        return "", []

    context = build_context(passages) or ""
    citations = [
        {
            "title": p.get("document_title"),
            "subject": p.get("subject"),
            "class_level": p.get("class_level"),
            "chapter": p.get("chapter_title") or None,
            "page": p.get("page_number") or None,
        }
        for p in passages
    ]
    return context, citations


def assemble_prompt(*, facts_text: str, sources_text: str, task: str) -> str:
    """One prompt: what happened, what the books say, what to produce."""
    parts = [facts_text]
    if sources_text:
        parts.append("APPROVED TEXTBOOK AND KNOWLEDGE BASE MATERIAL:\n" + sources_text)
    parts.append(task)
    prompt = "\n\n".join(parts)
    return prompt[:MAX_CONTEXT_CHARS]
