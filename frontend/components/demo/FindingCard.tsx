"use client";

import { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import type { DemoFinding } from "./scenarios";

interface Props {
  finding: DemoFinding;
  defaultOpen?: boolean;
}

const STATUS_DOT: Record<DemoFinding["status"], string> = {
  fail: "var(--non-compliant)",
  warn: "var(--needs-review)",
  pass: "var(--compliant)",
  info: "var(--text-muted)",
};

const STATUS_BG: Record<DemoFinding["status"], string> = {
  fail: "var(--non-compliant-bg)",
  warn: "var(--needs-review-bg)",
  pass: "var(--compliant-bg)",
  info: "var(--na-bg)",
};

const SEV_COLOR: Record<DemoFinding["severity"], string> = {
  critical: "var(--non-compliant)",
  high: "var(--needs-review)",
  medium: "var(--text-muted)",
  low: "var(--text-muted)",
};

export default function FindingCard({ finding, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const dot = STATUS_DOT[finding.status];
  const bg = STATUS_BG[finding.status];
  const sev = SEV_COLOR[finding.severity];

  return (
    <div
      className="finding-card rounded-lg overflow-hidden"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full text-left px-4 py-3 flex items-start gap-3"
      >
        <span
          className="mt-1.5 w-2 h-2 rounded-full flex-shrink-0"
          style={{ background: dot }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-baseline gap-2 mb-1">
            <span
              className="text-xs font-mono font-semibold"
              style={{ color: "var(--accent-bright)" }}
            >
              {finding.code_ref}
            </span>
            <span
              className="text-[10px] uppercase tracking-wide font-semibold"
              style={{ color: sev }}
            >
              {finding.severity}
            </span>
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              · {finding.discipline}
            </span>
            <span
              className="text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded ml-auto"
              style={{ background: bg, color: dot }}
            >
              {finding.status}
            </span>
          </div>
          <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            {finding.summary}
          </p>
        </div>
        <ChevronDown
          className="w-4 h-4 mt-1 flex-shrink-0 transition-transform"
          style={{
            color: "var(--text-muted)",
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
          }}
        />
      </button>

      {open && (
        <div
          className="px-4 pb-3 pt-1 space-y-3"
          style={{ borderTop: "1px solid var(--border)", background: "var(--bg-elevated)" }}
        >
          <div>
            <p
              className="text-[10px] uppercase tracking-wide font-semibold mb-1 mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              Rule
            </p>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {finding.description}
            </p>
          </div>

          {finding.evidence.length > 0 && (
            <div>
              <p
                className="text-[10px] uppercase tracking-wide font-semibold mb-1"
                style={{ color: "var(--text-muted)" }}
              >
                Evidence from drawings
              </p>
              <ul className="space-y-1">
                {finding.evidence.map((e, i) => (
                  <li
                    key={i}
                    className="text-xs leading-relaxed flex gap-1.5"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    <span style={{ color: "var(--text-muted)" }}>›</span>
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {finding.citation && (
            <div
              className="rounded-md p-2.5"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-center justify-between mb-1.5">
                <p
                  className="text-[10px] uppercase tracking-wide font-semibold"
                  style={{ color: "var(--accent)" }}
                >
                  Verified citation
                </p>
                <a
                  href={finding.citation.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] flex items-center gap-1 hover:underline"
                  style={{ color: "var(--accent-bright)" }}
                  onClick={e => e.stopPropagation()}
                >
                  {finding.citation.source_domain}
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </div>
              <p
                className="text-xs italic leading-relaxed mb-1"
                style={{ color: "var(--text-secondary)" }}
              >
                &ldquo;{finding.citation.text}&rdquo;
              </p>
              <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                {finding.citation.source_title}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
