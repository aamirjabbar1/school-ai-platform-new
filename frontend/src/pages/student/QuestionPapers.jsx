import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { questionPaperAPI } from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { FileText, Eye, Download, X, Clock, Award } from 'lucide-react';

export default function StudentQuestionPapers() {
  const { user } = useAuth();
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewPaper, setViewPaper] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    questionPaperAPI.getAll()
      .then(({ data }) => setPapers(data))
      .catch((e) => setError(e.response?.data?.detail || 'Failed to load papers'))
      .finally(() => setLoading(false));
  }, []);

  const downloadPdf = async (paper) => {
    try {
      const { data } = await questionPaperAPI.downloadPdf(paper.id);
      const url = window.URL.createObjectURL(new Blob([data], { type: 'application/pdf' }));
      const link = document.createElement('a');
      link.href = url;
      const safe = (paper.title || 'paper').replace(/[^a-z0-9_-]+/gi, '_');
      link.setAttribute('download', `${safe}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      setError('Failed to download PDF');
    }
  };

  return (
    <Layout title="Question Papers">
      <div className="mb-5">
        <h2 className="font-semibold text-gray-800">Question Papers</h2>
        <p className="text-sm text-gray-500">
          Papers published by your teachers for {user?.class_name || 'your class'}
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
          <X size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {loading ? (
        <div className="grid gap-3">{[1, 2, 3].map((i) => <div key={i} className="h-24 bg-gray-100 rounded-xl animate-pulse" />)}</div>
      ) : papers.length === 0 ? (
        <div className="card text-center py-12">
          <FileText size={40} className="mx-auto mb-3 text-gray-300" />
          <p className="text-gray-500">No question papers available yet</p>
          <p className="text-xs text-gray-400 mt-1">Your teachers haven't published any papers for {user?.class_name || 'your class'} yet.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {papers.map((p) => (
            <div key={p.id} className="card hover:shadow-md transition-shadow">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-gray-800 text-sm">{p.title}</h3>
                    <span className="badge-blue capitalize">{p.paper_type?.replace('_', ' ')}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {p.subject} • {p.class_name} • {p.questions?.length || 0} questions
                  </p>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
                    <span className="flex items-center gap-1"><Award size={12} /> {p.total_marks} marks</span>
                    <span className="flex items-center gap-1"><Clock size={12} /> {p.duration_minutes} min</span>
                    <span className="text-gray-400">{new Date(p.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => setViewPaper(p)}
                    className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-blue-600"
                    title="View paper"
                  >
                    <Eye size={16} />
                  </button>
                  <button
                    onClick={() => downloadPdf(p)}
                    className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-indigo-600"
                    title="Download PDF"
                  >
                    <Download size={16} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* View Paper Modal — questions only, no answer key for students */}
      {viewPaper && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-3xl my-4">
            <div className="p-5 border-b flex items-center justify-between">
              <div>
                <h2 className="font-bold text-gray-900">{viewPaper.title}</h2>
                <p className="text-sm text-gray-500">
                  {viewPaper.subject} • {viewPaper.total_marks} marks • {viewPaper.duration_minutes} min
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => downloadPdf(viewPaper)}
                  className="btn-secondary flex items-center gap-1.5 text-sm"
                >
                  <Download size={14} /> PDF
                </button>
                <button onClick={() => setViewPaper(null)} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
              </div>
            </div>
            <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
              {viewPaper.instructions && (
                <div className="p-3 bg-gray-50 rounded-lg text-sm text-gray-700 border border-gray-200">
                  <strong className="text-gray-800">Instructions:</strong> {viewPaper.instructions}
                </div>
              )}
              {viewPaper.questions?.length === 0 ? (
                <p className="text-gray-500 text-center py-4">No questions available</p>
              ) : (
                viewPaper.questions?.map((q, i) => (
                  <div key={i} className="border border-gray-200 rounded-lg p-3">
                    <p className="text-sm font-medium text-gray-800">
                      Q{q.number}. {q.question}
                      <span className="ml-2 text-xs text-gray-400">({q.marks} marks)</span>
                    </p>
                    {q.options && (
                      <div className="mt-2 space-y-1">
                        {q.options.map((opt, j) => (
                          <p key={j} className="text-xs text-gray-600 ml-3">{opt}</p>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
