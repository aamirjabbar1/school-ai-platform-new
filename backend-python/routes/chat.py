import json
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
from services.ai_service import stream_chat_with_rag


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
    (r"\bgrade\s*(\d{1,2})\b", lambda m: f"Grade {m.group(1)}"),
    (r"\bclass\s*(\d{1,2})\b", lambda m: f"Grade {m.group(1)}"),
    (r"\b(\d{1,2})(?:th|st|nd|rd)\s*(?:grade|class)\b", lambda m: f"Grade {m.group(1)}"),
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
        citations = []
        web_searches = []
        try:
            # Send session_id immediately so the client knows the session is live
            yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

            async for event_type, data in stream_chat_with_rag(
                body.message.strip(), db,
                user_role=user.role,
                subject=detected_subject,
                class_level=detected_class,
                conversation_history=conversation_history,
                user_id=user.id,
                session_id=session_id,
            ):
                if event_type == "text":
                    full_response += data
                    yield f"data: {json.dumps({'type': 'text', 'text': data})}\n\n"

                elif event_type == "citation":
                    citations.append(data)
                    yield f"data: {json.dumps({'type': 'citation', 'citation': data})}\n\n"

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
                    db.add(ChatHistory(
                        user_id=user.id, session_id=session_id, role="assistant",
                        content=full_response, subject_context=detected_subject,
                        sources_used={
                            "kb_sources":   sources,
                            "citations":    data.get("citations", []),
                            "web_searches": data.get("web_searches", []),
                        },
                    ))
                    await db.commit()

                    yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'sources': sources, 'citations': data.get('citations', []), 'web_searches': data.get('web_searches', []), 'context_found': data.get('context_found', False), 'usage': data.get('usage', {})})}\n\n"

                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': data.get('message', 'Unknown error')})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

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
