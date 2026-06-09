"use client";

/**
 * RaceTrack — the plan-review pipeline as a snaking blueprint course.
 *
 * Each checkpoint is a pipeline stage: Surveyor → Librarian → the 10 department
 * reviewers → Finish. Running a review animates a runner from Start to Finish,
 * hitting each checkpoint in order (stylized sequential race — the backend runs
 * departments 2-at-a-time, but the course reads cleanly left-to-right). Nodes
 * resolve to one of four states once results land: compliant (green check),
 * needs-review (amber), non-compliant (red X), or not-applicable (dim dash).
 *
 * Drawn in the site's B&W-blueprint language: a thin survey line on a grid,
 * DM-Mono checkpoint numbers, brand-blue runner. Purely prop-driven so the same
 * component powers the live dashboard and the marketing demo.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Search, BookOpen, Building2, Flame, Zap, Droplets, Wind,
  Accessibility, Leaf, Compass, Construction, Trees, Flag,
  Check, X, Minus, AlertTriangle, type LucideIcon,
} from "lucide-react";

export type NodeStatus = "compliant" | "needs_review" | "non_compliant" | "not_applicable";

export interface RaceNode {
  id: string;       // must match the agent string the backend emits
  label: string;    // short display label
  Icon: LucideIcon;
}

// Ordered course. `id` matches the exact strings the workflow reports in
// agents_completed / current_agent so live state maps without a lookup table.
export const RACE_NODES: RaceNode[] = [
  { id: "Surveyor",  label: "Surveyor",  Icon: Search },
  { id: "Librarian", label: "Librarian", Icon: BookOpen },
  { id: "Building & Safety",            label: "Building & Safety", Icon: Building2 },
  { id: "Fire Department",              label: "Fire",              Icon: Flame },
  { id: "Electrical Inspector",         label: "Electrical",        Icon: Zap },
  { id: "Plumbing Inspector",           label: "Plumbing",          Icon: Droplets },
  { id: "Mechanical Inspector",         label: "Mechanical",        Icon: Wind },
  { id: "Accessibility (ADA / CBC 11B)", label: "Accessibility",    Icon: Accessibility },
  { id: "Energy & Green Building",      label: "Energy",            Icon: Leaf },
  { id: "Planning & Zoning",            label: "Zoning",            Icon: Compass },
  { id: "Public Works",                 label: "Public Works",      Icon: Construction },
  { id: "Environmental",                label: "Environmental",     Icon: Trees },
];

interface Props {
  /** agent ids the backend reports as finished */
  completed: string[];
  /** the agent currently working, if any */
  current?: string | null;
  /** overall job progress 0–100 (smooths the runner between checkpoints) */
  progress?: number;
  /** "processing" | "completed" | "failed" — drives the finish reveal */
  status?: string;
  /** per-node verdicts, available once the report lands */
  results?: Record<string, NodeStatus>;
  /** compliance score 0–1 for the finish badge */
  score?: number;
  /** nodes per row before the course snakes back */
  perRow?: number;
}

const STATUS_TONE: Record<NodeStatus, { fg: string; bg: string; Icon: LucideIcon }> = {
  compliant:      { fg: "var(--compliant)",     bg: "var(--compliant-bg)",     Icon: Check },
  needs_review:   { fg: "var(--needs-review)",   bg: "var(--needs-review-bg)",   Icon: AlertTriangle },
  non_compliant:  { fg: "var(--non-compliant)",  bg: "var(--non-compliant-bg)",  Icon: X },
  not_applicable: { fg: "var(--text-muted)",     bg: "transparent",              Icon: Minus },
};

// Logical coordinate space; the SVG stretches this to the container.
const VIEW_W = 1000;
const ROW_H = 150;    // logical px per row (coordinate space)
const ROW_PX = 132;   // physical px per row (drives real height; keeps room for node + label)
const PAD_X = 90;
const PAD_Y = 78;

export default function RaceTrack({
  completed, current, progress = 0, status = "processing",
  results, score, perRow = 4,
}: Props) {
  const nodes = RACE_NODES;
  const pathRef = useRef<SVGPathElement>(null);
  const [pathLen, setPathLen] = useState(0);
  // FINISH is a synthetic terminal checkpoint.
  const total = nodes.length + 1;
  const rows = Math.ceil(total / perRow);
  const viewH = (rows - 1) * ROW_H + PAD_Y * 2;
  const xStep = perRow > 1 ? (VIEW_W - PAD_X * 2) / (perRow - 1) : 0;

  // Snake (boustrophedon) layout — odd rows run right-to-left.
  const coords = useMemo(() => {
    return Array.from({ length: total }, (_, i) => {
      const row = Math.floor(i / perRow);
      let col = i % perRow;
      if (row % 2 === 1) col = perRow - 1 - col;
      return { x: PAD_X + col * xStep, y: PAD_Y + row * ROW_H };
    });
  }, [total, perRow, xStep]);

  // Build the rounded survey path through every checkpoint.
  const pathD = useMemo(() => {
    const r = 26;
    let d = `M ${coords[0].x} ${coords[0].y}`;
    for (let i = 1; i < coords.length; i++) {
      const prev = coords[i - 1], cur = coords[i];
      if (cur.y === prev.y) {
        d += ` L ${cur.x} ${cur.y}`;
      } else {
        // vertical U-turn at a row end: short stub, arc, then drop in
        const dir = cur.x >= prev.x ? 1 : -1;
        d += ` L ${prev.x + dir * (xStep ? 0 : 0)} ${prev.y}`;
        d += ` Q ${prev.x + dir * r} ${prev.y} ${prev.x + dir * r} ${prev.y + r}`;
        d += ` L ${cur.x - dir * r} ${cur.y - r}`;
        d += ` Q ${cur.x - dir * r} ${cur.y} ${cur.x} ${cur.y}`;
      }
    }
    return d;
  }, [coords, xStep]);

  // Measure the rendered path so stroke-dashoffset can reveal a fraction of it.
  useEffect(() => {
    if (pathRef.current) setPathLen(pathRef.current.getTotalLength());
  }, [pathD]);

  // Frontier: how far the runner has advanced. A node is "reached" when done.
  const reachedCount = nodes.filter((n) => completed.includes(n.id)).length;
  const activeIdx = nodes.findIndex((n) => n.id === current);
  const isDone = status === "completed";
  const isFailed = status === "failed";

  // Runner sits at the active node, else just past the last reached one;
  // at completion it parks on FINISH.
  const frontier = isDone
    ? nodes.length
    : activeIdx >= 0
      ? activeIdx
      : Math.min(reachedCount, nodes.length - 1);
  const runner = coords[frontier];

  // Filled portion of the survey line (0–1) — blends checkpoint progress with
  // the job's % so the line creeps smoothly rather than jumping per node.
  const nodeFrac = isDone ? 1 : (reachedCount + (activeIdx >= 0 ? 0.5 : 0)) / total;
  const fillFrac = isDone ? 1 : Math.max(nodeFrac, (progress / 100) * (nodes.length / total));

  const nodeState = (n: RaceNode, i: number) => {
    if ((isDone || isFailed) && results?.[n.id]) return { kind: "resolved" as const, st: results[n.id] };
    if (current === n.id) return { kind: "active" as const };
    if (completed.includes(n.id)) return { kind: "reached" as const };
    return { kind: "pending" as const };
  };

  return (
    <div
      className="relative w-full select-none"
      style={{ height: rows * ROW_PX }}
    >
      {/* blueprint grid backdrop */}
      <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${VIEW_W} ${viewH}`} preserveAspectRatio="none">
        <defs>
          <pattern id="rt-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--border)" strokeWidth="0.6" opacity="0.6" />
          </pattern>
          <linearGradient id="rt-fill" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--accent)" />
            <stop offset="100%" stopColor="var(--accent-bright)" />
          </linearGradient>
        </defs>
        <rect width={VIEW_W} height={viewH} fill="url(#rt-grid)" />
        {/* base survey line */}
        <path d={pathD} fill="none" stroke="var(--border-bright)" strokeWidth="2.5"
          strokeLinecap="round" />
        {/* progress fill — stroke-dashoffset off the path's real length, CSS-
            transitioned (framer's pathLength prop won't reliably re-tween here) */}
        <path
          ref={pathRef}
          d={pathD} fill="none" stroke="url(#rt-fill)" strokeWidth="3.5" strokeLinecap="round"
          strokeDasharray={pathLen}
          strokeDashoffset={pathLen * (1 - fillFrac)}
          style={{ transition: "stroke-dashoffset 0.8s ease-in-out", filter: "drop-shadow(0 1px 4px var(--accent-glow))" }}
        />
      </svg>

      {/* runner token — plain CSS transition (framer won't reliably tween
          percentage left/top), so it glides checkpoint→checkpoint */}
      {!isDone && !isFailed && (
        <div
          className="absolute z-20"
          style={{
            left: `${(runner.x / VIEW_W) * 100}%`,
            top: `${(runner.y / viewH) * 100}%`,
            transform: "translate(-50%,-50%)",
            transition: "left 0.7s ease-in-out, top 0.7s ease-in-out",
          }}
        >
          <span className="relative flex h-4 w-4">
            <span className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping"
              style={{ background: "var(--accent)" }} />
            <span className="relative inline-flex h-4 w-4 rounded-full"
              style={{ background: "var(--accent)", boxShadow: "0 0 0 3px white, 0 0 0 6px var(--accent-glow)" }} />
          </span>
        </div>
      )}

      {/* checkpoints */}
      {nodes.map((n, i) => {
        const c = coords[i];
        const s = nodeState(n, i);
        const tone =
          s.kind === "resolved" ? STATUS_TONE[s.st]
          : s.kind === "active" ? { fg: "var(--accent)", bg: "var(--accent-soft)", Icon: n.Icon }
          : s.kind === "reached" ? { fg: "var(--text-primary)", bg: "var(--bg-card)", Icon: n.Icon }
          : { fg: "var(--text-muted)", bg: "var(--bg-card)", Icon: n.Icon };
        const BadgeIcon = s.kind === "resolved" ? tone.Icon : n.Icon;
        return (
          <div key={n.id} className="absolute z-10 flex flex-col items-center"
            style={{ left: `${(c.x / VIEW_W) * 100}%`, top: `${(c.y / viewH) * 100}%`, transform: "translate(-50%,-50%)" }}>
            <motion.div
              initial={false}
              animate={{ scale: s.kind === "active" ? 1.12 : 1 }}
              transition={{ type: "spring", stiffness: 200, damping: 14 }}
              className={`relative flex items-center justify-center rounded-full ${s.kind === "active" ? "agent-active" : ""}`}
              style={{
                width: 46, height: 46, background: tone.bg, color: tone.fg,
                boxShadow: `0 0 0 1.5px ${s.kind === "pending" ? "var(--border)" : tone.fg}`,
              }}
            >
              <BadgeIcon className="w-[18px] h-[18px]" strokeWidth={2.2} />
              {/* checkpoint number, blueprint-mono */}
              <span className="absolute -top-1 -left-1 flex items-center justify-center rounded-full text-[9px]"
                style={{ width: 16, height: 16, background: "var(--bg)", color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)", boxShadow: "0 0 0 1px var(--border)" }}>
                {i + 1}
              </span>
            </motion.div>
            <span className="mt-1.5 text-[10px] font-medium text-center leading-tight max-w-[78px]"
              style={{ color: s.kind === "pending" ? "var(--text-muted)" : "var(--text-secondary)",
                fontFamily: "var(--font-mono)" }}>
              {n.label}
            </span>
          </div>
        );
      })}

      {/* FINISH checkpoint */}
      {(() => {
        const c = coords[nodes.length];
        const pct = score != null ? Math.round(score * 100) : null;
        const ring = isDone
          ? (score ?? 0) >= 0.8 ? "var(--compliant)" : (score ?? 0) >= 0.5 ? "var(--needs-review)" : "var(--non-compliant)"
          : "var(--border-bright)";
        return (
          <div className="absolute z-10 flex flex-col items-center"
            style={{ left: `${(c.x / VIEW_W) * 100}%`, top: `${(c.y / viewH) * 100}%`, transform: "translate(-50%,-50%)" }}>
            <motion.div
              initial={false}
              animate={{ scale: isDone ? 1.15 : 1 }}
              transition={{ type: "spring", stiffness: 180, damping: 12 }}
              className="relative flex items-center justify-center rounded-full"
              style={{ width: 54, height: 54, background: "var(--bg-card)", color: ring, boxShadow: `0 0 0 2px ${ring}` }}>
              {isDone && pct != null
                ? <span className="text-[14px] font-bold" style={{ fontFamily: "var(--font-display)" }}>{pct}</span>
                : <Flag className="w-5 h-5" strokeWidth={2.2} />}
            </motion.div>
            <span className="mt-1.5 text-[10px] font-semibold" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
              {isDone ? "SCORE" : "FINISH"}
            </span>
          </div>
        );
      })()}
    </div>
  );
}
