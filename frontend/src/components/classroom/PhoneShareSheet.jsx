import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, Clapperboard, PenLine, Presentation, Smartphone, X } from 'lucide-react';

// Shown when Share Screen is pressed on a device that cannot share a screen.
//
// No mobile browser — Chrome, Samsung Internet or Firefox on Android, or any
// browser on an iPhone or iPad — lets a website capture the screen; Android and
// iOS keep that for installed apps. Rather than a button that does nothing,
// the teacher is offered the tools that show the same lesson from a phone.
export default function PhoneShareSheet({ open, onClose, onVideo, onBook, onDocumentCamera, onWhiteboard }) {
  const options = [
    {
      icon: Clapperboard, title: 'Share a video',
      body: 'Paste a YouTube link. Every student sees and hears it.', action: onVideo,
    },
    {
      icon: BookOpen, title: 'Open Book',
      body: 'Show a page from your books and write on it.', action: onBook,
    },
    {
      icon: Presentation, title: 'Show Book',
      body: "Point your phone's back camera at a page or worksheet.", action: onDocumentCamera,
    },
    {
      icon: PenLine, title: 'Whiteboard',
      body: 'Write and draw for the class.', action: onWhiteboard,
    },
  ];

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
                       glass-strong rounded-t-3xl sm:rounded-3xl p-5 max-h-[85vh] overflow-y-auto"
          >
            <div className="flex items-center gap-3 mb-2">
              <Smartphone size={20} className="text-brand-cyan" />
              <h2 className="font-display font-bold text-lg flex-1">Phones cannot share their screen</h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-surface-3">
                <X size={18} />
              </button>
            </div>

            <p className="text-sm text-muted mb-4">
              Android phones and iPhones do not allow websites to share the screen. These show the
              same lesson from your phone, and work better on a slow connection:
            </p>

            <div className="space-y-2">
              {options.map(({ icon: Icon, title, body, action }) => (
                <button
                  key={title}
                  onClick={() => { onClose(); action(); }}
                  className="w-full glass rounded-2xl p-3 flex items-center gap-3 text-left
                             hover:shadow-glow transition-shadow"
                >
                  <div className="w-10 h-10 rounded-xl bg-surface-3 flex items-center justify-center text-brand-cyan shrink-0">
                    <Icon size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-sm">{title}</div>
                    <div className="text-xs text-muted">{body}</div>
                  </div>
                </button>
              ))}
            </div>

            <p className="text-xs text-faint mt-4">
              To share your whole screen, including other apps and websites, teach from a laptop or
              desktop computer using Chrome or Edge.
            </p>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
