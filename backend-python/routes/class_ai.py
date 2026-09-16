"""
Academic and AI layer for Online Classes (spec §16–§19).

Four things live here:

  * **The lesson record** — what was actually taught, confirmed by the teacher.
    The system proposes; the teacher decides. Displaying a page is not proof of
    teaching it, and no amount of structured data changes that.
  * **Class summary, coverage analysis and revision notes** — generated once per
    class from written records and cached. Thirty students opening the summary
    produce one AI call between them, not thirty.
  * **Ask LSS AI About This Class** — a student types a question and gets a
    written answer, grounded in their own class's material with sources shown.
  * **Teacher AI assistant** — explanations, examples, quizzes, homework drafts
    the teacher confirms, edits or rejects before students ever see them.

All of it is text-to-text. Classroom audio is never read, transcribed or sent
anywhere, and every prompt says so, so no answer can pretend to have overheard
the lesson. If AI is unavailable, disabled or over budget, these endpoints
return a plain message and the classroom is unaffected.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from middleware.rate_limit import limiter
from models.models import Assignment, LessonPlan, User, utcnow
from models.online_classes import (
    OnlineClassAIOutput,
    OnlineClassAIQuestion,
    OnlineClassLessonRecord,
    OnlineClassResource,
    OnlineClassSession,
)
from services import class_context, class_events, class_matching, lss_ai_service
from services.classroom_access import get_session, is_host, require_host, require_member
from services.lss_ai_service import AIUnavailable
from services.online_class_config import get_settings

logger = logging.getLogger("agent")

router = APIRouter(prefix="/online-classes", tags=["online-classes-ai"])


# ─── Request bodies ───────────────────────────────────────────────────────────

class LessonRecordRequest(BaseModel):
    topics_covered: list[str] | None = None
    pages_covered: list[int] | None = None
    homework: str | None = None
    teacher_notes: str | None = None
    lesson_plan_id: str | None = None
    confirm: bool = False


class AskRequest(BaseModel):
    question: str


class AssistantRequest(BaseModel):
    request: str
    kind: str = "explain"   # explain | examples | quiz | simplify | revision | homework


class HomeworkPublishRequest(BaseModel):
    title: str
    description: str
    instructions: str | None = None
    due_date: str | None = None
    max_marks: int = 10


# ─── Lesson record (spec §16, §18) ────────────────────────────────────────────

async def _get_or_create_record(db: AsyncSession, session: OnlineClassSession) -> OnlineClassLessonRecord:
    record = (await db.execute(
        select(OnlineClassLessonRecord).where(OnlineClassLessonRecord.session_id == session.id)
    )).scalar_one_or_none()
    if record:
        return record

    # Seed from what the classroom actually did — pages presented are a
    # starting point for the teacher to edit, never a claim of coverage.
    resources = (await db.execute(
        select(OnlineClassResource).where(OnlineClassResource.session_id == session.id)
    )).scalars().all()
    pages: list[int] = []
    for resource in resources:
        pages.extend(resource.pages_presented or [])

    record = OnlineClassLessonRecord(
        session_id=session.id,
        lesson_plan_id=session.lesson_plan_id,
        pages_covered=sorted(set(pages)),
        topics_covered=[],
    )
    db.add(record)
    await db.flush()
    return record


@router.get("/{session_id}/lesson-record")
async def read_lesson_record(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_member(session, user)

    record = await _get_or_create_record(db, session)
    await db.commit()

    facts = await class_context.collect_class_facts(db, session)
    return {
        "session": session.to_dict(),
        "record": record.to_dict(),
        "presented": facts["resources"],
        "lesson_plan": facts["lesson_plan"],
        "can_edit": is_host(session, user),
    }


@router.put("/{session_id}/lesson-record")
async def update_lesson_record(
    session_id: str,
    body: LessonRecordRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """The teacher's word on what was taught. Only they can give it."""
    session = await get_session(db, session_id)
    require_host(session, user)

    record = await _get_or_create_record(db, session)
    if body.topics_covered is not None:
        record.topics_covered = body.topics_covered
    if body.pages_covered is not None:
        record.pages_covered = sorted({int(p) for p in body.pages_covered})
    if body.homework is not None:
        record.homework = body.homework
    if body.teacher_notes is not None:
        record.teacher_notes = body.teacher_notes
    if body.lesson_plan_id is not None:
        record.lesson_plan_id = body.lesson_plan_id or None

    if body.confirm:
        record.is_confirmed = True
        record.confirmed_by = user.id
        record.confirmed_at = utcnow()

        # A confirmed record changes the facts, so any summary written from the
        # earlier draft is now out of date rather than merely old.
        for output in (await db.execute(
            select(OnlineClassAIOutput).where(OnlineClassAIOutput.session_id == session.id)
        )).scalars().all():
            output.is_stale = True

    await db.commit()
    await db.refresh(record)

    if body.confirm:
        # The one controlled post-class AI job (spec §19E). Queued, not awaited:
        # confirming a lesson record must never wait on a language model.
        try:
            from tasks.online_class_tasks import generate_class_summary_task
            generate_class_summary_task.delay(session.id)
        except Exception as exc:  # pragma: no cover - broker unavailable
            logger.warning("[CLASS AI] summary job not queued for %s: %s", session.id, exc)

    return record.to_dict()


# ─── Cached AI outputs (spec §19E) ────────────────────────────────────────────

async def _cached(db: AsyncSession, session_id: str, kind: str) -> OnlineClassAIOutput | None:
    return (await db.execute(
        select(OnlineClassAIOutput).where(
            OnlineClassAIOutput.session_id == session_id,
            OnlineClassAIOutput.kind == kind,
        )
    )).scalar_one_or_none()


async def _store(
    db: AsyncSession,
    session_id: str,
    kind: str,
    *,
    content,
    sources: list[dict],
    model: str,
    usage: dict,
) -> OnlineClassAIOutput:
    output = await _cached(db, session_id, kind)
    if output is None:
        output = OnlineClassAIOutput(session_id=session_id, kind=kind)
        db.add(output)

    output.content = content
    output.sources = sources
    output.provider = "anthropic"
    output.model = model
    output.input_tokens = usage.get("input_tokens")
    output.output_tokens = usage.get("output_tokens")
    output.is_stale = False
    output.generated_at = utcnow()
    await db.commit()
    await db.refresh(output)
    return output


SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "3-5 sentences a student can read."},
        "topics": {"type": "array", "items": {"type": "string"}},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "homework": {"type": "string"},
        "revision_points": {"type": "array", "items": {"type": "string"}},
        "teacher_followups": {"type": "array", "items": {"type": "string"}},
        "not_in_record": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Things a reader might expect that the written record does not cover.",
        },
    },
    "required": ["summary", "topics", "key_points"],
}


async def _generate_summary(
    db: AsyncSession,
    session: OnlineClassSession,
    user: User | None,
) -> OnlineClassAIOutput:
    settings = await get_settings(db)
    facts = await class_context.collect_class_facts(db, session)

    query_terms = ", ".join(
        (facts.get("lesson_record") or {}).get("topics_covered") or []
    ) or " ".join(r["title"] for r in facts["resources"][:2]) or session.subject
    passages = await class_context.retrieve_supporting_material(db, session, query_terms)
    sources_text, citations = class_context.render_sources(passages)

    result = await lss_ai_service.generate(
        db,
        feature=lss_ai_service.CLASS_SUMMARY,
        settings=settings,
        system=(
            "You write class summaries for a school platform, for students aged 5-18.\n"
            f"{class_context.NO_SPEECH_RULE}\n"
            "Write plainly and warmly, at the reading level of the class. Never invent "
            "content that contradicts the textbook material given to you. If the record "
            "is thin, say what is missing in `not_in_record` rather than padding the summary."
        ),
        prompt=class_context.assemble_prompt(
            facts_text=class_context.render_facts(facts),
            sources_text=sources_text,
            task=(
                "Write the class summary for students, from the records above only. "
                "Give the topics, the key points worth remembering, the homework if the "
                "record states any, and short revision points."
            ),
        ),
        schema=SUMMARY_SCHEMA,
        max_tokens=1600,
        user=user,
        session_id=session.id,
        class_name=session.class_name,
    )

    return await _store(
        db, session.id, "summary",
        content=result["data"] or {"summary": result["text"]},
        sources=citations, model=result["model"], usage=result["usage"],
    )


@router.get("/{session_id}/summary")
async def read_summary(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The stored summary. Students read; they never trigger generation."""
    session = await get_session(db, session_id)
    require_member(session, user)

    output = await _cached(db, session.id, "summary")
    if output:
        return {"available": True, **output.to_dict()}

    return {
        "available": False,
        "message": "Your teacher has not published a summary for this class yet.",
    }


@router.post("/{session_id}/ai/summary")
async def generate_summary(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Generate (or refresh) the class summary — teacher-triggered, cached."""
    session = await get_session(db, session_id)
    require_host(session, user)

    existing = await _cached(db, session.id, "summary")
    if existing and not existing.is_stale:
        return {"reused": True, **existing.to_dict()}

    try:
        output = await _generate_summary(db, session, user)
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"reused": False, **output.to_dict()}


COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "covered": {"type": "array", "items": {"type": "string"}},
        "possibly_remaining": {"type": "array", "items": {"type": "string"}},
        "suggested_next_start": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["covered", "possibly_remaining"],
}


@router.post("/{session_id}/ai/coverage")
async def coverage_analysis(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Compare the approved plan with what was presented (spec §18).

    The result is a suggestion attached to the lesson record — never the record
    itself. The teacher confirms or edits it before it becomes official.
    """
    session = await get_session(db, session_id)
    require_host(session, user)

    if not session.lesson_plan_id:
        raise HTTPException(status_code=409, detail="No lesson plan is linked to this class.")

    settings = await get_settings(db)
    facts = await class_context.collect_class_facts(db, session)

    try:
        result = await lss_ai_service.generate(
            db,
            feature=lss_ai_service.COVERAGE_ANALYSIS,
            settings=settings,
            system=(
                "You compare a school's approved lesson plan against what a class "
                f"actually presented.\n{class_context.NO_SPEECH_RULE}\n"
                "A page being displayed is evidence it was shown, not proof it was "
                "taught. Phrase everything as a suggestion for the teacher to confirm."
            ),
            prompt=class_context.assemble_prompt(
                facts_text=class_context.render_facts(facts),
                sources_text="",
                task=(
                    "Compare the planned lesson with the material presented. List what "
                    "appears covered, what may remain, and where the next lesson could "
                    "reasonably start."
                ),
            ),
            schema=COVERAGE_SCHEMA,
            max_tokens=900,
            user=user,
            session_id=session.id,
            class_name=session.class_name,
        )
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    record = await _get_or_create_record(db, session)
    record.ai_suggestion = result["data"] or {"note": result["text"]}
    await db.commit()

    await _store(
        db, session.id, "coverage_analysis",
        content=record.ai_suggestion, sources=[],
        model=result["model"], usage=result["usage"],
    )
    return {"suggestion": record.ai_suggestion, "confirmed": False}


REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "key_concepts": {"type": "array", "items": {"type": "string"}},
        "definitions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["term", "meaning"],
            },
        },
        "practice_questions": {"type": "array", "items": {"type": "string"}},
        "quick_check": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["key_concepts", "practice_questions"],
}


@router.post("/{session_id}/ai/revision-notes")
async def revision_notes(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revision notes for this class — generated once, then served from store."""
    session = await get_session(db, session_id)
    require_member(session, user)

    existing = await _cached(db, session.id, "revision_notes")
    if existing and not existing.is_stale:
        return {"reused": True, **existing.to_dict()}

    # Students may trigger the first generation, because notes nobody can
    # produce are notes nobody gets — but only once per class, and inside the
    # same budget every other feature respects.
    settings = await get_settings(db)
    facts = await class_context.collect_class_facts(db, session)
    topics = (facts.get("lesson_record") or {}).get("topics_covered") or []
    query = ", ".join(topics) or session.subject

    passages = await class_context.retrieve_supporting_material(db, session, query)
    sources_text, citations = class_context.render_sources(passages)

    try:
        result = await lss_ai_service.generate(
            db,
            feature=lss_ai_service.REVISION_NOTES,
            settings=settings,
            system=(
                f"You write revision notes for {session.class_name} students.\n"
                f"{class_context.NO_SPEECH_RULE}\n"
                "Use the approved textbook material as the source of truth. Keep the "
                "language age-appropriate and concrete."
            ),
            prompt=class_context.assemble_prompt(
                facts_text=class_context.render_facts(facts),
                sources_text=sources_text,
                task="Write revision notes for this class: key concepts, important "
                     "definitions, and a few short practice questions.",
            ),
            schema=REVISION_SCHEMA,
            max_tokens=1600,
            user=user,
            session_id=session.id,
            class_name=session.class_name,
        )
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    output = await _store(
        db, session.id, "revision_notes",
        content=result["data"] or {"key_concepts": [], "practice_questions": []},
        sources=citations, model=result["model"], usage=result["usage"],
    )
    return {"reused": False, **output.to_dict()}


# ─── Ask LSS AI about this class (spec §19) ───────────────────────────────────

@router.post("/{session_id}/ask")
@limiter.limit("10/minute")
async def ask_about_class(
    request: Request,
    session_id: str,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The student types a question; LSS AI answers in writing.

    No microphone is involved at any point — the student types, and the answer
    comes from their own class's records and the approved textbook, with the
    sources listed so a teacher can check them.
    """
    session = await get_session(db, session_id)
    require_member(session, user)

    question = (body.question or "").strip()
    if len(question) < 3:
        raise HTTPException(status_code=400, detail="Please type your question.")
    if len(question) > 1000:
        raise HTTPException(status_code=400, detail="Please shorten your question.")

    # Someone in this class already asked this — reuse the answer rather than
    # paying for the same explanation thirty times.
    repeat = (await db.execute(
        select(OnlineClassAIQuestion).where(
            OnlineClassAIQuestion.session_id == session.id,
            OnlineClassAIQuestion.status == "answered",
            func.lower(OnlineClassAIQuestion.question) == question.lower(),
        ).limit(1)
    )).scalar_one_or_none()
    if repeat:
        return {"answer": repeat.answer, "sources": repeat.sources or [], "reused": True}

    settings = await get_settings(db)
    facts = await class_context.collect_class_facts(db, session)
    passages = await class_context.retrieve_supporting_material(db, session, question)
    sources_text, citations = class_context.render_sources(passages)

    young = class_matching.is_young_class(session.class_name, settings.young_classes)

    try:
        result = await lss_ai_service.generate(
            db,
            feature=lss_ai_service.ASK_AI,
            settings=settings,
            system=(
                f"You are LSS AI, helping a {session.class_name} student with their "
                f"{session.subject} class.\n{class_context.NO_SPEECH_RULE}\n"
                + ("Use very simple words and short sentences; the student is young.\n"
                   if young else
                   "Explain clearly and step by step, at the level of the class.\n")
                + "Answer from the approved textbook material and the class record. If "
                  "the answer is not in either, say so honestly and explain the topic "
                  "from the textbook material instead. Never invent facts that "
                  "contradict the book."
            ),
            prompt=class_context.assemble_prompt(
                facts_text=class_context.render_facts(facts),
                sources_text=sources_text,
                task=f"The student asks:\n\"{question}\"\n\nAnswer them directly.",
            ),
            max_tokens=1200,
            user=user,
            session_id=session.id,
            class_name=session.class_name,
        )
    except AIUnavailable as exc:
        db.add(OnlineClassAIQuestion(
            session_id=session.id, student_id=user.id, question=question,
            status="blocked" if exc.status != "failed" else "failed",
        ))
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc))

    record = OnlineClassAIQuestion(
        session_id=session.id,
        student_id=user.id,
        question=question,
        answer=result["text"],
        sources=citations,
        provider="anthropic",
        model=result["model"],
        status="answered",
    )
    db.add(record)
    await db.commit()

    return {"answer": result["text"], "sources": citations, "reused": False}


@router.get("/{session_id}/ask/history")
async def ask_history(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A student's own questions; a teacher sees the whole class's."""
    session = await get_session(db, session_id)
    role = require_member(session, user)

    query = select(OnlineClassAIQuestion).where(OnlineClassAIQuestion.session_id == session.id)
    if role == "student":
        query = query.where(OnlineClassAIQuestion.student_id == user.id)

    rows = (await db.execute(
        query.order_by(OnlineClassAIQuestion.created_at.desc()).limit(50)
    )).scalars().all()
    return {"questions": [q.to_dict() for q in rows]}


# ─── Teacher AI assistant (spec §19B.5, §19B.6) ───────────────────────────────

_ASSISTANT_TASKS = {
    "explain": "Explain this concept a different way, for this class's level.",
    "examples": "Give worked examples suitable for this class.",
    "quiz": "Write a short quiz (5 questions with answers) for this class.",
    "simplify": "Rewrite this in simpler language for this class.",
    "revision": "Write revision questions for this class.",
    "homework": "Suggest homework for this class, with clear instructions students can follow.",
}


@router.post("/{session_id}/ai/assistant")
@limiter.limit("20/minute")
async def teacher_assistant(
    request: Request,
    session_id: str,
    body: AssistantRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Text-based help for the teacher, grounded in this class's material."""
    session = await get_session(db, session_id)
    require_host(session, user)

    ask = (body.request or "").strip()
    if not ask:
        raise HTTPException(status_code=400, detail="Tell the assistant what you need.")

    settings = await get_settings(db)
    facts = await class_context.collect_class_facts(db, session)
    passages = await class_context.retrieve_supporting_material(db, session, ask)
    sources_text, citations = class_context.render_sources(passages)

    instruction = _ASSISTANT_TASKS.get(body.kind, _ASSISTANT_TASKS["explain"])

    try:
        result = await lss_ai_service.generate(
            db,
            feature=(
                lss_ai_service.HOMEWORK_DRAFT if body.kind == "homework"
                else lss_ai_service.TEACHER_ASSISTANT
            ),
            settings=settings,
            system=(
                f"You assist a teacher of {session.class_name} {session.subject}.\n"
                f"{class_context.NO_SPEECH_RULE}\n"
                "Ground everything in the approved textbook material. Be practical and "
                "brief — the teacher may be mid-lesson. Anything you draft is a "
                "proposal the teacher will edit or reject before students see it."
            ),
            prompt=class_context.assemble_prompt(
                facts_text=class_context.render_facts(facts),
                sources_text=sources_text,
                task=f"{instruction}\n\nTeacher's request: {ask}",
            ),
            max_tokens=1500,
            user=user,
            session_id=session.id,
            class_name=session.class_name,
        )
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"answer": result["text"], "sources": citations, "kind": body.kind}


@router.post("/{session_id}/homework/publish")
async def publish_homework(
    session_id: str,
    body: HomeworkPublishRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Publish homework to students through the existing Assignments module.

    Whatever the AI drafted, this is the teacher's text — they confirm or edit
    it here, and the assignment students receive is an ordinary LSS assignment,
    not an AI artefact.
    """
    session = await get_session(db, session_id)
    require_host(session, user)

    if not body.title.strip() or not body.description.strip():
        raise HTTPException(status_code=400, detail="Homework needs a title and a description.")

    from datetime import date as date_type

    due = None
    if body.due_date:
        try:
            due = date_type.fromisoformat(body.due_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Due date must be YYYY-MM-DD.")

    assignment = Assignment(
        title=body.title.strip(),
        description=body.description.strip(),
        subject=session.subject,
        class_name=session.class_name,
        section=session.section,
        teacher_id=session.teacher_id,
        due_date=due,
        assignment_type="homework",
        max_marks=body.max_marks or 10,
        instructions=(body.instructions or "").strip() or None,
    )
    db.add(assignment)

    record = await _get_or_create_record(db, session)
    record.homework = body.description.strip()

    await class_events.record(
        db, session.id, "homework_published",
        actor_id=user.id, actor_role=user.role, payload={"title": body.title},
    )
    await db.commit()
    await db.refresh(assignment)
    return {"assignment": assignment.to_dict(), "message": "Homework published to students."}


# ─── Lesson plans for the classroom (spec §18) ────────────────────────────────

@router.get("/{session_id}/lesson-plans")
async def available_lesson_plans(
    session_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Today's lesson plans for this class and subject, to link to the class."""
    session = await get_session(db, session_id)
    require_host(session, user)

    plans = (await db.execute(
        select(LessonPlan)
        .where(
            LessonPlan.teacher_id == session.teacher_id,
            LessonPlan.subject == session.subject,
            LessonPlan.is_archived == False,  # noqa: E712
        )
        .order_by(LessonPlan.created_at.desc())
        .limit(50)
    )).scalars().all()

    matching = [
        p for p in plans if class_matching.same_class(p.class_name, session.class_name)
    ]
    return {
        "plans": [
            {
                "id": p.id, "title": p.title, "plan_type": p.plan_type,
                "book_name": p.book_name, "is_published": p.is_published,
                "review_status": p.review_status,
                "lessons": [
                    {"id": l.get("id"), "title": l.get("title") or l.get("topic")}
                    for l in (p.plan_data or {}).get("lessons", [])[:40]
                ],
            }
            for p in matching
        ],
        "linked_plan_id": session.lesson_plan_id,
    }


class LinkPlanRequest(BaseModel):
    lesson_plan_id: str | None = None
    lesson_ref: str | None = None


@router.post("/{session_id}/lesson-plan")
async def link_lesson_plan(
    session_id: str,
    body: LinkPlanRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_host(session, user)

    session.lesson_plan_id = body.lesson_plan_id or None
    session.lesson_plan_ref = body.lesson_ref or None
    await db.commit()
    return {"lesson_plan_id": session.lesson_plan_id, "lesson_ref": session.lesson_plan_ref}
