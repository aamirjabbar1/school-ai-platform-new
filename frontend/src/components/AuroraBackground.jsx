import { useMemo } from 'react';

/**
 * Fixed, full-screen animated backdrop: drifting gradient "aurora" blobs plus a
 * subtle twinkling star field. Theme-aware via CSS variables (--aurora-*,
 * --star-color) and GPU-light (transform/opacity only). Reduced-motion users
 * get a calm, static version via the global prefers-reduced-motion guard.
 *
 * Rendered once behind the app; pointer-events disabled so it never blocks UI.
 */
export default function AuroraBackground({ stars = 36 }) {
  const dots = useMemo(
    () =>
      Array.from({ length: stars }, (_, i) => ({
        id: i,
        top: Math.random() * 100,
        left: Math.random() * 100,
        size: Math.random() * 2 + 1,
        delay: Math.random() * 5,
        duration: Math.random() * 3 + 3,
      })),
    [stars]
  );

  return (
    <div aria-hidden className="fixed inset-0 -z-10 overflow-hidden pointer-events-none">
      {/* Drifting gradient blobs */}
      <div
        className="absolute -top-1/4 -left-1/4 h-[55vmax] w-[55vmax] rounded-full blur-3xl animate-blob"
        style={{ background: 'var(--aurora-1)' }}
      />
      <div
        className="absolute top-1/3 -right-1/4 h-[50vmax] w-[50vmax] rounded-full blur-3xl animate-blob"
        style={{ background: 'var(--aurora-3)', animationDelay: '4s' }}
      />
      <div
        className="absolute -bottom-1/4 left-1/4 h-[48vmax] w-[48vmax] rounded-full blur-3xl animate-blob"
        style={{ background: 'var(--aurora-2)', animationDelay: '8s' }}
      />
      <div
        className="absolute top-1/4 left-1/3 h-[40vmax] w-[40vmax] rounded-full blur-3xl animate-blob"
        style={{ background: 'var(--aurora-4)', animationDelay: '12s' }}
      />

      {/* Twinkling stars */}
      {dots.map((d) => (
        <span
          key={d.id}
          className="absolute rounded-full animate-twinkle"
          style={{
            top: `${d.top}%`,
            left: `${d.left}%`,
            width: `${d.size}px`,
            height: `${d.size}px`,
            background: 'var(--star-color)',
            animationDelay: `${d.delay}s`,
            animationDuration: `${d.duration}s`,
          }}
        />
      ))}

      {/* Subtle grid + vignette for depth */}
      <div
        className="absolute inset-0 opacity-[0.04] dark:opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgb(var(--accent)) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--accent)) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
          maskImage: 'radial-gradient(circle at 50% 40%, black, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(circle at 50% 40%, black, transparent 75%)',
        }}
      />
    </div>
  );
}
