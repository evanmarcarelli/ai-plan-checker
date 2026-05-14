"use client";

import { useEffect, useRef } from "react";
import type { AgentLog } from "@/lib/api";
import { formatTimestamp } from "@/lib/utils";
import { Terminal } from "lucide-react";

interface Props {
  logs: AgentLog[];
  isProcessing: boolean;
  currentAgent?: string | null;
}

const AGENT_COLORS: Record<string, { dot: string; label: string; bg: string }> = {
  Surveyor: { dot: "#60a5fa", label: "text-blue-400", bg: "rgba(96,165,250,0.08)" },
  Librarian: { dot: "#a78bfa", label: "text-violet-400", bg: "rgba(167,139,250,0.08)" },
  Coordinator: { dot: "#94a3b8", label: "text-slate-400", bg: "rgba(148,163,184,0.06)" },
  "Building & Safety": { dot: "#f59e0b", label: "text-amber-400", bg: "rgba(245,158,11,0.08)" },
  "Fire Department": { dot: "#ef4444", label: "text-red-400", bg: "rgba(239,68,68,0.08)" },
  "Electrical Inspector": { dot: "#facc15", label: "text-yellow-400", bg: "rgba(250,204,21,0.08)" },
  "Plumbing Inspector": { dot: "#22d3ee", label: "text-cyan-400", bg: "rgba(34,211,238,0.08)" },
  "Mechanical Inspector": { dot: "#94a3b8", label: "text-slate-400", bg: "rgba(148,163,184,0.06)" },
  "Accessibility (ADA / CBC 11B)": { dot: "#3b82f6", label: "text-blue-500", bg: "rgba(59,130,246,0.08)" },
  "Energy & Green Building": { dot: "#10b981", label: "text-emerald-500", bg: "rgba(16,185,129,0.08)" },
  "Planning & Zoning": { dot: "#a855f7", label: "text-purple-400", bg: "rgba(168,85,247,0.08)" },
  "Public Works": { dot: "#64748b", label: "text-slate-500", bg: "rgba(100,116,139,0.08)" },
  "Environmental": { dot: "#84cc16", label: "text-lime-400", bg: "rgba(132,204,22,0.08)" },
  System: { dot: "#94a3b8", label: "text-slate-400", bg: "rgba(148,163,184,0.06)" },
};

const LEVEL_STYLES: Record<string, string> = {
  error: "text-red-400",
  warning: "text-amber-400",
  info: "text-[var(--text-secondary)]",
};

export default function AgentLogs({ logs, isProcessing, currentAgent }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Auto-scroll to bottom
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [logs]);

  return (
    <div
      className="rounded-2xl overflow-hidden flex flex-col"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        height: "calc(100vh - 220px)",
        minHeight: "480px",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)" }}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4" style={{ color: "var(--accent)" }} />
          <span className="text-sm font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
            Agent Logs
          </span>
          {isProcessing && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full animate-pulse"
              style={{ background: "rgba(79, 126, 255, 0.15)", color: "var(--accent-bright)", border: "1px solid rgba(79,126,255,0.25)" }}
            >
              LIVE
            </span>
          )}
        </div>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {logs.length} events
        </span>
      </div>

      {/* Log entries */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto p-3 space-y-0.5 font-mono text-xs"
        style={{ background: "rgba(0,0,0,0.2)" }}
      >
        {logs.length === 0 && (
          <div className="flex items-center justify-center h-full flex-col gap-3">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
            >
              <Terminal className="w-5 h-5" style={{ color: "var(--text-muted)" }} />
            </div>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              Waiting for agents…
            </p>
          </div>
        )}

        {logs.map((log, idx) => {
          const agentStyle = AGENT_COLORS[log.agent] || AGENT_COLORS.System;
          const levelStyle = LEVEL_STYLES[log.level] || LEVEL_STYLES.info;

          return (
            <div
              key={idx}
              className="log-entry flex gap-3 px-2 py-1.5 rounded-lg group hover:bg-white/[0.02] transition-colors"
            >
              {/* Timestamp */}
              <span
                className="flex-shrink-0 w-20 text-right select-none"
                style={{ color: "var(--text-muted)" }}
              >
                {formatTimestamp(log.timestamp)}
              </span>

              {/* Agent badge */}
              <span
                className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide w-20 text-center ${agentStyle.label}`}
                style={{ background: agentStyle.bg }}
              >
                {log.agent}
              </span>

              {/* Message */}
              <span className={`flex-1 leading-relaxed ${levelStyle}`}>
                {log.message}
              </span>
            </div>
          );
        })}

        {/* Blinking cursor when active */}
        {isProcessing && (
          <div className="flex gap-3 px-2 py-1.5">
            <span className="w-20" />
            <span className="w-20" />
            <span className="text-blue-400">
              <span className="inline-block w-2 h-3.5 bg-blue-400 animate-pulse ml-1" />
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
