const Anthropic = require('@anthropic-ai/sdk');
const { searchKnowledgeBase, buildContext } = require('./documentService');

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const MODEL = process.env.AI_MODEL || 'claude-opus-4-6';
const SCHOOL_NAME = process.env.SCHOOL_NAME || 'Our School';

// ─── SYSTEM PROMPTS ───────────────────────────────────────────────────────────

const getSystemPrompt = (role, subject = null) => {
  const base = `You are an educational AI assistant for ${SCHOOL_NAME}. Your role is to help ${role === 'student' ? 'students' : 'teachers'} with academic content.

CRITICAL RULES - YOU MUST FOLLOW THESE STRICTLY:
1. You MUST ONLY answer questions based on the academic content provided in the CONTEXT SECTION below.
2. Do NOT use any general internet knowledge, your training data, or information outside the provided context.
3. If the answer is NOT found in the provided context, respond with:
   "I cannot find this specific information in the available school materials. Please consult your ${role === 'student' ? 'teacher or' : ''} the relevant textbook."
4. Always cite the source document when providing an answer (e.g., "According to [Book Title]...").
5. Be educational, clear, and supportive.
6. Support both English and Urdu languages - respond in the same language as the question.
7. For mathematics, show step-by-step solutions when possible.
8. All answers must be aligned with the school curriculum.`;

  const roleInstructions = role === 'student'
    ? `\nSTUDENT ASSISTANCE GUIDELINES:
- Explain concepts clearly with examples from the provided material
- Help break down complex topics into simpler parts
- Provide structured notes and summaries based on the content
- Guide students in preparing answers for assignments
- Create practice questions based on provided material`
    : `\nTEACHER ASSISTANCE GUIDELINES:
- Help create lesson plans based on the curriculum content
- Generate quiz questions and assessments from provided material
- Create detailed answer keys for questions
- Suggest teaching strategies for specific topics
- Help structure exam questions at different difficulty levels`;

  return base + roleInstructions;
};

// ─── CHAT WITH RAG ────────────────────────────────────────────────────────────

const chatWithRAG = async (userMessage, options = {}) => {
  const {
    userRole = 'student',
    subject = null,
    classLevel = null,
    conversationHistory = [],
    sessionId = null,
  } = options;

  // Search knowledge base for relevant content
  const searchResults = await searchKnowledgeBase(userMessage, {
    subject,
    classLevel,
    limit: 6,
  });

  const context = buildContext(searchResults);
  const systemPrompt = getSystemPrompt(userRole, subject);

  // Build the full system message with context
  const systemWithContext = context
    ? `${systemPrompt}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT FROM SCHOOL KNOWLEDGE BASE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMPORTANT: Base your answer ONLY on the context above. Do not use any other knowledge.`
    : `${systemPrompt}

NOTE: No relevant content was found in the school's knowledge base for this query. Inform the user that this topic is not covered in the available school materials.`;

  // Build conversation history for multi-turn chat
  const messages = [];
  if (conversationHistory.length > 0) {
    // Keep last 10 messages for context (5 exchanges)
    const recentHistory = conversationHistory.slice(-10);
    for (const msg of recentHistory) {
      messages.push({ role: msg.role, content: msg.content });
    }
  }
  messages.push({ role: 'user', content: userMessage });

  // Stream response from Claude
  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 4096,
    system: systemWithContext,
    messages,
    thinking: { type: 'adaptive' },
    stream: false,
  });

  const assistantMessage = response.content.find((b) => b.type === 'text')?.text || '';

  // Extract source references
  const sources = searchResults.map((r) => ({
    title: r.document_title,
    subject: r.subject,
    class_level: r.class_level,
  }));

  return {
    message: assistantMessage,
    sources,
    contextFound: searchResults.length > 0,
  };
};

// ─── STREAMING CHAT WITH RAG ──────────────────────────────────────────────────

const streamChatWithRAG = async (userMessage, options = {}, onChunk) => {
  const {
    userRole = 'student',
    subject = null,
    classLevel = null,
    conversationHistory = [],
  } = options;

  const searchResults = await searchKnowledgeBase(userMessage, {
    subject,
    classLevel,
    limit: 6,
  });

  const context = buildContext(searchResults);
  const systemPrompt = getSystemPrompt(userRole, subject);

  const systemWithContext = context
    ? `${systemPrompt}\n\n${'━'.repeat(40)}\nCONTEXT FROM SCHOOL KNOWLEDGE BASE:\n${'━'.repeat(40)}\n${context}\n${'━'.repeat(40)}\nIMPORTANT: Base your answer ONLY on the context above.`
    : `${systemPrompt}\n\nNOTE: No relevant content found in the knowledge base for this query.`;

  const messages = [];
  if (conversationHistory.length > 0) {
    const recentHistory = conversationHistory.slice(-10);
    for (const msg of recentHistory) {
      messages.push({ role: msg.role, content: msg.content });
    }
  }
  messages.push({ role: 'user', content: userMessage });

  let fullResponse = '';

  const stream = await client.messages.stream({
    model: MODEL,
    max_tokens: 4096,
    system: systemWithContext,
    messages,
  });

  for await (const event of stream) {
    if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
      const chunk = event.delta.text;
      fullResponse += chunk;
      if (onChunk) onChunk(chunk);
    }
  }

  const sources = searchResults.map((r) => ({
    title: r.document_title,
    subject: r.subject,
    class_level: r.class_level,
  }));

  return {
    message: fullResponse,
    sources,
    contextFound: searchResults.length > 0,
  };
};

// ─── GENERATE QUESTION PAPER ──────────────────────────────────────────────────

const generateQuestionPaper = async (params) => {
  const {
    subject,
    classLevel,
    paperType,
    totalMarks,
    durationMinutes,
    topics = [],
    difficultyDistribution = { easy: 30, medium: 50, hard: 20 },
  } = params;

  // Search for relevant content
  const topicQuery = topics.length > 0 ? topics.join(' ') : subject;
  const searchResults = await searchKnowledgeBase(topicQuery, {
    subject,
    classLevel,
    limit: 15,
  });

  const context = buildContext(searchResults);

  if (!context) {
    throw new Error('No content found in knowledge base for the specified subject and class level. Please upload relevant books first.');
  }

  const prompt = `Based on the following academic content, generate a complete ${paperType.replace('_', ' ')} examination paper.

REQUIREMENTS:
- Subject: ${subject}
- Class: ${classLevel}
- Total Marks: ${totalMarks}
- Duration: ${durationMinutes} minutes
- Difficulty: ${difficultyDistribution.easy}% Easy, ${difficultyDistribution.medium}% Medium, ${difficultyDistribution.hard}% Hard
${topics.length > 0 ? `- Focus Topics: ${topics.join(', ')}` : ''}

PAPER STRUCTURE (distribute marks appropriately):
1. Section A: Multiple Choice Questions (MCQs)
2. Section B: Short Answer Questions
3. Section C: Long Answer / Essay Questions

Generate the paper as a JSON object with this structure:
{
  "title": "Paper title",
  "sections": [
    {
      "name": "Section A: Multiple Choice Questions",
      "instructions": "Circle the correct answer",
      "questions": [
        {
          "number": 1,
          "question": "Question text",
          "type": "mcq",
          "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
          "correct_answer": "B",
          "marks": 1,
          "difficulty": "easy"
        }
      ]
    },
    {
      "name": "Section B: Short Answer Questions",
      "instructions": "Answer in 3-5 sentences",
      "questions": [
        {
          "number": 6,
          "question": "Question text",
          "type": "short_answer",
          "marks": 5,
          "difficulty": "medium",
          "model_answer": "Expected answer"
        }
      ]
    }
  ]
}

STRICTLY use only information from the provided academic content. Do not add questions on topics not covered in the content.`;

  const systemMsg = `You are an expert examination paper creator for ${SCHOOL_NAME}. Create well-structured, curriculum-aligned examination papers based strictly on the provided academic content. Always respond with valid JSON.

ACADEMIC CONTENT:
${context}`;

  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 8192,
    system: systemMsg,
    messages: [{ role: 'user', content: prompt }],
  });

  const responseText = response.content.find((b) => b.type === 'text')?.text || '';

  // Extract JSON from response
  const jsonMatch = responseText.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    throw new Error('Failed to generate valid question paper format');
  }

  const paperData = JSON.parse(jsonMatch[0]);

  // Extract all questions and answers for structured storage
  const questions = [];
  const answerKey = [];

  if (paperData.sections) {
    for (const section of paperData.sections) {
      if (section.questions) {
        for (const q of section.questions) {
          questions.push({
            number: q.number,
            section: section.name,
            question: q.question,
            type: q.type,
            options: q.options || null,
            marks: q.marks,
            difficulty: q.difficulty,
          });
          answerKey.push({
            number: q.number,
            correct_answer: q.correct_answer || q.model_answer,
            marks: q.marks,
          });
        }
      }
    }
  }

  return {
    paperData,
    questions,
    answerKey,
    sources: searchResults.slice(0, 5).map((r) => r.document_title),
  };
};

// ─── GENERATE ASSIGNMENT ──────────────────────────────────────────────────────

const generateAssignmentContent = async (params) => {
  const { topic, subject, classLevel, assignmentType } = params;

  const searchResults = await searchKnowledgeBase(topic, { subject, classLevel, limit: 8 });
  const context = buildContext(searchResults);

  if (!context) {
    throw new Error('No relevant content found in the knowledge base for this topic.');
  }

  const prompt = `Based on the provided academic content, create a ${assignmentType} assignment for ${classLevel} students on the topic: "${topic}".

Create:
1. Clear assignment title
2. Learning objectives (3-5 points)
3. Detailed instructions
4. ${assignmentType === 'research' ? '5 research questions to answer' : '5 specific tasks/questions'}
5. Evaluation criteria (marking rubric)

Keep everything strictly aligned with the provided content. Do not add information not present in the content.`;

  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 2048,
    system: `You are an educational content creator for ${SCHOOL_NAME}. Create assignments strictly based on the provided content.\n\nCONTENT:\n${context}`,
    messages: [{ role: 'user', content: prompt }],
  });

  return response.content.find((b) => b.type === 'text')?.text || '';
};

module.exports = { chatWithRAG, streamChatWithRAG, generateQuestionPaper, generateAssignmentContent };
