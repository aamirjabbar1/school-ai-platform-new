import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { apiError } from '../../services/apiError';
import { Clapperboard, X, Loader2 } from 'lucide-react';

// SHARE VIDEO — paste a YouTube link; every student's device plays it, with
// sound, in step with the teacher. Works the same from a phone or a laptop.
export default function ShareVideoDialog({ open, onClose, onShare, onResume, hasVideo, videoOnStage }) {
  const [link, setLink] = useState('');
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) { setError(''); setLink(''); }
  }, [open]);

  const submit = async (event) => {
    event.preventDefault();
    if (!link.trim()) return;
    setSharing(true);
    setError('');
    try {
      await onShare(link.trim());
      onClose();
    } catch (err) {
      setError(apiError(err, 'This video could not be shared.'));
    } finally {
      setSharing(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm" onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 24 }}
            className="absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:max-w-lg sm:h-fit
                       glass-strong rounded-t-3xl sm:rounded-3xl p-5"
          >
            <div className="flex items-center gap-3 mb-3">
              <Clapperboard size={20} className="text-brand-cyan" />
              <h2 className="font-display font-bold text-lg flex-1">Share a video</h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-surface-3">
                <X size={18} />
              </button>
            </div>

            <p className="text-sm text-muted mb-3">
              Paste a YouTube link. The video plays on every student&apos;s screen with its sound,
              and pauses when you pause. Press play when you are ready.
            </p>

            <form onSubmit={submit} className="space-y-3">
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://youtu.be/…"
                inputMode="url"
                autoComplete="off"
                autoFocus
                className="input-field"
              />
              {error && <div className="text-sm text-rose-400">{error}</div>}
              <button type="submit" disabled={sharing || !link.trim()} className="btn-primary w-full">
                {sharing ? <Loader2 size={18} className="animate-spin" /> : <Clapperboard size={18} />}
                Show to the class
              </button>
            </form>

            {hasVideo && !videoOnStage && (
              <button onClick={() => { onResume(); onClose(); }} className="btn-secondary w-full mt-2">
                Go back to the last video
              </button>
            )}

            <p className="text-xs text-faint mt-3">
              Tip: if your microphone is on and the video plays from your speaker, students may hear
              it twice. Headphones avoid that.
            </p>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
