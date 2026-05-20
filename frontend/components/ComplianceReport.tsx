"use client";

import { useState, useMemo, useEffect } from "react";
import type { ComplianceReport as Report, ComplianceFinding } from "@/lib/api";
import { getExportUrl, listReportComments } from "@/lib/api";
import {
  getStatusColor, getStatusLabel, getSeverityColor,
  getCategoryIcon, getCategoryLabel, cn
} from "@/lib/utils";
import {
  Download, Search, Filter, MapPin, Building2,
  AlertTriangle, CheckCircle2, Clock, MinusCircle,
  FileText, FileSpreadsheet, ChevronDown, ChevronUp,
  Zap, Shield, Wrench, Wifi, Accessibility, BatteryMedium,
  Share2,
} from "lucide-react";
import { ShareDialog } from "@/components/ShareDialog";
import { ChatWidget } from "@/components/ChatWidget";
import { FindingComments } from "@/components/FindingComments";

// ─── Score Ring ──────────────────────────────────────────────────────
function ScoreRing({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const r = 45;
  const circ = 2 * Math.PI * r;
  const dashoffset = circ - (circ * score);

  const color = score >= 0.8 ? "#10b981" : score >= 0.5 ? "#f59e0b" : "#ef4444";

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width="120" height="120" viewBox="0 0 100 100">
        {/* Track */}
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="8" />
        {/* Progress */}
        <circle
          cx="50" cy="50" r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={dashoffset}
          transform="rotate(-90 50 50)"
          style={{
            filter: `drop-shadow(0 0 6px ${color}60)`,
            transition: "stroke-dashoffset 1.5s ease-out",
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold" style={{ color, fontFamily: "var(--font-display)" }}>
          {pct}%
        </span>
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>score</span>
      </div>
    </div>
  );
}

// ─── Summary Cards ────────────────────────────────────────────────────
function SummaryCard({ label, value, icon: Icon, color }: {
  label: string; value: number; icon: React.ElementType; color: string;
}) {
  return (
    <div
      className="p-4 rounded-xl flex items-center gap-3"
      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
    >
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: `${color}18`, border: `1px solid ${color}30` }}
      >
        <Icon className="w-4.5 h-4.5" style={{ color }} />
      </div>
      <div>
        <div className="text-xl font-bold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
          {value}
        </div>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</div>
      </div>
    </div>
  );
}

// ─── Finding Card ─────────────────────────────────────────────────────
function FindingCard({
  finding,
  jobId,
  commentCount,
}: {
  finding: ComplianceFinding;
  jobId: string;
  commentCount: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const req = finding.code_requirement;
  // Stable comment key = the code citation, not the per-run finding_id.
  const findingRef = req.code_id || req.section;

  return (
    <div
      className="finding-card rounded-xl overflow-hidden"
      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
    >
      {/* Header row */}
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Category icon */}
        <span className="text-lg flex-shrink-0 mt-0.5">{getCategoryIcon(finding.category)}</span>

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            {/* Code reference */}
            <span
              className="text-xs font-mono px-1.5 py-0.5 rounded"
              style={{
                background: "rgba(212, 175, 55, 0.08)",
                color: "var(--accent-bright)",
                border: "1px solid rgba(212, 175, 55, 0.20)"
              }}
            >
              {req.section || req.code_id}
            </span>
            {/* Status badge */}
            <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium border", getStatusColor(finding.status))}>
              {getStatusLabel(finding.status)}
            </span>
            {/* Severity badge */}
            <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium border", getSeverityColor(finding.severity))}>
              {finding.severity.toUpperCase()}
            </span>
          </div>

          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {finding.description}
          </p>
        </div>

        <div className="flex-shrink-0 mt-1">
          {expanded
            ? <ChevronUp className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
            : <ChevronDown className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
          }
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div
          className="px-4 pb-4 pt-0 border-t space-y-3 text-sm"
          style={{ borderColor: "var(--border)" }}
        >
          {/* Values comparison */}
          {(finding.plan_value || finding.required_value) && (
            <div className="grid grid-cols-2 gap-3 pt-3">
              {finding.plan_value && (
                <div
                  className="p-3 rounded-lg"
                  style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
                >
                  <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>Plan shows</div>
                  <div className="font-semibold" style={{ color: "var(--text-primary)" }}>
                    {finding.plan_value}
                  </div>
                </div>
              )}
              {finding.required_value && (
                <div
                  className="p-3 rounded-lg"
                  style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
                >
                  <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>Code requires</div>
                  <div className="font-semibold" style={{ color: "var(--text-primary)" }}>
                    {finding.required_value}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Code reference detail */}
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            <span className="font-medium" style={{ color: "var(--text-secondary)" }}>{req.code_name}</span>
            {req.section && ` § ${req.section}`}
            {req.jurisdiction_specific && (
              <span className="ml-2 text-amber-400">· Jurisdiction-specific</span>
            )}
          </div>

          {/* Recommendation */}
          {finding.recommendation && (
            <div
              className="flex gap-2 p-3 rounded-lg text-xs"
              style={{
                background: "var(--needs-review-bg)",
                border: "1px solid rgba(245,158,11,0.2)",
                color: "#fcd34d"
              }}
            >
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              <span>{finding.recommendation}</span>
            </div>
          )}

          {/* Team discussion — owners can comment; threads are shared with
              any contractor/inspector invited to the report. */}
          <FindingComments
            jobId={jobId}
            findingRef={findingRef}
            canComment
            initialCount={commentCount}
          />
        </div>
      )}
    </div>
  );
}

// ─── Main Report Component ────────────────────────────────────────────
export default function ComplianceReport({
  report,
  jobId,
  filename,
}: {
  report: Report;
  jobId: string;
  filename?: string;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [shareOpen, setShareOpen] = useState(false);
  // commentCounts: code_id → number of comments, fetched once so each
  // FindingCard can show its count without N separate requests.
  const [commentCounts, setCommentCounts] = useState<Record<string, number>>({});

  const s = report.summary;
  const j = report.jurisdiction;
  const pd = report.plan_data;

  useEffect(() => {
    listReportComments(jobId)
      .then(({ comments }) => {
        const counts: Record<string, number> = {};
        for (const c of comments) {
          counts[c.finding_ref] = (counts[c.finding_ref] || 0) + 1;
        }
        setCommentCounts(counts);
      })
      .catch(() => {/* comments are best-effort; ignore */});
  }, [jobId]);

  // Get unique categories
  const categories = useMemo(() => {
    const cats = new Set(report.findings.map((f) => f.category));
    return Array.from(cats);
  }, [report.findings]);

  // Filter findings
  const filtered = useMemo(() => {
    return report.findings.filter((f) => {
      if (statusFilter !== "all" && f.status !== statusFilter) return false;
      if (categoryFilter !== "all" && f.category !== categoryFilter) return false;
      if (severityFilter !== "all" && f.severity !== severityFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          f.description.toLowerCase().includes(q) ||
          f.code_requirement.section?.toLowerCase().includes(q) ||
          f.code_requirement.code_name?.toLowerCase().includes(q) ||
          f.category.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [report.findings, statusFilter, categoryFilter, severityFilter, search]);

  return (
    <div className="space-y-5">
      {/* ── Liability disclaimer (must be visible at top of every report) ── */}
      <div
        className="flex gap-3 p-4 rounded-xl text-xs"
        style={{
          background: "var(--needs-review-bg)",
          border: "1px solid rgba(245, 158, 11, 0.3)",
          color: "var(--text-secondary)",
        }}
      >
        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--needs-review)" }} />
        <div className="leading-relaxed">
          <strong style={{ color: "var(--text-primary)" }}>AI-generated preliminary review.</strong>{" "}
          This report is produced by an AI system for educational and pre-submittal feedback only. It is
          <strong style={{ color: "var(--text-primary)" }}> not engineering advice</strong> and does
          <strong style={{ color: "var(--text-primary)" }}> not replace</strong> stamped review by a
          licensed architect or engineer or approval by the Authority Having Jurisdiction (AHJ). up2code
          makes no warranty of accuracy and is not liable for any decision, permit outcome, construction
          activity, or damages arising from reliance on this output. Always verify all findings with a
          licensed professional and your AHJ before submitting or constructing.
        </div>
      </div>

      {/* ── Top: Summary + Jurisdiction ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Score + summary */}
        <div
          className="lg:col-span-2 p-6 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-start gap-6">
            <ScoreRing score={s.compliance_score} />
            <div className="flex-1 min-w-0">
              <h2
                className="text-xl font-bold mb-1"
                style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
              >
                Compliance Report
              </h2>
              <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
                {report.generated_at
                  ? new Date(report.generated_at).toLocaleString()
                  : ""} · {filename || "Uploaded plan"}
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <SummaryCard label="Compliant" value={s.compliant} icon={CheckCircle2} color="#10b981" />
                <SummaryCard label="Non-Compliant" value={s.non_compliant} icon={AlertTriangle} color="#ef4444" />
                <SummaryCard label="Needs Review" value={s.needs_review} icon={Clock} color="#f59e0b" />
                <SummaryCard label="N/A" value={s.not_applicable} icon={MinusCircle} color="#64748b" />
              </div>
            </div>
          </div>

          {/* Severity pills */}
          {(s.critical_issues > 0 || s.high_issues > 0) && (
            <div className="flex flex-wrap gap-2 mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
              {s.critical_issues > 0 && (
                <span className={cn("text-xs px-3 py-1 rounded-full border font-medium", getSeverityColor("critical"))}>
                  {s.critical_issues} Critical
                </span>
              )}
              {s.high_issues > 0 && (
                <span className={cn("text-xs px-3 py-1 rounded-full border font-medium", getSeverityColor("high"))}>
                  {s.high_issues} High
                </span>
              )}
              {s.medium_issues > 0 && (
                <span className={cn("text-xs px-3 py-1 rounded-full border font-medium", getSeverityColor("medium"))}>
                  {s.medium_issues} Medium
                </span>
              )}
            </div>
          )}
        </div>

        {/* Jurisdiction + Export */}
        <div className="space-y-3">
          {/* Jurisdiction card */}
          <div
            className="p-5 rounded-2xl"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <h3
              className="text-sm font-semibold mb-3 flex items-center gap-2"
              style={{ color: "var(--text-primary)" }}
            >
              <MapPin className="w-4 h-4 text-amber-300" />
              Jurisdiction
            </h3>
            {j ? (
              <div className="space-y-2 text-sm">
                {j.city && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>City</span>
                    <span style={{ color: "var(--text-primary)" }}>{j.city}</span>
                  </div>
                )}
                {j.state && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>State</span>
                    <span style={{ color: "var(--text-primary)" }}>{j.state} ({j.state_code})</span>
                  </div>
                )}
                {j.seismic_zone && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>Seismic Zone</span>
                    <span className="text-amber-400 font-medium">Zone {j.seismic_zone}</span>
                  </div>
                )}
                {j.wind_zone && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>Wind Zone</span>
                    <span className="text-amber-400 font-medium">Zone {j.wind_zone}</span>
                  </div>
                )}
                {j.confidence !== undefined && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>Confidence</span>
                    <span style={{ color: "var(--text-primary)" }}>
                      {Math.round((j.confidence || 0) * 100)}%
                    </span>
                  </div>
                )}
                {Object.values(report.code_versions)[0] && (
                  <div
                    className="pt-2 mt-2 text-xs"
                    style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)" }}
                  >
                    {Object.values(report.code_versions)[0]}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>Jurisdiction not identified</p>
            )}
          </div>

          {/* Plan data card */}
          {pd && (pd.project_name || pd.occupancy_type || pd.plan_type) && (
            <div
              className="p-5 rounded-2xl"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <h3
                className="text-sm font-semibold mb-3 flex items-center gap-2"
                style={{ color: "var(--text-primary)" }}
              >
                <Building2 className="w-4 h-4 text-amber-300" />
                Project Data
              </h3>
              <div className="space-y-2 text-sm">
                {pd.project_name && (
                  <div>
                    <span className="block text-xs mb-0.5" style={{ color: "var(--text-muted)" }}>Project</span>
                    <span style={{ color: "var(--text-primary)" }}>{pd.project_name}</span>
                  </div>
                )}
                {pd.plan_type && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>Type</span>
                    <span className="capitalize" style={{ color: "var(--text-primary)" }}>{pd.plan_type}</span>
                  </div>
                )}
                {pd.occupancy_type && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>Occupancy</span>
                    <span style={{ color: "var(--text-primary)" }}>{pd.occupancy_type}</span>
                  </div>
                )}
                {pd.building_area && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--text-muted)" }}>Area</span>
                    <span style={{ color: "var(--text-primary)" }}>{pd.building_area.toLocaleString()} SF</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Collaborate */}
          <div
            className="p-4 rounded-2xl"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <h3 className="text-xs font-semibold mb-3" style={{ color: "var(--text-secondary)" }}>
              COLLABORATE
            </h3>
            <button
              onClick={() => setShareOpen(true)}
              className="flex items-center gap-2 w-full py-2.5 px-4 rounded-xl text-sm font-medium"
              style={{ background: "#0B0E14", color: "#fff" }}
            >
              <Share2 className="w-4 h-4" />
              Share with contractor / inspector
            </button>
            <p className="text-[11px] mt-2 leading-snug" style={{ color: "var(--text-muted)" }}>
              Invite collaborators to view and discuss findings. They don&apos;t need a Up2Code account — it&apos;s free for them.
            </p>
          </div>

          {/* Export buttons */}
          <div
            className="p-4 rounded-2xl space-y-2"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <h3 className="text-xs font-semibold mb-3" style={{ color: "var(--text-secondary)" }}>
              EXPORT REPORT
            </h3>
            <a
              href={getExportUrl(jobId, "pdf")}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 w-full py-2.5 px-4 rounded-xl text-sm font-medium transition-all"
              style={{
                background: "linear-gradient(135deg, #1e40af20, #3b82f620)",
                border: "1px solid rgba(59,130,246,0.25)",
                color: "#93c5fd",
              }}
            >
              <FileText className="w-4 h-4" />
              Download PDF Report
              <Download className="w-3.5 h-3.5 ml-auto" />
            </a>
            <a
              href={getExportUrl(jobId, "csv")}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 w-full py-2.5 px-4 rounded-xl text-sm font-medium transition-all"
              style={{
                background: "linear-gradient(135deg, #14532d20, #22c55e20)",
                border: "1px solid rgba(34,197,94,0.25)",
                color: "#86efac",
              }}
            >
              <FileSpreadsheet className="w-4 h-4" />
              Download CSV Data
              <Download className="w-3.5 h-3.5 ml-auto" />
            </a>
          </div>
        </div>
      </div>

      {/* ── Recommendations ── */}
      {report.recommendations && report.recommendations.length > 0 && (
        <div
          className="p-5 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid rgba(245,158,11,0.2)" }}
        >
          <h3
            className="text-sm font-semibold mb-3 flex items-center gap-2"
            style={{ fontFamily: "var(--font-display)", color: "#fcd34d" }}
          >
            <AlertTriangle className="w-4 h-4" />
            Action Items ({report.recommendations.length})
          </h3>
          <div className="space-y-2">
            {report.recommendations.slice(0, 10).map((rec, i) => (
              <div key={i} className="flex gap-3 text-sm">
                <span className="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: "rgba(245,158,11,0.15)", color: "#f59e0b" }}
                >
                  {i + 1}
                </span>
                <span style={{ color: "var(--text-secondary)" }}>{rec}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Findings Table ── */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        {/* Controls header */}
        <div
          className="p-4 flex flex-wrap gap-3 items-center"
          style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-elevated)" }}
        >
          <h3
            className="text-sm font-semibold flex-shrink-0"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Findings ({filtered.length}/{report.findings.length})
          </h3>

          {/* Search */}
          <div className="flex-1 min-w-48 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
            <input
              type="text"
              placeholder="Search findings…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 rounded-lg text-xs outline-none"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-2 py-2 rounded-lg text-xs outline-none"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
            >
              <option value="all">All Status</option>
              <option value="non_compliant">Non-Compliant</option>
              <option value="needs_review">Needs Review</option>
              <option value="compliant">Compliant</option>
              <option value="not_applicable">N/A</option>
            </select>

            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="px-2 py-2 rounded-lg text-xs outline-none"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
            >
              <option value="all">All Severity</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>

            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-2 py-2 rounded-lg text-xs outline-none"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
            >
              <option value="all">All Categories</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>{getCategoryLabel(cat)}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Category summary pills */}
        <div
          className="px-4 py-3 flex flex-wrap gap-2"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          {categories.map((cat) => {
            const count = report.findings.filter((f) => f.category === cat).length;
            const nonComp = report.findings.filter((f) => f.category === cat && f.status === "non_compliant").length;
            return (
              <button
                key={cat}
                onClick={() => setCategoryFilter(categoryFilter === cat ? "all" : cat)}
                className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all
                  ${categoryFilter === cat ? "ring-1 ring-blue-500" : ""}`}
                style={{
                  background: categoryFilter === cat ? "rgba(79,126,255,0.15)" : "var(--bg-elevated)",
                  border: `1px solid ${categoryFilter === cat ? "rgba(79,126,255,0.4)" : "var(--border)"}`,
                  color: "var(--text-secondary)"
                }}
              >
                <span>{getCategoryIcon(cat)}</span>
                <span>{getCategoryLabel(cat)}</span>
                <span
                  className="px-1 rounded font-medium text-[10px]"
                  style={{ background: nonComp > 0 ? "var(--non-compliant-bg)" : "var(--bg-card)", color: nonComp > 0 ? "var(--non-compliant)" : "var(--text-muted)" }}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Finding cards list */}
        <div className="p-4 space-y-2 max-h-[60vh] overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No findings match your filters</p>
            </div>
          ) : (
            filtered.map((finding) => (
              <FindingCard
                key={finding.finding_id}
                finding={finding}
                jobId={jobId}
                commentCount={
                  commentCounts[finding.code_requirement.code_id] ??
                  commentCounts[finding.code_requirement.section] ??
                  0
                }
              />
            ))
          )}
        </div>
      </div>

      {/* Multi-department review notes */}
      {report.auditor_notes && (
        <div
          className="p-4 rounded-xl text-xs"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)"
          }}
        >
          <strong className="font-medium" style={{ color: "var(--text-secondary)" }}>Review Notes: </strong>
          {report.auditor_notes}
          <br />
          <span className="mt-1 block text-[10px]">
            This report is generated by AI and is for informational purposes only.
            Always verify with the Authority Having Jurisdiction (AHJ).
          </span>
        </div>
      )}

      {/* Share dialog */}
      {shareOpen && <ShareDialog jobId={jobId} onClose={() => setShareOpen(false)} />}

      {/* Floating AI assistant — clarifying questions grounded in the code corpus */}
      <ChatWidget jobId={jobId} />
    </div>
  );
}
