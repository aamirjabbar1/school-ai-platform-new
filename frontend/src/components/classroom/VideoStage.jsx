import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Loader2, Pause, Play, RotateCcw, Undo2, Volume2, VideoOff, X,
} from 'lucide-react';

// ─── Shared video ─────────────────────────────────────────────────────────────
//
// Each device plays the YouTube video itself — picture and sound at the
// quality its own connection allows — and only "playing at 1:32" crosses the
// classroom connection. That is what lets a teacher on a phone show a video at
// all (no mobile browser can share its screen), and it is lighter for everyone
// than re-streaming a video through screen share.
//
// The teacher's player is the clock. Students' players follow it: they start
// where the class is, pause when the teacher pauses, and are pulled back into
// step if they drift. Small differences are tolerated on purpose — seeking a
// buffering video on a slow line would stall it for good.
//
// Two rules decide almost everything here, and both come from phones:
//
//   * The frame is built by hand, not by the YouTube API's own div-to-iframe
//     helper, so it can carry `allow="autoplay; encrypted-media"`. A
//     cross-origin frame without that permission is refused permission to
//     start playing at all, which is a black rectangle and no sound on exactly
//     the devices this feature exists for.
//   * A picture beats silence. When a browser refuses to start a video with
//     sound — every mobile browser does, until the page has been touched —
//     the video is started muted and the class is offered one tap for sound,
//     rather than being left watching nothing.

const YT_STATE = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 };

const HEARTBEAT_MS = 3000;       // teacher → class position updates
const CHECK_MS = 1000;           // how often a student's player is checked
const CLOCK_MS = 500;            // how often the teacher's own readout ticks
const PLAYING_DRIFT_S = 4;       // tolerated gap while playing
const PAUSED_DRIFT_S = 1.5;      // tolerated gap while paused
const SEEK_SETTLE_MS = 5000;     // let a seek finish buffering before judging it
const MUTED_AFTER_MS = 1600;     // sound refused → play it silently instead
const BLOCKED_AFTER_MS = 4500;   // even silent play refused → the class must tap
const IGNORE_SYNC_MS = 1500;     // a heartbeat sent before a pause must not undo it
const READY_TIMEOUT_MS = 9000;   // a frame that never loads must say so

let apiPromise = null;

function loadYouTubeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve(window.YT);
    };
    const script = document.createElement('script');
    script.src = 'https://www.youtube.com/iframe_api';
    script.async = true;
    script.onerror = () => {
      script.remove();
      apiPromise = null; // a later attempt (e.g. after reconnecting) may succeed
      reject(new Error('youtube-unavailable'));
    };
    document.head.appendChild(script);
  });
  return apiPromise;
}

// The frame the class watches. Built here rather than by YT.Player's div
// replacement so that `allow` and `playsinline` are ours to set: without
// `allow="autoplay"` a phone refuses to let this frame start playing even
// silently, and without `playsinline` an iPhone rips the video out of the
// lesson into its own fullscreen player.
function buildFrame(videoId, { editable, start }) {
  const params = new URLSearchParams({
    enablejsapi: '1',
    playsinline: '1',
    rel: '0',
    modestbranding: '1',
    iv_load_policy: '3',
    // Students follow the teacher; their controls would only fight it.
    controls: editable ? '1' : '0',
    disablekb: editable ? '0' : '1',
    fs: editable ? '1' : '0',
    start: String(Math.max(0, Math.floor(start || 0))),
    origin: window.location.origin,
  });

  const frame = document.createElement('iframe');
  // The API addresses an existing frame by id, so it needs one of its own.
  frame.id = `class-video-${Math.random().toString(36).slice(2, 10)}`;
  frame.src = `https://www.youtube-nocookie.com/embed/${videoId}?${params.toString()}`;
  frame.title = 'Class video';
  frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen; accelerometer; gyroscope';
  frame.allowFullscreen = true;
  frame.setAttribute('playsinline', '');
  frame.setAttribute('frameborder', '0');
  frame.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;border:0;background:#000';
  return frame;
}

function expectedPosition(target) {
  if (!target) return 0;
  return target.playing ? target.position + (Date.now() - target.at) / 1000 : target.position;
}

function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return `${minutes}:${String(rest).padStart(2, '0')}`;
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

export default function VideoStage({
  video, editable = false, sync, lowBandwidth = false, onReport, onProgress, onStop,
}) {
  const hostRef = useRef(null);
  const playerRef = useRef(null);
  const loadedIdRef = useRef(null);
  const targetRef = useRef(null);     // where the class should be
  const reportedRef = useRef(null);   // teacher: what the class was last told
  const lastSeekRef = useRef(0);
  const cuedAtRef = useRef(null);
  const wantPlaySinceRef = useRef(0);
  const mutedToStartRef = useRef(false);
  const ignoreSyncUntilRef = useRef(0);
  const callbacksRef = useRef({ onReport, onProgress });
  callbacksRef.current = { onReport, onProgress };

  const [status, setStatus] = useState('loading'); // loading|ready|slow|unavailable|no-embed|error
  const [blocked, setBlocked] = useState(false);
  const [tapVideo, setTapVideo] = useState(false);
  const tapVideoRef = useRef(false);
  tapVideoRef.current = tapVideo;
  const [soundOff, setSoundOff] = useState(false);
  // What the teacher's own controls show. The teacher drives the class from
  // these buttons, not from the small controls inside the video: on a phone
  // those are hard to hit, and on some browsers they are covered entirely.
  const [teacherState, setTeacherState] = useState({ playing: false, position: 0, duration: 0 });
  // With data saver on, a student chooses to spend data on a video.
  const [started, setStarted] = useState(editable || !lowBandwidth);

  const videoId = video?.video_id;
  const hasVideo = !!videoId;

  // ── Where the class should be, from the server ────────────────────────────
  // Declared before the effects that read it, so they see the new target.
  useEffect(() => {
    if (!videoId) return;
    const elapsed = video.playing
      ? Math.max(0, Date.now() / 1000 - (video.updated_at || Date.now() / 1000))
      : 0;
    targetRef.current = {
      videoId,
      playing: !!video.playing,
      position: (video.position || 0) + elapsed,
      at: Date.now(),
    };
    ignoreSyncUntilRef.current = Date.now() + IGNORE_SYNC_MS;
  }, [videoId, video?.playing, video?.position, video?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── …and from the teacher's heartbeat, between those moments ──────────────
  useEffect(() => {
    if (editable || !sync || Date.now() < ignoreSyncUntilRef.current) return;
    if (sync.videoId !== targetRef.current?.videoId) return;
    targetRef.current = {
      videoId: sync.videoId, playing: sync.playing, position: sync.position, at: sync.at,
    };
  }, [sync, editable]);

  // ── Teacher: tell the class what just happened ────────────────────────────
  const report = (playing, position) => {
    reportedRef.current = { playing, position, at: Date.now() };
    callbacksRef.current.onReport?.({ playing, position });
  };

  const handleStateChange = (player, state) => {
    if (!editable) {
      if (state === YT_STATE.PLAYING) {
        wantPlaySinceRef.current = 0;
        setBlocked(false);
        setTapVideo(false);
        setSoundOff(!!player.isMuted?.());
      }
      return;
    }
    const position = player.getCurrentTime();
    const last = reportedRef.current;
    if (state === YT_STATE.PLAYING) {
      // Also fires after a seek or a stall, which is when students need the
      // new position.
      if (!last || !last.playing || Math.abs(position - expectedPosition(last)) > 2) {
        report(true, position);
      }
    } else if (state === YT_STATE.PAUSED) {
      if (!last || last.playing || Math.abs(position - last.position) > 1) report(false, position);
    } else if (state === YT_STATE.ENDED) {
      report(false, position);
    }
  };

  // ── Create the player ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!started || !hasVideo) return undefined;
    let cancelled = false;
    let player = null;
    setStatus('loading');
    setBlocked(false);
    setTapVideo(false);
    setSoundOff(false);
    mutedToStartRef.current = false;

    // A frame that never becomes ready used to leave a blank white rectangle
    // and no explanation — the teacher could not tell a slow connection from a
    // broken lesson. Say which it is, and leave a way out.
    const slowTimer = setTimeout(() => {
      if (!cancelled) setStatus((prev) => (prev === 'loading' ? 'slow' : prev));
    }, READY_TIMEOUT_MS);

    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !hostRef.current) return;
        const target = targetRef.current || { videoId, playing: false, position: 0, at: Date.now() };
        const start = expectedPosition(target);
        loadedIdRef.current = target.videoId;
        reportedRef.current = { playing: target.playing, position: start, at: Date.now() };

        const frame = buildFrame(target.videoId, { editable, start });
        hostRef.current.appendChild(frame);

        player = new YT.Player(frame, {
          events: {
            onReady: () => {
              if (cancelled) return;
              playerRef.current = player;
              clearTimeout(slowTimer);
              setStatus('ready');
              const now = targetRef.current;
              if (now?.playing) {
                player.seekTo(expectedPosition(now), true);
                wantPlaySinceRef.current = Date.now();
                player.playVideo();
              }
            },
            onStateChange: (event) => !cancelled && handleStateChange(player, event.data),
            onError: (event) => {
              if (cancelled) return;
              clearTimeout(slowTimer);
              // 101/150: the owner does not allow playback on other sites.
              setStatus(event.data === 101 || event.data === 150 ? 'no-embed' : 'error');
            },
          },
        });
      })
      .catch(() => { if (!cancelled) setStatus('unavailable'); });

    return () => {
      cancelled = true;
      clearTimeout(slowTimer);
      const ready = playerRef.current;
      // Leaving the video (for the board, a book, the end of class) pauses it
      // for everyone, so coming back resumes where the teacher left off.
      if (editable && ready) {
        try {
          const state = ready.getPlayerState();
          if (state === YT_STATE.PLAYING || state === YT_STATE.BUFFERING) {
            callbacksRef.current.onReport?.({ playing: false, position: ready.getCurrentTime() });
          }
        } catch { /* player already gone */ }
      }
      try { player?.destroy?.(); } catch { /* never finished loading */ }
      playerRef.current = null;
      loadedIdRef.current = null;
      // destroy() takes the frame with it; this clears one that never loaded.
      if (hostRef.current) hostRef.current.innerHTML = '';
    };
    // Handlers read refs; recreating the player on every render would restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, hasVideo, editable]);

  // ── A different video on the same stage ───────────────────────────────────
  useEffect(() => {
    const player = playerRef.current;
    if (!player || !videoId || loadedIdRef.current === videoId) return;
    loadedIdRef.current = videoId;
    const target = targetRef.current;
    const start = expectedPosition(target);
    setStatus('ready');
    setBlocked(false);
    setTapVideo(false);
    mutedToStartRef.current = false;
    if (editable) {
      reportedRef.current = { playing: false, position: start, at: Date.now() };
      player.cueVideoById({ videoId, startSeconds: start });
    } else if (target.playing) {
      player.loadVideoById({ videoId, startSeconds: start });
    } else {
      cuedAtRef.current = start;
      player.cueVideoById({ videoId, startSeconds: start });
    }
  }, [videoId, editable]);

  // ── Teacher: heartbeat, and the readout under the video ───────────────────
  useEffect(() => {
    if (!editable || !started) return undefined;

    const readOut = () => {
      const player = playerRef.current;
      if (!player?.getPlayerState) return null;
      let state;
      try { state = player.getPlayerState(); } catch { return null; }
      const position = player.getCurrentTime?.() || 0;
      setTeacherState({
        playing: state === YT_STATE.PLAYING || state === YT_STATE.BUFFERING,
        position,
        duration: player.getDuration?.() || 0,
      });
      return { state, position };
    };

    const ticker = setInterval(readOut, CLOCK_MS);
    const timer = setInterval(() => {
      const player = playerRef.current;
      if (!player || !loadedIdRef.current) return;
      const now = readOut();
      if (!now) return;
      // Nothing has been played yet: the shared start point already stands.
      if (now.state === YT_STATE.UNSTARTED || now.state === YT_STATE.CUED) return;
      const last = reportedRef.current;
      // Seeking while paused raises no event; notice it here.
      if (now.state === YT_STATE.PAUSED && last && !last.playing
          && Math.abs(now.position - last.position) > 1) {
        report(false, now.position);
      }
      callbacksRef.current.onProgress?.({
        videoId: loadedIdRef.current,
        playing: now.state === YT_STATE.PLAYING || now.state === YT_STATE.BUFFERING,
        position: now.position,
      });
    }, HEARTBEAT_MS);

    return () => { clearInterval(timer); clearInterval(ticker); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, started]);

  // ── Student: follow the teacher ───────────────────────────────────────────
  useEffect(() => {
    if (editable || !started) return undefined;
    const timer = setInterval(() => {
      const player = playerRef.current;
      const target = targetRef.current;
      if (!player || !target || loadedIdRef.current !== target.videoId) return;

      const state = player.getPlayerState();
      const position = player.getCurrentTime();
      const want = expectedPosition(target);
      const now = Date.now();
      const settled = now - lastSeekRef.current > SEEK_SETTLE_MS;
      const seek = (to) => { lastSeekRef.current = now; player.seekTo(to, true); };

      if (target.playing) {
        if (state === YT_STATE.BUFFERING) return;
        if (state !== YT_STATE.PLAYING) {
          if (!wantPlaySinceRef.current) wantPlaySinceRef.current = now;
          const waiting = now - wantPlaySinceRef.current;

          // Every mobile browser refuses to start a video with sound until the
          // page has been touched, and a lesson cannot wait for thirty taps.
          // Silent pictures now, sound one tap later, beats a black rectangle.
          if (waiting > MUTED_AFTER_MS && !mutedToStartRef.current) {
            mutedToStartRef.current = true;
            player.mute?.();
            setSoundOff(true);
          }
          // Refused even muted: only a tap on this page will do it now.
          if (waiting > BLOCKED_AFTER_MS && !tapVideoRef.current) setBlocked(true);

          if (settled && Math.abs(position - want) > PLAYING_DRIFT_S) seek(want);
          player.playVideo();
          return;
        }
        if (settled && Math.abs(position - want) > PLAYING_DRIFT_S) seek(want);
        // Some browsers let a video start only silently. A lesson video
        // without its sound is half a lesson, so offer the tap that fixes it.
        setSoundOff(!!player.isMuted?.());
        return;
      }

      wantPlaySinceRef.current = 0;
      setBlocked(false);
      setTapVideo(false);
      if (state === YT_STATE.PLAYING || state === YT_STATE.BUFFERING) player.pauseVideo();
      if (!settled || Math.abs(position - want) <= PAUSED_DRIFT_S) return;
      if (state === YT_STATE.UNSTARTED || state === YT_STATE.CUED) {
        // seekTo would start a cued video playing; re-cue at the right moment.
        if (cuedAtRef.current !== null && Math.abs(cuedAtRef.current - want) <= PAUSED_DRIFT_S) return;
        cuedAtRef.current = want;
        lastSeekRef.current = now;
        player.cueVideoById({ videoId: target.videoId, startSeconds: want });
      } else {
        seek(want);
      }
    }, CHECK_MS);
    return () => clearInterval(timer);
  }, [editable, started]);

  const turnSoundOn = () => {
    const player = playerRef.current;
    if (!player) return;
    mutedToStartRef.current = false;
    player.unMute?.();
    player.setVolume?.(100);
    player.playVideo?.();
    setSoundOff(false);
  };

  const tapToPlay = () => {
    const player = playerRef.current;
    if (!player) return;
    player.unMute?.();
    mutedToStartRef.current = false;
    player.playVideo();
    // If the browser still wants the tap on the video itself, get out of the
    // way and say so.
    setTimeout(() => {
      if (playerRef.current?.getPlayerState?.() !== YT_STATE.PLAYING) {
        setBlocked(false);
        setTapVideo(true);
      }
    }, 1500);
  };

  // ── Teacher's controls (spec §9) ──────────────────────────────────────────
  //
  // Every one of these runs from a real tap on this page, which is what lets a
  // phone start a video at all, and it means the teacher never has to hunt for
  // the small controls inside the video frame.
  const teacherPlay = useCallback(() => {
    const player = playerRef.current;
    if (!player) return;
    player.unMute?.();
    player.playVideo?.();
    report(true, player.getCurrentTime?.() || 0);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const teacherPause = useCallback(() => {
    const player = playerRef.current;
    if (!player) return;
    player.pauseVideo?.();
    report(false, player.getCurrentTime?.() || 0);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const teacherSeekTo = useCallback((to) => {
    const player = playerRef.current;
    if (!player) return;
    const at = Math.max(0, to);
    lastSeekRef.current = Date.now();
    player.seekTo?.(at, true);
    report(reportedRef.current?.playing ?? false, at);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const teacherSeekBy = useCallback((delta) => {
    const player = playerRef.current;
    if (!player) return;
    teacherSeekTo((player.getCurrentTime?.() || 0) + delta);
  }, [teacherSeekTo]);

  const retry = () => {
    // Rebuilding is the only cure for a frame that never answered; flipping
    // `started` off and on again re-runs the effect that creates it.
    setStarted(false);
    setTimeout(() => setStarted(true), 50);
  };

  if (!hasVideo) {
    return <Message>No video is being shared.</Message>;
  }

  if (!started) {
    return (
      <Message>
        <p>Your teacher is showing a video. Data saver is on, and watching uses more data.</p>
        <button onClick={() => setStarted(true)} className="btn-primary mt-3">
          <Play size={16} /> Watch the video
        </button>
      </Message>
    );
  }

  // A fatal problem replaces the video; nothing is playing behind it.
  const problem = {
    unavailable: 'YouTube could not be reached on this connection.',
    'no-embed': editable
      ? 'The owner of this video does not allow it to be played in other websites. Please choose a different video.'
      : 'This video cannot be played here.',
    error: 'This video could not be played.',
  }[status];

  // "Slow" is different: the video frame itself is there and may well be
  // playing — it is the control link to it that has not answered. Covering a
  // working video with an error would be the wrong thing to do, so this is a
  // note above it, and the video keeps the screen.
  const slow = status === 'slow';

  return (
    <div className="w-full h-full flex flex-col gap-2 min-h-0">
      <div className="relative flex-1 min-h-0 rounded-2xl overflow-hidden bg-black">
        {/* Behind the frame: the video's own picture. A frame that has not
            loaded paints blank white, which reads as a broken classroom. This
            way the worst case still shows which video was shared. */}
        <img
          src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 w-full h-full object-contain opacity-60"
          onError={(event) => { event.currentTarget.style.display = 'none'; }}
        />
        <div ref={hostRef} className="absolute inset-0" />

        {status === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-slate-950/70
                          text-white/80 text-sm">
            <Loader2 className="animate-spin" size={20} /> Loading the video…
          </div>
        )}

        {problem && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6
                          bg-slate-950/90 text-white/85 text-sm text-center">
            <VideoOff size={30} />
            <p className="max-w-xs">{problem}</p>
          </div>
        )}

        {slow && (
          <div className="absolute top-2 inset-x-2 flex items-center justify-center gap-2 px-3 py-2
                          rounded-xl bg-amber-500/90 text-slate-950 text-xs font-semibold text-center">
            <span>
              {editable
                ? 'This video is slow to answer. Use the controls in the video itself, or try again.'
                : 'This video is slow to answer — it may not follow your teacher exactly.'}
            </span>
            {editable && (
              <button onClick={retry} className="underline shrink-0">Try again</button>
            )}
          </div>
        )}

        {/* A student looking at a stopped video should know it is not broken. */}
        {!editable && !problem && !slow && status === 'ready' && !video?.playing && !blocked && (
          <div className="absolute inset-x-0 bottom-3 flex justify-center pointer-events-none">
            <span className="px-3 py-1.5 rounded-xl bg-slate-950/80 text-white text-xs font-semibold">
              Waiting for your teacher to play the video
            </span>
          </div>
        )}

        {!editable && blocked && !problem && (
          <button
            onClick={tapToPlay}
            className="absolute inset-0 flex flex-col items-center justify-center gap-3
                       bg-slate-950/60 text-white font-semibold"
          >
            <span className="h-16 w-16 rounded-full bg-rose-500 flex items-center justify-center">
              <Play size={30} className="ml-1" />
            </span>
            Tap to play the video
          </button>
        )}

        {/* The whole picture turns the sound on, not just the button. A child
            watching a silent lesson should not have to hit a small target. */}
        {!editable && soundOff && !blocked && !tapVideo && !problem && (
          <button
            onClick={turnSoundOn}
            aria-label="Turn the video sound on"
            className="absolute inset-0 flex items-end justify-center pb-3"
          >
            <span className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-rose-500 text-white
                             text-sm font-semibold shadow-lg">
              <Volume2 size={18} /> Tap for sound
            </span>
          </button>
        )}

        {!editable && tapVideo && !problem && (
          <div className="absolute top-2 inset-x-0 flex justify-center pointer-events-none">
            <span className="px-3 py-1.5 rounded-xl bg-slate-950/80 text-white text-xs font-semibold">
              Tap the video to start it
            </span>
          </div>
        )}
      </div>

      {/* The teacher drives the class from here, not from inside the video */}
      {editable && (
        <div className="shrink-0 glass rounded-2xl px-3 py-2 flex items-center gap-2 flex-wrap">
          <button
            onClick={teacherState.playing ? teacherPause : teacherPlay}
            disabled={status !== 'ready'}
            className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-brand-blue text-white
                       text-sm font-semibold disabled:opacity-50"
          >
            {teacherState.playing ? <Pause size={18} /> : <Play size={18} />}
            {teacherState.playing ? 'Pause for the class' : 'Play for the class'}
          </button>

          <button
            onClick={() => teacherSeekBy(-10)}
            disabled={status !== 'ready'}
            className="p-2.5 rounded-2xl glass disabled:opacity-50"
            title="Back 10 seconds"
          >
            <Undo2 size={18} />
          </button>

          <button
            onClick={() => teacherSeekTo(0)}
            disabled={status !== 'ready'}
            className="p-2.5 rounded-2xl glass disabled:opacity-50"
            title="Start again from the beginning"
          >
            <RotateCcw size={18} />
          </button>

          <span className="text-xs text-muted tabular-nums">
            {clock(teacherState.position)}
            {teacherState.duration ? ` / ${clock(teacherState.duration)}` : ''}
          </span>

          <span className="text-xs text-muted ml-auto hidden sm:inline">
            {status !== 'ready'
              ? 'Opening the video…'
              : teacherState.playing
                ? 'Your class is watching this'
                : 'Paused for everyone'}
          </span>

          {onStop && (
            <button onClick={onStop} className="btn-secondary text-sm">
              <X size={16} /> Stop showing
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Message({ children }) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center rounded-2xl bg-surface-3
                    text-muted text-sm text-center p-6">
      {children}
    </div>
  );
}
