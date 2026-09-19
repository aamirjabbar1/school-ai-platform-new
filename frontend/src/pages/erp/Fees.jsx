/**
 * Fee collection — the counter.
 *
 * A parent is standing there. So the screen is: type a name or GR number, see
 * what they owe, take the money, hand over a receipt. Three taps, and the
 * amount is filled in already because the system knows what is owed.
 *
 * The one thing it will not do is let a payment be taken twice by accident: the
 * server keys on the bank reference, and the screen locks the button while the
 * request is in flight. A double-tap at a counter is not a hypothetical.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Empty, Field, Note, Panel, Stat } from '../../components/erp/Kit';
import {
  Banknote, CheckCircle2, Coins, Loader2, Receipt, Search, TrendingUp, Users,
} from 'lucide-react';

const METHODS = [
  { value: 'cash', label: 'Cash' },
  { value: 'bank', label: 'Bank transfer' },
  { value: 'online', label: 'Online / Quick Pay' },
  { value: 'cheque', label: 'Cheque' },
];

const rupees = (value) =>
  `Rs ${Number(value || 0).toLocaleString('en-PK', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

export default function ErpFees() {
  const [summary, setSummary] = useState(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [student, setStudent] = useState(null);
  const [ledger, setLedger] = useState(null);
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState('cash');
  const [reference, setReference] = useState('');
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState('');

  const loadSummary = async () => {
    try {
      const { data } = await erpAPI.feeSummary();
      setSummary(data);
    } catch { /* the counter still works without today's total */ }
  };

  useEffect(() => { loadSummary(); }, []);

  useEffect(() => {
    if (!query.trim()) { setResults([]); return undefined; }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const { data } = await erpAPI.feeSearchStudent({ q: query });
        setResults(data.students);
      } catch (e) {
        setError(e.response?.data?.detail || 'Search failed.');
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const pick = async (entry) => {
    setStudent(entry);
    setResults([]);
    setQuery('');
    setDone(null);
    setError('');
    setAmount(entry.outstanding && Number(entry.outstanding) > 0 ? String(entry.outstanding) : '');
    try {
      const { data } = await erpAPI.feeLedger(entry.id);
      setLedger(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load the fee account.');
    }
  };

  const askTake = () => {
    const value = Number(amount);
    if (!value || value <= 0) { setError('Enter the amount being paid.'); return; }
    const owed = Number(ledger?.account?.outstanding || 0);
    setConfirm({
      title: `Take ${rupees(value)} from ${student.name}?`,
      lines: [
        `Outstanding before this payment: ${rupees(owed)}.`,
        value > owed
          ? `This is ${rupees(value - owed)} more than owed — the extra is kept as an advance against next month.`
          : `Outstanding after this payment: ${rupees(owed - value)}.`,
        `Paid by ${METHODS.find((m) => m.value === method)?.label.toLowerCase()}.`,
        'A receipt number is issued and the oldest unpaid month is settled first.',
      ],
      confirmLabel: 'Take the payment',
    });
  };

  const take = async () => {
    setBusy(true);
    setError('');
    try {
      const { data } = await erpAPI.receivePayment({
        student_user_id: student.id,
        amount: Number(amount),
        method,
        bank_reference: reference.trim() || undefined,
      });
      setDone(data);
      setAmount('');
      setReference('');
      const { data: fresh } = await erpAPI.feeLedger(student.id);
      setLedger(fresh);
      loadSummary();
    } catch (e) {
      setError(e.response?.data?.detail || 'The payment was not taken. Nothing was changed.');
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  return (
    <Layout title="Fee collection">
      <div className="space-y-4 max-w-4xl">
        {error && <Note kind="bad">{error}</Note>}

        {summary && (
          <div className="grid sm:grid-cols-3 gap-3">
            <Stat icon={Coins} value={rupees(summary.collected_today)} label={`collected today · ${summary.receipts_today} receipts`} />
            <Stat icon={TrendingUp} value={rupees(summary.collected_this_month)} label="collected this month" />
            <Stat icon={Users} value={rupees(summary.outstanding)} label={`outstanding · ${summary.defaulters} students`} tone="warn" />
          </div>
        )}

        <Panel title="Who is paying?">
          <div className="relative">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="GR number, name or father’s name…"
              className="w-full min-h-[52px] rounded-xl pl-10 pr-3 bg-surface-2 border border-line text-ink text-lg
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            />
          </div>

          {searching && <p className="text-sm text-muted mt-2">Searching…</p>}

          {results.length > 0 && (
            <div className="space-y-2 mt-3">
              {results.map((r) => (
                <button
                  key={r.id}
                  onClick={() => pick(r)}
                  className="w-full text-left rounded-xl bg-surface-2 hover:bg-surface-3 p-3 flex items-center gap-3 min-h-[60px] transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink truncate">{r.name}</div>
                    <div className="text-sm text-muted truncate">
                      {r.gr_no ? `GR ${r.gr_no} · ` : ''}{r.class_name || ''}
                      {r.father_name ? ` · ${r.father_name}` : ''}
                    </div>
                  </div>
                  <div className={`text-sm font-bold shrink-0 ${Number(r.outstanding) > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {rupees(r.outstanding)}
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>

        {student && ledger && (
          <>
            {done && (
              <Panel>
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-2xl bg-emerald-500/15 text-emerald-400 flex items-center justify-center shrink-0">
                    <CheckCircle2 size={26} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-bold text-ink text-lg">
                      {done.duplicate ? 'Already received' : `Receipt ${done.receipt_no}`}
                    </div>
                    <div className="text-sm text-muted">
                      {done.duplicate
                        ? 'This exact payment was already recorded — nothing was taken twice.'
                        : `${rupees(done.amount)} received from ${student.name}.`}
                    </div>
                  </div>
                  <button onClick={() => window.print()} className="btn-secondary min-h-[44px] shrink-0">
                    <Receipt size={16} /> Print
                  </button>
                </div>
              </Panel>
            )}

            <Panel
              title={student.name}
              subtitle={`${student.gr_no ? `GR ${student.gr_no} · ` : ''}${student.class_name || ''}`}
            >
              <div className="rounded-2xl bg-surface-2/60 p-4 mb-4 flex items-center justify-between">
                <span className="text-muted">Outstanding</span>
                <span className={`text-2xl font-bold ${Number(ledger.account.outstanding) > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {rupees(ledger.account.outstanding)}
                </span>
              </div>
              {Number(ledger.account.advance) > 0 && (
                <Note kind="good">
                  {rupees(ledger.account.advance)} paid in advance — it comes off the next voucher.
                </Note>
              )}

              <div className="grid sm:grid-cols-2 gap-4 mt-4">
                <Field label="Amount being paid" type="number" value={amount} onChange={setAmount} />
                <Field label="How" value={method} onChange={setMethod} options={METHODS} />
              </div>
              {method !== 'cash' && (
                <div className="mt-4">
                  <Field
                    label="Bank / transaction reference"
                    value={reference}
                    onChange={setReference}
                    hint="Optional, but it stops the same transfer being recorded twice."
                  />
                </div>
              )}

              <button
                onClick={askTake}
                disabled={busy || !amount}
                className="btn-primary w-full min-h-[52px] mt-5 text-base"
              >
                {busy ? <Loader2 size={18} className="animate-spin" /> : <Banknote size={18} />}
                Take payment
              </button>
            </Panel>

            <Panel title="Statement" subtitle="Everything charged and everything paid.">
              {ledger.entries.length === 0 ? (
                <Empty icon={Receipt} title="Nothing yet"
                       hint="Vouchers and payments appear here as they happen." />
              ) : (
                <div className="space-y-1">
                  {[...ledger.entries].reverse().map((e) => (
                    <div key={e.id} className="flex items-center gap-3 py-2 border-b border-line/40 last:border-0">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-ink truncate">{e.description}</div>
                        <div className="text-xs text-faint">{e.date}</div>
                      </div>
                      <div className="text-right shrink-0">
                        {Number(e.debit) > 0 && <div className="text-sm text-rose-400">+{rupees(e.debit)}</div>}
                        {Number(e.credit) > 0 && <div className="text-sm text-emerald-400">−{rupees(e.credit)}</div>}
                        <div className="text-xs text-faint">bal {rupees(e.balance)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </>
        )}

        {!student && !searching && query === '' && (
          <Empty icon={Search} title="Search for a student to take a payment"
                 hint="Type a GR number, a name, or a father’s name." />
        )}
      </div>

      <Confirm
        open={!!confirm}
        title={confirm?.title}
        lines={confirm?.lines || []}
        confirmLabel={confirm?.confirmLabel}
        onConfirm={take}
        onCancel={() => setConfirm(null)}
        busy={busy}
      />
    </Layout>
  );
}
