// =====================================================================
// Pilot configuration — single source of truth for the 90% target knobs.
//
// Every threshold the pipeline uses to enforce the 90% / broad-scope
// pilot brief lives here. Touch this file when you want to change a
// gate; do NOT scatter magic numbers across triage.ts / critic.ts /
// archetype.ts. The brief itself is at docs/PILOT_BRIEF.md.
//
// Rule of thumb: if a number in this file would change for the 99%
// roadmap, it belongs here.
// =====================================================================
import type { ProjectArchetype } from "./archetype.ts";

// =====================================================================
// Accuracy targets (read by the eval harness + check-pilot-targets CLI)
// =====================================================================
export const PILOT_TARGETS = {
  /** When the system says "fail", ground truth agrees ≥ this rate. */
  per_finding_precision_min: 0.90,
  /** The system catches ≥ this share of real issues. */
  per_finding_recall_min: 0.85,
  /** When the archetype gate says "reject", it's right ≥ this rate. */
  out_of_scope_rejection_precision_min: 0.95,
  /** Per-archetype F1 may drop at most this much between labeled runs. */
  per_archetype_f1_regression_tolerance: 0.02,
  /** Minimum number of ground-truth observations for an archetype to
   *  be evaluated against the targets (below this, results are noise). */
  min_observations_per_archetype: 10,
} as const;

// =====================================================================
// Pipeline gates (read by triage.ts and critic.ts)
// =====================================================================
export const PIPELINE_GATES = {
  /** A "fail" finding needs a citation at least this confident to ship.
   *  Below this, the finding is auto-downgraded to "warn" in triage.ts
   *  step 4c. 0.5 keeps recall up; raise toward 0.7 to trade recall for
   *  precision. Brief Hard NO: > 0.80. */
  citation_min_confidence: 0.5,

  /** Confidence below this auto-routes the finding to the human-review
   *  queue instead of shipping it as "fail". Currently informational —
   *  the dashboard reads it (Month 2 work item 7). */
  finding_ship_min_confidence: 0.75,

  /** Adversarial critic verdict confidence at-or-above which a dissent
   *  triggers a hard downgrade (fail → warn). Below this, the finding
   *  stays as fail but gets a "models disagree" tag. */
  critic_hard_downgrade_confidence: 0.7,

  /** Max number of findings the critic loop runs per submittal. Bounds
   *  cost at ~$0.25 per submittal. Brief Hard NO: increasing to an
   *  N-of-5 ensemble. */
  critic_max_findings_per_run: 5,

  /** Max number of citation-research enrichments per submittal.
   *  Each one is ~$0.05-0.20 in search + LLM. */
  research_max_citations_per_run: 5,
} as const;

// =====================================================================
// Pilot scope — the archetype allowlist
//
// Mirrors the brief's "In-pilot scope" table. The agencies.pilot_archetypes
// column overrides this per-agency; this constant is the DEFAULT applied
// when no agency-specific override exists.
// =====================================================================
export const PILOT_ARCHETYPES_DEFAULT: ProjectArchetype[] = [
  "la_sfr_typ_vb_ministerial",
  "la_ti_commercial",
  "ventura_sfr_typ_vb_ministerial",
  "ventura_ti_commercial",
];

/**
 * Archetypes that get triaged but are flagged as "edge — needs extra
 * reviewer attention" in the dashboard. Listed in the brief as
 * `la_assembly_small` and `la_school_small`. Today the archetype
 * classifier does not yet emit these labels — when it does, add them
 * here so the dashboard can route them with a yellow flag.
 */
export const PILOT_EDGE_ARCHETYPES: readonly ProjectArchetype[] = [
  // Empty until classifier emits these.
];

// =====================================================================
// Helpers
// =====================================================================

/** True iff the agency hasn't overridden the default pilot scope. */
export function usingDefaultPilotScope(agencyPilotArchetypes?: readonly string[]): boolean {
  return !agencyPilotArchetypes || agencyPilotArchetypes.length === 0;
}

/** Render the pilot targets as a one-line banner for logs / dashboards. */
export function formatPilotTargets(): string {
  const t = PILOT_TARGETS;
  return `90% pilot target: precision ≥ ${(t.per_finding_precision_min * 100).toFixed(0)}%, ` +
    `recall ≥ ${(t.per_finding_recall_min * 100).toFixed(0)}%, ` +
    `gate precision ≥ ${(t.out_of_scope_rejection_precision_min * 100).toFixed(0)}%`;
}
