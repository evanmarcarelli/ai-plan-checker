"use client";

import { useState } from "react";
import Link from "next/link";
import BrandMark from "@/components/BrandMark";
import { createClient } from "@/lib/supabase/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const supabase = createClient();
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    if (error) {
      setError(error.message);
      setLoading(false);
      return;
    }
    setSent(true);
    setLoading(false);
  }

  const inputStyle: React.CSSProperties = {
    background: "var(--bg-elevated)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg)" }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <BrandMark size={44} style={{ color: "var(--text-primary)" }} />
          </div>
          <h1 className="text-3xl font-bold" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Reset password
          </h1>
          <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
            We&apos;ll email you a link to set a new one.
          </p>
        </div>

        <div className="rounded-xl p-6 space-y-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          {sent ? (
            <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
              If an account with <strong style={{ color: "var(--text-primary)" }}>{email}</strong> exists, a password reset
              email is on its way. Check your inbox (and spam folder).
              <div className="mt-4">
                <Link href="/login" className="font-medium" style={{ color: "var(--accent-bright)" }}>
                  Back to sign in
                </Link>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
                  Email
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  style={inputStyle}
                  placeholder="you@firm.com"
                />
              </div>
              {error && (
                <p className="text-sm px-3 py-2 rounded-lg"
                   style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
                  {error}
                </p>
              )}
              <button
                type="submit"
                disabled={loading}
                className="w-full font-medium py-2.5 rounded-lg transition-all disabled:opacity-60"
                style={{ background: "var(--ink)", color: "#fff" }}
              >
                {loading ? "Sending…" : "Send reset link"}
              </button>
              <p className="text-sm text-center" style={{ color: "var(--text-secondary)" }}>
                <Link href="/login" className="font-medium" style={{ color: "var(--accent-bright)" }}>
                  Back to sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
