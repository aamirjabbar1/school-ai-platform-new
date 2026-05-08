const express = require('express');
const router = express.Router();
const { authenticate, authorize } = require('../middleware/auth');
const { documentUpload, submissionUpload } = require('../middleware/upload');

const authCtrl = require('../controllers/authController');
const chatCtrl = require('../controllers/chatController');
const assignCtrl = require('../controllers/assignmentController');
const docCtrl = require('../controllers/documentController');
const qpCtrl = require('../controllers/questionPaperController');
const adminCtrl = require('../controllers/adminController');

// ─── AUTH ROUTES ──────────────────────────────────────────────────────────────
router.post('/auth/login', authCtrl.login);
router.get('/auth/me', authenticate, authCtrl.getMe);
router.put('/auth/change-password', authenticate, authCtrl.changePassword);

// ─── CHAT ROUTES ──────────────────────────────────────────────────────────────
router.post('/chat/message', authenticate, chatCtrl.sendMessage);
router.get('/chat/history', authenticate, chatCtrl.getChatHistory);
router.get('/chat/sessions', authenticate, chatCtrl.getChatSessions);
router.delete('/chat/session/:sessionId', authenticate, chatCtrl.deleteSession);

// ─── ASSIGNMENT ROUTES ────────────────────────────────────────────────────────
router.get('/assignments', authenticate, assignCtrl.getAssignments);
router.get('/assignments/:id', authenticate, assignCtrl.getAssignment);
router.post('/assignments', authenticate, authorize('teacher', 'admin'), assignCtrl.createAssignment);
router.put('/assignments/:id', authenticate, authorize('teacher', 'admin'), assignCtrl.updateAssignment);
router.delete('/assignments/:id', authenticate, authorize('teacher', 'admin'), assignCtrl.deleteAssignment);
router.post('/assignments/ai-generate', authenticate, authorize('teacher', 'admin'), assignCtrl.generateWithAI);
router.post('/assignments/:id/submit', authenticate, authorize('student'), submissionUpload.single('submission'), assignCtrl.submitAssignment);
router.post('/assignments/grade', authenticate, authorize('teacher', 'admin'), assignCtrl.gradeSubmission);

// ─── DOCUMENT ROUTES ──────────────────────────────────────────────────────────
router.get('/documents', authenticate, docCtrl.getDocuments);
router.get('/documents/stats', authenticate, authorize('admin'), docCtrl.getStats);
router.post('/documents/upload', authenticate, authorize('admin', 'teacher'), documentUpload.single('document'), docCtrl.uploadDocument);
router.post('/documents/:id/reingest', authenticate, authorize('admin'), docCtrl.reingestDocument);
router.delete('/documents/:id', authenticate, authorize('admin'), docCtrl.deleteDocument);

// ─── QUESTION PAPER ROUTES ────────────────────────────────────────────────────
router.get('/question-papers', authenticate, qpCtrl.getQuestionPapers);
router.get('/question-papers/:id', authenticate, qpCtrl.getQuestionPaper);
router.post('/question-papers/generate', authenticate, authorize('teacher', 'admin'), qpCtrl.generatePaper);
router.post('/question-papers', authenticate, authorize('teacher', 'admin'), qpCtrl.createPaper);
router.put('/question-papers/:id/publish', authenticate, authorize('teacher', 'admin'), qpCtrl.publishPaper);
router.delete('/question-papers/:id', authenticate, authorize('teacher', 'admin'), qpCtrl.deletePaper);

// ─── ADMIN ROUTES ─────────────────────────────────────────────────────────────
router.get('/admin/dashboard', authenticate, authorize('admin'), adminCtrl.getDashboard);
router.get('/admin/users', authenticate, authorize('admin'), adminCtrl.getUsers);
router.post('/admin/users', authenticate, authorize('admin'), adminCtrl.createUser);
router.post('/admin/users/bulk', authenticate, authorize('admin'), adminCtrl.bulkCreateUsers);
router.put('/admin/users/:id', authenticate, authorize('admin'), adminCtrl.updateUser);
router.delete('/admin/users/:id', authenticate, authorize('admin'), adminCtrl.deleteUser);
router.post('/admin/broadcast', authenticate, authorize('admin'), adminCtrl.broadcastNotification);

// ─── NOTIFICATION ROUTES (all authenticated users) ───────────────────────────
router.get('/notifications', authenticate, adminCtrl.getNotifications);
router.put('/notifications/:id/read', authenticate, adminCtrl.markNotificationRead);

module.exports = router;
