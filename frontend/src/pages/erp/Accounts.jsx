/**
 * Accounts.
 *
 * Almost nothing on this page is data entry, because almost nothing should be:
 * a fee received posts itself, an approved payroll posts itself. What is left
 * is recording an expense and reading the statements — so that is what the page
 * is, and the accounting vocabulary stays out of the way.
 *
 * "Money out" rather than "debit an expense account and credit cash". The
 * double entry happens; it just is not the accountant's problem at the moment
 * they are holding an electricity bill.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Empty, Field, Note, Panel, Stat } from '../../components/erp/Kit';
import {
  ArrowDownRight, ArrowUpRight, BookOpen, Loader2, Plus, Scale, TrendingUp,
} from 'lucide-react';

const rupees = (v) => `Rs ${Number(v || 0).toLocaleString('en-PK')}`;
const today = () => new Date().toISOString().slice(0, 10);

const TABS = [
  { key: 'expenses', label: 'Money out' },
  { key: 'pl', label: 'Income & expenses' },
  { key: 'balance', label: 'Balance sheet' },
  { key: 'trial', label: 'Trial balance' },
];

export default function ErpAccounts() {
  const [tab, setTab] = useState('expenses');
  const [chart, setChart] = useState([]);
  const [expenses, setExpenses] = useState(null);
  const [pl, setPl] = useState(null);
  const [balance, setBalance] = useState(null);
  const [trial, setTrial] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await erpAPI.chartOfAccounts();
      setChart(data.accounts);
      const { data: exp } = await erpAPI.expenses({});
      setExpenses(exp);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load accounts.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    (async () => {
      try {
        if (tab === 'pl' && !pl) setPl((await erpAPI.profitAndLoss({})).data);
        if (tab === 'balance' && !balance) setBalance((await erpAPI.balanceSheet({})).data);
        if (tab === 'trial' && !trial) setTrial((await erpAPI.trialBalance({})).data);
      } catch (e) {
        setError(e.response?.data?.detail || 'Could not load that statement.');
      }
    })();
  }, [tab]);

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await erpAPI.recordExpense({
        expense_date: form.expense_date,
        account_id: form.account_id,
        amount: Number(form.amount),
        paid_from: form.paid_from,
        description: form.description || undefined,
      });
      setMessage('Expense recorded. The accounting entry was posted automatically.');
      setForm(null);
      setPl(null); setBalance(null); setTrial(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not record that expense.');
    } finally {
      setBusy(false);
    }
  };

  const expenseAccounts = chart.filter((a) => a.account_type === 'expense' && a.is_postable);

  if (loading) return <Layout title="Accounts"><Busy /></Layout>;

  return (
    <Layout title="Accounts">
      <div className="space-y-4 max-w-4xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <div className="flex gap-2 overflow-x-auto pb-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 min-h-[44px] rounded-xl whitespace-nowrap text-sm font-medium transition-colors
                          ${tab === t.key ? 'btn-primary' : 'btn-secondary'}`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Expenses ── */}
        {tab === 'expenses' && (
          <>
            <Panel
              title="Money out"
              subtitle="Record what the school paid for. The accounting entry writes itself."
              action={
                <button
                  onClick={() => setForm({
                    expense_date: today(), account_id: '', amount: '',
                    paid_from: 'cash', description: '',
                  })}
                  className="btn-primary min-h-[44px]"
                >
                  <Plus size={16} /> Record
                </button>
              }
            >
              {!expenses?.expenses?.length ? (
                <Empty icon={ArrowDownRight} title="Nothing recorded yet"
                       hint="Electricity, repairs, stationery — anything the school pays for." />
              ) : (
                <>
                  <p className="text-sm text-muted mb-3">{rupees(expenses.total)} in this period</p>
                  <div className="space-y-2">
                    {expenses.expenses.map((e) => (
                      <div key={e.id} className="rounded-xl bg-surface-2/60 p-3 flex items-center gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-ink truncate">{e.account_name}</div>
                          <div className="text-sm text-muted truncate">
                            {e.expense_date} · {e.description || e.expense_no}
                          </div>
                        </div>
                        <div className="font-semibold text-ink shrink-0">{rupees(e.amount)}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Panel>

            {form && (
              <Panel title="Record money out">
                <div className="grid sm:grid-cols-2 gap-4">
                  <Field label="Date" type="date" value={form.expense_date}
                         onChange={(v) => setForm((f) => ({ ...f, expense_date: v }))} />
                  <Field label="Amount" type="number" value={form.amount}
                         onChange={(v) => setForm((f) => ({ ...f, amount: v }))} required />
                  <Field label="What for" value={form.account_id}
                         onChange={(v) => setForm((f) => ({ ...f, account_id: v }))}
                         options={expenseAccounts.map((a) => ({ value: a.id, label: a.name }))}
                         required />
                  <Field label="Paid from" value={form.paid_from}
                         onChange={(v) => setForm((f) => ({ ...f, paid_from: v }))}
                         options={[
                           { value: 'cash', label: 'Cash' },
                           { value: 'bank', label: 'Bank' },
                           { value: 'cheque', label: 'Cheque' },
                         ]} />
                </div>
                <div className="mt-4">
                  <Field label="Note" value={form.description}
                         onChange={(v) => setForm((f) => ({ ...f, description: v }))}
                         placeholder="September electricity bill" />
                </div>
                <div className="flex flex-col sm:flex-row gap-3 mt-5">
                  <button onClick={() => setForm(null)} className="btn-secondary flex-1 min-h-[48px]">Cancel</button>
                  <button onClick={save} disabled={busy || !form.amount || !form.account_id}
                          className="btn-primary flex-1 min-h-[48px]">
                    {busy ? <Loader2 size={16} className="animate-spin" /> : null} Record it
                  </button>
                </div>
              </Panel>
            )}
          </>
        )}

        {/* ── Profit and loss ── */}
        {tab === 'pl' && (pl ? (
          <>
            <div className="grid sm:grid-cols-3 gap-3">
              <Stat icon={ArrowUpRight} value={rupees(pl.total_income)} label="income" />
              <Stat icon={ArrowDownRight} value={rupees(pl.total_expenses)} label="expenses" tone="warn" />
              <Stat icon={TrendingUp} value={rupees(pl.surplus)} label="surplus" />
            </div>
            <Panel title="Income" subtitle={`${pl.from} to ${pl.to}`}>
              <Rows rows={pl.income} empty="No income recorded yet." />
            </Panel>
            <Panel title="Expenses">
              <Rows rows={pl.expenses} empty="No expenses recorded yet." />
            </Panel>
          </>
        ) : <Busy />)}

        {/* ── Balance sheet ── */}
        {tab === 'balance' && (balance ? (
          <>
            {!balance.balanced && (
              <Note kind="bad">
                This balance sheet does not balance. That is a problem with the books,
                not with the page — tell whoever maintains the system.
              </Note>
            )}
            <Panel title="What the school owns" subtitle={`As at ${balance.as_at}`}>
              <Rows rows={balance.assets} total={balance.total_assets} empty="Nothing recorded yet." />
            </Panel>
            <Panel title="What the school owes">
              <Rows rows={balance.liabilities} total={balance.total_liabilities} empty="Nothing owed." />
            </Panel>
            <Panel title="Equity">
              <Rows rows={balance.equity} total={balance.total_equity} empty="Nothing recorded." />
              <div className="flex justify-between pt-3 mt-3 border-t border-line/60">
                <span className="text-muted">Surplus this year</span>
                <span className="font-semibold text-ink">{rupees(balance.surplus_this_year)}</span>
              </div>
            </Panel>
          </>
        ) : <Busy />)}

        {/* ── Trial balance ── */}
        {tab === 'trial' && (trial ? (
          <Panel
            title="Trial balance"
            subtitle={trial.balanced ? 'Debits equal credits.' : 'Debits and credits disagree.'}
          >
            {!trial.balanced && (
              <Note kind="bad">The ledger does not balance. This should never happen.</Note>
            )}
            {trial.rows.length === 0 ? (
              <Empty icon={Scale} title="Nothing posted yet"
                     hint="Entries appear here as fees are received and expenses recorded." />
            ) : (
              <div className="space-y-1">
                {trial.rows.map((r) => (
                  <div key={r.code} className="flex items-center gap-3 py-2 border-b border-line/40 last:border-0">
                    <span className="text-xs text-faint font-mono w-12 shrink-0">{r.code}</span>
                    <span className="flex-1 min-w-0 text-ink truncate">{r.name}</span>
                    <span className="text-sm text-muted shrink-0">{rupees(r.balance)}</span>
                  </div>
                ))}
                <div className="flex justify-between pt-3 font-semibold text-ink">
                  <span>Total</span>
                  <span>{rupees(trial.total_debit)}</span>
                </div>
              </div>
            )}
          </Panel>
        ) : <Busy />)}
      </div>
    </Layout>
  );
}

function Rows({ rows, total, empty }) {
  if (!rows?.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.code} className="flex items-center justify-between gap-3 py-1.5">
          <span className="text-ink truncate">{r.name}</span>
          <span className="text-muted shrink-0">{rupees(r.amount)}</span>
        </div>
      ))}
      {total !== undefined && (
        <div className="flex justify-between pt-3 mt-2 border-t border-line/60 font-semibold text-ink">
          <span>Total</span>
          <span>{rupees(total)}</span>
        </div>
      )}
    </div>
  );
}
