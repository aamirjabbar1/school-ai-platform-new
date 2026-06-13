import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookText, ChevronDown, GraduationCap, Quote } from 'lucide-react';

// Subject → accent gradient (falls back to brand blue→cyan).
const SUBJECT_ACCENT = {
  Mathematics: 'from-blue-500 to-indigo-500',
  Physics: 'from-cyan-500 to-blue-500',
  Chemistry: 'from-emerald-500 to-teal-500',
  Biology: 'from-green-500 to-emerald-500',
  Science: 'from-teal-500 to-cyan-500',
  English: 'from-rose-500 to-pink-500',
  Urdu: 'from-amber-500 to-orange-500',
  Islamiat: 'from-emerald-600 to-green-500',
  'Computer Science': 'from-violet-500 to-purple-500',
  'Social Studies': 'from-orange-500 to-amber-500',
  History: 'from-amber-600 to-yellow-500',
  Geography: 'from-lime-500 to-green-500',
};

function DocRow({ doc, index }) {
  const [open, setOpen] = useState(false);
  const accent = SUBJECT_ACCENT[doc.subject] || 'from-brand-blue to-brand-cyan';
  const chunks = doc.chunks || [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="rounded-xl glass-strong overflow-hidden"
    >
      <button
        type="button"
        onClick={() => chunks.length && setOpen((o) => !o)}
        className="w-full flex items-center gap-2.5 p-2.5 text-left"
      >
        <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${accent} flex items-center justify-center text-white shrink-0 shadow-glow`}>
          <BookText size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold text-ink truncate">{doc.title || 'Curriculum document'}</div>
          <div className="flex items-center gap-1.5 mt-0.5 text-[10.5px] text-muted">
            {doc.subject && <span className="font-medium">{doc.subject}</span>}
            {doc.class_level && (
              <span className="inline-flex items-center gap-0.5">
                <GraduationCap size={10} /> {doc.class_level}
              </span>
            )}
            {doc.document_type && <span className="capitalize opacity-80">· {doc.document_type}</span>}
          </div>
        </div>
        {chunks.length > 0 && (
          <ChevronDown size={14} className={`text-faint transition-transform shrink-0 ${open ? 'rotate-180' : ''}`} />
        )}
      </button>

      <AnimatePresence initial={false}>
        {open && chunks.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-2.5 pb-2.5 space-y-1.5">
              {chunks.slice(0, 4).map((c, i) => (
                <div key={i} className="relative rounded-lg bg-surface-3/60 p-2 pl-5 text-[11.5px] leading-relaxed text-muted">
                  <Quote size={11} className="absolute left-1.5 top-2 text-brand-cyan/70" />
                  <span className="line-clamp-4">{c.text}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/**
 * Collapsible "From your books" card listing the curriculum documents that
 * grounded the answer (the `done.sources` array). Pure presentation over data
 * the chat already receives.
 */
export default function SourcesCard({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources?.length) return null;

  return (
    <div className="w-full">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group inline-flex items-center gap-2 text-xs font-semibold rounded-full glass px-3 py-1.5 text-ink/80 hover:text-ink transition-colors"
      >
        <BookText size={13} className="text-brand-cyan" />
        <span>From your books</span>
        <span className="px-1.5 py-0.5 rounded-full bg-brand-cyan/15 text-brand-cyan text-[10px] font-bold">
          {sources.length}
        </span>
        <ChevronDown size={13} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-1.5">
              {sources.map((doc, i) => (
                <DocRow key={doc.document_id || i} doc={doc} index={i} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
