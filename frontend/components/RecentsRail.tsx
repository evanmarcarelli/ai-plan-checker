"use client";

/**
 * RecentsRail — a persistent left sidebar of past plan-review reports, keyed by
 * project address. Each row carries a status dot: a blue pulse while a job is
 * running, then the compliance verdict color (green / amber / red) once it's
 * done. Click a row to reopen that report.
 */
import type { JobListItem } from "@/lib/api";
import { FileClock } from "lucide-react";

interface Props {
  jobs: JobListItem[];
  activeJobId?: string | null;
  onSelect: (id: string) => void;
  loading?: boolean;
}

// Primary label: project address, then project name, then the file name.
function jobLabel(j: JobListItem): string {
  return (
    j.plan_data?.project_address?.trim() ||
    j.plan_data?.project_name?.trim() ||
    j.filename?.replace(/\.pdf$/i, "") ||
    "Untitled report"
  );
}

// Status-then-verdict dot. Running → blue pulse. Done → score-based verdict.
function dotFor(j: JobListItem): { color: string; pulse: boolean } {
  if (j.status === "processing" || j.status === "pending")
    return { color: "var(--accent)", pulse: true };
  if (j.status === "failed") return { color: "var(--non-compliant)", pulse: false };
  const score = j.summary?.compliance_score;
  if (score == null) return { color: "var(--text-muted)", pulse: false };
  const color =
    score >= 0.8 ? "var(--compliant)" : score >= 0.5 ? "var(--needs-review)" : "var(--non-compliant)";
  return { color, pulse: false };
}

function relTime(iso: string): string {
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "";
  const s = Math.max(1, Math.floor((Date.now() - d) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function RecentsRail({ jobs, activeJobId, onSelect, loading }: Props) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 h-12 flex-shrink-0">
        <FileClock className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
        <span className="text-[11px] font-semibold tracking-[0.16em] uppercase" style={{ color: "var(--text-muted)" }}>
          Recent reports
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {loading && jobs.length === 0 && (
          <p className="px-2 py-3 text-[12px]" style={{ color: "var(--text-muted)" }}>Loading…</p>
        )}
        {!loading && jobs.length === 0 && (
          <p className="px-2 py-3 text-[12px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
            No reports yet. Your past plan reviews will show up here.
          </p>
        )}

        {jobs.map((j) => {
          const dot = dotFor(j);
          const active = j.id === activeJobId;
          const score = j.summary?.compliance_score;
          return (
            <button
              key={j.id}
              onClick={() => onSelect(j.id)}
              title={jobLabel(j)}
              className="w-full text-left flex items-start gap-2.5 px-2.5 py-2 rounded-lg mb-0.5 transition-colors"
              style={{ background: active ? "var(--bg-elevated)" : "transparent" }}
              onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--bg-elevated)"; }}
              onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
            >
              <span className="relative flex h-2 w-2 mt-1.5 flex-shrink-0">
                {dot.pulse && (
                  <span className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping"
                    style={{ background: dot.color }} />
                )}
                <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: dot.color }} />
              </span>
              <span className="flex-1 min-w-0">
                <span className="block text-[13px] font-medium truncate"
                  style={{ color: active ? "var(--text-primary)" : "var(--text-secondary)" }}>
                  {jobLabel(j)}
                </span>
                <span className="block text-[11px] truncate" style={{ color: "var(--text-muted)" }}>
                  {relTime(j.created_at)}
                  {j.status === "processing" && " · running"}
                  {j.status === "failed" && " · failed"}
                  {j.status === "completed" && score != null && ` · ${Math.round(score * 100)}`}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
