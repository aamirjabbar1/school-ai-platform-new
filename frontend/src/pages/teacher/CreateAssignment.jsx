import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../../components/Layout';
import { assignmentAPI } from '../../services/api';
import { Loader2, Send, CheckCircle, X, Wand2 } from 'lucide-react';

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
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState(''); // '' | 'generating' | 'creating'
  const [aiGenerated, setAiGenerated] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const deriveTitle = (content) => {
    const lines = content.split('\n').filter((l) => l.trim());
    const titleLine = lines.find((l) => l.toLowerCase().includes('title:'));
    return titleLine ? titleLine.replace(/.*title:\s*/i, '').trim() : '';
  };

  // Step 1: draft the assignment from the topic INTO the editable fields for review.
  // This does NOT create/publish anything — the teacher reviews and edits first.
  const runGenerate = async () => {
    if (!form.subject || !form.class_name) {
      setError('Please select a subject and class first');
      return;
    }
    if (!aiTopic.trim()) {
      setError('Enter a topic to generate content');
      return;
    }
    setBusy(true);
    setPhase('generating');
    setError('');
    try {
      const { data } = await assignmentAPI.generateWithAI({
        topic: aiTopic.trim(),
        subject: form.subject,
        class_level: form.class_name,
        assignment_type: form.assignment_type,
      });
      const content = (data.content || '').trim();
      if (!content) throw new Error('No content was generated');
      setForm((f) => ({ ...f, title: f.title.trim() || deriveTitle(content) || aiTopic.trim(), description: content }));
      setAiGenerated(true);
    } catch (e) {
      setError(e.response?.data?.detail || e.response?.data?.error || 'Failed to generate content. Make sure relevant books are uploaded.');
    } finally {
      setBusy(false);
      setPhase('');
    }
  };

  // Step 2: create the (reviewed) assignment and publish it to students.
  const createAssignment = async () => {
    if (!form.subject || !form.class_name) {
      setError('Please select a subject and class');
      return;
    }
    if (!form.title.trim() || !form.description.trim()) {
      setError('Add a title and description — or enter a topic above to generate a draft');
      return;
    }
    setBusy(true);
    setPhase('creating');
    setError('');
    try {
      await assignmentAPI.create(form);
      setSuccess(true);
      setTimeout(() => navigate('/teacher/dashboard'), 2000);
    } catch (e) {
      setError(e.response?.data?.detail || e.response?.data?.error || 'Failed to create assignment');
    } finally {
      setBusy(false);
      setPhase('');
    }
  };

  // One button: with a topic and no content yet, generate a draft for review;
  // otherwise create the reviewed assignment.
  const willGenerate = !form.description.trim() && !!aiTopic.trim();

  const handleSubmit = (e) => {
    e.preventDefault();
    if (willGenerate) runGenerate();
    else createAssignment();
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
          <p className="text-xs text-blue-600 mb-3">
            Enter a topic and pick a subject &amp; class below, then click <strong>Generate with AI</strong>. The AI drafts the content into the fields below for you to <strong>review and edit</strong> — nothing is sent to students until you click <strong>Create Assignment</strong>. To write it yourself, just fill in the Description.
          </p>
          <input
            type="text"
            value={aiTopic}
            onChange={(e) => setAiTopic(e.target.value)}
            placeholder="Enter topic (e.g. Photosynthesis, Algebra Equations, Mughal Empire)"
            className="input-field w-full text-sm"
          />
          {aiGenerated && (
            <button type="button" onClick={runGenerate} disabled={busy} className="mt-2 text-xs text-blue-700 hover:underline flex items-center gap-1 disabled:opacity-50">
              <Wand2 size={12} /> Regenerate from this topic
            </button>
          )}
        </div>

        {aiGenerated && !success && (
          <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800 flex items-start gap-2">
            <CheckCircle size={16} className="shrink-0 mt-0.5" />
            <span>AI draft ready. <strong>Review and edit</strong> the title and content below, then click <strong>Create Assignment</strong> to publish to students.</span>
          </div>
        )}

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
            <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
            <input type="text" value={form.title} onChange={(e) => set('title', e.target.value)} className="input-field" placeholder="Leave blank to auto-generate from the topic" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description / Content</label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={10}
              className="input-field resize-none"
              placeholder="Leave blank to generate from the topic above, or write the assignment yourself..."
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
            <button type="button" onClick={() => navigate(-1)} disabled={busy} className="btn-secondary flex-1">
              Cancel
            </button>
            <button type="submit" disabled={busy} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {busy ? <Loader2 size={16} className="animate-spin" /> : (willGenerate ? <Wand2 size={16} /> : <Send size={16} />)}
              {busy
                ? (phase === 'generating' ? 'Generating draft…' : 'Creating…')
                : (willGenerate ? 'Generate with AI' : 'Create Assignment')}
            </button>
          </div>
        </form>
      </div>
    </Layout>
  );
}
