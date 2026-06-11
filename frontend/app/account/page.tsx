"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, Download, Trash2, Loader2, AlertTriangle, Sun, Moon, Monitor } from "lucide-react";
import { getMe, exportMyData, deleteMyAccount, type UserProfile } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { useTheme, type ThemePref } from "@/components/ThemeProvider";

const THEME_OPTIONS: { value: ThemePref; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "system", label: "System", Icon: Monitor },
  { value: "dark", label: "Dark", Icon: Moon },
];

export default function AccountPage() {
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMe().then(setProfile).catch(() => setProfile(null));
  }, []);

  async function handleExport() {
    setExporting(true);
    setError(null);
    try {
      await exportMyData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleDelete() {
    if (confirmText !== "DELETE") {
      setError('Type DELETE to confirm.');
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await deleteMyAccount();
      const sb = createClient();
      await sb.auth.signOut();
      router.push("/signup");
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  }

  return (
    <div className="min-h-screen px-6 py-12" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto">
        <button
          onClick={() => router.push("/dashboard")}
          className="inline-flex items-center gap-1.5 text-sm mb-8 hover:underline"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft className="w-4 h-4" />
          Back to dashboard
        </button>

        <h1 className="text-3xl font-bold mb-2"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
          Account
        </h1>
        <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>
          Manage your data and account.
        </p>

        {/* Profile card */}
        <div className="rounded-xl p-6 mb-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <div className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Profile
          </div>
          <dl className="text-sm space-y-2">
            <div className="flex justify-between">
              <dt style={{ color: "var(--text-muted)" }}>Email</dt>
              <dd style={{ color: "var(--text-secondary)" }}>{profile?.email || "—"}</dd>
            </div>
            <div className="flex justify-between">
              <dt style={{ color: "var(--text-muted)" }}>Plan</dt>
              <dd style={{ color: "var(--text-secondary)" }}>
                {profile?.plan_tier ? profile.plan_tier.charAt(0).toUpperCase() + profile.plan_tier.slice(1) : "Free"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt style={{ color: "var(--text-muted)" }}>Credits remaining</dt>
              <dd style={{ color: "var(--text-secondary)" }}>{profile?.credits_remaining ?? 0}</dd>
            </div>
          </dl>
        </div>

        {/* Appearance */}
        <div className="rounded-xl p-6 mb-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <div className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Appearance
          </div>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            Choose how Architechtura looks. &ldquo;System&rdquo; follows your device&apos;s light or dark setting.
          </p>
          <div
            role="radiogroup"
            aria-label="Theme"
            className="inline-flex rounded-lg p-1 gap-1"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
          >
            {THEME_OPTIONS.map(({ value, label, Icon }) => {
              const active = theme === value;
              return (
                <button
                  key={value}
                  role="radio"
                  aria-checked={active}
                  onClick={() => setTheme(value)}
                  className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors"
                  style={{
                    background: active ? "var(--bg-card)" : "transparent",
                    color: active ? "var(--text-primary)" : "var(--text-secondary)",
                    boxShadow: active ? "0 1px 2px rgba(11,14,20,0.10)" : "none",
                  }}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Data export */}
        <div className="rounded-xl p-6 mb-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <div className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Export your data
          </div>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            Download a JSON file containing everything we store about you — profile, jobs, findings, agent logs.
          </p>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-60"
            style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Download my data
          </button>
        </div>

        {/* Danger zone */}
        <div className="rounded-xl p-6"
             style={{ background: "var(--bg-card)", border: "1px solid rgba(239,68,68,0.3)" }}>
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4" style={{ color: "var(--non-compliant)" }} />
            <div className="text-sm font-semibold" style={{ color: "var(--non-compliant)", fontFamily: "var(--font-display)" }}>
              Delete account
            </div>
          </div>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            Permanently delete your account, all uploaded plans, findings, and agent logs. This cannot be undone.
            If you have an active subscription, cancel it first via the Pricing page.
          </p>
          <div className="space-y-3">
            <label className="text-xs block" style={{ color: "var(--text-muted)" }}>
              Type <code style={{ color: "var(--non-compliant)" }}>DELETE</code> to confirm:
            </label>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="w-48 px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
              }}
            />
            <div>
              <button
                onClick={handleDelete}
                disabled={deleting || confirmText !== "DELETE"}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-40"
                style={{ background: "var(--non-compliant)", color: "#fff" }}
              >
                {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                Permanently delete my account
              </button>
            </div>
          </div>
          {error && (
            <p className="text-sm mt-4 px-3 py-2 rounded-lg"
               style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
