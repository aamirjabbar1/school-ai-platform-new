/**
 * ERP settings — the Owner's switches.
 *
 * Two things live here, and both are things a school changes once and then
 * forgets: how institutional numbers are formed, and whether the ERP is
 * visible to anyone besides the Owner.
 *
 * The number format shows a live example rather than explaining the syntax.
 * "LSS-{seq:05d}" means nothing; "the next one will be LSS-00001" means
 * everything.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Note, Panel } from '../../components/erp/Kit';
import { Check, Hash, Loader2, Power } from 'lucide-react';

export default function ErpSettings() {
  const [loading, setLoading] = useState(true);
  const [series, setSeries] = useState([]);
  const [flags, setFlags] = useState([]);
  const [edits, setEdits] = useState({});
  const [savingScope, setSavingScope] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: n }, { data: f }] = await Promise.all([erpAPI.numbering(), erpAPI.flags()]);
      setSeries(n);
      setFlags(f);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load settings.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const saveSeries = async (scope) => {
    const edit = edits[scope];
    if (!edit) return;
    setSavingScope(scope);
    setError('');
    try {
      await erpAPI.updateNumbering(scope, edit);
      setMessage('Saved.');
      setEdits((e) => ({ ...e, [scope]: undefined }));
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save that.');
    } finally {
      setSavingScope(null);
    }
  };

  const askToggle = (flag) => {
    const turningOn = !flag.enabled;
    setConfirm({
      title: turningOn ? 'Switch the ERP on for the school?' : 'Switch the ERP off?',
      lines: turningOn
        ? [
            'Everyone with an ERP role will see the ERP from their next page load.',
            'Students and teachers see nothing new unless you give them a role.',
            'Nothing in LSS Bot changes — classes, lessons and the chatbot carry on exactly as they are.',
            'You can switch it off again at any time, instantly.',
          ]
        : [
            'Only you will be able to see the ERP again.',
            'Nothing is deleted. Every record stays exactly as it is.',
          ],
      confirmLabel: turningOn ? 'Switch it on' : 'Switch it off',
      danger: !turningOn,
      run: async () => {
        setBusy(true);
        try {
          await erpAPI.updateFlag(flag.key, { enabled: turningOn });
          setMessage(turningOn ? 'The ERP is now on for the school.' : 'The ERP is off again.');
          await load();
        } catch (e) {
          setError(e.response?.data?.detail || 'Could not change that.');
        } finally {
          setBusy(false);
          setConfirm(null);
        }
      },
    });
  };

  if (loading) return <Layout title="ERP settings"><Busy /></Layout>;

  return (
    <Layout title="ERP settings">
      <div className="space-y-4 max-w-3xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <Panel title="Who can see the ERP" subtitle="While it is off, only you can open it.">
          <div className="space-y-3">
            {flags.map((flag) => (
              <div key={flag.key} className="rounded-2xl bg-surface-2/60 p-4 flex items-center gap-4">
                <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shrink-0
                                ${flag.enabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-surface-3 text-faint'}`}>
                  <Power size={20} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink">
                    {flag.key === 'erp' ? 'School ERP' : flag.key}
                  </div>
                  <div className="text-sm text-muted">
                    {flag.enabled ? 'On for everyone with a role' : 'Off — only you can see it'}
                  </div>
                </div>
                <button
                  onClick={() => askToggle(flag)}
                  className={`${flag.enabled ? 'btn-secondary' : 'btn-primary'} min-h-[44px] shrink-0`}
                >
                  {flag.enabled ? 'Switch off' : 'Switch on'}
                </button>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Numbers" subtitle="How GR, admission and employee numbers are formed.">
          <div className="space-y-3">
            {series.map((s) => {
              const edit = edits[s.scope] || {};
              const dirty = edit.pattern !== undefined || edit.next_value !== undefined;
              return (
                <div key={s.scope} className="rounded-2xl bg-surface-2/60 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Hash size={16} className="text-brand-cyan" />
                    <span className="font-semibold text-ink">{s.label || s.scope}</span>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-3">
                    <label className="block">
                      <span className="block text-xs text-muted mb-1">Format</span>
                      <input
                        value={edit.pattern ?? s.pattern}
                        onChange={(e) => setEdits((x) => ({ ...x, [s.scope]: { ...edit, pattern: e.target.value } }))}
                        className="w-full min-h-[44px] rounded-xl px-3 bg-surface border border-line text-ink font-mono text-sm
                                   focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
                      />
                    </label>
                    <label className="block">
                      <span className="block text-xs text-muted mb-1">Next number</span>
                      <input
                        type="number"
                        min="1"
                        value={edit.next_value ?? s.next_value}
                        onChange={(e) => setEdits((x) => ({ ...x, [s.scope]: { ...edit, next_value: Number(e.target.value) } }))}
                        className="w-full min-h-[44px] rounded-xl px-3 bg-surface border border-line text-ink
                                   focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
                      />
                    </label>
                  </div>

                  <div className="flex items-center justify-between gap-3 mt-3">
                    <p className="text-sm text-muted">
                      The next one will be <strong className="text-ink font-mono">{s.preview}</strong>
                    </p>
                    {dirty && (
                      <button
                        onClick={() => saveSeries(s.scope)}
                        disabled={savingScope === s.scope}
                        className="btn-primary min-h-[44px] shrink-0"
                      >
                        {savingScope === s.scope
                          ? <Loader2 size={16} className="animate-spin" />
                          : <Check size={16} />}
                        Save
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-faint mt-4">
            Use <code className="font-mono">{'{seq}'}</code> where the number goes.
            <code className="font-mono"> {'{seq:05d}'}</code> pads it to five digits — 00001, 00002, and so on.
          </p>
        </Panel>
      </div>

      <Confirm
        open={!!confirm}
        title={confirm?.title}
        lines={confirm?.lines || []}
        confirmLabel={confirm?.confirmLabel}
        danger={confirm?.danger}
        onConfirm={() => confirm?.run()}
        onCancel={() => setConfirm(null)}
        busy={busy}
      />
    </Layout>
  );
}
