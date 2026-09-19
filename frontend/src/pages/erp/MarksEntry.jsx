/**
 * Marks entry.
 *
 * A teacher with a stack of marked papers wants one column of boxes and a Save
 * button. So: pick the exam, pick the paper, type down the list. Enter moves to
 * the next child, which is the difference between a five-minute job and a
 * twenty-minute one.
 *
 * The maximum is shown at the top and enforced as you type, because a 105 out
 * of 100 caught here is a typo and caught after publication is a grievance.
 */
import { useEffect, useRef, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Empty, Note, Panel } from '../../components/erp/Kit';
import { ArrowLeft, Check, ClipboardList, Loader2, Send } from 'lucide-react';

export default function ErpMarksEntry() {
  const [loading, setLoading] = useState(true);
  const [exams, setExams] = useState([]);
  const [exam, setExam] = useState(null);
  const [papers, setPapers] = useState([]);
  const [paper, setPaper] = useState(null);
  const [sheet, setSheet] = useState(null);
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const inputs = useRef([]);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await erpAPI.exams();
        setExams(data.exams);
      } catch (e) {
        setError(e.response?.data?.detail || 'Could not load examinations.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const openExam = async (e) => {
    setExam(e);
    setPaper(null);
    setSheet(null);
    try {
      const { data } = await erpAPI.examSubjects(e.id, {});
      setPapers(data.subjects);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load the papers.');
    }
  };

  const openPaper = async (p) => {
    setPaper(p);
    setSheet(null);
    setError('');
    try {
      const { data } = await erpAPI.marksSheet(p.id, {});
      setSheet(data);
      setValues(Object.fromEntries(data.students.map((s) => [
        s.student_id,
        { obtained: s.obtained, is_absent: s.is_absent, is_exempt: s.is_exempt },
      ])));
    } catch (err) {
      setError(err.response?.data?.detail || 'You may not enter marks for this paper.');
      setPaper(null);
    }
  };

  const setMark = (id, patch) =>
    setValues((v) => ({ ...v, [id]: { ...v[id], ...patch } }));

  const save = async (submit) => {
    setSaving(true);
    setError('');
    try {
      const { data } = await erpAPI.saveMarks({
        exam_subject_id: paper.id,
        submit,
        marks: Object.entries(values).map(([student_id, v]) => ({
          student_id,
          obtained: v.is_absent || v.is_exempt || v.obtained === '' ? null : Number(v.obtained),
          is_absent: !!v.is_absent,
          is_exempt: !!v.is_exempt,
        })),
      });
      setMessage(submit
        ? `${data.saved} marks submitted for review.`
        : `${data.saved} marks saved.`);
      if (submit) { setPaper(null); setSheet(null); }
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save. Nothing was changed.');
    } finally {
      setSaving(false);
    }
  };

  const onKeyDown = (index) => (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      inputs.current[index + 1]?.focus();
    }
  };

  if (loading) return <Layout title="Marks entry"><Busy /></Layout>;

  /* ── Which exam ── */
  if (!exam) {
    return (
      <Layout title="Marks entry">
        <div className="space-y-4 max-w-3xl">
          {error && <Note kind="bad">{error}</Note>}
          {exams.length === 0 ? (
            <Empty icon={ClipboardList} title="No examinations yet"
                   hint="The exam office creates examinations before marks can be entered." />
          ) : (
            <>
              <p className="text-sm text-muted px-1">Which examination?</p>
              <div className="space-y-2">
                {exams.map((e) => (
                  <button key={e.id} onClick={() => openExam(e)}
                          className="card w-full text-left min-h-[72px] flex items-center gap-4 hover:scale-[1.005] transition-transform">
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-ink text-lg">{e.name}</div>
                      <div className="text-sm text-muted">{e.status.replace('_', ' ')}</div>
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </Layout>
    );
  }

  /* ── Which paper ── */
  if (!paper) {
    return (
      <Layout title="Marks entry">
        <div className="space-y-4 max-w-3xl">
          <button onClick={() => setExam(null)} className="flex items-center gap-2 text-muted hover:text-ink min-h-[44px]">
            <ArrowLeft size={18} /> {exam.name}
          </button>
          {message && <Note kind="good">{message}</Note>}
          {error && <Note kind="bad">{error}</Note>}
          {papers.length === 0 ? (
            <Empty icon={ClipboardList} title="No papers set up for this exam"
                   hint="The exam office adds subjects and marks before entry can start." />
          ) : (
            <div className="space-y-2">
              {papers.map((p) => (
                <button key={p.id} onClick={() => openPaper(p)}
                        className="card w-full text-left min-h-[68px] flex items-center gap-4 hover:scale-[1.005] transition-transform">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink">{p.class_name} · {p.subject_name}</div>
                    <div className="text-sm text-muted">out of {p.max_marks}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </Layout>
    );
  }

  /* ── The sheet ── */
  return (
    <Layout title="Marks entry">
      <div className="max-w-3xl pb-28">
        <button onClick={() => setPaper(null)} className="flex items-center gap-2 text-muted hover:text-ink mb-3 min-h-[44px]">
          <ArrowLeft size={18} /> {paper.class_name} · {paper.subject_name}
        </button>

        {message && <div className="mb-3"><Note kind="good">{message}</Note></div>}
        {error && <div className="mb-3"><Note kind="bad">{error}</Note></div>}

        {!sheet ? <Busy /> : (
          <>
            <Panel>
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold text-ink">{sheet.subject}</div>
                  <div className="text-sm text-muted">{sheet.exam?.name}</div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-ink">{sheet.max_marks}</div>
                  <div className="text-xs text-muted">maximum</div>
                </div>
              </div>
              {sheet.locked && (
                <div className="mt-3">
                  <Note kind="info">These marks have been submitted. Changes need a reviewer.</Note>
                </div>
              )}
            </Panel>

            <div className="space-y-2 mt-3">
              {sheet.students.map((s, index) => {
                const v = values[s.student_id] || {};
                return (
                  <div key={s.student_id} className="card flex items-center gap-3 min-h-[64px]">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-ink truncate">{s.name}</div>
                      <div className="text-xs text-faint">
                        {s.roll_no ? `Roll ${s.roll_no}` : s.gr_no ? `GR ${s.gr_no}` : ''}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => setMark(s.student_id, { is_absent: !v.is_absent, is_exempt: false })}
                        className={`px-3 min-h-[44px] rounded-xl text-sm font-medium transition-colors
                                    ${v.is_absent ? 'bg-rose-500/20 text-rose-400' : 'bg-surface-2 text-muted'}`}
                      >
                        Absent
                      </button>
                      <input
                        ref={(el) => { inputs.current[index] = el; }}
                        type="number"
                        inputMode="decimal"
                        max={sheet.max_marks}
                        min={0}
                        disabled={v.is_absent || v.is_exempt}
                        value={v.obtained ?? ''}
                        onChange={(e) => setMark(s.student_id, { obtained: e.target.value })}
                        onKeyDown={onKeyDown(index)}
                        className="w-20 min-h-[44px] rounded-xl px-2 bg-surface-2 border border-line text-ink
                                   text-center text-lg font-semibold disabled:opacity-40
                                   focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {sheet?.students?.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 p-3 glass-strong border-t border-line/60">
          <div className="max-w-3xl mx-auto flex items-center gap-3">
            <button onClick={() => save(false)} disabled={saving} className="btn-secondary flex-1 min-h-[52px]">
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Save
            </button>
            <button onClick={() => save(true)} disabled={saving} className="btn-primary flex-1 min-h-[52px]">
              <Send size={16} /> Submit for review
            </button>
          </div>
        </div>
      )}
    </Layout>
  );
}
