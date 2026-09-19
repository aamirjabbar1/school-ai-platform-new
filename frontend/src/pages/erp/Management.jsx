/**
 * The management dashboard.
 *
 * What needs attention first, the school's numbers second, and a box to ask a
 * question in plain words. Nothing else — a dashboard that shows everything
 * shows nothing, and this one is read by people between meetings.
 *
 * Every panel appears only if the person may see it, so the Preschool Head gets
 * a shorter dashboard rather than the Owner's with gaps in it.
 */
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Empty, Note, Panel, Stat } from '../../components/erp/Kit';
import {
  AlertCircle, ArrowRight, Banknote, CalendarCheck, GraduationCap, Home,
  Loader2, Send, Sparkles, Users, Wallet,
} from 'lucide-react';

const rupees = (v) => `Rs ${Number(v || 0).toLocaleString('en-PK')}`;

const SEVERITY = {
  high: 'border-rose-500/50 text-rose-400',
  medium: 'border-amber-500/50 text-amber-400',
  low: 'border-line text-muted',
};

export default function ErpManagement() {
  const [loading, setLoading] = useState(true);
  const [dash, setDash] = useState(null);
  const [items, setItems] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [question, setQuestion] = useState('');
  const [thread, setThread] = useState([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  const bottom = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const [{ data: d }, { data: e }, { data: s }] = await Promise.all([
          erpAPI.managementDashboard(),
          erpAPI.managementExceptions(),
          erpAPI.assistantSuggestions(),
        ]);
        setDash(d);
        setItems(e.items);
        setSuggestions(s.suggestions);
      } catch (err) {
        setError(err.response?.data?.detail || 'Could not load the dashboard.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [thread]);

  const ask = async (text) => {
    const q = (text ?? question).trim();
    if (!q) return;
    setQuestion('');
    setThread((t) => [...t, { role: 'user', text: q }]);
    setAsking(true);
    try {
      const { data } = await erpAPI.assistantAsk({ question: q });
      setThread((t) => [...t, { role: 'assistant', text: data.answer, used: data.used }]);
    } catch (e) {
      setThread((t) => [...t, {
        role: 'assistant',
        text: e.response?.data?.detail || 'I could not answer that just now.',
      }]);
    } finally {
      setAsking(false);
    }
  };

  if (loading) return <Layout title="Management"><Busy label="Reading the school…" /></Layout>;

  return (
    <Layout title="Management">
      <div className="space-y-4 max-w-4xl">
        {error && <Note kind="bad">{error}</Note>}

        {/* ── Needs attention ── */}
        <Panel title="Needs attention" subtitle="Everything else is running on its own.">
          {items.length === 0 ? (
            <div className="flex items-center gap-3 text-ink py-2">
              <Sparkles className="text-brand-cyan" size={20} />
              <span className="font-semibold">Nothing needs you today.</span>
            </div>
          ) : (
            <div className="space-y-2">
              {items.map((item) => (
                <Link
                  key={item.key}
                  to={item.link}
                  className={`block rounded-2xl border p-4 ${SEVERITY[item.severity]} hover:bg-surface-2/40 transition-colors`}
                >
                  <div className="flex items-center gap-3">
                    <AlertCircle size={18} className="shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-ink">
                        <span className="text-lg font-bold">{item.count}</span>{' '}
                        <span className="text-muted">{item.label}</span>
                      </div>
                      {item.detail && (
                        <div className="text-xs text-faint truncate mt-0.5">{item.detail}</div>
                      )}
                    </div>
                    <ArrowRight size={16} className="text-faint shrink-0" />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </Panel>

        {/* ── The numbers ── */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {dash.students && (
            <Stat icon={Users} value={dash.students.active_students} label="students on the roll" />
          )}
          {dash.attendance && (
            <Stat icon={CalendarCheck}
                  value={`${dash.attendance.percentage}%`}
                  label={`present today · ${dash.attendance.absent} away`} />
          )}
          {dash.fees && (
            <Stat icon={Banknote} value={rupees(dash.fees.collected_today)} label="collected today" />
          )}
          {dash.fees && (
            <Stat icon={AlertCircle} value={rupees(dash.fees.outstanding)}
                  label={`outstanding · ${dash.fees.defaulters} students`} tone="warn" />
          )}
          {dash.payroll && (
            <Stat icon={Wallet} value={rupees(dash.payroll.total_net)}
                  label={`payroll · ${dash.payroll.status}`} />
          )}
          {dash.staff && (
            <Stat icon={GraduationCap} value={dash.staff.active_staff} label="staff" />
          )}
          {dash.families && (
            <Stat icon={Home} value={dash.families.families_with_siblings}
                  label="families with siblings here" />
          )}
        </div>

        {/* ── Ask ── */}
        <Panel title="Ask about your school" subtitle="Plain words. It reads the real data.">
          {thread.length === 0 ? (
            <div className="flex flex-wrap gap-2 mb-4">
              {suggestions.map((s) => (
                <button key={s} onClick={() => ask(s)}
                        className="px-3 py-2 rounded-xl bg-surface-2 hover:bg-surface-3 text-sm text-ink
                                   min-h-[44px] transition-colors">
                  {s}
                </button>
              ))}
            </div>
          ) : (
            <div className="space-y-3 mb-4 max-h-96 overflow-y-auto">
              {thread.map((m, i) => (
                <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
                  <div className={`inline-block max-w-[85%] rounded-2xl px-4 py-2.5 text-left
                                   ${m.role === 'user'
                                      ? 'bg-brand-blue/20 text-ink'
                                      : 'bg-surface-2 text-ink'}`}>
                    <p className="whitespace-pre-wrap text-sm">{m.text}</p>
                    {m.used?.length > 0 && (
                      <p className="text-xs text-faint mt-1.5">
                        from {m.used.join(', ').replace(/_/g, ' ')}
                      </p>
                    )}
                  </div>
                </div>
              ))}
              {asking && (
                <div className="flex items-center gap-2 text-muted text-sm">
                  <Loader2 size={14} className="animate-spin" /> Looking…
                </div>
              )}
              <div ref={bottom} />
            </div>
          )}

          <div className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') ask(); }}
              placeholder="How many students are absent today?"
              className="flex-1 min-h-[48px] rounded-xl px-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            />
            <button onClick={() => ask()} disabled={asking || !question.trim()}
                    className="btn-primary min-h-[48px] px-4">
              {asking ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
        </Panel>
      </div>
    </Layout>
  );
}
