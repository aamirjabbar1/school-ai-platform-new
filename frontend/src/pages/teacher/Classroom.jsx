import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import useClassroom from '../../components/classroom/useClassroom';
import VideoTile from '../../components/classroom/VideoTile';
import ConnectionBanner from '../../components/classroom/ConnectionBanner';
import Stage from '../../components/classroom/Stage';
import ResourcePicker from '../../components/classroom/ResourcePicker';
import AttendanceReport from '../../components/classroom/AttendanceReport';
import { onlineClassAPI } from '../../services/api';
import { apiError } from '../../services/apiError';
import {
  Mic, MicOff, Video, VideoOff, Users, PhoneOff, Hand, VolumeX, UserMinus,
  Lock, Unlock, X, Loader2, PenLine, BookOpen, MonitorUp, Camera, Presentation, Circle,
} from 'lucide-react';

// The teaching interface. Large, unambiguous controls and no conferencing
// vocabulary: a teacher who has never used video software should be able to
// start, teach and end a lesson without being taught how.
export default function TeacherClassroom() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const classroom = useClassroom({ sessionId, role: 'teacher' });
  const {
    status, error, session, hands, participants, attendance, micOn, cameraOn,
    audioBlocked, localVideo, stage, screenSharing, docCameraOn, boardStrokes, board,
    connect, disconnect, toggleMic, toggleCamera, enableAudio, refreshState,
    toggleScreenShare, toggleDocumentCamera, changeStage, presentDocument,
    recordingAvailable,
  } = classroom;

  const boardRef = useRef(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [ending, setEnding] = useState(false);
  const [savingBoard, setSavingBoard] = useState(false);
  const [notice, setNotice] = useState('');
  const showAttendanceOnly = params.get('view') === 'attendance';

  useEffect(() => {
    if (showAttendanceOnly) return;
    connect();
    // connect() rejoins the room; re-running it on every render would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(''), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  const students = useMemo(() => {
    const handSet = new Set(hands.map((h) => h.user_id));
    const connected = new Map(participants.map((p) => [p.identity, p]));
    return attendance
      .filter((row) => row.role === 'student')
      .map((row) => ({ ...row, live: connected.get(row.user_id), handRaised: handSet.has(row.user_id) }))
      .sort((a, b) => (
        Number(b.handRaised) - Number(a.handRaised)
        || Number(!!b.live) - Number(!!a.live)
        || (a.user_name || '').localeCompare(b.user_name || '')
      ));
  }, [attendance, participants, hands]);

  const run = async (key, fn) => {
    setBusy(key);
    try { await fn(); await refreshState(); } finally { setBusy(''); }
  };

  const endClass = async () => {
    setEnding(true);
    try {
      await onlineClassAPI.end(sessionId);
      await disconnect();
      navigate('/teacher/online-classes');
    } catch { setEnding(false); }
  };

  const saveBoard = async () => {
    setSavingBoard(true);
    try {
      await onlineClassAPI.saveWhiteboard(sessionId, {
        page_index: board.pageIndex,
        strokes: boardStrokes,
        image_base64: boardRef.current?.toPNG?.() || null,
      });
      setNotice('Board saved to today’s lesson record.');
    } catch {
      setNotice('Could not save the board. Your writing is still on screen.');
    } finally {
      setSavingBoard(false);
    }
  };

  const recording = session?.recording_status === 'recording';

  const toggleRecording = async () => {
    setBusy('record');
    try {
      if (recording) {
        await onlineClassAPI.stopRecording(sessionId);
        setNotice('Recording stopped. It will appear in Recorded Classes shortly.');
      } else {
        await onlineClassAPI.startRecording(sessionId);
        setNotice('Recording started. Students can see that this class is being recorded.');
      }
      await refreshState();
    } catch (err) {
      setNotice(apiError(err, 'Recording could not be changed.'));
    } finally {
      setBusy('');
    }
  };

  const shareScreen = async () => {
    const result = await toggleScreenShare();
    if (!result.ok && result.reason === 'unsupported') {
      // Rather than a button that silently fails on a phone, say what works.
      setNotice('This device cannot share a screen. Use Show Book to point the camera at your book.');
    } else if (!result.ok && result.reason === 'failed') {
      setNotice('Screen sharing did not start. Please try again.');
    }
  };

  const showPhysicalBook = async () => {
    const result = await toggleDocumentCamera();
    if (!result.ok) setNotice('Could not switch to the rear camera on this device.');
  };

  if (showAttendanceOnly) {
    return <AttendanceReport sessionId={sessionId} onBack={() => navigate('/teacher/online-classes')} />;
  }

  if (status === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center p-6 text-center">
        <div className="card max-w-md">
          <div className="font-display font-bold text-lg text-ink">Could not start the class</div>
          <p className="text-muted text-sm mt-2">{error}</p>
          <button onClick={() => navigate('/teacher/online-classes')} className="btn-primary mt-4">
            Back to Online Classes
          </button>
        </div>
      </div>
    );
  }

  if (status === 'ended') {
    return <AttendanceReport sessionId={sessionId} onBack={() => navigate('/teacher/online-classes')} ended />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-surface text-ink">
      <ConnectionBanner status={status} audioBlocked={audioBlocked} onEnableAudio={enableAudio} />

      <header className="glass border-b border-line/60 px-4 py-3 flex items-center gap-3">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-display font-bold truncate">
            {session?.subject} — {session?.class_name}{session?.section ? ` (${session.section})` : ''}
          </div>
          <div className="text-xs text-muted">
            {status === 'connecting' ? 'Connecting…' : `${participants.length} connected`}
          </div>
        </div>
        <button onClick={() => setPanelOpen(true)} className="relative btn-secondary text-sm">
          <Users size={16} /> Students
          {hands.length > 0 && (
            <span className="absolute -top-1.5 -right-1.5 h-5 min-w-5 px-1 rounded-full bg-amber-500
                             text-white text-[11px] font-bold flex items-center justify-center">
              {hands.length}
            </span>
          )}
        </button>
      </header>

      {/* Stage + own camera. The lesson gets the space; the teacher's face is
          a thumbnail, because what is being taught matters more than who. */}
      <main className="flex-1 p-3 lg:p-5 flex flex-col lg:flex-row gap-3 min-h-0">
        <div className="flex-1 min-h-[45vh] lg:min-h-0">
          <Stage
            classroom={classroom}
            sessionId={sessionId}
            editable
            boardRef={boardRef}
            onSaveBoard={saveBoard}
            savingBoard={savingBoard}
          />
        </div>

        {stage.mode !== 'camera' && (
          <div className="lg:w-56 shrink-0">
            <VideoTile
              track={localVideo}
              mirrored={!docCameraOn}
              label="You"
              placeholder="Camera off"
              className="h-28 lg:h-40 w-full"
            />
          </div>
        )}
      </main>

      {hands.length > 0 && (
        <div className="mx-3 mb-2 glass-strong rounded-2xl px-4 py-2.5 flex items-center gap-3 flex-wrap">
          <Hand size={18} className="text-amber-400 shrink-0" />
          <span className="text-sm font-medium">
            {hands[0].user_name}{hands.length > 1 && ` and ${hands.length - 1} more`} want to speak
          </span>
          <button
            onClick={() => run('grant', () => onlineClassAPI.setPermissions(sessionId, {
              user_id: hands[0].user_id, mic: true, camera: false,
            }))}
            disabled={busy === 'grant'}
            className="btn-primary text-sm ml-auto"
          >
            Let {hands[0].user_name?.split(' ')[0]} speak
          </button>
        </div>
      )}

      {notice && (
        <div className="mx-3 mb-2 glass rounded-2xl px-4 py-2.5 text-sm text-ink">{notice}</div>
      )}

      {/* Teaching tools + classroom controls */}
      <footer className="glass-strong border-t border-line/60 px-3 py-3">
        <div className="flex items-center justify-center gap-2 sm:gap-3 flex-wrap">
          <Tool
            icon={PenLine} label="Whiteboard" active={stage.mode === 'whiteboard'}
            onClick={() => changeStage('whiteboard', { page: board.pageIndex })}
          />
          <Tool icon={BookOpen} label="Open Book" active={stage.mode === 'book'}
                onClick={() => setPickerOpen(true)} />
          <Tool icon={MonitorUp} label="Share Screen" active={screenSharing} onClick={shareScreen} />
          <Tool icon={Presentation} label="Show Book" active={docCameraOn} onClick={showPhysicalBook} />
          <Tool icon={Camera} label="Camera view" active={stage.mode === 'camera'}
                onClick={() => changeStage('camera', null)} />

          <span className="w-px h-8 bg-line mx-1 hidden sm:block" />

          <Tool icon={micOn ? Mic : MicOff} label={micOn ? 'Mute' : 'Unmute'}
                danger={!micOn} onClick={toggleMic} />
          <Tool icon={cameraOn ? Video : VideoOff} label={cameraOn ? 'Stop video' : 'Start video'}
                danger={!cameraOn} onClick={toggleCamera} />
          <Tool icon={VolumeX} label="Mute all" busy={busy === 'muteall'}
                onClick={() => run('muteall', () => onlineClassAPI.muteAll(sessionId))} />
          {/* Shown only when the school has recording switched on and the
              recorder is configured — otherwise there is no button to press. */}
          {recordingAvailable && (
            <Tool
              icon={Circle}
              label={recording ? 'Stop rec' : 'Record'}
              active={recording}
              busy={busy === 'record'}
              onClick={toggleRecording}
            />
          )}
          <Tool
            icon={session?.is_locked ? Lock : Unlock}
            label={session?.is_locked ? 'Unlock' : 'Lock class'}
            busy={busy === 'lock'}
            onClick={() => run('lock', () => onlineClassAPI.lockClass(sessionId, !session?.is_locked))}
          />

          <button onClick={endClass} disabled={ending} className="btn-danger px-5 py-3 rounded-2xl">
            {ending ? <Loader2 size={20} className="animate-spin" /> : <PhoneOff size={20} />}
            End Class
          </button>
        </div>
      </footer>

      <ResourcePicker
        sessionId={sessionId}
        subject={session?.subject}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPresent={presentDocument}
      />

      {/* Students panel */}
      <AnimatePresence>
        {panelOpen && (
          <div className="fixed inset-0 z-40">
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm"
              onClick={() => setPanelOpen(false)}
            />
            <motion.aside
              initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
              className="absolute right-0 top-0 bottom-0 w-full sm:w-96 glass-strong p-4 overflow-y-auto"
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-display font-bold text-lg">Students</h2>
                <button onClick={() => setPanelOpen(false)} className="p-2 rounded-xl hover:bg-surface-3">
                  <X size={18} />
                </button>
              </div>

              <button
                onClick={() => run('cameras', () => onlineClassAPI.lockCameras(sessionId, !session?.cameras_locked))}
                className="btn-secondary text-xs w-full mb-3"
              >
                {session?.cameras_locked ? 'Allow student cameras' : 'Turn off student cameras'}
              </button>

              {students.length === 0 && <p className="text-sm text-muted">Nobody has joined yet.</p>}

              <div className="space-y-2">
                {students.map((s) => (
                  <div key={s.user_id} className="glass rounded-2xl p-3">
                    <div className="flex items-center gap-2.5">
                      <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${s.live ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-sm truncate flex items-center gap-1.5">
                          {s.user_name}
                          {s.handRaised && <Hand size={14} className="text-amber-400" />}
                        </div>
                        <div className="text-xs text-muted">
                          {s.live ? 'In class' : 'Not connected'} · {s.total_minutes} min
                        </div>
                      </div>
                    </div>
                    {s.live && (
                      <div className="flex gap-1.5 mt-2.5">
                        <button
                          onClick={() => run(`mic-${s.user_id}`, () => onlineClassAPI.setPermissions(sessionId, {
                            user_id: s.user_id, mic: true, camera: false,
                          }))}
                          className="btn-secondary text-xs flex-1"
                        >
                          <Mic size={13} /> Allow mic
                        </button>
                        <button
                          onClick={() => run(`mute-${s.user_id}`, () => onlineClassAPI.muteStudent(sessionId, s.user_id))}
                          className="btn-secondary text-xs flex-1"
                        >
                          <MicOff size={13} /> Mute
                        </button>
                        <button
                          onClick={() => run(`rm-${s.user_id}`, () => onlineClassAPI.removeStudent(sessionId, s.user_id))}
                          className="btn-secondary text-xs text-rose-400"
                          title="Remove from class"
                        >
                          <UserMinus size={13} />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </motion.aside>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Tool({ icon: Icon, label, onClick, active, danger, busy }) {
  const tone = danger ? 'bg-rose-500/90 text-white'
    : active ? 'bg-brand-blue text-white'
      : 'glass text-ink';
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className={`flex flex-col items-center gap-1 px-3.5 py-2.5 rounded-2xl min-w-[4.5rem] ${tone}
                  transition-transform hover:-translate-y-0.5 disabled:opacity-60`}
    >
      {busy ? <Loader2 size={20} className="animate-spin" /> : <Icon size={20} />}
      <span className="text-[11px] font-semibold whitespace-nowrap">{label}</span>
    </button>
  );
}
