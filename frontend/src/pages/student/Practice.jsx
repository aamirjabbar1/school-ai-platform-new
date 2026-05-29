import { useState } from 'react';
import Layout from '../../components/Layout';
import { questionPaperAPI } from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import {
  Sparkles, Loader2, CheckCircle, XCircle, X, Award, RefreshCw, AlertCircle,
  TrendingDown,
} from 'lucide-react';

const SUBJECTS = ['Mathematics', 'Science', 'English', 'Urdu', 'Islamiat', 'Computer Science', 'Physics', 'Chemistry', 'Biology', 'Social Studies', 'History', 'Geography'];
const DIFFICULTIES = [
  { value: 'mixed', label: 'Mixed' },
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
];
const COUNTS = [5, 10, 15, 20];

export default function Practice() {
  const { user } = useAuth();
  const subjectOptions = (user?.subjects?.length ? user.subjects : SUBJECTS);

  const [stage, setStage] = useState('setup'); // 'setup' | 'taking' | 'result'
  const [form, setForm] = useState({ subject: subjectOptions[0] || '', topics: '', num_questions: 10, difficulty: 'mixed' });
  const [loading, setLoading] = useState(false);
  const [grading, setGrading] = useState(false);
  const [error, setError] = useState('');

  const [test, setTest] = useState(null);       // { title, questions, answer_key }
  const [answers, setAnswers] = useState({});    // { [number]: string }
  const [result, setResult] = useState(null);    // grading response

  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const startPractice = async () => {
    if (!form.subject) { setError('Please choose a subject'); return; }
    setLoading(true);
    setError('');
    try {
      const { data } = await questionPaperAPI.generatePractice({
        subject: form.subject,
        class_name: user?.class_name || 'All Classes',
        topics: form.topics ? form.topics.split(',').map((t) => t.trim()).filter(Boolean) : [],
        num_questions: Number(form.num_questions),
        difficulty: form.difficulty,
      });
      setTest(data);
      setAnswers({});
      setResult(null);
      setStage('taking');
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not generate a practice test. Make sure material for this subject is in the Knowledge Base.');
    } finally {
      setLoading(false);
    }
  };

  const submitForGrading = async () => {
    setGrading(true);
    setError('');
    try {
      const { data } = await questionPaperAPI.gradePractice({
        questions: test.questions,
        answer_key: test.answer_key,
        answers,
      });
      setResult(data);
      setStage('result');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      setError(e.response?.data?.detail || 'Grading failed. Please try again.');
    } finally {
      setGrading(false);
    }
  };

  const reset = () => {
    setStage('setup');
    setTest(null);
    setAnswers({});
    setResult(null);
    setError('');
  };

  const answeredCount = test ? test.questions.filter((q) => (answers[q.number] || '').trim()).length : 0;
  const keyByNum = (n) => (test?.answer_key || []).find((a) => a.number === n) || {};
  const resByNum = (n) => (result?.results || []).find((r) => r.number === n) || {};
  const pct = result && result.total_max ? Math.round((result.total_score / result.total_max) * 100) : 0;

  return (
    <Layout title="Practice & Self-Assessment">
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {/* SETUP */}
      {stage === 'setup' && (
        <div className="max-w-xl">
          <div className="mb-5">
            <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Sparkles size={18} className="text-blue-600" /> Generate a Practice Test</h2>
            <p className="text-sm text-gray-500">The AI creates questions from your school's books and past papers, then grades your answers with feedback.</p>
          </div>
          <div className="card space-y-4">
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subject *</label>
                <select value={form.subject} onChange={(e) => setF('subject', e.target.value)} className="input-field">
                  {subjectOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Difficulty</label>
                <select value={form.difficulty} onChange={(e) => setF('difficulty', e.target.value)} className="input-field">
                  {DIFFICULTIES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Number of Questions</label>
                <select value={form.num_questions} onChange={(e) => setF('num_questions', e.target.value)} className="input-field">
                  {COUNTS.map((c) => <option key={c} value={c}>{c} questions</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Topic (optional)</label>
                <input type="text" value={form.topics} onChange={(e) => setF('topics', e.target.value)} className="input-field" placeholder="e.g. Photosynthesis" />
              </div>
            </div>
            <button onClick={startPractice} disabled={loading} className="btn-primary w-full flex items-center justify-center gap-2">
              {loading ? <><Loader2 size={16} className="animate-spin" /> Generating…</> : <><Sparkles size={16} /> Start Practice</>}
            </button>
          </div>
        </div>
      )}

      {/* TAKING */}
      {stage === 'taking' && test && (
        <div className="max-w-3xl">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div>
              <h2 className="font-semibold text-gray-800">{test.title}</h2>
              <p className="text-sm text-gray-500">Answer the questions, then submit for AI grading.</p>
            </div>
            <span className="text-sm text-gray-500">{answeredCount}/{test.questions.length} answered</span>
          </div>

          <div className="space-y-3">
            {test.questions.map((q) => (
              <div key={q.number} className="card">
                <p className="text-sm font-medium text-gray-800">
                  Q{q.number}. {q.question}
                  <span className="ml-2 text-xs text-gray-400">({q.marks} marks)</span>
                </p>
                {q.options?.length ? (
                  <div className="mt-3 space-y-1.5">
                    {q.options.map((opt, j) => (
                      <label key={j} className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer text-sm transition-colors ${answers[q.number] === opt ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                        <input
                          type="radio"
                          name={`q-${q.number}`}
                          checked={answers[q.number] === opt}
                          onChange={() => setAnswers((a) => ({ ...a, [q.number]: opt }))}
                        />
                        {opt}
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea
                    value={answers[q.number] || ''}
                    onChange={(e) => setAnswers((a) => ({ ...a, [q.number]: e.target.value }))}
                    className="input-field mt-3 min-h-[80px]"
                    placeholder="Type your answer…"
                  />
                )}
              </div>
            ))}
          </div>

          <div className="flex gap-3 mt-4">
            <button onClick={reset} className="btn-secondary flex items-center gap-2"><X size={16} /> Cancel</button>
            <button onClick={submitForGrading} disabled={grading} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {grading ? <><Loader2 size={16} className="animate-spin" /> Grading…</> : <><CheckCircle size={16} /> Submit for AI Grading</>}
            </button>
          </div>
        </div>
      )}

      {/* RESULT */}
      {stage === 'result' && result && test && (
        <div className="max-w-3xl">
          {/* Score summary */}
          <div className="card mb-4">
            <div className="flex items-center gap-4">
              <div className={`w-16 h-16 rounded-full flex flex-col items-center justify-center shrink-0 ${pct >= 50 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                <span className="text-lg font-bold leading-none">{pct}%</span>
              </div>
              <div className="flex-1">
                <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Award size={18} className="text-amber-500" /> {result.total_score} / {result.total_max} marks</h2>
                <p className="text-sm text-gray-600 mt-1">{result.overall_feedback}</p>
              </div>
            </div>
            {result.weak_topics?.length > 0 && (
              <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-xs font-semibold text-amber-800 flex items-center gap-1 mb-1.5"><TrendingDown size={13} /> Topics to revise</p>
                <div className="flex flex-wrap gap-1.5">
                  {result.weak_topics.map((t, i) => <span key={i} className="badge-yellow">{t}</span>)}
                </div>
              </div>
            )}
          </div>

          {/* Per-question breakdown */}
          <div className="space-y-3">
            {test.questions.map((q) => {
              const r = resByNum(q.number);
              const correct = r.is_correct ?? (r.score >= (r.max_marks || q.marks));
              return (
                <div key={q.number} className="card">
                  <div className="flex items-start gap-2">
                    {correct ? <CheckCircle size={18} className="text-green-600 shrink-0 mt-0.5" /> : <XCircle size={18} className="text-red-500 shrink-0 mt-0.5" />}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800">
                        Q{q.number}. {q.question}
                        <span className="ml-2 text-xs text-gray-400">({r.score ?? 0}/{r.max_marks ?? q.marks} marks)</span>
                      </p>
                      <p className="text-xs text-gray-500 mt-1"><span className="font-medium text-gray-600">Your answer:</span> {(answers[q.number] || '').trim() || '(blank)'}</p>
                      <p className="text-xs text-green-700 mt-0.5"><span className="font-medium">Model answer:</span> {keyByNum(q.number).correct_answer}</p>
                      {r.feedback && <p className="text-xs text-gray-600 mt-1 p-2 bg-gray-50 rounded">{r.feedback}</p>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="flex gap-3 mt-4">
            <button onClick={reset} className="btn-primary flex items-center gap-2"><RefreshCw size={16} /> New Practice Test</button>
          </div>
        </div>
      )}
    </Layout>
  );
}
