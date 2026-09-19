/**
 * Students.
 *
 * One search box answers every way a school refers to a student — GR number,
 * admission number, the registration number they log in with, their name, or
 * their father's name. Asking someone to pick "search by…" first is a question
 * the computer can answer itself.
 *
 * Rows are cards, not a wide table: the specification asks for no horizontal
 * scrolling on a phone, and a table of eleven columns cannot honour that.
 */
import { useEffect, useMemo, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Drawer, Empty, Field, Missing, Note, Panel } from '../../components/erp/Kit';
import { Loader2, Search, UserRound, Users } from 'lucide-react';

export default function ErpStudents() {
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [classId, setClassId] = useState('');
  const [onlyIncomplete, setOnlyIncomplete] = useState(false);
  const [data, setData] = useState({ students: [], total: 0 });
  const [classes, setClasses] = useState([]);
  const [open, setOpen] = useState(null);      // the student being edited
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    erpAPI.classes().then(({ data }) => setClasses(data)).catch(() => {});
  }, []);

  // One debounce covers typing and the filters, so a fast typist does not
  // fire a request per keystroke on a school's connection.
  useEffect(() => {
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await erpAPI.students({
          q: query || undefined,
          class_id: classId || undefined,
          needs_attention: onlyIncomplete || undefined,
          limit: 100,
        });
        setData(data);
      } catch (e) {
        setError(e.response?.data?.detail || 'Could not load students.');
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query, classId, onlyIncomplete]);

  const classOptions = useMemo(
    () => classes.map((c) => ({ value: c.id, label: `${c.canonical_name} (${c.students})` })),
    [classes],
  );

  const openStudent = async (student) => {
    setError('');
    setOpen(student);
    try {
      const { data } = await erpAPI.student(student.id);
      setForm({
        gr_no: data.profile?.gr_no || '',
        admission_no: data.profile?.admission_no || '',
        date_of_birth: data.profile?.date_of_birth || '',
        gender: data.profile?.gender || '',
        b_form: data.profile?.b_form || '',
        phone: data.profile?.phone || '',
        address: data.profile?.address || '',
        previous_school: data.profile?.previous_school || '',
        _detail: data,
      });
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not open that student.');
    }
  };

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const payload = { ...form };
      delete payload._detail;
      // Empty strings are "not answered", not "set to blank".
      Object.keys(payload).forEach((k) => { if (payload[k] === '') delete payload[k]; });
      await erpAPI.updateStudent(open.id, payload);
      setMessage(`${open.name} saved.`);
      setOpen(null);
      setQuery((q) => q);                       // re-runs the search
      const { data } = await erpAPI.students({ q: query || undefined, class_id: classId || undefined, limit: 100 });
      setData(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  const setF = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Layout title="Students">
      <div className="space-y-4 max-w-5xl">
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        <Panel>
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by GR number, name or father’s name…"
                className="w-full min-h-[48px] rounded-xl pl-10 pr-3 bg-surface-2 border border-line text-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
              />
            </div>
            <select
              value={classId}
              onChange={(e) => setClassId(e.target.value)}
              className="min-h-[48px] rounded-xl px-3 bg-surface-2 border border-line text-ink sm:w-56
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            >
              <option value="">All classes</option>
              {classOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <label className="flex items-center gap-2 mt-3 text-sm text-muted cursor-pointer select-none">
            <input
              type="checkbox"
              checked={onlyIncomplete}
              onChange={(e) => setOnlyIncomplete(e.target.checked)}
              className="w-4 h-4 accent-brand-cyan"
            />
            Only show students with something missing
          </label>
        </Panel>

        {loading ? (
          <Busy label="Finding students…" />
        ) : data.students.length === 0 ? (
          <Empty
            icon={Users}
            title="No students found"
            hint={query ? 'Try part of a name, or the GR number on its own.' : 'Run setup from the ERP home page to link your students.'}
          />
        ) : (
          <>
            <p className="text-sm text-muted px-1">
              {data.total} student{data.total === 1 ? '' : 's'}
              {data.total > data.students.length ? ` · showing the first ${data.students.length}` : ''}
            </p>
            <div className="space-y-2">
              {data.students.map((s) => (
                <button
                  key={s.id}
                  onClick={() => openStudent(s)}
                  className="card w-full text-left hover:scale-[1.005] transition-transform flex items-center gap-4 min-h-[72px]"
                >
                  <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-brand-blue via-brand-cyan to-brand-teal
                                  flex items-center justify-center text-white font-bold shrink-0">
                    {s.name?.charAt(0)?.toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink truncate">{s.name}</div>
                    <div className="text-sm text-muted truncate">
                      {s.father_name ? `${s.father_name} · ` : ''}
                      {s.class_name || 'No class'}{s.section_name ? ` ${s.section_name}` : ''}
                    </div>
                    <div className="mt-1"><Missing fields={s.missing} /></div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-xs text-faint">GR</div>
                    <div className="font-mono text-sm text-ink">{s.gr_no || '—'}</div>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <Drawer
        open={!!open}
        title={open?.name}
        subtitle={open ? `Logs in as ${open.registration_no}` : ''}
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
            <div className="rounded-2xl bg-surface-2/60 p-4 text-sm space-y-1">
              <Row label="Class this session" value={
                form._detail?.enrollment
                  ? `${form._detail.enrollment.class_name}${form._detail.enrollment.section_name ? ` — ${form._detail.enrollment.section_name}` : ''}`
                  : 'Not placed in a class yet'
              } />
              <Row label="Father" value={open.father_name || '—'} />
              <Row label="Login" value={open.registration_no} />
            </div>

            <Field label="GR Number" value={form.gr_no} onChange={setF('gr_no')}
                   hint="The number in the school's GR register. Leave blank to allocate one later." />
            <Field label="Admission Number" value={form.admission_no} onChange={setF('admission_no')} />
            <Field label="Date of birth" type="date" value={form.date_of_birth} onChange={setF('date_of_birth')} />
            <Field label="Gender" value={form.gender} onChange={setF('gender')}
                   options={[{ value: 'male', label: 'Male' }, { value: 'female', label: 'Female' }]} />
            <Field label="B-Form / CNIC" value={form.b_form} onChange={setF('b_form')} />
            <Field label="Phone" value={form.phone} onChange={setF('phone')} />
            <Field label="Address" value={form.address} onChange={setF('address')} />
            <Field label="Previous school" value={form.previous_school} onChange={setF('previous_school')} />
          </>
        )}
      </Drawer>
    </Layout>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted">{label}</span>
      <span className="text-ink font-medium text-right">{value}</span>
    </div>
  );
}
