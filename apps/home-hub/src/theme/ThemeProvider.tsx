'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import { OlinThemeId, DEFAULT_THEME_ID } from './types';
import { OLIN_THEMES } from './registry';

const THEME_STORAGE_KEY = 'olin.appearance.theme.v1';

interface ThemeContextValue {
  activeTheme: OlinThemeId;
  setTheme: (themeId: OlinThemeId) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  activeTheme: DEFAULT_THEME_ID,
  setTheme: () => {}
});

export const useOlinTheme = () => useContext(ThemeContext);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [activeTheme, setActiveThemeState] = useState<OlinThemeId>(DEFAULT_THEME_ID);
  
  // Hydrate from localStorage once mounted
  useEffect(() => {
    try {
      const stored = localStorage.getItem(THEME_STORAGE_KEY) as OlinThemeId;
      if (stored && OLIN_THEMES[stored]) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setActiveThemeState(stored);
        document.documentElement.setAttribute('data-olin-theme', stored);
      }
    } catch {
      // Ignore
    }
  }, []);

  const setTheme = (themeId: OlinThemeId) => {
    if (OLIN_THEMES[themeId]) {
      setActiveThemeState(themeId);
      document.documentElement.setAttribute('data-olin-theme', themeId);
      try {
        localStorage.setItem(THEME_STORAGE_KEY, themeId);
      } catch {
        // Ignore
      }
    }
  };

  return (
    <ThemeContext.Provider value={{ activeTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
