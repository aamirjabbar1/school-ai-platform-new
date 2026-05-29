import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { assignmentAPI } from '../../services/api';
import Markdown from '../../components/Markdown';
import { BookOpen, Loader2, X, CheckCircle, Clock, FileText, Award, Download, Send } from 'lucide-react';

// Submission files are stored on disk and served by the API at /uploads/...
const fileUrl = (p) => {
  if (!p) return null;
  const idx = p.indexOf('/uploads/');
  return idx >= 0 ? p.slice(idx) : null;
};

const counts = (a) => {
  const subs = a.submissions || [];
  return {
    total: subs.length,
    review: subs.filter((s) => s.status === 'submitted').length,
    graded: subs.filter((s) => s.status === 'graded').length,
  };
};

export default function TeacherAssignments() {
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [gradeInputs, setGradeInputs] = useState({});
  const [savingId, setSavingId] = useState(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const load = async () => {
    const { data } = await assignmentAPI.getAll();
    setAssignments(data);
    setSelected((sel) => (sel ? data.find((a) => a.id === sel.id) || null : null));
    return data;
  };

  useEffect(() => { load().finally(() => setLoading(false)); }, []);

  const openAssignment = (a) => {
    setSelected(a);
    const inputs = {};
    (a.submissions || []).forEach((s) => {
      inputs[s.id] = { grade: s.grade ?? '', feedback: s.feedback ?? '' };
    });
    setGradeInputs(inputs);
    setError('');
  };

  const setInput = (subId, k, v) =>
    setGradeInputs((g) => ({ ...g, [subId]: { ...g[subId], [k]: v } }));

  const saveGrade = async (sub) => {
    const input = gradeInputs[sub.id] || {};
    if (input.grade === '' || input.grade === null || input.grade === undefined) {
      setError('Enter a grade before saving');
      return;
    }
    setSavingId(sub.id);
    setError('');
    try {
      await assignmentAPI.grade({
        submission_id: sub.id,
        grade: parseFloat(input.grade),
        feedback: input.feedback || '',
      });
      setSuccess(`Grade saved for ${sub.student_name}`);
      await load();
      setTimeout(() => setSuccess(''), 2500);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to save grade');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <Layout title="Assignments">
      {success && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm flex items-center gap-2">
          <CheckCircle size={16} /> {success}
        </div>
      )}

      <div className="mb-5">
        <h2 className="font-semibold text-gray-800">Your Assignments</h2>
        <p className="text-sm text-gray-500">Review student submissions and grade them.</p>
      </div>

      {loading ? (
        <div className="grid gap-3">{[1, 2, 3].map((i) => <div key={i} className="h-24 bg-gray-100 rounded-xl animate-pulse" />)}</div>
      ) : assignments.length === 0 ? (
        <div className="card text-center py-12">
          <BookOpen size={40} className="mx-auto mb-3 text-gray-300" />
          <p className="text-gray-500">No assignments yet</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {assignments.map((a) => {
            const c = counts(a);
            return (
              <div key={a.id} className="card hover:shadow-md transition-shadow">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-gray-800">{a.title}</h3>
                      <span className="badge-blue capitalize">{a.assignment_type}</span>
                      {c.review > 0 && <span className="badge-yellow">{c.review} to review</span>}
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {a.subject} • {a.class_name} • {a.max_marks} marks
                      {a.due_date && ` • Due ${new Date(a.due_date).toLocaleDateString()}`}
                    </p>
                    <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
                      <span className="flex items-center gap-1"><FileText size={12} /> {c.total} submitted</span>
                      <span className="flex items-center gap-1 text-green-600"><CheckCircle size={12} /> {c.graded} graded</span>
                      {c.review > 0 && <span className="flex items-center gap-1 text-yellow-600"><Clock size={12} /> {c.review} pending</span>}
                    </div>
                  </div>
                  <button onClick={() => openAssignment(a)} className="btn-primary text-sm shrink-0">
                    Review ({c.total})
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Submissions / grading modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-3xl my-4">
            <div className="p-5 border-b flex items-start justify-between">
              <div>
                <h2 className="font-bold text-gray-900">{selected.title}</h2>
                <p className="text-sm text-gray-500">{selected.subject} • {selected.class_name} • {selected.max_marks} marks</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 p-1"><X size={20} /></button>
            </div>

            <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
              {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>}

              {/* Assignment brief */}
              {selected.description && (
                <details className="p-3 bg-blue-50 rounded-lg border border-blue-100 text-sm text-gray-800" open>
                  <summary className="cursor-pointer font-semibold text-gray-700 mb-1">Assignment brief</summary>
                  <div className="mt-2">
                    <Markdown>{selected.description}</Markdown>
                    {selected.instructions && (
                      <p className="mt-2 pt-2 border-t border-blue-100 text-gray-600">
                        <span className="font-semibold">Instructions:</span> {selected.instructions}
                      </p>
                    )}
                  </div>
                </details>
              )}

              <h3 className="text-sm font-semibold text-gray-700">Submissions</h3>

              {(selected.submissions || []).length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <FileText size={32} className="mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No submissions yet</p>
                </div>
              ) : (
                (selected.submissions || []).map((s) => {
                  const url = fileUrl(s.file_path);
                  const input = gradeInputs[s.id] || { grade: '', feedback: '' };
                  return (
                    <div key={s.id} className="border border-gray-200 rounded-xl p-4">
                      <div className="flex items-center gap-2 flex-wrap mb-2">
                        <span className="font-semibold text-gray-800 text-sm">{s.student_name}</span>
                        <span className={s.status === 'graded' ? 'badge-green' : 'badge-blue'}>{s.status}</span>
                        {s.submitted_at && <span className="text-xs text-gray-400">{new Date(s.submitted_at).toLocaleString()}</span>}
                        {s.status === 'graded' && <span className="badge-purple ml-auto"><Award size={10} className="mr-1" /> {s.grade}/{selected.max_marks}</span>}
                      </div>

                      {s.content && (
                        <div className="text-sm text-gray-700 bg-gray-50 rounded-lg p-3 whitespace-pre-wrap max-h-60 overflow-y-auto">{s.content}</div>
                      )}
                      {url && (
                        <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:underline mt-2">
                          <Download size={13} /> {s.file_name || 'Attached file'}
                        </a>
                      )}
                      {!s.content && !url && <p className="text-xs text-gray-400 italic">No answer text or file submitted.</p>}

                      {/* Grading */}
                      <div className="mt-3 pt-3 border-t border-gray-100 grid sm:grid-cols-[120px_1fr_auto] gap-2 items-end">
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">Grade (/{selected.max_marks})</label>
                          <input
                            type="number" min="0" max={selected.max_marks}
                            value={input.grade}
                            onChange={(e) => setInput(s.id, 'grade', e.target.value)}
                            className="input-field"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">Feedback</label>
                          <input
                            type="text"
                            value={input.feedback}
                            onChange={(e) => setInput(s.id, 'feedback', e.target.value)}
                            className="input-field"
                            placeholder="Optional feedback for the student"
                          />
                        </div>
                        <button
                          onClick={() => saveGrade(s)}
                          disabled={savingId === s.id}
                          className="btn-primary flex items-center justify-center gap-1.5 h-[38px]"
                        >
                          {savingId === s.id ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                          {s.status === 'graded' ? 'Update' : 'Save'}
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
