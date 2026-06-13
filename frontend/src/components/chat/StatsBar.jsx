import { motion } from 'framer-motion';
import { Flame, MessageCircleQuestion, Layers } from 'lucide-react';

function Pill({ icon: Icon, value, label, grad }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex items-center gap-1.5 rounded-full glass pl-1 pr-2.5 py-1"
      title={label}
    >
      <span className={`w-6 h-6 rounded-full bg-gradient-to-br ${grad} flex items-center justify-center text-white`}>
        <Icon size={12} />
      </span>
      <span className="text-xs font-bold text-ink leading-none">{value}</span>
      <span className="hidden sm:inline text-[10px] text-muted leading-none">{label}</span>
    </motion.div>
  );
}

/**
 * Playful, honest progress pills computed from real session data
 * (no backend changes): day streak, questions asked, conversations.
 */
export default function StatsBar({ streak = 0, questions = 0, topics = 0 }) {
  return (
    <div className="flex items-center gap-1.5">
      {streak > 0 && <Pill icon={Flame} value={`${streak}d`} label="streak" grad="from-amber-500 to-orange-500" />}
      <Pill icon={MessageCircleQuestion} value={questions} label="asked" grad="from-brand-blue to-brand-cyan" />
      {topics > 0 && <Pill icon={Layers} value={topics} label="chats" grad="from-brand-violet to-brand-purple" />}
    </div>
  );
}
