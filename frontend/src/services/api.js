import axios from 'axios';

const API_BASE = 'https://api.lssbot.net/api';

// Exported for the few places a browser fetches a URL itself — a PDF viewer
// loading a textbook, a video element playing a recording — where axios (and
// therefore our Authorization header) is not in the loop.
export const API_ORIGIN = API_BASE;

const api = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Handle 401 globally
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

// ─── AUTH ─────────────────────────────────────────────────────────────────────
export const authAPI = {
  login: (credentials) => api.post('/auth/login', credentials),
  getMe: () => api.get('/auth/me'),
  changePassword: (data) => api.put('/auth/change-password', data),
  forceChangePassword: (newPassword) => api.put('/auth/force-change-password', { new_password: newPassword }),
};

// ─── CHAT ─────────────────────────────────────────────────────────────────────
export const chatAPI = {
  // Returns a Response with an SSE-encoded body. Pass `signal` from an
  // AbortController to support stop/cancel.
  sendMessage: (data, signal) => {
    const token = localStorage.getItem('token');
    return fetch(`${API_BASE}/chat/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
      signal,
    });
  },
  getHistory: (params) => api.get('/chat/history', { params }),
  getSessions: () => api.get('/chat/sessions'),
  deleteSession: (id) => api.delete(`/chat/session/${id}`),
  // Memory endpoints
  getMemoryTopics: () => api.get('/chat/memory/topics'),
  searchMemory: (q, subject) => api.get('/chat/memory/search', { params: { q, subject } }),
  clearMemory: (subject) => api.delete('/chat/memory', { params: { subject } }),
};

// ─── ASSIGNMENTS ──────────────────────────────────────────────────────────────
export const assignmentAPI = {
  getAll: (params) => api.get('/assignments', { params }),
  getOne: (id) => api.get(`/assignments/${id}`),
  create: (data) => api.post('/assignments', data),
  update: (id, data) => api.put(`/assignments/${id}`, data),
  delete: (id) => api.delete(`/assignments/${id}`),
  // AI generation runs an LLM call + RAG retrieval; allow up to 10 min.
  generateWithAI: (data) => api.post('/assignments/ai-generate', data, { timeout: 600000 }),
  submit: (id, data) => {
    const formData = new FormData();
    Object.entries(data).forEach(([k, v]) => { if (v !== undefined && v !== null) formData.append(k, v); });
    return api.post(`/assignments/${id}/submit`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  grade: (data) => api.post('/assignments/grade', data),
};

// ─── DOCUMENTS ────────────────────────────────────────────────────────────────
export const documentAPI = {
  getAll: (params) => api.get('/documents', { params }),
  getStats: () => api.get('/documents/stats'),
  // onUploadProgress: optional (e) => {} to drive a progress bar
  upload: (formData, onUploadProgress) => api.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
    onUploadProgress,
  }),
  reingest: (id) => api.post(`/documents/${id}/reingest`),
  delete: (id) => api.delete(`/documents/${id}`),
};

// ─── QUESTION PAPERS ──────────────────────────────────────────────────────────
export const questionPaperAPI = {
  getAll: (params) => api.get('/question-papers', { params }),
  getOne: (id) => api.get(`/question-papers/${id}`),
  // Generation runs an LLM call + RAG retrieval (books + past papers); allow up to 10 min.
  generate: (data) => api.post('/question-papers/generate', data, { timeout: 600000 }),
  create: (data) => api.post('/question-papers', data),
  togglePublish: (id) => api.put(`/question-papers/${id}/publish`),
  delete: (id) => api.delete(`/question-papers/${id}`),
  // Server-rendered PDF (teachers get answer key, students get questions only)
  downloadPdf: (id) => api.get(`/question-papers/${id}/pdf`, { responseType: 'blob' }),
  // AI exam suite (powered by uploaded past papers)
  predictImportant: (data) => api.post('/question-papers/predict-important', data, { timeout: 120000 }),
  generatePractice: (data) => api.post('/question-papers/practice/generate', data, { timeout: 120000 }),
  gradePractice: (data) => api.post('/question-papers/practice/grade', data, { timeout: 120000 }),
};

// ─── LESSON PLANS ───────────────────────────────────────────────────────────
export const lessonPlanAPI = {
  getAll: (params) => api.get('/lesson-plans', { params }),
  getOne: (id) => api.get(`/lesson-plans/${id}`),
  // Generation runs an LLM call + RAG retrieval; allow up to 10 min.
  generate: (data) => api.post('/lesson-plans/generate', data, { timeout: 600000 }),
  create: (data) => api.post('/lesson-plans', data),
  update: (id, data) => api.put(`/lesson-plans/${id}`, data),
  togglePublish: (id) => api.put(`/lesson-plans/${id}/publish`),
  duplicate: (id) => api.post(`/lesson-plans/${id}/duplicate`),
  delete: (id) => api.delete(`/lesson-plans/${id}`),
  downloadPdf: (id) => api.get(`/lesson-plans/${id}/pdf`, { responseType: 'blob' }),
  downloadDocx: (id) => api.get(`/lesson-plans/${id}/docx`, { responseType: 'blob' }),
};

// ─── ADMIN ────────────────────────────────────────────────────────────────────
export const adminAPI = {
  getDashboard: () => api.get('/admin/dashboard'),
  getUsers: (params) => api.get('/admin/users', { params }),
  createUser: (data) => api.post('/admin/users', data),
  bulkCreateUsers: (data) => api.post('/admin/users/bulk', data),
  updateUser: (id, data) => api.put(`/admin/users/${id}`, data),
  resetPassword: (id, newPassword) => api.post(`/admin/users/${id}/reset-password`, { new_password: newPassword }),
  deleteUser: (id) => api.delete(`/admin/users/${id}`),
  broadcast: (data) => api.post('/admin/broadcast', data),
  importTeachers: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/admin/import-teachers', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
  },
  downloadCredentials: () => api.get('/admin/download-credentials', { responseType: 'blob' }),
  // Curriculum mappings (student class → knowledge-base class)
  getCurriculumMappings: () => api.get('/admin/curriculum-mappings'),
  createCurriculumMapping: (data) => api.post('/admin/curriculum-mappings', data),
  updateCurriculumMapping: (id, data) => api.put(`/admin/curriculum-mappings/${id}`, data),
  deleteCurriculumMapping: (id) => api.delete(`/admin/curriculum-mappings/${id}`),
  // Bulk student import (Excel → background Celery job)
  bulkImportStudents: ({ file, duplicate_mode, password_mode, section_mode, custom_password }) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('duplicate_mode', duplicate_mode);
    formData.append('password_mode', password_mode);
    formData.append('section_mode', section_mode);
    if (custom_password) formData.append('custom_password', custom_password);
    return api.post('/admin/students/bulk-import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    });
  },
  // Centralised oversight of teacher-authored lesson plans and question papers.
  // `type` is 'lesson-plans' or 'question-papers'.
  listContent: (type, params) => api.get(`/admin/content/${type}`, { params }),
  getContent: (type, id) => api.get(`/admin/content/${type}/${id}`),
  getContentSummary: () => api.get('/admin/content/summary'),
  getContentFilters: () => api.get('/admin/content/filters'),
  getContentRevisions: (type, id) => api.get(`/admin/content/${type}/${id}/revisions`),
  getContentRevision: (type, id, revisionId) =>
    api.get(`/admin/content/${type}/${id}/revisions/${revisionId}`),
  reviewContent: (type, id, data) => api.post(`/admin/content/${type}/${id}/review`, data),
  editContent: (type, id, data) => api.patch(`/admin/content/${type}/${id}`, data),
  archiveContent: (type, id, data) => api.post(`/admin/content/${type}/${id}/archive`, data),
  // Re-runs the AI over the record's stored inputs; allow up to 10 min.
  regenerateContent: (type, id) =>
    api.post(`/admin/content/${type}/${id}/regenerate`, {}, { timeout: 600000 }),
  deleteContent: (type, id) => api.delete(`/admin/content/${type}/${id}`),
  getImportBatches: () => api.get('/admin/students/import-batches'),
  getImportBatch: (id) => api.get(`/admin/students/import-batches/${id}`),
  downloadImportCredentials: (id) => api.get(`/admin/students/import-batches/${id}/credentials`, { responseType: 'blob' }),
  rollbackImport: (id) => api.post(`/admin/students/import-batches/${id}/rollback`),
};

// ─── ONLINE CLASSES ───────────────────────────────────────────────────────────
// The classroom never asks anyone for a meeting ID, link or password: the
// server decides which room a user belongs in and mints a short-lived token.
export const onlineClassAPI = {
  // Teacher
  start: (data) => api.post('/online-classes/start', data),
  teacherSessions: () => api.get('/online-classes/teacher/sessions'),
  end: (id) => api.post(`/online-classes/${id}/end`),
  attendance: (id) => api.get(`/online-classes/${id}/attendance`),
  muteAll: (id) => api.post(`/online-classes/${id}/controls/mute-all`),
  muteStudent: (id, user_id) => api.post(`/online-classes/${id}/controls/mute`, { user_id }),
  setPermissions: (id, data) => api.post(`/online-classes/${id}/controls/permissions`, data),
  lockClass: (id, locked) => api.post(`/online-classes/${id}/controls/lock`, { locked }),
  lockCameras: (id, locked) => api.post(`/online-classes/${id}/controls/cameras`, { locked }),
  removeStudent: (id, user_id) => api.post(`/online-classes/${id}/controls/remove`, { user_id }),
  lowerHand: (id, user_id) => api.post(`/online-classes/${id}/controls/hand`, { user_id }),

  // Student
  today: () => api.get('/online-classes/student/today'),

  // Shared
  join: (id) => api.post(`/online-classes/${id}/join`),
  leave: (id) => api.post(`/online-classes/${id}/leave`),
  raiseHand: (id, raised) => api.post(`/online-classes/${id}/hand`, { raised }),
  state: (id) => api.get(`/online-classes/${id}/state`),

  // Teaching tools (Phase 2)
  setStage: (id, data) => api.post(`/online-classes/${id}/stage`, data),
  resources: (id, params) => api.get(`/online-classes/${id}/resources`, { params }),
  present: (id, data) => api.post(`/online-classes/${id}/present`, data),
  presentPage: (id, data) => api.post(`/online-classes/${id}/page`, data),
  conversionStatus: (id, documentId) =>
    api.get(`/online-classes/${id}/resources/${documentId}/status`),
  resourceToken: (id) => api.get(`/online-classes/${id}/resource-token`),
  share: (id, data) => api.post(`/online-classes/${id}/share`, data),
  video: (id, data) => api.post(`/online-classes/${id}/video`, data),
  saveBoardSnapshot: (id, data) => api.post(`/online-classes/${id}/whiteboard/snapshot`, data),
  boardSnapshot: (id) => api.get(`/online-classes/${id}/whiteboard/snapshot`),
  saveWhiteboard: (id, data) => api.post(`/online-classes/${id}/whiteboard/save`, data),
  whiteboards: (id) => api.get(`/online-classes/${id}/whiteboard`),

  // Recording (Phase 3)
  startRecording: (id) => api.post(`/online-classes/${id}/recording/start`),
  stopRecording: (id) => api.post(`/online-classes/${id}/recording/stop`),
  recordings: () => api.get('/online-classes/recordings'),
  recordingToken: (recordingId) => api.get(`/online-classes/recordings/${recordingId}/token`),

  // Scheduling (Phase 3)
  schedules: () => api.get('/online-classes/schedules'),
  createSchedule: (data) => api.post('/online-classes/schedules', data),
  deleteSchedule: (id) => api.delete(`/online-classes/schedules/${id}`),
  upcoming: () => api.get('/online-classes/upcoming'),
  startScheduled: (sessionId) => api.post(`/online-classes/schedules/${sessionId}/start`),

  // Lesson record + AI (Phase 4). AI calls take longer than a classroom action,
  // so they get their own timeout; none of them are required for a class to run.
  lessonRecord: (id) => api.get(`/online-classes/${id}/lesson-record`),
  saveLessonRecord: (id, data) => api.put(`/online-classes/${id}/lesson-record`, data),
  lessonPlans: (id) => api.get(`/online-classes/${id}/lesson-plans`),
  linkLessonPlan: (id, data) => api.post(`/online-classes/${id}/lesson-plan`, data),
  summary: (id) => api.get(`/online-classes/${id}/summary`),
  generateSummary: (id) => api.post(`/online-classes/${id}/ai/summary`, {}, { timeout: 180000 }),
  coverage: (id) => api.post(`/online-classes/${id}/ai/coverage`, {}, { timeout: 180000 }),
  revisionNotes: (id) => api.post(`/online-classes/${id}/ai/revision-notes`, {}, { timeout: 180000 }),
  ask: (id, question) => api.post(`/online-classes/${id}/ask`, { question }, { timeout: 180000 }),
  askHistory: (id) => api.get(`/online-classes/${id}/ask/history`),
  assistant: (id, data) => api.post(`/online-classes/${id}/ai/assistant`, data, { timeout: 180000 }),
  publishHomework: (id, data) => api.post(`/online-classes/${id}/homework/publish`, data),
};

// ─── ADMIN — LIVE CLASSES CONTROL ROOM ────────────────────────────────────────
export const liveClassAdminAPI = {
  overview: () => api.get('/admin/live-classes'),
  history: (params) => api.get('/admin/live-classes/history', { params }),
  detail: (id) => api.get(`/admin/live-classes/${id}`),
  observe: (id) => api.post(`/admin/live-classes/${id}/observe`),
  forceEnd: (id) => api.post(`/admin/live-classes/${id}/end`),
  logs: (params) => api.get('/admin/live-classes-logs', { params }),
  report: (params) => api.get('/admin/online-classes/report', { params }),
  getSettings: () => api.get('/admin/online-classes/settings'),
  updateSettings: (data) => api.put('/admin/online-classes/settings', data),
  aiUsage: (params) => api.get('/admin/online-classes/ai-usage', { params }),
  health: () => api.get('/admin/online-classes/health'),
};

// ─── NOTIFICATIONS ────────────────────────────────────────────────────────────
export const notificationAPI = {
  getAll: () => api.get('/notifications'),
  markRead: (id) => api.put(`/notifications/${id}/read`),
};

// ─── ERP ──────────────────────────────────────────────────────────────────────
// Phase 1: setup, masters, people, access and settings. Every call is gated
// server-side by the `erp` feature flag, so these are safe to reference even
// while the module is switched off.
export const erpAPI = {
  status: () => api.get('/erp/status'),
  dashboard: () => api.get('/erp/dashboard'),

  // Setup
  analyze: () => api.get('/erp/setup/analyze'),
  runSetup: () => api.post('/erp/setup/run', {}, { timeout: 300000 }),
  allocateGrNumbers: () => api.post('/erp/setup/allocate-gr-numbers', {}, { timeout: 120000 }),
  allocateEmployeeNumbers: () => api.post('/erp/setup/allocate-employee-numbers', {}, { timeout: 120000 }),

  // Masters
  sessions: () => api.get('/erp/sessions'),
  createSession: (data) => api.post('/erp/sessions', data),
  makeSessionCurrent: (id) => api.post(`/erp/sessions/${id}/make-current`),
  classes: () => api.get('/erp/classes'),
  subjects: () => api.get('/erp/subjects'),

  // People
  students: (params) => api.get('/erp/students', { params }),
  student: (id) => api.get(`/erp/students/${id}`),
  updateStudent: (id, data) => api.put(`/erp/students/${id}`, data),
  staff: (params) => api.get('/erp/staff', { params }),
  updateStaff: (id, data) => api.put(`/erp/staff/${id}`, data),

  // Access
  roles: () => api.get('/erp/access/roles'),
  people: () => api.get('/erp/access/people'),
  grantRole: (data) => api.post('/erp/access/grant', data),
  revokeRole: (data) => api.post('/erp/access/revoke', data),

  // Settings
  numbering: () => api.get('/erp/settings/numbering'),
  updateNumbering: (scope, data) => api.put(`/erp/settings/numbering/${scope}`, data),
  flags: () => api.get('/erp/settings/flags'),
  updateFlag: (key, data) => api.put(`/erp/settings/flags/${key}`, data),

  audit: (params) => api.get('/erp/audit', { params }),

  // Admissions & families (phase 2)
  admissions: (params) => api.get('/erp/admissions', { params }),
  createAdmission: (data) => api.post('/erp/admissions', data),
  updateAdmission: (id, data) => api.put(`/erp/admissions/${id}`, data),
  confirmAdmission: (id) => api.post(`/erp/admissions/${id}/confirm`, {}, { timeout: 60000 }),
  rejectAdmission: (id, reason) => api.post(`/erp/admissions/${id}/reject`, { reason }),
  suggestFamilies: (data) => api.post('/erp/families/suggest', data),
  families: (params) => api.get('/erp/families', { params }),
  family: (id) => api.get(`/erp/families/${id}`),
  createFamily: (data) => api.post('/erp/families', data),
  linkChild: (familyId, studentId) => api.post(`/erp/families/${familyId}/add-child/${studentId}`),

  // Attendance (phase 3)
  attendanceClasses: () => api.get('/erp/attendance/my-classes'),
  attendanceRoster: (params) => api.get('/erp/attendance/roster', { params }),
  saveAttendance: (data) => api.post('/erp/attendance/save', data),
  attendanceMissing: (params) => api.get('/erp/attendance/missing', { params }),
  attendanceClassReport: (params) => api.get('/erp/attendance/report/class', { params }),
  attendanceStudentReport: (id, params) => api.get(`/erp/attendance/report/student/${id}`, { params }),

  // Fees (phase 4)
  feeHeads: () => api.get('/erp/fees/heads'),
  createFeeHead: (data) => api.post('/erp/fees/heads', data),
  updateFeeHead: (id, data) => api.put(`/erp/fees/heads/${id}`, data),
  feeStructure: () => api.get('/erp/fees/structure'),
  saveFeeStructure: (data) => api.put('/erp/fees/structure', data),
  applyFeeIncrease: (data) => api.post('/erp/fees/structure/increase', data),
  concessions: (params) => api.get('/erp/fees/concessions', { params }),
  createConcession: (data) => api.post('/erp/fees/concessions', data),
  endConcession: (id) => api.delete(`/erp/fees/concessions/${id}`),
  generateVouchers: (data) => api.post('/erp/fees/vouchers/generate', data, { timeout: 300000 }),
  vouchers: (params) => api.get('/erp/fees/vouchers', { params }),
  voucher: (id) => api.get(`/erp/fees/vouchers/${id}`),
  cancelVoucher: (id, reason) => api.post(`/erp/fees/vouchers/${id}/cancel`, { reason }),
  receivePayment: (data) => api.post('/erp/fees/payments', data),
  reversePayment: (id, reason) => api.post(`/erp/fees/payments/${id}/reverse`, { reason }),
  payments: (params) => api.get('/erp/fees/payments', { params }),
  feeLedger: (id) => api.get(`/erp/fees/ledger/${id}`),
  defaulters: (params) => api.get('/erp/fees/defaulters', { params }),
  feeSummary: (params) => api.get('/erp/fees/summary', { params }),
  feeSearchStudent: (params) => api.get('/erp/fees/search-student', { params }),
};

export default api;
