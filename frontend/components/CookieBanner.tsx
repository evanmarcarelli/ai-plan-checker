"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Cookie, X } from "lucide-react";

const STORAGE_KEY = "up2code_cookie_consent_v1";

type Consent = "accepted" | "rejected" | null;

export function getCookieConsent(): Consent {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "accepted" || v === "rejected" ? v : null;
  } catch {
    return null;
  }
}

export default function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (getCookieConsent() === null) setVisible(true);
  }, []);

  function setConsent(value: "accepted" | "rejected") {
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // localStorage unavailable — silently fail
    }
    // Tell the rest of the app it can (or can't) load analytics now
    window.dispatchEvent(new CustomEvent("cookie-consent", { detail: value }));
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      className="fixed bottom-4 left-4 right-4 sm:left-auto sm:right-6 sm:bottom-6 sm:max-w-md z-50 rounded-xl p-4 shadow-2xl"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border-bright)",
      }}
      role="dialog"
      aria-label="Cookie preferences"
    >
      <div className="flex items-start gap-3">
        <Cookie className="w-5 h-5 flex-shrink-0 mt-0.5" style={{ color: "var(--accent-bright)" }} />
        <div className="flex-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>We use cookies.</strong>{" "}
          We use essential cookies for authentication and security. With your permission we also use
          analytics cookies to understand how the site is used. See our{" "}
          <Link href="/privacy" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
            Privacy Policy
          </Link>
          .
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => setConsent("accepted")}
              className="px-3 py-1.5 rounded-lg text-xs font-medium"
              style={{ background: "linear-gradient(135deg, #D4AF37, #E5C158)", color: "#fff" }}
            >
              Accept all
            </button>
            <button
              onClick={() => setConsent("rejected")}
              className="px-3 py-1.5 rounded-lg text-xs font-medium"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
            >
              Essential only
            </button>
          </div>
        </div>
        <button
          onClick={() => setConsent("rejected")}
          aria-label="Dismiss"
          className="p-1 rounded hover:bg-white/5 transition-colors"
          style={{ color: "var(--text-muted)" }}
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
