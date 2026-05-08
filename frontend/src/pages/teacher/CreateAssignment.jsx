import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import { assignmentAPI } from '../../services/api';
import { Bot, Loader2, Send, CheckCircle, X, Wand2 } from 'lucide-react';

const SUBJECTS = ['Mathematics', 'Science', 'English', 'Urdu', 'Islamiat', 'Computer Science', 'Social Studies', 'Physics', 'Chemistry', 'Biology'];
const CLASSES = ['Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6', 'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12'];
const TYPES = ['homework', 'quiz', 'project', 'research', 'classwork'];

export default function CreateAssignment() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: '', description: '', subject: '', class_name: '', due_date: '',
    assignment_type: 'homework', max_marks: 100, instructions: '',
  });
  const [aiTopic, setAiTopic] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const generateWithAI = async () => {
    if (!aiTopic || !form.subject || !form.class_name) {
      setError('Please select subject, class, and enter a topic before generating');
      return;
    }
    setAiLoading(true);
    setError('');
    try {
      const { data } = await assignmentAPI.generateWithAI({
        topic: aiTopic,
        subject: form.subject,
        class_level: form.class_name,
        assignment_type: form.assignment_type,
      });
      // Parse title from first line
      const lines = data.content.split('\n').filter((l) => l.trim());
      const titleLine = lines.find((l) => l.toLowerCase().includes('title:'));
      if (titleLine) {
        set('title', titleLine.replace(/.*title:\s*/i, '').trim());
      }
      set('description', data.content);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to generate content. Make sure relevant books are uploaded.');
    } finally {
      setAiLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.title || !form.description || !form.subject || !form.class_name) {
      setError('Please fill all required fields');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await assignmentAPI.create(form);
      setSuccess(true);
      setTimeout(() => navigate('/teacher/dashboard'), 2000);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to create assignment');
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <Layout title="Create Assignment">
        <div className="max-w-xl mx-auto card text-center py-12">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <CheckCircle size={32} className="text-green-600" />
          </div>
          <h2 className="text-xl font-bold text-gray-900">Assignment Created!</h2>
          <p className="text-gray-500 text-sm mt-2">Students have been notified. Redirecting...</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Create Assignment">
      <div className="max-w-3xl mx-auto space-y-5">
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-red-700 text-sm">
            <X size={16} className="shrink-0" /> {error}
          </div>
        )}

        {/* AI Generator */}
        <div className="card border-2 border-dashed border-blue-200 bg-blue-50/50">
          <div className="flex items-center gap-2 mb-3">
            <Wand2 size={18} className="text-blue-600" />
            <span className="font-semibold text-blue-800 text-sm">AI Assignment Generator</span>
          </div>
          <p className="text-xs text-blue-600 mb-3">Generate assignment content from your school's knowledge base</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={aiTopic}
              onChange={(e) => setAiTopic(e.target.value)}
              placeholder="Enter topic (e.g. Photosynthesis, Algebra Equations, Mughal Empire)"
              className="input-field flex-1 text-sm"
            />
            <button
              onClick={generateWithAI}
              disabled={aiLoading}
              className="btn-primary flex items-center gap-2 whitespace-nowrap"
            >
              {aiLoading ? <Loader2 size={16} className="animate-spin" /> : <Bot size={16} />}
              {aiLoading ? 'Generating...' : 'Generate'}
            </button>
          </div>
        </div>

        {/* Assignment Form */}
        <form onSubmit={handleSubmit} className="card space-y-4">
          <h3 className="font-semibold text-gray-800">Assignment Details</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Subject *</label>
              <select value={form.subject} onChange={(e) => set('subject', e.target.value)} className="input-field" required>
                <option value="">Select subject</option>
                {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Class *</label>
              <select value={form.class_name} onChange={(e) => set('class_name', e.target.value)} className="input-field" required>
                <option value="">Select class</option>
                {CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
              <select value={form.assignment_type} onChange={(e) => set('assignment_type', e.target.value)} className="input-field capitalize">
                {TYPES.map((t) => <option key={t} value={t} className="capitalize">{t}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Max Marks</label>
              <input type="number" value={form.max_marks} onChange={(e) => set('max_marks', e.target.value)} className="input-field" min="1" max="1000" />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Title *</label>
            <input type="text" value={form.title} onChange={(e) => set('title', e.target.value)} className="input-field" placeholder="Assignment title" required />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description / Content *</label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={10}
              className="input-field resize-none"
              placeholder="Describe the assignment..."
              required
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Due Date</label>
              <input type="date" value={form.due_date} onChange={(e) => set('due_date', e.target.value)} className="input-field" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Additional Instructions</label>
              <input type="text" value={form.instructions} onChange={(e) => set('instructions', e.target.value)} className="input-field" placeholder="Optional instructions" />
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={() => navigate(-1)} className="btn-secondary flex-1">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              Create Assignment
            </button>
          </div>
        </form>
      </div>
    </Layout>
  );
}
