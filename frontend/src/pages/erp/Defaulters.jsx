/**
 * Defaulter List — All (Active).
 *
 * The specification asks for the whole school's active defaulters in minimal
 * clicks, so the page loads it immediately: no filters to set first, no
 * "Generate" to press. Filters narrow what is already on screen.
 *
 * Export is CSV, built in the browser from the rows already fetched — no
 * second request, and it opens in Excel.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Empty, Note, Panel, Stat } from '../../components/erp/Kit';
import { Coins, Download, Printer, Users } from 'lucide-react';

const rupees = (v) => `Rs ${Number(v || 0).toLocaleString('en-PK')}`;

const AGING_LABEL = {
  '0-30': 'Up to a month',
  '31-60': '1–2 months',
  '61-90': '2–3 months',
  '91-180': '3–6 months',
  '180+': 'Over 6 months',
};

const AGING_TONE = {
  '0-30': 'text-amber-400',
  '31-60': 'text-orange-400',
  '61-90': 'text-rose-400',
  '91-180': 'text-rose-500',
  '180+': 'text-rose-600',
};

export default function ErpDefaulters() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [classes, setClasses] = useState([]);
  const [classId, setClassId] = useState('');
  const [minAmount, setMinAmount] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await erpAPI.defaulters({
        class_id: classId || undefined,
        min_amount: minAmount || undefined,
      });
      setData(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load the defaulter list.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { erpAPI.classes().then(({ data }) => setClasses(data)).catch(() => {}); }, []);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [classId, minAmount]);

  const exportCsv = () => {
    const header = [
      'GR No', 'Admission No', 'Student', 'Father', 'Class', 'Section',
      'Outstanding', 'Unpaid months', 'Oldest unpaid', 'Days overdue', 'Last payment',
    ];
    const rows = data.students.map((s) => [
      s.gr_no || '', s.admission_no || '', s.name, s.father_name || '',
      s.class_name || '', s.section_name || '', s.outstanding, s.unpaid_months,
      s.oldest_unpaid_month || '', s.days_overdue, s.last_payment_on || '',
    ]);
    const csv = [header, ...rows]
      .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n');

    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `defaulters-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Layout title="Fee defaulters">
      <div className="space-y-4 max-w-5xl">
        {error && <Note kind="bad">{error}</Note>}

        {data && (
          <div className="grid sm:grid-cols-2 gap-3">
            <Stat icon={Users} value={data.total} label="students owing money" tone="warn" />
            <Stat icon={Coins} value={rupees(data.total_outstanding)} label="total outstanding" tone="warn" />
          </div>
        )}

        <Panel>
          <div className="flex flex-col sm:flex-row gap-3">
            <select
              value={classId}
              onChange={(e) => setClassId(e.target.value)}
              className="flex-1 min-h-[44px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            >
              <option value="">All classes</option>
              {classes.map((c) => <option key={c.id} value={c.id}>{c.canonical_name}</option>)}
            </select>
            <input
              type="number"
              value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)}
              placeholder="Owing at least…"
              className="sm:w-48 min-h-[44px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            />
            <div className="flex gap-2">
              <button onClick={exportCsv} disabled={!data?.students?.length}
                      className="btn-secondary min-h-[44px]">
                <Download size={16} /> Excel
              </button>
              <button onClick={() => window.print()} className="btn-secondary min-h-[44px]">
                <Printer size={16} /> Print
              </button>
            </div>
          </div>

          {data?.aging && Object.keys(data.aging).length > 0 && (
            <div className="flex flex-wrap gap-2 mt-4">
              {Object.entries(data.aging).map(([bucket, count]) => (
                <span key={bucket} className="px-3 py-1.5 rounded-xl bg-surface-2 text-sm">
                  <span className={`font-bold ${AGING_TONE[bucket] || 'text-ink'}`}>{count}</span>
                  <span className="text-muted"> · {AGING_LABEL[bucket] || bucket}</span>
                </span>
              ))}
            </div>
          )}
        </Panel>

        {loading ? (
          <Busy label="Working out who owes what…" />
        ) : !data?.students?.length ? (
          <Empty icon={Coins} title="Nobody owes anything"
                 hint="Either every fee is paid, or vouchers have not been generated yet." />
        ) : (
          <div className="space-y-2">
            {data.students.map((s) => (
              <div key={s.id} className="card flex items-center gap-4 min-h-[76px]">
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink truncate">{s.name}</div>
                  <div className="text-sm text-muted truncate">
                    {s.gr_no ? `GR ${s.gr_no} · ` : ''}
                    {s.class_name || ''}{s.section_name ? ` ${s.section_name}` : ''}
                    {s.father_name ? ` · ${s.father_name}` : ''}
                  </div>
                  <div className="text-xs mt-1">
                    <span className={AGING_TONE[s.aging] || 'text-muted'}>
                      {s.unpaid_months} month{s.unpaid_months === 1 ? '' : 's'} unpaid
                    </span>
                    {s.last_payment_on && (
                      <span className="text-faint"> · last paid {s.last_payment_on}</span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-lg font-bold text-rose-400">{rupees(s.outstanding)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
