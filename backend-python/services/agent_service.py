"""
LangChain agent service — the production chat engine.

Built on LangChain v1 `create_agent` (a LangGraph harness) so the model runs a
real agentic loop: it decides *when* to query the curriculum knowledge base and
can refine its search across multiple steps, instead of always pre-retrieving.

Tools
  • search_curriculum  — client-side tool wrapping the hybrid Milvus + BM25
                          retriever (classifier + page routing live inside it).
  • web_search          — Anthropic server-side web search (executed by Claude).

Design goals (parity with the previous native Anthropic implementation):
  • Real-time token streaming mapped to the existing SSE event contract
        ("text", "web_search_query", "web_search_result", "tool_use", "done", "error")
  • Prompt caching on the static system prompt + tool definitions
  • Persistent user memory + RAG knowledge-base context
  • Multi-language (English / Urdu) education-aligned system prompt

The four structured-output generators (question papers, important questions,
practice tests, grading) remain native single-shot forced-tool calls in
services/ai_service.py — an agent loop adds nothing there.

References:
  https://docs.langchain.com/oss/python/langchain/agents
  https://docs.langchain.com/oss/python/langchain/streaming
  https://docs.langchain.com/oss/python/integrations/chat/anthropic
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.messages import AIMessage, AIMessageChunk, SystemMessage
from langchain_anthropic import ChatAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from services.ai_service import build_kb_sources, _sanitize_history
from services.document_service import search_knowledge_base, build_context
from services.memory_service import search_user_memory, build_memory_context


logger = logging.getLogger("agent")


# ─── MODEL (singleton) ────────────────────────────────────────────────────────

# Extended thinking: Claude reasons before answering and (with interleaved
# thinking) between tool calls. The reasoning tokens are streamed to the client
# as "thinking" SSE events and shown in a collapsible panel.
#   • "adaptive" lets Claude size its own thinking budget per request — Anthropic
#     recommends it over the deprecated fixed-budget "enabled" mode.
#   • temperature must stay at the default (1.0) while thinking is on.
MAX_OUTPUT_TOKENS = 8192
# Interleaved thinking lets Claude think *between* tool calls (e.g. reason about
# curriculum search results before answering) — ideal for an agentic loop.
_INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"

_chat_model: ChatAnthropic | None = None


def get_chat_model() -> ChatAnthropic:
    """Lazily build a singleton streaming ChatAnthropic bound to the configured
    Claude model, with extended (adaptive, interleaved) thinking enabled.
    Caching / web-search / tools are attached per request by the agent harness."""
    global _chat_model
    if _chat_model is None:
        from config.settings import ANTHROPIC_API_KEY, AI_MODEL
        _chat_model = ChatAnthropic(
            model=AI_MODEL,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=MAX_OUTPUT_TOKENS,
            streaming=True,
            thinking={"type": "adaptive"},
            default_headers={"anthropic-beta": _INTERLEAVED_THINKING_BETA},
        )
    return _chat_model


def get_school() -> str:
    from config.settings import SCHOOL_NAME
    return SCHOOL_NAME


# ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────

def _static_rules(role: str) -> str:
    """Static role + school + tool-usage rules. Identical for a given role, so
    it is the natural prompt-cache prefix."""
    school = get_school()
    audience = "students" if role == "student" else "teachers"

    text = f"""You are an educational AI assistant for {school}. Your role is to help {audience} with academic content.

PRIMARY KNOWLEDGE SOURCE — School Knowledge Base
The school's curriculum (textbooks, notes, past exam papers, worksheets) is available through the `search_curriculum` tool. That curriculum is the authoritative source for school content.

TOOLS:
- `search_curriculum`: Search the school knowledge base. ALWAYS call this FIRST for any question about a school subject, topic, chapter, page, exercise, definition, formula, or past-paper content. You may call it more than once with refined queries if the first results are insufficient. Pass a focused natural-language query.
- `web_search`: Use ONLY for current events, real-world examples, or supplementary background that is NOT a school-curriculum topic — or when `search_curriculum` lacks enough information AND the question is general knowledge. Never use `web_search` to override or contradict curriculum content.

CRITICAL RULES:
1. Answer school-curriculum questions PRIMARILY from `search_curriculum` results. You may refer to a chapter or page naturally in prose (e.g., "as covered in Chapter 5"), but do NOT include bracketed citation markers, footnote numbers, or [Source] tags in your answer.
2. When the user asks about a specific page, chapter, exercise, or question number (e.g. "what is on page 45", "explain page 45", "summarise Chapter 3"), call `search_curriculum` with that reference; the returned content IS the content from that location. Answer directly from it and mention the page or chapter naturally (e.g., "Page 45 covers..."). Do NOT claim the information is unavailable when matching content is returned.
3. Only if `search_curriculum` returns NO_RESULTS (or clearly irrelevant content) AND a web search also fails for a curriculum topic, respond: "I cannot find this specific information in the available school materials. Please consult your {'teacher or ' if role == 'student' else ''}the relevant textbook."
4. Be educational, clear, and supportive. Adapt depth to the audience.
5. Respond in the same language as the question (English or Urdu). Mathematical and scientific notation may stay in English.
6. For mathematics, show step-by-step solutions.
7. Stay aligned with the curriculum for grade-appropriate explanations.
8. For casual messages (greetings, thanks) you do not need to call any tool — just respond naturally."""

    if role == "student":
        text += "\n\nSTUDENT ASSISTANCE:\n- Explain concepts clearly with examples from the curriculum\n- Break complex topics into digestible parts\n- Provide structured notes and summaries\n- Help prepare assignment answers\n- Create practice questions"
    else:
        text += "\n\nTEACHER ASSISTANCE:\n- Help build lesson plans aligned with the curriculum\n- Generate quiz questions and assessments\n- Produce detailed answer keys\n- Suggest teaching strategies\n- Vary exam difficulty levels"

    return text


def _build_system_message(
    role: str,
    subject: str | None,
    memory_context: str,
) -> SystemMessage:
    """System message as Anthropic content blocks:
      [0] static role/rules text  ← cache_control: ephemeral (cache breakpoint)
      [1] (optional) dynamic per-query notes + memory  ← NOT cached
    """
    blocks: list[dict] = [
        {
            "type": "text",
            "text": _static_rules(role),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    dynamic_parts: list[str] = []
    if subject:
        dynamic_parts.append(f"Current subject context: {subject}.")
    if memory_context:
        dynamic_parts.append(memory_context)
    if dynamic_parts:
        blocks.append({"type": "text", "text": "\n\n".join(dynamic_parts)})

    return SystemMessage(content=blocks)


# ─── TOOLS ────────────────────────────────────────────────────────────────────

def _build_curriculum_tool(collector: list[dict], opts: dict[str, Any]):
    """Build the per-request `search_curriculum` tool.

    `collector` accumulates the raw chunk hits returned during this turn so the
    caller can surface deduplicated source documents in the final "done" event.
    `opts` carries the locked filters (subject/class/type/language) for the turn.
    """

    @tool("search_curriculum", extras={"cache_control": {"type": "ephemeral"}})
    async def search_curriculum(query: str) -> str:
        """Search the school's curriculum knowledge base (textbooks, notes, past
        exam papers, worksheets) for content relevant to the question. Use this
        for ANY question about a school subject, chapter, topic, page, exercise,
        definition, formula, or past-paper content. Pass a focused query."""
        logger.info("[TOOL] search_curriculum(query=%r, filters=%s)", query, opts)
        results = await search_knowledge_base(
            query,
            subject=opts.get("subject"),
            class_level=opts.get("class_level"),
            document_type=opts.get("document_type"),
            language=opts.get("language"),
            limit=8,
        )
        logger.info("[TOOL] search_curriculum → %d hits", len(results or []))
        if not results:
            return (
                "NO_RESULTS: The knowledge base returned no curriculum content for "
                "this query. Do not fabricate curriculum facts."
            )
        collector.extend(results)
        return build_context(results) or "NO_RESULTS"

    return search_curriculum


def _web_search_tool(max_uses: int = 3) -> dict:
    """Anthropic server-side web search tool definition (executed by Claude)."""
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max_uses,
        "cache_control": {"type": "ephemeral"},
    }


# ─── MESSAGE SCANNING (web search + usage extraction) ─────────────────────────

def _extract_thinking(token: AIMessageChunk) -> str:
    """Pull extended-thinking (reasoning) delta text out of a streamed chunk.

    `token.text` returns only `text`-type blocks, so reasoning never leaks into
    the answer — we collect it separately here from `thinking`/`reasoning`
    content blocks and stream it as its own SSE channel.
    """
    content = getattr(token, "content", None)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in ("thinking", "reasoning"):
            parts.append(block.get("thinking") or block.get("reasoning") or "")
    return "".join(parts)


def _scan_assistant_message(
    message: AIMessage,
    web_searches: list[dict],
    usage_holder: dict[str, Any],
) -> list[tuple[str, Any]]:
    """Inspect a completed assistant message for Anthropic server-side web-search
    blocks and usage. Returns SSE events to emit (query/result), in order.

    Server-side web search runs within a single model turn, so the assistant
    message content holds the `server_tool_use` (query) block followed by the
    `web_search_tool_result` (results) block. Extracting from the completed
    message is far more robust than parsing partial streaming JSON.
    """
    events: list[tuple[str, Any]] = []

    content = message.content
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "server_tool_use" and block.get("name") == "web_search":
                query = (block.get("input") or {}).get("query")
                if query:
                    web_searches.append({"query": query, "urls": []})
                    events.append(("web_search_query", query))

            elif btype == "web_search_tool_result":
                raw = block.get("content")
                results: list[dict] = []
                if isinstance(raw, list):
                    for r in raw:
                        if isinstance(r, dict) and r.get("type") == "web_search_result":
                            results.append({
                                "url":      r.get("url", ""),
                                "title":   r.get("title", ""),
                                "page_age": r.get("page_age"),
                            })
                # Attach to the most recent pending search
                for ws in reversed(web_searches):
                    if not ws["urls"]:
                        ws["urls"] = results
                        break
                events.append(("web_search_result", results))

    usage = getattr(message, "usage_metadata", None)
    if usage:
        usage_holder.clear()
        usage_holder.update(dict(usage))

    return events


# ─── STREAMING CHAT (LangChain agent) ─────────────────────────────────────────

async def stream_chat_with_agent(
    user_message: str,
    db: AsyncSession,
    **options: Any,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Async generator yielding (event_type, data) tuples for SSE — identical
    contract to the previous native implementation so routes/chat.py and the
    frontend are unchanged.

    Event types:
      "thinking"          → str chunk of Claude's extended-thinking reasoning
      "text"              → {"text": str, "seg": int} chunk to append
      "intermediate"      → {"seg": int} — that segment was a tool-calling step;
                            its text is reasoning, not the final answer
      "web_search_query"  → str (the query Claude searched for)
      "web_search_result" → list of {url, title, page_age} dicts
      "tool_use"          → dict {name} — non-search tool invocation
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

    logger.info(
        "[AGENT] start | role=%s subject=%s class=%s web_search=%s msg=%r",
        user_role, subject, class_level, enable_web_search, user_message[:120],
    )

    try:
        # 1. Past-conversation memory → injected into the system prompt
        memory_context = ""
        if user_id:
            memories = await search_user_memory(
                user_id, user_message, db,
                current_session_id=session_id,
                subject=subject,
                limit=5,
            )
            memory_context = build_memory_context(memories)

        system_message = _build_system_message(user_role, subject, memory_context)

        # 2. Tools — KB retrieval (client-side) + web search (server-side)
        kb_hits: list[dict] = []
        opts = {
            "subject": subject,
            "class_level": class_level,
            "document_type": document_type,
            "language": language,
        }
        tools: list[Any] = [_build_curriculum_tool(kb_hits, opts)]
        if enable_web_search:
            tools.append(_web_search_tool(max_uses=3))

        agent = create_agent(
            model=get_chat_model(),
            tools=tools,
            system_prompt=system_message,
        )
        logger.info(
            "[AGENT] built | tools=%s memory_chars=%d",
            [getattr(t, "name", t.get("name") if isinstance(t, dict) else "?") for t in tools],
            len(memory_context),
        )

        # 3. Messages — sanitized history (strict alternation) + new user turn
        history_msgs = _sanitize_history(conversation_history[-12:])
        if len(history_msgs) > 10:
            history_msgs = history_msgs[-10:]
            while history_msgs and history_msgs[0]["role"] != "user":
                history_msgs.pop(0)
        agent_input = {"messages": history_msgs + [{"role": "user", "content": user_message}]}
        logger.info("[AGENT] history_turns=%d → streaming…", len(history_msgs))

        # 4. Stream tokens live ("messages") + completed messages ("updates").
        #
        # An agent run produces several assistant messages: intermediate ones
        # that call tools (and may "narrate" in text, e.g. "let me refine my
        # search") and one FINAL message that is the real answer. We tag each
        # assistant message with a segment id and, once "updates" reveals a
        # segment made tool calls, mark it intermediate so the frontend moves its
        # text from the answer into the thinking panel. Only non-intermediate
        # segment text becomes the saved answer.
        web_searches: list[dict] = []
        usage: dict[str, Any] = {}
        seen_message_ids: set[str] = set()
        seg_of_msg: dict[Any, int] = {}
        seg_text: dict[int, list[str]] = {}
        intermediate_segs: set[int] = set()
        next_seg = 0
        think_chars = 0
        text_chars = 0

        def _seg_for(mid: Any) -> int:
            nonlocal next_seg
            if mid not in seg_of_msg:
                seg_of_msg[mid] = next_seg
                seg_text[next_seg] = []
                next_seg += 1
            return seg_of_msg[mid]

        async for mode, chunk in agent.astream(
            agent_input,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                token = chunk[0] if isinstance(chunk, tuple) else chunk
                if isinstance(token, AIMessageChunk):
                    seg = _seg_for(getattr(token, "id", None) or "?")
                    thinking = _extract_thinking(token)
                    if thinking:
                        if think_chars == 0:
                            logger.info("[AGENT] thinking… (streaming reasoning)")
                        think_chars += len(thinking)
                        yield ("thinking", thinking)
                    text = token.text or ""
                    if text:
                        if text_chars == 0:
                            logger.info("[AGENT] answer started (think_chars=%d)", think_chars)
                        text_chars += len(text)
                        seg_text.setdefault(seg, []).append(text)
                        yield ("text", {"text": text, "seg": seg})

            elif mode == "updates":
                if not isinstance(chunk, dict):
                    continue
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    for msg in update.get("messages", []) or []:
                        if isinstance(msg, AIMessage):
                            mid = getattr(msg, "id", None) or id(msg)
                            if mid in seen_message_ids:
                                continue
                            seen_message_ids.add(mid)
                            tool_calls = getattr(msg, "tool_calls", None) or []
                            # A message that calls tools is an intermediate step;
                            # its narration text belongs in the thinking panel.
                            if tool_calls:
                                seg = _seg_for(mid)
                                intermediate_segs.add(seg)
                                yield ("intermediate", {"seg": seg})
                            for tc in tool_calls:
                                logger.info("[AGENT] tool_call → %s", tc.get("name"))
                                yield ("tool_use", {"name": tc.get("name")})
                            for evt in _scan_assistant_message(msg, web_searches, usage):
                                if evt[0] == "web_search_query":
                                    logger.info("[AGENT] web_search → %r", evt[1])
                                yield evt

        # Final answer = text from segments that did NOT call tools.
        full_message = "".join(
            "".join(seg_text[s])
            for s in sorted(seg_text)
            if s not in intermediate_segs
        )
        kb_sources = build_kb_sources(kb_hits)
        logger.info(
            "[AGENT] done | think=%d text=%d answer=%d kb_hits=%d web_searches=%d usage=%s",
            think_chars, text_chars, len(full_message), len(kb_hits), len(web_searches), usage or {},
        )

        yield ("done", {
            "message":       full_message,
            "web_searches":  web_searches,
            "sources":       kb_sources,
            "context_found": bool(kb_hits),
            "usage":         usage,
        })

    except Exception as exc:
        import traceback
        traceback.print_exc()
        logger.error("[AGENT] error: %s: %s", type(exc).__name__, exc)
        yield ("error", {"message": str(exc)})


# ─── NON-STREAMING CHAT (internal callers) ───────────────────────────────────

async def chat_with_agent(
    user_message: str,
    db: AsyncSession,
    **options: Any,
) -> dict:
    """One-shot chat. Returns full message + sources."""
    full_message = ""
    web_searches: list[dict] = []
    sources: list[dict] = []
    context_found = False

    async for etype, data in stream_chat_with_agent(user_message, db, **options):
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
