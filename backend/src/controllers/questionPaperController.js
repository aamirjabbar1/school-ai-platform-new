const { QuestionPaper, User } = require('../models');
const { generateQuestionPaper } = require('../services/aiService');

// GET /api/question-papers
const getQuestionPapers = async (req, res) => {
  try {
    const { subject, class_name, paper_type } = req.query;
    const where = {};

    if (req.user.role === 'teacher') where.teacher_id = req.user.id;
    if (subject) where.subject = subject;
    if (class_name) where.class_name = class_name;
    if (paper_type) where.paper_type = paper_type;

    const papers = await QuestionPaper.findAll({
      where,
      include: [{ model: User, as: 'teacher', attributes: ['id', 'name'] }],
      order: [['created_at', 'DESC']],
    });

    // Students only see published papers
    if (req.user.role === 'student') {
      return res.json(papers.filter((p) => p.is_published && p.class_name === req.user.class_name));
    }

    res.json(papers);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch question papers' });
  }
};

// GET /api/question-papers/:id
const getQuestionPaper = async (req, res) => {
  try {
    const paper = await QuestionPaper.findByPk(req.params.id, {
      include: [{ model: User, as: 'teacher', attributes: ['id', 'name'] }],
    });

    if (!paper) return res.status(404).json({ error: 'Question paper not found' });

    // Students: only see published papers, without answer key
    if (req.user.role === 'student') {
      if (!paper.is_published) return res.status(403).json({ error: 'Paper not published yet' });
      const { answer_key, ...paperData } = paper.toJSON();
      return res.json(paperData);
    }

    res.json(paper);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch question paper' });
  }
};

// POST /api/question-papers/generate (teacher only)
const generatePaper = async (req, res) => {
  try {
    const { subject, class_name, paper_type, total_marks, duration_minutes, topics, difficulty_distribution } = req.body;

    if (!subject || !class_name || !paper_type) {
      return res.status(400).json({ error: 'Subject, class name, and paper type are required' });
    }

    const result = await generateQuestionPaper({
      subject,
      classLevel: class_name,
      paperType: paper_type,
      totalMarks: total_marks || 100,
      durationMinutes: duration_minutes || 60,
      topics: topics || [],
      difficultyDistribution: difficulty_distribution || { easy: 30, medium: 50, hard: 20 },
    });

    // Save the generated paper
    const title = `${paper_type.replace('_', ' ').toUpperCase()} - ${subject} (${class_name})`;
    const paper = await QuestionPaper.create({
      title,
      subject,
      class_name,
      teacher_id: req.user.id,
      paper_type,
      questions: result.questions,
      answer_key: result.answerKey,
      total_marks: total_marks || 100,
      duration_minutes: duration_minutes || 60,
      is_published: false,
    });

    res.status(201).json({
      paper,
      formatted_paper: result.paperData,
      sources_used: result.sources,
    });
  } catch (error) {
    console.error('Paper generation error:', error);
    res.status(500).json({ error: error.message || 'Failed to generate question paper' });
  }
};

// POST /api/question-papers (manual creation)
const createPaper = async (req, res) => {
  try {
    const { title, subject, class_name, paper_type, questions, answer_key, total_marks, duration_minutes, instructions } = req.body;

    if (!title || !subject || !class_name || !questions) {
      return res.status(400).json({ error: 'Title, subject, class, and questions are required' });
    }

    const paper = await QuestionPaper.create({
      title,
      subject,
      class_name,
      teacher_id: req.user.id,
      paper_type: paper_type || 'class_test',
      questions,
      answer_key: answer_key || [],
      total_marks: total_marks || 100,
      duration_minutes: duration_minutes || 60,
      instructions: instructions || null,
    });

    res.status(201).json(paper);
  } catch (error) {
    res.status(500).json({ error: 'Failed to create question paper' });
  }
};

// PUT /api/question-papers/:id/publish (teacher only)
const publishPaper = async (req, res) => {
  try {
    const paper = await QuestionPaper.findByPk(req.params.id);
    if (!paper) return res.status(404).json({ error: 'Paper not found' });
    if (paper.teacher_id !== req.user.id && req.user.role !== 'admin') {
      return res.status(403).json({ error: 'Not authorized' });
    }

    await paper.update({ is_published: !paper.is_published });
    res.json({ message: `Paper ${paper.is_published ? 'published' : 'unpublished'}`, paper });
  } catch (error) {
    res.status(500).json({ error: 'Failed to update paper status' });
  }
};

// DELETE /api/question-papers/:id (teacher/admin)
const deletePaper = async (req, res) => {
  try {
    const paper = await QuestionPaper.findByPk(req.params.id);
    if (!paper) return res.status(404).json({ error: 'Paper not found' });
    if (paper.teacher_id !== req.user.id && req.user.role !== 'admin') {
      return res.status(403).json({ error: 'Not authorized' });
    }

    await paper.destroy();
    res.json({ message: 'Paper deleted' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete paper' });
  }
};

module.exports = { getQuestionPapers, getQuestionPaper, generatePaper, createPaper, publishPaper, deletePaper };
