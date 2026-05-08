const { ChatHistory } = require('../models');
const { streamChatWithRAG } = require('../services/aiService');
const { v4: uuidv4 } = require('uuid');

// POST /api/chat/message  (streaming SSE)
const sendMessage = async (req, res) => {
  const { message, subject, session_id } = req.body;

  if (!message || message.trim().length === 0) {
    return res.status(400).json({ error: 'Message is required' });
  }

  const sessionId = session_id || uuidv4();
  const user = req.user;

  // Set up SSE headers for streaming
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  try {
    // Fetch recent conversation history for this session
    const history = await ChatHistory.findAll({
      where: { user_id: user.id, session_id: sessionId },
      order: [['created_at', 'ASC']],
      limit: 20,
    });

    const conversationHistory = history.map((h) => ({
      role: h.role,
      content: h.content,
    }));

    // Save user message
    await ChatHistory.create({
      user_id: user.id,
      session_id: sessionId,
      role: 'user',
      content: message.trim(),
      subject_context: subject || null,
    });

    let fullResponse = '';
    let sources = [];

    // Stream response
    const result = await streamChatWithRAG(
      message.trim(),
      {
        userRole: user.role,
        subject: subject || null,
        classLevel: user.class_name || null,
        conversationHistory,
      },
      (chunk) => {
        res.write(`data: ${JSON.stringify({ type: 'chunk', content: chunk })}\n\n`);
      }
    );

    fullResponse = result.message;
    sources = result.sources;

    // Save assistant response
    await ChatHistory.create({
      user_id: user.id,
      session_id: sessionId,
      role: 'assistant',
      content: fullResponse,
      subject_context: subject || null,
      sources_used: sources,
    });

    // Send completion event
    res.write(`data: ${JSON.stringify({
      type: 'done',
      session_id: sessionId,
      sources,
      context_found: result.contextFound,
    })}\n\n`);

    res.end();
  } catch (error) {
    console.error('Chat error:', error);
    res.write(`data: ${JSON.stringify({ type: 'error', message: 'An error occurred. Please try again.' })}\n\n`);
    res.end();
  }
};

// GET /api/chat/history
const getChatHistory = async (req, res) => {
  try {
    const { session_id, limit = 50 } = req.query;
    const where = { user_id: req.user.id };
    if (session_id) where.session_id = session_id;

    const history = await ChatHistory.findAll({
      where,
      order: [['created_at', 'DESC']],
      limit: parseInt(limit),
    });

    res.json(history.reverse());
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch chat history' });
  }
};

// GET /api/chat/sessions
const getChatSessions = async (req, res) => {
  try {
    const { sequelize } = require('../config/database');
    const sessions = await sequelize.query(`
      SELECT
        session_id,
        MAX(subject_context) as subject,
        COUNT(*) as message_count,
        MIN(created_at) as started_at,
        MAX(created_at) as last_message_at,
        (SELECT content FROM chat_history ch2
         WHERE ch2.session_id = ch.session_id AND ch2.user_id = :userId AND ch2.role = 'user'
         ORDER BY ch2.created_at ASC LIMIT 1) as first_message
      FROM chat_history ch
      WHERE user_id = :userId
      GROUP BY session_id
      ORDER BY last_message_at DESC
      LIMIT 20
    `, {
      replacements: { userId: req.user.id },
      type: sequelize.QueryTypes.SELECT,
    });

    res.json(sessions);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch sessions' });
  }
};

// DELETE /api/chat/session/:sessionId
const deleteSession = async (req, res) => {
  try {
    await ChatHistory.destroy({
      where: { user_id: req.user.id, session_id: req.params.sessionId },
    });
    res.json({ message: 'Session deleted' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete session' });
  }
};

module.exports = { sendMessage, getChatHistory, getChatSessions, deleteSession };
