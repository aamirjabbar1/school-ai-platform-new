/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Legacy brand scales (kept for backward compatibility with existing pages)
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        school: {
          dark: '#0f172a',
          navy: '#1e3a5f',
          blue: '#2563eb',
          light: '#f0f9ff',
        },
        // Futuristic brand gradient stops (blue → cyan → purple → teal)
        brand: {
          blue: '#2563eb',
          sky: '#38bdf8',
          cyan: '#22d3ee',
          teal: '#2dd4bf',
          purple: '#a855f7',
          violet: '#7c3aed',
          indigo: '#6366f1',
        },
        // Semantic, theme-aware tokens backed by CSS variables (see index.css).
        // Usage: bg-surface, text-ink, border-line, etc. — adapt to light/dark.
        surface: 'rgb(var(--surface) / <alpha-value>)',
        'surface-2': 'rgb(var(--surface-2) / <alpha-value>)',
        'surface-3': 'rgb(var(--surface-3) / <alpha-value>)',
        ink: 'rgb(var(--ink) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        faint: 'rgb(var(--faint) / <alpha-value>)',
        line: 'rgb(var(--line) / <alpha-value>)',
        accent: 'rgb(var(--accent) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Baloo 2"', 'Inter', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        '4xl': '2rem',
      },
      boxShadow: {
        glow: '0 0 20px -2px rgb(56 189 248 / 0.45)',
        'glow-lg': '0 0 45px -5px rgb(99 102 241 / 0.55)',
        'glow-purple': '0 0 30px -4px rgb(168 85 247 / 0.5)',
        'glass': '0 8px 32px -8px rgb(2 6 23 / 0.45)',
        'soft': '0 10px 40px -12px rgb(2 6 23 / 0.18)',
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(120deg, #2563eb 0%, #22d3ee 35%, #7c3aed 70%, #2dd4bf 100%)',
        'brand-radial': 'radial-gradient(circle at 30% 30%, #38bdf8, #2563eb 45%, #7c3aed 100%)',
        'aurora': 'radial-gradient(60% 60% at 50% 0%, rgb(37 99 235 / 0.35), transparent 70%)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '0% 50%' },
          '100%': { backgroundPosition: '200% 50%' },
        },
        'gradient-x': {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-14px)' },
        },
        bob: {
          '0%, 100%': { transform: 'translateY(0) scale(1)' },
          '50%': { transform: 'translateY(-8px) scale(1.015)' },
        },
        blob: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(30px, -40px) scale(1.1)' },
          '66%': { transform: 'translate(-25px, 25px) scale(0.95)' },
        },
        'glow-pulse': {
          '0%, 100%': { opacity: '0.55', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.06)' },
        },
        'spin-slow': {
          to: { transform: 'rotate(360deg)' },
        },
        twinkle: {
          '0%, 100%': { opacity: '0.2' },
          '50%': { opacity: '1' },
        },
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        shimmer: 'shimmer 2.5s linear infinite',
        'gradient-x': 'gradient-x 6s ease infinite',
        float: 'float 7s ease-in-out infinite',
        bob: 'bob 4s ease-in-out infinite',
        blob: 'blob 18s ease-in-out infinite',
        'glow-pulse': 'glow-pulse 3.5s ease-in-out infinite',
        'spin-slow': 'spin-slow 8s linear infinite',
        twinkle: 'twinkle 4s ease-in-out infinite',
        'fade-up': 'fade-up 0.4s ease-out both',
      },
    },
  },
  plugins: [],
};
