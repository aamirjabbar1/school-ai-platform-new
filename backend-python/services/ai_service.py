import json
import re
import anthropic
from services.document_service import search_knowledge_base, build_context
from services.memory_service import search_user_memory, build_memory_context
from sqlalchemy.ext.asyncio import AsyncSession

_client = None


def get_client():
    global _client
    if _client is None:
        from config.settings import ANTHROPIC_API_KEY
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def get_model():
    from config.settings import AI_MODEL
    return AI_MODEL


def get_school():
    from config.settings import SCHOOL_NAME
    return SCHOOL_NAME


# ─── SYSTEM PROMPTS ───────────────────────────────────────────────────────────


def get_system_prompt(role: str, subject: str = None) -> str:
    school = get_school()
    base = f"""You are an educational AI assistant for {school}. Your role is to help {'students' if role == 'student' else 'teachers'} with academic content.

CRITICAL RULES - YOU MUST FOLLOW THESE STRICTLY:
1. You MUST ONLY answer questions based on the academic content provided in the CONTEXT SECTION below.
2. Do NOT use any general internet knowledge, your training data, or information outside the provided context.
3. If the answer is NOT found in the provided context, respond with:
   "I cannot find this specific information in the available school materials. Please consult your {'teacher or ' if role == 'student' else ''}the relevant textbook."
4. Always cite the source document when providing an answer (e.g., "According to [Book Title]...").
5. Be educational, clear, and supportive.
6. Support both English and Urdu languages - respond in the same language as the question.
7. For mathematics, show step-by-step solutions when possible.
8. All answers must be aligned with the school curriculum."""

    if role == "student":
        base += """
STUDENT ASSISTANCE GUIDELINES:
- Explain concepts clearly with examples from the provided material
- Help break down complex topics into simpler parts
- Provide structured notes and summaries based on the content
- Guide students in preparing answers for assignments
- Create practice questions based on provided material"""
    else:
        base += """
TEACHER ASSISTANCE GUIDELINES:
- Help create lesson plans based on the curriculum content
- Generate quiz questions and assessments from provided material
- Create detailed answer keys for questions
- Suggest teaching strategies for specific topics
- Help structure exam questions at different difficulty levels"""

    return base


# ─── CHAT WITH RAG ────────────────────────────────────────────────────────────


async def chat_with_rag(user_message: str, db: AsyncSession, **options) -> dict:
    user_role = options.get("user_role", "student")
    subject = options.get("subject")
    class_level = options.get("class_level")
    conversation_history = options.get("conversation_history", [])
    user_id = options.get("user_id")
    session_id = options.get("session_id")

    search_results = await search_knowledge_base(user_message, subject=subject, class_level=class_level, limit=6)
    context = build_context(search_results)

    # Search user's past conversations for relevant memory
    memory_context = ""
    if user_id:
        memories = await search_user_memory(
            user_id, user_message, db,
            current_session_id=session_id,
            subject=subject,
            limit=5,
        )
        memory_context = build_memory_context(memories)

    system_prompt = get_system_prompt(user_role, subject)

    separator = "━" * 40
    if context:
        system_with_context = f"""{system_prompt}

{separator}
CONTEXT FROM SCHOOL KNOWLEDGE BASE:
{separator}
{context}
{separator}
IMPORTANT: Base your answer ONLY on the context above. Do not use any other knowledge."""
    else:
        system_with_context = f"""{system_prompt}

NOTE: No relevant content was found in the school's knowledge base for this query. Inform the user that this topic is not covered in the available school materials."""

    # Inject memory context if available
    if memory_context:
        system_with_context = f"""{system_with_context}

{separator}
{memory_context}
{separator}"""

    messages = []
    if conversation_history:
        for msg in conversation_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    response = get_client().messages.create(
        model=get_model(),
        max_tokens=4096,
        system=system_with_context,
        messages=messages,
        stream=False,
    )

    assistant_message = ""
    for block in response.content:
        if block.type == "text":
            assistant_message = block.text
            break

    sources = [
        {"title": r["document_title"], "subject": r["subject"], "class_level": r["class_level"]}
        for r in search_results
    ]

    return {
        "message": assistant_message,
        "sources": sources,
        "context_found": len(search_results) > 0,
    }


# ─── STREAMING CHAT WITH RAG ─────────────────────────────────────────────────


async def stream_chat_with_rag(user_message: str, db: AsyncSession, **options):
    """Async generator that yields (chunk_type, data) tuples for SSE streaming."""
    user_role = options.get("user_role", "student")
    subject = options.get("subject")
    class_level = options.get("class_level")
    conversation_history = options.get("conversation_history", [])
    user_id = options.get("user_id")
    session_id = options.get("session_id")

    search_results = await search_knowledge_base(user_message, subject=subject, class_level=class_level, limit=6)
    context = build_context(search_results)

    # Search user's past conversations for relevant memory
    memory_context = ""
    if user_id:
        memories = await search_user_memory(
            user_id, user_message, db,
            current_session_id=session_id,
            subject=subject,
            limit=5,
        )
        memory_context = build_memory_context(memories)

    system_prompt = get_system_prompt(user_role, subject)

    separator = "━" * 40
    if context:
        system_with_context = f"""{system_prompt}

{separator}
CONTEXT FROM SCHOOL KNOWLEDGE BASE:
{separator}
{context}
{separator}
IMPORTANT: Base your answer ONLY on the context above."""
    else:
        system_with_context = f"""{system_prompt}

NOTE: No relevant content found in the knowledge base for this query."""

    # Inject memory context if available
    if memory_context:
        system_with_context = f"""{system_with_context}

{separator}
{memory_context}
{separator}"""

    messages = []
    if conversation_history:
        for msg in conversation_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    full_response = ""

    with get_client().messages.stream(
        model=get_model(),
        max_tokens=4096,
        system=system_with_context,
        messages=messages,
    ) as stream:
        for text_chunk in stream.text_stream:
            full_response += text_chunk
            yield ("chunk", text_chunk)

    sources = [
        {"title": r["document_title"], "subject": r["subject"], "class_level": r["class_level"]}
        for r in search_results
    ]

    yield ("done", {
        "message": full_response,
        "sources": sources,
        "context_found": len(search_results) > 0,
    })


# ─── GENERATE QUESTION PAPER ─────────────────────────────────────────────────


async def generate_question_paper(params: dict, db: AsyncSession) -> dict:
    subject = params["subject"]
    class_level = params["class_level"]
    paper_type = params["paper_type"]
    total_marks = params.get("total_marks", 100)
    duration_minutes = params.get("duration_minutes", 60)
    topics = params.get("topics", [])
    difficulty = params.get("difficulty_distribution", {"easy": 30, "medium": 50, "hard": 20})

    topic_query = " ".join(topics) if topics else subject
    search_results = await search_knowledge_base(topic_query, subject=subject, class_level=class_level, limit=15)
    context = build_context(search_results)

    if not context:
        raise ValueError("No content found in knowledge base for the specified subject and class level.")

    school = get_school()
    prompt = f"""Based on the following academic content, generate a complete {paper_type.replace('_', ' ')} examination paper.

REQUIREMENTS:
- Subject: {subject}
- Class: {class_level}
- Total Marks: {total_marks}
- Duration: {duration_minutes} minutes
- Difficulty: {difficulty.get('easy', 30)}% Easy, {difficulty.get('medium', 50)}% Medium, {difficulty.get('hard', 20)}% Hard
{f"- Focus Topics: {', '.join(topics)}" if topics else ""}

PAPER STRUCTURE (distribute marks appropriately):
1. Section A: Multiple Choice Questions (MCQs)
2. Section B: Short Answer Questions
3. Section C: Long Answer / Essay Questions

Generate the paper as a JSON object with this structure:
{{
  "title": "Paper title",
  "sections": [
    {{
      "name": "Section A: Multiple Choice Questions",
      "instructions": "Circle the correct answer",
      "questions": [
        {{
          "number": 1,
          "question": "Question text",
          "type": "mcq",
          "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
          "correct_answer": "B",
          "marks": 1,
          "difficulty": "easy"
        }}
      ]
    }}
  ]
}}

STRICTLY use only information from the provided academic content."""

    system_msg = f"""You are an expert examination paper creator for {school}. Create well-structured, curriculum-aligned examination papers based strictly on the provided academic content. Always respond with valid JSON.

ACADEMIC CONTENT:
{context}"""

    response = get_client().messages.create(
        model=get_model(),
        max_tokens=8192,
        system=system_msg,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = ""
    for block in response.content:
        if block.type == "text":
            response_text = block.text
            break

    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if not json_match:
        raise ValueError("Failed to generate valid question paper format")

    paper_data = json.loads(json_match.group(0))

    questions = []
    answer_key = []

    for section in paper_data.get("sections", []):
        for q in section.get("questions", []):
            questions.append({
                "number": q.get("number"),
                "section": section.get("name"),
                "question": q.get("question"),
                "type": q.get("type"),
                "options": q.get("options"),
                "marks": q.get("marks"),
                "difficulty": q.get("difficulty"),
            })
            answer_key.append({
                "number": q.get("number"),
                "correct_answer": q.get("correct_answer") or q.get("model_answer"),
                "marks": q.get("marks"),
            })

    return {
        "paper_data": paper_data,
        "questions": questions,
        "answer_key": answer_key,
        "sources": [r["document_title"] for r in search_results[:5]],
    }


# ─── GENERATE ASSIGNMENT CONTENT ─────────────────────────────────────────────


async def generate_assignment_content(params: dict, db: AsyncSession) -> str:
    topic = params["topic"]
    subject = params["subject"]
    class_level = params["class_level"]
    assignment_type = params.get("assignment_type", "homework")
    school = get_school()

    search_results = await search_knowledge_base(topic, subject=subject, class_level=class_level, limit=8)
    context = build_context(search_results)

    if not context:
        raise ValueError("No relevant content found in the knowledge base for this topic.")

    prompt = f"""Based on the provided academic content, create a {assignment_type} assignment for {class_level} students on the topic: "{topic}".

Create:
1. Clear assignment title
2. Learning objectives (3-5 points)
3. Detailed instructions
4. {'5 research questions to answer' if assignment_type == 'research' else '5 specific tasks/questions'}
5. Evaluation criteria (marking rubric)

Keep everything strictly aligned with the provided content."""

    response = get_client().messages.create(
        model=get_model(),
        max_tokens=2048,
        system=f"You are an educational content creator for {school}. Create assignments strictly based on the provided content.\n\nCONTENT:\n{context}",
        messages=[{"role": "user", "content": prompt}],
    )

    for block in response.content:
        if block.type == "text":
            return block.text
    return ""
