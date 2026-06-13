"use client";

/**
 * RecentsRail — a compact, Claude-style left sidebar of past plan reviews, each
 * labeled by its project address. A small status dot carries the verdict: a blue
 * pulse while a job is running, then the compliance color (green / amber / red).
 * Click a row to reopen that report; "New check" resets to the upload view.
 */
import type { JobListItem } from "@/lib/api";
import { Plus } from "lucide-react";

interface Props {
  jobs: JobListItem[];
  activeJobId?: string | null;
  onSelect: (id: string) => void;
  onNew?: () => void;
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

// Status-then-verdict dot. Running -> blue pulse. Done -> score-based verdict.
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

export default function RecentsRail({ jobs, activeJobId, onSelect, onNew, loading }: Props) {
  return (
    <div className="flex flex-col h-full">
      {/* New check — mirrors Claude's "New chat" affordance */}
      {onNew && (
        <div className="px-2 pt-3 pb-1 flex-shrink-0">
          <button
            onClick={onNew}
            className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[13px] font-medium transition-colors"
            style={{ color: "var(--text-primary)", background: "transparent" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-elevated)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <Plus className="w-4 h-4 flex-shrink-0" strokeWidth={2} style={{ color: "var(--text-muted)" }} />
            New check
          </button>
        </div>
      )}

      <div className="px-3.5 pt-2 pb-1.5 flex-shrink-0">
        <span className="text-[11px] font-medium" style={{ color: "var(--text-muted)" }}>
          Recents
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {loading && jobs.length === 0 && (
          <p className="px-2.5 py-1.5 text-[12px]" style={{ color: "var(--text-muted)" }}>Loading…</p>
        )}
        {!loading && jobs.length === 0 && (
          <p className="px-2.5 py-1.5 text-[12px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
            No reports yet.
          </p>
        )}

        {jobs.map((j) => {
          const dot = dotFor(j);
          const active = j.id === activeJobId;
          return (
            <button
              key={j.id}
              onClick={() => onSelect(j.id)}
              title={jobLabel(j)}
              className="w-full text-left flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg transition-colors"
              style={{ background: active ? "var(--bg-elevated)" : "transparent" }}
              onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--bg-elevated)"; }}
              onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
            >
              <span className="relative flex h-1.5 w-1.5 flex-shrink-0">
                {dot.pulse && (
                  <span className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping"
                    style={{ background: dot.color }} />
                )}
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full" style={{ background: dot.color }} />
              </span>
              <span className="flex-1 min-w-0 truncate text-[13px]"
                style={{ color: active ? "var(--text-primary)" : "var(--text-secondary)" }}>
                {jobLabel(j)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
