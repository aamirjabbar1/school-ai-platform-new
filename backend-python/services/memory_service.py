"""
Persistent Memory Service
Searches a user's past conversations across all sessions to find relevant context.
Uses keyword matching on SQLite (no vector DB required).
"""

import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# Common English + Urdu stop words to filter out
STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "this", "that", "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "a", "an", "the", "and", "but",
    "or", "nor", "not", "so", "if", "as", "at", "by", "for", "in", "of",
    "on", "to", "up", "with", "from", "into", "about", "what", "which",
    "who", "whom", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "some", "any", "no", "than", "too",
    "very", "just", "also", "tell", "explain", "make", "give", "please",
    "help", "want", "need", "know",
    # Urdu common words
    "ka", "ki", "ke", "hai", "hain", "tha", "thi", "ko", "se", "mein",
    "par", "ne", "ho", "ya", "aur", "kya", "ye", "wo", "tu", "main",
    "karo", "kijiye", "batao", "bataiye",
}


def extract_keywords(text_input: str) -> list[str]:
    """Extract meaningful keywords from a query."""
    words = re.findall(r"[a-zA-Z0-9]+", text_input.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    return keywords[:12]  # cap at 12 keywords


async def search_user_memory(
    user_id: str,
    query: str,
    db: AsyncSession,
    current_session_id: str = None,
    subject: str = None,
    limit: int = 5,
) -> list[dict]:
    """
    Search a user's past conversations for context relevant to the current query.
    Returns Q&A pairs from previous sessions ranked by keyword relevance.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return []

    # Build keyword match scoring for user messages
    kw_conditions = []
    kw_params = {}
    relevance_parts = []

    for i, kw in enumerate(keywords):
        param_name = f"mkw{i}"
        kw_conditions.append(f"user_msg.content LIKE :{param_name}")
        # Also match in assistant response for topic continuity
        relevance_parts.append(
            f"(CASE WHEN user_msg.content LIKE :{param_name} THEN 2 ELSE 0 END)"
            f" + (CASE WHEN asst_msg.content LIKE :{param_name} THEN 1 ELSE 0 END)"
        )
        kw_params[param_name] = f"%{kw}%"

    if not kw_conditions:
        return []

    where_kw = " OR ".join(kw_conditions)
    relevance_score = " + ".join(relevance_parts)

    # Exclude current session so we only pull past context
    session_filter = ""
    if current_session_id:
        session_filter = "AND user_msg.session_id != :current_sid"
        kw_params["current_sid"] = current_session_id

    subject_filter = ""
    if subject:
        subject_filter = "AND user_msg.subject_context = :subj"
        kw_params["subj"] = subject

    kw_params["uid"] = user_id
    kw_params["lim"] = limit

    sql = text(f"""
        SELECT
            user_msg.session_id,
            user_msg.content AS user_question,
            asst_msg.content AS assistant_answer,
            user_msg.subject_context AS subject,
            user_msg.created_at AS asked_at,
            ({relevance_score}) AS relevance
        FROM chat_history user_msg
        LEFT JOIN chat_history asst_msg
            ON asst_msg.session_id = user_msg.session_id
            AND asst_msg.user_id = user_msg.user_id
            AND asst_msg.role = 'assistant'
            AND asst_msg.created_at > user_msg.created_at
            AND asst_msg.id = (
                SELECT id FROM chat_history
                WHERE session_id = user_msg.session_id
                  AND user_id = user_msg.user_id
                  AND role = 'assistant'
                  AND created_at > user_msg.created_at
                ORDER BY created_at ASC
                LIMIT 1
            )
        WHERE user_msg.user_id = :uid
          AND user_msg.role = 'user'
          AND ({where_kw})
          {session_filter}
          {subject_filter}
        ORDER BY relevance DESC, user_msg.created_at DESC
        LIMIT :lim
    """)

    result = await db.execute(sql, kw_params)
    rows = result.mappings().all()

    memories = []
    for r in rows:
        if r["relevance"] and r["relevance"] > 0:
            memories.append({
                "session_id": r["session_id"],
                "user_question": r["user_question"],
                "assistant_answer": (r["assistant_answer"] or "")[:500],  # truncate long answers
                "subject": r["subject"],
                "asked_at": str(r["asked_at"]) if r["asked_at"] else None,
                "relevance": r["relevance"],
            })

    return memories


def build_memory_context(memories: list[dict]) -> str:
    """Format past conversation memories into a context string for the system prompt."""
    if not memories:
        return ""

    lines = []
    lines.append("PAST CONVERSATION HISTORY WITH THIS USER:")
    lines.append("(The user has discussed these topics before - use this to continue their learning journey)")
    lines.append("")

    for i, m in enumerate(memories, 1):
        subject_tag = f" [{m['subject']}]" if m.get("subject") else ""
        date_tag = ""
        if m.get("asked_at"):
            # Just show the date portion
            date_tag = f" (on {m['asked_at'][:10]})"

        lines.append(f"--- Previous Interaction {i}{subject_tag}{date_tag} ---")
        lines.append(f"Student asked: {m['user_question']}")
        if m.get("assistant_answer"):
            # Show a summary of the answer (first 400 chars)
            answer_preview = m["assistant_answer"]
            if len(answer_preview) > 400:
                answer_preview = answer_preview[:400] + "..."
            lines.append(f"You answered: {answer_preview}")
        lines.append("")

    lines.append("INSTRUCTIONS FOR USING PAST CONTEXT:")
    lines.append("- Recognize when the current question relates to a previous topic")
    lines.append("- Build upon previous explanations instead of repeating from scratch")
    lines.append("- If the user is revisiting a topic, acknowledge it naturally (e.g., 'Building on our previous discussion about...')")
    lines.append("- Progress the user's learning by going deeper or covering new aspects")
    lines.append("")

    return "\n".join(lines)


async def get_user_topics(
    user_id: str,
    db: AsyncSession,
    limit: int = 30,
) -> list[dict]:
    """Get a summary of topics the user has discussed, grouped by subject."""
    sql = text("""
        SELECT
            session_id,
            subject_context AS subject,
            MIN(created_at) AS started_at,
            MAX(created_at) AS last_at,
            COUNT(*) AS message_count,
            (SELECT content FROM chat_history ch2
             WHERE ch2.session_id = ch.session_id AND ch2.user_id = :uid AND ch2.role = 'user'
             ORDER BY ch2.created_at ASC LIMIT 1) AS first_question
        FROM chat_history ch
        WHERE user_id = :uid AND role = 'user'
        GROUP BY session_id
        ORDER BY last_at DESC
        LIMIT :lim
    """)
    result = await db.execute(sql, {"uid": user_id, "lim": limit})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def clear_user_memory(
    user_id: str,
    db: AsyncSession,
    subject: str = None,
) -> int:
    """Delete a user's chat history. Optionally filter by subject."""
    if subject:
        sql = text(
            "DELETE FROM chat_history WHERE user_id = :uid AND subject_context = :subj"
        )
        result = await db.execute(sql, {"uid": user_id, "subj": subject})
    else:
        sql = text("DELETE FROM chat_history WHERE user_id = :uid")
        result = await db.execute(sql, {"uid": user_id})
    await db.commit()
    return result.rowcount
