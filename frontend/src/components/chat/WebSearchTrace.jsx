import { motion } from 'framer-motion';
import { Globe, Loader2 } from 'lucide-react';

function hostname(url) {
  try { return new URL(url).hostname.replace('www.', ''); } catch { return url; }
}

/**
 * Shows the web searches Claude ran for an answer, as a glass card with a
 * pulsing globe and clickable source chips.
 */
export default function WebSearchTrace({ searches }) {
  if (!searches?.length) return null;
  return (
    <div className="space-y-1.5 w-full">
      {searches.map((s, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl glass px-3 py-2"
        >
          <div className="flex items-center gap-2 text-[11.5px] font-semibold text-emerald-600 dark:text-emerald-300">
            {s.pending
              ? <Loader2 size={12} className="animate-spin" />
              : <Globe size={12} className="animate-glow-pulse" />}
            <span>{s.pending ? 'Searching the web…' : 'Searched the web for'}</span>
            {!s.pending && <span className="italic text-muted">"{s.query}"</span>}
          </div>
          {s.urls?.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {s.urls.slice(0, 6).map((u, j) => (
                <a
                  key={j}
                  href={u.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={u.title}
                  className="inline-flex items-center gap-1 text-[10.5px] px-2 py-0.5 rounded-full glass-strong text-ink/80 hover:text-ink hover:scale-105 transition-transform truncate max-w-[170px]"
                >
                  <img
                    src={`https://www.google.com/s2/favicons?domain=${hostname(u.url)}&sz=32`}
                    alt=""
                    className="w-3 h-3 rounded-sm"
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                  {hostname(u.url)}
                </a>
              ))}
              {s.urls.length > 6 && (
                <span className="text-[10.5px] text-muted self-center">+{s.urls.length - 6} more</span>
              )}
            </div>
          )}
        </motion.div>
      ))}
    </div>
  );
}
