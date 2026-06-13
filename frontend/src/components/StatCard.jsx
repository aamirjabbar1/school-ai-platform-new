import { motion } from 'framer-motion';

// Static gradient map (Tailwind can't see dynamically-built class names).
const GRADIENTS = {
  blue: 'from-brand-blue to-brand-cyan',
  cyan: 'from-cyan-500 to-sky-500',
  green: 'from-emerald-500 to-teal-500',
  emerald: 'from-emerald-500 to-green-500',
  yellow: 'from-amber-500 to-orange-500',
  orange: 'from-orange-500 to-amber-500',
  purple: 'from-brand-violet to-brand-purple',
  pink: 'from-pink-500 to-rose-500',
  red: 'from-rose-500 to-pink-500',
  teal: 'from-teal-500 to-emerald-500',
  indigo: 'from-brand-indigo to-brand-violet',
  gray: 'from-slate-500 to-slate-400',
};

/**
 * A glass statistic tile with a gradient icon and a gentle hover lift.
 * Replaces the old dynamic `bg-${color}-100` pattern that Tailwind purged.
 */
export default function StatCard({ icon: Icon, value, label, sub, color = 'blue', delay = 0 }) {
  const grad = GRADIENTS[color] || GRADIENTS.blue;
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35 }}
      whileHover={{ y: -4 }}
      className="card !p-4 sm:!p-5"
    >
      <div className={`w-11 h-11 rounded-2xl bg-gradient-to-br ${grad} flex items-center justify-center mb-3 text-white shadow-glow`}>
        {Icon && <Icon size={20} />}
      </div>
      <div className="text-2xl font-bold text-ink font-display">{value}</div>
      <div className="text-sm text-muted">{label}</div>
      {sub && <div className="text-xs text-faint">{sub}</div>}
    </motion.div>
  );
}
