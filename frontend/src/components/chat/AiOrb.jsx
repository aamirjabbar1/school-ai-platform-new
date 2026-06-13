import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';

/**
 * The LSS AI tutor's "face" — a glowing gradient orb. Reused at multiple sizes:
 * a large floating hero orb, a small assistant avatar, and the thinking state.
 *
 * props:
 *   size   - diameter in px
 *   active - amps up the glow/motion (e.g. while thinking)
 *   float  - gentle bobbing (hero)
 *   icon   - show the sparkle glyph in the center
 */
export default function AiOrb({ size = 40, active = false, float = false, icon = true, className = '' }) {
  return (
    <motion.div
      className={`relative shrink-0 ${float ? 'animate-float' : ''} ${className}`}
      style={{ width: size, height: size }}
      animate={active ? { scale: [1, 1.04, 1] } : {}}
      transition={active ? { duration: 1.6, repeat: Infinity, ease: 'easeInOut' } : {}}
    >
      {/* outer glow halo */}
      <span
        className={`absolute -inset-1 rounded-full bg-brand-radial blur-md ${active ? 'opacity-90 animate-glow-pulse' : 'opacity-60'}`}
      />
      {/* orbiting ring while active */}
      {active && (
        <span className="absolute -inset-1.5 rounded-full border border-brand-cyan/40 animate-spin-slow" />
      )}
      {/* core sphere */}
      <span className="absolute inset-0 rounded-full bg-brand-radial shadow-glow overflow-hidden">
        <span className="absolute top-[12%] left-[16%] w-1/3 h-1/3 rounded-full bg-white/55 blur-[2px]" />
      </span>
      {icon && (
        <span className="absolute inset-0 flex items-center justify-center text-white">
          <Sparkles size={size * 0.42} className={active ? 'animate-spin-slow' : ''} />
        </span>
      )}
    </motion.div>
  );
}
