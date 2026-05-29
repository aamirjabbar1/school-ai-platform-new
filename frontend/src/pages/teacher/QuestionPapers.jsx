import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { questionPaperAPI } from '../../services/api';
import { FileText, Wand2, Loader2, Eye, Trash2, Globe, EyeOff, Plus, X, CheckCircle, ChevronDown, ChevronUp, Download, Sparkles, Lightbulb, TrendingUp } from 'lucide-react';

const SUBJECTS = ['Mathematics', 'Science', 'English', 'Urdu', 'Islamiat', 'Computer Science', 'Physics', 'Chemistry', 'Biology'];
const CLASSES = ['Class 1','Class 2','Class 3','Class 4','Class 5','Class 6','Class 7','Class 8','Class 9','Class 10','Class 11','Class 12'];
const PAPER_TYPES = ['monthly_test', 'mid_term', 'final_exam', 'quiz', 'class_test'];
const IMPORTANCE_BADGE = { high: 'badge-red', medium: 'badge-yellow', low: 'badge-gray' };

export default function QuestionPapers() {
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showGenerator, setShowGenerator] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [viewPaper, setViewPaper] = useState(null);
  const [expandedAnswers, setExpandedAnswers] = useState({});

  // Important-question prediction
  const [showPredict, setShowPredict] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [predictForm, setPredictForm] = useState({ subject: '', class_name: '' });
  const [predictions, setPredictions] = useState(null);

  const [genForm, setGenForm] = useState({
    subject: '', class_name: '', paper_type: 'class_test',
    total_marks: 100, duration_minutes: 60, topics: '',
    generation_mode: 'standard', use_past_papers: true,
    difficulty_distribution: { easy: 30, medium: 50, hard: 20 },
  });

  useEffect(() => {
    questionPaperAPI.getAll().then(({ data }) => setPapers(data)).finally(() => setLoading(false));
  }, []);

  const setGen = (k, v) => setGenForm((f) => ({ ...f, [k]: v }));

  const generate = async () => {
    if (!genForm.subject || !genForm.class_name) {
      setError('Subject and class are required');
      return;
    }
    setGenerating(true);
    setError('');
    try {
      const { data } = await questionPaperAPI.generate({
        ...genForm,
        topics: genForm.topics ? genForm.topics.split(',').map((t) => t.trim()) : [],
      });
      setPapers((prev) => [data.paper, ...prev]);
      setShowGenerator(false);
      setGenForm({ subject: '', class_name: '', paper_type: 'class_test', total_marks: 100, duration_minutes: 60, topics: '', generation_mode: 'standard', use_past_papers: true, difficulty_distribution: { easy: 30, medium: 50, hard: 20 } });
    } catch (e) {
      setError(e.response?.data?.detail || e.response?.data?.error || 'Failed to generate paper. Ensure relevant books/papers are uploaded.');
    } finally {
      setGenerating(false);
    }
  };

  const runPrediction = async () => {
    if (!predictForm.subject || !predictForm.class_name) {
      setError('Subject and class are required');
      return;
    }
    setPredicting(true);
    setError('');
    setPredictions(null);
    try {
      const { data } = await questionPaperAPI.predictImportant(predictForm);
      setPredictions(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Prediction failed. Upload past papers for this subject and class first.');
    } finally {
      setPredicting(false);
    }
  };

  const togglePublish = async (id) => {
    try {
      const { data } = await questionPaperAPI.togglePublish(id);
      setPapers((prev) => prev.map((p) => p.id === id ? data.paper : p));
    } catch (e) {
      console.error(e);
    }
  };

  const deletePaper = async (id) => {
    if (!confirm('Delete this question paper?')) return;
    await questionPaperAPI.delete(id);
    setPapers((prev) => prev.filter((p) => p.id !== id));
  };

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
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="font-semibold text-gray-800">Question Papers</h2>
          <p className="text-sm text-gray-500">Generate AI-powered exam papers from your curriculum</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { setShowPredict(true); setPredictions(null); }} className="btn-secondary flex items-center gap-2">
            <Lightbulb size={16} /> Predict Important Questions
          </button>
          <button onClick={() => setShowGenerator(true)} className="btn-primary flex items-center gap-2">
            <Wand2 size={16} /> Generate Paper
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-red-700 text-sm">
          <X size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {loading ? (
        <div className="grid gap-3">{[1,2,3].map((i) => <div key={i} className="h-20 bg-gray-100 rounded-xl animate-pulse" />)}</div>
      ) : papers.length === 0 ? (
        <div className="card text-center py-12">
          <FileText size={40} className="mx-auto mb-3 text-gray-300" />
          <p className="text-gray-500">No question papers yet</p>
          <button onClick={() => setShowGenerator(true)} className="btn-primary mt-3 inline-flex items-center gap-2">
            <Wand2 size={16} /> Generate First Paper
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {papers.map((p) => (
            <div key={p.id} className="card hover:shadow-md transition-shadow">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-gray-800 text-sm">{p.title}</h3>
                    <span className={p.is_published ? 'badge-green' : 'badge-gray'}>
                      {p.is_published ? 'Published' : 'Draft'}
                    </span>
                    <span className="badge-blue capitalize">{p.paper_type?.replace('_', ' ')}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {p.subject} • {p.class_name} • {p.total_marks} marks • {p.duration_minutes} min
                    {p.questions?.length > 0 && ` • ${p.questions.length} questions`}
                  </p>
                  <p className="text-xs text-gray-400">{new Date(p.created_at).toLocaleDateString()}</p>
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
                    title="Download PDF (with answer key)"
                  >
                    <Download size={16} />
                  </button>
                  <button
                    onClick={() => togglePublish(p.id)}
                    className={`p-1.5 rounded-lg hover:bg-gray-100 ${p.is_published ? 'text-green-600' : 'text-gray-400 hover:text-green-600'}`}
                    title={p.is_published ? 'Unpublish' : 'Publish to students'}
                  >
                    {p.is_published ? <Globe size={16} /> : <EyeOff size={16} />}
                  </button>
                  <button
                    onClick={() => deletePaper(p.id)}
                    className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-red-600"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Generator Modal */}
      {showGenerator && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg my-4">
            <div className="p-5 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Wand2 size={18} className="text-blue-600" />
                <h2 className="font-bold text-gray-900">Generate Question Paper</h2>
              </div>
              <button onClick={() => setShowGenerator(false)} className="text-gray-400 hover:text-gray-600">
                <X size={20} />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subject *</label>
                  <select value={genForm.subject} onChange={(e) => setGen('subject', e.target.value)} className="input-field">
                    <option value="">Select</option>
                    {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Class *</label>
                  <select value={genForm.class_name} onChange={(e) => setGen('class_name', e.target.value)} className="input-field">
                    <option value="">Select</option>
                    {CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Paper Type</label>
                  <select value={genForm.paper_type} onChange={(e) => setGen('paper_type', e.target.value)} className="input-field">
                    {PAPER_TYPES.map((t) => <option key={t} value={t} className="capitalize">{t.replace('_', ' ')}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Total Marks</label>
                  <input type="number" value={genForm.total_marks} onChange={(e) => setGen('total_marks', parseInt(e.target.value))} className="input-field" min="10" max="200" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Duration (min)</label>
                  <input type="number" value={genForm.duration_minutes} onChange={(e) => setGen('duration_minutes', parseInt(e.target.value))} className="input-field" min="15" max="180" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Focus Topics (comma-separated, optional)</label>
                <input type="text" value={genForm.topics} onChange={(e) => setGen('topics', e.target.value)} className="input-field" placeholder="e.g. Photosynthesis, Cell Division, Respiration" />
              </div>

              {/* Generation mode */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Generation Mode</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setGen('generation_mode', 'standard')}
                    className={`p-2.5 rounded-lg border text-left text-xs transition-all ${genForm.generation_mode === 'standard' ? 'border-blue-500 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}
                  >
                    <span className="font-semibold flex items-center gap-1"><Wand2 size={13} /> Standard</span>
                    <span className="block text-gray-500 mt-0.5">From the curriculum (textbooks).</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setGen('generation_mode', 'model')}
                    className={`p-2.5 rounded-lg border text-left text-xs transition-all ${genForm.generation_mode === 'model' ? 'border-purple-500 bg-purple-50 text-purple-800' : 'border-gray-200 text-gray-600 hover:border-gray-300'}`}
                  >
                    <span className="font-semibold flex items-center gap-1"><Sparkles size={13} /> Model Paper</span>
                    <span className="block text-gray-500 mt-0.5">Mirrors uploaded past papers.</span>
                  </button>
                </div>
                {genForm.generation_mode === 'standard' && (
                  <label className="flex items-center gap-2 mt-2 text-xs text-gray-600">
                    <input type="checkbox" checked={genForm.use_past_papers} onChange={(e) => setGen('use_past_papers', e.target.checked)} />
                    Use uploaded past papers as a style &amp; difficulty reference
                  </label>
                )}
              </div>

              <div className="p-3 bg-amber-50 rounded-lg text-xs text-amber-700 border border-amber-200">
                ⚠️ Ensure relevant books/materials for this subject and class are uploaded in the Knowledge Base before generating.
                {genForm.generation_mode === 'model' && ' Model Paper mode requires past papers (document type: Question Paper) for this subject and class.'}
              </div>
              <div className="flex gap-3">
                <button onClick={() => setShowGenerator(false)} className="btn-secondary flex-1">Cancel</button>
                <button onClick={generate} disabled={generating} className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {generating ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />}
                  {generating ? 'Generating...' : 'Generate'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* View Paper Modal */}
      {viewPaper && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-3xl my-4">
            <div className="p-5 border-b flex items-center justify-between">
              <div>
                <h2 className="font-bold text-gray-900">{viewPaper.title}</h2>
                <p className="text-sm text-gray-500">{viewPaper.total_marks} marks • {viewPaper.duration_minutes} min</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => downloadPdf(viewPaper)}
                  className="btn-secondary flex items-center gap-1.5 text-sm"
                  title="Download PDF (with answer key)"
                >
                  <Download size={14} /> PDF
                </button>
                <button onClick={() => setViewPaper(null)} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
              </div>
            </div>
            <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
              {viewPaper.questions?.length === 0 ? (
                <p className="text-gray-500 text-center py-4">No questions available</p>
              ) : (
                viewPaper.questions?.map((q, i) => (
                  <div key={i} className="border border-gray-200 rounded-lg p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1">
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
                      <span className={`badge shrink-0 ${q.difficulty === 'easy' ? 'badge-green' : q.difficulty === 'hard' ? 'badge-red' : 'badge-yellow'}`}>
                        {q.difficulty}
                      </span>
                    </div>
                    {/* Answer toggle */}
                    {viewPaper.answer_key?.[i] && (
                      <div className="mt-2">
                        <button
                          onClick={() => setExpandedAnswers((p) => ({ ...p, [i]: !p[i] }))}
                          className="text-xs text-blue-600 flex items-center gap-1"
                        >
                          {expandedAnswers[i] ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                          {expandedAnswers[i] ? 'Hide Answer' : 'Show Answer Key'}
                        </button>
                        {expandedAnswers[i] && (
                          <div className="mt-1 p-2 bg-green-50 rounded text-xs text-green-800">
                            <strong>Answer:</strong> {viewPaper.answer_key[i]?.correct_answer}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Predict Important Questions Modal */}
      {showPredict && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl my-4">
            <div className="p-5 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Lightbulb size={18} className="text-amber-500" />
                <h2 className="font-bold text-gray-900">Predict Important Questions</h2>
              </div>
              <button onClick={() => { setShowPredict(false); setPredictions(null); }} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-sm text-gray-500">The AI analyses all uploaded past papers for this subject and class to predict the questions most likely to appear.</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subject *</label>
                  <select value={predictForm.subject} onChange={(e) => setPredictForm((f) => ({ ...f, subject: e.target.value }))} className="input-field">
                    <option value="">Select</option>
                    {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Class *</label>
                  <select value={predictForm.class_name} onChange={(e) => setPredictForm((f) => ({ ...f, class_name: e.target.value }))} className="input-field">
                    <option value="">Select</option>
                    {CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <button onClick={runPrediction} disabled={predicting} className="btn-primary w-full flex items-center justify-center gap-2">
                {predicting ? <><Loader2 size={16} className="animate-spin" /> Analysing past papers…</> : <><TrendingUp size={16} /> Predict</>}
              </button>

              {predictions && (
                <div className="space-y-3 max-h-[55vh] overflow-y-auto pt-1">
                  {predictions.summary && (
                    <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">{predictions.summary}</div>
                  )}
                  {(predictions.predictions || []).length === 0 ? (
                    <p className="text-sm text-gray-500 text-center py-2">No predictions returned.</p>
                  ) : (
                    predictions.predictions.map((p, i) => (
                      <div key={i} className="border border-gray-200 rounded-lg p-3">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="badge-blue">{p.topic}</span>
                          <span className={IMPORTANCE_BADGE[p.importance] || 'badge-gray'}>{p.importance} priority</span>
                          {p.frequency && <span className="text-xs text-gray-400">{p.frequency}</span>}
                        </div>
                        <p className="text-sm font-medium text-gray-800">{p.question}</p>
                        {p.rationale && <p className="text-xs text-gray-500 mt-1">{p.rationale}</p>}
                      </div>
                    ))
                  )}
                  {predictions.sources?.length > 0 && (
                    <p className="text-xs text-gray-400">Based on: {predictions.sources.join(', ')}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
