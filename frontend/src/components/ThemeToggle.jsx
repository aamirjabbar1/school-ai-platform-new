import { motion, AnimatePresence } from 'framer-motion';
import { Sun, Moon, MonitorSmartphone } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

const ICONS = {
  dark: Moon,
  light: Sun,
  auto: MonitorSmartphone,
};
const LABELS = {
  dark: 'Dark',
  light: 'Light',
  auto: 'Auto',
};

/**
 * Animated theme switch. Click cycles dark → light → auto.
 * Variant "icon" renders a compact round button; "full" adds the label.
 */
export default function ThemeToggle({ variant = 'icon', className = '' }) {
  const { mode, cycleMode } = useTheme();
  const Icon = ICONS[mode] || Moon;

  return (
    <motion.button
      type="button"
      onClick={cycleMode}
      whileTap={{ scale: 0.9 }}
      whileHover={{ scale: 1.05 }}
      aria-label={`Theme: ${LABELS[mode]}. Click to change.`}
      title={`Theme: ${LABELS[mode]} (click to cycle)`}
      className={`relative inline-flex items-center gap-2 rounded-full glass-strong overflow-hidden
                  ${variant === 'full' ? 'px-3 py-1.5' : 'h-9 w-9 justify-center'}
                  text-ink/80 hover:text-ink transition-colors ${className}`}
    >
      {/* glow ring */}
      <span className="pointer-events-none absolute inset-0 rounded-full bg-brand-gradient opacity-0 hover:opacity-10 transition-opacity" />
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={mode}
          initial={{ y: 8, opacity: 0, rotate: -30 }}
          animate={{ y: 0, opacity: 1, rotate: 0 }}
          exit={{ y: -8, opacity: 0, rotate: 30 }}
          transition={{ duration: 0.2 }}
          className="flex items-center justify-center text-brand-sky"
        >
          <Icon size={17} />
        </motion.span>
      </AnimatePresence>
      {variant === 'full' && (
        <span className="text-xs font-semibold text-ink/80">{LABELS[mode]}</span>
      )}
    </motion.button>
  );
}
