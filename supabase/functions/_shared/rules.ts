// =====================================================================
// AHJ rule knowledge base.
//
// This file is intentionally kept simple: a flat array of typed rules
// the deterministic engine can evaluate. Per-agency overrides and
// custom rules live on the agencies row (rule_overrides / custom_rules
// JSONB columns) and are merged at evaluation time.
//
// For a production deployment, this should be replaced by a curated
// corpus of the IBC under license, organized by chapter + section. The
// current set is enough to demonstrate the system end-to-end.
// =====================================================================
export type Severity = "critical" | "major" | "moderate" | "minor";
export type Discipline =
  | "Architectural" | "Accessibility" | "Structural"
  | "Electrical" | "Mechanical" | "Plumbing"
  | "Fire & Life Safety" | "Energy" | "General" | "Commercial";

export interface Rule {
  id: string;
  discipline: Discipline;
  code_ref: string;
  description: string;
  severity: Severity;
  check: { type: string; [k: string]: unknown };
  // When true, a "fail" produced by this rule MUST carry a verified
  // citation before being surfaced to the reviewer as fail. Findings
  // that fail-without-citation are auto-downgraded to "warn" by the
  // triage runner. Declarative rules (e.g. "occupancy_declared") set
  // this to false because there's nothing to cite — the violation is
  // a structural omission, not a code interpretation.
  requires_citation?: boolean;
}

// Reference tables (abbreviated 2021 IBC values) — used by the rule engine
export const IBC_T506_2: Record<string, Record<string, number | "UL" | "NP">> = {
  "A-1": {"I-A":"UL","I-B":"UL","II-A":15500,"II-B":8500, "III-A":14000,"III-B":8500, "IV":15000,"V-A":11500,"V-B":5500},
  "A-2": {"I-A":"UL","I-B":"UL","II-A":15500,"II-B":9500, "III-A":14000,"III-B":9500, "IV":15000,"V-A":11500,"V-B":6000},
  "A-3": {"I-A":"UL","I-B":"UL","II-A":15500,"II-B":9500, "III-A":14000,"III-B":9500, "IV":15000,"V-A":11500,"V-B":6000},
  "B":   {"I-A":"UL","I-B":"UL","II-A":37500,"II-B":23000,"III-A":28500,"III-B":19000,"IV":36000,"V-A":18000,"V-B":9000},
  "E":   {"I-A":"UL","I-B":"UL","II-A":26500,"II-B":14500,"III-A":23500,"III-B":14500,"IV":25500,"V-A":18500,"V-B":9500},
  "F-1": {"I-A":"UL","I-B":"UL","II-A":25000,"II-B":15500,"III-A":19000,"III-B":12000,"IV":33500,"V-A":14000,"V-B":8500},
  "I-2": {"I-A":"UL","I-B":55000,"II-A":26500,"II-B":"NP","III-A":26500,"III-B":"NP","IV":26500,"V-A":18500,"V-B":"NP"},
  "M":   {"I-A":"UL","I-B":"UL","II-A":21500,"II-B":12500,"III-A":18500,"III-B":12500,"IV":20500,"V-A":14000,"V-B":9000},
  "R-1": {"I-A":"UL","I-B":"UL","II-A":24000,"II-B":16000,"III-A":24000,"III-B":16000,"IV":20500,"V-A":12000,"V-B":7000},
  "R-2": {"I-A":"UL","I-B":"UL","II-A":24000,"II-B":16000,"III-A":24000,"III-B":16000,"IV":20500,"V-A":12000,"V-B":7000},
  "S-1": {"I-A":"UL","I-B":48000,"II-A":26000,"II-B":17500,"III-A":26000,"III-B":17500,"IV":25500,"V-A":14000,"V-B":9000},
  "S-2": {"I-A":"UL","I-B":79000,"II-A":39000,"II-B":26000,"III-A":39000,"III-B":26000,"IV":38500,"V-A":21000,"V-B":13500},
};

export const IBC_T504_4: Record<string, Record<string, number | "UL" | "NP">> = {
  "A-1":{"I-A":"UL","I-B":5, "II-A":3,"II-B":2,"III-A":3,"III-B":2,"IV":3,"V-A":2,"V-B":1},
  "A-2":{"I-A":"UL","I-B":11,"II-A":3,"II-B":2,"III-A":3,"III-B":2,"IV":3,"V-A":2,"V-B":1},
  "A-3":{"I-A":"UL","I-B":11,"II-A":3,"II-B":2,"III-A":3,"III-B":2,"IV":3,"V-A":2,"V-B":1},
  "B":  {"I-A":"UL","I-B":11,"II-A":5,"II-B":3,"III-A":5,"III-B":3,"IV":5,"V-A":3,"V-B":2},
  "E":  {"I-A":"UL","I-B":5, "II-A":3,"II-B":2,"III-A":3,"III-B":2,"IV":3,"V-A":1,"V-B":1},
  "F-1":{"I-A":"UL","I-B":11,"II-A":4,"II-B":2,"III-A":3,"III-B":2,"IV":4,"V-A":2,"V-B":1},
  "I-2":{"I-A":"UL","I-B":5, "II-A":2,"II-B":"NP","III-A":1,"III-B":"NP","IV":1,"V-A":1,"V-B":"NP"},
  "M":  {"I-A":"UL","I-B":11,"II-A":4,"II-B":2,"III-A":4,"III-B":2,"IV":4,"V-A":3,"V-B":1},
  "R-1":{"I-A":"UL","I-B":11,"II-A":4,"II-B":4,"III-A":4,"III-B":4,"IV":4,"V-A":3,"V-B":2},
  "R-2":{"I-A":"UL","I-B":11,"II-A":4,"II-B":4,"III-A":4,"III-B":4,"IV":4,"V-A":3,"V-B":2},
  "S-1":{"I-A":"UL","I-B":11,"II-A":4,"II-B":2,"III-A":3,"III-B":2,"IV":4,"V-A":3,"V-B":1},
  "S-2":{"I-A":"UL","I-B":11,"II-A":5,"II-B":3,"III-A":4,"III-B":3,"IV":4,"V-A":4,"V-B":2},
};

export const MIN_EXITS_BY_LOAD = [
  { maxLoad: 500,    exits: 2 },
  { maxLoad: 1000,   exits: 3 },
  { maxLoad: Infinity, exits: 4 },
];

export const HIGH_RISE_FT = 75;

// =====================================================================
// CalFire WUI rules (CA jurisdictions only)
//
// These rules are injected by the triage runner when the Surveyor
// resolves a CA jurisdiction. They depend on scope.wui_zone which is
// populated from the CalFire FHSZ GIS overlay (not plan text).
//
// For non-CA jurisdictions scope.wui_zone is undefined, so these rules
// produce "info" and don't create false-positive findings.
// =====================================================================
export const CALFIRE_WUI_RULES: Rule[] = [
  {
    id: "FIRE-WUI-7A",
    discipline: "Fire & Life Safety",
    code_ref: "CBC Chapter 7A · CA Gov Code §51182",
    description:
      "Projects in a CalFire High or Very High Fire Hazard Severity Zone (FHSZ) require wildfire-resistive exterior construction per CBC Chapter 7A: ignition-resistant materials for roofing, exterior walls, decks, vents, and glazing.",
    severity: "critical",
    check: { type: "wui_zone_check" },
    requires_citation: true,
  },
  {
    id: "FIRE-WUI-VENT",
    discipline: "Fire & Life Safety",
    code_ref: "CBC Section 708A",
    description:
      "WUI zone: attic, crawl space, and foundation vents must be ember-resistant (CalFire-listed). Verify vent spec on architectural drawings.",
    severity: "major",
    check: { type: "wui_vent_check" },
    requires_citation: true,
  },
  {
    id: "FIRE-WUI-DECK",
    discipline: "Architectural",
    code_ref: "CBC Section 709A",
    description:
      "WUI zone: exterior decks and balconies ≥ 6 ft above grade or in Very High FHSZ must use ignition-resistant or noncombustible material. Deck material spec required.",
    severity: "major",
    check: { type: "wui_deck_check" },
    requires_citation: true,
  },
];

export const BASELINE_RULES: Rule[] = [
  // Building-scale code analysis.
  // Declarative-completeness rules: requires_citation = false (the failure
  // is a missing field, not a code-text interpretation).
  { id:"COM-OCCUPANCY-DECL", discipline:"Commercial", code_ref:"IBC 302",
    description:"Occupancy classification (Group A/B/E/F/H/I/M/R/S) shall be declared.",
    severity:"critical", check:{ type:"occupancy_declared" }, requires_citation: false },
  { id:"COM-CONSTRUCTION-TYPE", discipline:"Commercial", code_ref:"IBC 602",
    description:"Construction Type (I-A through V-B) shall be declared.",
    severity:"critical", check:{ type:"construction_type_declared" }, requires_citation: false },
  // Numeric-table rules: requires_citation = true (we're asserting the
  // applicant violated a specific tabular limit; reviewer must see the table).
  { id:"COM-AREA-ALLOWABLE", discipline:"Commercial", code_ref:"IBC Table 506.2",
    description:"Building area per story shall not exceed the tabular allowable area.",
    severity:"critical", check:{ type:"allowable_area_check" }, requires_citation: true },
  { id:"COM-STORIES-ALLOWABLE", discipline:"Commercial", code_ref:"IBC Table 504.4",
    description:"Number of stories shall not exceed the tabular limit.",
    severity:"critical", check:{ type:"stories_check" }, requires_citation: true },
  { id:"COM-MIXED-OCCUPANCY", discipline:"Commercial", code_ref:"IBC 508",
    description:"Mixed-occupancy strategy (accessory, non-separated, separated) shall be declared.",
    severity:"major", check:{ type:"mixed_occupancy_check" }, requires_citation: false },
  { id:"COM-HIGH-RISE", discipline:"Commercial", code_ref:"IBC 403",
    description:"High-rise (>75 ft) provisions: smoke control, voice alarm, standby power.",
    severity:"critical", check:{ type:"high_rise_check" }, requires_citation: true },

  // Egress
  { id:"EGR-OCCUPANT-LOAD", discipline:"Fire & Life Safety", code_ref:"IBC 1004",
    description:"Design occupant load shall be declared.",
    severity:"critical", check:{ type:"occupant_load_declared" }, requires_citation: false },
  { id:"EGR-MIN-EXITS", discipline:"Fire & Life Safety", code_ref:"IBC 1006.3.2",
    description:"Minimum exits: 2 (≤500), 3 (501–1000), 4 (>1000).",
    severity:"critical", check:{ type:"num_exits_check" }, requires_citation: true },
  { id:"EGR-EXIT-CAPACITY", discipline:"Fire & Life Safety", code_ref:"IBC 1005.3",
    description:"Egress width: 0.2 in/occupant doors, 0.3 in/occupant stairs.",
    severity:"critical", check:{ type:"exit_capacity_check" }, requires_citation: true },
  { id:"EGR-PANIC-HARDWARE", discipline:"Fire & Life Safety", code_ref:"IBC 1010.1.10",
    description:"Panic hardware required on Group A (OL ≥ 50) and Group E doors.",
    severity:"major", check:{ type:"panic_hardware_check" }, requires_citation: true },

  // Required submittal items — these are completeness checks (missing
  // keyword = missing element of the submittal), not code interpretations.
  { id:"GEN-CODE-ANALYSIS", discipline:"General", code_ref:"IBC Ch. 3–5",
    description:"Code analysis sheet (occupancy, type, area, height) shall be provided.",
    severity:"critical", check:{ type:"required_keyword",
      patterns:["code\\s+analysis", "occupancy\\s+(?:group|classification)", "construction\\s+type"] },
    requires_citation: false },
  { id:"FLS-SPRINKLER", discipline:"Fire & Life Safety", code_ref:"IFC 903 · NFPA 13",
    description:"Sprinkler system per NFPA 13 where required.",
    severity:"critical", check:{ type:"required_keyword",
      patterns:["NFPA\\s*13", "sprinkler\\s+system"] }, requires_citation: false },
  { id:"FLS-ALARM", discipline:"Fire & Life Safety", code_ref:"IFC 907 · NFPA 72",
    description:"Fire alarm system per NFPA 72 where required.",
    severity:"critical", check:{ type:"required_keyword",
      patterns:["NFPA\\s*72", "fire\\s+alarm"] }, requires_citation: false },
  { id:"NEC-SERVICE-RATING", discipline:"Electrical", code_ref:"NEC 230.42",
    description:"Service entrance ampacity shall be specified.",
    severity:"major", check:{ type:"required_keyword",
      patterns:["\\d+\\s*A(?:MP)?\\s+service", "main\\s+breaker"] }, requires_citation: false },
  { id:"PLUMB-FIXTURES", discipline:"Plumbing", code_ref:"IPC Table 403.1",
    description:"Plumbing fixture count shall meet minimum ratios for occupancy.",
    severity:"major", check:{ type:"plumbing_fixture_calc" }, requires_citation: true },
  { id:"ENR-IECC", discipline:"Energy", code_ref:"IECC C401 · R401",
    description:"IECC compliance path shall be identified.",
    severity:"major", check:{ type:"required_keyword",
      patterns:["\\bIECC\\b", "energy\\s+code"] }, requires_citation: false },
];

/**
 * Resolve the active rule set for an agency by merging:
 *   baseline + agency.custom_rules - agency.rule_overrides[disabled]
 */
export function rulesForAgency(
  baseline: Rule[],
  customRules: Rule[] = [],
  overrides: { disabled?: string[]; severity_changes?: Record<string, Severity> } = {},
): Rule[] {
  const disabled = new Set(overrides.disabled ?? []);
  const sevChanges = overrides.severity_changes ?? {};
  const out: Rule[] = [];
  for (const r of [...baseline, ...customRules]) {
    if (disabled.has(r.id)) continue;
    if (sevChanges[r.id]) out.push({ ...r, severity: sevChanges[r.id] });
    else out.push(r);
  }
  return out;
}
