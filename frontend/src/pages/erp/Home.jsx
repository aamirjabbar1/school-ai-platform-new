/**
 * ERP home.
 *
 * Two states, and the screen decides which one you are in — nobody has to know
 * there is a setup step:
 *
 *   Before setup  →  one panel showing exactly what will be linked, one button.
 *   After setup   →  the school's numbers, and whatever needs a person today.
 *
 * Everything that can be worked out from data the platform already holds is
 * worked out. The only thing asked of a human is the press.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Attention, Busy, Confirm, Note, Panel, Stat } from '../../components/erp/Kit';
import {
  ArrowRight, Building2, CalendarRange, GraduationCap, Home, Layers,
  ShieldCheck, Sparkles, UserPlus, Users, Wand2,
} from 'lucide-react';

export default function ErpHome() {
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [dash, setDash] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirm, setConfirm] = useState(null);   // { title, lines, run }
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const { data: st } = await erpAPI.status();
      setStatus(st);
      if (st.setup_done) {
        const { data } = await erpAPI.dashboard();
        setDash(data);
      } else {
        const { data } = await erpAPI.analyze();
        setPreview(data);
      }
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load the ERP.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const runAction = async (fn, successMessage) => {
    setBusy(true);
    setError('');
    try {
      const { data } = await fn();
      setMessage(typeof successMessage === 'function' ? successMessage(data) : successMessage);
      setConfirm(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.detail || 'That did not work. Nothing was changed.');
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  };

  /* ── Setup ─────────────────────────────────────────────────────────────── */

  const askSetup = () => {
    const p = preview;
    setConfirm({
      title: 'Set up the school?',
      lines: [
        `${p.students.to_link} students will be linked to the ERP — they keep their existing login, password and dashboard.`,
        `${p.staff.to_link} staff members will be linked as employees.`,
        `${p.classes.to_create} classes and ${p.sections.to_create} sections will be created from the classes already in use.`,
        'Nothing is deleted, no password is changed, and no student or teacher is created.',
        'You can run this again safely — it only adds what is missing.',
      ],
      confirmLabel: 'Set up my school',
      run: () => runAction(
        erpAPI.runSetup,
        (d) => `Done. ${d.students_linked} students and ${d.staff_linked} staff linked, ${d.classes_created} classes and ${d.sections_created} sections created.`,
      ),
    });
  };

  const askAction = (item) => {
    if (item.action === 'allocate_gr') {
      setConfirm({
        title: 'Allocate GR numbers?',
        lines: [
          `${item.count} students have no GR number yet.`,
          'Each will be given the next number in the GR series, in name order.',
          'If LSS already keeps a paper GR register, type those numbers in on the student instead — a generated number that disagrees with the register is worse than a blank one.',
        ],
        confirmLabel: 'Allocate GR numbers',
        run: () => runAction(erpAPI.allocateGrNumbers, (d) => `${d.allocated} GR numbers allocated (${d.first} to ${d.last}).`),
      });
    } else if (item.action === 'allocate_employee_no') {
      setConfirm({
        title: 'Allocate employee numbers?',
        lines: [
          `${item.count} staff members have no employee number yet.`,
          'Each will be given the next number in the employee series.',
          'Payroll needs these later, so it is safe to do now.',
        ],
        confirmLabel: 'Allocate employee numbers',
        run: () => runAction(erpAPI.allocateEmployeeNumbers, (d) => `${d.allocated} employee numbers allocated.`),
      });
    }
  };

  if (loading) return <Layout title="School ERP"><Busy label="Opening the ERP…" /></Layout>;

  if (!status?.available) {
    return (
      <Layout title="School ERP">
        <Note kind="bad">The ERP is not switched on for your account.</Note>
      </Layout>
    );
  }

  return (
    <Layout title="School ERP">
      <div className="space-y-5 max-w-5xl">
        {status.preview_only && (
          <Note kind="info">
            <strong>Only you can see this.</strong> The ERP is switched off for everyone else while you try it.
            Turn it on for the school from <Link to="/erp/settings" className="underline">Settings</Link> when you are ready.
          </Note>
        )}
        {message && <Note kind="good">{message}</Note>}
        {error && <Note kind="bad">{error}</Note>}

        {/* ── Before setup ── */}
        {!status.setup_done && preview && (
          <Panel
            title="Let’s set up your school"
            subtitle="Everything below is already in LSS Bot. Nothing needs to be typed in again."
          >
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
              <Stat icon={Users} value={preview.students.to_link} label="students to link" />
              <Stat icon={GraduationCap} value={preview.staff.to_link} label="staff to link" />
              <Stat icon={Building2} value={preview.classes.to_create} label="classes found" />
              <Stat icon={Layers} value={preview.sections.to_create} label="sections found" />
            </div>

            <div className="rounded-2xl bg-surface-2/60 p-4 mb-5">
              <p className="text-sm font-semibold text-ink mb-2">Classes found in your data</p>
              <div className="flex flex-wrap gap-2">
                {preview.classes.names.map((name) => (
                  <span key={name} className="px-3 py-1 rounded-lg bg-surface-3 text-sm text-ink">{name}</span>
                ))}
              </div>
            </div>

            {preview.needs_attention?.length > 0 && (
              <div className="rounded-2xl border border-amber-500/40 p-4 mb-5">
                <p className="text-sm font-semibold text-ink mb-1">
                  {preview.needs_attention.length} class names could not be recognised
                </p>
                <p className="text-sm text-muted mb-3">
                  These are left exactly as they are and will keep working. You can map them later.
                </p>
                <div className="flex flex-wrap gap-2">
                  {preview.needs_attention.slice(0, 12).map((item) => (
                    <span key={item.value} className="px-3 py-1 rounded-lg bg-amber-500/10 text-sm text-amber-300">
                      {item.value} ({item.rows})
                    </span>
                  ))}
                </div>
              </div>
            )}

            <button onClick={askSetup} className="btn-primary w-full sm:w-auto min-h-[48px] text-base">
              <Wand2 size={18} /> Set up my school
            </button>
            <p className="text-xs text-faint mt-3">
              Safe to press. It adds records — it never deletes, renames or resets anything.
            </p>
          </Panel>
        )}

        {/* ── After setup ── */}
        {status.setup_done && dash && (
          <>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              <Stat icon={Users} value={dash.totals.students} label="students" />
              <Stat icon={GraduationCap} value={dash.totals.staff} label="teachers" />
              <Stat icon={Building2} value={`${dash.totals.classes} / ${dash.totals.sections}`} label="classes / sections" />
            </div>

            {dash.needs_attention.length > 0 ? (
              <Panel title="Needs your attention" subtitle="Everything else is running on its own.">
                <div className="space-y-3">
                  {dash.needs_attention.map((item) => (
                    <Attention
                      key={item.key}
                      count={item.count}
                      label={item.label}
                      actionLabel={item.action === 'open_students' ? undefined : item.action_label}
                      onAction={() => askAction(item)}
                      busy={busy}
                    />
                  ))}
                </div>
              </Panel>
            ) : (
              <Panel>
                <div className="flex items-center gap-3 text-ink">
                  <Sparkles className="text-brand-cyan" size={20} />
                  <span className="font-semibold">Nothing needs your attention today.</span>
                </div>
              </Panel>
            )}

            <div className="grid sm:grid-cols-2 gap-3">
              <Tile to="/erp/admissions" icon={UserPlus} title="Admissions"
                    hint="Admit a new student — one form, one press" />
              <Tile to="/erp/students" icon={Users} title="Students"
                    hint="Find any student by GR number, name or father’s name" />
              <Tile to="/erp/families" icon={Home} title="Families"
                    hint="One household, every child the school teaches from it" />
              <Tile to="/erp/staff" icon={GraduationCap} title="Staff"
                    hint="Employee records, designations and joining dates" />
              <Tile to="/erp/classes" icon={Building2} title="Classes & sections"
                    hint="Who is in which class this session" />
              {status.is_owner && (
                <Tile to="/erp/access" icon={ShieldCheck} title="People & access"
                      hint="Decide who can do what" />
              )}
            </div>

            {dash.session && (
              <p className="text-sm text-muted flex items-center gap-2">
                <CalendarRange size={15} />
                Current session: <strong className="text-ink">{dash.session.name}</strong>
              </p>
            )}
          </>
        )}
      </div>

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

function Tile({ to, icon: Icon, title, hint }) {
  return (
    <Link to={to} className="card hover:scale-[1.01] transition-transform flex items-center gap-4 min-h-[76px]">
      <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-brand-blue via-brand-cyan to-brand-teal flex items-center justify-center text-white shrink-0">
        <Icon size={20} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-ink">{title}</div>
        <div className="text-sm text-muted truncate">{hint}</div>
      </div>
      <ArrowRight size={18} className="text-faint shrink-0" />
    </Link>
  );
}
