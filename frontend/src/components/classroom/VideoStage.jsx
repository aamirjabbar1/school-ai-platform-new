import { useEffect, useRef, useState } from 'react';
import { Loader2, Play, VideoOff, Volume2 } from 'lucide-react';

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

const YT_STATE = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 };

const HEARTBEAT_MS = 4000;       // teacher → class position updates
const CHECK_MS = 1000;           // how often a student's player is checked
const PLAYING_DRIFT_S = 4;       // tolerated gap while playing
const PAUSED_DRIFT_S = 1.5;      // tolerated gap while paused
const SEEK_SETTLE_MS = 5000;     // let a seek finish buffering before judging it
const BLOCKED_AFTER_MS = 3000;   // still not playing → the browser needs a tap
const IGNORE_SYNC_MS = 1500;     // a heartbeat sent before a pause must not undo it

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

function expectedPosition(target) {
  if (!target) return 0;
  return target.playing ? target.position + (Date.now() - target.at) / 1000 : target.position;
}

export default function VideoStage({
  video, editable = false, sync, lowBandwidth = false, onReport, onProgress,
}) {
  const hostRef = useRef(null);
  const playerRef = useRef(null);
  const loadedIdRef = useRef(null);
  const targetRef = useRef(null);     // where the class should be
  const reportedRef = useRef(null);   // teacher: what the class was last told
  const lastSeekRef = useRef(0);
  const cuedAtRef = useRef(null);
  const wantPlaySinceRef = useRef(0);
  const ignoreSyncUntilRef = useRef(0);
  const callbacksRef = useRef({ onReport, onProgress });
  callbacksRef.current = { onReport, onProgress };

  const [status, setStatus] = useState('loading'); // loading|ready|unavailable|no-embed|error
  const [blocked, setBlocked] = useState(false);
  const [tapVideo, setTapVideo] = useState(false);
  const tapVideoRef = useRef(false);
  tapVideoRef.current = tapVideo;
  const [soundOff, setSoundOff] = useState(false);
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

    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !hostRef.current) return;
        const target = targetRef.current;
        const start = expectedPosition(target);
        // The API replaces this element with an iframe, so it is created here
        // rather than rendered by React.
        const mount = document.createElement('div');
        hostRef.current.appendChild(mount);
        loadedIdRef.current = target.videoId;
        reportedRef.current = { playing: target.playing, position: start, at: Date.now() };

        player = new YT.Player(mount, {
          host: 'https://www.youtube-nocookie.com',
          videoId: target.videoId,
          width: '100%',
          height: '100%',
          playerVars: {
            playsinline: 1,
            rel: 0,
            modestbranding: 1,
            iv_load_policy: 3,
            // Students follow the teacher; their controls would only fight it.
            controls: editable ? 1 : 0,
            disablekb: editable ? 0 : 1,
            fs: editable ? 1 : 0,
            start: Math.floor(start),
            origin: window.location.origin,
          },
          events: {
            onReady: () => {
              if (cancelled) return;
              playerRef.current = player;
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
              // 101/150: the owner does not allow playback on other sites.
              setStatus(event.data === 101 || event.data === 150 ? 'no-embed' : 'error');
            },
          },
        });
      })
      .catch(() => { if (!cancelled) setStatus('unavailable'); });

    return () => {
      cancelled = true;
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

  // ── Teacher: heartbeat ────────────────────────────────────────────────────
  useEffect(() => {
    if (!editable || !started) return undefined;
    const timer = setInterval(() => {
      const player = playerRef.current;
      if (!player || !loadedIdRef.current) return;
      const state = player.getPlayerState();
      // Nothing has been played yet: the shared start point already stands.
      if (state === YT_STATE.UNSTARTED || state === YT_STATE.CUED) return;
      const position = player.getCurrentTime();
      const last = reportedRef.current;
      // Seeking while paused raises no event; notice it here.
      if (state === YT_STATE.PAUSED && last && !last.playing && Math.abs(position - last.position) > 1) {
        report(false, position);
      }
      callbacksRef.current.onProgress?.({
        videoId: loadedIdRef.current,
        playing: state === YT_STATE.PLAYING || state === YT_STATE.BUFFERING,
        position,
      });
    }, HEARTBEAT_MS);
    return () => clearInterval(timer);
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
          // Browsers may refuse to start sound without a tap on this page. Once
          // the student has been asked to tap the video itself, the overlay
          // stays away so that tap can land.
          if (now - wantPlaySinceRef.current > BLOCKED_AFTER_MS && !tapVideoRef.current) {
            setBlocked(true);
          }
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
    player.unMute?.();
    player.setVolume?.(100);
    setSoundOff(false);
  };

  const tapToPlay = () => {
    const player = playerRef.current;
    if (!player) return;
    player.unMute?.();
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

  const problem = {
    unavailable: 'YouTube could not be reached on this connection.',
    'no-embed': editable
      ? 'The owner of this video does not allow it to be played in other websites. Please choose a different video.'
      : 'This video cannot be played here.',
    error: 'This video could not be played.',
  }[status];

  return (
    <div className="relative w-full h-full rounded-2xl overflow-hidden bg-black">
      <div ref={hostRef} className="absolute inset-0" />

      {status === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 text-white/80 text-sm">
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

      {!editable && soundOff && !blocked && !problem && (
        <button
          onClick={turnSoundOn}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-2.5
                     rounded-2xl bg-rose-500 text-white text-sm font-semibold shadow-lg"
        >
          <Volume2 size={18} /> Tap for sound
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
