import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Plus, Trash2, AlertTriangle, MessageSquare, History } from 'lucide-react';

function parseDate(raw) {
  if (!raw) return null;
  const d = new Date(String(raw).replace(/(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([+-])/, '$1$2'));
  return isNaN(d) ? null : d;
}

/**
 * Slide-in glass drawer of past chat sessions. All data + actions are owned by
 * the parent ChatInterface; the clear-history confirmation lives here locally.
 */
export default function SessionsDrawer({
  open, onClose, sessions, activeId, memoryCount,
  onLoad, onDelete, onNew, onClearAll,
}) {
  const [confirm, setConfirm] = useState(false);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-40">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-slate-950/50 backdrop-blur-sm"
          />
          <motion.aside
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ type: 'spring', stiffness: 380, damping: 38 }}
            className="absolute left-0 top-0 bottom-0 w-[86vw] max-w-xs p-3"
          >
            <div className="h-full flex flex-col glass-strong rounded-3xl overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-line/60">
                <div className="flex items-center gap-2 font-display font-bold text-ink">
                  <History size={18} className="text-brand-cyan" /> Chat History
                </div>
                <button onClick={onClose} className="h-8 w-8 inline-flex items-center justify-center rounded-lg hover:bg-surface-3/60 text-muted" aria-label="Close history">
                  <X size={16} />
                </button>
              </div>

              <div className="p-3">
                <button
                  onClick={onNew}
                  className="btn-primary w-full py-2"
                >
                  <Plus size={15} /> New Chat
                </button>
              </div>

              {/* Sessions */}
              <div className="flex-1 overflow-y-auto px-3 space-y-1.5">
                {sessions.length === 0 && (
                  <div className="text-center py-10 text-muted">
                    <MessageSquare size={26} className="mx-auto mb-2 opacity-40" />
                    <p className="text-xs">No conversations yet</p>
                  </div>
                )}
                {sessions.map((s) => {
                  const d = parseDate(s.last_message_at);
                  const active = s.session_id === activeId;
                  return (
                    <button
                      key={s.session_id}
                      onClick={() => onLoad(s.session_id)}
                      className={`group relative w-full text-left p-2.5 rounded-xl transition-colors ${
                        active ? 'glass shadow-glow' : 'hover:bg-surface-3/50'
                      }`}
                    >
                      {active && <span className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-brand-gradient" />}
                      <div className="flex items-start justify-between gap-1 pl-1.5">
                        <div className="min-w-0">
                          <p className="text-xs font-semibold text-ink truncate">{s.first_message || 'Chat session'}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            {s.subject && <span className="text-[10px] text-brand-cyan font-medium">{s.subject}</span>}
                            <span className="text-[10px] text-faint">{d ? d.toLocaleDateString() : ''}</span>
                          </div>
                        </div>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => onDelete(s.session_id, e)}
                          className="opacity-0 group-hover:opacity-100 text-faint hover:text-rose-400 p-0.5 cursor-pointer"
                          aria-label="Delete session"
                        >
                          <Trash2 size={13} />
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Footer: clear all */}
              {memoryCount > 0 && (
                <div className="p-3 border-t border-line/60">
                  {!confirm ? (
                    <button
                      onClick={() => setConfirm(true)}
                      className="flex items-center gap-1.5 text-[11px] text-faint hover:text-rose-400 transition-colors"
                    >
                      <Trash2 size={12} /> Clear all history
                    </button>
                  ) : (
                    <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <AlertTriangle size={13} className="text-rose-500" />
                        <span className="text-xs text-rose-500 dark:text-rose-300 font-semibold">Delete all chat history?</span>
                      </div>
                      <p className="text-[11px] text-muted mb-2">This permanently erases the AI's memory of past conversations.</p>
                      <div className="flex gap-1.5">
                        <button onClick={() => { onClearAll(); setConfirm(false); }} className="flex-1 text-xs py-1.5 rounded-lg bg-rose-500 text-white hover:bg-rose-600 transition-colors">Delete All</button>
                        <button onClick={() => setConfirm(false)} className="flex-1 text-xs py-1.5 rounded-lg glass text-ink/80">Cancel</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
