// =====================================================================
// Project archetype classifier.
//
// Runs at intake to decide whether a submittal is inside the current
// pilot scope. Out-of-scope plans get rejected before the rule engine
// even runs — keeping the accuracy claim defensible.
//
// "Pilot scope" is a per-agency allowlist (agencies.pilot_archetypes
// JSONB array). If the column is empty or null, every archetype is
// accepted (legacy / unrestricted operation).
//
// Pure function — no LLM, no network. Inputs are the extracted scope,
// the resolved property overlay (if any), and the raw plan text for
// keyword cues. Reasoning is human-readable so reviewers can see why
// something was excluded.
// =====================================================================
import type { BuildingScope } from "./extract.ts";
import type { PropertyProfile } from "./property.ts";
import { PILOT_ARCHETYPES_DEFAULT } from "./pilot_config.ts";

export type ProjectArchetype =
  // In-pilot — Los Angeles
  | "la_sfr_typ_vb_ministerial"     // Single-family residence, Type V-B, no overlay flags
  | "la_ti_commercial"              // Commercial tenant improvement (no shell modification)
  // In-pilot — Ventura County (unincorporated)
  | "ventura_sfr_typ_vb_ministerial"  // SFR Type V-B outside VHFHSZ and outside Coastal Zone
  | "ventura_ti_commercial"           // Commercial TI in Ventura County, no shell change
  // Out-of-pilot (each maps to a specific human-readable reason)
  | "la_hillside_sfr"               // Subject to Hillside / BHO geometry rules
  | "la_hpoz_property"              // In a Historic Preservation Overlay Zone
  | "la_coastal_zone"               // CA Coastal Commission jurisdiction
  | "ventura_vhfhsz_sfr"            // Ventura County parcel in Very-High FHSZ (CBC Ch. 7A)
  | "ventura_ag_building"           // Agricultural-zoned structure, county-specific exemptions
  | "high_rise_or_mid_rise"         // Building height > 75 ft
  | "multifamily_new_construction"  // R-2/R-1 new build (not TI)
  | "mixed_use_new_construction"
  | "unclassified";                 // Couldn't tell — needs human triage

export interface ArchetypeResult {
  archetype: ProjectArchetype;
  in_pilot_scope: boolean;
  reasoning: string[];           // human-readable bullets explaining why
  excluded_overlays: string[];   // empty when in scope; lists which overlays kicked us out
}

// Default allowlist sourced from pilot_config.ts so a single edit there
// rewires the gate, the brief, and the eval harness simultaneously.
const IN_SCOPE: ReadonlySet<ProjectArchetype> = new Set(PILOT_ARCHETYPES_DEFAULT);

// =====================================================================
// classifyArchetype
//
// Order matters: we check "kicked out by overlay" cases first (cheapest
// reject), then identify the in-scope archetype, then fall back to
// unclassified.
// =====================================================================
export function classifyArchetype(
  scope: BuildingScope,
  property: PropertyProfile | null | undefined,
  planText: string,
  pilotArchetypes?: ProjectArchetype[],
): ArchetypeResult {
  const reasoning: string[] = [];
  const excluded: string[] = [];

  // ---- Jurisdiction detection (plan-text + parcel hint) --------------
  // Used by both LA and Ventura branches to pick the right out-of-scope
  // archetype slug when overlays fire.
  const venturaTextCue =
    /\bventura\s+county\b|\bcounty\s+of\s+ventura\b|\bcamarillo\b|\bsimi\s+valley\b|\bthousand\s+oaks\b|\boxnard\b|\bojai\b|\bmoorpark\b|\bport\s+hueneme\b|\bfillmore\b|\bsanta\s+paula\b/i;
  const isVenturaJurisdiction =
    /ventura/i.test(property?.parcel?.jurisdiction ?? "") ||
    venturaTextCue.test(planText);

  // ---- Hard rejects: address-derived overlays --------------------
  // These are the LA-specific accuracy killers that we deliberately
  // park out of pilot scope until we have ground-truth data on them.
  if (property?.parcel?.zoning_code) {
    const z = property.parcel.zoning_code.toUpperCase();
    if (/H$|HILLSIDE|\bBMO\b|\bBHO\b/i.test(z)) {
      excluded.push("Hillside / BHO zoning");
      reasoning.push(`Parcel zoning code "${z}" indicates Hillside overlay`);
      return finalize("la_hillside_sfr", excluded, reasoning, pilotArchetypes);
    }
  }
  if (property?.coastal_zone?.in_coastal_zone) {
    excluded.push("CA Coastal Zone");
    reasoning.push("Address is inside the CA Coastal Commission jurisdiction");
    return finalize("la_coastal_zone", excluded, reasoning, pilotArchetypes);
  }

  // ---- Ventura County VHFHSZ reject ------------------------------
  // Ventura's biggest accuracy risk: large unincorporated areas sit in
  // Very-High Fire Hazard Severity Zone, which pulls CBC Chapter 7A
  // wildfire-resistive-material requirements into the rule set. We
  // don't have enough ground truth on Ch. 7A material schedules yet,
  // so park these out of pilot until we do.
  if (isVenturaJurisdiction && property?.wui_zone?.in_wui) {
    excluded.push(`Ventura VHFHSZ (${property.wui_zone.haz_class})`);
    reasoning.push(
      `Address falls in CalFire ${property.wui_zone.haz_class} FHSZ — CBC Ch. 7A wildfire-resistive materials review out of pilot scope`,
    );
    return finalize("ventura_vhfhsz_sfr", excluded, reasoning, pilotArchetypes);
  }

  // Plan-text VHFHSZ cue (when GIS isn't resolved). Conservative —
  // only rejects on explicit Ventura + WUI/FHSZ co-mention.
  const wuiTextCue = /\bvery\s+high\s+fire\s+hazard\s+severity\s+zone\b|\bVHFHSZ\b|\bWUI\b|\bChapter\s+7A\b/i;
  if (isVenturaJurisdiction && wuiTextCue.test(planText)) {
    excluded.push("Ventura VHFHSZ (plan-text cue)");
    reasoning.push("Plan text references Ventura County WUI / Very-High FHSZ");
    return finalize("ventura_vhfhsz_sfr", excluded, reasoning, pilotArchetypes);
  }

  // ---- Ventura County agricultural building reject ---------------
  // Ag-zoned structures get county-specific exemptions (Title 8 ag
  // overlay + CBC §312 utility/misc). Outside the pilot until we
  // have fixtures with reviewer-confirmed exemption decisions.
  const agTextCue = /\bagricultural\s+(building|structure|exempt)|\bA-E\b|\bAE-\d|\bopen\s+space\s+agricultural\b/i;
  if (isVenturaJurisdiction && agTextCue.test(planText)) {
    excluded.push("Ventura agricultural building");
    reasoning.push("Plan text indicates an agricultural-zoned structure (county-specific exemptions apply)");
    return finalize("ventura_ag_building", excluded, reasoning, pilotArchetypes);
  }

  // ---- Plan-text overlay cues (when no property profile) ---------
  // The plan set itself often calls out applicable overlays even when
  // GIS isn't resolved. Conservative regex — we only reject on explicit
  // mention.
  const hillsideCues = /\bbaseline\s+hillside|\bBHO\b|\bhillside\s+ordinance\b|\bmulholland\b.*\bspecific\s+plan|RE40-?1H|RE15-?1H/i;
  if (hillsideCues.test(planText)) {
    excluded.push("Hillside / BHO (plan-text cue)");
    reasoning.push("Plan text references Baseline Hillside Ordinance or Hillside zoning");
    return finalize("la_hillside_sfr", excluded, reasoning, pilotArchetypes);
  }
  const hpozCues = /\bHPOZ\b|\bhistoric\s+preservation\s+overlay/i;
  if (hpozCues.test(planText)) {
    excluded.push("HPOZ");
    reasoning.push("Plan text references HPOZ (Historic Preservation Overlay Zone)");
    return finalize("la_hpoz_property", excluded, reasoning, pilotArchetypes);
  }

  // ---- Building scale rejects ----------------------------------------
  if (scope.height_ft != null && scope.height_ft > 75) {
    excluded.push("High-rise (> 75 ft)");
    reasoning.push(`Building height ${scope.height_ft} ft exceeds 75 ft high-rise threshold`);
    return finalize("high_rise_or_mid_rise", excluded, reasoning, pilotArchetypes);
  }
  if (scope.stories_above != null && scope.stories_above >= 5) {
    excluded.push("Mid-rise (≥ 5 stories)");
    reasoning.push(`${scope.stories_above} stories puts this above the pilot single-family / TI scope`);
    return finalize("high_rise_or_mid_rise", excluded, reasoning, pilotArchetypes);
  }

  // ---- In-scope identification ---------------------------------------
  // TI = explicit "tenant improvement" / interior alteration cues
  const tiCues = /\btenant\s+improvement\b|\bTI\b\s+plans?|interior\s+alteration|interior\s+remodel|\bsuite\s+\d/i;
  if (tiCues.test(planText) && !scope.mixed_occupancy) {
    if (isVenturaJurisdiction) {
      reasoning.push("Ventura County commercial tenant improvement");
      return finalize("ventura_ti_commercial", excluded, reasoning, pilotArchetypes);
    }
    reasoning.push("Plan text identifies this as a commercial tenant improvement");
    return finalize("la_ti_commercial", excluded, reasoning, pilotArchetypes);
  }

  // SFR Type V-B = R-3, single occupancy, V-B construction, modest scale
  const isR3 = scope.occupancies.includes("R-3") || scope.occupancy_primary === "R-3";
  const isVB = scope.construction_type === "V-B";
  const modestArea = (scope.per_story_area_sf ?? scope.building_area_sf ?? 0) <= 10_000;
  const lowRise = scope.stories_above == null || scope.stories_above <= 3;

  if (isR3 && isVB && modestArea && lowRise) {
    if (isVenturaJurisdiction) {
      reasoning.push("Ventura County single-family R-3 / Type V-B, ≤ 3 stories, no VHFHSZ or ag overlay");
      return finalize("ventura_sfr_typ_vb_ministerial", excluded, reasoning, pilotArchetypes);
    }
    reasoning.push("Single-family R-3 / Type V-B with modest area and ≤ 3 stories");
    return finalize("la_sfr_typ_vb_ministerial", excluded, reasoning, pilotArchetypes);
  }

  // Multifamily new construction = R-1 or R-2 + no TI cue
  if ((scope.occupancies.includes("R-1") || scope.occupancies.includes("R-2")) && !tiCues.test(planText)) {
    reasoning.push("R-1 / R-2 occupancy without TI markers — multifamily new construction");
    return finalize("multifamily_new_construction", excluded, reasoning, pilotArchetypes);
  }

  // Mixed-use new construction
  if (scope.mixed_occupancy && !tiCues.test(planText)) {
    reasoning.push("Mixed-occupancy declaration without TI markers — likely new construction");
    return finalize("mixed_use_new_construction", excluded, reasoning, pilotArchetypes);
  }

  // Fallback: we couldn't confidently bucket it
  reasoning.push("Could not classify into a known archetype — manual triage required");
  return finalize("unclassified", excluded, reasoning, pilotArchetypes);
}

function finalize(
  archetype: ProjectArchetype,
  excluded: string[],
  reasoning: string[],
  pilotArchetypes?: ProjectArchetype[],
): ArchetypeResult {
  // If the agency hasn't set a pilot allowlist, accept everything that
  // would otherwise be IN_SCOPE. If it has set one, the allowlist wins.
  const allow = pilotArchetypes && pilotArchetypes.length > 0
    ? new Set(pilotArchetypes)
    : IN_SCOPE;
  const inScope = allow.has(archetype);
  return {
    archetype,
    in_pilot_scope: inScope,
    reasoning,
    excluded_overlays: excluded,
  };
}

// =====================================================================
// Human-readable reason for the dashboard / comment letter
// =====================================================================
export function renderArchetypeBanner(result: ArchetypeResult): string {
  if (result.in_pilot_scope) {
    return `In-pilot archetype: ${result.archetype}. AI triage proceeded.`;
  }
  const why = result.excluded_overlays.length
    ? result.excluded_overlays.join("; ")
    : result.reasoning[result.reasoning.length - 1] ?? "Out of current pilot scope";
  return `OUT OF PILOT SCOPE (${result.archetype}). Reason: ${why}. Send to manual review.`;
}
