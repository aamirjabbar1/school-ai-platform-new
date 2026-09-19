/**
 * Admissions.
 *
 * A clerk with a paper form should be able to work this without being told how.
 * So: one form, in the order the paper form asks, with no steps, no tabs and no
 * jargon. The only decision on the page is the last one — save it for later, or
 * admit the child now.
 *
 * The family suggestion is the one clever thing, and it stays out of the way
 * until it has something useful to say: type a father's name or a phone number
 * and the families already in the school appear, with the reason they matched.
 * The clerk links or ignores. Nothing merges on its own.
 *
 * When an admission is confirmed the password appears once, because that is the
 * only moment it exists in readable form. The screen says so plainly rather
 * than letting someone close it and find out later.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Confirm, Drawer, Empty, Field, Note, Panel } from '../../components/erp/Kit';
import {
  CheckCircle2, Copy, Link2, Loader2, Printer, Search, UserPlus, Users,
} from 'lucide-react';

const BLANK = {
  student_name: '', father_name: '', mother_name: '', date_of_birth: '', gender: '',
  b_form: '', phone: '', address: '', previous_school: '', previous_class: '',
  class_applied_id: '', section_id: '', family_id: '', remarks: '',
};

const STATUS_LABEL = {
  inquiry: 'Enquiry', applied: 'Applied', approved: 'Approved',
  confirmed: 'Admitted', rejected: 'Not accepted', cancelled: 'Cancelled',
};

export default function ErpAdmissions() {
  const [loading, setLoading] = useState(true);
  const [list, setList] = useState({ admissions: [], total: 0 });
  const [classes, setClasses] = useState([]);
  const [query, setQuery] = useState('');
  const [showOpen, setShowOpen] = useState(true);

  const [form, setForm] = useState(null);         // null = closed, object = open
  const [suggestions, setSuggestions] = useState([]);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [credentials, setCredentials] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await erpAPI.admissions({
        status: showOpen ? 'open' : undefined,
        q: query || undefined,
      });
      setList(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load admissions.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { erpAPI.classes().then(({ data }) => setClasses(data)).catch(() => {}); }, []);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [query, showOpen]);

  // Family suggestions, as the clerk types. Never writes, so it is safe to
  // fire often — but debounced anyway, because the office connection is shared
  // with thirty classrooms.
  useEffect(() => {
    if (!form) return undefined;
    const { father_name, phone, b_form } = form;
    if (!father_name && !phone) { setSuggestions([]); return undefined; }
    const t = setTimeout(async () => {
      try {
        const { data } = await erpAPI.suggestFamilies({ father_name, phone, cnic: b_form });
        setSuggestions(data);
      } catch { /* a suggestion that fails is simply no suggestion */ }
    }, 400);
    return () => clearTimeout(t);
  }, [form?.father_name, form?.phone, form?.b_form]);

  const setF = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const sections = classes.find((c) => c.id === form?.class_applied_id)?.sections || [];

  const save = async ({ thenAdmit }) => {
    if (!form.student_name.trim()) { setError("Please enter the student's name."); return; }
    if (thenAdmit && !form.class_applied_id) { setError('Please choose which class they are joining.'); return; }

    setSaving(true);
    setError('');
    try {
      const payload = { ...form };
      Object.keys(payload).forEach((k) => { if (payload[k] === '') delete payload[k]; });

      const { data: admission } = form.id
        ? await erpAPI.updateAdmission(form.id, payload)
        : await erpAPI.createAdmission(payload);

      if (!thenAdmit) {
        setMessage(`Saved. Application ${admission.application_no} for ${admission.student_name}.`);
        setForm(null);
        await load();
        return;
      }

      const { data: creds } = await erpAPI.confirmAdmission(admission.id);
      setForm(null);
      setCredentials(creds);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'That did not work. Nothing was saved.');
    } finally {
      setSaving(false);
      setConfirm(null);
    }
  };

  const askAdmit = () => {
    const className = classes.find((c) => c.id === form.class_applied_id)?.canonical_name;
    setConfirm({
      title: `Admit ${form.student_name}?`,
      lines: [
        `${form.student_name} will be admitted to ${className || 'the selected class'}.`,
        'A GR number and admission number will be allocated.',
        'A login will be created, and the password will be shown to you once — print it before closing.',
        form.family_id ? 'They will be added to the family you linked.' : 'A new family record will be created.',
        'They will appear on class lists, the chatbot and online classes straight away.',
      ],
      confirmLabel: 'Yes, admit them',
      run: () => save({ thenAdmit: true }),
    });
  };

  const copyCredentials = () => {
    const c = credentials;
    const text = [
      `Student: ${c.name}`, `GR No: ${c.gr_no}`, `Admission No: ${c.admission_no}`,
      `Class: ${c.class_name}${c.section ? ` ${c.section}` : ''}`,
      `User ID: ${c.login_id}`, `Password: ${c.password}`,
      'Change the password at first login.',
    ].join('\n');
    navigator.clipboard?.writeText(text);
    setMessage('Copied. Paste it wherever you need it.');
  };

  return (
    <Layout title="Admissions">
      <div className="space-y-4 max-w-5xl">
        {message && <Note kind="good">{message}</Note>}
        {error && !form && <Note kind="bad">{error}</Note>}

        <Panel>
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name, father’s name or application number…"
                className="w-full min-h-[48px] rounded-xl pl-10 pr-3 bg-surface-2 border border-line text-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
              />
            </div>
            <button
              onClick={() => { setForm({ ...BLANK }); setSuggestions([]); setError(''); }}
              className="btn-primary min-h-[48px] shrink-0"
            >
              <UserPlus size={18} /> New admission
            </button>
          </div>
          <label className="flex items-center gap-2 mt-3 text-sm text-muted cursor-pointer select-none">
            <input type="checkbox" checked={showOpen} onChange={(e) => setShowOpen(e.target.checked)}
                   className="w-4 h-4 accent-brand-cyan" />
            Only show admissions still in progress
          </label>
        </Panel>

        {loading ? (
          <Busy label="Loading admissions…" />
        ) : list.admissions.length === 0 ? (
          <Empty
            icon={Users}
            title={showOpen ? 'Nothing in progress' : 'No admissions yet'}
            hint="Press New admission to record an enquiry or admit a student."
          />
        ) : (
          <div className="space-y-2">
            {list.admissions.map((a) => (
              <button
                key={a.id}
                onClick={() => {
                  if (a.status === 'confirmed') return;
                  setForm({ ...BLANK, ...a, date_of_birth: a.date_of_birth || '' });
                  setError('');
                }}
                className={`card w-full text-left flex items-center gap-4 min-h-[72px]
                            ${a.status === 'confirmed' ? 'opacity-80 cursor-default' : 'hover:scale-[1.005] transition-transform'}`}
              >
                <div className={`w-11 h-11 rounded-2xl flex items-center justify-center text-white font-bold shrink-0
                                ${a.status === 'confirmed'
                                  ? 'bg-gradient-to-br from-emerald-500 to-teal-400'
                                  : 'bg-gradient-to-br from-brand-blue via-brand-cyan to-brand-teal'}`}>
                  {a.student_name?.charAt(0)?.toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink truncate">{a.student_name}</div>
                  <div className="text-sm text-muted truncate">
                    {a.father_name ? `${a.father_name} · ` : ''}{a.class_name || 'No class chosen'}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xs text-faint">{a.application_no}</div>
                  <div className={`text-sm font-medium ${a.status === 'confirmed' ? 'text-emerald-400' : 'text-ink'}`}>
                    {STATUS_LABEL[a.status] || a.status}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── The form ── */}
      <Drawer
        open={!!form}
        title={form?.id ? form.student_name : 'New admission'}
        subtitle={form?.application_no || 'Fill in what you have — you can come back to it'}
        onClose={() => setForm(null)}
        footer={
          <div className="flex flex-col sm:flex-row gap-3">
            <button onClick={() => save({ thenAdmit: false })} disabled={saving}
                    className="btn-secondary flex-1 min-h-[48px]">
              {saving ? <Loader2 size={16} className="animate-spin" /> : null} Save for now
            </button>
            <button onClick={askAdmit} disabled={saving} className="btn-primary flex-1 min-h-[48px]">
              <CheckCircle2 size={18} /> Admit this student
            </button>
          </div>
        }
      >
        {form && (
          <>
            {error && <Note kind="bad">{error}</Note>}

            <Field label="Student’s name" value={form.student_name} onChange={setF('student_name')} required />
            <Field label="Father’s name" value={form.father_name} onChange={setF('father_name')} />
            <Field label="Phone" value={form.phone} onChange={setF('phone')} placeholder="0300-1234567" />

            {/* Family suggestions — only when there is something to suggest. */}
            {suggestions.length > 0 && !form.family_id && (
              <div className="rounded-2xl border border-brand-cyan/40 p-4">
                <p className="text-sm font-semibold text-ink mb-1">
                  {suggestions.length === 1 ? 'This family is already in the school' : 'These families are already in the school'}
                </p>
                <p className="text-xs text-muted mb-3">Link them so brothers and sisters share one family record.</p>
                <div className="space-y-2">
                  {suggestions.map((f) => (
                    <button
                      key={f.id}
                      onClick={() => setF('family_id')(f.id)}
                      className="w-full text-left rounded-xl bg-surface-2 p-3 flex items-center gap-3 min-h-[56px]
                                 hover:bg-surface-3 transition-colors"
                    >
                      <Link2 size={16} className="text-brand-cyan shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-ink truncate">
                          {f.father_name || f.family_code}
                        </div>
                        <div className="text-xs text-muted">
                          {f.children} {f.children === 1 ? 'child' : 'children'} · {f.reason}
                        </div>
                      </div>
                      <span className="text-xs text-brand-cyan shrink-0">Link</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {form.family_id && (
              <Note kind="good">
                Linked to an existing family.{' '}
                <button onClick={() => setF('family_id')('')} className="underline">Undo</button>
              </Note>
            )}

            <Field label="Mother’s name" value={form.mother_name} onChange={setF('mother_name')} />
            <Field label="Date of birth" type="date" value={form.date_of_birth} onChange={setF('date_of_birth')} />
            <Field label="Gender" value={form.gender} onChange={setF('gender')}
                   options={[{ value: 'male', label: 'Male' }, { value: 'female', label: 'Female' }]} />
            <Field label="B-Form number" value={form.b_form} onChange={setF('b_form')} />
            <Field label="Address" value={form.address} onChange={setF('address')} />

            <div className="pt-2 border-t border-line/60 space-y-4">
              <p className="text-xs text-faint pt-2">Which class are they joining?</p>
              <Field
                label="Class"
                value={form.class_applied_id}
                onChange={(v) => setForm((f) => ({ ...f, class_applied_id: v, section_id: '' }))}
                options={classes.map((c) => ({ value: c.id, label: c.canonical_name }))}
                required
              />
              {sections.length > 0 && (
                <Field label="Section" value={form.section_id} onChange={setF('section_id')}
                       options={sections.map((s) => ({ value: s.id, label: `${s.name} (${s.students})` }))}
                       hint="Optional — you can place them later." />
              )}
              <Field label="Previous school" value={form.previous_school} onChange={setF('previous_school')} />
              <Field label="Remarks" value={form.remarks} onChange={setF('remarks')} />
            </div>
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
        busy={saving}
      />

      {/* ── The login slip, shown once ── */}
      <Drawer
        open={!!credentials}
        title={`${credentials?.name} is admitted`}
        subtitle="Write this down or print it now"
        onClose={() => setCredentials(null)}
        footer={
          <div className="flex flex-col sm:flex-row gap-3">
            <button onClick={copyCredentials} className="btn-secondary flex-1 min-h-[48px]">
              <Copy size={16} /> Copy
            </button>
            <button onClick={() => window.print()} className="btn-secondary flex-1 min-h-[48px]">
              <Printer size={16} /> Print
            </button>
            <button onClick={() => setCredentials(null)} className="btn-primary flex-1 min-h-[48px]">
              Done
            </button>
          </div>
        }
      >
        {credentials && (
          <>
            <Note kind="bad">
              The password is shown <strong>once</strong>. After you close this, it cannot be shown
              again — it can only be reset.
            </Note>
            <div className="rounded-2xl bg-surface-2/60 p-5 space-y-3">
              <Slip label="Student" value={credentials.name} />
              <Slip label="GR Number" value={credentials.gr_no} mono />
              <Slip label="Admission Number" value={credentials.admission_no} mono />
              <Slip label="Class" value={`${credentials.class_name}${credentials.section ? ` — ${credentials.section}` : ''}`} />
              <div className="pt-3 border-t border-line/60 space-y-3">
                <Slip label="User ID" value={credentials.login_id} mono big />
                <Slip label="Password" value={credentials.password} mono big />
              </div>
            </div>
            <p className="text-sm text-muted">
              They will be asked to choose their own password the first time they log in.
            </p>
          </>
        )}
      </Drawer>
    </Layout>
  );
}

function Slip({ label, value, mono, big }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-sm text-muted shrink-0">{label}</span>
      <span className={`text-ink text-right break-all ${mono ? 'font-mono' : ''} ${big ? 'text-lg font-bold' : 'font-medium'}`}>
        {value}
      </span>
    </div>
  );
}
