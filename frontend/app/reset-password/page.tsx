"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });
    if (error) {
      setError(error.message);
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
               style={{ background: "linear-gradient(135deg, #D4AF37, #C5A880)" }}>
            <Building2 className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-3xl font-bold" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Set a new password
          </h1>
        </div>

        <form onSubmit={handleSubmit}
              className="rounded-xl p-6 space-y-4"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <div>
            <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              New password
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
          <div>
            <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              Confirm password
            </label>
            <input
              type="password"
              required
              minLength={10}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              style={inputStyle}
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
            style={{ background: "linear-gradient(135deg, #D4AF37, #E5C158)", color: "#fff" }}
          >
            {loading ? "Saving…" : "Save password"}
          </button>
        </form>
      </div>
    </div>
  );
}
