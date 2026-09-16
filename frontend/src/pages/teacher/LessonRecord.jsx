import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import Markdown from '../../components/Markdown';
import { onlineClassAPI } from '../../services/api';
import {
  CheckCircle2, Sparkles, Loader2, BookOpen, ClipboardList, Send, Wand2, AlertCircle,
} from 'lucide-react';

// After the class: the teacher confirms what was actually taught (spec §16, §18).
//
// The system fills in what it can prove — the pages the classroom displayed,
// the boards that were saved — and stops there. Whether a page was *taught* is
// a judgement only the teacher can make, so nothing becomes the official record
// until they say so. The AI drafts; it never signs.
export default function LessonRecord() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [topics, setTopics] = useState('');
  const [pages, setPages] = useState('');
  const [homework, setHomework] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [summary, setSummary] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [assistantAnswer, setAssistantAnswer] = useState('');
  const [assistantAsk, setAssistantAsk] = useState('');

  useEffect(() => {
    onlineClassAPI.lessonRecord(sessionId)
      .then(({ data: payload }) => {
        setData(payload);
        setTopics((payload.record.topics_covered || []).join('\n'));
        setPages((payload.record.pages_covered || []).join(', '));
        setHomework(payload.record.homework || '');
        setNotes(payload.record.teacher_notes || '');
        setCoverage(payload.record.ai_suggestion || null);
      })
      .catch(() => setError('Could not load this class record.'));

    onlineClassAPI.summary(sessionId)
      .then(({ data: payload }) => { if (payload.available) setSummary(payload.content); })
      .catch(() => {});
  }, [sessionId]);

  const save = async (confirm) => {
    setBusy(confirm ? 'confirm' : 'save');
    setError('');
    try {
      const { data: record } = await onlineClassAPI.saveLessonRecord(sessionId, {
        topics_covered: topics.split('\n').map((t) => t.trim()).filter(Boolean),
        pages_covered: pages.split(',').map((p) => parseInt(p.trim(), 10)).filter((n) => !Number.isNaN(n)),
        homework,
        teacher_notes: notes,
        confirm,
      });
      setData((prev) => ({ ...prev, record }));
      setNotice(confirm ? 'Lesson record confirmed.' : 'Saved.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not save the record.');
    } finally {
      setBusy('');
    }
  };

  // Every AI action degrades to a message. A failed summary must never look
  // like a broken lesson record.
  const runAI = async (key, fn, onDone) => {
    setBusy(key);
    setError('');
    try {
      const { data: payload } = await fn();
      onDone(payload);
    } catch (err) {
      setError(err?.response?.data?.detail
        || 'LSS AI is not available right now. Your lesson record is unaffected.');
    } finally {
      setBusy('');
    }
  };

  const publishHomework = async () => {
    if (!homework.trim()) { setError('Write the homework first.'); return; }
    setBusy('homework');
    try {
      await onlineClassAPI.publishHomework(sessionId, {
        title: `${data.session.subject} homework`,
        description: homework.trim(),
        max_marks: 10,
      });
      setNotice('Homework published to students.');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not publish homework.');
    } finally {
      setBusy('');
    }
  };

  if (error && !data) {
    return <Layout title="Lesson Record"><div className="card text-rose-400">{error}</div></Layout>;
  }
  if (!data) {
    return <Layout title="Lesson Record"><div className="card text-muted">Loading…</div></Layout>;
  }

  const confirmed = data.record.is_confirmed;

  return (
    <Layout title="Lesson Record">
      <div className="max-w-3xl space-y-4">
        <div className="card">
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <div className="font-display font-bold text-ink">
                {data.session.subject} — {data.session.class_name}
                {data.session.section ? ` (${data.session.section})` : ''}
              </div>
              <div className="text-sm text-muted">
                {data.session.actual_start && new Date(data.session.actual_start).toLocaleString()}
                {' · '}{Math.round((data.session.duration_seconds || 0) / 60)} minutes
              </div>
            </div>
            {confirmed && (
              <span className="inline-flex items-center gap-1.5 text-emerald-400 text-sm font-semibold">
                <CheckCircle2 size={16} /> Confirmed
              </span>
            )}
          </div>
        </div>

        {/* What the system can prove */}
        <div className="card">
          <div className="flex items-center gap-2 font-semibold text-ink mb-2">
            <BookOpen size={17} /> Shown in this class
          </div>
          {data.presented.length === 0 ? (
            <p className="text-sm text-muted">No book or document was presented.</p>
          ) : (
            <ul className="text-sm text-muted space-y-1">
              {data.presented.map((r) => (
                <li key={r.title}>
                  {r.title}
                  {r.pages_presented?.length ? ` — pages ${r.pages_presented.join(', ')}` : ''}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-faint mt-2">
            A page being displayed means it was shown on screen — you decide what was taught.
          </p>
        </div>

        {notice && <div className="card text-sm text-emerald-400">{notice}</div>}
        {error && (
          <div className="card text-sm text-rose-400 flex items-center gap-2">
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {/* Teacher's record */}
        <div className="card space-y-3">
          <div className="font-semibold text-ink flex items-center gap-2">
            <ClipboardList size={17} /> What you taught
          </div>

          <label className="block text-sm">
            <span className="text-muted text-xs">Topics covered (one per line)</span>
            <textarea
              rows={4}
              value={topics}
              onChange={(e) => setTopics(e.target.value)}
              className="input-field mt-1"
              placeholder={'Photosynthesis — the basic process\nWhy leaves are green'}
            />
          </label>

          <label className="block text-sm">
            <span className="text-muted text-xs">Pages covered</span>
            <input
              value={pages}
              onChange={(e) => setPages(e.target.value)}
              className="input-field mt-1"
              placeholder="24, 25, 26"
            />
          </label>

          <label className="block text-sm">
            <span className="text-muted text-xs">Homework</span>
            <textarea
              rows={3}
              value={homework}
              onChange={(e) => setHomework(e.target.value)}
              className="input-field mt-1"
              placeholder="Exercise 3 on page 27, questions 1-5"
            />
          </label>

          <label className="block text-sm">
            <span className="text-muted text-xs">Notes for the record</span>
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input-field mt-1"
            />
          </label>

          <div className="flex flex-wrap gap-2">
            <button onClick={() => save(false)} disabled={busy === 'save'} className="btn-secondary">
              {busy === 'save' ? 'Saving…' : 'Save draft'}
            </button>
            <button onClick={() => save(true)} disabled={busy === 'confirm'} className="btn-primary">
              {busy === 'confirm' ? 'Confirming…' : 'Confirm lesson record'}
            </button>
            {homework.trim() && (
              <button onClick={publishHomework} disabled={busy === 'homework'} className="btn-secondary">
                <Send size={15} /> Publish homework
              </button>
            )}
          </div>
        </div>

        {/* AI help — optional, always degradable */}
        <div className="card space-y-3">
          <div className="font-semibold text-ink flex items-center gap-2">
            <Sparkles size={17} className="text-brand-cyan" /> LSS AI help
          </div>
          <p className="text-xs text-muted">
            Written from your class records and the Knowledge Base. LSS AI did not hear the
            lesson — nothing here is based on speech — so check it before publishing.
          </p>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => runAI('summary',
                () => onlineClassAPI.generateSummary(sessionId),
                (payload) => { setSummary(payload.content); setNotice('Summary ready for students.'); })}
              disabled={busy === 'summary'}
              className="btn-secondary text-sm"
            >
              {busy === 'summary' ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              Write class summary
            </button>

            {data.session.lesson_plan_id && (
              <button
                onClick={() => runAI('coverage',
                  () => onlineClassAPI.coverage(sessionId),
                  (payload) => setCoverage(payload.suggestion))}
                disabled={busy === 'coverage'}
                className="btn-secondary text-sm"
              >
                {busy === 'coverage' ? <Loader2 size={15} className="animate-spin" /> : <Wand2 size={15} />}
                Compare with lesson plan
              </button>
            )}
          </div>

          {coverage && (
            <div className="glass rounded-2xl p-3 text-sm">
              <div className="font-semibold text-ink mb-1">Suggested coverage (not yet official)</div>
              {coverage.covered?.length > 0 && (
                <p className="text-muted">Appears covered: {coverage.covered.join('; ')}</p>
              )}
              {coverage.possibly_remaining?.length > 0 && (
                <p className="text-muted">Possibly remaining: {coverage.possibly_remaining.join('; ')}</p>
              )}
              {coverage.suggested_next_start && (
                <p className="text-muted mt-1">Next lesson could start at: {coverage.suggested_next_start}</p>
              )}
              <button
                onClick={() => {
                  const extra = (coverage.covered || []).join('\n');
                  setTopics((prev) => (prev ? `${prev}\n${extra}` : extra));
                  setNotice('Added to your topics — edit before confirming.');
                }}
                className="btn-secondary text-xs mt-2"
              >
                Use these topics
              </button>
            </div>
          )}

          {summary && (
            <div className="glass rounded-2xl p-3 text-sm">
              <div className="font-semibold text-ink mb-1">Class summary (students can see this)</div>
              <Markdown>{summary.summary || ''}</Markdown>
              {summary.key_points?.length > 0 && (
                <ul className="list-disc ml-5 mt-2 text-muted">
                  {summary.key_points.map((point) => <li key={point}>{point}</li>)}
                </ul>
              )}
              {summary.not_in_record?.length > 0 && (
                <p className="text-xs text-faint mt-2">
                  Not in the class record: {summary.not_in_record.join('; ')}
                </p>
              )}
            </div>
          )}

          {/* Assistant */}
          <div className="pt-2 border-t border-line/50">
            <div className="text-sm font-medium text-ink mb-1.5">Ask the teaching assistant</div>
            <div className="flex gap-2">
              <input
                value={assistantAsk}
                onChange={(e) => setAssistantAsk(e.target.value)}
                placeholder="Explain photosynthesis a simpler way…"
                className="input-field flex-1"
              />
              <button
                onClick={() => runAI('assistant',
                  () => onlineClassAPI.assistant(sessionId, { request: assistantAsk, kind: 'explain' }),
                  (payload) => setAssistantAnswer(payload.answer))}
                disabled={busy === 'assistant' || !assistantAsk.trim()}
                className="btn-primary"
              >
                {busy === 'assistant' ? <Loader2 size={15} className="animate-spin" /> : 'Ask'}
              </button>
            </div>
            {assistantAnswer && (
              <div className="glass rounded-2xl p-3 mt-2 text-sm">
                <Markdown>{assistantAnswer}</Markdown>
              </div>
            )}
          </div>
        </div>

        <button onClick={() => navigate('/teacher/online-classes')} className="btn-secondary">
          Back to Online Classes
        </button>
      </div>
    </Layout>
  );
}
