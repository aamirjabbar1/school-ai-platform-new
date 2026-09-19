/**
 * Fee setup — what the school charges, and billing a month.
 *
 * Two jobs on one page because they are done together and rarely: set the
 * table once a year, then press Generate once a month.
 *
 * The grid is classes down, heads across, and it saves only what changed. The
 * increase tool always previews first — applying a percentage across a school
 * without seeing the old and new figures side by side is how a school finds out
 * it has doubled its nursery fee.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Drawer, Empty, Field, Note, Panel } from '../../components/erp/Kit';
import { Check, Loader2, Plus, Receipt, TrendingUp, Wand2 } from 'lucide-react';

const rupees = (v) => `Rs ${Number(v || 0).toLocaleString('en-PK')}`;
const thisMonth = () => new Date().toISOString().slice(0, 8) + '01';

export default function ErpFeeSetup() {
  const [loading, setLoading] = useState(true);
  const [grid, setGrid] = useState(null);
  const [edits, setEdits] = useState({});
  const [saving, setSaving] = useState(false);
  const [newHead, setNewHead] = useState(null);
  const [month, setMonth] = useState(thisMonth().slice(0, 7));
  const [classId, setClassId] = useState('');
  const [percent, setPercent] = useState('');
  const [preview, setPreview] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await erpAPI.feeStructure();
      setGrid(data);
      setEdits({});
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load the fee table.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const valueFor = (classId, headId) => {
    const key = `${classId}:${headId}`;
    return edits[key] !== undefined ? edits[key] : (grid?.amounts[key] ?? '0');
  };

  const setValue = (classId, headId, value) =>
    setEdits((e) => ({ ...e, [`${classId}:${headId}`]: value }));

  const saveGrid = async () => {
    setSaving(true);
    setError('');
    try {
      const entries = Object.entries(edits).map(([key, amount]) => {
        const [class_id, head_id] = key.split(':');
        return { class_id, head_id, amount: Number(amount) || 0 };
      });
      const { data } = await erpAPI.saveFeeStructure({ entries });
      setMessage(`${data.changed} fee${data.changed === 1 ? '' : 's'} saved.`);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const addHead = async () => {
    setBusy(true);
    try {
      await erpAPI.createFeeHead({
        code: newHead.code.trim().toUpperCase(),
        name: newHead.name.trim(),
        head_type: newHead.head_type,
      });
      setNewHead(null);
      setMessage('Fee head added.');
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not add that fee head.');
    } finally {
      setBusy(false);
    }
  };

  const askGenerate = () => {
    const label = new Date(`${month}-01`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    const className = grid.classes.find((c) => c.id === classId)?.canonical_name;
    setConfirm({
      title: `Generate vouchers for ${label}?`,
      lines: [
        className ? `For ${className} only.` : 'For every class in the school.',
        'Each student gets one voucher, with their concessions already applied.',
        'Anyone already billed for this month is skipped — this is safe to run twice.',
        'Unpaid amounts from earlier months are shown as arrears on the voucher.',
      ],
      confirmLabel: 'Generate vouchers',
      run: async () => {
        setBusy(true);
        try {
          const { data } = await erpAPI.generateVouchers({
            month: `${month}-01`,
            class_id: classId || undefined,
          });
          setMessage(
            `${data.created} voucher${data.created === 1 ? '' : 's'} generated` +
            `${data.skipped ? `, ${data.skipped} skipped` : ''} · ${rupees(data.total_amount)}.`,
          );
        } catch (e) {
          setError(e.response?.data?.detail || 'Could not generate vouchers.');
        } finally {
          setBusy(false);
          setConfirm(null);
        }
      },
    });
  };

  const runPreview = async () => {
    setBusy(true);
    setError('');
    try {
      const { data } = await erpAPI.applyFeeIncrease({
        percent: Number(percent), class_id: classId || undefined, preview_only: true,
      });
      setPreview(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not work out the increase.');
    } finally {
      setBusy(false);
    }
  };

  const askApplyIncrease = () => {
    setConfirm({
      title: `Increase fees by ${percent}%?`,
      lines: [
        `${preview.changes.length} fee amounts will change.`,
        'This changes what future vouchers charge. Vouchers already generated are not touched.',
        'Every change is recorded with who made it and when.',
      ],
      confirmLabel: `Apply ${percent}% increase`,
      run: async () => {
        setBusy(true);
        try {
          const { data } = await erpAPI.applyFeeIncrease({
            percent: Number(percent), class_id: classId || undefined, preview_only: false,
          });
          setMessage(`${data.applied} fees increased by ${percent}%.`);
          setPreview(null);
          setPercent('');
          await load();
        } catch (e) {
          setError(e.response?.data?.detail || 'Could not apply the increase.');
        } finally {
          setBusy(false);
          setConfirm(null);
        }
      },
    });
  };

  if (loading) return <Layout title="Fee setup"><Busy /></Layout>;
  if (!grid) return <Layout title="Fee setup"><Note kind="bad">{error}</Note></Layout>;

  const dirty = Object.keys(edits).length > 0;

  return (
    <Layout title="Fee setup">
      <div className="space-y-4 max-w-5xl pb-24">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        {/* ── Generate ── */}
        <Panel title="Generate this month’s vouchers" subtitle="Safe to press twice — nobody is billed for the same month more than once.">
          <div className="grid sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-sm font-medium text-ink mb-1.5">Month</span>
              <input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                className="w-full min-h-[44px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
              />
            </label>
            <Field
              label="Class"
              value={classId}
              onChange={setClassId}
              options={grid.classes.map((c) => ({ value: c.id, label: c.canonical_name }))}
              hint="Leave blank for the whole school"
            />
            <div className="flex items-end">
              <button onClick={askGenerate} disabled={busy} className="btn-primary w-full min-h-[44px]">
                <Receipt size={16} /> Generate
              </button>
            </div>
          </div>
        </Panel>

        {/* ── The grid ── */}
        <Panel
          title="What each class pays"
          subtitle={`Session ${grid.session.name}. Monthly amounts.`}
          action={
            <button onClick={() => setNewHead({ code: '', name: '', head_type: 'recurring' })}
                    className="btn-secondary min-h-[44px]">
              <Plus size={16} /> Fee head
            </button>
          }
        >
          {grid.heads.length === 0 ? (
            <Empty icon={Receipt} title="No fee heads yet"
                   hint="Add Tuition, Admission, Transport and anything else the school charges for." />
          ) : (
            <div className="overflow-x-auto -mx-2 px-2">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-2 pr-3 font-medium sticky left-0 bg-surface">Class</th>
                    {grid.heads.map((h) => (
                      <th key={h.id} className="py-2 px-2 font-medium whitespace-nowrap">{h.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {grid.classes.map((c) => (
                    <tr key={c.id} className="border-t border-line/40">
                      <td className="py-2 pr-3 font-medium text-ink whitespace-nowrap sticky left-0 bg-surface">
                        {c.canonical_name}
                      </td>
                      {grid.heads.map((h) => (
                        <td key={h.id} className="py-1.5 px-1">
                          <input
                            type="number"
                            value={valueFor(c.id, h.id)}
                            onChange={(e) => setValue(c.id, h.id, e.target.value)}
                            className="w-24 min-h-[40px] rounded-lg px-2 bg-surface-2 border border-line text-ink text-right
                                       focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {/* ── Increase ── */}
        <Panel title="Apply an approved increase" subtitle="You will see every old and new figure before anything changes.">
          <div className="grid sm:grid-cols-3 gap-3">
            <Field label="Increase by %" type="number" value={percent} onChange={setPercent} />
            <Field
              label="Class"
              value={classId}
              onChange={setClassId}
              options={grid.classes.map((c) => ({ value: c.id, label: c.canonical_name }))}
              hint="Leave blank for every class"
            />
            <div className="flex items-end">
              <button onClick={runPreview} disabled={busy || !percent} className="btn-secondary w-full min-h-[44px]">
                <TrendingUp size={16} /> Preview
              </button>
            </div>
          </div>

          {preview && (
            <div className="mt-4">
              {preview.changes.length === 0 ? (
                <Note kind="info">Nothing would change.</Note>
              ) : (
                <>
                  <div className="rounded-2xl bg-surface-2/60 p-3 max-h-72 overflow-y-auto space-y-1">
                    {preview.changes.map((c) => (
                      <div key={c.structure_id} className="flex items-center justify-between gap-3 text-sm py-1">
                        <span className="text-ink truncate">{c.class_name} · {c.head_name}</span>
                        <span className="shrink-0 text-muted">
                          {rupees(c.old)} → <span className="text-ink font-semibold">{rupees(c.new)}</span>
                        </span>
                      </div>
                    ))}
                  </div>
                  <button onClick={askApplyIncrease} className="btn-primary w-full min-h-[48px] mt-3">
                    <Wand2 size={16} /> Apply this increase
                  </button>
                </>
              )}
            </div>
          )}
        </Panel>
      </div>

      {dirty && (
        <div className="fixed bottom-0 left-0 right-0 z-40 p-3 glass-strong border-t border-line/60">
          <div className="max-w-5xl mx-auto flex items-center gap-3">
            <span className="text-sm text-muted flex-1">
              {Object.keys(edits).length} change{Object.keys(edits).length === 1 ? '' : 's'} not saved
            </span>
            <button onClick={() => setEdits({})} className="btn-secondary min-h-[48px]">Undo</button>
            <button onClick={saveGrid} disabled={saving} className="btn-primary min-h-[48px]">
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Save fees
            </button>
          </div>
        </div>
      )}

      <Drawer
        open={!!newHead}
        title="Add a fee head"
        subtitle="Anything the school charges for"
        onClose={() => setNewHead(null)}
        footer={
          <button onClick={addHead} disabled={busy || !newHead?.name?.trim()}
                  className="btn-primary w-full min-h-[48px]">
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} Add it
          </button>
        }
      >
        {newHead && (
          <>
            <Field
              label="Name"
              value={newHead.name}
              onChange={(v) => setNewHead((h) => ({
                ...h, name: v, code: v.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 10),
              }))}
              placeholder="Tuition Fee"
              required
            />
            <Field label="Short code" value={newHead.code}
                   onChange={(v) => setNewHead((h) => ({ ...h, code: v }))}
                   hint="Filled in for you. It appears on reports." />
            <Field
              label="Charged"
              value={newHead.head_type}
              onChange={(v) => setNewHead((h) => ({ ...h, head_type: v }))}
              options={[
                { value: 'recurring', label: 'Every month' },
                { value: 'one_time', label: 'Once — admission, security' },
              ]}
            />
          </>
        )}
      </Drawer>

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
