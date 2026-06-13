"""
AI service — built on the official Anthropic Python SDK (AsyncAnthropic).

Features:
  • Real-time streaming (text_delta, tool_use, web search)
  • Plain-text RAG context (no Anthropic Citations API)
  • Web search tool (server-side, Anthropic-executed)
  • Structured outputs for exam papers via tool_use with strict JSON schema
  • Multi-language (English / Urdu) education-aligned system prompt
  • Persistent user memory + RAG knowledge-base context
  • Prompt caching on the static system prompt + tool definitions

Reference: https://docs.claude.com/en/api/messages-streaming
           https://docs.claude.com/en/build-with-claude/prompt-caching
           https://docs.claude.com/en/agents-and-tools/tool-use/overview
           https://docs.claude.com/en/agents-and-tools/tool-use/web-search-tool
"""
from __future__ import annotations

from typing import Any, AsyncGenerator

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_service import search_knowledge_base, build_context
from services.memory_service import search_user_memory, build_memory_context


# ─── CLIENT ───────────────────────────────────────────────────────────────────

_async_client: anthropic.AsyncAnthropic | None = None


def get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        from config.settings import ANTHROPIC_API_KEY
        _async_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _async_client


def get_model() -> str:
    from config.settings import AI_MODEL
    return AI_MODEL


def get_school() -> str:
    from config.settings import SCHOOL_NAME
    return SCHOOL_NAME


# ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────

def _static_system_text(role: str) -> str:
    """The role + school + rules portion. Identical across all requests for
    this user role, so it is the natural cache prefix."""
    school = get_school()
    audience = "students" if role == "student" else "teachers"

    text = f"""You are an educational AI assistant for {school}. Your role is to help {audience} with academic content.

PRIMARY KNOWLEDGE SOURCE — School Knowledge Base
The user will provide curriculum content from one or more school documents alongside their question. Those documents are the authoritative source for school curriculum content.

CRITICAL RULES:
1. Answer school-curriculum questions PRIMARILY from the provided curriculum content. You may refer to a chapter or page naturally in prose (e.g., "as covered in Chapter 5"), but do NOT include bracketed citation markers, footnote numbers, or [Source] tags in your answer.
2. Use the web_search tool ONLY for: current events, real-world examples, supplementary background that is NOT a school curriculum topic, or when the documents lack enough information AND the question is general knowledge. Never use web_search to override or contradict curriculum content.
3. When the user asks about a specific page, chapter, exercise, or question number (e.g. "what is on page 45", "explain page 45", "summarise Chapter 3"), the curriculum content provided to you IS the content from that location. Answer directly from it and mention the page or chapter naturally (e.g., "Page 45 covers..."). Do NOT claim the information is unavailable when matching content is provided.
4. Only if the question is about a specific curriculum topic AND neither the documents nor a web search yields a confident answer, respond: "I cannot find this specific information in the available school materials. Please consult your {'teacher or ' if role == 'student' else ''}the relevant textbook."
5. Be educational, clear, and supportive. Adapt depth to the audience.
6. Respond in the same language as the question (English or Urdu). Mathematical and scientific notation may stay in English.
7. For mathematics, show step-by-step solutions.
8. Stay aligned with the curriculum for grade-appropriate explanations."""

    if role == "student":
        text += "\n\nSTUDENT ASSISTANCE:\n- Explain concepts clearly with examples from the curriculum\n- Break complex topics into digestible parts\n- Provide structured notes and summaries\n- Help prepare assignment answers\n- Create practice questions"
    else:
        text += "\n\nTEACHER ASSISTANCE:\n- Help build lesson plans aligned with the curriculum\n- Generate quiz questions and assessments\n- Produce detailed answer keys\n- Suggest teaching strategies\n- Vary exam difficulty levels"

    return text


def build_system_blocks(
    role: str,
    subject: str | None,
    has_kb_context: bool,
    memory_context: str,
) -> list[dict]:
    """
    System as a list of content blocks:
      [0] static role/rules text  ←  cache_control: ephemeral  (cache breakpoint)
      [1] (optional) dynamic per-query notes + memory  ← NOT cached
    """
    blocks: list[dict] = [
        {
            "type": "text",
            "text": _static_system_text(role),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    dynamic_parts: list[str] = []
    if subject:
        dynamic_parts.append(f"Current subject context: {subject}.")
    if not has_kb_context:
        dynamic_parts.append(
            "NOTE: No curriculum documents were retrieved for this query. "
            "If the question is curriculum-related, tell the user this topic is not "
            "covered in the available school materials. For general knowledge or "
            "current events, you may use web_search."
        )
    if memory_context:
        dynamic_parts.append(memory_context)

    if dynamic_parts:
        blocks.append({"type": "text", "text": "\n\n".join(dynamic_parts)})

    return blocks


# ─── BUILD KB SOURCES SUMMARY ────────────────────────────────────────────────

def build_kb_sources(search_results: list[dict]) -> list[dict]:
    """Deduplicated list of source documents used in this answer (for UI display)."""
    seen: set[str] = set()
    sources: list[dict] = []
    for r in search_results:
        key = r.get("document_id") or r.get("document_title", "")
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "title":         r.get("document_title"),
            "subject":       r.get("subject"),
            "class_level":   r.get("class_level"),
            "document_type": r.get("document_type", "book"),
        })
    return sources


# ─── TOOLS ────────────────────────────────────────────────────────────────────

def build_web_search_tool(max_uses: int = 3, cached: bool = True) -> dict:
    """Anthropic-managed web search tool."""
    tool: dict = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max_uses,
    }
    if cached:
        tool["cache_control"] = {"type": "ephemeral"}
    return tool


# Structured-output tool: forces Claude to emit a complete exam paper as JSON
# with a strict schema, instead of asking for JSON-in-text and parsing it.
QUESTION_PAPER_TOOL: dict[str, Any] = {
    "name": "submit_question_paper",
    "description": (
        "Submit a complete examination paper. Call this once with the entire paper. "
        "Include 3 sections (MCQs, Short Answer, Long Answer) with appropriate mark "
        "distribution and difficulty mix. Every question must have a model answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Full paper title including subject and class"},
            "sections": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "name":         {"type": "string", "description": "e.g. 'Section A: Multiple Choice Questions'"},
                        "instructions": {"type": "string"},
                        "questions": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "number":    {"type": "integer", "minimum": 1},
                                    "question":  {"type": "string"},
                                    "type":      {"type": "string", "enum": ["mcq", "short_answer", "long_answer"]},
                                    "options":   {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "MCQ options like ['A) ...', 'B) ...']; omit for non-MCQ",
                                    },
                                    "correct_answer": {"type": "string", "description": "MCQ letter or model answer text"},
                                    "marks":          {"type": "integer", "minimum": 1},
                                    "difficulty":     {"type": "string", "enum": ["easy", "medium", "hard"]},
                                },
                                "required": ["number", "question", "type", "correct_answer", "marks", "difficulty"],
                            },
                        },
                    },
                    "required": ["name", "questions"],
                },
            },
        },
        "required": ["title", "sections"],
    },
}


# Structured-output tool: predicted "important" / likely exam questions, derived
# from analysing the past papers in the knowledge base.
IMPORTANT_QUESTIONS_TOOL: dict[str, Any] = {
    "name": "submit_important_questions",
    "description": (
        "Submit the predicted important / most-likely exam questions derived from analysing the "
        "provided past papers. Group by topic, rank by importance, and justify each prediction."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "1-3 sentence overview of the exam patterns found across the past papers"},
            "predictions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "topic":      {"type": "string", "description": "The topic / chapter this question belongs to"},
                        "question":   {"type": "string", "description": "A question likely to appear in the next exam"},
                        "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                        "frequency":  {"type": "string", "description": "How often this topic/question recurs, e.g. 'appears in 3 of 4 papers'"},
                        "rationale":  {"type": "string", "description": "Why this is likely to appear"},
                    },
                    "required": ["topic", "question", "importance", "rationale"],
                },
            },
        },
        "required": ["summary", "predictions"],
    },
}


# Structured-output tool: grades a student's self-assessment against a model key.
GRADE_ASSESSMENT_TOOL: dict[str, Any] = {
    "name": "submit_grading",
    "description": (
        "Submit the graded results of a student's self-assessment, with per-question scores, "
        "correctness, specific feedback, an overall summary, and weak topics to revise."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "number":     {"type": "integer", "minimum": 1},
                        "score":      {"type": "number", "description": "Marks awarded for this answer"},
                        "max_marks":  {"type": "integer", "minimum": 1},
                        "is_correct": {"type": "boolean"},
                        "feedback":   {"type": "string", "description": "Short, specific feedback for the student"},
                    },
                    "required": ["number", "score", "max_marks", "feedback"],
                },
            },
            "total_score":      {"type": "number"},
            "total_max":        {"type": "number"},
            "overall_feedback": {"type": "string", "description": "Encouraging 2-4 sentence summary of performance"},
            "weak_topics":      {"type": "array", "items": {"type": "string"}, "description": "Topics the student should revise"},
        },
        "required": ["results", "total_score", "total_max", "overall_feedback"],
    },
}


def _flatten_paper(paper_data: dict) -> tuple[list[dict], list[dict]]:
    """Flatten a submit_question_paper tool result into (questions, answer_key)."""
    questions: list[dict] = []
    answer_key: list[dict] = []
    for section in paper_data.get("sections", []):
        for q in section.get("questions", []):
            questions.append({
                "number":     q.get("number"),
                "section":    section.get("name"),
                "question":   q.get("question"),
                "type":       q.get("type"),
                "options":    q.get("options"),
                "marks":      q.get("marks"),
                "difficulty": q.get("difficulty"),
            })
            answer_key.append({
                "number":         q.get("number"),
                "correct_answer": q.get("correct_answer"),
                "marks":          q.get("marks"),
            })
    return questions, answer_key


def _extract_tool_input(response, tool_name: str) -> dict | None:
    """Return the input of the first tool_use block matching tool_name, or None."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return block.input
    return None


def _sanitize_history(history: list[dict]) -> list[dict]:
    """Normalise stored conversation history into a strictly alternating,
    non-empty user/assistant sequence ready to send to the Anthropic API.

    A prior turn whose assistant reply failed to persist (error, interruption,
    or an empty response after a long web search) leaves a dangling `user`
    message. Sent as-is, the API merges two consecutive `user` turns and the
    model answers the previous question before the current one. This collapses
    consecutive same-role turns (keeping the latest), drops empty messages and
    any leading assistant turn, and removes a trailing user turn so the freshly
    appended user message alternates correctly.
    """
    cleaned: list[dict] = []
    for m in history or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if cleaned and cleaned[-1]["role"] == role:
            # Collapse consecutive same-role turns, keeping the most recent.
            cleaned[-1] = {"role": role, "content": content}
        else:
            cleaned.append({"role": role, "content": content})

    # Must begin with a user turn.
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    # Drop a dangling trailing user turn (its reply was never recorded) so the
    # new user message we append next does not create two user turns in a row.
    while cleaned and cleaned[-1]["role"] == "user":
        cleaned.pop()
    return cleaned


# ─── STREAMING CHAT WITH RAG ─────────────────────────────────────────────────

async def stream_chat_with_rag(
    user_message: str,
    db: AsyncSession,
    **options: Any,
) -> AsyncGenerator[tuple[str, Any], None]:
    """
    Async generator yielding (event_type, data) tuples for SSE.

    Event types:
      "text"              → str chunk to append
      "web_search_query"  → str (the query Claude searched for)
      "web_search_result" → list of {url, title, page_age} dicts
      "tool_use"          → dict {name, id} — non-search tool invocation
      "done"              → {message, web_searches, sources, context_found, usage}
      "error"             → {message}
    """
    user_role = options.get("user_role", "student")
    subject = options.get("subject")
    class_level = options.get("class_level")
    document_type = options.get("document_type")
    language = options.get("language")
    conversation_history = options.get("conversation_history") or []
    user_id = options.get("user_id")
    session_id = options.get("session_id")
    enable_web_search = options.get("enable_web_search", True)

    try:
        # 1. RAG search → plain-text curriculum context
        search_results = await search_knowledge_base(
            user_message,
            subject=subject,
            class_level=class_level,
            document_type=document_type,
            language=language,
            limit=8,
        )
        kb_context = build_context(search_results)
        kb_sources = build_kb_sources(search_results)

        # 2. Past-conversation memory
        memory_context = ""
        if user_id:
            memories = await search_user_memory(
                user_id, user_message, db,
                current_session_id=session_id,
                subject=subject,
                limit=5,
            )
            memory_context = build_memory_context(memories)

        system_blocks = build_system_blocks(
            user_role,
            subject,
            has_kb_context=bool(kb_context),
            memory_context=memory_context,
        )

        # 3. Build messages — KB context goes inline as plain text
        history_msgs = _sanitize_history(conversation_history[-12:])
        # Keep the most recent turns while preserving the leading-user invariant.
        if len(history_msgs) > 10:
            history_msgs = history_msgs[-10:]
            while history_msgs and history_msgs[0]["role"] != "user":
                history_msgs.pop(0)

        if kb_context:
            user_text = (
                "Use the following curriculum content from the school knowledge base to answer the question. "
                "Refer to chapters or pages naturally in prose if helpful, but do not write bracketed citation "
                "markers in your answer.\n\n"
                f"{kb_context}\n\n---\n\nQuestion: {user_message}"
            )
        else:
            user_text = user_message

        messages = history_msgs + [{"role": "user", "content": user_text}]

        # 4. Tools — web search by default
        tools: list[dict] = []
        if enable_web_search:
            tools.append(build_web_search_tool(max_uses=3))

        # 5. Stream
        client = get_async_client()
        full_text_parts: list[str] = []
        web_searches: list[dict] = []  # {query, result_count, urls}
        current_search_query = ""
        current_search_id: str | None = None
        usage: dict[str, Any] = {}

        stream_kwargs: dict[str, Any] = {
            "model": get_model(),
            "max_tokens": 4096,
            "system": system_blocks,
            "messages": messages,
        }
        if tools:
            stream_kwargs["tools"] = tools

        async with client.messages.stream(**stream_kwargs) as stream:
            async for event in stream:
                etype = event.type

                if etype == "content_block_start":
                    block = event.content_block
                    btype = getattr(block, "type", None)
                    if btype == "server_tool_use" and getattr(block, "name", "") == "web_search":
                        current_search_id = block.id
                        current_search_query = ""

                elif etype == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", None)

                    if dtype == "text_delta":
                        text = delta.text
                        full_text_parts.append(text)
                        yield ("text", text)

                    elif dtype == "input_json_delta":
                        # Tool input being streamed (web_search query, etc.)
                        if current_search_id:
                            current_search_query += delta.partial_json

                elif etype == "content_block_stop":
                    if current_search_id and current_search_query:
                        try:
                            import json
                            q = json.loads(current_search_query).get("query", "")
                            if q:
                                yield ("web_search_query", q)
                                web_searches.append({"query": q, "id": current_search_id, "urls": []})
                        except json.JSONDecodeError:
                            pass
                        current_search_id = None
                        current_search_query = ""

            # Stream complete — fetch the final accumulated message
            final = await stream.get_final_message()

            if final.usage:
                usage = final.usage.model_dump() if hasattr(final.usage, "model_dump") else dict(final.usage)

            for block in final.content:
                btype = getattr(block, "type", None)
                if btype == "web_search_tool_result":
                    tool_use_id = getattr(block, "tool_use_id", None)
                    content = getattr(block, "content", None)
                    if isinstance(content, list):
                        results = []
                        for r in content:
                            if getattr(r, "type", None) == "web_search_result":
                                results.append({
                                    "url":      getattr(r, "url", ""),
                                    "title":    getattr(r, "title", ""),
                                    "page_age": getattr(r, "page_age", None),
                                })
                        for ws in web_searches:
                            if ws["id"] == tool_use_id:
                                ws["urls"] = results
                                break
                        yield ("web_search_result", results)

        full_message = "".join(full_text_parts)

        yield ("done", {
            "message":       full_message,
            "web_searches":  web_searches,
            "sources":       kb_sources,
            "context_found": bool(kb_context),
            "usage":         usage,
        })

    except anthropic.APIError as exc:
        yield ("error", {"message": f"Claude API error: {exc}"})
    except Exception as exc:
        import traceback
        traceback.print_exc()
        yield ("error", {"message": str(exc)})


# ─── NON-STREAMING CHAT WITH RAG (for tools/internal use) ────────────────────

async def chat_with_rag(
    user_message: str,
    db: AsyncSession,
    **options: Any,
) -> dict:
    """One-shot chat. Returns full message + sources."""
    full_message = ""
    web_searches: list[dict] = []
    sources: list[dict] = []
    context_found = False

    async for etype, data in stream_chat_with_rag(user_message, db, **options):
        if etype == "done":
            full_message  = data["message"]
            web_searches  = data["web_searches"]
            sources       = data["sources"]
            context_found = data["context_found"]
        elif etype == "error":
            raise RuntimeError(data["message"])

    return {
        "message":       full_message,
        "web_searches":  web_searches,
        "sources":       sources,
        "context_found": context_found,
    }


# ─── GENERATE QUESTION PAPER (structured output via tool_use) ────────────────

async def generate_question_paper(params: dict, db: AsyncSession) -> dict:
    subject          = params["subject"]
    class_level      = params["class_level"]
    paper_type       = params["paper_type"]
    total_marks      = params.get("total_marks", 100)
    duration_minutes = params.get("duration_minutes", 60)
    topics           = params.get("topics", [])
    difficulty       = params.get("difficulty_distribution", {"easy": 30, "medium": 50, "hard": 20})
    generation_mode  = params.get("generation_mode", "standard")   # "standard" | "model"
    use_past_papers  = params.get("use_past_papers", True)

    topic_query = " ".join(topics) if topics else subject

    # Curriculum (book) content — the source of truth for facts and topics.
    book_results = await search_knowledge_base(
        topic_query, subject=subject, class_level=class_level,
        document_type="book", limit=15,
    )

    # Past-paper (exam) content — pattern/style reference; required for model mode.
    past_results: list[dict] = []
    if use_past_papers or generation_mode == "model":
        past_results = await search_knowledge_base(
            topic_query, subject=subject, class_level=class_level,
            document_type="exam", limit=15,
        )

    if generation_mode == "model" and not past_results:
        raise ValueError(
            "No past papers found for this subject and class. Upload past papers in the "
            "Knowledge Base first, or switch to Standard mode."
        )
    if not book_results and not past_results:
        raise ValueError("No content found in knowledge base for the specified subject and class level.")

    book_context = build_context(book_results) or ""
    past_context = build_context(past_results) or ""
    kb_sources = build_kb_sources(book_results + past_results)
    school = get_school()

    requirements = f"""REQUIREMENTS:
- Subject: {subject}
- Class:   {class_level}
- Total marks:       {total_marks}
- Duration:          {duration_minutes} minutes
- Difficulty mix:    {difficulty.get('easy', 30)}% easy / {difficulty.get('medium', 50)}% medium / {difficulty.get('hard', 20)}% hard
{f"- Focus topics:      {', '.join(topics)}" if topics else ""}"""

    if generation_mode == "model":
        header = (
            f"Create a MODEL {paper_type.replace('_', ' ')} paper for {school} by analysing the PAST "
            "PAPERS provided below. Study them to infer the section structure, marks distribution, "
            "question styles, recurring topics, and difficulty balance, then produce a NEW paper that "
            "mirrors that exam pattern. Do NOT copy past-paper questions verbatim — write fresh "
            "questions in the same style. Keep every question aligned to the curriculum content."
        )
    else:
        header = (
            f"Create a complete {paper_type.replace('_', ' ')} examination paper for {school}.\n\n"
            "STRUCTURE (distribute marks appropriately):\n"
            "- Section A: Multiple Choice Questions (MCQs)\n"
            "- Section B: Short Answer Questions\n"
            "- Section C: Long Answer / Essay Questions"
        )

    context_blocks = f"CURRICULUM CONTENT (source of truth):\n{book_context or '(none provided)'}"
    if past_context:
        context_blocks += (
            "\n\n---\n\nPAST PAPER REFERENCE (use for structure, style, difficulty and recurring "
            f"topics — do not copy verbatim):\n{past_context}"
        )

    instructions = (
        f"{header}\n\n{requirements}\n\n"
        "Use the content below. Then call the `submit_question_paper` tool exactly once with the "
        f"complete paper.\n\n{context_blocks}"
    )

    paper_system = [{
        "type": "text",
        "text": (
            f"You are an expert examination-paper creator for {school}. "
            "Build curriculum-aligned papers strictly from the provided content. "
            "Always finish by calling the submit_question_paper tool with the complete structured paper."
        ),
        "cache_control": {"type": "ephemeral"},
    }]

    paper_tool = dict(QUESTION_PAPER_TOOL)
    paper_tool["cache_control"] = {"type": "ephemeral"}

    response = await get_async_client().messages.create(
        model=get_model(),
        max_tokens=8192,
        system=paper_system,
        messages=[{"role": "user", "content": instructions}],
        tools=[paper_tool],
        tool_choice={"type": "tool", "name": "submit_question_paper"},
    )

    paper_data = _extract_tool_input(response, "submit_question_paper")
    if not paper_data:
        raise ValueError("Claude did not return a structured question paper.")

    questions, answer_key = _flatten_paper(paper_data)

    return {
        "paper_data": paper_data,
        "questions":  questions,
        "answer_key": answer_key,
        "sources":    [s["title"] for s in kb_sources],
    }


# ─── PREDICT IMPORTANT QUESTIONS (from past papers) ──────────────────────────

async def predict_important_questions(
    subject: str,
    class_level: str,
    paper_type: str | None = None,
) -> dict:
    """Analyse uploaded past papers for a subject/class and predict likely exam questions."""
    results = await search_knowledge_base(
        f"{subject} {class_level} important exam questions topics",
        subject=subject, class_level=class_level,
        document_type="exam", limit=40,
    )
    if not results:
        raise ValueError(
            "No past papers found for this subject and class. Upload past papers in the "
            "Knowledge Base first."
        )

    context = build_context(results) or ""
    sources = build_kb_sources(results)
    school = get_school()

    instructions = f"""Analyse the PAST EXAM PAPERS below for {subject} ({class_level}) at {school}.
Identify the topics and questions that recur most often and are therefore most likely to appear in the
next exam. Consider frequency across papers, marks weighting, and curriculum importance. Predict a
focused set (roughly 10-20) of the most important questions, grouped by topic. Then call the
`submit_important_questions` tool exactly once.

PAST PAPERS:
{context}"""

    system = [{
        "type": "text",
        "text": (
            f"You are an exam-pattern analyst for {school}. You study past papers to predict likely "
            "questions. Be concrete and base every prediction on evidence in the provided papers. "
            "Always finish by calling the submit_important_questions tool."
        ),
        "cache_control": {"type": "ephemeral"},
    }]
    tool = dict(IMPORTANT_QUESTIONS_TOOL)
    tool["cache_control"] = {"type": "ephemeral"}

    response = await get_async_client().messages.create(
        model=get_model(),
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": instructions}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_important_questions"},
    )

    data = _extract_tool_input(response, "submit_important_questions")
    if not data:
        raise ValueError("Claude did not return any predictions.")

    return {
        "summary":     data.get("summary", ""),
        "predictions": data.get("predictions", []),
        "sources":     [s["title"] for s in sources],
    }


# ─── GENERATE PRACTICE TEST (student self-practice) ──────────────────────────

async def generate_practice_test(
    subject: str,
    class_level: str,
    topics: list[str] | None = None,
    num_questions: int = 10,
    difficulty: str = "mixed",
) -> dict:
    """Generate a lightweight, self-gradable practice test from books + past papers."""
    topics = topics or []
    topic_query = " ".join(topics) if topics else subject

    book_results = await search_knowledge_base(
        topic_query, subject=subject, class_level=class_level,
        document_type="book", limit=10,
    )
    past_results = await search_knowledge_base(
        topic_query, subject=subject, class_level=class_level,
        document_type="exam", limit=6,
    )
    if not book_results and not past_results:
        raise ValueError("No content found in the knowledge base for this subject and class.")

    context = build_context(book_results + past_results) or ""
    sources = build_kb_sources(book_results + past_results)
    school = get_school()

    diff_line = {
        "easy":   "Keep all questions easy.",
        "medium": "Keep all questions at medium difficulty.",
        "hard":   "Make all questions challenging.",
        "mixed":  "Use a mix of easy, medium, and hard questions.",
    }.get(difficulty, "Use a mix of easy, medium, and hard questions.")

    instructions = f"""Create a self-practice test for {class_level} {subject} students at {school}.
- Exactly {num_questions} questions in total.
- {diff_line}
- Favour Multiple Choice and Short Answer questions suitable for quick self-assessment; you may include
  1-2 long-answer questions.
- Every question MUST include a clear, complete model answer in `correct_answer`.
{f"- Focus topics: {', '.join(topics)}" if topics else ""}

Use ONLY the curriculum content below. Then call the `submit_question_paper` tool exactly once.

CURRICULUM CONTENT:
{context}"""

    system = [{
        "type": "text",
        "text": (
            f"You are a practice-test creator for {school}. Build curriculum-aligned self-practice tests "
            "strictly from the provided content. Always finish by calling the submit_question_paper tool."
        ),
        "cache_control": {"type": "ephemeral"},
    }]
    tool = dict(QUESTION_PAPER_TOOL)
    tool["cache_control"] = {"type": "ephemeral"}

    response = await get_async_client().messages.create(
        model=get_model(),
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": instructions}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_question_paper"},
    )

    paper_data = _extract_tool_input(response, "submit_question_paper")
    if not paper_data:
        raise ValueError("Claude did not return a practice test.")

    questions, answer_key = _flatten_paper(paper_data)
    return {
        "title":      paper_data.get("title", f"{subject} Practice Test"),
        "questions":  questions,
        "answer_key": answer_key,
        "sources":    [s["title"] for s in sources],
    }


# ─── GRADE STUDENT SELF-ASSESSMENT ───────────────────────────────────────────

async def grade_self_assessment(
    questions: list[dict],
    answer_key: list[dict],
    student_answers: dict,
) -> dict:
    """Grade a student's practice answers against the model key; return scores + feedback."""
    school = get_school()
    key_by_num = {a.get("number"): a for a in answer_key}

    def _student_answer(num) -> str:
        return str(
            student_answers.get(str(num))
            if student_answers.get(str(num)) is not None
            else student_answers.get(num, "")
        ).strip()

    blocks: list[str] = []
    for q in questions:
        num = q.get("number")
        marks = q.get("marks", 1)
        opts = ("\nOptions: " + " | ".join(q.get("options") or [])) if q.get("options") else ""
        model = key_by_num.get(num, {}).get("correct_answer", "")
        ans = _student_answer(num) or "(no answer)"
        blocks.append(
            f"Q{num} ({marks} marks) [{q.get('type', 'short_answer')}]: {q.get('question')}{opts}\n"
            f"Model answer: {model}\n"
            f"Student answer: {ans}"
        )

    instructions = f"""Grade this student's self-assessment for {school}. For each question, compare the
student's answer to the model answer and award marks out of that question's marks. MCQs are
all-or-nothing; short/long answers may receive partial credit for partially correct reasoning. Give brief,
specific, encouraging feedback per question. Then summarise overall performance and list weak topics to
revise. Call the `submit_grading` tool exactly once.

{chr(10).join(f'---{chr(10)}{b}' for b in blocks)}"""

    system = [{
        "type": "text",
        "text": (
            "You are a fair, encouraging examiner. Grade strictly against the model answers but reward "
            "correct reasoning and partial understanding. Always finish by calling the submit_grading tool."
        ),
        "cache_control": {"type": "ephemeral"},
    }]
    tool = dict(GRADE_ASSESSMENT_TOOL)
    tool["cache_control"] = {"type": "ephemeral"}

    response = await get_async_client().messages.create(
        model=get_model(),
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": instructions}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_grading"},
    )

    data = _extract_tool_input(response, "submit_grading")
    if not data:
        raise ValueError("Claude did not return grading results.")
    return data


# ─── GENERATE ASSIGNMENT CONTENT ─────────────────────────────────────────────

async def generate_assignment_content(params: dict, db: AsyncSession) -> dict:
    """Creates assignment text using plain-text curriculum context."""
    topic           = params["topic"]
    subject         = params["subject"]
    class_level     = params["class_level"]
    assignment_type = params.get("assignment_type", "homework")
    school          = get_school()

    search_results = await search_knowledge_base(
        topic,
        subject=subject,
        class_level=class_level,
        document_type="book",
        limit=8,
    )
    if not search_results:
        raise ValueError("No relevant content found in the knowledge base for this topic.")

    kb_context = build_context(search_results) or ""
    kb_sources = build_kb_sources(search_results)

    prompt = f"""Create a {assignment_type} assignment for {class_level} students on the topic: "{topic}".

Produce, using ONLY the curriculum content provided below:
1. A clear assignment title
2. 3-5 learning objectives
3. Detailed instructions for the student
4. {'5 research questions' if assignment_type == 'research' else '5 specific tasks/questions'}
5. An evaluation rubric

Keep it strictly aligned with the supplied content. Do not write bracketed citation markers in your answer.

CURRICULUM CONTENT:
{kb_context}"""

    assignment_system = [{
        "type": "text",
        "text": (
            f"You are an educational content creator for {school}. "
            "Build assignments strictly from the provided content."
        ),
        "cache_control": {"type": "ephemeral"},
    }]

    response = await get_async_client().messages.create(
        model=get_model(),
        max_tokens=2048,
        system=assignment_system,
        messages=[{"role": "user", "content": prompt}],
    )

    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text

    return {
        "content":   text,
        "sources":   [s["title"] for s in kb_sources],
    }
