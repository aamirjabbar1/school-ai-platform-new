import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { assignmentAPI } from '../../services/api';
import Markdown from '../../components/Markdown';
import { BookOpen, Send, Loader2, Upload, CheckCircle, Clock, X, Eye } from 'lucide-react';

const STATUS_BADGE = {
  graded: 'badge-green',
  submitted: 'badge-blue',
  draft: 'badge-gray',
};

export default function StudentAssignments() {
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitForm, setSubmitForm] = useState({ content: '', file: null });
  const [activeTab, setActiveTab] = useState('all');
  const [successMsg, setSuccessMsg] = useState('');

  useEffect(() => {
    assignmentAPI.getAll().then(({ data }) => setAssignments(data))
      .finally(() => setLoading(false));
  }, []);

  const filtered = assignments.filter((a) => {
    if (activeTab === 'pending') return !a.my_submission || a.my_submission.status === 'draft';
    if (activeTab === 'submitted') return a.my_submission?.status === 'submitted';
    if (activeTab === 'graded') return a.my_submission?.status === 'graded';
    return true;
  });

  const handleSubmit = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      await assignmentAPI.submit(selected.id, {
        content: submitForm.content,
        file: submitForm.file,
        ai_generated: false,
      });
      setSuccessMsg('Assignment submitted successfully!');
      setSelected(null);
      setSubmitForm({ content: '', file: null });
      const { data } = await assignmentAPI.getAll();
      setAssignments(data);
      setTimeout(() => setSuccessMsg(''), 3000);
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout title="My Assignments">
      {successMsg && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2 text-green-700">
          <CheckCircle size={18} /> {successMsg}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-gray-100 rounded-lg mb-4 w-fit">
        {['all', 'pending', 'submitted', 'graded'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize
              ${activeTab === tab ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600 hover:text-gray-800'}`}
          >
            {tab}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="grid gap-4">
          {[1,2,3].map((i) => <div key={i} className="h-24 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-12">
          <BookOpen size={40} className="mx-auto mb-3 text-gray-300" />
          <p className="text-gray-500">No assignments found</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {filtered.map((a) => {
            const status = a.my_submission?.status;
            const isOverdue = a.due_date && new Date(a.due_date) < new Date() && !status;
            return (
              <div key={a.id} className="card hover:shadow-md transition-shadow">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-gray-800">{a.title}</h3>
                      <span className={STATUS_BADGE[status] || (isOverdue ? 'badge-red' : 'badge-yellow')}>
                        {status || (isOverdue ? 'Overdue' : 'Pending')}
                      </span>
                    </div>
                    <p className="text-sm text-gray-500 mt-0.5">
                      {a.subject} • {a.assignment_type} • {a.max_marks} marks
                      {a.due_date && ` • Due: ${new Date(a.due_date).toLocaleDateString()}`}
                    </p>
                    <p className="text-sm text-gray-600 mt-1 line-clamp-2">{a.description}</p>
                    {status === 'graded' && (
                      <div className="mt-2 p-2 bg-green-50 rounded-lg">
                        <span className="text-green-700 text-sm font-medium">
                          Grade: {a.my_submission.grade}/{a.max_marks}
                        </span>
                        {a.my_submission.feedback && (
                          <p className="text-xs text-green-600 mt-0.5">Feedback: {a.my_submission.feedback}</p>
                        )}
                      </div>
                    )}
                  </div>
                  {status !== 'graded' && (
                    <button
                      onClick={() => { setSelected(a); setSubmitForm({ content: a.my_submission?.content || '', file: null }); }}
                      className={status === 'submitted' ? 'btn-secondary text-sm' : 'btn-primary text-sm'}
                    >
                      {status === 'submitted' ? <><Eye size={14} className="inline mr-1" />View</> : 'Submit'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Submission Modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl my-4">
            <div className="p-5 border-b border-gray-100 flex items-start justify-between">
              <div>
                <h2 className="font-bold text-gray-900">{selected.title}</h2>
                <p className="text-sm text-gray-500">{selected.subject} • {selected.max_marks} marks</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 p-1">
                <X size={20} />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="p-3 bg-blue-50 rounded-lg text-sm text-gray-800 border border-blue-100">
                <Markdown>{selected.description}</Markdown>
                {selected.instructions && (
                  <p className="mt-2 pt-2 border-t border-blue-100 text-gray-600">
                    <span className="font-semibold">Additional instructions:</span> {selected.instructions}
                  </p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Your Answer</label>
                <textarea
                  value={submitForm.content}
                  onChange={(e) => setSubmitForm({ ...submitForm, content: e.target.value })}
                  rows={10}
                  className="input-field resize-none"
                  placeholder="Write your answer here..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Attach File (optional)
                </label>
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png"
                  onChange={(e) => setSubmitForm({ ...submitForm, file: e.target.files[0] })}
                  className="w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-gray-200 file:text-sm file:bg-gray-50 hover:file:bg-gray-100"
                />
              </div>

              <div className="flex gap-3 pt-2">
                <button onClick={() => setSelected(null)} className="btn-secondary flex-1">
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={submitting || (!submitForm.content && !submitForm.file)}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                  Submit Assignment
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
