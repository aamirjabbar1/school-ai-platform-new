import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Sparkles, ChevronDown } from 'lucide-react';

/**
 * Extended-thinking (reasoning) trace. While Claude is actively thinking it shows
 * an animated shimmering pill; once done it collapses to a tappable "Thought
 * process" chip that reveals the reasoning text.
 */
export default function ThinkingTrace({ text, active }) {
  const [open, setOpen] = useState(false);
  // Auto-expand while actively thinking, auto-collapse once done.
  useEffect(() => { setOpen(active); }, [active]);
  if (!text && !active) return null;

  return (
    <div className="w-full max-w-full">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`group relative flex items-center gap-2 text-xs font-semibold rounded-full pl-1.5 pr-3 py-1 transition-all duration-300 ${
          active
            ? 'text-white shadow-glow bg-gradient-to-r from-brand-indigo via-brand-violet to-brand-sky bg-[length:200%_100%] animate-[shimmer_2.5s_linear_infinite]'
            : 'text-brand-violet dark:text-brand-sky glass'
        }`}
      >
        <span className="relative flex h-5 w-5 items-center justify-center">
          {active && <span className="absolute inset-0 rounded-full bg-white/30 animate-ping" />}
          <Sparkles size={13} className={active ? 'text-white animate-spin-slow' : 'text-brand-violet dark:text-brand-sky'} />
        </span>
        <span className="tracking-tight">{active ? 'Thinking' : 'Thought process'}</span>
        <ChevronDown size={13} className={`transition-transform duration-300 ${open ? 'rotate-180' : ''} ${active ? 'text-white/80' : ''}`} />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div className="relative mt-2 rounded-2xl glass px-3.5 py-2.5">
              <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-gradient-to-b from-brand-indigo via-brand-violet to-brand-sky" />
              <p className="text-[12.5px] leading-relaxed text-muted whitespace-pre-wrap break-words pl-2">
                {text || (active ? 'Reasoning…' : '')}
                {active && <span className="inline-block w-1.5 h-3.5 ml-0.5 align-middle rounded-sm bg-brand-sky animate-pulse" />}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
