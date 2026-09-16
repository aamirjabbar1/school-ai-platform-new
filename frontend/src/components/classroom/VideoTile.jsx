import { useEffect, useRef } from 'react';
import { VideoOff } from 'lucide-react';

// Attaches a media track to a <video> element and detaches it on unmount, so a
// classroom that switches teachers or reconnects never leaves a dead stream
// holding the camera.
export default function VideoTile({
  track, label, mirrored = false, muted = true, placeholder = 'Camera off', className = '',
}) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!track || !el) return undefined;
    track.attach(el);
    return () => { try { track.detach(el); } catch { /* element already gone */ } };
  }, [track]);

  return (
    <div className={`relative rounded-2xl overflow-hidden bg-surface-3 ${className}`}>
      {track ? (
        <video
          ref={ref}
          autoPlay
          playsInline
          muted={muted}
          className={`w-full h-full object-cover ${mirrored ? 'scale-x-[-1]' : ''}`}
        />
      ) : (
        <div className="w-full h-full min-h-[8rem] flex flex-col items-center justify-center gap-2 text-muted">
          <VideoOff size={28} />
          <span className="text-sm">{placeholder}</span>
        </div>
      )}
      {label && (
        <div className="absolute bottom-2 left-2 px-2.5 py-1 rounded-lg text-xs font-medium
                        text-white bg-slate-950/60 backdrop-blur-sm">
          {label}
        </div>
      )}
    </div>
  );
}
