/**
 * Payroll.
 *
 * Select the month, press Generate, look at it, press Approve. That is the
 * whole screen, because that is the whole job — the salary was defined once,
 * months ago, and nothing should ask for it again.
 *
 * Two things are deliberately loud rather than tucked away:
 *
 *   • Anyone whose salary has not been set is named before the run, not
 *     silently paid zero. Zero on a payslip is how a teacher finds out.
 *   • A prorated line says why on the line itself — "joined on 14 September",
 *     "3 days unpaid leave". A number a teacher cannot account for is a
 *     conversation the office has to have instead.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Empty, Field, Note, Panel, Stat } from '../../components/erp/Kit';
import {
  BadgeCheck, Banknote, Calculator, CheckCircle2, Coins, Loader2, Users, Wallet,
} from 'lucide-react';

const rupees = (v) => `Rs ${Number(v || 0).toLocaleString('en-PK')}`;
const thisMonth = () => new Date().toISOString().slice(0, 7);

const STATUS = {
  draft: { label: 'Not generated', tone: 'text-muted' },
  calculated: { label: 'Ready to review', tone: 'text-amber-400' },
  approved: { label: 'Approved', tone: 'text-emerald-400' },
  paid: { label: 'Paid', tone: 'text-emerald-400' },
};

export default function ErpPayroll() {
  const [month, setMonth] = useState(thisMonth());
  const [runs, setRuns] = useState([]);
  const [detail, setDetail] = useState(null);
  const [salaries, setSalaries] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [editing, setEditing] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: r }, { data: s }] = await Promise.all([erpAPI.payrollRuns(), erpAPI.salaries()]);
      setRuns(r.runs);
      setSalaries(s.staff);
      const forMonth = r.runs.find((x) => x.month.slice(0, 7) === month);
      setDetail(forMonth ? (await erpAPI.payrollRun(forMonth.id)).data : null);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load payroll.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [month]);

  const generate = async () => {
    setBusy(true);
    setError('');
    try {
      const { data } = await erpAPI.generatePayroll({ month: `${month}-01` });
      setMessage(
        `${data.employee_count} salaries calculated · ${rupees(data.total_net)} net.` +
        (data.without_salary?.length
          ? ` ${data.without_salary.length} skipped — no salary set.`
          : ''),
      );
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not generate payroll.');
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  const askApprove = () => {
    setConfirm({
      title: `Approve ${new Date(`${month}-01`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })} payroll?`,
      lines: [
        `${detail.employee_count} people, ${rupees(detail.total_net)} net.`,
        'Payslips become visible to staff.',
        'Advance instalments are recovered from their balances.',
        'The figures are frozen — any correction after this goes in next month’s payroll.',
      ],
      confirmLabel: 'Approve payroll',
      run: async () => {
        setBusy(true);
        try {
          await erpAPI.approvePayroll(detail.id);
          setMessage('Payroll approved. Payslips are now available to staff.');
          await load();
        } catch (e) {
          setError(e.response?.data?.detail || 'Could not approve.');
        } finally {
          setBusy(false);
          setConfirm(null);
        }
      },
    });
  };

  const saveSalary = async () => {
    setBusy(true);
    setError('');
    try {
      await erpAPI.setSalary(editing.id, {
        basic: Number(editing.basic),
        effective_from: editing.effective_from || undefined,
        reason: editing.reason || undefined,
      });
      setMessage(`Salary saved for ${editing.name}.`);
      setEditing(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save that salary.');
    } finally {
      setBusy(false);
    }
  };

  const withoutSalary = (salaries || []).filter((s) => !s.has_salary);
  const status = STATUS[detail?.status || 'draft'];

  if (loading) return <Layout title="Payroll"><Busy /></Layout>;

  return (
    <Layout title="Payroll">
      <div className="space-y-4 max-w-5xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <Panel title="Monthly payroll" subtitle="Salaries are already defined. Pick a month and generate.">
          <div className="flex flex-col sm:flex-row gap-3">
            <label className="flex-1">
              <span className="block text-sm font-medium text-ink mb-1.5">Month</span>
              <input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                className="w-full min-h-[48px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
              />
            </label>
            <div className="flex items-end gap-2">
              <button
                onClick={() => setConfirm({
                  title: 'Generate this month’s payroll?',
                  lines: [
                    'Every active employee with a salary is calculated.',
                    'Anyone who joined or left mid-month, or took unpaid leave, is prorated.',
                    'Nothing is paid and no payslip is visible until you approve it.',
                  ],
                  confirmLabel: 'Generate',
                  run: generate,
                })}
                disabled={busy || detail?.status === 'approved' || detail?.status === 'paid'}
                className="btn-primary min-h-[48px]"
              >
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Calculator size={16} />}
                {detail ? 'Regenerate' : 'Generate'}
              </button>
            </div>
          </div>

          {detail && (
            <div className="flex items-center gap-2 mt-3 text-sm">
              <BadgeCheck size={15} className={status.tone} />
              <span className={status.tone}>{status.label}</span>
              {detail.approved_at && <span className="text-faint">· {detail.approved_at.slice(0, 10)}</span>}
            </div>
          )}
        </Panel>

        {withoutSalary.length > 0 && (
          <Panel title={`${withoutSalary.length} without a salary`} subtitle="They are skipped by payroll until a salary is set.">
            <div className="space-y-2">
              {withoutSalary.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setEditing({ ...s, basic: '', effective_from: '', reason: '' })}
                  className="w-full text-left rounded-xl bg-amber-500/10 p-3 flex items-center gap-3 min-h-[56px]"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-ink truncate">{s.name}</div>
                    <div className="text-sm text-muted truncate">{s.designation || 'Staff'}</div>
                  </div>
                  <span className="text-sm text-brand-cyan shrink-0">Set salary</span>
                </button>
              ))}
            </div>
          </Panel>
        )}

        {detail && (
          <>
            <div className="grid sm:grid-cols-3 gap-3">
              <Stat icon={Users} value={detail.employee_count} label="people paid" />
              <Stat icon={Coins} value={rupees(detail.total_gross)} label="gross" />
              <Stat icon={Wallet} value={rupees(detail.total_net)} label="net payable" />
            </div>

            <Panel
              title="The month"
              subtitle="Check it before approving. After approval the figures are frozen."
              action={
                detail.status === 'calculated' ? (
                  <button onClick={askApprove} disabled={busy} className="btn-primary min-h-[44px]">
                    <CheckCircle2 size={16} /> Approve
                  </button>
                ) : detail.status === 'approved' ? (
                  <button
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await erpAPI.markPayrollPaid(detail.id, {});
                        setMessage('Marked as paid.');
                        await load();
                      } catch (e) {
                        setError(e.response?.data?.detail || 'Could not mark as paid.');
                      } finally { setBusy(false); }
                    }}
                    className="btn-secondary min-h-[44px]"
                  >
                    <Banknote size={16} /> Mark paid
                  </button>
                ) : null
              }
            >
              {detail.lines.length === 0 ? (
                <Empty icon={Users} title="Nothing calculated"
                       hint="Set salaries first, then generate the month." />
              ) : (
                <div className="space-y-2">
                  {detail.lines.map((line) => (
                    <div key={line.id} className="rounded-xl bg-surface-2/60 p-3 flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-ink truncate">{line.name}</div>
                        <div className="text-xs text-muted truncate">
                          {line.employee_no ? `${line.employee_no} · ` : ''}{line.designation || ''}
                        </div>
                        {line.is_prorated && (
                          <div className="text-xs text-amber-400 mt-0.5">
                            {line.days_payable}/{line.days_in_month} days{line.note ? ` — ${line.note}` : ''}
                          </div>
                        )}
                      </div>
                      <div className="text-right shrink-0">
                        <div className="font-bold text-ink">{rupees(line.net)}</div>
                        {Number(line.deductions) + Number(line.advance_recovery) > 0 && (
                          <div className="text-xs text-muted">
                            gross {rupees(line.gross)}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </>
        )}

        <Panel title="Salaries" subtitle="Defined once. Payroll uses them every month until they are revised.">
          <div className="space-y-2">
            {(salaries || []).filter((s) => s.has_salary).map((s) => (
              <button
                key={s.id}
                onClick={() => setEditing({ ...s, basic: s.basic || '', effective_from: '', reason: '' })}
                className="w-full text-left rounded-xl bg-surface-2/60 hover:bg-surface-3 p-3 flex items-center gap-3 min-h-[56px] transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-ink truncate">{s.name}</div>
                  <div className="text-sm text-muted truncate">
                    {s.employee_no ? `${s.employee_no} · ` : ''}{s.designation || ''}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-semibold text-ink">{rupees(s.basic)}</div>
                  <div className="text-xs text-faint">from {s.effective_from}</div>
                </div>
              </button>
            ))}
          </div>
        </Panel>
      </div>

      {/* Set or revise a salary */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
             onClick={() => !busy && setEditing(null)}>
          <div className="glass-strong rounded-3xl w-full max-w-md p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div>
              <h3 className="text-xl font-bold text-ink">{editing.name}</h3>
              <p className="text-sm text-muted">{editing.designation || 'Staff'}</p>
            </div>
            <Field label="Basic salary (per month)" type="number" value={editing.basic}
                   onChange={(v) => setEditing((e) => ({ ...e, basic: v }))} required />
            <Field label="Effective from" type="date" value={editing.effective_from}
                   onChange={(v) => setEditing((e) => ({ ...e, effective_from: v }))}
                   hint="Leave blank for today. The previous salary is kept, not replaced." />
            <Field label="Reason" value={editing.reason}
                   onChange={(v) => setEditing((e) => ({ ...e, reason: v }))}
                   placeholder="Annual increment" />
            <div className="flex flex-col-reverse sm:flex-row gap-3 sm:justify-end pt-2">
              <button onClick={() => setEditing(null)} className="btn-secondary min-h-[48px]">Cancel</button>
              <button onClick={saveSalary} disabled={busy || !editing.basic} className="btn-primary min-h-[48px]">
                {busy ? <Loader2 size={16} className="animate-spin" /> : null} Save salary
              </button>
            </div>
          </div>
        </div>
      )}

      <Confirm
        open={!!confirm}
        title={confirm?.title}
        lines={confirm?.lines || []}
        confirmLabel={confirm?.confirmLabel}
        onConfirm={() => confirm?.run()}
        onCancel={() => setConfirm(null)}
        busy={busy}
      />
    </Layout>
  );
}
