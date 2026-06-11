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

// Unified subdued palette — every agent shares the same chip styling so the
// log reads as one quiet stream of events rather than a confetti of colors.
// Severity is conveyed by the *level* (error/warning), not the agent name.
const AGENT_CHIP_BG = "var(--bg-elevated)";
const AGENT_CHIP_FG = "var(--text-secondary)";

const LEVEL_STYLES: Record<string, string> = {
  error: "text-[var(--non-compliant)]",
  warning: "text-[var(--needs-review)]",
  info: "text-[var(--text-secondary)]",
};

export default function AgentLogs({ logs, isProcessing, currentAgent }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Whether the view is "stuck" to the newest log. Starts true so a fresh run
  // streams live; flips off the moment the user scrolls up to read history, and
  // back on when they scroll near the bottom again.
  const pinnedToBottomRef = useRef(true);

  // Update the pinned flag whenever the user (or a programmatic jump) scrolls
  // this container. Threshold gives a little slack so being "almost" at the
  // bottom still counts as following.
  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    pinnedToBottomRef.current = distanceFromBottom < 60;
  }

  useEffect(() => {
    // On each new log, follow the tail ONLY if pinned, and scroll ONLY this
    // container — never via scrollIntoView, which would scroll every ancestor
    // and yank the whole dashboard down to the log on every agent action. When
    // the user has scrolled up, we leave their position alone so they can
    // freely watch the race track and read the stream at their own pace.
    if (!pinnedToBottomRef.current) return;
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <div
      className="rounded-xl overflow-hidden flex flex-col"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        height: "calc(100vh - 220px)",
        minHeight: "480px",
      }}
    >
      {/* Header — editorial label, not a heavy chrome bar */}
      <div
        className="flex items-center justify-between px-5 py-3 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4" style={{ color: "var(--accent)" }} />
          <span
            className="text-[11px] font-semibold tracking-[0.18em] uppercase"
            style={{ color: "var(--text-muted)" }}
          >
            Agent logs
          </span>
          {isProcessing && (
            <span
              className="text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded-md"
              style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
            >
              LIVE
            </span>
          )}
        </div>
        <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
          {logs.length} events
        </span>
      </div>

      {/* Log entries — light surface, monospace stream */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 space-y-0.5 font-mono text-[12px]"
        style={{ background: "var(--bg-elevated)" }}
      >
        {logs.length === 0 && (
          <div className="flex items-center justify-center h-full flex-col gap-3">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <Terminal className="w-5 h-5" style={{ color: "var(--text-muted)" }} />
            </div>
            <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
              Waiting for agents…
            </p>
          </div>
        )}

        {logs.map((log, idx) => {
          const levelStyle = LEVEL_STYLES[log.level] || LEVEL_STYLES.info;
          return (
            <div
              key={idx}
              className="log-entry flex gap-3 px-2 py-1.5 rounded-md group hover:bg-black/[0.02] transition-colors"
            >
              <span
                className="flex-shrink-0 w-20 text-right select-none"
                style={{ color: "var(--text-muted)" }}
              >
                {formatTimestamp(log.timestamp)}
              </span>
              <span
                className="flex-shrink-0 px-1.5 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider w-24 text-center truncate"
                style={{ background: AGENT_CHIP_BG, color: AGENT_CHIP_FG }}
              >
                {log.agent}
              </span>
              <span className={`flex-1 leading-relaxed ${levelStyle}`}>
                {log.message}
              </span>
            </div>
          );
        })}

        {/* Blinking cursor when active — uses brand accent */}
        {isProcessing && (
          <div className="flex gap-3 px-2 py-1.5">
            <span className="w-20" />
            <span className="w-24" />
            <span>
              <span
                className="inline-block w-2 h-3.5 animate-pulse ml-1"
                style={{ background: "var(--accent)" }}
              />
            </span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
