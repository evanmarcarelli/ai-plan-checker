"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Building2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firm, setFirm] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!accepted) {
      setError("You must agree to the Terms of Service and Privacy Policy.");
      return;
    }
    setLoading(true);
    setError(null);

    const supabase = createClient();
    const { error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { display_name: email.split("@")[0], firm_name: firm || null },
      },
    });
    if (signUpError) {
      setError(signUpError.message);
      setLoading(false);
      return;
    }

    const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
    if (signInError) {
      setError("Account created. Please check your email to confirm before signing in.");
      setLoading(false);
      return;
    }
    router.push("/dashboard");
    router.refresh();
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
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl mb-4"
               style={{ background: "#0B0E14" }}>
            <Building2 className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-3xl font-bold" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            AI Plan Checker
          </h1>
          <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
            Create your account — 1 free pre-submittal review
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl p-6 space-y-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <div>
            <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              Work email
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
          <div>
            <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              Firm / company <span style={{ color: "var(--text-muted)" }}>(optional)</span>
            </label>
            <input
              type="text"
              value={firm}
              onChange={(e) => setFirm(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              style={inputStyle}
              placeholder="Acme Architects"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              Password
            </label>
            <input
              type="password"
              required
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              style={inputStyle}
            />
            <p className="text-xs mt-1.5" style={{ color: "var(--text-muted)" }}>
              At least 10 characters with lowercase, uppercase, digit, and symbol.
            </p>
          </div>
          <label className="flex items-start gap-2 text-xs cursor-pointer"
                 style={{ color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
              className="mt-0.5 accent-blue-500"
            />
            <span>
              I agree to the{" "}
              <Link href="/terms" target="_blank" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
                Terms of Service
              </Link>{" "}
              and{" "}
              <Link href="/privacy" target="_blank" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
                Privacy Policy
              </Link>
              . I understand reports are AI-generated for preliminary review only and must be verified by a licensed professional and the AHJ.
            </span>
          </label>
          {error && (
            <p className="text-sm px-3 py-2 rounded-lg"
               style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading || !accepted}
            className="w-full font-medium py-2.5 rounded-lg transition-all disabled:opacity-60"
            style={{
              background: "#0B0E14",
              color: "#fff",
            }}
          >
            {loading ? "Creating account…" : "Create account"}
          </button>
          <p className="text-sm text-center" style={{ color: "var(--text-secondary)" }}>
            Already have an account?{" "}
            <Link href="/login" className="font-medium" style={{ color: "var(--accent-bright)" }}>
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
