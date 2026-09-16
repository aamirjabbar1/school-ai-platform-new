import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import Layout from '../../components/Layout';
import StatCard from '../../components/StatCard';
import { liveClassAdminAPI } from '../../services/api';
import {
  Radio, Users, GraduationCap, Eye, PhoneOff, Clock, Video, AlertTriangle,
  ScrollText, BarChart3, Settings as SettingsIcon, RefreshCw, Sparkles,
} from 'lucide-react';

// The control room (spec §14). Every number here is counted from the
// classroom's own records — who joined, when, what was shown — so an
// administrator is looking at what happened, not at an estimate.
const TABS = [
  { id: 'live', label: 'Live now', icon: Radio },
  { id: 'history', label: 'History', icon: Clock },
  { id: 'logs', label: 'Logs', icon: ScrollText },
  { id: 'report', label: 'Reports', icon: BarChart3 },
  { id: 'ai', label: 'AI usage', icon: Sparkles },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
];

export default function AdminLiveClasses() {
  const [tab, setTab] = useState('live');
  const [overview, setOverview] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = () => {
    setRefreshing(true);
    liveClassAdminAPI.overview()
      .then(({ data }) => setOverview(data))
      .catch(() => {})
      .finally(() => setRefreshing(false));
  };

  // A control room that is stale is worse than no control room.
  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const counts = overview?.counts || {};

  return (
    <Layout title="Live Classes">
      {!overview?.media_server_configured && (
        <div className="card mb-5 flex items-center gap-3 border-l-4 border-amber-500">
          <AlertTriangle className="text-amber-400 shrink-0" size={20} />
          <div className="text-sm">
            <div className="font-semibold text-ink">Online Classes is not connected yet</div>
            <div className="text-muted">
              Set the LiveKit variables on the server, then redeploy. Everything else
              in LSS Bot keeps working meanwhile.
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard icon={Radio} value={counts.live_classes ?? '—'} label="Classes Live" sub="right now" color="red" />
        <StatCard icon={Users} value={counts.students_online ?? '—'} label="Students Online" sub="connected" color="blue" delay={0.06} />
        <StatCard icon={GraduationCap} value={counts.teachers_online ?? '—'} label="Teachers Online" sub="teaching" color="green" delay={0.12} />
        <StatCard
          icon={Video}
          value={overview?.recording_configured ? 'On' : 'Off'}
          label="Recording"
          sub={overview?.recording_configured ? 'available' : 'not configured'}
          color="purple"
          delay={0.18}
        />
      </div>

      <div className="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-3.5 py-2 rounded-xl text-sm font-medium whitespace-nowrap flex items-center gap-2 ${
              tab === id ? 'bg-brand-blue text-white' : 'glass text-muted hover:text-ink'}`}
          >
            <Icon size={15} /> {label}
          </button>
        ))}
        <button onClick={load} className="ml-auto btn-secondary text-sm" disabled={refreshing}>
          <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {tab === 'live' && <LiveTab classes={overview?.classes || []} onChanged={load} />}
      {tab === 'history' && <HistoryTab />}
      {tab === 'logs' && <LogsTab />}
      {tab === 'report' && <ReportTab />}
      {tab === 'ai' && <AIUsageTab />}
      {tab === 'settings' && <SettingsTab />}
    </Layout>
  );
}

// ─── Live ─────────────────────────────────────────────────────────────────────

function LiveTab({ classes, onChanged }) {
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');

  const observe = async (session) => {
    setBusy(session.id);
    try {
      const { data } = await liveClassAdminAPI.observe(session.id);
      setNotice(
        data.announced
          ? `Joining ${session.subject}. The class has been told you are observing.`
          : `Joining ${session.subject}.`,
      );
      window.open(`/admin/observe/${session.id}`, '_blank', 'noopener');
    } catch (err) {
      setNotice(err?.response?.data?.detail || 'Could not open that class.');
    } finally {
      setBusy('');
    }
  };

  const forceEnd = async (session) => {
    // eslint-disable-next-line no-alert
    if (!window.confirm(`End ${session.subject} for ${session.class_name}? Everyone will be disconnected.`)) return;
    setBusy(session.id);
    try {
      await liveClassAdminAPI.forceEnd(session.id);
      onChanged();
    } finally { setBusy(''); }
  };

  if (!classes.length) {
    return <div className="card text-muted text-sm text-center py-10">No classes are live right now.</div>;
  }

  return (
    <>
      {notice && <div className="card mb-3 text-sm">{notice}</div>}
      <div className="space-y-3">
        {classes.map((session) => (
          <motion.div
            key={session.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="card flex flex-col sm:flex-row sm:items-center gap-3"
          >
            <span className="relative flex h-3 w-3 shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500" />
            </span>

            <div className="flex-1 min-w-0">
              <div className="font-semibold text-ink">
                {session.subject} — {session.class_name}{session.section ? ` (${session.section})` : ''}
              </div>
              <div className="text-sm text-muted">
                {session.teacher_name} · started{' '}
                {session.actual_start && new Date(session.actual_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                {' · '}{session.minutes_running} min
                {' · '}{session.students_online} student{session.students_online === 1 ? '' : 's'}
                {session.hands_raised > 0 && ` · ${session.hands_raised} hand${session.hands_raised === 1 ? '' : 's'} up`}
                {session.recording_status === 'recording' && ' · recording'}
              </div>
            </div>

            <div className="flex gap-2">
              <button onClick={() => observe(session)} disabled={busy === session.id} className="btn-secondary text-sm">
                <Eye size={15} /> Observe
              </button>
              <button onClick={() => forceEnd(session)} disabled={busy === session.id} className="btn-secondary text-sm text-rose-400">
                <PhoneOff size={15} /> End
              </button>
            </div>
          </motion.div>
        ))}
      </div>
    </>
  );
}

// ─── History ──────────────────────────────────────────────────────────────────

function HistoryTab() {
  const [classes, setClasses] = useState([]);
  const [days, setDays] = useState(7);

  useEffect(() => {
    liveClassAdminAPI.history({ days }).then(({ data }) => setClasses(data.classes || [])).catch(() => {});
  }, [days]);

  return (
    <>
      <div className="flex gap-2 mb-3">
        {[1, 7, 30].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`px-3 py-1.5 rounded-xl text-sm ${days === d ? 'bg-brand-blue text-white' : 'glass text-muted'}`}
          >
            {d === 1 ? 'Today' : `${d} days`}
          </button>
        ))}
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-2 pr-3 font-medium">Class</th>
              <th className="py-2 pr-3 font-medium">Teacher</th>
              <th className="py-2 pr-3 font-medium">Started</th>
              <th className="py-2 pr-3 font-medium">Minutes</th>
              <th className="py-2 pr-3 font-medium">Attended</th>
              <th className="py-2 font-medium">Recording</th>
            </tr>
          </thead>
          <tbody>
            {classes.map((s) => (
              <tr key={s.id} className="border-t border-line/50">
                <td className="py-2 pr-3">
                  {s.subject} — {s.class_name}{s.section ? ` (${s.section})` : ''}
                </td>
                <td className="py-2 pr-3 text-muted">{s.teacher_name}</td>
                <td className="py-2 pr-3 text-muted">
                  {s.actual_start && new Date(s.actual_start).toLocaleString([], {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                  })}
                </td>
                <td className="py-2 pr-3">{Math.round((s.duration_seconds || 0) / 60)}</td>
                <td className="py-2 pr-3">
                  {s.students_attended}/{s.students_on_register}
                  <span className="text-xs text-faint"> ({s.attendance_rate}%)</span>
                </td>
                <td className="py-2 text-muted">{s.recording ? s.recording.status : '—'}</td>
              </tr>
            ))}
            {classes.length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-muted">No classes in this period.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ─── Logs ─────────────────────────────────────────────────────────────────────

function LogsTab() {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    liveClassAdminAPI.logs({ hours: 24 }).then(({ data }) => setEvents(data.events || [])).catch(() => {});
  }, []);

  return (
    <div className="card">
      <p className="text-xs text-muted mb-3">
        Classroom actions from the last 24 hours. Records what was done, never what was said.
      </p>
      <div className="space-y-1.5 max-h-[32rem] overflow-y-auto">
        {events.map((e) => (
          <div key={e.id} className="flex items-start gap-3 text-sm py-1.5 border-b border-line/40">
            <span className="text-xs text-faint w-16 shrink-0">
              {new Date(e.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
            <span className="font-medium text-ink w-40 shrink-0 truncate">{e.type.replace(/_/g, ' ')}</span>
            <span className="text-muted truncate">
              {e.subject} — {e.class_name}{e.section ? ` (${e.section})` : ''} · {e.teacher_name}
            </span>
          </div>
        ))}
        {events.length === 0 && <p className="text-sm text-muted py-6 text-center">Nothing logged yet.</p>}
      </div>
    </div>
  );
}

// ─── Reports ──────────────────────────────────────────────────────────────────

function ReportTab() {
  const [report, setReport] = useState(null);

  useEffect(() => {
    liveClassAdminAPI.report({ days: 30 }).then(({ data }) => setReport(data)).catch(() => {});
  }, []);

  if (!report) return <div className="card text-muted text-sm">Loading…</div>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="card">
        <div className="font-semibold mb-1">Average attendance</div>
        <div className="text-3xl font-display font-bold text-gradient-soft">
          {report.average_attendance_percent}%
        </div>
        <div className="text-xs text-muted mt-1">across the last {report.days} days</div>
      </div>

      <div className="card">
        <div className="font-semibold mb-2">Classes by teacher</div>
        <div className="space-y-1.5 max-h-64 overflow-y-auto">
          {report.by_teacher.map((row) => (
            <div key={row.teacher_id} className="flex justify-between text-sm">
              <span className="text-muted truncate">{row.teacher_name}</span>
              <span className="font-semibold">{row.classes}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card lg:col-span-2">
        <div className="font-semibold mb-2">Classes by class group</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {report.by_class.map((row) => (
            <div key={`${row.class_name}-${row.section}`} className="glass rounded-xl px-3 py-2 text-sm flex justify-between">
              <span className="text-muted truncate">
                {row.class_name}{row.section ? ` (${row.section})` : ''}
              </span>
              <span className="font-semibold">{row.classes}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Settings ─────────────────────────────────────────────────────────────────

function SettingsTab() {
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState('');

  useEffect(() => {
    liveClassAdminAPI.getSettings().then(({ data }) => setSettings(data)).catch(() => {});
  }, []);

  const update = (field, value) => setSettings((prev) => ({ ...prev, [field]: value }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await liveClassAdminAPI.updateSettings(settings);
      setSettings(data);
      setSaved('Settings saved.');
      setTimeout(() => setSaved(''), 4000);
    } finally { setSaving(false); }
  };

  if (!settings) return <div className="card text-muted text-sm">Loading…</div>;

  return (
    <div className="space-y-4">
      <Section title="Attendance rules" note="How online attendance is scored (spec §13).">
        <Number label="Present at or above (%)" value={settings.present_min_percent} onChange={(v) => update('present_min_percent', v)} />
        <Number label="Partial at or above (%)" value={settings.partial_min_percent} onChange={(v) => update('partial_min_percent', v)} />
        <Number label="Late after (minutes)" value={settings.late_after_minutes} onChange={(v) => update('late_after_minutes', v)} />
      </Section>

      <Section title="Classroom" note="Young classes get the simplified interface and stricter defaults.">
        <Number label="Teacher reconnect grace (minutes)" value={settings.teacher_grace_minutes} onChange={(v) => update('teacher_grace_minutes', v)} />
        <Number label="Students may join early (minutes)" value={settings.join_early_minutes} onChange={(v) => update('join_early_minutes', v)} />
        <Toggle label="Allow administrators to observe classes" value={settings.allow_admin_observe} onChange={(v) => update('allow_admin_observe', v)} />
        <Toggle label="Tell the class when an administrator is observing" value={settings.announce_admin_observe} onChange={(v) => update('announce_admin_observe', v)} />
      </Section>

      <Section title="Recording" note="Recordings are video only. They are never transcribed or sent to an AI service.">
        <Toggle label="Recording available school-wide" value={settings.recording_enabled_globally} onChange={(v) => update('recording_enabled_globally', v)} />
        <Toggle label="Record scheduled classes by default" value={settings.recording_default_on} onChange={(v) => update('recording_default_on', v)} />
        <Number label="Keep recordings for (days, 0 = until deleted)" value={settings.recording_retention_days} onChange={(v) => update('recording_retention_days', v)} />
        <Number label="Maximum classes recording at once" value={settings.max_concurrent_recordings} onChange={(v) => update('max_concurrent_recordings', v)} />
      </Section>

      <Section title="AI features" note="Text-to-text only. Speech-to-text is not part of this system.">
        <Toggle label="AI class summary" value={settings.ai_class_summary_enabled} onChange={(v) => update('ai_class_summary_enabled', v)} />
        <Toggle label="Lesson plan coverage analysis" value={settings.ai_coverage_analysis_enabled} onChange={(v) => update('ai_coverage_analysis_enabled', v)} />
        <Toggle label="AI revision notes" value={settings.ai_revision_notes_enabled} onChange={(v) => update('ai_revision_notes_enabled', v)} />
        <Toggle label="Ask LSS AI about this class" value={settings.ai_ask_enabled} onChange={(v) => update('ai_ask_enabled', v)} />
        <Toggle label="Teacher AI assistant" value={settings.ai_teacher_assistant_enabled} onChange={(v) => update('ai_teacher_assistant_enabled', v)} />
      </Section>

      <Section title="AI budget" note="Spending stops at these limits; classes keep running regardless.">
        <Number label="Daily budget (USD)" value={settings.ai_daily_budget_usd} onChange={(v) => update('ai_daily_budget_usd', v)} step="0.5" />
        <Number label="Monthly budget (USD)" value={settings.ai_monthly_budget_usd} onChange={(v) => update('ai_monthly_budget_usd', v)} step="5" />
        <Number label="Student questions per day" value={settings.ai_max_questions_per_student_per_day} onChange={(v) => update('ai_max_questions_per_student_per_day', v)} />
        <Number label="AI calls per class" value={settings.ai_max_calls_per_session} onChange={(v) => update('ai_max_calls_per_session', v)} />
      </Section>

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving} className="btn-primary">
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        {saved && <span className="text-sm text-emerald-400">{saved}</span>}
      </div>
    </div>
  );
}

function Section({ title, note, children }) {
  return (
    <div className="card">
      <div className="font-semibold text-ink">{title}</div>
      {note && <p className="text-xs text-muted mt-0.5 mb-3">{note}</p>}
      <div className="space-y-2.5">{children}</div>
    </div>
  );
}

function Number({ label, value, onChange, step = '1' }) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm">
      <span className="text-muted">{label}</span>
      <input
        type="number"
        step={step}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : parseFloat(e.target.value))}
        className="input-field w-28 text-right"
      />
    </label>
  );
}

function Toggle({ label, value, onChange }) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
      <span className="text-muted">{label}</span>
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} className="w-4 h-4" />
    </label>
  );
}

// ─── AI usage (spec §19G) ─────────────────────────────────────────────────────

function AIUsageTab() {
  const [usage, setUsage] = useState(null);

  useEffect(() => {
    liveClassAdminAPI.aiUsage({ days: 30 }).then(({ data }) => setUsage(data)).catch(() => {});
  }, []);

  if (!usage) return <div className="card text-muted text-sm">Loading…</div>;

  const budget = usage.budgets || {};

  return (
    <div className="space-y-4">
      {usage.alerts?.length > 0 && (
        <div className="card border-l-4 border-amber-500 text-sm space-y-1">
          {usage.alerts.map((alert) => (
            <div key={alert} className="text-amber-400">{alert}</div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card">
          <div className="text-xs text-muted uppercase">Today</div>
          <div className="text-2xl font-display font-bold text-ink">${usage.today_usd}</div>
          <div className="text-xs text-muted mt-1">
            {budget.daily_used_percent}% of ${budget.daily_usd} budget
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">This month</div>
          <div className="text-2xl font-display font-bold text-ink">${usage.month_usd}</div>
          <div className="text-xs text-muted mt-1">
            {budget.monthly_used_percent}% of ${budget.monthly_usd} budget
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Models in use</div>
          <div className="text-sm text-ink mt-1">{usage.models?.capable}</div>
          <div className="text-sm text-muted">{usage.models?.fast}</div>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <div className="font-semibold text-ink mb-2">By feature</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-2 pr-3 font-medium">Feature</th>
              <th className="py-2 pr-3 font-medium">Requests</th>
              <th className="py-2 pr-3 font-medium">Input tokens</th>
              <th className="py-2 pr-3 font-medium">Output tokens</th>
              <th className="py-2 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {usage.by_feature.map((row) => (
              <tr key={row.feature} className="border-t border-line/50">
                <td className="py-2 pr-3 capitalize">{row.feature.replace(/_/g, ' ')}</td>
                <td className="py-2 pr-3">{row.requests}</td>
                <td className="py-2 pr-3 text-muted">{row.input_tokens.toLocaleString()}</td>
                <td className="py-2 pr-3 text-muted">{row.output_tokens.toLocaleString()}</td>
                <td className="py-2">${row.cost_usd}</td>
              </tr>
            ))}
            {usage.by_feature.length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-muted">No AI usage yet.</td></tr>
            )}
          </tbody>
        </table>
        <p className="text-xs text-faint mt-3">
          Text-to-text only. There is no speech-to-text or transcription cost, because
          the classroom never sends audio to an AI service.
        </p>
      </div>

      {usage.by_class.length > 0 && (
        <div className="card">
          <div className="font-semibold text-ink mb-2">By class</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {usage.by_class.map((row) => (
              <div key={row.class_name} className="glass rounded-xl px-3 py-2 text-sm flex justify-between">
                <span className="text-muted truncate">{row.class_name}</span>
                <span className="font-semibold">${row.cost_usd}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
