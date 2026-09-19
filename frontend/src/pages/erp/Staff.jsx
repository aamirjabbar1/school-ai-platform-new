/**
 * Staff.
 *
 * The same shape as Students, with one difference that matters: CNIC and bank
 * details are only fetched and only editable for someone entitled to see them.
 * The server decides that (`sensitive_visible`), not this file — a field hidden
 * only in the browser is not hidden.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Drawer, Empty, Field, Missing, Note, Panel } from '../../components/erp/Kit';
import { GraduationCap, Loader2, Search } from 'lucide-react';

export default function ErpStaff() {
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [onlyIncomplete, setOnlyIncomplete] = useState(false);
  const [data, setData] = useState({ staff: [], total: 0, sensitive_visible: false });
  const [open, setOpen] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await erpAPI.staff({
        q: query || undefined,
        needs_attention: onlyIncomplete || undefined,
      });
      setData(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load staff.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [query, onlyIncomplete]);

  const openStaff = (person) => {
    setError('');
    setOpen(person);
    setForm({
      employee_no: person.employee_no || '',
      designation: person.designation || '',
      department: person.department || '',
      joining_date: person.joining_date || '',
      employment_type: person.employment_type || '',
      qualification: person.qualification || '',
      phone: person.phone || '',
      cnic: person.cnic || '',
      bank_name: person.bank_name || '',
      bank_iban: person.bank_iban || '',
    });
  };

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const payload = { ...form };
      Object.keys(payload).forEach((k) => { if (payload[k] === '') delete payload[k]; });
      await erpAPI.updateStaff(open.id, payload);
      setMessage(`${open.name} saved.`);
      setOpen(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const setF = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Layout title="Staff">
      <div className="space-y-4 max-w-5xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <Panel>
          <div className="relative">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, employee number or designation…"
              className="w-full min-h-[48px] rounded-xl pl-10 pr-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            />
          </div>
          <label className="flex items-center gap-2 mt-3 text-sm text-muted cursor-pointer select-none">
            <input
              type="checkbox"
              checked={onlyIncomplete}
              onChange={(e) => setOnlyIncomplete(e.target.checked)}
              className="w-4 h-4 accent-brand-cyan"
            />
            Only show staff with something missing
          </label>
        </Panel>

        {loading ? (
          <Busy label="Loading staff…" />
        ) : data.staff.length === 0 ? (
          <Empty icon={GraduationCap} title="No staff found"
                 hint="Run setup from the ERP home page to link your teachers." />
        ) : (
          <div className="space-y-2">
            {data.staff.map((p) => (
              <button
                key={p.id}
                onClick={() => openStaff(p)}
                className="card w-full text-left hover:scale-[1.005] transition-transform flex items-center gap-4 min-h-[72px]"
              >
                <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-emerald-500 via-teal-400 to-brand-cyan
                                flex items-center justify-center text-white font-bold shrink-0">
                  {p.name?.charAt(0)?.toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink truncate">{p.name}</div>
                  <div className="text-sm text-muted truncate">
                    {p.designation || (p.role === 'admin' ? 'Administrator' : 'Teacher')}
                    {p.subjects?.length ? ` · ${p.subjects.slice(0, 3).join(', ')}` : ''}
                  </div>
                  <div className="mt-1"><Missing fields={p.missing} /></div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xs text-faint">Employee</div>
                  <div className="font-mono text-sm text-ink">{p.employee_no || '—'}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <Drawer
        open={!!open}
        title={open?.name}
        subtitle={open ? `Logs in as ${open.login_id}` : ''}
        onClose={() => setOpen(null)}
        footer={
          <button onClick={save} disabled={saving} className="btn-primary w-full min-h-[48px]">
            {saving ? <Loader2 size={16} className="animate-spin" /> : null}
            {saving ? 'Saving…' : 'Save'}
          </button>
        }
      >
        {open && (
          <>
            <Field label="Employee Number" value={form.employee_no} onChange={setF('employee_no')} />
            <Field label="Designation" value={form.designation} onChange={setF('designation')}
                   hint="For example: Senior Teacher, Coordinator, Accountant" />
            <Field label="Department" value={form.department} onChange={setF('department')} />
            <Field label="Joining date" type="date" value={form.joining_date} onChange={setF('joining_date')} />
            <Field label="Employment type" value={form.employment_type} onChange={setF('employment_type')}
                   options={[
                     { value: 'permanent', label: 'Permanent' },
                     { value: 'contract', label: 'Contract' },
                     { value: 'visiting', label: 'Visiting' },
                   ]} />
            <Field label="Qualification" value={form.qualification} onChange={setF('qualification')} />
            <Field label="Phone" value={form.phone} onChange={setF('phone')} />

            {data.sensitive_visible && (
              <div className="pt-2 border-t border-line/60 space-y-4">
                <p className="text-xs text-faint pt-2">
                  Payroll needs these. Only accounts with permission can see or change them.
                </p>
                <Field label="CNIC" value={form.cnic} onChange={setF('cnic')} placeholder="00000-0000000-0" />
                <Field label="Bank" value={form.bank_name} onChange={setF('bank_name')} />
                <Field label="IBAN" value={form.bank_iban} onChange={setF('bank_iban')} />
              </div>
            )}
          </>
        )}
      </Drawer>
    </Layout>
  );
}
