import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import useClassroom from '../../components/classroom/useClassroom';
import VideoTile from '../../components/classroom/VideoTile';
import ConnectionBanner from '../../components/classroom/ConnectionBanner';
import Stage from '../../components/classroom/Stage';
import { onlineClassAPI } from '../../services/api';
import { Hand, Mic, MicOff, LogOut, Loader2, Signal, SignalLow } from 'lucide-react';

// The student's classroom. Two versions of the same lesson: the standard one,
// and a version for Pre-Nursery to Class 2 with three enormous buttons and no
// vocabulary a five-year-old would have to ask a parent about.
//
// The main area always shows whatever the teacher is showing — book, board,
// shared screen or camera — and switches by itself. A child should never have
// to work out which tile is the lesson.
export default function StudentClassroom() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const classroom = useClassroom({ sessionId, role: 'student' });
  const {
    status, error, session, grant, micOn, audioBlocked, remoteVideo, stage,
    deviceNotice, dismissDeviceNotice,
    lowBandwidth, connect, disconnect, toggleMic, enableAudio, applyLowBandwidth,
  } = classroom;

  const [handRaised, setHandRaised] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const young = !!session?.young_mode;

  const raiseHand = async () => {
    const next = !handRaised;
    setHandRaised(next);
    try { await onlineClassAPI.raiseHand(sessionId, next); } catch { setHandRaised(!next); }
  };

  const leave = async () => {
    setLeaving(true);
    await disconnect();
    navigate('/student/online-classes');
  };

  if (status === 'error') {
    return (
      <CenteredCard
        title="You cannot join this class"
        body={error}
        action="Back"
        onAction={() => navigate('/student/online-classes')}
      />
    );
  }

  if (status === 'ended') {
    return (
      <CenteredCard
        title="The class has ended"
        body="Your teacher has finished the lesson. Well done!"
        action="Back to my classes"
        onAction={() => navigate('/student/online-classes')}
      />
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-surface text-ink">
      <ConnectionBanner
        status={status}
        audioBlocked={audioBlocked}
        onEnableAudio={enableAudio}
        deviceNotice={deviceNotice}
        onDismissDeviceNotice={dismissDeviceNotice}
      />

      <header className="glass border-b border-line/60 px-4 py-3 flex items-center gap-3">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500" />
        </span>
        <div className="min-w-0 flex-1">
          <div className={`font-display font-bold truncate ${young ? 'text-xl' : ''}`}>
            {session?.subject || 'Class'}
          </div>
          {!young && session?.teacher_name && (
            <div className="text-xs text-muted">Teacher: {session.teacher_name}</div>
          )}
        </div>

        {/* Students are always told when a class is being recorded */}
        {session?.recording_status === 'recording' && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg
                           bg-rose-500/15 text-rose-400 text-xs font-semibold">
            <span className="h-2 w-2 rounded-full bg-rose-500 animate-pulse" />
            Recording
          </span>
        )}

        {/* Older students can trade pictures for a lesson that keeps working */}
        {!young && (
          <button
            onClick={() => applyLowBandwidth(!lowBandwidth)}
            className="btn-secondary text-xs"
            title="Turn video off to save data"
          >
            {lowBandwidth ? <SignalLow size={15} /> : <Signal size={15} />}
            {lowBandwidth ? 'Data saver on' : 'Data saver'}
          </button>
        )}
      </header>

      {/* Roughly four-fifths of the screen is the lesson itself */}
      <main className="flex-1 p-2 sm:p-3 lg:p-5 flex flex-col lg:flex-row gap-3 min-h-0">
        <div className="flex-1 min-h-[45vh] lg:min-h-0">
          <Stage classroom={classroom} sessionId={sessionId} editable={false} />
        </div>

        {/* The teacher stays visible in a corner while a book or board is up */}
        {stage.mode !== 'camera' && !lowBandwidth && (
          <div className="lg:w-56 shrink-0">
            <VideoTile
              track={remoteVideo}
              label={young ? null : session?.teacher_name}
              placeholder="Teacher"
              className="h-24 lg:h-40 w-full"
            />
          </div>
        )}
      </main>

      <footer className="glass-strong border-t border-line/60 px-3 py-4">
        <div className={`flex items-center justify-center ${young ? 'gap-4' : 'gap-3'} flex-wrap`}>
          <StudentButton
            onClick={raiseHand}
            icon={Hand}
            label={handRaised ? 'Hand up' : 'Raise hand'}
            big={young}
            tone={handRaised ? 'bg-amber-500 text-white' : 'glass text-ink'}
          />

          {grant.mic ? (
            <StudentButton
              onClick={toggleMic}
              icon={micOn ? Mic : MicOff}
              label={micOn ? 'Speaking' : 'Speak'}
              big={young}
              tone={micOn ? 'bg-emerald-500 text-white' : 'glass text-ink'}
            />
          ) : (
            <StudentButton disabled icon={MicOff} label="Mic off" big={young} tone="glass text-faint" />
          )}

          <StudentButton
            onClick={leave}
            icon={leaving ? Loader2 : LogOut}
            label="Leave"
            big={young}
            tone="bg-rose-500 text-white"
            spin={leaving}
          />
        </div>

        {!grant.mic && !young && (
          <p className="text-center text-xs text-muted mt-3">
            Raise your hand and your teacher will turn on your microphone.
          </p>
        )}
      </footer>
    </div>
  );
}

function StudentButton({ onClick, icon: Icon, label, tone, big, disabled, spin }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex flex-col items-center justify-center gap-1.5 rounded-3xl font-bold
                  transition-transform hover:-translate-y-0.5 disabled:hover:translate-y-0
                  disabled:opacity-70 ${tone}
                  ${big ? 'px-8 py-6 min-w-[8rem] text-lg' : 'px-6 py-4 min-w-[6rem]'}`}
    >
      <Icon size={big ? 36 : 24} className={spin ? 'animate-spin' : ''} />
      <span className={big ? 'text-base' : 'text-xs'}>{label}</span>
    </button>
  );
}

function CenteredCard({ title, body, action, onAction }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-surface text-ink">
      <div className="card max-w-md text-center">
        <div className="font-display font-bold text-lg">{title}</div>
        {body && <p className="text-muted text-sm mt-2">{body}</p>}
        <button onClick={onAction} className="btn-primary mt-5">{action}</button>
      </div>
    </div>
  );
}
