import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Room, RoomEvent, Track, VideoPresets, AudioPresets, DisconnectReason, createLocalVideoTrack,
} from 'livekit-client';
import { liveClassAdminAPI, onlineClassAPI } from '../../services/api';
import { apiError } from '../../services/apiError';

// ─── Live classroom connection ────────────────────────────────────────────────
//
// Wraps the media client so pages deal in classroom language (teacher video,
// the board, page 42, raised hands) rather than WebRTC.
//
// Three behaviours matter more than the rest, because they are what a class on
// a fluctuating connection actually experiences:
//
//   * A dropped connection is not the end of the lesson. The client reconnects
//     on its own, and classroom state is re-read afterwards so a teacher who
//     turned a page mid-drop is not lost.
//   * Teaching state travels as data, not pixels: "page 62", "this stroke".
//     A student's browser renders the page itself, which keeps a lesson legible
//     on a connection that could never carry video of a document.
//   * Everything realtime has a slow polling fallback, so a missed message
//     costs latency, never correctness.

const STATE_POLL_MS = 15000;
const SNAPSHOT_MS = 6000;
const LIVE_STROKE_MS = 60;

// ─── Local devices ────────────────────────────────────────────────────────────
//
// A camera or microphone that will not start must never cost anyone the
// classroom. A teacher on a desktop with no webcam, or one who dismissed the
// permission prompt, can still teach the whole lesson: the whiteboard, the
// books and screen sharing need no capture device at all. So device failures
// are reported, not thrown — and specifically enough to act on, since "plug in
// a microphone" and "allow the browser" are different problems.

function deviceReason(err) {
  switch (err?.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return 'blocked in your browser';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'not connected to this computer';
    case 'NotReadableError':
    case 'TrackStartError':
      return 'already being used by another app';
    default:
      return 'unavailable';
  }
}

async function tryDevice(enable) {
  try {
    await enable();
    return { ok: true };
  } catch (err) {
    return { ok: false, reason: deviceReason(err) };
  }
}

const STILL_WORKS = 'The whiteboard, books and screen sharing still work.';

// ─── Screen share with sound ──────────────────────────────────────────────────
//
// Voice processing is for voices. Left on, echo cancellation and noise
// suppression treat a video's music and narration as noise to remove, and
// automatic gain pumps the volume. Speech settings (low bitrate, DTX, which
// goes silent in quiet passages) are replaced with a music preset for the same
// reason; they apply to the shared sound only, never to the teacher's mic.
const SCREEN_CAPTURE = {
  audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  systemAudio: 'include',
  // The teacher keeps hearing the video they are sharing.
  suppressLocalAudioPlayback: false,
  // "Share this tab instead" keeps the sound following the tab being shown.
  surfaceSwitching: 'include',
};
const SCREEN_PUBLISH = { audioPreset: AudioPresets.musicStereo, dtx: false, red: false };
const AUDIO_REQUEST_REJECTED = ['TypeError', 'NotSupportedError', 'OverconstrainedError'];

function deviceNoticeFor(mic, camera) {
  if (mic.ok && camera.ok) return '';
  if (!mic.ok && !camera.ok) {
    return `Your microphone is ${mic.reason} and your camera is ${camera.reason}. ${STILL_WORKS}`;
  }
  if (!mic.ok) {
    return `Your microphone is ${mic.reason}, so students will not hear you. ${STILL_WORKS}`;
  }
  return `Your camera is ${camera.reason}, so students will not see you. ${STILL_WORKS}`;
}

export default function useClassroom({ sessionId, role }) {
  const [status, setStatus] = useState('idle'); // idle|connecting|live|reconnecting|ended|error
  const [error, setError] = useState('');
  const [session, setSession] = useState(null);
  const [hands, setHands] = useState([]);
  const [grant, setGrant] = useState({ mic: false, camera: false });
  const [participants, setParticipants] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [speakers, setSpeakers] = useState([]);
  const [micOn, setMicOn] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [screenSharing, setScreenSharing] = useState(false);
  const [docCameraOn, setDocCameraOn] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [deviceNotice, setDeviceNotice] = useState('');
  const [lowBandwidth, setLowBandwidth] = useState(false);
  // Stays false until the server says recording is both switched on by the
  // school and actually configured, so no dead Record button is ever shown.
  const [recordingAvailable, setRecordingAvailable] = useState(false);

  const [remoteVideo, setRemoteVideo] = useState(null);   // teacher camera
  const [remoteScreen, setRemoteScreen] = useState(null); // teacher screen share
  const [localVideo, setLocalVideo] = useState(null);
  const [resourceToken, setResourceToken] = useState('');

  // Teaching surfaces
  const [stage, setStage] = useState({ mode: 'camera', state: {} });
  const [board, setBoard] = useState({ pageIndex: 0, pages: { 0: [] } });
  const [annotations, setAnnotations] = useState({});   // "docId:page" → strokes
  const [liveStrokes, setLiveStrokes] = useState([]);   // in-progress remote stroke
  const [videoSync, setVideoSync] = useState(null);     // teacher's live video position

  const roomRef = useRef(null);
  const stoppingShareRef = useRef(false);
  const pollRef = useRef(null);
  const snapshotRef = useRef(null);
  const liveSendRef = useRef(0);
  const endedRef = useRef(false);
  const teacherIdRef = useRef(null);
  const boardRef = useRef(board);
  const annotationsRef = useRef(annotations);
  const stageRef = useRef(stage);

  boardRef.current = board;
  annotationsRef.current = annotations;
  stageRef.current = stage;

  const isTeacher = role === 'teacher';
  // An administrator watching a class joins through the audited observe
  // endpoint, never through the student join path.
  const isObserver = role === 'observer';

  // ── Classroom state (poll + after reconnect) ──────────────────────────────
  const refreshState = useCallback(async () => {
    try {
      const { data } = await onlineClassAPI.state(sessionId);
      setSession(data.session);
      setHands(data.hands || []);
      if (data.grant) setGrant(data.grant);
      if (data.attendance) setAttendance(data.attendance);
      setRecordingAvailable(!!data.recording_available);
      if (data.session?.stage_mode) {
        setStage({ mode: data.session.stage_mode, state: data.session.stage_state || {} });
      }
      if (data.session?.status === 'ended') setStatus('ended');
    } catch {
      // A failed refresh is not worth interrupting a lesson for.
    }
  }, [sessionId]);

  // ── Publishing (teacher → class) ──────────────────────────────────────────
  const publish = useCallback((message, { reliable = true } = {}) => {
    const room = roomRef.current;
    if (!room || room.state !== 'connected') return;
    try {
      room.localParticipant.publishData(
        new TextEncoder().encode(JSON.stringify(message)),
        { reliable },
      );
    } catch {
      // Dropping a realtime frame is survivable; state is re-read on poll.
    }
  }, []);

  // ── Incoming messages ─────────────────────────────────────────────────────
  const handleMessage = useCallback((payload) => {
    let message;
    try {
      message = JSON.parse(new TextDecoder().decode(payload));
    } catch {
      return;
    }

    switch (message.t) {
      case 'stage':
        setStage({ mode: message.mode, state: message.state || {} });
        break;

      case 'stroke':
        setLiveStrokes([]);
        applyStroke(message, setBoard, setAnnotations);
        break;

      case 'stroke_live':
        setLiveStrokes(message.stroke ? [message.stroke] : []);
        break;

      case 'clear':
        setLiveStrokes([]);
        if (message.surface === 'book') {
          setAnnotations((prev) => ({ ...prev, [message.key]: [] }));
        } else {
          setBoard((prev) => ({ ...prev, pages: { ...prev.pages, [message.page]: [] } }));
        }
        break;

      case 'undo':
        if (message.surface === 'book') {
          setAnnotations((prev) => ({
            ...prev, [message.key]: (prev[message.key] || []).slice(0, -1),
          }));
        } else {
          setBoard((prev) => ({
            ...prev,
            pages: { ...prev.pages, [message.page]: (prev.pages[message.page] || []).slice(0, -1) },
          }));
        }
        break;

      case 'board_page':
        setBoard((prev) => ({
          ...prev,
          pageIndex: message.page,
          pages: { ...prev.pages, [message.page]: prev.pages[message.page] || [] },
        }));
        break;

      case 'video_sync':
        // Stamped on arrival rather than trusting the teacher's clock.
        setVideoSync({
          videoId: message.video_id,
          playing: !!message.playing,
          position: Number(message.position) || 0,
          at: Date.now(),
        });
        break;

      case 'hands':
        setHands(message.hands || []);
        break;

      case 'grant':
        setGrant((prev) => (
          message.user_id === roomRef.current?.localParticipant?.identity
            ? { mic: !!message.mic, camera: !!message.camera }
            : prev
        ));
        break;

      case 'mute_all':
        if (!isTeacher) { setGrant({ mic: false, camera: false }); setMicOn(false); }
        break;

      case 'ended':
        endedRef.current = true;
        setStatus('ended');
        break;

      default:
        refreshState();
    }
  }, [isTeacher, refreshState]);

  // ── Catch-up for a late joiner or a reconnect ─────────────────────────────
  const loadSnapshot = useCallback(async () => {
    try {
      const { data } = await onlineClassAPI.boardSnapshot(sessionId);
      if (data.stage_mode) setStage({ mode: data.stage_mode, state: data.stage_state || {} });
      const snapshot = data.snapshot;
      if (!snapshot) return;
      if (snapshot.board) setBoard(snapshot.board);
      if (snapshot.annotations) setAnnotations(snapshot.annotations);
    } catch {
      // Nothing saved yet — a blank board is the correct state.
    }
  }, [sessionId]);

  // ── Connect ───────────────────────────────────────────────────────────────
  const connect = useCallback(async () => {
    setStatus('connecting');
    setError('');
    try {
      const { data } = isObserver
        ? await liveClassAdminAPI.observe(sessionId)
        : await onlineClassAPI.join(sessionId);
      setSession(data.session);
      teacherIdRef.current = data.session.teacher_id;
      setGrant({ mic: !!data.can_speak, camera: !!data.can_camera });
      if (data.session.low_bandwidth_default) setLowBandwidth(true);

      const room = new Room({
        adaptiveStream: true,   // drop resolution before dropping the lesson
        dynacast: true,         // stop sending layers nobody is watching
        publishDefaults: {
          simulcast: true,
          videoSimulcastLayers: [VideoPresets.h180, VideoPresets.h360],
          audioPreset: { maxBitrate: 32000 },
          dtx: true,
          red: true,
        },
        videoCaptureDefaults: { resolution: VideoPresets.h720.resolution },
      });
      roomRef.current = room;

      room
        .on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
          if (track.kind === Track.Kind.Audio) { attachAudio(track); }
          if (track.kind === Track.Kind.Video && participant.identity === teacherIdRef.current) {
            if (publication.source === Track.Source.ScreenShare) setRemoteScreen(track);
            else setRemoteVideo(track);
          }
          syncParticipants(room, setParticipants);
        })
        .on(RoomEvent.TrackUnsubscribed, (track, publication, participant) => {
          if (track.kind === Track.Kind.Audio) detachAudio(track);
          if (track.kind === Track.Kind.Video && participant.identity === teacherIdRef.current) {
            if (publication.source === Track.Source.ScreenShare) setRemoteScreen(null);
            else setRemoteVideo(null);
          }
          syncParticipants(room, setParticipants);
        })
        .on(RoomEvent.LocalTrackPublished, (pub) => {
          if (pub.kind === Track.Kind.Video && pub.source !== Track.Source.ScreenShare) {
            setLocalVideo(pub.videoTrack || null);
          }
        })
        .on(RoomEvent.LocalTrackUnpublished, (pub) => {
          if (pub.kind === Track.Kind.Video && pub.source !== Track.Source.ScreenShare) {
            setLocalVideo(null);
          }
          // The browser's own "Stop sharing" bar ends the share without going
          // through the Share Screen button. Without this the class would sit
          // on "Starting the shared screen…" until the teacher noticed.
          if (pub.source === Track.Source.ScreenShare) {
            setScreenSharing(false);
            if (!stoppingShareRef.current) {
              onlineClassAPI.share(sessionId, { active: false, source: 'screen' }).catch(() => {});
            }
          }
        })
        .on(RoomEvent.ParticipantConnected, () => syncParticipants(room, setParticipants))
        .on(RoomEvent.ParticipantDisconnected, () => syncParticipants(room, setParticipants))
        .on(RoomEvent.ActiveSpeakersChanged, (list) => setSpeakers(list.map((p) => p.identity)))
        .on(RoomEvent.DataReceived, handleMessage)
        .on(RoomEvent.Reconnecting, () => setStatus('reconnecting'))
        .on(RoomEvent.Reconnected, () => {
          setStatus('live');
          refreshState();
          if (!isTeacher) loadSnapshot();
        })
        .on(RoomEvent.AudioPlaybackStatusChanged, () => setAudioBlocked(!room.canPlaybackAudio))
        .on(RoomEvent.Disconnected, (reason) => {
          if (endedRef.current || reason === DisconnectReason.ROOM_DELETED) setStatus('ended');
          else setStatus('disconnected');
        });

      await room.connect(data.url, data.token);
      setStatus('live');

      // Browsers block audio until a user gesture; connect() runs inside one.
      try { await room.startAudio(); } catch { setAudioBlocked(true); }

      if (isTeacher) {
        // Each device is enabled on its own, and a failure is a notice rather
        // than an exception — otherwise a laptop with no webcam throws here and
        // the catch below ends a class the teacher had already joined.
        const mic = await tryDevice(() => room.localParticipant.setMicrophoneEnabled(true));
        const camera = await tryDevice(() => room.localParticipant.setCameraEnabled(true));
        setMicOn(mic.ok);
        setCameraOn(camera.ok);
        setDeviceNotice(deviceNoticeFor(mic, camera));
      }

      syncParticipants(room, setParticipants);
      refreshState();
      loadSnapshot();

      // Key for the browser's own fetches (textbook pages, images).
      try {
        const { data: rt } = await onlineClassAPI.resourceToken(sessionId);
        setResourceToken(rt.token);
      } catch { /* books simply will not open until the next refresh */ }
    } catch (err) {
      setError(apiError(err, 'Could not connect to the class.'));
      setStatus('error');
    }
  }, [sessionId, isTeacher, handleMessage, refreshState, loadSnapshot]);

  // ── Leave ─────────────────────────────────────────────────────────────────
  const disconnect = useCallback(async () => {
    try { await roomRef.current?.disconnect(); } catch { /* already gone */ }
    roomRef.current = null;
    try { await onlineClassAPI.leave(sessionId); } catch { /* webhook covers it */ }
  }, [sessionId]);

  // ── Local devices ─────────────────────────────────────────────────────────
  // Turning a device on can fail the same way it can at join time — a student
  // granted the mic may have none. Say so; never leave the button lying.
  const toggleMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    const next = !micOn;
    const result = await tryDevice(() => room.localParticipant.setMicrophoneEnabled(next));
    setMicOn(next && result.ok);
    setDeviceNotice(result.ok ? '' : `Your microphone is ${result.reason}.`);
  }, [micOn]);

  const toggleCamera = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    const next = !cameraOn;
    const result = await tryDevice(() => room.localParticipant.setCameraEnabled(next));
    setCameraOn(next && result.ok);
    setDeviceNotice(result.ok ? '' : `Your camera is ${result.reason}.`);
  }, [cameraOn]);

  const dismissDeviceNotice = useCallback(() => setDeviceNotice(''), []);

  // A teacher with no camera is still in the lesson. Without this, a class
  // watches "Waiting for your teacher" while the teacher is talking to them.
  const teacherPresent = useMemo(
    () => participants.some((p) => p.identity === session?.teacher_id),
    [participants, session?.teacher_id],
  );

  const enableAudio = useCallback(async () => {
    try { await roomRef.current?.startAudio(); setAudioBlocked(false); } catch { /* banner stays */ }
  }, []);

  // ── Screen share (spec §9) ────────────────────────────────────────────────
  const toggleScreenShare = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return { ok: false, reason: 'not-connected' };

    // Stopping is never allowed to fail: the button that started the share is
    // the only way back, so it must work even if the browser has already torn
    // the capture down underneath us.
    if (screenSharing) {
      stoppingShareRef.current = true;
      try {
        await room.localParticipant.setScreenShareEnabled(false);
      } catch { /* the capture had already ended */ } finally {
        stoppingShareRef.current = false;
      }
      setScreenSharing(false);
      try {
        await onlineClassAPI.share(sessionId, { active: false, source: 'screen' });
      } catch { /* the next state poll corrects the stage */ }
      return { ok: true };
    }

    if (!navigator.mediaDevices?.getDisplayMedia) {
      // No mobile browser can capture the screen — Android and iOS reserve that
      // for installed apps. The caller offers what does work from a phone
      // (a shared video, the book, the document camera) instead.
      return { ok: false, reason: 'unsupported' };
    }

    try {
      try {
        // Sound is asked for, not assumed: Chrome and Edge offer "Also share
        // tab audio" (and system audio for a whole screen on Windows), which is
        // how a YouTube video shared in a lesson is heard as well as seen.
        await room.localParticipant.setScreenShareEnabled(true, SCREEN_CAPTURE, SCREEN_PUBLISH);
      } catch (err) {
        // A browser that rejects the audio request itself still gets to share
        // the picture. These errors are raised before the picker opens, so the
        // retry never makes the teacher choose a screen twice.
        if (!AUDIO_REQUEST_REJECTED.includes(err?.name)) throw err;
        await room.localParticipant.setScreenShareEnabled(true, { audio: false });
      }
      setScreenSharing(true);
      const withSound = !!room.localParticipant
        .getTrackPublication(Track.Source.ScreenShareAudio)?.track;
      await onlineClassAPI.share(sessionId, { active: true, source: 'screen' });
      return { ok: true, withSound };
    } catch (err) {
      return { ok: false, reason: err?.name === 'NotAllowedError' ? 'cancelled' : 'failed' };
    }
  }, [screenSharing, sessionId]);

  // ── Shared video ──────────────────────────────────────────────────────────
  //
  // Every device plays the video itself; the teacher's player is the clock.
  // Play, pause and seek go through the server so late joiners start in the
  // right place, and a heartbeat over the data channel keeps everyone within a
  // few seconds between those moments.
  const shareVideo = useCallback(async (url) => {
    const { data } = await onlineClassAPI.video(sessionId, { url, playing: false });
    setStage({ mode: data.mode, state: data.state || {} });
    return data;
  }, [sessionId]);

  const reportVideo = useCallback(async ({ playing, position }) => {
    try {
      const { data } = await onlineClassAPI.video(sessionId, { playing, position });
      // Only the video's own state is taken from the reply. A pause sent as the
      // teacher switches to the board can finish after that switch, and must
      // not put the video back on the teacher's screen.
      setStage((prev) => ({
        ...prev,
        state: { ...prev.state, video: data.state?.video || prev.state.video },
      }));
    } catch {
      // The heartbeat keeps the class in step; late joiners catch up on poll.
    }
  }, [sessionId]);

  const sendVideoProgress = useCallback(({ videoId, playing, position }) => {
    publish({ t: 'video_sync', video_id: videoId, playing, position }, { reliable: false });
  }, [publish]);

  // ── Document camera (spec §10) ────────────────────────────────────────────
  //
  // The rear camera pointed at a physical textbook, optimised for detail over
  // motion: a still page at a readable resolution is worth far more than a
  // smooth one that cannot be read. Replaces the front camera rather than
  // adding a second stream, because two video tracks would double what every
  // student has to download.
  const toggleDocumentCamera = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return { ok: false };

    // Turning it off must always succeed. The rear camera is released first,
    // and only then is the front one asked for: if that fails (a phone that
    // will not hand the camera back, a laptop with none), the class still
    // leaves the document-camera view. Otherwise a teacher who pressed the
    // wrong button would be stuck showing their desk for the rest of the
    // lesson with no way back.
    if (docCameraOn) {
      try { await room.localParticipant.setCameraEnabled(false); } catch { /* already gone */ }
      setDocCameraOn(false);
      let restored = true;
      try {
        await room.localParticipant.setCameraEnabled(true);
      } catch {
        restored = false;
      }
      setCameraOn(restored);
      try {
        await onlineClassAPI.share(sessionId, { active: false, source: 'document_camera' });
      } catch { /* the next state poll corrects the stage */ }
      return { ok: true, cameraRestored: restored };
    }

    try {
      await room.localParticipant.setCameraEnabled(false);
      const track = await createLocalVideoTrack({
        facingMode: 'environment',
        resolution: VideoPresets.h1080.resolution,
      });
      await room.localParticipant.publishTrack(track, {
        source: Track.Source.Camera,
        simulcast: false,
        degradationPreference: 'maintain-resolution',
        videoEncoding: { maxBitrate: 1_200_000, maxFramerate: 12 },
      });
      setLocalVideo(track);
      setDocCameraOn(true);
      setCameraOn(true);
      await onlineClassAPI.share(sessionId, { active: true, source: 'document_camera' });
      return { ok: true };
    } catch (err) {
      return { ok: false, reason: err?.message };
    }
  }, [docCameraOn, sessionId]);

  // ── Low-bandwidth mode (spec §23) ─────────────────────────────────────────
  //
  // Priority when the line is poor: the teacher's voice, then what is being
  // taught (board and book, which are data, not video), then video. Turning
  // video off entirely keeps a lesson usable where it would otherwise stall.
  const applyLowBandwidth = useCallback((enabled) => {
    const room = roomRef.current;
    setLowBandwidth(enabled);
    if (!room) return;
    const remote = room.remoteParticipants || room.participants || new Map();
    remote.forEach((participant) => {
      participant.trackPublications?.forEach?.((publication) => {
        if (publication.kind === Track.Kind.Video) publication.setSubscribed(!enabled);
      });
    });
  }, []);

  // ── Teaching surfaces ─────────────────────────────────────────────────────
  const surfaceKey = useMemo(() => {
    if (stage.mode === 'book') {
      const bookState = stage.state?.book || {};
      return `${bookState.document_id || 'doc'}:${bookState.page || 1}`;
    }
    return null;
  }, [stage]);

  const addStroke = useCallback((stroke) => {
    if (stage.mode === 'book' && surfaceKey) {
      setAnnotations((prev) => ({ ...prev, [surfaceKey]: [...(prev[surfaceKey] || []), stroke] }));
      publish({ t: 'stroke', surface: 'book', key: surfaceKey, stroke });
    } else {
      const page = boardRef.current.pageIndex;
      setBoard((prev) => ({
        ...prev, pages: { ...prev.pages, [page]: [...(prev.pages[page] || []), stroke] },
      }));
      publish({ t: 'stroke', surface: 'board', page, stroke });
    }
    setLiveStrokes([]);
  }, [stage.mode, surfaceKey, publish]);

  const sendStrokeProgress = useCallback((stroke) => {
    const now = Date.now();
    if (now - liveSendRef.current < LIVE_STROKE_MS) return;
    liveSendRef.current = now;
    publish({ t: 'stroke_live', stroke }, { reliable: false });
  }, [publish]);

  const clearSurface = useCallback(() => {
    if (stage.mode === 'book' && surfaceKey) {
      setAnnotations((prev) => ({ ...prev, [surfaceKey]: [] }));
      publish({ t: 'clear', surface: 'book', key: surfaceKey });
    } else {
      const page = boardRef.current.pageIndex;
      setBoard((prev) => ({ ...prev, pages: { ...prev.pages, [page]: [] } }));
      publish({ t: 'clear', surface: 'board', page });
    }
  }, [stage.mode, surfaceKey, publish]);

  const undoStroke = useCallback(() => {
    if (stage.mode === 'book' && surfaceKey) {
      setAnnotations((prev) => ({ ...prev, [surfaceKey]: (prev[surfaceKey] || []).slice(0, -1) }));
      publish({ t: 'undo', surface: 'book', key: surfaceKey });
    } else {
      const page = boardRef.current.pageIndex;
      setBoard((prev) => ({
        ...prev, pages: { ...prev.pages, [page]: (prev.pages[page] || []).slice(0, -1) },
      }));
      publish({ t: 'undo', surface: 'board', page });
    }
  }, [stage.mode, surfaceKey, publish]);

  const setBoardPage = useCallback((page) => {
    setBoard((prev) => ({
      ...prev, pageIndex: page, pages: { ...prev.pages, [page]: prev.pages[page] || [] },
    }));
    publish({ t: 'board_page', page });
  }, [publish]);

  const addBoardPage = useCallback(() => {
    const next = Object.keys(boardRef.current.pages).length;
    setBoardPage(next);
  }, [setBoardPage]);

  // ── Books (spec §7) ───────────────────────────────────────────────────────
  const presentDocument = useCallback(async (documentId, page = 1) => {
    const { data } = await onlineClassAPI.present(sessionId, { document_id: documentId, page });
    if (data.state === 'ready') await refreshState();
    return data;
  }, [sessionId, refreshState]);

  const presentPage = useCallback(async (page) => {
    const bookState = stageRef.current.state?.book || {};
    if (!bookState.document_id) return;
    setStage((prev) => ({
      ...prev,
      state: { ...prev.state, book: { ...(prev.state.book || {}), page } },
    }));
    try {
      await onlineClassAPI.presentPage(sessionId, {
        document_id: bookState.document_id, page,
      });
    } catch {
      refreshState();
    }
  }, [sessionId, refreshState]);

  // ── Stage switching (spec §8) ─────────────────────────────────────────────
  const changeStage = useCallback(async (mode, state) => {
    setStage((prev) => ({
      mode,
      state: state ? { ...prev.state, [mode]: { ...(prev.state[mode] || {}), ...state } } : prev.state,
    }));
    try {
      const { data } = await onlineClassAPI.setStage(sessionId, { mode, state: state || null });
      setStage({ mode: data.mode, state: data.state || {} });
    } catch {
      refreshState();
    }
  }, [sessionId, refreshState]);

  // ── Board snapshot for late joiners ───────────────────────────────────────
  useEffect(() => {
    if (!isTeacher || status !== 'live') return undefined;
    snapshotRef.current = setInterval(() => {
      onlineClassAPI.saveBoardSnapshot(sessionId, {
        snapshot: { board: boardRef.current, annotations: annotationsRef.current },
      }).catch(() => { /* the next tick will try again */ });
    }, SNAPSHOT_MS);
    return () => clearInterval(snapshotRef.current);
  }, [isTeacher, status, sessionId]);

  // A student whose microphone was revoked must stop publishing immediately.
  useEffect(() => {
    if (isTeacher || !roomRef.current) return;
    if (!grant.mic && micOn) {
      roomRef.current.localParticipant.setMicrophoneEnabled(false);
      setMicOn(false);
    }
  }, [grant.mic, micOn, isTeacher]);

  // ── Polling fallback + cleanup ────────────────────────────────────────────
  useEffect(() => {
    if (status !== 'live' && status !== 'reconnecting') return undefined;
    pollRef.current = setInterval(refreshState, STATE_POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [status, refreshState]);

  useEffect(() => () => { roomRef.current?.disconnect(); }, []);

  const boardStrokes = board.pages[board.pageIndex] || [];
  const bookAnnotations = surfaceKey ? (annotations[surfaceKey] || []) : [];

  return {
    status, error, session, hands, grant, participants, attendance, speakers,
    micOn, cameraOn, audioBlocked, deviceNotice, dismissDeviceNotice, teacherPresent,
    screenSharing, docCameraOn, lowBandwidth,
    recordingAvailable,
    remoteVideo, remoteScreen, localVideo, resourceToken,
    stage, board, boardStrokes, bookAnnotations, liveStrokes, videoSync,
    boardPageCount: Object.keys(board.pages).length,
    room: roomRef,
    connect, disconnect, toggleMic, toggleCamera, enableAudio, refreshState,
    toggleScreenShare, toggleDocumentCamera, applyLowBandwidth,
    shareVideo, reportVideo, sendVideoProgress,
    addStroke, sendStrokeProgress, clearSurface, undoStroke,
    setBoardPage, addBoardPage, changeStage, loadSnapshot,
    presentDocument, presentPage,
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function applyStroke(message, setBoard, setAnnotations) {
  if (message.surface === 'book') {
    setAnnotations((prev) => ({
      ...prev, [message.key]: [...(prev[message.key] || []), message.stroke],
    }));
    return;
  }
  setBoard((prev) => ({
    ...prev,
    pages: { ...prev.pages, [message.page]: [...(prev.pages[message.page] || []), message.stroke] },
  }));
}

// livekit-client v2 exposes `remoteParticipants`; older builds used
// `participants`. Reading both keeps this working across a client upgrade.
function syncParticipants(room, setParticipants) {
  const remote = room.remoteParticipants || room.participants || new Map();
  setParticipants(Array.from(remote.values()).map((p) => ({
    identity: p.identity,
    name: p.name || p.identity,
    isSpeaking: p.isSpeaking,
    micEnabled: p.isMicrophoneEnabled,
    cameraEnabled: p.isCameraEnabled,
  })));
}

// Audio is attached outside React: a hidden element per track, so a re-render
// can never silence a classroom mid-sentence.
function attachAudio(track) {
  const el = track.attach();
  el.style.display = 'none';
  el.setAttribute('data-lss-audio', '1');
  document.body.appendChild(el);
}

function detachAudio(track) {
  track.detach().forEach((el) => el.remove());
}
