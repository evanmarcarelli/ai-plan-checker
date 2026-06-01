// =====================================================================
// Scope extraction.
//
// Pulls the building-wide facts out of a plan set's text:
// occupancies, construction type, area, stories, height, sprinkler,
// occupant load, travel distance, etc.
//
// Strategy: run BOTH the LLM and a regex extractor, then reconcile.
// The LLM is much better on messy / non-standard layouts; regex is
// reliable on structured ones and gives us a confidence signal.
// When they disagree, we prefer the LLM if its self-reported confidence
// is high, and we record the discrepancy in the audit log so a reviewer
// can spot-check.
// =====================================================================
import { LlmClient, LlmCallContext } from "./llm.ts";
import { WuiZoneResult } from "./wui.ts";

export interface BuildingScope {
  occupancies: string[];
  occupancy_primary: string | null;
  construction_type: string | null;
  building_area_sf: number | null;
  per_story_area_sf: number | null;
  stories_above: number | null;
  height_ft: number | null;
  sprinklered: boolean | null;
  occupant_load: number | null;
  travel_distance_ft: number | null;
  has_kitchen: boolean;
  has_atrium: boolean;
  has_elevator: boolean;
  has_area_of_refuge: boolean;
  panic_hardware_called_out: boolean;
  mixed_occupancy: boolean;
  // Per-field confidence 0–1, set by the LLM
  confidence: Record<string, number>;
  // Provenance: where each fact came from (sheet name / page / quote)
  evidence: Record<string, string>;
  // What the extractor isn't sure about — drives reviewer questions
  ambiguities: string[];
  // Did we use the LLM or fall back to regex?
  source: "llm" | "regex" | "merged";
  // Address-derived facts (populated externally by the triage runner, not from plan text)
  // WUI zone from CalFire FHSZ GIS — present only for CA projects where address is known.
  wui_zone?: WuiZoneResult;
}

const EMPTY_SCOPE: BuildingScope = {
  occupancies: [], occupancy_primary: null,
  construction_type: null,
  building_area_sf: null, per_story_area_sf: null,
  stories_above: null, height_ft: null,
  sprinklered: null,
  occupant_load: null, travel_distance_ft: null,
  has_kitchen: false, has_atrium: false, has_elevator: false,
  has_area_of_refuge: false, panic_hardware_called_out: false,
  mixed_occupancy: false,
  confidence: {}, evidence: {}, ambiguities: [],
  source: "regex",
};

// =====================================================================
// LLM-based extractor
// =====================================================================
const SCOPE_SCHEMA = {
  type: "object",
  properties: {
    occupancies: { type: "array", items: { type: "string" } },
    occupancy_primary: { type: ["string", "null"] },
    construction_type: { type: ["string", "null"] },
    building_area_sf: { type: ["number", "null"] },
    per_story_area_sf: { type: ["number", "null"] },
    stories_above: { type: ["integer", "null"] },
    height_ft: { type: ["number", "null"] },
    sprinklered: { type: ["boolean", "null"] },
    occupant_load: { type: ["integer", "null"] },
    travel_distance_ft: { type: ["number", "null"] },
    has_kitchen: { type: "boolean" },
    has_atrium: { type: "boolean" },
    has_elevator: { type: "boolean" },
    has_area_of_refuge: { type: "boolean" },
    panic_hardware_called_out: { type: "boolean" },
    confidence: {
      type: "object",
      additionalProperties: { type: "number", minimum: 0, maximum: 1 },
    },
    evidence: { type: "object", additionalProperties: { type: "string" } },
    ambiguities: { type: "array", items: { type: "string" } },
  },
  required: ["occupancies", "construction_type", "stories_above", "height_ft", "occupant_load"],
};

const SCOPE_SYSTEM = `You are a senior building plan reviewer. Your job is to read the
text extracted from a commercial plan set's title sheet, code analysis sheet, and life-safety
plan, and pull out the building-wide facts that drive code analysis.

Rules you MUST follow:
1. Only report facts that are stated explicitly in the text. If a value is not stated, set it to null.
2. NEVER invent or estimate a number that is not in the text.
3. Occupancy groups must use IBC notation: "A-1", "A-2", "A-3", "A-4", "A-5", "B", "E", "F-1", "F-2",
   "H-1"..."H-5", "I-1"..."I-4", "M", "R-1", "R-2", "R-3", "R-4", "S-1", "S-2", "U".
4. Construction Type must be one of: I-A, I-B, II-A, II-B, III-A, III-B, IV, IV-A, IV-B, IV-C, IV-HT, V-A, V-B.
5. For each populated field, include a "confidence" value between 0 and 1
   (1.0 = explicit declaration, 0.7 = inferred from clear context, 0.5 = ambiguous).
6. For each field, include an "evidence" entry: the short verbatim phrase from the
   text that supports the value (max 80 chars, no editorializing).
7. List in "ambiguities" any specific question a human reviewer should resolve
   (e.g., "Two construction types referenced — I-A in code analysis, II-B on cover sheet").
8. If a value would be a guess, leave it null and add it to ambiguities.

Respond with JSON only, matching the requested schema. No prose, no commentary.`;

// =====================================================================
// Regex-based extractor (fallback / cross-check)
// =====================================================================
function regexExtract(text: string): BuildingScope {
  const scope: BuildingScope = JSON.parse(JSON.stringify(EMPTY_SCOPE));
  scope.source = "regex";

  // Occupancy groups
  const occRe = /(?:occupancy\s*(?:group|classification)?\s*(?:[:=]\s*)?|group\s+)([ABEFHIMRS](?:-\d)?(?:\s*,\s*[ABEFHIMRS](?:-\d)?)*)(?=\W|$)/gi;
  const found = new Set<string>();
  let m: RegExpExecArray | null;
  while ((m = occRe.exec(text)) !== null) {
    for (const g of m[1].split(/[,\s]+/)) {
      const s = g.trim().toUpperCase();
      if (/^[ABEFHIMRS](-\d)?$/.test(s)) found.add(s);
    }
  }
  scope.occupancies = [...found];
  scope.mixed_occupancy = scope.occupancies.length > 1;
  scope.occupancy_primary = scope.occupancies[0] ?? null;

  // Construction type
  const ct = text.match(/(?:construction\s+type|type)\s*[:=\-]?\s*([IVX]{1,3})[-\s]?([AB])?/i);
  if (ct) {
    const roman = ct[1].toUpperCase();
    const letter = (ct[2] || "").toUpperCase();
    scope.construction_type = letter ? `${roman}-${letter}` : roman;
  }

  // Area
  const areaRe = /(?:total|building|gross|per[-\s]?story)\s+area\s*[:=\-]?\s*([\d,]+)\s*(?:sf|sq\s*ft|square\s+feet)/gi;
  const areas: number[] = [];
  while ((m = areaRe.exec(text)) !== null) areas.push(parseInt(m[1].replace(/,/g, ""), 10));
  if (areas.length) scope.building_area_sf = Math.max(...areas);
  const ps = text.match(/per[-\s]?story[^\n]{0,40}?([\d,]+)\s*(?:sf|sq\s*ft)/i);
  if (ps) scope.per_story_area_sf = parseInt(ps[1].replace(/,/g, ""), 10);

  // Stories
  const sm = text.match(/(?:stories?\s+above(?:\s+grade)?|number\s+of\s+stories|stories)\s*[:=\-]?\s*(\d{1,2})/i);
  if (sm) scope.stories_above = parseInt(sm[1], 10);

  // Height
  const h = text.match(/(?:building\s+height|height)\s*[:=\-]?\s*(\d{1,3})\s*(?:ft|feet)/i);
  if (h) scope.height_ft = parseInt(h[1], 10);

  // Sprinklered
  if (/\bfully\s+sprinklered\b|sprinkler(?:ed)?\s*[:=]\s*yes|NFPA\s*13/i.test(text)) scope.sprinklered = true;
  else if (/\bnon[-\s]?sprinklered\b|sprinkler(?:ed)?\s*[:=]\s*no/i.test(text)) scope.sprinklered = false;

  // Occupant load
  const olRe = /(?:total\s+)?(?:design\s+)?occupant\s+load\s*[:=\-]?\s*(\d{1,5})/gi;
  const loads: number[] = [];
  while ((m = olRe.exec(text)) !== null) loads.push(parseInt(m[1], 10));
  if (loads.length) scope.occupant_load = Math.max(...loads);

  // Travel distance
  const td = text.match(/travel\s+distance\s*[:=\-]?\s*(\d{1,4})\s*(?:ft|feet)/i);
  if (td) scope.travel_distance_ft = parseInt(td[1], 10);

  // Boolean flags — negation-aware
  scope.has_kitchen = positiveMention(text, /commercial\s+kitchen|kitchen\s+hood|type\s+I\s+hood|ansul/i);
  scope.has_atrium = positiveMention(text, /\batrium\b/i);
  scope.has_elevator = positiveMention(text, /\belevator\b|passenger\s+lift/i);
  scope.has_area_of_refuge = positiveMention(text, /area\s+of\s+refuge/i);
  scope.panic_hardware_called_out = positiveMention(text, /panic\s+hardware|panic\s+bar/i);

  // For regex, confidence is 0.85 for any extracted value (deterministic but not
  // contextually aware), 0 for missing.
  for (const k of Object.keys(scope) as (keyof BuildingScope)[]) {
    if (k === "confidence" || k === "evidence" || k === "ambiguities" || k === "source") continue;
    const v = scope[k];
    const present = v !== null && !(Array.isArray(v) && v.length === 0) && v !== false;
    scope.confidence[k] = present ? 0.85 : 0;
  }

  return scope;
}

function positiveMention(text: string, pattern: RegExp): boolean {
  const global = new RegExp(pattern.source, pattern.flags.includes("g") ? pattern.flags : pattern.flags + "g");
  const negRe = /\b(?:no|not|without|missing|absent|lacks?|n\/a)\s+(?:\w+\s+){0,5}?$/i;
  let m: RegExpExecArray | null;
  while ((m = global.exec(text)) !== null) {
    const before = text.slice(Math.max(0, m.index - 50), m.index);
    if (negRe.test(before)) continue;
    const parenNeg = /\(\s*(?:no|without|missing)\b[^)]*$/i;
    if (parenNeg.test(before)) continue;
    return true;
  }
  return false;
}

// =====================================================================
// Reconciliation: merge LLM + regex outputs, prefer LLM if confident
// =====================================================================
function merge(llm: BuildingScope, rgx: BuildingScope): BuildingScope {
  const out: BuildingScope = JSON.parse(JSON.stringify(EMPTY_SCOPE));
  out.source = "merged";

  // Fields where we prefer the higher-confidence source
  const fields: (keyof BuildingScope)[] = [
    "occupancies", "occupancy_primary", "construction_type",
    "building_area_sf", "per_story_area_sf",
    "stories_above", "height_ft",
    "sprinklered", "occupant_load", "travel_distance_ft",
    "has_kitchen", "has_atrium", "has_elevator",
    "has_area_of_refuge", "panic_hardware_called_out",
    "mixed_occupancy",
  ];
  for (const f of fields) {
    const llmConf = (llm.confidence[f as string] ?? 0);
    const rgxConf = (rgx.confidence[f as string] ?? 0);
    const pickLlm = llmConf >= rgxConf;
    // deno-lint-ignore no-explicit-any
    (out as any)[f] = pickLlm ? (llm as any)[f] : (rgx as any)[f];
    out.confidence[f as string] = Math.max(llmConf, rgxConf);
    if (llm.evidence[f as string]) out.evidence[f as string] = llm.evidence[f as string];
  }

  // Discrepancies become ambiguities for the reviewer
  out.ambiguities = [...(llm.ambiguities ?? [])];
  for (const f of fields) {
    const a = (llm as Record<string, unknown>)[f as string];
    const b = (rgx as Record<string, unknown>)[f as string];
    if (a == null && b == null) continue;
    if (JSON.stringify(a) !== JSON.stringify(b)) {
      out.ambiguities.push(
        `LLM and regex disagree on ${String(f)}: LLM said ${JSON.stringify(a)}, regex said ${JSON.stringify(b)}`,
      );
    }
  }
  // Recompute mixed_occupancy from final occupancies
  out.mixed_occupancy = (out.occupancies?.length ?? 0) > 1;
  return out;
}

// =====================================================================
// Public API
// =====================================================================
export async function extractScope(
  llm: LlmClient,
  ctx: LlmCallContext,
  planText: string,
  options: { useLlm?: boolean } = {},
): Promise<BuildingScope> {
  const useLlm = options.useLlm !== false;

  // Always do the regex pass — it's cheap and acts as a sanity check.
  const regexResult = regexExtract(planText);
  if (!useLlm) return regexResult;

  // Truncate input — only the first ~30K chars typically contain the
  // code analysis sheet. Avoids unnecessary token spend.
  const truncated = planText.slice(0, 30_000);

  let llmResult: BuildingScope;
  try {
    const partial = await llm.structured<Partial<BuildingScope>>(ctx, {
      tier: "balanced",
      system: SCOPE_SYSTEM,
      user:
`Extracted plan-set text follows. Pull the structured facts as instructed.

<plan_text>
${truncated}
</plan_text>`,
      schema: SCOPE_SCHEMA,
    });
    llmResult = {
      ...EMPTY_SCOPE,
      ...partial,
      occupancies: partial.occupancies ?? [],
      mixed_occupancy: (partial.occupancies?.length ?? 0) > 1,
      has_kitchen:                Boolean(partial.has_kitchen),
      has_atrium:                 Boolean(partial.has_atrium),
      has_elevator:               Boolean(partial.has_elevator),
      has_area_of_refuge:         Boolean(partial.has_area_of_refuge),
      panic_hardware_called_out:  Boolean(partial.panic_hardware_called_out),
      confidence: partial.confidence ?? {},
      evidence:   partial.evidence   ?? {},
      ambiguities: partial.ambiguities ?? [],
      source: "llm",
    };
  } catch (err) {
    console.warn("LLM extraction failed; using regex only:", err);
    return regexResult;
  }

  return merge(llmResult, regexResult);
}
