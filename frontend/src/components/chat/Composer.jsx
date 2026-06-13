import { motion } from 'framer-motion';
import { Send, Square, ChevronDown } from 'lucide-react';

/**
 * Floating glass message composer pinned to the bottom of the conversation.
 * Auto-growing textarea, subject selector, and an animated send / stop button.
 * All state is owned by the parent; this is presentation + wiring.
 */
export default function Composer({
  input, setInput, onSubmit, streaming, onStop,
  subject, setSubject, subjects = [], inputRef,
}) {
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="px-3 pb-3 sm:px-4 sm:pb-4">
      <div className="mx-auto w-full max-w-3xl">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-strong rounded-3xl p-2 shadow-glow"
        >
          <div className="flex items-end gap-2">
            {/* Subject selector */}
            <div className="relative shrink-0">
              <select
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="appearance-none cursor-pointer text-xs font-medium rounded-2xl glass pl-3 pr-7 py-2.5 text-ink/80 focus:outline-none focus:ring-2 focus:ring-brand-cyan/50 max-w-[7.5rem] truncate"
                title="Filter by subject"
              >
                <option value="">All Subjects</option>
                {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <ChevronDown size={13} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-faint" />
            </div>

            {/* Text input */}
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about your studies…"
              disabled={streaming}
              className="flex-1 resize-none bg-transparent border-0 focus:ring-0 focus:outline-none text-sm text-ink placeholder:text-faint py-2.5 max-h-40 disabled:opacity-60"
              style={{ minHeight: '2.75rem' }}
            />

            {/* Send / Stop */}
            {streaming ? (
              <motion.button
                type="button"
                onClick={onStop}
                whileTap={{ scale: 0.9 }}
                className="btn-danger h-11 w-11 rounded-2xl !p-0"
                title="Stop generating"
                aria-label="Stop generating"
              >
                <Square size={16} fill="white" />
              </motion.button>
            ) : (
              <motion.button
                type="button"
                onClick={onSubmit}
                disabled={!input.trim()}
                whileTap={{ scale: 0.9 }}
                whileHover={input.trim() ? { scale: 1.05 } : {}}
                className="btn-primary h-11 w-11 rounded-2xl !p-0 disabled:opacity-40"
                title="Send"
                aria-label="Send message"
              >
                <Send size={17} />
              </motion.button>
            )}
          </div>
        </motion.div>
        <p className="text-[11px] text-faint mt-2 text-center">
          Grounded in your school curriculum · web search used only when needed
        </p>
      </div>
    </div>
  );
}
