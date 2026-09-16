import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import { onlineClassAPI } from '../../services/api';
import { apiError } from '../../services/apiError';
import { classesFor, sectionsFor, subjectsFor } from '../../constants/academics';
import {
  Radio, Video, Users, Clock, AlertCircle, ArrowRight, CalendarClock, CalendarPlus, X,
  ClipboardList,
} from 'lucide-react';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

// START CLASS — the only screen a teacher sees before teaching.
// Class → Section → Subject → one button. No meeting to configure, nothing to
// copy, nothing to send to students: they already know where their class is.
export default function TeacherOnlineClasses() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const classes = useMemo(() => classesFor(user), [user]);
  const subjects = useMemo(() => subjectsFor(user), [user]);

  const [className, setClassName] = useState('');
  const [section, setSection] = useState('');
  const [subject, setSubject] = useState('');
  const [duration, setDuration] = useState(40);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [live, setLive] = useState([]);
  const [recent, setRecent] = useState([]);

  const sections = useMemo(() => sectionsFor(user, className), [user, className]);

  useEffect(() => {
    if (!className && classes.length) setClassName(classes[0]);
    if (!subject && subjects.length) setSubject(subjects[0]);
  }, [classes, subjects, className, subject]);

  useEffect(() => {
    setSection((current) => (sections.includes(current) ? current : (sections[0] || '')));
  }, [sections]);

  const [upcoming, setUpcoming] = useState([]);
  const [scheduleOpen, setScheduleOpen] = useState(false);

  const loadSessions = () => {
    onlineClassAPI.teacherSessions()
      .then(({ data }) => { setLive(data.live || []); setRecent(data.recent || []); })
      .catch(() => { /* the start button still works */ });
    onlineClassAPI.upcoming()
      .then(({ data }) => setUpcoming(data.upcoming || []))
      .catch(() => { /* scheduling is optional; START CLASS is not */ });
  };

  useEffect(loadSessions, []);

  const startScheduled = async (session) => {
    try {
      const { data } = await onlineClassAPI.startScheduled(session.id);
      navigate(`/teacher/classroom/${data.session.id}`);
    } catch (err) {
      setError(apiError(err, 'Could not start that class.'));
    }
  };

  const startClass = async () => {
    setStarting(true);
    setError('');
    try {
      const { data } = await onlineClassAPI.start({
        class_name: className,
        section: section || null,
        subject,
        planned_duration_minutes: Number(duration) || 40,
      });
      navigate(`/teacher/classroom/${data.session.id}`);
    } catch (err) {
      setError(apiError(err, 'Could not start the class. Please try again.'));
      setStarting(false);
    }
  };

  return (
    <Layout title="Online Classes">
      {/* Start a class */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl p-6 mb-6 text-white shadow-glow-lg"
      >
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500 via-teal-500 to-brand-cyan" />
        <div className="relative z-10">
          <h2 className="font-display text-2xl font-bold">Start a live class</h2>
          <p className="text-white/85 text-sm mt-1">
            Your students see it appear on their dashboard and simply press Join.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
            <label className="block">
              <span className="text-xs font-semibold text-white/80">Class</span>
              <select
                value={className}
                onChange={(e) => setClassName(e.target.value)}
                className="input-field mt-1 text-ink"
              >
                {classes.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-xs font-semibold text-white/80">Section</span>
              <select
                value={section}
                onChange={(e) => setSection(e.target.value)}
                className="input-field mt-1 text-ink"
              >
                <option value="">Whole class</option>
                {sections.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-xs font-semibold text-white/80">Subject</span>
              <select
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="input-field mt-1 text-ink"
              >
                {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-xs font-semibold text-white/80">Minutes</span>
              <input
                type="number"
                min={5}
                max={300}
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                className="input-field mt-1 text-ink"
              />
            </label>
          </div>

          {error && (
            <div className="mt-4 flex items-center gap-2 text-sm bg-white/15 rounded-xl px-3 py-2">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          <button
            onClick={startClass}
            disabled={starting || !className || !subject}
            className="mt-5 w-full sm:w-auto inline-flex items-center justify-center gap-2.5
                       px-8 py-4 rounded-2xl bg-white text-emerald-700 font-bold text-lg
                       shadow-lg disabled:opacity-60 transition-transform hover:-translate-y-0.5"
          >
            <Video size={22} />
            {starting ? 'Starting…' : 'START CLASS'}
          </button>
        </div>
      </motion.div>

      {/* A class already running */}
      {live.length > 0 && (
        <div className="mb-6">
          <h3 className="font-display font-bold text-ink mb-3">Your live class</h3>
          {live.map((s) => (
            <button
              key={s.id}
              onClick={() => navigate(`/teacher/classroom/${s.id}`)}
              className="card w-full flex items-center gap-4 text-left hover:shadow-glow transition-shadow"
            >
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500" />
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-ink">
                  {s.subject} — {s.class_name}{s.section ? ` (${s.section})` : ''}
                </div>
                <div className="text-sm text-muted">
                  Started {new Date(s.actual_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
              <span className="btn-primary">Return to class <ArrowRight size={16} /></span>
            </button>
          ))}
        </div>
      )}

      {/* Scheduled classes */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-display font-bold text-ink">Upcoming</h3>
        <button onClick={() => setScheduleOpen(true)} className="btn-secondary text-sm">
          <CalendarPlus size={15} /> Add to timetable
        </button>
      </div>

      {upcoming.length === 0 ? (
        <div className="card text-muted text-sm mb-6">
          Nothing scheduled. You can always press START CLASS above.
        </div>
      ) : (
        <div className="space-y-2.5 mb-6">
          {upcoming.map((s) => (
            <div key={s.id} className="card flex items-center gap-4 py-4">
              <div className="w-10 h-10 rounded-xl bg-surface-3 flex items-center justify-center text-brand-cyan">
                <CalendarClock size={18} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-ink truncate">
                  {s.subject} — {s.class_name}{s.section ? ` (${s.section})` : ''}
                </div>
                <div className="text-sm text-muted">
                  {s.scheduled_start && new Date(s.scheduled_start).toLocaleString([], {
                    weekday: 'short', hour: '2-digit', minute: '2-digit',
                  })}
                  {' · '}{s.planned_duration_minutes} min
                </div>
              </div>
              <button onClick={() => startScheduled(s)} className="btn-primary text-sm">
                <Video size={15} /> Start
              </button>
            </div>
          ))}
        </div>
      )}

      <ScheduleDialog
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        onSaved={() => { setScheduleOpen(false); loadSessions(); }}
        classes={classes}
        subjects={subjects}
        sectionsFor={(c) => sectionsFor(user, c)}
      />

      {/* Today */}
      <h3 className="font-display font-bold text-ink mb-3">Earlier today</h3>
      {recent.length === 0 ? (
        <div className="card text-muted text-sm flex items-center gap-2">
          <Clock size={16} /> No classes yet today.
        </div>
      ) : (
        <div className="space-y-2.5">
          {recent.map((s) => (
            <div key={s.id} className="card flex items-center gap-4 py-4">
              <div className="w-10 h-10 rounded-xl bg-surface-3 flex items-center justify-center text-muted">
                <Radio size={18} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-ink truncate">
                  {s.subject} — {s.class_name}{s.section ? ` (${s.section})` : ''}
                </div>
                <div className="text-sm text-muted">
                  {s.actual_start && new Date(s.actual_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  {' · '}{Math.round((s.duration_seconds || 0) / 60)} min
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => navigate(`/teacher/classroom/${s.id}?view=attendance`)}
                  className="btn-secondary text-sm"
                >
                  <Users size={15} /> Attendance
                </button>
                <button
                  onClick={() => navigate(`/teacher/lesson-record/${s.id}`)}
                  className="btn-secondary text-sm"
                >
                  <ClipboardList size={15} /> Lesson record
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Layout>
  );
}

// ─── Timetable entry (spec §20) ───────────────────────────────────────────────
//
// A weekly slot, so students see UPCOMING on their dashboard and the class
// turns LIVE the moment the teacher starts it. The teacher still presses START
// CLASS — a timetable schedules attention, not a camera.
function ScheduleDialog({ open, onClose, onSaved, classes, subjects, sectionsFor }) {
  const [form, setForm] = useState({
    class_name: '', section: '', subject: '', weekday: 1,
    start_time: '08:00', duration_minutes: 40, recording_enabled: false,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setForm((f) => ({
      ...f,
      class_name: f.class_name || classes[0] || '',
      subject: f.subject || subjects[0] || '',
    }));
  }, [open, classes, subjects]);

  if (!open) return null;

  const sections = sectionsFor(form.class_name);

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      await onlineClassAPI.createSchedule({
        ...form,
        section: form.section || null,
        start_time: `${form.start_time}:00`,
        weekday: Number(form.weekday),
        duration_minutes: Number(form.duration_minutes),
        recurrence: 'weekly',
      });
      onSaved();
    } catch (err) {
      setError(apiError(err, 'Could not save this timetable entry.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative glass-strong rounded-3xl p-5 w-full max-w-md">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display font-bold text-lg">Weekly class</h3>
          <button onClick={onClose} className="p-2 rounded-xl hover:bg-surface-3"><X size={18} /></button>
        </div>

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="text-muted text-xs">Class</span>
            <select
              value={form.class_name}
              onChange={(e) => setForm({ ...form, class_name: e.target.value, section: '' })}
              className="input-field mt-1"
            >
              {classes.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>

          <label className="block text-sm">
            <span className="text-muted text-xs">Section</span>
            <select
              value={form.section}
              onChange={(e) => setForm({ ...form, section: e.target.value })}
              className="input-field mt-1"
            >
              <option value="">Whole class</option>
              {sections.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>

          <label className="block text-sm">
            <span className="text-muted text-xs">Subject</span>
            <select
              value={form.subject}
              onChange={(e) => setForm({ ...form, subject: e.target.value })}
              className="input-field mt-1"
            >
              {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="text-muted text-xs">Day</span>
              <select
                value={form.weekday}
                onChange={(e) => setForm({ ...form, weekday: e.target.value })}
                className="input-field mt-1"
              >
                {WEEKDAYS.map((day, index) => <option key={day} value={index}>{day}</option>)}
              </select>
            </label>
            <label className="block text-sm">
              <span className="text-muted text-xs">Time</span>
              <input
                type="time"
                value={form.start_time}
                onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                className="input-field mt-1"
              />
            </label>
          </div>

          <label className="block text-sm">
            <span className="text-muted text-xs">Minutes</span>
            <input
              type="number"
              min={5}
              max={300}
              value={form.duration_minutes}
              onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })}
              className="input-field mt-1"
            />
          </label>

          {error && <div className="text-sm text-rose-400">{error}</div>}

          <button onClick={save} disabled={saving} className="btn-primary w-full">
            {saving ? 'Saving…' : 'Add to timetable'}
          </button>
        </div>
      </div>
    </div>
  );
}
