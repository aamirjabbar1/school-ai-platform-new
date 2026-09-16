import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, MicOff, Volume2, WifiOff, X } from 'lucide-react';

// What a student sees when the network wobbles. Deliberately plain language:
// a child who reads "ICE connection failed" learns nothing except that
// something is broken, so they get "Reconnecting…" and a spinner instead.
//
// `deviceNotice` is the same idea for a camera or microphone that would not
// start: the lesson carries on, so this informs rather than interrupts, and it
// can be dismissed.
export default function ConnectionBanner({
  status, audioBlocked, onEnableAudio, deviceNotice, onDismissDeviceNotice,
}) {
  const reconnecting = status === 'reconnecting';
  const disconnected = status === 'disconnected';
  const show = reconnecting || disconnected || audioBlocked || Boolean(deviceNotice);

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
          ) : (!reconnecting && !disconnected && deviceNotice) ? (
            <div className="flex items-start gap-2 px-4 py-3 rounded-2xl
                            glass-strong text-ink font-medium">
              <MicOff size={18} className="text-amber-400 shrink-0 mt-0.5" />
              <span className="flex-1 text-sm">{deviceNotice}</span>
              <button
                onClick={onDismissDeviceNotice}
                aria-label="Dismiss"
                className="shrink-0 text-ink-soft hover:text-ink"
              >
                <X size={16} />
              </button>
            </div>
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
