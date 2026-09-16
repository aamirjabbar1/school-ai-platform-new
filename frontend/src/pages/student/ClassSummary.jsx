import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Layout from '../../components/Layout';
import Markdown from '../../components/Markdown';
import { onlineClassAPI } from '../../services/api';
import { apiError } from '../../services/apiError';
import { Sparkles, Send, Loader2, BookOpen, MessageSquare, FileText } from 'lucide-react';

// After a class: what was covered, plus ASK LSS AI ABOUT THIS CLASS (spec §19).
//
// The student types their question — there is no microphone here and nothing
// listens. The answer is written from the class's own record and the approved
// textbook, and the sources are shown so a teacher can check them.
export default function ClassSummary() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [summary, setSummary] = useState(null);
  const [notes, setNotes] = useState(null);
  const [question, setQuestion] = useState('');
  const [thread, setThread] = useState([]);
  const [asking, setAsking] = useState(false);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [error, setError] = useState('');
  const endRef = useRef(null);

  useEffect(() => {
    onlineClassAPI.summary(sessionId)
      .then(({ data }) => setSummary(data))
      .catch(() => setSummary({ available: false, message: 'Summary not available.' }));

    onlineClassAPI.askHistory(sessionId)
      .then(({ data }) => setThread(
        (data.questions || []).reverse().map((q) => ({
          question: q.question, answer: q.answer, sources: q.sources || [],
        })),
      ))
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [thread]);

  const ask = async () => {
    const text = question.trim();
    if (!text) return;
    setAsking(true);
    setError('');
    setQuestion('');
    setThread((prev) => [...prev, { question: text, answer: null }]);

    try {
      const { data } = await onlineClassAPI.ask(sessionId, text);
      setThread((prev) => prev.map((item, i) => (
        i === prev.length - 1 ? { ...item, answer: data.answer, sources: data.sources } : item
      )));
    } catch (err) {
      const detail = apiError(err, 'LSS AI cannot answer right now. Please try again later.');
      setThread((prev) => prev.slice(0, -1));
      setError(detail);
      setQuestion(text);
    } finally {
      setAsking(false);
    }
  };

  const loadNotes = async () => {
    setLoadingNotes(true);
    setError('');
    try {
      const { data } = await onlineClassAPI.revisionNotes(sessionId);
      setNotes(data.content);
    } catch (err) {
      setError(apiError(err, 'Revision notes are not available right now.'));
    } finally {
      setLoadingNotes(false);
    }
  };

  const content = summary?.content;

  return (
    <Layout title="About this class">
      <div className="max-w-3xl space-y-4">
        {/* Summary */}
        <div className="card">
          <div className="flex items-center gap-2 font-semibold text-ink mb-2">
            <FileText size={17} /> Class summary
          </div>
          {summary === null && <p className="text-sm text-muted">Loading…</p>}
          {summary && !summary.available && (
            <p className="text-sm text-muted">{summary.message}</p>
          )}
          {content && (
            <>
              <Markdown>{content.summary || ''}</Markdown>
              {content.topics?.length > 0 && (
                <div className="mt-3">
                  <div className="text-xs font-semibold text-muted uppercase">Topics</div>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {content.topics.map((topic) => (
                      <span key={topic} className="text-xs px-2 py-1 rounded-lg glass text-ink">{topic}</span>
                    ))}
                  </div>
                </div>
              )}
              {content.key_points?.length > 0 && (
                <ul className="list-disc ml-5 mt-3 text-sm text-muted space-y-1">
                  {content.key_points.map((point) => <li key={point}>{point}</li>)}
                </ul>
              )}
              {content.homework && (
                <div className="glass rounded-xl p-3 mt-3 text-sm">
                  <span className="font-semibold text-ink">Homework: </span>
                  <span className="text-muted">{content.homework}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Revision notes */}
        <div className="card">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-semibold text-ink">
              <BookOpen size={17} /> Revision notes
            </div>
            {!notes && (
              <button onClick={loadNotes} disabled={loadingNotes} className="btn-secondary text-sm">
                {loadingNotes ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                Get revision notes
              </button>
            )}
          </div>
          {notes && (
            <div className="mt-3 text-sm space-y-3">
              {notes.key_concepts?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-muted uppercase">Key concepts</div>
                  <ul className="list-disc ml-5 mt-1 text-muted">
                    {notes.key_concepts.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </div>
              )}
              {notes.definitions?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-muted uppercase">Definitions</div>
                  <ul className="mt-1 text-muted space-y-1">
                    {notes.definitions.map((d) => (
                      <li key={d.term}><span className="text-ink font-medium">{d.term}:</span> {d.meaning}</li>
                    ))}
                  </ul>
                </div>
              )}
              {notes.practice_questions?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-muted uppercase">Practice</div>
                  <ol className="list-decimal ml-5 mt-1 text-muted space-y-1">
                    {notes.practice_questions.map((q) => <li key={q}>{q}</li>)}
                  </ol>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Ask LSS AI */}
        <div className="card">
          <div className="flex items-center gap-2 font-semibold text-ink mb-1">
            <MessageSquare size={17} className="text-brand-cyan" /> Ask LSS AI about this class
          </div>
          <p className="text-xs text-muted mb-3">
            Type your question — LSS AI answers from your books and this class's record.
          </p>

          <div className="space-y-3 max-h-[26rem] overflow-y-auto">
            {thread.map((item, index) => (
              <div key={`${item.question}-${index}`} className="space-y-2">
                <div className="glass rounded-2xl px-3 py-2 text-sm ml-auto max-w-[85%] w-fit">
                  {item.question}
                </div>
                {item.answer === null ? (
                  <div className="flex items-center gap-2 text-sm text-muted">
                    <Loader2 size={15} className="animate-spin" /> LSS AI is writing…
                  </div>
                ) : (
                  <div className="glass-strong rounded-2xl px-3 py-2 text-sm">
                    <Markdown>{item.answer}</Markdown>
                    {item.sources?.length > 0 && (
                      <div className="text-xs text-faint mt-2">
                        From your books:{' '}
                        {item.sources.map((s) => (
                          s.page ? `${s.title} (p. ${s.page})` : s.title
                        )).join(' · ')}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          {error && <div className="text-sm text-rose-400 mt-2">{error}</div>}

          <div className="flex gap-2 mt-3">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !asking) ask(); }}
              placeholder="I didn't understand today's topic…"
              className="input-field flex-1"
            />
            <button onClick={ask} disabled={asking || !question.trim()} className="btn-primary">
              {asking ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
        </div>

        <button onClick={() => navigate('/student/online-classes')} className="btn-secondary">
          Back to my classes
        </button>
      </div>
    </Layout>
  );
}
