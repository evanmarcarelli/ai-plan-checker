"use client";

// App-wide theme controller. Three user-facing preferences — "light", "dark",
// and "system" (follow the OS). The *resolved* theme (light|dark) is written to
// <html data-theme="…">, which flips the CSS variable palette in globals.css.
//
// First paint is handled by the inline no-flash script in the root layout
// (app/layout.tsx) so there's never a light flash before this provider mounts.
// This provider keeps localStorage + the data-theme attribute in sync after
// mount and re-resolves live when the OS scheme changes while in "system" mode.

import { createContext, useContext, useEffect, useState, useCallback } from "react";

export type ThemePref = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";

// Inline script string, run before paint in <head>. Kept here so the resolution
// logic lives in one place and can't drift from the provider's.
export const themeInitScript = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}')||'system';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');}catch(e){}})();`;

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolve(pref: ThemePref): ResolvedTheme {
  if (pref === "system") return systemPrefersDark() ? "dark" : "light";
  return pref;
}

function apply(resolved: ResolvedTheme) {
  document.documentElement.setAttribute("data-theme", resolved);
}

type ThemeContextValue = {
  /** The user's stored preference: light | dark | system. */
  theme: ThemePref;
  /** The actual theme in effect right now (system resolved to light/dark). */
  resolvedTheme: ResolvedTheme;
  setTheme: (pref: ThemePref) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemePref>("system");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");

  // Hydrate from storage on mount (the inline script already set the attribute).
  useEffect(() => {
    let stored: ThemePref = "system";
    try {
      const v = localStorage.getItem(THEME_STORAGE_KEY) as ThemePref | null;
      if (v === "light" || v === "dark" || v === "system") stored = v;
    } catch {}
    setThemeState(stored);
    setResolvedTheme(resolve(stored));
  }, []);

  // While in "system" mode, track live OS scheme changes.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const r = systemPrefersDark() ? "dark" : "light";
      apply(r);
      setResolvedTheme(r);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((pref: ThemePref) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, pref);
    } catch {}
    const r = resolve(pref);
    apply(r);
    setThemeState(pref);
    setResolvedTheme(r);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>");
  return ctx;
}
