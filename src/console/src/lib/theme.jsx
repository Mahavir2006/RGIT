import { createContext, useContext, useEffect, useMemo, useState } from 'react';

const ThemeContext = createContext(null);
const STORAGE_KEY = 'urban-sentinel-theme';

// Light is the default; dark is available and persists across reloads.
export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) || 'light'; } catch { return 'light'; }
  });

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    root.style.colorScheme = theme;
    try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* storage may be blocked */ }
  }, [theme]);

  const value = useMemo(() => ({
    theme,
    isDark: theme === 'dark',
    toggle: () => setTheme(current => (current === 'dark' ? 'light' : 'dark')),
    setTheme
  }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useTheme must be used inside ThemeProvider');
  return context;
}

// Reads a resolved design token off the document so canvas renderers stay in step with
// the CSS theme instead of carrying their own hard-coded palette.
export function readToken(name, fallback) {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!value) return fallback;
  const probe = value.startsWith('#') ? value : null;
  return probe ? parseInt(probe.slice(1), 16) : fallback;
}

export function palette() {
  return {
    bg: readToken('--bg', 0xffffff),
    surface: readToken('--surface', 0xffffff),
    surface2: readToken('--surface-2', 0xfafafa),
    surface3: readToken('--surface-3', 0xf4f4f5),
    border: readToken('--border', 0xe8e8ea),
    borderStrong: readToken('--border-strong', 0xd4d4d8),
    fgSubtle: readToken('--fg-subtle', 0x8e8e96),
    accent: readToken('--accent', 0x4f46e5),
    healthy: readToken('--healthy', 0x3f7d58),
    degraded: readToken('--degraded', 0x9a6b1f),
    stale: readToken('--stale', 0x8a6a2f),
    critical: readToken('--critical', 0xb4373c),
    info: readToken('--info', 0x4a5568)
  };
}