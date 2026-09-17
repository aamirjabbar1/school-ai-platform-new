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
// Two rules decide almost everything here, and both were learned from phones
// in real classrooms rather than from the documentation:
//
//   * A picture beats silence. When a browser refuses to start a video with
//     sound — every mobile browser does, until the page has been touched —
//     the video is started muted and the class is offered one tap for sound,
//     rather than being left watching nothing.
//   * Nothing decorative may touch the video. A phone draws video on its own
//     GPU layer, and a rounded `overflow:hidden` parent, a faded sibling or a
//     frosted-glass neighbour drags it back into the page, where some devices
//     simply do not draw it: sound plays and the picture is black. So the box
//     around the video rounds nothing, fades nothing and blurs nothing, and
//     the frame is stripped of its own radius after YouTube builds it.

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

// TEMPORARY. Share Video has to work on phones none of us can attach a
// debugger to, so while that is being settled the stage says out loud what it
// thinks is happening, on both sides. Turn this off once the picture is good.
const SHOW_DIAGNOSTICS = true;

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

// The frame is built by YouTube's own API, not by hand.
//
// It was hand-built here for a while, to control its styling. That was a
// mistake, and an instructive one: the API's frame also carries
// `referrerpolicy="strict-origin-when-cross-origin"`, and a phone whose
// browser strips cross-site referrers — Samsung Internet, Brave, Firefox and
// Chrome with tracking protection all do — then reaches YouTube with no
// referrer at all and is answered with a player configuration error. Which
// looks, in a classroom, like a blank white rectangle.
//
// So the API builds it, and only its layout is adjusted afterwards: filling
// the box, and carrying no radius or transform of its own, because both put
// the video back on a layer the phone has to redraw by hand.
function layOutFrame(frame) {
  if (!frame) return;
  frame.style.position = 'absolute';
  frame.style.inset = '0';
  frame.style.width = '100%';
  frame.style.height = '100%';
  frame.style.border = '0';
  frame.style.borderRadius = '0';
  frame.style.display = 'block';
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
  const [details, setDetails] = useState('');
  // null while unknown, then whether YouTube can be reached from this device.
  const [reachable, setReachable] = useState(null);
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

  // ── Can this device reach YouTube at all? ─────────────────────────────────
  //
  // Asked plainly, with the video's own thumbnail, because a blocked or
  // filtered network — common on mobile data and on school connections — gives
  // a blank frame and no error a browser will hand us. Without this the class
  // stares at a white rectangle and everyone blames the lesson software.
  useEffect(() => {
    if (!videoId) return undefined;
    let cancelled = false;
    setReachable(null);
    const probe = new Image();
    probe.onload = () => { if (!cancelled) setReachable(true); };
    probe.onerror = () => { if (!cancelled) setReachable(false); };
    probe.src = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
    return () => { cancelled = true; probe.onload = null; probe.onerror = null; };
  }, [videoId]);

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

        // The API replaces this element with its own iframe.
        const mount = document.createElement('div');
        hostRef.current.appendChild(mount);

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
              layOutFrame(player.getIframe?.());
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
        // The frame exists as soon as the constructor returns, so it is laid
        // out now rather than only once the player answers.
        layOutFrame(player.getIframe?.());
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

  // ── Tell the player how big it is ─────────────────────────────────────────
  //
  // The YouTube player measures its frame once, as it starts. A frame that was
  // still being laid out at that moment — which is normal on a phone, where the
  // address bar moves and the keyboard has just closed — leaves it drawing a
  // video of the wrong size, or of no size at all. Re-stating the size after it
  // settles, and whenever the phone is turned, costs nothing and fixes that.
  useEffect(() => {
    if (!started || !hasVideo || status !== 'ready') return undefined;
    const fit = () => {
      const box = hostRef.current;
      const player = playerRef.current;
      if (!box || !player?.setSize) return;
      const { width, height } = box.getBoundingClientRect();
      if (width < 1 || height < 1) return;
      try { player.setSize(Math.round(width), Math.round(height)); } catch { /* not ready */ }
    };
    const settle = setTimeout(fit, 700);
    window.addEventListener('resize', fit);
    window.addEventListener('orientationchange', fit);
    return () => {
      clearTimeout(settle);
      window.removeEventListener('resize', fit);
      window.removeEventListener('orientationchange', fit);
    };
  }, [started, hasVideo, status]);

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

  // One line the teacher can read out when a video still misbehaves on a
  // device none of us can put our hands on. Hidden until the clock is tapped,
  // so it costs a working lesson nothing.
  const describe = () => {
    const player = playerRef.current;
    const box = hostRef.current;
    const frame = box?.firstElementChild;
    const ask = (fn, fallback = '?') => {
      try { const value = fn(); return value === undefined || value === null ? fallback : value; }
      catch { return fallback; }
    };
    const size = (element) => {
      const rect = element?.getBoundingClientRect();
      return rect ? `${Math.round(rect.width)}×${Math.round(rect.height)}` : 'none';
    };
    return [
      status,
      `yt ${reachable === null ? 'testing' : reachable ? 'reachable' : 'BLOCKED'}`,
      `id ${videoId || 'none'}`,
      `state ${ask(() => player?.getPlayerState?.())}`,
      `quality ${ask(() => player?.getPlaybackQuality?.())}`,
      `loaded ${ask(() => Math.round((player?.getVideoLoadedFraction?.() || 0) * 100))}%`,
      `muted ${ask(() => String(!!player?.isMuted?.()))}`,
      `box ${size(box)}`,
      `frame ${size(frame)}`,
    ].join(' · ');
  };

  useEffect(() => {
    if (!SHOW_DIAGNOSTICS || !started || !hasVideo) return undefined;
    const tick = () => setDetails(describe());
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
    // `describe` reads the current render's state, so it is refreshed whenever
    // any of that changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, hasVideo, status, reachable, blocked, soundOff]);

  const retry = () => {
    // Rebuilding is the only cure for a frame that never answered; flipping
    // `started` off and on again re-runs the effect that creates it.
    setStarted(false);
    setTimeout(() => setStarted(true), 50);
  };

  if (!hasVideo) {
    return (
      <Message>
        No video is being shared.
        {SHOW_DIAGNOSTICS && (
          <span className="block mt-2 text-[10px] text-faint select-all">
            {editable ? 'teacher' : 'student'} · no video in the stage state
          </span>
        )}
      </Message>
    );
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

  // A device that cannot fetch a thumbnail will not be playing a video either.
  // Say so in the words that point at the actual cause, rather than leaving a
  // blank frame for a teacher to interpret mid-lesson.
  const unreachable = reachable === false
    ? 'YouTube cannot be opened on this device. Its network or a content filter is blocking '
      + 'YouTube — mobile data and school connections often do. Try a different network.'
    : null;

  // A fatal problem replaces the video; nothing is playing behind it.
  const problem = unreachable || {
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
    // `absolute inset-0`, not `h-full`.
    //
    // This is what was wrong all along. The stage sits in a flex item whose
    // height comes from `min-height` and from flex growth, so its own `height`
    // stays `auto` — and a percentage height resolved against `auto` is not
    // 45vh, it is nothing. On a desktop the stage is a *row* flex item, which
    // is stretched to a real height, so `h-full` worked there and only there.
    // Every phone got a player that was loading, playing, unmuted and 0 pixels
    // tall. Filling a positioned parent asks no question that can be answered
    // with "auto".
    <div className="absolute inset-0 flex flex-col gap-2">
      {/* Nothing may clip, round, fade or blur this box.
          On a phone the video is drawn by the GPU on a layer of its own, and a
          rounded `overflow:hidden` parent, an `opacity` sibling or a frosted
          neighbour forces it back into the page — which, on a good many Android
          and iOS devices, is a black rectangle with working sound. That is
          exactly what a class saw here. Square corners are a small price.
          The poster is a background image rather than an element for the same
          reason: one less layer over the video. */}
      <div
        className="relative flex-1 min-h-0"
        style={{
          backgroundColor: '#000',
          backgroundImage: `url(https://i.ytimg.com/vi/${videoId}/hqdefault.jpg)`,
          backgroundSize: 'contain',
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'center',
        }}
      >
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
                ? 'This video has not answered. Use the controls in the video itself, or try again. '
                  + 'If it stays blank, this browser may be blocking YouTube — try Chrome.'
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

      {/* The teacher drives the class from here, not from inside the video.
          Solid, not frosted: a backdrop blur pressed against the video is one
          of the things that costs a phone the picture. */}
      {editable && (
        <div className="shrink-0 bg-surface-2 border border-line rounded-2xl px-3 py-2
                        flex items-center gap-2 flex-wrap">
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
            className="p-2.5 rounded-2xl bg-surface-3 border border-line disabled:opacity-50"
            title="Back 10 seconds"
          >
            <Undo2 size={18} />
          </button>

          <button
            onClick={() => teacherSeekTo(0)}
            disabled={status !== 'ready'}
            className="p-2.5 rounded-2xl bg-surface-3 border border-line disabled:opacity-50"
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
            <button
              onClick={onStop}
              className="flex items-center gap-2 px-3 py-2 rounded-2xl bg-surface-3 border border-line
                         text-sm font-medium"
            >
              <X size={16} /> Stop showing
            </button>
          )}

        </div>
      )}

      {/* TEMPORARY — while Share Video is being made to work on real phones.
          Neither of us can attach a debugger to the devices this has to run on,
          so the page says out loud what it thinks is happening. Delete this
          strip, SHOW_DIAGNOSTICS and `describe()` once the picture is good. */}
      {SHOW_DIAGNOSTICS && details && (
        <div className="shrink-0 text-[10px] leading-tight text-faint break-all select-all
                        bg-surface-2 border border-line rounded-xl px-2 py-1">
          {editable ? 'teacher' : 'student'} · {details}
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
