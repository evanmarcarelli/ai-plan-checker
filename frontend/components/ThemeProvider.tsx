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
import { usePathname } from "next/navigation";

export type ThemePref = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";

// The light/dark preference only applies to the signed-in product surface.
// Marketing, auth, legal, and shared-report pages are ALWAYS light — the
// brand look — regardless of the stored preference or OS scheme.
export const THEMED_PREFIXES = ["/dashboard", "/account", "/billing"];

export function isThemedPath(pathname: string): boolean {
  return THEMED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

// Inline script string, run before paint in <head>. Kept here so the resolution
// logic lives in one place and can't drift from the provider's.
// Default is LIGHT for everyone — only an explicit "dark" or "system" choice
// (stored by the account Appearance control) deviates from it, and only on
// the product routes listed in THEMED_PREFIXES.
export const themeInitScript = `(function(){try{var p=location.pathname;var themed=${JSON.stringify(
  THEMED_PREFIXES
)}.some(function(x){return p===x||p.indexOf(x+'/')===0;});var t=localStorage.getItem('${THEME_STORAGE_KEY}')||'light';var d=themed&&(t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches));document.documentElement.setAttribute('data-theme',d?'dark':'light');}catch(e){}})();`;

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
  const [theme, setThemeState] = useState<ThemePref>("light");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");
  const pathname = usePathname();
  const themed = isThemedPath(pathname ?? "/");

  // Hydrate from storage on mount (the inline script already set the attribute).
  useEffect(() => {
    let stored: ThemePref = "light";
    try {
      const v = localStorage.getItem(THEME_STORAGE_KEY) as ThemePref | null;
      if (v === "light" || v === "dark" || v === "system") stored = v;
    } catch {}
    setThemeState(stored);
    setResolvedTheme(resolve(stored));
  }, []);

  // Keep the attribute in sync with the resolved theme AND the route. The
  // inline script only runs on full page loads — client-side navigation
  // between product and marketing pages re-applies here, so a dark dashboard
  // can never leak its theme onto the always-light marketing/auth pages.
  useEffect(() => {
    apply(themed ? resolvedTheme : "light");
  }, [themed, resolvedTheme]);

  // While in "system" mode, track live OS scheme changes.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      setResolvedTheme(systemPrefersDark() ? "dark" : "light");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((pref: ThemePref) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, pref);
    } catch {}
    setThemeState(pref);
    setResolvedTheme(resolve(pref));
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
