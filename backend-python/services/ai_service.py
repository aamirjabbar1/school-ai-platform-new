"""
AI service — built on the official Anthropic Python SDK (AsyncAnthropic).

Features:
  • Real-time streaming (text_delta, citations_delta, tool_use, web search)
  • Native Citations API — each RAG chunk becomes a citable custom-content document
  • Web search tool (server-side, Anthropic-executed, with auto-citations)
  • Structured outputs for exam papers via tool_use with strict JSON schema
  • Multi-language (English / Urdu) education-aligned system prompt
  • Persistent user memory + RAG knowledge-base context
  • Prompt caching on the static system prompt + tool definitions
    (cache_control breakpoints per Anthropic prompt-caching guidelines)

Reference: https://docs.claude.com/en/api/messages-streaming
           https://docs.claude.com/en/build-with-claude/citations
           https://docs.claude.com/en/build-with-claude/prompt-caching
           https://docs.claude.com/en/agents-and-tools/tool-use/overview
           https://docs.claude.com/en/agents-and-tools/tool-use/web-search-tool
"""
from __future__ import annotations

from typing import Any, AsyncGenerator

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_service import search_knowledge_base
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
#
# Architecture: split into a STATIC block (role + school + rules — cacheable)
# and a DYNAMIC block (per-query notes + memory — not cached). Cache breakpoint
# sits on the static block. Per Anthropic docs, this lets Claude reuse the
# static prefix across requests at 0.1× input rate when its token count
# crosses the model's minimum cacheable threshold.

def _static_system_text(role: str) -> str:
    """The role + school + rules portion. Identical across all requests for
    this user role, so it is the natural cache prefix."""
    school = get_school()
    audience = "students" if role == "student" else "teachers"

    text = f"""You are an educational AI assistant for {school}. Your role is to help {audience} with academic content.

PRIMARY KNOWLEDGE SOURCE — School Knowledge Base
The user will provide one or more curriculum documents alongside their question. Those documents are the authoritative source for school curriculum content.

CRITICAL RULES:
1. Answer school-curriculum questions PRIMARILY from the provided curriculum documents. When you draw on them, the API attaches structured citations automatically — do not format citations manually.
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

    This way the static prefix is reusable across requests while per-query
    info (subject, kb-empty notice, memory recall) sits after the breakpoint.
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


# ─── BUILD CITATION DOCUMENTS FROM RAG RESULTS ───────────────────────────────

def build_citation_documents(search_results: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Convert Milvus chunks into Anthropic citation documents.

    Strategy: group chunks by source document_id so each source becomes one
    custom-content document with multiple content blocks (one per chunk).
    Citations will reference (document_index, start_block_index, end_block_index)
    which we can map back to chapter/page metadata.

    Returns:
      documents: list[dict]  — Anthropic-format document content blocks
      doc_metadata: list[dict] — parallel list with our metadata for citation
                                  enrichment (one entry per document_index)
    """
    if not search_results:
        return [], []

    # Group chunks by document_id, preserving first-appearance order
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in search_results:
        doc_id = r.get("document_id") or r.get("document_title", "unknown")
        if doc_id not in grouped:
            grouped[doc_id] = []
            order.append(doc_id)
        grouped[doc_id].append(r)

    documents: list[dict] = []
    doc_metadata: list[dict] = []

    for doc_id in order:
        chunks = grouped[doc_id]
        first = chunks[0]

        # Custom content blocks — preserves chunk-level granularity for citations
        content_blocks = [{"type": "text", "text": c["chunk_text"]} for c in chunks]

        # Build a context string carrying metadata Claude can use but won't cite from
        ctx_parts = [
            f"Subject: {first['subject']}",
            f"Class: {first['class_level']}",
            f"Type: {first.get('document_type', 'book')}",
        ]
        if first.get("language"):
            ctx_parts.append(f"Language: {first['language']}")
        if first.get("term"):
            ctx_parts.append(f"Term: {first['term']}")
        if first.get("academic_year"):
            ctx_parts.append(f"Academic Year: {first['academic_year']}")

        documents.append({
            "type": "document",
            "source": {
                "type": "content",
                "content": content_blocks,
            },
            "title": (first["document_title"] or "Untitled")[:255],
            "context": " | ".join(ctx_parts),
            "citations": {"enabled": True},
        })

        # Per-block metadata for citation enrichment (chapter, page, etc.)
        block_meta = [
            {
                "chapter_number": c.get("chapter_number", 0),
                "chapter_title":  c.get("chapter_title", ""),
                "page_number":    c.get("page_number", 0),
                "chunk_index":    c.get("chunk_index", 0),
                "score":          c.get("score"),
            }
            for c in chunks
        ]

        doc_metadata.append({
            "document_id":    doc_id,
            "document_title": first["document_title"],
            "subject":        first["subject"],
            "class_level":    first["class_level"],
            "document_type":  first.get("document_type", "book"),
            "language":       first.get("language"),
            "term":           first.get("term"),
            "academic_year":  first.get("academic_year"),
            "blocks":         block_meta,
        })

    return documents, doc_metadata


def enrich_citation(citation: dict, doc_metadata: list[dict]) -> dict:
    """Attach our extra metadata (chapter, page, subject, etc.) to a citation."""
    out = dict(citation)
    ctype = citation.get("type")
    doc_idx = citation.get("document_index")

    if ctype in ("content_block_location", "char_location", "page_location") \
            and doc_idx is not None and 0 <= doc_idx < len(doc_metadata):
        meta = doc_metadata[doc_idx]
        out["subject"] = meta["subject"]
        out["class_level"] = meta["class_level"]
        out["document_type"] = meta["document_type"]
        out["language"] = meta["language"]
        out["term"] = meta["term"]
        out["academic_year"] = meta["academic_year"]

        # For custom-content citations, pull chapter/page from the cited block(s)
        if ctype == "content_block_location":
            start = citation.get("start_block_index", 0)
            blocks = meta["blocks"]
            if 0 <= start < len(blocks):
                out["chapter_number"] = blocks[start]["chapter_number"]
                out["chapter_title"] = blocks[start]["chapter_title"]
                out["page_number"] = blocks[start]["page_number"]

    return out


# ─── TOOLS ────────────────────────────────────────────────────────────────────

def build_web_search_tool(max_uses: int = 3, cached: bool = True) -> dict:
    """
    Anthropic-managed web search tool. Citations are automatic.

    `cached=True` places a cache_control breakpoint on this tool definition
    so the (static) tools array is reused across requests when long enough.
    """
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
      "citation"          → enriched citation dict (school doc OR web_search_result)
      "web_search_query"  → str (the query Claude searched for)
      "web_search_result" → list of {url, title, page_age} dicts
      "tool_use"          → dict {name, id} — non-search tool invocation
      "done"              → {message, citations, web_searches, sources, context_found, usage}
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
        # 1. RAG search → curriculum documents with native citations
        search_results = await search_knowledge_base(
            user_message,
            subject=subject,
            class_level=class_level,
            document_type=document_type,
            language=language,
            limit=8,
        )
        documents, doc_metadata = build_citation_documents(search_results)

        # 2. Past-conversation memory (text-only — not citable)
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
            has_kb_context=bool(documents),
            memory_context=memory_context,
        )

        # 3. Build messages — documents go inside the user content block
        history_msgs = [
            {"role": m["role"], "content": m["content"]}
            for m in conversation_history[-10:]
        ]

        user_content: list[dict] = list(documents)
        user_content.append({"type": "text", "text": user_message})

        messages = history_msgs + [{"role": "user", "content": user_content}]

        # 4. Tools — web search by default
        tools: list[dict] = []
        if enable_web_search:
            tools.append(build_web_search_tool(max_uses=3))

        # 5. Stream
        client = get_async_client()
        full_text_parts: list[str] = []
        all_citations: list[dict] = []
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

                # Block start — detect what kind of block we're entering
                if etype == "content_block_start":
                    block = event.content_block
                    btype = getattr(block, "type", None)
                    if btype == "server_tool_use" and getattr(block, "name", "") == "web_search":
                        current_search_id = block.id
                        current_search_query = ""

                # Delta events
                elif etype == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", None)

                    if dtype == "text_delta":
                        text = delta.text
                        full_text_parts.append(text)
                        yield ("text", text)

                    elif dtype == "citations_delta":
                        # Citation arrived for the current text block
                        raw = delta.citation
                        cit_dict = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
                        enriched = enrich_citation(cit_dict, doc_metadata)
                        all_citations.append(enriched)
                        yield ("citation", enriched)

                    elif dtype == "input_json_delta":
                        # Tool input being streamed (web_search query, etc.)
                        if current_search_id:
                            current_search_query += delta.partial_json

                # Block stop — finalize tool blocks
                elif etype == "content_block_stop":
                    # If a search query just finished streaming, parse + emit it
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

                # The SDK also exposes raw content blocks — pull web_search_tool_result
                # off the accumulated message after stream ends (handled below).

            # Stream complete — fetch the final accumulated message
            final = await stream.get_final_message()

            if final.usage:
                usage = final.usage.model_dump() if hasattr(final.usage, "model_dump") else dict(final.usage)

            # Walk the final content for web_search_tool_result blocks (non-streaming meta)
            for block in final.content:
                btype = getattr(block, "type", None)
                if btype == "web_search_tool_result":
                    tool_use_id = getattr(block, "tool_use_id", None)
                    content = getattr(block, "content", None)
                    # content is either a list of results or an error block
                    if isinstance(content, list):
                        results = []
                        for r in content:
                            if getattr(r, "type", None) == "web_search_result":
                                results.append({
                                    "url":      getattr(r, "url", ""),
                                    "title":    getattr(r, "title", ""),
                                    "page_age": getattr(r, "page_age", None),
                                })
                        # Attach to matching search entry
                        for ws in web_searches:
                            if ws["id"] == tool_use_id:
                                ws["urls"] = results
                                break
                        yield ("web_search_result", results)

        # 6. Build sources summary for storage / UI
        kb_sources = [
            {
                "title":         meta["document_title"],
                "subject":       meta["subject"],
                "class_level":   meta["class_level"],
                "document_type": meta["document_type"],
            }
            for meta in doc_metadata
        ]

        full_message = "".join(full_text_parts)

        yield ("done", {
            "message":       full_message,
            "citations":     all_citations,
            "web_searches":  web_searches,
            "sources":       kb_sources,
            "context_found": bool(documents),
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
    """One-shot chat. Returns full message, citations, sources."""
    full_message = ""
    citations: list[dict] = []
    web_searches: list[dict] = []
    sources: list[dict] = []
    context_found = False

    async for etype, data in stream_chat_with_rag(user_message, db, **options):
        if etype == "done":
            full_message  = data["message"]
            citations     = data["citations"]
            web_searches  = data["web_searches"]
            sources       = data["sources"]
            context_found = data["context_found"]
        elif etype == "error":
            raise RuntimeError(data["message"])

    return {
        "message":       full_message,
        "citations":     citations,
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

    # Pull relevant curriculum content
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

    documents, doc_metadata = build_citation_documents(search_results)
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

Use the provided curriculum documents as the SOLE source of content. Then call the `submit_question_paper` tool exactly once with the complete paper."""

    user_content: list[dict] = list(documents)
    user_content.append({"type": "text", "text": instructions})

    # Static system prompt — cacheable so repeated paper generations reuse it.
    paper_system = [{
        "type": "text",
        "text": (
            f"You are an expert examination-paper creator for {school}. "
            "Build curriculum-aligned papers strictly from the provided documents. "
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
        messages=[{"role": "user", "content": user_content}],
        tools=[paper_tool],
        tool_choice={"type": "tool", "name": "submit_question_paper"},
    )

    # Extract the structured tool input
    paper_data: dict[str, Any] | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_question_paper":
            paper_data = block.input
            break

    if not paper_data:
        raise ValueError("Claude did not return a structured question paper.")

    # Flatten for storage
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
        "sources":    [m["document_title"] for m in doc_metadata],
    }


# ─── GENERATE ASSIGNMENT CONTENT ─────────────────────────────────────────────

async def generate_assignment_content(params: dict, db: AsyncSession) -> dict:
    """Creates assignment text and returns it along with citation metadata."""
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

    documents, doc_metadata = build_citation_documents(search_results)

    prompt = f"""Create a {assignment_type} assignment for {class_level} students on the topic: "{topic}".

Produce, using ONLY the provided curriculum documents:
1. A clear assignment title
2. 3-5 learning objectives
3. Detailed instructions for the student
4. {'5 research questions' if assignment_type == 'research' else '5 specific tasks/questions'}
5. An evaluation rubric

Keep it strictly aligned with the supplied content."""

    user_content: list[dict] = list(documents)
    user_content.append({"type": "text", "text": prompt})

    assignment_system = [{
        "type": "text",
        "text": (
            f"You are an educational content creator for {school}. "
            "Build assignments strictly from the provided documents."
        ),
        "cache_control": {"type": "ephemeral"},
    }]

    response = await get_async_client().messages.create(
        model=get_model(),
        max_tokens=2048,
        system=assignment_system,
        messages=[{"role": "user", "content": user_content}],
    )

    text = ""
    citations: list[dict] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text
            for c in (getattr(block, "citations", None) or []):
                cdict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
                citations.append(enrich_citation(cdict, doc_metadata))

    return {
        "content":   text,
        "citations": citations,
        "sources":   [m["document_title"] for m in doc_metadata],
    }
