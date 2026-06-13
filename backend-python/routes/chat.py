import json
import logging
import re
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.models import User, ChatHistory
from services.agent_service import stream_chat_with_agent

logger = logging.getLogger("agent")


# Auto-detect subject from message content
SUBJECT_KEYWORDS = {
    "Mathematics": ["math", "algebra", "geometry", "equation", "fraction", "calculus", "arithmetic", "trigonometry", "number", "formula"],
    "Science": ["science", "experiment", "hypothesis", "atom", "molecule", "energy", "force"],
    "Physics": ["physics", "velocity", "acceleration", "gravity", "newton", "momentum", "wave", "optics", "thermodynamics"],
    "Chemistry": ["chemistry", "element", "compound", "reaction", "acid", "base", "periodic table", "bond", "solution"],
    "Biology": ["biology", "cell", "organism", "dna", "gene", "evolution", "photosynthesis", "ecosystem", "species"],
    "English": ["english", "grammar", "essay", "poem", "poetry", "literature", "novel", "comprehension", "vocabulary", "tense"],
    "Urdu": ["urdu", "ghazal", "nazm", "insha", "mukaalma", "urdu grammar"],
    "Computer Science": ["computer", "programming", "algorithm", "software", "hardware", "binary", "database", "network", "coding", "python", "html"],
    "Islamiat": ["islamiat", "islam", "quran", "hadith", "sunnah", "prophet", "surah", "namaz", "roza", "zakat"],
    "Social Studies": ["social studies", "society", "culture", "government", "democracy", "rights"],
    "History": ["history", "war", "empire", "civilization", "mughal", "independence", "ancient", "medieval"],
    "Geography": ["geography", "continent", "climate", "river", "mountain", "ocean", "earthquake", "population", "map"],
    "Economics": ["economics", "economy", "gdp", "inflation", "supply", "demand", "trade", "market"],
    "General Science": ["general science", "matter", "energy", "living things"],
}

CLASS_PATTERNS = [
    (r"\bgrade\s*(\d{1,2})\b", lambda m: f"Class {m.group(1)}"),
    (r"\bclass\s*(\d{1,2})\b", lambda m: f"Class {m.group(1)}"),
    (r"\b(\d{1,2})(?:th|st|nd|rd)\s*(?:grade|class)\b", lambda m: f"Class {m.group(1)}"),
]


def auto_detect_subject(message: str) -> str | None:
    """Detect subject from message keywords."""
    msg_lower = message.lower()
    best_subject = None
    best_count = 0
    for subject, keywords in SUBJECT_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in msg_lower)
        if count > best_count:
            best_count = count
            best_subject = subject
    return best_subject if best_count > 0 else None


def auto_detect_class(message: str) -> str | None:
    """Detect class/grade level from message."""
    msg_lower = message.lower()
    for pattern, formatter in CLASS_PATTERNS:
        m = re.search(pattern, msg_lower)
        if m:
            return formatter(m)
    return None

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    subject: str | None = None
    session_id: str | None = None


@router.post("/message")
async def send_message(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    session_id = body.session_id or str(uuid.uuid4())
    logger.info(
        "[CHAT] POST /chat/message | user=%s role=%s session=%s msg=%r",
        getattr(user, "id", "?"), getattr(user, "role", "?"), session_id, body.message[:120],
    )

    # Fetch conversation history
    result = await db.execute(
        select(ChatHistory)
        .where(ChatHistory.user_id == user.id, ChatHistory.session_id == session_id)
        .order_by(ChatHistory.created_at.asc())
        .limit(20)
    )
    history_rows = result.scalars().all()
    conversation_history = [{"role": h.role, "content": h.content} for h in history_rows]

    # Auto-detect subject and class from message if not explicitly provided
    detected_subject = body.subject or auto_detect_subject(body.message)
    detected_class = auto_detect_class(body.message) or user.class_name

    # Save user message
    db.add(ChatHistory(
        user_id=user.id, session_id=session_id, role="user",
        content=body.message.strip(), subject_context=detected_subject,
    ))
    await db.commit()

    async def event_stream():
        full_response = ""
        sources = []
        web_searches = []
        assistant_saved = False

        async def _save_assistant(content: str, kb_sources, searches):
            """Persist the assistant turn. Always called exactly once per stream
            so a failed/empty reply never leaves a dangling user message that
            would bleed into the next query."""
            nonlocal assistant_saved
            if assistant_saved:
                return
            assistant_saved = True
            db.add(ChatHistory(
                user_id=user.id, session_id=session_id, role="assistant",
                content=content or "I wasn't able to generate a response. Please try asking again.",
                subject_context=detected_subject,
                sources_used={
                    "kb_sources":   kb_sources or [],
                    "web_searches": searches or [],
                },
            ))
            await db.commit()

        try:
            # Send session_id immediately so the client knows the session is live
            yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

            async for event_type, data in stream_chat_with_agent(
                body.message.strip(), db,
                user_role=user.role,
                subject=detected_subject,
                class_level=detected_class,
                conversation_history=conversation_history,
                user_id=user.id,
                session_id=session_id,
            ):
                if event_type == "text":
                    # data = {"text": str, "seg": int}. Accumulate for the
                    # disconnect/error fallback; the clean final answer comes
                    # from the "done" event.
                    full_response += data.get("text", "")
                    yield f"data: {json.dumps({'type': 'text', 'text': data.get('text', ''), 'seg': data.get('seg', 0)})}\n\n"

                elif event_type == "thinking":
                    yield f"data: {json.dumps({'type': 'thinking', 'text': data})}\n\n"

                elif event_type == "intermediate":
                    # The given segment made tool calls — its text is reasoning,
                    # not the answer. Tell the client to reclassify it.
                    yield f"data: {json.dumps({'type': 'intermediate', 'seg': data.get('seg', 0)})}\n\n"

                elif event_type == "web_search_query":
                    yield f"data: {json.dumps({'type': 'web_search_query', 'query': data})}\n\n"

                elif event_type == "web_search_result":
                    web_searches.append(data)
                    yield f"data: {json.dumps({'type': 'web_search_result', 'results': data})}\n\n"

                elif event_type == "tool_use":
                    yield f"data: {json.dumps({'type': 'tool_use', 'tool': data})}\n\n"

                elif event_type == "done":
                    full_response = data["message"]
                    sources = data["sources"]

                    # Persist assistant message + structured sources for history
                    await _save_assistant(full_response, sources, data.get("web_searches", []))

                    yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'sources': sources, 'web_searches': data.get('web_searches', []), 'context_found': data.get('context_found', False), 'usage': data.get('usage', {})})}\n\n"

                elif event_type == "error":
                    # Persist whatever text streamed so the user turn is never left
                    # dangling, then surface the error to the client.
                    await _save_assistant(full_response, sources, web_searches)
                    yield f"data: {json.dumps({'type': 'error', 'message': data.get('message', 'Unknown error')})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                await _save_assistant(full_response, sources, web_searches)
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Safety net: guarantee the assistant turn is recorded even if the
            # client disconnected before the stream produced a terminal event.
            if not assistant_saved and full_response.strip():
                try:
                    await _save_assistant(full_response, sources, web_searches)
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def get_chat_history(
    session_id: str = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ChatHistory).where(ChatHistory.user_id == user.id)
    if session_id:
        query = query.where(ChatHistory.session_id == session_id)
    query = query.order_by(ChatHistory.created_at.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()
    return [h.to_dict() for h in reversed(rows)]


@router.get("/sessions")
async def get_chat_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sql = text("""
        SELECT
            session_id,
            MAX(subject_context) as subject,
            COUNT(*) as message_count,
            MIN(created_at) as started_at,
            MAX(created_at) as last_message_at,
            (SELECT content FROM chat_history ch2
             WHERE ch2.session_id = ch.session_id AND ch2.user_id = :user_id AND ch2.role = 'user'
             ORDER BY ch2.created_at ASC LIMIT 1) as first_message
        FROM chat_history ch
        WHERE user_id = :user_id
        GROUP BY session_id
        ORDER BY last_message_at DESC
        LIMIT 20
    """)
    result = await db.execute(sql, {"user_id": user.id})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        ChatHistory.__table__.delete().where(
            ChatHistory.user_id == user.id, ChatHistory.session_id == session_id
        )
    )
    await db.commit()
    return {"message": "Session deleted"}


# ─── MEMORY ENDPOINTS ────────────────────────────────────────────────────────

from services.memory_service import get_user_topics, clear_user_memory


@router.get("/memory/topics")
async def get_memory_topics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a summary of all topics/subjects the user has discussed."""
    topics = await get_user_topics(user.id, db)
    return topics


@router.delete("/memory")
async def delete_memory(
    subject: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete all user chat memory. Optionally filter by subject."""
    deleted = await clear_user_memory(user.id, db, subject=subject)
    return {"message": f"Deleted {deleted} messages", "deleted_count": deleted}


@router.get("/memory/search")
async def search_memory(
    q: str,
    subject: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search user's past conversations for a specific topic."""
    from services.memory_service import search_user_memory
    results = await search_user_memory(user.id, q, db, subject=subject, limit=10)
    return results
