"use client";

// Guest-accessible report view.
//
// This is the VIRAL surface — every shared link lands a contractor or
// inspector here. They see the report, the AI assistant, and one prominent
// "Run your own review free" CTA. No signup required.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, Building2, CheckCircle2, Sparkles } from "lucide-react";
import { fetchSharedReport } from "@/lib/api";
import { FindingComments } from "@/components/FindingComments";
import { ChatWidget } from "@/components/ChatWidget";

type SharedReport = Awaited<ReturnType<typeof fetchSharedReport>>;

export default function SharedReportPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [data, setData] = useState<SharedReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guestName, setGuestName] = useState<string>("");
  const [askedName, setAskedName] = useState(false);

  useEffect(() => {
    if (!token) return;
    fetchSharedReport(token)
      .then((d) => setData(d))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, [token]);

  // First-time visitors: ask for a display name so their comments aren't anonymous.
  // Cached per-browser so they don't get re-prompted.
  useEffect(() => {
    if (!data) return;
    const cached = localStorage.getItem("up2code:guest_name");
    if (cached) {
      setGuestName(cached);
      setAskedName(true);
      return;
    }
    if (data.share.invited_name) {
      setGuestName(data.share.invited_name);
      setAskedName(true);
      localStorage.setItem("up2code:guest_name", data.share.invited_name);
    }
  }, [data]);

  function saveGuestName(name: string) {
    const clean = name.trim().slice(0, 80);
    if (!clean) return;
    setGuestName(clean);
    localStorage.setItem("up2code:guest_name", clean);
    setAskedName(true);
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg)" }}>
        <div className="max-w-md text-center">
          <AlertTriangle className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--non-compliant)" }} />
          <h1 className="text-xl font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
            This link isn't working
          </h1>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>{error}</p>
          <Link
            href="/"
            className="inline-block px-4 py-2 rounded-lg font-medium"
            style={{ background: "#0B0E14", color: "#fff" }}
          >
            Try PhiCodes AI free
          </Link>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg)" }}>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading shared report…</p>
      </div>
    );
  }

  const { share, report, findings } = data;
  const summary = report.summary as { compliance_score?: number; total_checks?: number; critical_issues?: number; high_issues?: number } | undefined;
  const score = summary?.compliance_score != null ? Math.round(summary.compliance_score * 100) : null;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      {/* ── Branded top bar (viral CTA) ─────────────────── */}
      <header
        className="px-6 py-3 border-b flex items-center justify-between"
        style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
      >
        <div className="flex items-center gap-2">
          <div
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg"
            style={{ background: "#0B0E14" }}
          >
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              PhiCodes AI
            </div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              Shared compliance review · {share.role}
            </div>
          </div>
        </div>
        <Link
          href="/"
          className="text-xs font-medium px-3 py-2 rounded-lg flex items-center gap-1.5"
          style={{ background: "#0B0E14", color: "#fff" }}
        >
          <Sparkles className="w-3.5 h-3.5" />
          Run your own review — free
        </Link>
      </header>

      {!askedName && (
        <GuestNamePrompt onSave={saveGuestName} />
      )}

      <main className="max-w-5xl mx-auto px-4 py-6">
        {/* Report header */}
        <div className="mb-6">
          <p className="text-xs uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
            Compliance review
          </p>
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>
            {report.filename || "Plan set"}
          </h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {[
              report.jurisdiction?.city,
              report.jurisdiction?.state,
            ].filter(Boolean).join(", ") || "Jurisdiction not detected"}
            {report.completed_at && ` · completed ${new Date(report.completed_at).toLocaleDateString()}`}
          </p>
        </div>

        {/* Summary */}
        {summary && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            <Stat label="Score" value={score != null ? `${score}%` : "—"} />
            <Stat label="Checks" value={summary.total_checks ?? "—"} />
            <Stat label="Critical" value={summary.critical_issues ?? 0} accent={summary.critical_issues ? "danger" : undefined} />
            <Stat label="High" value={summary.high_issues ?? 0} accent={summary.high_issues ? "warn" : undefined} />
          </div>
        )}

        {/* Findings */}
        <div className="space-y-3">
          {findings.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              The report has no individual findings to display yet.
            </p>
          ) : (
            findings.map((f) => (
              <FindingCard
                key={String(f.id)}
                finding={f}
                shareToken={token}
                guestName={guestName}
                canComment={share.role === "commenter" && !!guestName}
                jobId={share.job_id}
              />
            ))
          )}
        </div>
      </main>

      {/* Floating AI assistant */}
      <ChatWidget jobId={share.job_id} shareToken={token} guestName={guestName} />

      <footer className="px-6 py-6 text-center text-xs" style={{ color: "var(--text-muted)" }}>
        Powered by{" "}
        <Link href="/" className="font-medium" style={{ color: "var(--accent-bright)" }}>
          PhiCodes AI
        </Link>
        . Reports are AI-generated for preliminary review only and must be verified by a licensed professional and the AHJ.
      </footer>
    </div>
  );
}

// ─────────────────────── helpers ───────────────────────

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent?: "danger" | "warn";
}) {
  const color =
    accent === "danger" ? "var(--non-compliant)" :
    accent === "warn" ? "var(--accent)" :
    "var(--text-primary)";
  return (
    <div className="rounded-xl p-3 text-center" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <div className="text-xs uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
        {label}
      </div>
      <div className="text-xl font-semibold" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function FindingCard({
  finding,
  jobId,
  shareToken,
  guestName,
  canComment,
}: {
  finding: Record<string, unknown>;
  jobId: string;
  shareToken: string;
  guestName: string;
  canComment: boolean;
}) {
  const status = String(finding.status || "");
  const severity = String(finding.severity || "medium");
  const sevColor =
    severity === "critical" ? "var(--non-compliant)" :
    severity === "high" ? "#B45309" :
    "var(--text-muted)";
  const statusIcon =
    status === "compliant" ? <CheckCircle2 className="w-4 h-4" style={{ color: "var(--compliant)" }} /> :
    <AlertTriangle className="w-4 h-4" style={{ color: sevColor }} />;
  return (
    <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5">{statusIcon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-baseline gap-2 mb-1">
            <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              {String(finding.code_id || finding.code_section || "—")}
            </span>
            <span className="text-xs uppercase tracking-wide font-medium" style={{ color: sevColor }}>
              {severity}
            </span>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              · {String(finding.department || "")}
            </span>
          </div>
          <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            {String(finding.description || "")}
          </p>
          {finding.recommendation ? (
            <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--text-primary)" }}>
              <strong>Recommendation:</strong> {String(finding.recommendation)}
            </p>
          ) : null}
        </div>
      </div>
      <FindingComments
        findingRef={String(finding.code_id || finding.code_section || finding.id)}
        jobId={jobId}
        shareToken={shareToken}
        guestName={guestName}
        canComment={canComment}
      />
    </div>
  );
}

function GuestNamePrompt({ onSave }: { onSave: (name: string) => void }) {
  const [v, setV] = useState("");
  return (
    <div
      className="border-b px-6 py-3"
      style={{ background: "var(--bg-elevated)", borderColor: "var(--border)" }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSave(v);
        }}
        className="max-w-3xl mx-auto flex items-center gap-3"
      >
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Your name (so your comments aren't anonymous):
        </span>
        <input
          type="text"
          value={v}
          onChange={(e) => setV(e.target.value)}
          placeholder="e.g. Jamie · Acme Inspections"
          className="flex-1 px-3 py-1.5 rounded-md text-sm focus:outline-none"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        />
        <button
          type="submit"
          className="text-sm font-medium px-3 py-1.5 rounded-md"
          style={{ background: "#0B0E14", color: "#fff" }}
        >
          Continue
        </button>
      </form>
    </div>
  );
}
