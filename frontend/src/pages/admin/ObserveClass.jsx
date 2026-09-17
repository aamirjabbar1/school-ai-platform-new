import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import useClassroom from '../../components/classroom/useClassroom';
import Stage from '../../components/classroom/Stage';
import VideoTile from '../../components/classroom/VideoTile';
import ConnectionBanner from '../../components/classroom/ConnectionBanner';
import { Eye, LogOut, Users } from 'lucide-react';

// An administrator sitting in on a class (spec §14, §24).
//
// Read-only by construction: the token issued for this page cannot publish
// audio, video or data, so an observer cannot accidentally interrupt a lesson.
// Unless the school has turned the announcement off, the class is told an
// administrator is present — and either way it is written to the audit log.
export default function ObserveClass() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const classroom = useClassroom({ sessionId, role: 'observer' });
  const {
    status, error, session, participants, remoteVideo, stage, attendance,
    audioBlocked, connect, disconnect, enableAudio,
  } = classroom;

  useEffect(() => {
    connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const leave = async () => {
    await disconnect();
    navigate('/admin/live-classes');
  };

  if (status === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-surface text-ink">
        <div className="card max-w-md text-center">
          <div className="font-display font-bold text-lg">Could not open this class</div>
          <p className="text-muted text-sm mt-2">{error}</p>
          <button onClick={() => navigate('/admin/live-classes')} className="btn-primary mt-4">
            Back to Live Classes
          </button>
        </div>
      </div>
    );
  }

  const studentsPresent = attendance.filter((r) => r.role === 'student' && r.is_connected).length;

  return (
    <div className="min-h-screen flex flex-col bg-surface text-ink">
      <ConnectionBanner status={status} audioBlocked={audioBlocked} onEnableAudio={enableAudio} />

      <header className="glass border-b border-line/60 px-4 py-3 flex items-center gap-3">
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-brand-purple/20 text-brand-violet text-xs font-semibold">
          <Eye size={14} /> Observing
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-display font-bold truncate">
            {session?.subject} — {session?.class_name}{session?.section ? ` (${session.section})` : ''}
          </div>
          <div className="text-xs text-muted">
            {session?.teacher_name} · {studentsPresent || participants.length} connected
          </div>
        </div>
        <button onClick={leave} className="btn-secondary text-sm">
          <LogOut size={15} /> Leave
        </button>
      </header>

      <main className="flex-1 p-3 lg:p-5 flex flex-col lg:flex-row gap-3 min-h-0">
        <div className="relative flex-1 min-h-[45vh] lg:min-h-0">
          <Stage classroom={classroom} sessionId={sessionId} editable={false} />
        </div>

        <aside className="lg:w-72 shrink-0 flex flex-col gap-3">
          {stage.mode !== 'camera' && (
            <VideoTile track={remoteVideo} label={session?.teacher_name} placeholder="Teacher"
                       className="h-32 w-full" />
          )}
          <div className="glass-strong rounded-2xl p-3 flex-1 overflow-y-auto">
            <div className="flex items-center gap-2 mb-2 text-sm font-semibold">
              <Users size={15} /> In this class
            </div>
            <div className="space-y-1.5">
              {attendance.filter((r) => r.role === 'student').map((row) => (
                <div key={row.id} className="flex items-center gap-2 text-sm">
                  <span className={`h-2 w-2 rounded-full ${row.is_connected ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                  <span className="truncate flex-1">{row.user_name}</span>
                  <span className="text-xs text-faint">{row.total_minutes}m</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
}
