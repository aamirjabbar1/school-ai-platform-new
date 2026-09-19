/**
 * Attendance.
 *
 * The most-used screen in the whole ERP, and the one most likely to be used
 * badly: standing up, one hand, in a corridor, on a phone. So:
 *
 *   • Two screens, not five. Pick the class, tap the absentees, save.
 *   • Everyone starts present. In a class of twenty-four, three are away —
 *     defaulting the other way would mean twenty-one taps instead of three.
 *   • The whole row is the tap target, not a checkbox. 64px tall.
 *   • The count at the bottom is always visible, so the teacher knows what they
 *     are about to save without scrolling back up.
 *   • Saving is one request. A teacher on a weak connection spends one round
 *     trip, not twenty-four.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Empty, Note, Panel } from '../../components/erp/Kit';
import {
  ArrowLeft, Check, CheckCircle2, ClipboardCheck, Loader2, Users, X,
} from 'lucide-react';

const CYCLE = { present: 'absent', absent: 'leave', leave: 'present', late: 'present', half_day: 'present' };

const LOOK = {
  present: { label: 'Present', chip: 'bg-emerald-500/15 text-emerald-400', icon: Check },
  absent: { label: 'Absent', chip: 'bg-rose-500/15 text-rose-400', icon: X },
  leave: { label: 'Leave', chip: 'bg-amber-500/15 text-amber-400', icon: ClipboardCheck },
  late: { label: 'Late', chip: 'bg-sky-500/15 text-sky-400', icon: Check },
  half_day: { label: 'Half day', chip: 'bg-sky-500/15 text-sky-400', icon: Check },
};

const today = () => new Date().toISOString().slice(0, 10);

export default function ErpAttendance() {
  const [loading, setLoading] = useState(true);
  const [classes, setClasses] = useState([]);
  const [picked, setPicked] = useState(null);
  const [onDate, setOnDate] = useState(today());
  const [roster, setRoster] = useState(null);
  const [marks, setMarks] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const { data } = await erpAPI.attendanceClasses();
        setClasses(data.classes);
        // One class and nothing to choose between — skip the choosing.
        if (data.classes.length === 1) openClass(data.classes[0], today());
      } catch (e) {
        setError(e.response?.data?.detail || 'Could not load your classes.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const openClass = async (entry, forDate) => {
    setPicked(entry);
    setRoster(null);
    setSaved(null);
    setError('');
    try {
      const { data } = await erpAPI.attendanceRoster({
        class_id: entry.class_id,
        section_id: entry.section_id || undefined,
        on_date: forDate || onDate,
      });
      setRoster(data);
      setMarks(Object.fromEntries(data.students.map((s) => [s.id, s.status])));
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not open that class.');
    }
  };

  const cycle = (id) => setMarks((m) => ({ ...m, [id]: CYCLE[m[id]] || 'absent' }));

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const { data } = await erpAPI.saveAttendance({
        class_id: picked.class_id,
        section_id: picked.section_id || undefined,
        on_date: onDate,
        marks: Object.entries(marks).map(([student_id, status]) => ({ student_id, status })),
      });
      setSaved(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not save. Nothing was changed.');
    } finally {
      setSaving(false);
    }
  };

  const present = Object.values(marks).filter((s) => s !== 'absent' && s !== 'leave').length;
  const total = Object.keys(marks).length;

  if (loading) return <Layout title="Attendance"><Busy label="Loading your classes…" /></Layout>;

  /* ── Screen 1: which class ── */
  if (!picked) {
    return (
      <Layout title="Attendance">
        <div className="space-y-4 max-w-3xl">
          {error && <Note kind="bad">{error}</Note>}
          {classes.length === 0 ? (
            <Empty
              icon={Users}
              title="No classes assigned to you"
              hint="Ask the office to assign your classes, then this page will show them."
            />
          ) : (
            <>
              <p className="text-sm text-muted px-1">Which class are you taking?</p>
              <div className="space-y-2">
                {classes.map((c) => (
                  <button
                    key={`${c.class_id}-${c.section_id || 'all'}`}
                    onClick={() => openClass(c)}
                    className="card w-full text-left flex items-center gap-4 min-h-[76px] hover:scale-[1.005] transition-transform"
                  >
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 via-teal-400 to-brand-cyan
                                    flex items-center justify-center text-white shrink-0">
                      <ClipboardCheck size={22} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-ink text-lg">{c.label}</div>
                      {c.students > 0 && (
                        <div className="text-sm text-muted">{c.students} children</div>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </Layout>
    );
  }

  /* ── After saving ── */
  if (saved) {
    return (
      <Layout title="Attendance">
        <div className="max-w-md mx-auto text-center py-10 space-y-5">
          <div className="w-20 h-20 rounded-full bg-emerald-500/15 text-emerald-400 flex items-center justify-center mx-auto">
            <CheckCircle2 size={44} />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-ink">Saved</h2>
            <p className="text-muted mt-1">
              {picked.label} · {new Date(saved.date).toDateString()}
            </p>
          </div>
          <div className="card flex justify-around py-5">
            <div>
              <div className="text-3xl font-bold text-emerald-400">{saved.present}</div>
              <div className="text-sm text-muted">present</div>
            </div>
            <div>
              <div className="text-3xl font-bold text-rose-400">{saved.absent}</div>
              <div className="text-sm text-muted">away</div>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-3">
            <button onClick={() => { setPicked(null); setSaved(null); }} className="btn-secondary flex-1 min-h-[48px]">
              Another class
            </button>
            <button onClick={() => openClass(picked, onDate)} className="btn-primary flex-1 min-h-[48px]">
              Change something
            </button>
          </div>
        </div>
      </Layout>
    );
  }

  /* ── Screen 2: the register ── */
  return (
    <Layout title="Attendance">
      <div className="max-w-3xl pb-28">
        <button
          onClick={() => setPicked(null)}
          className="flex items-center gap-2 text-muted hover:text-ink mb-3 min-h-[44px]"
        >
          <ArrowLeft size={18} /> {picked.label}
        </button>

        {error && <div className="mb-3"><Note kind="bad">{error}</Note></div>}

        <Panel>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <label className="flex-1">
              <span className="block text-xs text-muted mb-1">Date</span>
              <input
                type="date"
                value={onDate}
                max={today()}
                onChange={(e) => { setOnDate(e.target.value); openClass(picked, e.target.value); }}
                className="w-full min-h-[44px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
              />
            </label>
            <p className="text-sm text-muted sm:pt-5">Tap a name to change it.</p>
          </div>
        </Panel>

        {!roster ? (
          <Busy label="Loading the class…" />
        ) : roster.students.length === 0 ? (
          <Empty icon={Users} title="No children in this class yet"
                 hint="Students appear here once they are placed in a class for this session." />
        ) : (
          <>
            {roster.already_taken && (
              <div className="mt-3"><Note kind="info">
                This register was already taken. Changing it now is recorded as a correction.
              </Note></div>
            )}
            {roster.from_online_class && (
              <div className="mt-3"><Note kind="info">
                Suggested from today’s online class. Check it and save.
              </Note></div>
            )}

            <div className="space-y-2 mt-3">
              {roster.students.map((s) => {
                const status = marks[s.id] || 'present';
                const look = LOOK[status] || LOOK.present;
                const Icon = look.icon;
                return (
                  <button
                    key={s.id}
                    onClick={() => cycle(s.id)}
                    className="card w-full text-left flex items-center gap-4 min-h-[64px] active:scale-[0.99] transition-transform"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-ink truncate">{s.name}</div>
                      <div className="text-xs text-muted truncate">
                        {s.roll_no ? `Roll ${s.roll_no}` : s.gr_no ? `GR ${s.gr_no}` : s.father_name || ''}
                      </div>
                    </div>
                    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium shrink-0 ${look.chip}`}>
                      <Icon size={15} /> {look.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* The count and the save button stay on screen, so the teacher never
          scrolls back up to find out what they are about to save. */}
      {roster?.students.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 p-3 glass-strong border-t border-line/60">
          <div className="max-w-3xl mx-auto flex items-center gap-3">
            <div className="text-sm shrink-0">
              <span className="text-emerald-400 font-bold text-lg">{present}</span>
              <span className="text-muted"> in · </span>
              <span className="text-rose-400 font-bold text-lg">{total - present}</span>
              <span className="text-muted"> away</span>
            </div>
            <button onClick={save} disabled={saving} className="btn-primary flex-1 min-h-[52px] text-base">
              {saving ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />}
              {saving ? 'Saving…' : 'Save attendance'}
            </button>
          </div>
        </div>
      )}
    </Layout>
  );
}
