"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, MapPin, AlertTriangle } from "lucide-react";
import FindingCard from "./FindingCard";
import type { DemoScenario } from "./scenarios";

interface Props {
  scenario: DemoScenario;
  onReset: () => void;
}

function scoreColor(s: number) {
  if (s >= 80) return { stroke: "var(--compliant)", text: "var(--compliant)" };
  if (s >= 60) return { stroke: "var(--needs-review)", text: "var(--needs-review)" };
  return { stroke: "var(--non-compliant)", text: "var(--non-compliant)" };
}

function gradeStyle(g: string): React.CSSProperties {
  if (g === "A" || g === "B")
    return { background: "var(--compliant-bg)", color: "var(--compliant)" };
  if (g === "C") return { background: "var(--needs-review-bg)", color: "var(--accent)" };
  return { background: "var(--non-compliant-bg)", color: "var(--non-compliant)" };
}

const CIRCUMFERENCE = 2 * Math.PI * 26;

export default function TriageReportView({ scenario, onReset }: Props) {
  const [displayScore, setDisplayScore] = useState(0);
  const { report } = scenario;
  const colors = scoreColor(report.completeness.score);
  const scope = report.scope;

  useEffect(() => {
    const target = report.completeness.score;
    let current = 0;
    const steps = 40;
    const interval = setInterval(() => {
      current += target / steps;
      if (current >= target) {
        setDisplayScore(target);
        clearInterval(interval);
      } else {
        setDisplayScore(Math.round(current));
      }
    }, 1000 / steps);
    return () => clearInterval(interval);
  }, [report.completeness.score]);

  const ORDER: Record<string, number> = { fail: 0, warn: 1, info: 2, pass: 3 };
  const sorted = [...report.findings].sort(
    (a, b) => (ORDER[a.status] ?? 4) - (ORDER[b.status] ?? 4),
  );

  const scopeRows = [
    { label: "Occupancy", value: scope.occupancies.join(" / ") },
    { label: "Construction", value: scope.construction_type },
    {
      label: "Total area",
      value: scope.building_area_sf ? `${scope.building_area_sf.toLocaleString()} SF` : null,
    },
    { label: "Stories", value: scope.stories_above },
    { label: "Height", value: scope.height_ft ? `${scope.height_ft} ft` : null },
    {
      label: "Sprinklered",
      value: scope.sprinklered === null ? null : scope.sprinklered ? "Yes" : "No",
    },
  ].filter(r => r.value !== null && r.value !== undefined);

  return (
    <div className="fade-in">
      {/* Sub-header */}
      <div
        className="flex items-start justify-between gap-4 px-5 py-3.5"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div>
          <h3
            className="font-semibold text-sm"
            style={{
              color: "var(--text-primary)",
              fontFamily: "var(--font-display)",
            }}
          >
            {scenario.projectName}
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            {scenario.address}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span
              className="font-mono text-[10px] font-semibold"
              style={{ color: "var(--accent-bright)" }}
            >
              {scenario.jurisdiction}
            </span>
            <span style={{ color: "var(--border-bright)" }}>·</span>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {scenario.projectType}
            </span>
          </div>
        </div>
        <button
          onClick={onReset}
          className="text-xs flex items-center gap-1 flex-shrink-0 mt-0.5 whitespace-nowrap hover:underline"
          style={{ color: "var(--accent-bright)" }}
        >
          <ArrowLeft className="w-3 h-3" />
          Try another
        </button>
      </div>

      <div className="p-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Left column: score + scope */}
        <div className="lg:col-span-2 space-y-3">
          {/* Score card */}
          <div
            className="rounded-lg p-4"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center gap-3">
              <div className="relative w-16 h-16 flex-shrink-0">
                <svg viewBox="0 0 64 64" className="w-16 h-16 -rotate-90">
                  <circle cx="32" cy="32" r="26" fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="6" />
                  <circle
                    cx="32"
                    cy="32"
                    r="26"
                    fill="none"
                    stroke={colors.stroke}
                    strokeWidth="6"
                    strokeDasharray={`${(displayScore / 100) * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
                    strokeLinecap="round"
                    style={{ transition: "stroke-dasharray 25ms linear" }}
                  />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-lg font-bold" style={{ color: colors.text }}>
                    {displayScore}
                  </span>
                </div>
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className="text-sm font-semibold"
                    style={{ color: "var(--text-primary)" }}
                  >
                    Completeness
                  </span>
                  <span
                    className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                    style={gradeStyle(report.completeness.grade)}
                  >
                    {report.completeness.grade}
                  </span>
                </div>
                <p
                  className="text-xs mt-0.5 leading-snug"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {report.completeness.headline}
                </p>
              </div>
            </div>

            {/* Stats tally */}
            <div
              className="mt-3 pt-3 grid grid-cols-4 gap-1.5"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              {[
                { label: "Fail", n: report.stats.fail, fg: "var(--non-compliant)", bg: "var(--non-compliant-bg)" },
                { label: "Warn", n: report.stats.warn, fg: "var(--needs-review)", bg: "var(--needs-review-bg)" },
                { label: "Pass", n: report.stats.pass, fg: "var(--compliant)", bg: "var(--compliant-bg)" },
                { label: "Info", n: report.stats.info, fg: "var(--text-muted)", bg: "var(--na-bg)" },
              ].map(({ label, n, fg, bg }) => (
                <div
                  key={label}
                  className="text-center py-1.5 rounded text-xs font-semibold"
                  style={{ background: bg, color: fg }}
                >
                  <div className="text-base font-bold leading-none mb-0.5">{n}</div>
                  {label}
                </div>
              ))}
            </div>
          </div>

          {/* Scope panel */}
          <div
            className="rounded-lg p-4"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center gap-2 mb-3">
              <MapPin className="w-3.5 h-3.5" style={{ color: "var(--accent-bright)" }} />
              <h4
                className="text-[10px] font-semibold uppercase tracking-wide"
                style={{ color: "var(--text-muted)" }}
              >
                Building Scope
              </h4>
            </div>
            <dl className="space-y-2">
              {scopeRows.map(({ label, value }) => (
                <div key={label} className="flex justify-between items-baseline gap-2">
                  <dt className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {label}
                  </dt>
                  <dd
                    className="text-xs font-medium text-right"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {String(value)}
                  </dd>
                </div>
              ))}
            </dl>

            {scope.wui_zone?.in_wui && (
              <div
                className="mt-3 pt-3"
                style={{ borderTop: "1px solid var(--border)" }}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{ background: "var(--non-compliant)" }}
                  />
                  <span
                    className="text-xs font-semibold"
                    style={{ color: "var(--non-compliant)" }}
                  >
                    WUI: {scope.wui_zone.haz_class} FHSZ ({scope.wui_zone.sra_type})
                  </span>
                </div>
                <p
                  className="text-[11px] mt-0.5 ml-3.5"
                  style={{ color: "var(--text-muted)" }}
                >
                  CBC Chapter 7A applies
                </p>
              </div>
            )}

            {scope.ambiguities.length > 0 && (
              <div
                className="mt-3 pt-3 space-y-1.5"
                style={{ borderTop: "1px solid var(--border)" }}
              >
                <p
                  className="text-[10px] font-semibold uppercase tracking-wide"
                  style={{ color: "var(--text-muted)" }}
                >
                  Reviewer Questions
                </p>
                {scope.ambiguities.slice(0, 2).map((a, i) => (
                  <p
                    key={i}
                    className="text-xs flex gap-1.5 items-start"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    <AlertTriangle
                      className="w-3 h-3 flex-shrink-0 mt-0.5"
                      style={{ color: "var(--accent)" }}
                    />
                    {a}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right column: findings */}
        <div className="lg:col-span-3 space-y-2">
          <h4
            className="text-[10px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--text-muted)" }}
          >
            Findings ({report.findings.length})
          </h4>
          {sorted.map((f, i) => (
            <FindingCard
              key={f.rule_id}
              finding={f}
              defaultOpen={i < 2 && (f.status === "fail" || f.status === "warn")}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
