// =====================================================================
// Triage runner: orchestrates the AI pipeline for one submittal.
//
// Stages:
//   1. extractScope        — LLM + regex hybrid; pulls building facts
//   2. evaluateAll         — deterministic rules over the scope
//   3. completenessJudgment — LLM holistic "is this submittal-ready?" call
//   4. assemble            — score + grade + ordered findings
//
// Returns a triage report ready to write to triage_runs.report.
// =====================================================================
import { LlmClient, LlmCallContext } from "./llm.ts";
import { extractScope, BuildingScope } from "./extract.ts";
import { evaluateAll, Finding } from "./evaluate.ts";
import { Rule, rulesForAgency, BASELINE_RULES, CALFIRE_WUI_RULES, CALGREEN_MANDATORY_RULES } from "./rules.ts";
import { JurisdictionProfile } from "./surveyor.ts";
import { propertyOverlayAmbiguities } from "./property.ts";
import {
  classifyArchetype, ArchetypeResult, ProjectArchetype, renderArchetypeBanner,
} from "./archetype.ts";
import { PIPELINE_GATES } from "./pilot_config.ts";

export const PIPELINE_VERSION = "ahj-1.0";

export interface TriageReport {
  pipeline_version: string;
  generated_at: string;
  scope: BuildingScope;
  findings: Finding[];
  // Archetype gate — set even when triage runs to completion. When
  // archetype.in_pilot_scope is false, findings is empty and completeness
  // is the "out of scope" stub.
  archetype: ArchetypeResult;
  completeness: {
    score: number;          // 0-100, "is this ready for substantive review"
    grade: "A" | "B" | "C" | "D" | "F";
    headline: string;       // one-line reviewer-facing summary
    missing_items: string[];// concrete items the applicant should provide
    reviewer_questions: string[]; // things the reviewer should think about
    assessment: string;     // 2-3 sentence holistic judgment
  };
  llm_metadata: {
    used_llm: boolean;
    model: string;
    cost_estimate_usd: number;
  };
  // Tally for the dashboard
  stats: {
    total: number; pass: number; fail: number; warn: number; info: number;
  };
}

interface AgencyConfig {
  id: string;
  custom_rules?: Rule[];
  rule_overrides?: { disabled?: string[]; severity_changes?: Record<string, "critical"|"major"|"moderate"|"minor"> };
  // Per-agency pilot scope allowlist. Empty / undefined → accept the
  // default IN_SCOPE archetypes defined in archetype.ts.
  pilot_archetypes?: ProjectArchetype[];
}

const SEV_W: Record<string, number> = { critical: 5, major: 3, moderate: 1, minor: 0.5 };

// =====================================================================
// LLM completeness judgment
// =====================================================================
const COMPLETENESS_SCHEMA = {
  type: "object",
  properties: {
    score: { type: "number", minimum: 0, maximum: 100 },
    grade: { type: "string", enum: ["A", "B", "C", "D", "F"] },
    headline: { type: "string", maxLength: 140 },
    missing_items: { type: "array", items: { type: "string" } },
    reviewer_questions: { type: "array", items: { type: "string" } },
    assessment: { type: "string" },
  },
  required: ["score", "grade", "headline", "missing_items", "assessment"],
};

const COMPLETENESS_SYSTEM = `You are a senior plan-check supervisor at a city building department.
You are NOT determining code compliance — that is the licensed reviewer's job.
You ARE assessing whether a submittal is COMPLETE enough to be worth a reviewer's time,
or whether intake should bounce it back to the applicant for missing items first.

Reviewer's question to you: "Should I open this file now, or send it back to the applicant?"

Score guidance:
  90-100  Submittal-ready. All major code-analysis items present, sheets organized.
  75-89   Minor gaps. Reviewer can proceed but applicant will need follow-up.
  60-74   Material gaps. Reviewer should request specific items before substantive review.
  40-59   Substantial gaps. Likely returned-incomplete with a request list.
  <40     Disorganized or missing core items. Should be bounced at intake.

Be brief. Be specific. Concrete missing items beat vague ones — say "no occupant load
calculation provided" not "needs more code analysis." Keep missing_items to actionable
phrases the reviewer can paste into a request letter.

Respond with JSON only, matching the schema. No prose.`;

async function completenessJudgment(
  llm: LlmClient,
  ctx: LlmCallContext,
  scope: BuildingScope,
  findings: Finding[],
  planTextSample: string,
): Promise<TriageReport["completeness"]> {
  const summary = {
    extracted_facts: scope,
    rule_findings: findings.map(f => ({
      id: f.rule_id, status: f.status, severity: f.severity,
      summary: f.summary,
    })),
  };

  try {
    const result = await llm.structured<TriageReport["completeness"]>(ctx, {
      tier: "balanced",
      system: COMPLETENESS_SYSTEM,
      user:
`Here is what the deterministic rule engine extracted and evaluated:

<analysis>
${JSON.stringify(summary, null, 2)}
</analysis>

And the first ~5KB of the plan-set text for context:

<text_sample>
${planTextSample.slice(0, 5000)}
</text_sample>

Make the completeness call.`,
      schema: COMPLETENESS_SCHEMA,
      fallback: deterministicCompleteness(findings),
    });
    // Always sanity-check the score against the deterministic floor
    const detFloor = deterministicCompleteness(findings);
    if (Math.abs(result.score - detFloor.score) > 25) {
      result.assessment = `${result.assessment}\n\n(System note: LLM and deterministic completeness diverged significantly — this report may need extra reviewer attention.)`;
    }
    if (!result.reviewer_questions) result.reviewer_questions = [];
    return result;
  } catch (err) {
    console.warn("completeness LLM failed:", err);
    return deterministicCompleteness(findings);
  }
}

function deterministicCompleteness(findings: Finding[]): TriageReport["completeness"] {
  let total = 0, earned = 0;
  for (const f of findings) {
    const w = SEV_W[f.severity] ?? 1;
    total += w;
    if (f.status === "pass") earned += w;
    else if (f.status === "warn") earned += w * 0.5;
  }
  const score = total ? Math.round((earned / total) * 100 * 10) / 10 : 0;
  const grade: "A"|"B"|"C"|"D"|"F" = score >= 95 ? "A" : score >= 85 ? "B" : score >= 70 ? "C" : score >= 55 ? "D" : "F";
  const fails = findings.filter(f => f.status === "fail");
  return {
    score, grade,
    headline: fails.length
      ? `${fails.length} required item${fails.length === 1 ? "" : "s"} missing.`
      : "Submittal appears complete; reviewer should proceed.",
    missing_items: fails.slice(0, 8).map(f => `${f.code_ref}: ${f.description}`),
    reviewer_questions: [],
    assessment: fails.length
      ? `Deterministic check found ${fails.length} likely-missing items. Recommend returning to applicant for completion before substantive review.`
      : "Deterministic check found no missing items. Submittal appears ready for substantive review.",
  };
}

// =====================================================================
// Public: runTriage
// =====================================================================
export async function runTriage(
  llm: LlmClient,
  ctx: { agencyId: string; submittalId: string; triageRunId?: string },
  agency: AgencyConfig,
  planText: string,
  options: {
    useLlm?: boolean;
    // If supplied, the Researcher runs against failing critical/major
    // findings to attach a verified code citation. Requires a SupabaseClient
    // for the citation cache + a jurisdiction key for the lookups.
    research?: {
      supabase: import("https://esm.sh/@supabase/supabase-js@2.45.0").SupabaseClient;
      jurisdictionKey: string;
      maxCitations?: number;
      // If the Surveyor has already resolved a full profile for this submittal,
      // pass it here so each research() call gets jurisdiction-specific sources
      // and does NOT search against irrelevant jurisdictions.
      jurisdictionProfile?: JurisdictionProfile;
    };
  } = {},
): Promise<TriageReport> {
  const useLlm = options.useLlm !== false;

  // 1. Extract scope (LLM + regex hybrid, with cross-check)
  const scope = await extractScope(llm,
    { ...ctx, purpose: "extract_scope" },
    planText,
    { useLlm },
  );

  // 1b. Attach address-derived overlay data from Surveyor profile.
  //     These are GIS-resolved facts, not plan-text-derived, so they're
  //     injected here rather than coming out of extractScope().
  const jp = options.research?.jurisdictionProfile;
  if (jp?.wuiZone) {
    scope.wui_zone = jp.wuiZone;
  }
  // Inject property overlay ambiguities (flood zone, coastal zone, LADBS,
  // WUI) into the scope so they surface in completeness reviewer questions.
  if (jp?.propertyProfile) {
    const overlayAmbs = propertyOverlayAmbiguities(jp.propertyProfile);
    if (overlayAmbs.length > 0) {
      scope.ambiguities = [...scope.ambiguities, ...overlayAmbs];
    }
  }

  // 1c. ARCHETYPE GATE.
  //     Classify the project before doing any rule evaluation. If it
  //     falls outside the pilot scope, we return early with an empty
  //     finding set and an explicit "out_of_pilot_scope" verdict —
  //     better to surface "we don't review this kind of project yet"
  //     than to pretend the AI is competent on it.
  const archetype = classifyArchetype(
    scope,
    jp?.propertyProfile ?? null,
    planText,
    agency.pilot_archetypes,
  );
  if (!archetype.in_pilot_scope) {
    const banner = renderArchetypeBanner(archetype);
    return {
      pipeline_version: PIPELINE_VERSION,
      generated_at: new Date().toISOString(),
      scope,
      findings: [],
      archetype,
      completeness: {
        score: 0,
        grade: "F",
        headline: banner,
        missing_items: [],
        reviewer_questions: [
          "This submittal is outside the AI pilot scope — manual review required.",
          ...archetype.reasoning,
        ],
        assessment: banner,
      },
      llm_metadata: {
        used_llm: false,
        model: "archetype-gate",
        cost_estimate_usd: 0,
      },
      stats: { total: 0, pass: 0, fail: 0, warn: 0, info: 0 },
    };
  }

  // 2. Determine the active rule set for this agency.
  //    Merge in CalFire WUI rules when the jurisdiction profile is CA.
  const isCaliforniaJurisdiction =
    options.research?.jurisdictionProfile?.state === "CA"
    || options.research?.jurisdictionKey?.startsWith("CA:");
  const extraSystemRules: Rule[] = isCaliforniaJurisdiction
    ? [...CALFIRE_WUI_RULES, ...CALGREEN_MANDATORY_RULES]
    : [];
  const rules = rulesForAgency(
    [...BASELINE_RULES, ...extraSystemRules],
    agency.custom_rules ?? [],
    agency.rule_overrides ?? {},
  );

  // 3. Run deterministic evaluation
  const findings = evaluateAll(rules, scope, planText);

  // 4. LLM completeness judgment (or deterministic fallback)
  const completeness = useLlm
    ? await completenessJudgment(llm,
        { ...ctx, purpose: "completeness_judgment" }, scope, findings, planText)
    : deterministicCompleteness(findings);

  // 4b. (NEW) Research step: enrich the most important failing findings
  //     with verified code citations retrieved live from authoritative
  //     sources. Capped at a small number per audit because each one
  //     costs ~$0.05-0.20 in LLM + search fees.
  //     Also runs an upfront amendment-diff lookup (no LLM, ~2ms) so
  //     reviewers see local LABC amendments alongside the base citation.
  if (options.research && useLlm) {
    const { research: researchFn } = await import("./research.ts");
    const { lookupAmendment, applyAmendmentNote } = await import("./amendments.ts");
    const cap = options.research.maxCitations ?? PIPELINE_GATES.research_max_citations_per_run;
    // Prioritize rules that requires_citation, then critical/major fails
    const toEnrich = findings
      .filter(f => f.status === "fail" && f.requires_citation
                && (f.severity === "critical" || f.severity === "major"))
      .slice(0, cap);
    for (const f of toEnrich) {
      try {
        const r = await researchFn(llm, options.research.supabase, ctx, {
          jurisdictionKey: options.research.jurisdictionKey,
          codeRef: f.code_ref,
          context: `Finding summary: ${f.summary}. Rule: ${f.description}`,
          jurisdictionProfile: options.research.jurisdictionProfile,
        });
        if (r.citation) {
          f.citation = {
            text: r.citation.citation_text,
            source_url: r.citation.source_url,
            source_title: r.citation.source_title,
            source_domain: r.citation.source_domain,
            confidence: r.citation.confidence,
            notes: r.citation.notes,
          };
        }
        // Amendment lookup is independent of the research outcome —
        // even when the researcher cites the base code, we want the
        // reviewer to know if there's a local override.
        const amendment = await lookupAmendment(
          options.research.supabase,
          options.research.jurisdictionKey,
          f.code_ref,
        );
        applyAmendmentNote(f, amendment);
      } catch (err) {
        console.warn(`research failed for ${f.rule_id}:`, err);
      }
    }
  }

  // 4c. CITATION GATE.
  //     Every "fail" on a rule with requires_citation=true must carry a
  //     verified citation (confidence ≥ 0.5) before being shown as fail.
  //     Anything that survived the research step uncited gets downgraded
  //     to "warn" with an explanatory note, and the reviewer is told
  //     why. This is the single biggest false-positive killer.
  for (const f of findings) {
    if (f.status !== "fail" || !f.requires_citation) continue;
    const cited = f.citation && f.citation.confidence >= PIPELINE_GATES.citation_min_confidence;
    if (cited) continue;
    f.status = "warn";
    f.summary = `[NEEDS CITATION] ${f.summary} — auto-downgraded from fail; reviewer must confirm against the cited code section before flagging the applicant.`;
    // Lower confidence to reflect the gap
    f.confidence = Math.min(f.confidence, PIPELINE_GATES.citation_min_confidence);
  }

  // 4d. ADVERSARIAL CRITIC.
  //     For every surviving fail (critical/major), run a cross-model
  //     adversarial critique. Disagreements either downgrade the
  //     finding (high-conf dissent) or flag it for the human queue
  //     (low-conf dissent). Capped at 5/run to bound cost.
  if (useLlm) {
    const { critiqueFinding, applyCritique } = await import("./critic.ts");
    const toCritique = findings
      .filter(f => f.status === "fail" && (f.severity === "critical" || f.severity === "major"))
      .slice(0, PIPELINE_GATES.critic_max_findings_per_run);
    for (const f of toCritique) {
      const verdict = await critiqueFinding(
        llm,
        { ...ctx, purpose: "adversarial_critique" },
        { scope, finding: f, planTextExcerpt: planText.slice(0, 8000) },
      );
      applyCritique(f, verdict);
    }
  }

  // 5. Order findings: fail > warn > info > pass, then by severity
  const SEV_RANK: Record<string, number> = { critical: 0, major: 1, moderate: 2, minor: 3 };
  const STATUS_RANK: Record<string, number> = { fail: 0, warn: 1, info: 2, pass: 3 };
  findings.sort((a, b) =>
    STATUS_RANK[a.status] - STATUS_RANK[b.status]
    || SEV_RANK[a.severity] - SEV_RANK[b.severity]
    || a.rule_id.localeCompare(b.rule_id),
  );

  const stats = {
    total: findings.length,
    pass: findings.filter(f => f.status === "pass").length,
    fail: findings.filter(f => f.status === "fail").length,
    warn: findings.filter(f => f.status === "warn").length,
    info: findings.filter(f => f.status === "info").length,
  };

  return {
    pipeline_version: PIPELINE_VERSION,
    generated_at: new Date().toISOString(),
    scope,
    findings,
    archetype,
    completeness,
    llm_metadata: {
      used_llm: useLlm,
      model: useLlm ? "claude-sonnet-4-6" : "deterministic-only",
      // Cost is recorded per-call in llm_usage; this is a placeholder
      cost_estimate_usd: 0,
    },
    stats,
  };
}
