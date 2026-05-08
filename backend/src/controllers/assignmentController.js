const { Assignment, Submission, User, Notification } = require('../models');
const { generateAssignmentContent } = require('../services/aiService');
const { Op } = require('sequelize');

// GET /api/assignments (teacher gets own, student gets their class)
const getAssignments = async (req, res) => {
  try {
    const { subject, status } = req.query;
    let where = { is_active: true };

    if (req.user.role === 'teacher') {
      where.teacher_id = req.user.id;
    } else if (req.user.role === 'student') {
      where.class_name = req.user.class_name;
    }

    if (subject) where.subject = subject;

    const assignments = await Assignment.findAll({
      where,
      include: [{ model: User, as: 'teacher', attributes: ['id', 'name'] }],
      order: [['created_at', 'DESC']],
    });

    // For students, add their submission status
    if (req.user.role === 'student') {
      const assignmentIds = assignments.map((a) => a.id);
      const submissions = await Submission.findAll({
        where: { student_id: req.user.id, assignment_id: { [Op.in]: assignmentIds } },
        attributes: ['assignment_id', 'status', 'grade'],
      });
      const submissionMap = {};
      submissions.forEach((s) => { submissionMap[s.assignment_id] = s; });

      const result = assignments.map((a) => ({
        ...a.toJSON(),
        my_submission: submissionMap[a.id] || null,
      }));
      return res.json(result);
    }

    res.json(assignments);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch assignments' });
  }
};

// GET /api/assignments/:id
const getAssignment = async (req, res) => {
  try {
    const assignment = await Assignment.findByPk(req.params.id, {
      include: [
        { model: User, as: 'teacher', attributes: ['id', 'name'] },
        {
          model: Submission,
          as: 'submissions',
          include: [{ model: User, as: 'student', attributes: ['id', 'name', 'login_id', 'class_name'] }],
        },
      ],
    });

    if (!assignment) return res.status(404).json({ error: 'Assignment not found' });

    // Students can only see their own submission
    if (req.user.role === 'student') {
      const mySubmission = assignment.submissions.find(
        (s) => s.student_id === req.user.id
      );
      return res.json({ ...assignment.toJSON(), submissions: mySubmission ? [mySubmission] : [] });
    }

    res.json(assignment);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch assignment' });
  }
};

// POST /api/assignments (teacher only)
const createAssignment = async (req, res) => {
  try {
    const { title, description, subject, class_name, due_date, assignment_type, max_marks, instructions } = req.body;

    if (!title || !description || !subject || !class_name) {
      return res.status(400).json({ error: 'Title, description, subject, and class are required' });
    }

    const assignment = await Assignment.create({
      title,
      description,
      subject,
      class_name,
      teacher_id: req.user.id,
      due_date: due_date || null,
      assignment_type: assignment_type || 'homework',
      max_marks: max_marks || 100,
      instructions: instructions || null,
    });

    // Notify all students in the class
    const students = await User.findAll({
      where: { role: 'student', class_name, is_active: true },
      attributes: ['id'],
    });

    if (students.length > 0) {
      const notifications = students.map((s) => ({
        user_id: s.id,
        title: 'New Assignment',
        message: `New ${assignment_type || 'homework'} assigned: "${title}" for ${subject}`,
        type: 'assignment',
        action_url: `/assignments/${assignment.id}`,
      }));
      await Notification.bulkCreate(notifications);
    }

    res.status(201).json(assignment);
  } catch (error) {
    res.status(500).json({ error: 'Failed to create assignment' });
  }
};

// PUT /api/assignments/:id (teacher only)
const updateAssignment = async (req, res) => {
  try {
    const assignment = await Assignment.findByPk(req.params.id);
    if (!assignment) return res.status(404).json({ error: 'Assignment not found' });
    if (assignment.teacher_id !== req.user.id && req.user.role !== 'admin') {
      return res.status(403).json({ error: 'Not authorized' });
    }

    await assignment.update(req.body);
    res.json(assignment);
  } catch (error) {
    res.status(500).json({ error: 'Failed to update assignment' });
  }
};

// DELETE /api/assignments/:id (teacher/admin only)
const deleteAssignment = async (req, res) => {
  try {
    const assignment = await Assignment.findByPk(req.params.id);
    if (!assignment) return res.status(404).json({ error: 'Assignment not found' });
    if (assignment.teacher_id !== req.user.id && req.user.role !== 'admin') {
      return res.status(403).json({ error: 'Not authorized' });
    }

    await assignment.update({ is_active: false });
    res.json({ message: 'Assignment deleted' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete assignment' });
  }
};

// POST /api/assignments/ai-generate (teacher only)
const generateWithAI = async (req, res) => {
  try {
    const { topic, subject, class_level, assignment_type } = req.body;
    if (!topic || !subject || !class_level) {
      return res.status(400).json({ error: 'Topic, subject, and class level are required' });
    }

    const content = await generateAssignmentContent({ topic, subject, classLevel: class_level, assignmentType: assignment_type || 'homework' });
    res.json({ content });
  } catch (error) {
    res.status(500).json({ error: error.message || 'Failed to generate assignment' });
  }
};

// POST /api/assignments/:id/submit (student only)
const submitAssignment = async (req, res) => {
  try {
    const { content } = req.body;
    const assignment = await Assignment.findByPk(req.params.id);

    if (!assignment) return res.status(404).json({ error: 'Assignment not found' });
    if (assignment.class_name !== req.user.class_name) {
      return res.status(403).json({ error: 'This assignment is not for your class' });
    }

    // Check if already submitted
    let submission = await Submission.findOne({
      where: { assignment_id: req.params.id, student_id: req.user.id },
    });

    const submissionData = {
      content: content || null,
      status: 'submitted',
      submitted_at: new Date(),
      ai_generated: req.body.ai_generated || false,
    };

    if (req.file) {
      submissionData.file_path = req.file.path;
      submissionData.file_name = req.file.originalname;
    }

    if (submission) {
      await submission.update(submissionData);
    } else {
      submission = await Submission.create({
        assignment_id: req.params.id,
        student_id: req.user.id,
        ...submissionData,
      });
    }

    // Notify teacher
    await Notification.create({
      user_id: assignment.teacher_id,
      title: 'Assignment Submitted',
      message: `${req.user.name} submitted "${assignment.title}"`,
      type: 'submission',
    });

    res.json(submission);
  } catch (error) {
    res.status(500).json({ error: 'Failed to submit assignment' });
  }
};

// POST /api/assignments/:id/grade (teacher only)
const gradeSubmission = async (req, res) => {
  try {
    const { submission_id, grade, feedback } = req.body;
    const submission = await Submission.findByPk(submission_id, {
      include: [{ model: Assignment, as: 'assignment' }],
    });

    if (!submission) return res.status(404).json({ error: 'Submission not found' });

    await submission.update({ grade, feedback, status: 'graded' });

    // Notify student
    await Notification.create({
      user_id: submission.student_id,
      title: 'Assignment Graded',
      message: `Your submission for "${submission.assignment.title}" has been graded: ${grade}`,
      type: 'grade',
    });

    res.json(submission);
  } catch (error) {
    res.status(500).json({ error: 'Failed to grade submission' });
  }
};

module.exports = { getAssignments, getAssignment, createAssignment, updateAssignment, deleteAssignment, generateWithAI, submitAssignment, gradeSubmission };
