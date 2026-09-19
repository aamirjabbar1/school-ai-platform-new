/**
 * Results — exams, ledgers and report cards.
 *
 * "Select exam → class → Generate", which is what §81.I asks for. The user
 * never writes a formula, a total or a percentage; the engine does all of it,
 * and the combined ledger and the combined report card call the same engine,
 * so they cannot disagree.
 *
 * The weightage editor shows its running total in large type and refuses to
 * look happy until it reads 100. That single number is the difference between
 * a combined result that means something and one that quietly does not.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Empty, Field, Note, Panel } from '../../components/erp/Kit';
import {
  Download, FileText, GraduationCap, Loader2, Plus, Printer, Scale, Trophy,
} from 'lucide-react';

const TABS = [
  { key: 'ledger', label: 'Exam ledger' },
  { key: 'combined', label: 'Combined result' },
  { key: 'setup', label: 'Examinations' },
];

export default function ErpResults() {
  const [tab, setTab] = useState('ledger');
  const [loading, setLoading] = useState(true);
  const [exams, setExams] = useState([]);
  const [classes, setClasses] = useState([]);
  const [schemes, setSchemes] = useState([]);
  const [examId, setExamId] = useState('');
  const [schemeId, setSchemeId] = useState('');
  const [classId, setClassId] = useState('');
  const [ledger, setLedger] = useState(null);
  const [working, setWorking] = useState(false);
  const [newExam, setNewExam] = useState(null);
  const [newScheme, setNewScheme] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: e }, { data: c }, { data: s }] = await Promise.all([
        erpAPI.exams(), erpAPI.classes(), erpAPI.resultSchemes(),
      ]);
      setExams(e.exams);
      setClasses(c);
      setSchemes(s.schemes);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load examinations.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const generate = async () => {
    if (!classId) { setError('Choose a class.'); return; }
    setWorking(true);
    setError('');
    setLedger(null);
    try {
      const { data } = tab === 'combined'
        ? await erpAPI.combinedLedger(schemeId, { class_id: classId })
        : await erpAPI.examLedger(examId, { class_id: classId });
      setLedger(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not generate that ledger.');
    } finally {
      setWorking(false);
    }
  };

  const createExam = async () => {
    setWorking(true);
    try {
      await erpAPI.createExam(newExam);
      setMessage(`${newExam.name} created.`);
      setNewExam(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not create that examination.');
    } finally {
      setWorking(false);
      setConfirm(null);
    }
  };

  const saveScheme = async () => {
    const total = newScheme.components.reduce((sum, c) => sum + Number(c.weight_percent || 0), 0);
    if (total !== 100) { setError(`The weights add up to ${total}%. They must total 100%.`); return; }
    setWorking(true);
    try {
      await erpAPI.createResultScheme({
        name: newScheme.name,
        class_id: newScheme.class_id || undefined,
        show_position: newScheme.show_position,
        components: newScheme.components.filter((c) => Number(c.weight_percent) > 0),
      });
      setMessage('Weightage scheme saved. Combined results now use it.');
      setNewScheme(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save that scheme.');
    } finally {
      setWorking(false);
    }
  };

  const exportCsv = () => {
    if (!ledger?.students?.length) return;
    const subjects = ledger.subjects || [];
    const header = ['GR No', 'Roll', 'Name', 'Father', ...subjects, 'Obtained', 'Total', '%', 'Grade'];
    const rows = ledger.students.map((s) => [
      s.gr_no || '', s.roll_no || '', s.name, s.father_name || '',
      ...subjects.map((sub) => s.subjects?.[sub] ?? ''),
      s.obtained ?? '', s.total ?? '', s.percent, s.grade,
    ]);
    const csv = [header, ...rows]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `ledger-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading) return <Layout title="Results"><Busy /></Layout>;

  const weightTotal = newScheme
    ? newScheme.components.reduce((sum, c) => sum + Number(c.weight_percent || 0), 0)
    : 0;

  return (
    <Layout title="Results">
      <div className="space-y-4 max-w-5xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <div className="flex gap-2 overflow-x-auto pb-1">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => { setTab(t.key); setLedger(null); }}
                    className={`px-4 min-h-[44px] rounded-xl whitespace-nowrap text-sm font-medium
                                ${tab === t.key ? 'btn-primary' : 'btn-secondary'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Ledgers ── */}
        {(tab === 'ledger' || tab === 'combined') && (
          <Panel
            title={tab === 'combined' ? 'Combined marks ledger' : 'Examination ledger'}
            subtitle="Select, generate. Every total and percentage is worked out for you."
          >
            <div className="grid sm:grid-cols-3 gap-3">
              {tab === 'combined' ? (
                <Field label="Weightage scheme" value={schemeId} onChange={setSchemeId}
                       options={schemes.map((s) => ({
                         value: s.id,
                         label: `${s.name} (${s.weights_total}%)`,
                       }))} />
              ) : (
                <Field label="Examination" value={examId} onChange={setExamId}
                       options={exams.map((e) => ({ value: e.id, label: e.name }))} />
              )}
              <Field label="Class" value={classId} onChange={setClassId}
                     options={classes.map((c) => ({ value: c.id, label: c.canonical_name }))} />
              <div className="flex items-end">
                <button onClick={generate}
                        disabled={working || !classId || (tab === 'combined' ? !schemeId : !examId)}
                        className="btn-primary w-full min-h-[44px]">
                  {working ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
                  Generate
                </button>
              </div>
            </div>
          </Panel>
        )}

        {ledger && (
          <Panel
            title={ledger.exam?.name || ledger.scheme?.name}
            subtitle={ledger.class_average
              ? `Class average ${ledger.class_average}% · ${ledger.pass_percent}% passed`
              : `Weights total ${ledger.weights_total}%`}
            action={
              <div className="flex gap-2">
                <button onClick={exportCsv} className="btn-secondary min-h-[44px]">
                  <Download size={16} /> Excel
                </button>
                <button onClick={() => window.print()} className="btn-secondary min-h-[44px]">
                  <Printer size={16} /> Print
                </button>
              </div>
            }
          >
            {ledger.weights_total && ledger.weights_total !== '100.00' && (
              <Note kind="bad">
                The weights in this scheme total {ledger.weights_total}%, not 100%. The combined
                result below is not meaningful until that is fixed.
              </Note>
            )}

            {ledger.students.length === 0 ? (
              <Empty icon={GraduationCap} title="No students in this class"
                     hint="Students appear once they are enrolled for this session." />
            ) : (
              <div className="overflow-x-auto -mx-2 px-2 mt-3">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-muted">
                      <th className="py-2 pr-3 font-medium">Student</th>
                      {(ledger.subjects || []).map((s) => (
                        <th key={s} className="py-2 px-2 font-medium text-center whitespace-nowrap">{s}</th>
                      ))}
                      {(ledger.exams || []).map((e) => (
                        <th key={e.exam_id} className="py-2 px-2 font-medium text-center whitespace-nowrap">
                          {e.name}<br /><span className="text-xs text-faint">{e.weight}%</span>
                        </th>
                      ))}
                      <th className="py-2 px-2 font-medium text-right">%</th>
                      <th className="py-2 pl-2 font-medium text-center">Grade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.students.map((s) => (
                      <tr key={s.student_id} className="border-t border-line/40">
                        <td className="py-2 pr-3">
                          <div className="font-medium text-ink whitespace-nowrap">{s.name}</div>
                          <div className="text-xs text-faint">{s.gr_no ? `GR ${s.gr_no}` : ''}</div>
                        </td>
                        {(ledger.subjects || []).map((sub) => (
                          <td key={sub} className="py-2 px-2 text-center text-ink">
                            {s.subject_status?.[sub] === 'absent' ? 'A'
                              : s.subject_status?.[sub] === 'exempt' ? '—'
                              : s.subjects?.[sub] ?? '·'}
                          </td>
                        ))}
                        {(ledger.exams || []).map((e) => {
                          const row = s.exams?.find((x) => x.exam_id === e.exam_id);
                          return (
                            <td key={e.exam_id} className="py-2 px-2 text-center text-ink">
                              {row ? `${row.percent}%` : '·'}
                            </td>
                          );
                        })}
                        <td className="py-2 px-2 text-right font-semibold text-ink">{s.percent}</td>
                        <td className="py-2 pl-2 text-center">
                          <span className={s.passed === false ? 'text-rose-400' : 'text-ink'}>
                            {s.grade}
                          </span>
                          {s.position && (
                            <span className="ml-1 text-xs text-brand-cyan">#{s.position}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        )}

        {/* ── Setup ── */}
        {tab === 'setup' && (
          <>
            <Panel
              title="Examinations"
              subtitle="Monthly tests, mid-term, final-term — whatever the school runs."
              action={
                <button onClick={() => setNewExam({ name: '', exam_type: 'monthly', sequence: exams.length + 1 })}
                        className="btn-primary min-h-[44px]">
                  <Plus size={16} /> Add
                </button>
              }
            >
              {exams.length === 0 ? (
                <Empty icon={GraduationCap} title="No examinations yet" hint="Add the first one." />
              ) : (
                <div className="space-y-2">
                  {exams.map((e) => (
                    <div key={e.id} className="rounded-xl bg-surface-2/60 p-3 flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-ink">{e.name}</div>
                        <div className="text-sm text-muted">{e.status.replace('_', ' ')}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {newExam && (
                <div className="mt-4 space-y-4 rounded-2xl bg-surface-2/60 p-4">
                  <Field label="Name" value={newExam.name}
                         onChange={(v) => setNewExam((x) => ({ ...x, name: v }))}
                         placeholder="First Monthly Test" required />
                  <Field label="Kind" value={newExam.exam_type}
                         onChange={(v) => setNewExam((x) => ({ ...x, exam_type: v }))}
                         options={[
                           { value: 'monthly', label: 'Monthly test' },
                           { value: 'mid_term', label: 'Mid-term' },
                           { value: 'final_term', label: 'Final-term' },
                         ]} />
                  <div className="flex gap-3">
                    <button onClick={() => setNewExam(null)} className="btn-secondary flex-1 min-h-[44px]">Cancel</button>
                    <button onClick={createExam} disabled={!newExam.name || working}
                            className="btn-primary flex-1 min-h-[44px]">Create</button>
                  </div>
                </div>
              )}
            </Panel>

            <Panel
              title="Combined result weightages"
              subtitle="How the monthly tests, mid-term and final-term add up to one result."
              action={
                <button
                  onClick={() => setNewScheme({
                    name: '', class_id: '', show_position: false,
                    components: exams.map((e) => ({ exam_id: e.id, exam: e.name, weight_percent: '' })),
                  })}
                  className="btn-primary min-h-[44px]"
                >
                  <Plus size={16} /> Add
                </button>
              }
            >
              {schemes.length === 0 ? (
                <Empty icon={Scale} title="No weightage scheme yet"
                       hint="Define one once, and every combined result and report card uses it." />
              ) : (
                <div className="space-y-2">
                  {schemes.map((s) => (
                    <div key={s.id} className="rounded-xl bg-surface-2/60 p-3">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-ink">{s.name}</div>
                          <div className="text-sm text-muted">
                            {s.components.map((c) => `${c.exam} ${c.weight_percent}%`).join(' · ')}
                          </div>
                        </div>
                        <span className={`text-sm font-bold shrink-0 ${
                          s.weights_total === '100.00' ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {s.weights_total}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {newScheme && (
                <div className="mt-4 space-y-4 rounded-2xl bg-surface-2/60 p-4">
                  <Field label="Name" value={newScheme.name}
                         onChange={(v) => setNewScheme((x) => ({ ...x, name: v }))}
                         placeholder="Annual Result 2026-2027" required />
                  <Field label="Class" value={newScheme.class_id}
                         onChange={(v) => setNewScheme((x) => ({ ...x, class_id: v }))}
                         options={classes.map((c) => ({ value: c.id, label: c.canonical_name }))}
                         hint="Leave blank to use this for every class" />

                  <div className="space-y-2">
                    {newScheme.components.map((c, i) => (
                      <div key={c.exam_id} className="flex items-center gap-3">
                        <span className="flex-1 text-sm text-ink truncate">{c.exam}</span>
                        <input
                          type="number" min="0" max="100"
                          value={c.weight_percent}
                          onChange={(e) => setNewScheme((x) => ({
                            ...x,
                            components: x.components.map((y, j) =>
                              j === i ? { ...y, weight_percent: e.target.value } : y),
                          }))}
                          className="w-20 min-h-[44px] rounded-xl px-2 bg-surface border border-line text-ink text-center
                                     focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
                        />
                        <span className="text-muted text-sm w-4">%</span>
                      </div>
                    ))}
                  </div>

                  <div className={`flex items-center justify-between rounded-xl p-3
                                   ${weightTotal === 100 ? 'bg-emerald-500/10' : 'bg-amber-500/10'}`}>
                    <span className="text-sm text-muted">Total</span>
                    <span className={`text-2xl font-bold ${
                      weightTotal === 100 ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {weightTotal}%
                    </span>
                  </div>
                  {weightTotal !== 100 && (
                    <p className="text-sm text-muted">It must come to exactly 100%.</p>
                  )}

                  <label className="flex items-center gap-2 text-sm text-muted cursor-pointer select-none">
                    <input type="checkbox" checked={newScheme.show_position}
                           onChange={(e) => setNewScheme((x) => ({ ...x, show_position: e.target.checked }))}
                           className="w-4 h-4 accent-brand-cyan" />
                    <Trophy size={14} /> Show position in class
                  </label>

                  <div className="flex gap-3">
                    <button onClick={() => setNewScheme(null)} className="btn-secondary flex-1 min-h-[44px]">Cancel</button>
                    <button onClick={saveScheme} disabled={working || weightTotal !== 100 || !newScheme.name}
                            className="btn-primary flex-1 min-h-[44px]">Save scheme</button>
                  </div>
                </div>
              )}
            </Panel>
          </>
        )}
      </div>

      <Confirm
        open={!!confirm}
        title={confirm?.title}
        lines={confirm?.lines || []}
        confirmLabel={confirm?.confirmLabel}
        onConfirm={() => confirm?.run()}
        onCancel={() => setConfirm(null)}
        busy={working}
      />
    </Layout>
  );
}
