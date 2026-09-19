/**
 * People & access — the Owner's screen.
 *
 * Roles are described in the words of the job ("Runs examinations end to end"),
 * not as a grid of forty permission checkboxes. The person deciding who the
 * Accounts Manager is should not have to understand `fee.voucher` to do it.
 *
 * The permission list is still there, underneath, for anyone who wants to look.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Empty, Note, Panel } from '../../components/erp/Kit';
import { ChevronDown, ShieldCheck, UserPlus, X } from 'lucide-react';

export default function ErpAccess() {
  const [loading, setLoading] = useState(true);
  const [roles, setRoles] = useState([]);
  const [catalogue, setCatalogue] = useState([]);
  const [people, setPeople] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  // The grant form: choose a person, choose a role, confirm.
  const [pickPerson, setPickPerson] = useState('');
  const [pickRole, setPickRole] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: r }, { data: p }] = await Promise.all([erpAPI.roles(), erpAPI.people()]);
      setRoles(r.roles);
      setCatalogue(r.catalogue);
      setPeople(p.people);
      setCandidates(p.candidates);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load access settings.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const describe = (key) => catalogue.find((c) => c.key === key)?.description || key;

  const askGrant = () => {
    const person = [...people, ...candidates].find((p) => p.id === pickPerson);
    const role = roles.find((r) => r.key === pickRole);
    if (!person || !role) return;
    setConfirm({
      title: `Make ${person.name} the ${role.name}?`,
      lines: [
        role.description,
        `${person.name} will be able to do ${role.permissions.length} things they cannot do today.`,
        'Their login and password do not change.',
        'You can remove this at any time.',
      ],
      confirmLabel: `Yes, make them ${role.name}`,
      run: async () => {
        setBusy(true);
        try {
          const { data } = await erpAPI.grantRole({ user_id: person.id, role_key: role.key });
          setMessage(data.message);
          setPickPerson(''); setPickRole('');
          await load();
        } catch (e) {
          setError(e.response?.data?.detail || 'Could not grant that role.');
        } finally {
          setBusy(false);
          setConfirm(null);
        }
      },
    });
  };

  const askRevoke = (person, role) => {
    setConfirm({
      title: `Remove ${role.name} from ${person.name}?`,
      lines: [
        `${person.name} will lose the access that role gives.`,
        'Their account, login and everything they have already done stay exactly as they are.',
      ],
      confirmLabel: 'Remove the role',
      danger: true,
      run: async () => {
        setBusy(true);
        try {
          await erpAPI.revokeRole({ user_id: person.id, role_key: role.key });
          setMessage(`${role.name} removed from ${person.name}.`);
          await load();
        } catch (e) {
          setError(e.response?.data?.detail || 'Could not remove that role.');
        } finally {
          setBusy(false);
          setConfirm(null);
        }
      },
    });
  };

  if (loading) return <Layout title="People & access"><Busy /></Layout>;

  return (
    <Layout title="People & access">
      <div className="space-y-4 max-w-4xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <Panel title="Give someone a role" subtitle="Three steps: who, what, confirm.">
          <div className="grid sm:grid-cols-2 gap-3">
            <select
              value={pickPerson}
              onChange={(e) => setPickPerson(e.target.value)}
              className="min-h-[48px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            >
              <option value="">1. Choose a person…</option>
              {[...people, ...candidates]
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((p) => <option key={p.id} value={p.id}>{p.name} ({p.login_id})</option>)}
            </select>
            <select
              value={pickRole}
              onChange={(e) => setPickRole(e.target.value)}
              className="min-h-[48px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            >
              <option value="">2. Choose a role…</option>
              {roles.map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}
            </select>
          </div>
          {pickRole && (
            <p className="text-sm text-muted mt-3">
              {roles.find((r) => r.key === pickRole)?.description}
            </p>
          )}
          <button
            onClick={askGrant}
            disabled={!pickPerson || !pickRole}
            className="btn-primary mt-4 min-h-[48px] w-full sm:w-auto"
          >
            <UserPlus size={18} /> 3. Give them this role
          </button>
        </Panel>

        <Panel title="Who has access" subtitle={`${people.length} people hold an ERP role`}>
          {people.length === 0 ? (
            <Empty icon={ShieldCheck} title="Nobody has an ERP role yet"
                   hint="Your admin accounts can already use the ERP. Add roles above to give other people access." />
          ) : (
            <div className="space-y-2">
              {people.map((p) => (
                <div key={p.id} className="rounded-2xl bg-surface-2/60 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink">{p.name}</div>
                    <div className="text-sm text-muted">{p.login_id}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {p.roles.map((r) => (
                      <span key={r.key} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl
                                                   bg-brand-blue/15 text-sm text-ink">
                        {r.name}
                        <button
                          onClick={() => askRevoke(p, roles.find((x) => x.key === r.key) || r)}
                          className="text-faint hover:text-rose-400 p-0.5"
                          aria-label={`Remove ${r.name}`}
                        >
                          <X size={14} />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="What each role can do" subtitle="Tap a role to see the detail.">
          <div className="space-y-2">
            {roles.map((r) => (
              <div key={r.key} className="rounded-2xl bg-surface-2/60 overflow-hidden">
                <button
                  onClick={() => setExpanded(expanded === r.key ? null : r.key)}
                  className="w-full p-4 flex items-center gap-3 text-left min-h-[60px]"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink">{r.name}</div>
                    <div className="text-sm text-muted">{r.description}</div>
                  </div>
                  <span className="text-sm text-faint shrink-0">{r.people} {r.people === 1 ? 'person' : 'people'}</span>
                  <ChevronDown
                    size={18}
                    className={`text-faint shrink-0 transition-transform ${expanded === r.key ? 'rotate-180' : ''}`}
                  />
                </button>
                {expanded === r.key && (
                  <ul className="px-4 pb-4 space-y-1">
                    {r.permissions.map((key) => (
                      <li key={key} className="text-sm text-muted flex gap-2">
                        <span className="text-brand-cyan">•</span>{describe(key)}
                      </li>
                    ))}
                    {r.permissions.length === 0 && (
                      <li className="text-sm text-faint">Sees only their own records.</li>
                    )}
                  </ul>
                )}
              </div>
            ))}
          </div>
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
