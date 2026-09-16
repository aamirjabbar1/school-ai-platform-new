import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Volume2, WifiOff } from 'lucide-react';

// What a student sees when the network wobbles. Deliberately plain language:
// a child who reads "ICE connection failed" learns nothing except that
// something is broken, so they get "Reconnecting…" and a spinner instead.
export default function ConnectionBanner({ status, audioBlocked, onEnableAudio }) {
  const reconnecting = status === 'reconnecting';
  const disconnected = status === 'disconnected';
  const show = reconnecting || disconnected || audioBlocked;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          className="fixed top-3 left-1/2 -translate-x-1/2 z-50 w-[min(92vw,30rem)]"
        >
          {audioBlocked ? (
            <button
              onClick={onEnableAudio}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-2xl
                         font-semibold text-white bg-brand-blue shadow-glow"
            >
              <Volume2 size={18} />
              Tap to turn on sound
            </button>
          ) : (
            <div className="flex items-center justify-center gap-2 px-4 py-3 rounded-2xl
                            glass-strong text-ink font-medium">
              {reconnecting ? (
                <>
                  <Loader2 size={18} className="animate-spin text-brand-cyan" />
                  Connection lost — reconnecting…
                </>
              ) : (
                <>
                  <WifiOff size={18} className="text-rose-400" />
                  You are not connected to the class.
                </>
              )}
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
