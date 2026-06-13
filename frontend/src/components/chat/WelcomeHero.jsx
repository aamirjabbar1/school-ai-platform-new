import { motion } from 'framer-motion';
import { Sparkles, BookOpen, Calculator, FlaskConical, PenLine, Lightbulb, Languages } from 'lucide-react';
import AiOrb from './AiOrb';

const STUDENT_PROMPTS = [
  { icon: FlaskConical, label: 'Explain photosynthesis', grad: 'from-emerald-500 to-teal-500' },
  { icon: Calculator, label: 'Help me with algebra', grad: 'from-blue-500 to-indigo-500' },
  { icon: BookOpen, label: 'Summarize Chapter 3', grad: 'from-violet-500 to-purple-500' },
  { icon: PenLine, label: 'Make study notes for my test', grad: 'from-rose-500 to-pink-500' },
  { icon: Languages, label: 'Translate this into Urdu', grad: 'from-amber-500 to-orange-500' },
  { icon: Lightbulb, label: 'Give me a fun science fact', grad: 'from-cyan-500 to-sky-500' },
];

const TEACHER_PROMPTS = [
  { icon: PenLine, label: 'Draft a lesson plan', grad: 'from-emerald-500 to-teal-500' },
  { icon: BookOpen, label: 'Create a quiz on this topic', grad: 'from-blue-500 to-indigo-500' },
  { icon: Lightbulb, label: 'Suggest classroom activities', grad: 'from-violet-500 to-purple-500' },
  { icon: Calculator, label: 'Explain a concept simply', grad: 'from-cyan-500 to-sky-500' },
];

export default function WelcomeHero({ userName, role = 'student', onPick }) {
  const prompts = role === 'teacher' ? TEACHER_PROMPTS : STUDENT_PROMPTS;
  const firstName = userName?.split(' ')[0] || (role === 'teacher' ? 'Teacher' : 'there');

  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-4 py-8">
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 200, damping: 18 }}
      >
        <AiOrb size={84} active float />
      </motion.div>

      <motion.h2
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="font-display text-2xl sm:text-3xl font-bold mt-6 text-ink"
      >
        Hi {firstName}! <span className="text-gradient">What shall we learn today?</span>
      </motion.h2>
      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25 }}
        className="text-muted text-sm mt-2 max-w-md"
      >
        Ask me anything from your subjects — I'll explain it clearly, with answers grounded in your
        school's curriculum. ✨
      </motion.p>

      <div className="mt-7 grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-xl">
        {prompts.map((p, i) => {
          const Icon = p.icon;
          return (
            <motion.button
              key={p.label}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35 + i * 0.07 }}
              whileHover={{ scale: 1.03, y: -2 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => onPick(p.label)}
              className="group flex items-center gap-3 p-3 rounded-2xl glass text-left hover:shadow-glow transition-shadow"
            >
              <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${p.grad} flex items-center justify-center text-white shrink-0 shadow-glow`}>
                <Icon size={17} />
              </div>
              <span className="text-sm font-medium text-ink/90 group-hover:text-ink">{p.label}</span>
              <Sparkles size={13} className="ml-auto text-faint opacity-0 group-hover:opacity-100 transition-opacity" />
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
