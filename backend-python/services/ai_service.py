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
3. If the question is about a specific curriculum topic and neither the documents nor a web search yields a confident answer, respond: "I cannot find this specific information in the available school materials. Please consult your {'teacher or ' if role == 'student' else ''}the relevant textbook."
4. Be educational, clear, and supportive. Adapt depth to the audience.
5. Respond in the same language as the question (English or Urdu). Mathematical and scientific notation may stay in English.
6. For mathematics, show step-by-step solutions.
7. Stay aligned with the curriculum for grade-appropriate explanations."""

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
        history_msgs = [
            {"role": m["role"], "content": m["content"]}
            for m in conversation_history[-10:]
        ]

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

    topic_query = " ".join(topics) if topics else subject
    search_results = await search_knowledge_base(
        topic_query,
        subject=subject,
        class_level=class_level,
        document_type="book",
        limit=15,
    )
    if not search_results:
        raise ValueError("No content found in knowledge base for the specified subject and class level.")

    kb_context = build_context(search_results) or ""
    kb_sources = build_kb_sources(search_results)
    school = get_school()

    instructions = f"""Create a complete {paper_type.replace('_', ' ')} examination paper for {school}.

REQUIREMENTS:
- Subject: {subject}
- Class:   {class_level}
- Total marks:       {total_marks}
- Duration:          {duration_minutes} minutes
- Difficulty mix:    {difficulty.get('easy', 30)}% easy / {difficulty.get('medium', 50)}% medium / {difficulty.get('hard', 20)}% hard
{f"- Focus topics:      {', '.join(topics)}" if topics else ""}

STRUCTURE (distribute marks appropriately):
- Section A: Multiple Choice Questions (MCQs)
- Section B: Short Answer Questions
- Section C: Long Answer / Essay Questions

Use the curriculum content provided below as the SOLE source. Then call the `submit_question_paper` tool exactly once with the complete paper.

CURRICULUM CONTENT:
{kb_context}"""

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

    paper_data: dict[str, Any] | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_question_paper":
            paper_data = block.input
            break

    if not paper_data:
        raise ValueError("Claude did not return a structured question paper.")

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

    return {
        "paper_data": paper_data,
        "questions":  questions,
        "answer_key": answer_key,
        "sources":    [s["title"] for s in kb_sources],
    }


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
