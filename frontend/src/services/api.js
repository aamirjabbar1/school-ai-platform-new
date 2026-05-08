import axios from 'axios';

const API_BASE = '/api';

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
};

// ─── CHAT ─────────────────────────────────────────────────────────────────────
export const chatAPI = {
  // Returns EventSource for SSE streaming
  sendMessage: (data) => {
    const token = localStorage.getItem('token');
    return fetch(`${API_BASE}/chat/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
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
  generateWithAI: (data) => api.post('/assignments/ai-generate', data),
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
  upload: (formData) => api.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  reingest: (id) => api.post(`/documents/${id}/reingest`),
  delete: (id) => api.delete(`/documents/${id}`),
};

// ─── QUESTION PAPERS ──────────────────────────────────────────────────────────
export const questionPaperAPI = {
  getAll: (params) => api.get('/question-papers', { params }),
  getOne: (id) => api.get(`/question-papers/${id}`),
  generate: (data) => api.post('/question-papers/generate', data),
  create: (data) => api.post('/question-papers', data),
  togglePublish: (id) => api.put(`/question-papers/${id}/publish`),
  delete: (id) => api.delete(`/question-papers/${id}`),
};

// ─── ADMIN ────────────────────────────────────────────────────────────────────
export const adminAPI = {
  getDashboard: () => api.get('/admin/dashboard'),
  getUsers: (params) => api.get('/admin/users', { params }),
  createUser: (data) => api.post('/admin/users', data),
  bulkCreateUsers: (data) => api.post('/admin/users/bulk', data),
  updateUser: (id, data) => api.put(`/admin/users/${id}`, data),
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
};

// ─── NOTIFICATIONS ────────────────────────────────────────────────────────────
export const notificationAPI = {
  getAll: () => api.get('/notifications'),
  markRead: (id) => api.put(`/notifications/${id}/read`),
};

export default api;
