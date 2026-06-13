import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const ThemeContext = createContext(null);

const STORAGE_KEY = 'lss-theme';
const MODES = ['dark', 'light', 'auto'];

function systemPrefersDark() {
  return typeof window !== 'undefined'
    && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function resolveIsDark(mode) {
  if (mode === 'dark') return true;
  if (mode === 'light') return false;
  return systemPrefersDark();
}

export function ThemeProvider({ children }) {
  const [mode, setMode] = useState(() => {
    const saved = typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY);
    return MODES.includes(saved) ? saved : 'dark';
  });
  const [isDark, setIsDark] = useState(() => resolveIsDark(
    (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) || 'dark'
  ));

  // Apply the resolved theme to <html> and persist the chosen mode.
  useEffect(() => {
    const dark = resolveIsDark(mode);
    setIsDark(dark);
    document.documentElement.classList.toggle('dark', dark);
    try { localStorage.setItem(STORAGE_KEY, mode); } catch { /* ignore */ }
  }, [mode]);

  // When in "auto", follow live OS changes.
  useEffect(() => {
    if (mode !== 'auto') return undefined;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      const dark = mq.matches;
      setIsDark(dark);
      document.documentElement.classList.toggle('dark', dark);
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [mode]);

  // Cycle dark → light → auto → dark
  const cycleMode = useCallback(() => {
    setMode((m) => MODES[(MODES.indexOf(m) + 1) % MODES.length]);
  }, []);

  const toggle = useCallback(() => {
    setMode((m) => (resolveIsDark(m) ? 'light' : 'dark'));
  }, []);

  return (
    <ThemeContext.Provider value={{ mode, isDark, setMode, cycleMode, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
