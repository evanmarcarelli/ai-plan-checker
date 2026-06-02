// =====================================================================
// Deterministic rule evaluator.
//
// Takes the extracted scope + the active rule set, and produces a list
// of findings. This is the *trustworthy* layer of the pipeline — every
// finding here is the result of a fixed predicate against extracted
// values, with no LLM judgment involved.
// =====================================================================
import { Rule, HIGH_RISE_FT } from "./rules.ts";
import { BuildingScope, EvidenceLocation, TextBlock } from "./extract.ts";
import {
  checkAllowableArea, checkAllowableStories,
  checkMinExits, checkExitCapacity, checkFixtures,
} from "./checkers.ts";
import { searchCodeChunks, CORPUS_CITE_THRESHOLD } from "./corpus.ts";
import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

export type Status = "pass" | "fail" | "warn" | "info";

export interface Finding {
  rule_id: string;
  code_ref: string;
  description: string;
  discipline: string;
  severity: string;
  status: Status;
  summary: string;
  evidence: string[];
  // Confidence the deterministic check is *correct*, given input quality.
  // Always 1.0 when scope inputs are confident; lower when scope inputs
  // were uncertain (extracted with confidence < 0.7).
  confidence: number;
  // Whether the triage runner must attach a verified citation before
  // surfacing this as a "fail". Mirrors Rule.requires_citation. When
  // true and no citation is produced, the runner downgrades fail → warn.
  requires_citation: boolean;
  // Where on the planset the supporting evidence lives. Drives the PDF
  // annotation overlay in the reviewer dashboard. Null when the finding
  // is a missing-element check ("expected NFPA 13 callout, found none")
  // or when no text_blocks were available at evaluation time.
  evidence_location?: EvidenceLocation | null;
  // Set by verifyCorpusCitations when the rule's code_ref produced no
  // sufficiently-similar chunk in the pre-indexed corpus. The live
  // researcher step gets a chance to find it; if it still can't, the
  // final citation gate downgrades fail -> warn. Drives the
  // "Citation unverified — confirm before sending" badge.
  citation_unverified?: boolean;
  // Optional verified citation produced by the Researcher. Present only
  // for findings that the research step looked up — typically the
  // failing critical/major ones.
  citation?: {
    text: string;
    source_url: string;
    source_title: string;
    source_domain: string;
    confidence: number;
    notes?: string;
  };
}

// Map a rule's check.type to the BuildingScope evidence key whose
// extracted verbatim snippet is the best provenance for that finding.
// Used to attach evidence_location after the deterministic evaluation.
function primaryEvidenceKey(rule: Rule): string | null {
  switch (rule.check.type) {
    case "occupancy_declared":         return "occupancies";
    case "construction_type_declared": return "construction_type";
    case "occupant_load_declared":     return "occupant_load";
    case "allowable_area_check":       return "building_area_sf";
    case "stories_check":              return "stories_above";
    case "high_rise_check":            return "height_ft";
    case "mixed_occupancy_check":      return "occupancies";
    case "num_exits_check":            return "occupant_load";
    case "exit_capacity_check":        return "occupant_load";
    case "panic_hardware_check":       return "panic_hardware_called_out";
    case "plumbing_fixture_calc":      return "occupancy_primary";
    default:                            return null;
  }
}

// Find the first text_block that contains any of the matched hits from
// a required_keyword check. Used when the rule passed (so we have a
// concrete substring to point at in the PDF).
function locateKeywordMatch(
  hits: string[],
  blocks: TextBlock[],
): EvidenceLocation | null {
  if (!blocks?.length || !hits?.length) return null;
  for (const hit of hits) {
    const needle = hit.toLowerCase().trim();
    if (!needle) continue;
    for (const b of blocks) {
      if (b.text.toLowerCase().includes(needle)) {
        return { text: hit, page: b.page, bbox: b.bbox, sheet: b.sheet ?? null };
      }
    }
  }
  return null;
}

export function evaluateAll(
  rules: Rule[],
  scope: BuildingScope,
  fullText: string,
  textBlocks: TextBlock[] = [],
): Finding[] {
  return rules.map(r => {
    const f = evaluate(r, scope, fullText);
    // Default to true if rule didn't specify — safer to require a citation
    // and rarely downgrade than to silently emit uncited fails.
    f.requires_citation = r.requires_citation ?? true;

    // Attach evidence_location. Two sources, in priority order:
    //   1. For typed checks, look up scope.evidence[<primary field>].
    //   2. For required_keyword passes, scan text_blocks for the hit.
    // Leaves evidence_location null when nothing applicable is found —
    // typically the missing-keyword failure case ("not found anywhere").
    const evKey = primaryEvidenceKey(r);
    let loc: EvidenceLocation | null = evKey ? (scope.evidence?.[evKey] ?? null) : null;
    if (!loc && r.check.type === "required_keyword" && f.status === "pass") {
      loc = locateKeywordMatch(f.evidence, textBlocks);
    }
    f.evidence_location = loc;

    return f;
  });
}

function evaluate(rule: Rule, scope: BuildingScope, fullText: string): Finding {
  const base = {
    rule_id: rule.id,
    code_ref: rule.code_ref,
    description: rule.description,
    discipline: rule.discipline,
    severity: rule.severity,
  };
  const confidence = baseConfidence(rule, scope);

  const t = rule.check.type;

  // -------- declared / required-keyword checks ----------------------
  if (t === "occupancy_declared") {
    if (scope.occupancies.length) {
      return mk(base, "pass", `Occupancy declared: ${scope.occupancies.join(", ")}.`, scope.occupancies, confidence);
    }
    return mk(base, "fail", "No occupancy group declared.", [], confidence);
  }
  if (t === "construction_type_declared") {
    if (scope.construction_type) {
      return mk(base, "pass", `Construction Type declared: ${scope.construction_type}.`, [scope.construction_type], confidence);
    }
    return mk(base, "fail", "Construction Type not declared.", [], confidence);
  }
  if (t === "occupant_load_declared") {
    if (scope.occupant_load != null) {
      return mk(base, "pass", `Occupant load declared: ${scope.occupant_load}.`, [String(scope.occupant_load)], confidence);
    }
    return mk(base, "fail", "No occupant load declared.", [], confidence);
  }

  // -------- table-driven numeric checks (delegated to pure functions) --
  // Arithmetic + table lookups live in checkers.ts so they are
  // independently unit-tested. evaluate.ts only assembles the input
  // shape from the BuildingScope.
  if (t === "allowable_area_check") {
    const r = checkAllowableArea({
      occupancyPrimary: scope.occupancy_primary,
      constructionType: scope.construction_type,
      areaSf: scope.per_story_area_sf ?? scope.building_area_sf,
    });
    return mk(base, r.status, r.summary, r.evidence ?? [],
      r.status === "info" ? 1 : confidence);
  }

  if (t === "stories_check") {
    const r = checkAllowableStories({
      occupancyPrimary: scope.occupancy_primary,
      constructionType: scope.construction_type,
      storiesAbove: scope.stories_above,
      sprinklered: scope.sprinklered,
    });
    return mk(base, r.status, r.summary, r.evidence ?? [],
      r.status === "info" ? 1 : confidence);
  }

  if (t === "high_rise_check") {
    if (scope.height_ft == null) return mk(base, "info", "Height not declared.", [], 1);
    if (scope.height_ft <= HIGH_RISE_FT) {
      return mk(base, "pass", `Below ${HIGH_RISE_FT} ft threshold — IBC 403 not triggered.`, [], confidence);
    }
    const reqs: [RegExp, string][] = [
      [/smoke\s+control/i, "smoke control"],
      [/voice\s+(?:alarm|evacuation|notification)/i, "voice alarm"],
      [/standby\s+power|emergency\s+generator/i, "standby power"],
      [/responder\s+radio|\bBDA\b|\bDAS\b/i, "emergency responder radio"],
    ];
    const missing = reqs.filter(([re]) => !re.test(fullText)).map(([, n]) => n);
    if (missing.length) {
      return mk(base, "fail", `High-rise (${scope.height_ft} ft) missing IBC 403 provisions: ${missing.join(", ")}.`, [], confidence);
    }
    return mk(base, "pass", "High-rise provisions addressed.", [], confidence);
  }

  if (t === "mixed_occupancy_check") {
    if (!scope.mixed_occupancy) {
      return mk(base, "pass", "Single occupancy — IBC 508 separation not required.", [], confidence);
    }
    if (/accessory\s+occupanc|non[-\s]?separated|separated\s+occupanc|508\.\d/i.test(fullText)) {
      return mk(base, "pass", `Mixed occupancy (${scope.occupancies.join("/")}) with IBC 508 strategy declared.`, [], confidence);
    }
    return mk(base, "fail", `Mixed occupancy (${scope.occupancies.join("/")}) but no IBC 508 strategy declared.`, [], confidence);
  }

  if (t === "num_exits_check") {
    // Extract the input (count of labeled exits) here from raw text;
    // delegate the arithmetic to checkers.ts.
    const exits = new Set<string>();
    const negRe = /\b(?:no|not|without|missing|only|lacks?)\s+(?:\w+\s+){0,5}?$/i;
    const re = /\b(exit|stair)\s+([A-Z]|[1-9])\b/gi;
    let m: RegExpExecArray | null;
    while ((m = re.exec(fullText)) !== null) {
      const before = fullText.slice(Math.max(0, m.index - 60), m.index);
      if (negRe.test(before)) continue;
      exits.add(`${m[1]} ${m[2]}`.toUpperCase());
    }
    const r = checkMinExits({
      occupantLoad: scope.occupant_load,
      declaredExits: exits.size,
    });
    return mk(base, r.status, r.summary,
      r.status === "pass" ? [...exits].slice(0, 6) : [...exits],
      r.status === "info" ? 1 : confidence);
  }

  if (t === "exit_capacity_check") {
    // Sum visible "EXIT DOOR XX\"" callouts; delegate arithmetic.
    const re = /(?:exit|egress|stair)\s+door[^\n]{0,25}(\d{1,3})\s*["″]/gi;
    let totalDoor = 0, totalStair = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(fullText)) !== null) {
      const w = parseInt(m[1], 10);
      if (/stair/i.test(m[0])) totalStair += w; else totalDoor += w;
    }
    const r = checkExitCapacity({
      occupantLoad: scope.occupant_load,
      declaredDoorWidthIn: totalDoor,
      declaredStairWidthIn: totalStair,
    });
    return mk(base, r.status, r.summary, r.evidence ?? [],
      r.status === "info" ? 1 : confidence);
  }

  if (t === "panic_hardware_check") {
    const triggers = scope.occupancies.some(o => o.startsWith("A") || o.startsWith("E"))
                  && (scope.occupant_load == null || scope.occupant_load >= 50);
    if (!triggers) return mk(base, "pass", "Occupancy does not trigger panic hardware.", [], confidence);
    if (scope.panic_hardware_called_out) return mk(base, "pass", "Panic hardware called out.", [], confidence);
    return mk(base, "fail",
      `Group ${scope.occupancies.filter(o => o.startsWith("A") || o.startsWith("E")).join(", ")} requires panic hardware; no callout found.`,
      [], confidence);
  }

  if (t === "plumbing_fixture_calc") {
    const wcM = fullText.match(/(?:water\s+closets?|\bWC\b)\s*[:=]?\s*(\d{1,3})/i);
    const lavM = fullText.match(/(?:lavator(?:y|ies)|\bLAV\b)\s*[:=]?\s*(\d{1,3})/i);
    const r = checkFixtures({
      occupancyPrimary: scope.occupancy_primary,
      occupantLoad: scope.occupant_load,
      actualWc: wcM ? parseInt(wcM[1], 10) : null,
      actualLav: lavM ? parseInt(lavM[1], 10) : null,
    });
    return mk(base, r.status, r.summary, r.evidence ?? [],
      r.status === "info" ? 1 : confidence);
  }

  // -------- CalFire WUI zone checks --------------------------------
  // These only produce substantive findings when scope.wui_zone is set
  // (i.e., when the Surveyor resolved a CA address via CalFire FHSZ).
  // For non-CA or missing-address jobs they produce "info" so they
  // don't pollute the finding list.

  if (t === "wui_zone_check") {
    if (!scope.wui_zone) {
      return mk(base, "info", "WUI zone not resolved (no CA address or not a CA jurisdiction).", [], 1);
    }
    const { in_wui, haz_class, sra_type, county } = scope.wui_zone;
    const sraLabel = sra_type ? ` (${sra_type})` : "";
    const countyLabel = county ? ` — ${county} County` : "";
    if (!in_wui || !haz_class) {
      return mk(base, "pass",
        `Address is not in a CalFire-designated FHSZ${countyLabel}. CBC Chapter 7A not triggered.`,
        [], 1);
    }
    // In WUI zone: check that the plan references Chapter 7A materials
    const wuiKeywords = /chapter\s*7[Aa]|7A\s+material|ignition[-\s]resist|WUI|wildland[-\s]urban/i;
    if (wuiKeywords.test(fullText)) {
      return mk(base, "pass",
        `${haz_class} FHSZ${sraLabel}${countyLabel}. CBC Chapter 7A materials referenced in plans.`,
        [], confidence);
    }
    return mk(base, "fail",
      `Project is in a ${haz_class} FHSZ${sraLabel}${countyLabel}. CBC Chapter 7A wildfire-resistive construction required but not addressed in submittal.`,
      [`${haz_class} FHSZ${sraLabel}`], confidence);
  }

  if (t === "wui_vent_check") {
    if (!scope.wui_zone?.in_wui) {
      return mk(base, "info", "Not in WUI zone — CBC Section 708A ember-resistant vent requirement not triggered.", [], 1);
    }
    if (/ember[-\s]resist|708[Aa]|WUI\s+vent|CalFire.{0,30}vent/i.test(fullText)) {
      return mk(base, "pass", "Ember-resistant vent specification found (CBC 708A).", [], confidence);
    }
    return mk(base, "warn",
      `${scope.wui_zone.haz_class} FHSZ: No ember-resistant vent specification found. CBC Section 708A requires CalFire-listed vents in WUI zones.`,
      [], confidence);
  }

  if (t === "wui_deck_check") {
    if (!scope.wui_zone?.in_wui) {
      return mk(base, "info", "Not in WUI zone — CBC Section 709A deck material requirement not triggered.", [], 1);
    }
    if (/ignition[-\s]resist.*deck|deck.*ignition[-\s]resist|noncombustible.*deck|deck.*noncombustible|709[Aa]/i.test(fullText)) {
      return mk(base, "pass", "Deck ignition-resistant material spec found (CBC 709A).", [], confidence);
    }
    return mk(base, "warn",
      `${scope.wui_zone.haz_class} FHSZ: No ignition-resistant deck material specification found. CBC Section 709A applies.`,
      [], confidence);
  }

  // -------- generic keyword checks ----------------------------------
  if (t === "required_keyword") {
    const patterns = (rule.check.patterns as string[] | undefined) ?? [];
    const hits: string[] = [];
    for (const p of patterns) {
      const m = fullText.match(new RegExp(p, "i"));
      if (m) hits.push(m[0]);
    }
    if (hits.length) return mk(base, "pass", `Required keyword(s) present: ${[...new Set(hits)].slice(0, 3).join(", ")}`, hits.slice(0, 3), confidence);
    return mk(base, "fail", `Required keyword not found. ${rule.description}`, [], confidence);
  }

  return mk(base, "info", "Unknown check type — skipped.", [], 1);
}

function mk(
  base: { rule_id: string; code_ref: string; description: string; discipline: string; severity: string },
  status: Status, summary: string, evidence: string[], confidence: number,
): Finding {
  // requires_citation is overwritten by evaluateAll() after this mk()
  // call; default true here for type-correctness of the partial object.
  return { ...base, status, summary, evidence, confidence, requires_citation: true };
}

// =====================================================================
// Corpus citation gate
//
// Runs after evaluateAll() and BEFORE the live researcher step. For
// every fail with requires_citation=true, look up the rule's code_ref
// in the pre-indexed corpus. Two outcomes:
//
//   - high similarity (>= CORPUS_CITE_THRESHOLD): attach top chunk as
//     finding.citation. The live researcher skips already-cited
//     findings, so this is also a cost-saver.
//   - low similarity / no hit: set citation_unverified, downgrade
//     severity one tier (critical->major, major->moderate). The live
//     researcher still gets a chance to attach a citation; if it
//     succeeds it should clear citation_unverified. The final
//     citation gate in triage.ts handles still-uncited fails.
//
// Pure side-effect on the findings array (mutates citation, severity,
// citation_unverified). Returns nothing — easier to reason about than
// a "fixed-up copy" since downstream code already mutates findings.
// =====================================================================
const SEVERITY_DOWNGRADE: Record<string, string> = {
  critical: "major",
  major: "moderate",
  moderate: "minor",
  minor: "minor",
};

export async function verifyCorpusCitations(
  findings: Finding[],
  supabase: SupabaseClient,
  jurisdictionKey: string,
): Promise<void> {
  for (const f of findings) {
    if (f.status !== "fail" || !f.requires_citation) continue;
    if (f.citation) continue;  // already cited by an earlier pass

    try {
      const result = await searchCodeChunks(
        supabase,
        `${f.code_ref}: ${f.description}`,
        { jurisdictionKey, exactSectionRef: f.code_ref, topK: 3 },
      );

      if (result.hitFound
          && result.bestSimilarity >= CORPUS_CITE_THRESHOLD
          && result.chunks.length > 0) {
        const top = result.chunks[0];
        let domain = "code-corpus";
        if (top.source_url) {
          try { domain = new URL(top.source_url).hostname; } catch { /* noop */ }
        }
        f.citation = {
          // ICC licensing: keep verbatim excerpt <= 200 chars in user-facing output.
          text: top.chunk_text.slice(0, 200),
          source_url: top.source_url ?? "",
          source_title: top.section_title
            ? `${top.section_ref ?? top.corpus_key} — ${top.section_title}`
            : (top.section_ref ?? top.code_name),
          source_domain: domain,
          confidence: top.similarity,
          notes: `Verified against pre-indexed corpus (${(top.similarity * 100).toFixed(0)}% match, ${result.source}).`,
        };
      } else {
        f.citation_unverified = true;
        f.severity = SEVERITY_DOWNGRADE[f.severity] ?? f.severity;
      }
    } catch (err) {
      console.warn(`[citation-gate] corpus lookup failed for ${f.rule_id}:`, err);
      f.citation_unverified = true;
    }
  }
}

function baseConfidence(rule: Rule, scope: BuildingScope): number {
  // Use the lowest scope-input confidence among the inputs the rule needs
  const t = rule.check.type;
  const fields: string[] =
    t === "allowable_area_check" ? ["occupancy_primary", "construction_type", "building_area_sf"] :
    t === "stories_check" ? ["occupancy_primary", "construction_type", "stories_above"] :
    t === "high_rise_check" ? ["height_ft"] :
    t === "num_exits_check" ? ["occupant_load"] :
    t === "exit_capacity_check" ? ["occupant_load"] :
    t === "panic_hardware_check" ? ["occupancies", "occupant_load"] :
    t === "occupancy_declared" ? ["occupancies"] :
    t === "construction_type_declared" ? ["construction_type"] :
    t === "occupant_load_declared" ? ["occupant_load"] :
    [];
  if (!fields.length) return 1;
  let lowest = 1;
  for (const f of fields) {
    const c = scope.confidence[f];
    if (c != null) lowest = Math.min(lowest, c);
  }
  return lowest;
}
