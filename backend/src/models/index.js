const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/database');

const isSQLite = sequelize.getDialect() === 'sqlite';

// Use JSON for both dialects (Sequelize maps JSONB→TEXT on SQLite)
const JSON_TYPE = DataTypes.JSON;

// ─── USER MODEL ───────────────────────────────────────────────────────────────
const User = sequelize.define('User', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  name: { type: DataTypes.STRING(100), allowNull: false },
  login_id: {
    type: DataTypes.STRING(50),
    allowNull: false,
    unique: true,
    comment: 'Student/Teacher ID for login',
  },
  email: { type: DataTypes.STRING(150), allowNull: true, unique: true },
  password_hash: { type: DataTypes.STRING(255), allowNull: false },
  role: {
    type: DataTypes.STRING(20),
    allowNull: false,
    defaultValue: 'student',
    validate: { isIn: [['student', 'teacher', 'admin']] },
  },
  class_name: { type: DataTypes.STRING(50), allowNull: true },
  // Store as JSON string for SQLite compatibility
  subjects: {
    type: JSON_TYPE,
    allowNull: true,
    defaultValue: [],
    get() {
      const val = this.getDataValue('subjects');
      if (typeof val === 'string') { try { return JSON.parse(val); } catch { return []; } }
      return val || [];
    },
  },
  is_active: { type: DataTypes.BOOLEAN, defaultValue: true },
  last_login: { type: DataTypes.DATE, allowNull: true },
}, { tableName: 'users', timestamps: true, underscored: true });

// ─── ASSIGNMENT MODEL ─────────────────────────────────────────────────────────
const Assignment = sequelize.define('Assignment', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  title: { type: DataTypes.STRING(200), allowNull: false },
  description: { type: DataTypes.TEXT, allowNull: false },
  subject: { type: DataTypes.STRING(100), allowNull: false },
  class_name: { type: DataTypes.STRING(50), allowNull: false },
  teacher_id: { type: DataTypes.UUID, allowNull: false },
  due_date: { type: DataTypes.DATEONLY, allowNull: true },
  assignment_type: {
    type: DataTypes.STRING(20),
    defaultValue: 'homework',
    validate: { isIn: [['homework', 'quiz', 'project', 'research', 'classwork']] },
  },
  max_marks: { type: DataTypes.INTEGER, defaultValue: 100 },
  instructions: { type: DataTypes.TEXT, allowNull: true },
  is_active: { type: DataTypes.BOOLEAN, defaultValue: true },
}, { tableName: 'assignments', timestamps: true, underscored: true });

// ─── SUBMISSION MODEL ─────────────────────────────────────────────────────────
const Submission = sequelize.define('Submission', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  assignment_id: { type: DataTypes.UUID, allowNull: false },
  student_id: { type: DataTypes.UUID, allowNull: false },
  content: { type: DataTypes.TEXT, allowNull: true },
  file_path: { type: DataTypes.STRING(500), allowNull: true },
  file_name: { type: DataTypes.STRING(255), allowNull: true },
  status: {
    type: DataTypes.STRING(20),
    defaultValue: 'draft',
    validate: { isIn: [['draft', 'submitted', 'graded', 'returned']] },
  },
  grade: { type: DataTypes.FLOAT, allowNull: true },
  feedback: { type: DataTypes.TEXT, allowNull: true },
  submitted_at: { type: DataTypes.DATE, allowNull: true },
  ai_generated: { type: DataTypes.BOOLEAN, defaultValue: false },
}, { tableName: 'submissions', timestamps: true, underscored: true });

// ─── DOCUMENT MODEL ───────────────────────────────────────────────────────────
const Document = sequelize.define('Document', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  title: { type: DataTypes.STRING(255), allowNull: false },
  subject: { type: DataTypes.STRING(100), allowNull: false },
  class_level: { type: DataTypes.STRING(50), allowNull: false },
  description: { type: DataTypes.TEXT, allowNull: true },
  file_path: { type: DataTypes.STRING(500), allowNull: false },
  file_name: { type: DataTypes.STRING(255), allowNull: false },
  file_type: { type: DataTypes.STRING(50), allowNull: false },
  file_size: { type: DataTypes.INTEGER, allowNull: true },
  uploaded_by: { type: DataTypes.UUID, allowNull: false },
  is_ingested: { type: DataTypes.BOOLEAN, defaultValue: false },
  total_chunks: { type: DataTypes.INTEGER, defaultValue: 0 },
  ingestion_error: { type: DataTypes.TEXT, allowNull: true },
}, { tableName: 'documents', timestamps: true, underscored: true });

// ─── DOCUMENT CHUNK MODEL ─────────────────────────────────────────────────────
const DocumentChunk = sequelize.define('DocumentChunk', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  document_id: { type: DataTypes.UUID, allowNull: false },
  chunk_text: { type: DataTypes.TEXT, allowNull: false },
  chunk_index: { type: DataTypes.INTEGER, allowNull: false },
  word_count: { type: DataTypes.INTEGER, defaultValue: 0 },
}, { tableName: 'document_chunks', timestamps: true, underscored: true });

// ─── QUESTION PAPER MODEL ─────────────────────────────────────────────────────
const QuestionPaper = sequelize.define('QuestionPaper', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  title: { type: DataTypes.STRING(255), allowNull: false },
  subject: { type: DataTypes.STRING(100), allowNull: false },
  class_name: { type: DataTypes.STRING(50), allowNull: false },
  teacher_id: { type: DataTypes.UUID, allowNull: false },
  paper_type: {
    type: DataTypes.STRING(20),
    defaultValue: 'class_test',
    validate: { isIn: [['monthly_test', 'mid_term', 'final_exam', 'quiz', 'class_test']] },
  },
  questions: { type: JSON_TYPE, allowNull: false, defaultValue: [] },
  answer_key: { type: JSON_TYPE, allowNull: false, defaultValue: [] },
  total_marks: { type: DataTypes.INTEGER, defaultValue: 100 },
  duration_minutes: { type: DataTypes.INTEGER, defaultValue: 60 },
  instructions: { type: DataTypes.TEXT, allowNull: true },
  is_published: { type: DataTypes.BOOLEAN, defaultValue: false },
}, { tableName: 'question_papers', timestamps: true, underscored: true });

// ─── CHAT HISTORY MODEL ───────────────────────────────────────────────────────
const ChatHistory = sequelize.define('ChatHistory', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  user_id: { type: DataTypes.UUID, allowNull: false },
  session_id: { type: DataTypes.STRING(100), allowNull: false },
  role: {
    type: DataTypes.STRING(10),
    allowNull: false,
    validate: { isIn: [['user', 'assistant']] },
  },
  content: { type: DataTypes.TEXT, allowNull: false },
  subject_context: { type: DataTypes.STRING(100), allowNull: true },
  sources_used: { type: JSON_TYPE, allowNull: true, defaultValue: [] },
}, { tableName: 'chat_history', timestamps: true, underscored: true });

// ─── NOTIFICATION MODEL ───────────────────────────────────────────────────────
const Notification = sequelize.define('Notification', {
  id: { type: DataTypes.UUID, defaultValue: DataTypes.UUIDV4, primaryKey: true },
  user_id: { type: DataTypes.UUID, allowNull: false },
  title: { type: DataTypes.STRING(200), allowNull: false },
  message: { type: DataTypes.TEXT, allowNull: false },
  type: {
    type: DataTypes.STRING(20),
    defaultValue: 'system',
    validate: { isIn: [['assignment', 'submission', 'grade', 'announcement', 'system']] },
  },
  is_read: { type: DataTypes.BOOLEAN, defaultValue: false },
  action_url: { type: DataTypes.STRING(255), allowNull: true },
}, { tableName: 'notifications', timestamps: true, underscored: true });

// ─── ASSOCIATIONS ─────────────────────────────────────────────────────────────
User.hasMany(Assignment, { foreignKey: 'teacher_id', as: 'created_assignments' });
Assignment.belongsTo(User, { foreignKey: 'teacher_id', as: 'teacher' });

User.hasMany(Submission, { foreignKey: 'student_id', as: 'submissions' });
Submission.belongsTo(User, { foreignKey: 'student_id', as: 'student' });

Assignment.hasMany(Submission, { foreignKey: 'assignment_id', as: 'submissions' });
Submission.belongsTo(Assignment, { foreignKey: 'assignment_id', as: 'assignment' });

User.hasMany(Document, { foreignKey: 'uploaded_by', as: 'documents' });
Document.belongsTo(User, { foreignKey: 'uploaded_by', as: 'uploader' });

Document.hasMany(DocumentChunk, { foreignKey: 'document_id', as: 'chunks', onDelete: 'CASCADE' });
DocumentChunk.belongsTo(Document, { foreignKey: 'document_id', as: 'document' });

User.hasMany(QuestionPaper, { foreignKey: 'teacher_id', as: 'question_papers' });
QuestionPaper.belongsTo(User, { foreignKey: 'teacher_id', as: 'teacher' });

User.hasMany(ChatHistory, { foreignKey: 'user_id', as: 'chat_history', onDelete: 'CASCADE' });
ChatHistory.belongsTo(User, { foreignKey: 'user_id', as: 'user' });

User.hasMany(Notification, { foreignKey: 'user_id', as: 'notifications', onDelete: 'CASCADE' });
Notification.belongsTo(User, { foreignKey: 'user_id', as: 'user' });

module.exports = { User, Assignment, Submission, Document, DocumentChunk, QuestionPaper, ChatHistory, Notification };
