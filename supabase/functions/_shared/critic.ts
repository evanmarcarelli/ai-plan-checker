// =====================================================================
// Adversarial cross-model critic.
//
// Every "fail" finding the pipeline emits gets a second pass from a
// different model than the one that produced the underlying scope
// extraction. The critic is prompted ADVERSARIALLY — "find the reason
// this flag is wrong" — rather than asked to agree. Findings the
// critic disputes are downgraded with a `disputed_by_critic` annotation
// and routed to the human-review queue with maximum priority.
//
// Why adversarial: same-model critique tends to confirm rather than
// challenge. The same family of failure modes (hallucinated cross-
// references, missed sprinkler-mode negation, etc.) lives in both the
// proposer and the critic when they share weights. Splitting models is
// the cheapest way to get an independent read.
//
// Default proposer/critic split:
//   Proposer = Sonnet (used in extraction + research)
//   Critic   = Opus   (slower, sharper)
//
// Cost: ~$0.02-0.05 per critique. Capped to 5 findings per submittal.
// =====================================================================
import { LlmClient, LlmCallContext } from "./llm.ts";
import type { Finding } from "./evaluate.ts";
import type { BuildingScope } from "./extract.ts";
import { PIPELINE_GATES } from "./pilot_config.ts";

export interface CritiqueVerdict {
  // The critic AGREES the finding is a real violation worth flagging.
  agrees: boolean;
  // 0-1, the critic's confidence that the proposer is correct.
  confidence: number;
  // Short, reviewer-facing rebuttal text — present when agrees=false.
  dissent_reasoning?: string;
  // The model that did the critique (for audit).
  critic_model: string;
}

const CRITIC_SCHEMA = {
  type: "object",
  properties: {
    agrees:           { type: "boolean" },
    confidence:       { type: "number", minimum: 0, maximum: 1 },
    dissent_reasoning:{ type: "string" },
  },
  required: ["agrees", "confidence"],
};

const CRITIC_SYSTEM = `You are an adversarial code reviewer auditing another AI's findings on
a building permit plan set. Your job is NOT to agree with the proposer's flag — your
job is to FIND THE REASON THE FLAG IS WRONG.

A flag is wrong when ANY of these is true:
  - The proposer misread the plan text (occupancy, area, type, OL).
  - The cited code section does not actually apply to this occupancy / configuration.
  - The proposer's check ignored a sprinkler / frontage / NFPA increase that would clear it.
  - The proposer flagged a missing item that is actually present elsewhere in the text.
  - The deterministic check fired but the extracted input was low-confidence.
  - The local jurisdiction amended the section in a way the proposer didn't consider.

If, after looking carefully, you cannot find a reason the flag is wrong, agree —
but only then. Default to skepticism. Adversarial means adversarial.

Output JSON:
  agrees: boolean — true ONLY if you cannot find a reason the flag is wrong
  confidence: 0-1 — how confident YOU are in your verdict (not the proposer's)
  dissent_reasoning: required when agrees=false; one sentence explaining the rebuttal.

Respond with JSON only. No prose.`;

export interface CritiqueInput {
  scope: BuildingScope;
  finding: Finding;
  // Optional verbatim slice from the plan text relevant to the finding.
  // The critic uses this to verify extraction was correct.
  planTextExcerpt?: string;
}

export async function critiqueFinding(
  llm: LlmClient,
  ctx: LlmCallContext,
  input: CritiqueInput,
  options: { criticModel?: string } = {},
): Promise<CritiqueVerdict> {
  // Default critic = Opus (different family from Sonnet proposer).
  // Caller can override (e.g. tests use a fast model).
  const criticModel = options.criticModel ?? "claude-opus-4-7";

  const summary = {
    rule_id: input.finding.rule_id,
    code_ref: input.finding.code_ref,
    severity: input.finding.severity,
    status: input.finding.status,
    proposer_summary: input.finding.summary,
    extracted_scope: {
      occupancies:        input.scope.occupancies,
      occupancy_primary:  input.scope.occupancy_primary,
      construction_type:  input.scope.construction_type,
      building_area_sf:   input.scope.building_area_sf,
      per_story_area_sf:  input.scope.per_story_area_sf,
      stories_above:      input.scope.stories_above,
      height_ft:          input.scope.height_ft,
      sprinklered:        input.scope.sprinklered,
      occupant_load:      input.scope.occupant_load,
    },
    scope_confidence: input.scope.confidence,
    cited_text: input.finding.citation?.text ?? null,
  };

  try {
    const result = await llm.structured<{ agrees: boolean; confidence: number; dissent_reasoning?: string }>(
      ctx,
      {
        model: criticModel,
        system: CRITIC_SYSTEM,
        user:
`Here is the finding to critique.

<finding>
${JSON.stringify(summary, null, 2)}
</finding>

${input.planTextExcerpt
  ? `<plan_text_excerpt>\n${input.planTextExcerpt.slice(0, 4000)}\n</plan_text_excerpt>`
  : "(no plan-text excerpt provided)"}

Find the reason this flag is wrong. If you cannot find one, agree.`,
        schema: CRITIC_SCHEMA,
        // Default to "needs human review" if the critique itself fails —
        // safer than silently accepting an uncritiqued fail.
        fallback: {
          agrees: false,
          confidence: 0,
          dissent_reasoning: "Critic call failed; treat finding as unverified.",
        },
        maxRetries: 1,
        timeoutMs: 45_000,
      },
    );

    return {
      agrees: result.agrees,
      confidence: result.confidence,
      dissent_reasoning: result.dissent_reasoning,
      critic_model: criticModel,
    };
  } catch (err) {
    console.warn(`[critic] critique failed for ${input.finding.rule_id}:`, err);
    return {
      agrees: false,
      confidence: 0,
      dissent_reasoning: `Critic exception: ${(err as Error).message}`,
      critic_model: criticModel,
    };
  }
}

/**
 * Apply the critic verdict to the finding in-place.
 *   - Critic agrees:                       leave as fail; bump confidence.
 *   - Critic disagrees with high conf:     downgrade to "warn", attach dissent.
 *   - Critic disagrees with low conf:      leave as fail but flag for human queue.
 *
 * The mutation surface is intentionally narrow — `status`, `confidence`,
 * `summary` only. Downstream dashboards / comment drafting stay
 * untouched.
 */
export function applyCritique(finding: Finding, verdict: CritiqueVerdict): void {
  if (verdict.agrees) {
    // Critic backs the proposer — multiply confidence (capped at 0.98)
    finding.confidence = Math.min(0.98, finding.confidence * 1.1);
    return;
  }
  // High-confidence dissent → downgrade (threshold from pilot_config)
  if (verdict.confidence >= PIPELINE_GATES.critic_hard_downgrade_confidence) {
    finding.status = "warn";
    finding.summary =
      `[DISPUTED BY CRITIC — ${verdict.critic_model}] ${finding.summary} ` +
      `Rebuttal: ${verdict.dissent_reasoning ?? "no reasoning provided"}.`;
    finding.confidence = Math.min(finding.confidence, 0.4);
    return;
  }
  // Low-confidence dissent → leave as fail but lower confidence so the
  // dashboard routes this to human review with a "models disagree" tag.
  finding.summary =
    `[CRITIC DISSENT — low conf ${(verdict.confidence * 100).toFixed(0)}%] ${finding.summary} ` +
    `Concern: ${verdict.dissent_reasoning ?? "no reasoning provided"}.`;
  finding.confidence = Math.min(finding.confidence, 0.6);
}
