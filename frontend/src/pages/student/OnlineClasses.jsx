import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import { onlineClassAPI } from '../../services/api';
import { Video, CalendarClock, CheckCircle2 } from 'lucide-react';

// TODAY'S CLASSES. When a teacher starts, a red LIVE card appears here and the
// student presses one button. There is nothing to type, nothing to remember,
// and no way to end up in the wrong class — the server already knows theirs.
export default function StudentOnlineClasses() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [live, setLive] = useState([]);
  const [finished, setFinished] = useState([]);
  const [young, setYoung] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = () => onlineClassAPI.today()
    .then(({ data }) => {
      setLive(data.live || []);
      setFinished(data.finished || []);
      setYoung(!!data.young_mode);
    })
    .catch(() => {})
    .finally(() => setLoading(false));

  // A class can start at any moment, so the list refreshes on a slow timer.
  useEffect(() => {
    load();
    const timer = setInterval(load, 20000);
    return () => clearInterval(timer);
  }, []);

  return (
    <Layout title={young ? 'My Class' : "Today's Classes"}>
      {live.length > 0 ? (
        <div className="space-y-4 mb-8">
          {live.map((s) => (
            <motion.div
              key={s.id}
              initial={{ opacity: 0, scale: 0.97 }}
              animate={{ opacity: 1, scale: 1 }}
              className="relative overflow-hidden rounded-3xl p-6 text-white shadow-glow-lg"
            >
              <div className="absolute inset-0 bg-gradient-to-br from-rose-500 via-brand-violet to-brand-blue" />
              <div className="relative z-10 text-center sm:text-left">
                <div className="inline-flex items-center gap-2 bg-white/20 rounded-full px-3 py-1 text-sm font-bold">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white" />
                  </span>
                  {young ? 'YOUR CLASS IS LIVE' : 'LIVE'}
                </div>

                <h2 className={`font-display font-bold mt-3 ${young ? 'text-4xl' : 'text-2xl'}`}>
                  {s.subject}
                </h2>
                <p className="text-white/90 mt-1">Teacher: {s.teacher_name}</p>

                <button
                  onClick={() => navigate(`/student/classroom/${s.id}`)}
                  className={`mt-5 w-full sm:w-auto inline-flex items-center justify-center gap-3
                              rounded-2xl bg-white text-brand-blue font-bold shadow-lg
                              transition-transform hover:-translate-y-0.5
                              ${young ? 'px-10 py-6 text-2xl' : 'px-8 py-4 text-lg'}`}
                >
                  <Video size={young ? 30 : 22} />
                  JOIN CLASS
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <div className="card text-center py-10 mb-8">
          <CalendarClock size={38} className="mx-auto text-faint mb-3" />
          <div className="font-display font-semibold text-ink">
            {loading ? 'Checking for classes…' : 'No class is live right now'}
          </div>
          <p className="text-sm text-muted mt-1">
            {young
              ? 'Your teacher will start the class soon.'
              : `When your ${user?.class_name || 'class'} teacher starts a class, it appears here.`}
          </p>
        </div>
      )}

      {!young && finished.length > 0 && (
        <>
          <h3 className="font-display font-bold text-ink mb-3">Finished today</h3>
          <div className="space-y-2.5">
            {finished.map((s) => (
              <button
                key={s.id}
                onClick={() => navigate(`/student/class-summary/${s.id}`)}
                className="card w-full flex items-center gap-3 py-4 text-left hover:shadow-glow transition-shadow"
              >
                <CheckCircle2 size={18} className="text-emerald-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-ink truncate">{s.subject}</div>
                  <div className="text-sm text-muted">
                    {s.teacher_name} ·{' '}
                    {s.actual_start && new Date(s.actual_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
                <span className="text-xs text-brand-cyan font-semibold whitespace-nowrap">
                  Summary &amp; Ask AI
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </Layout>
  );
}
