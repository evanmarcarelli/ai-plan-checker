// Pre-baked triage reports rendered client-side by the live demo on the
// marketing page. Zero backend calls — picking a scenario shows a fixed
// report after a short fake-processing animation.

export interface DemoCitation {
  text: string;
  source_url: string;
  source_title: string;
  source_domain: string;
}

export interface DemoFinding {
  rule_id: string;
  code_ref: string;
  description: string;
  discipline: string;
  severity: "critical" | "high" | "medium" | "low";
  status: "fail" | "warn" | "pass" | "info";
  summary: string;
  evidence: string[];
  citation?: DemoCitation;
}

export interface DemoWuiZone {
  in_wui: boolean;
  haz_class: string | null;
  sra_type: string | null;
  county: string | null;
}

export interface DemoScope {
  occupancies: string[];
  construction_type: string | null;
  building_area_sf: number | null;
  stories_above: number | null;
  height_ft: number | null;
  sprinklered: boolean | null;
  ambiguities: string[];
  wui_zone?: DemoWuiZone;
}

export interface DemoCompleteness {
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  headline: string;
  missing_items: string[];
  reviewer_questions: string[];
  assessment: string;
}

export interface DemoReport {
  scope: DemoScope;
  findings: DemoFinding[];
  completeness: DemoCompleteness;
  stats: { total: number; pass: number; fail: number; warn: number; info: number };
}

export interface DemoScenario {
  id: string;
  label: string;
  location: string;
  jurisdiction: string;
  projectName: string;
  projectType: string;
  address: string;
  badgeText: string;
  description: string;
  processingNotes: { jurisdiction: string; ruleCount: number; citationCount: number };
  report: DemoReport;
}

// ────────────────────────────── Altadena SFR Rebuild ──────────────────

const ALTADENA_SFR: DemoScenario = {
  id: "altadena-sfr",
  label: "Altadena SFR Rebuild",
  location: "Altadena, CA",
  jurisdiction: "CA:LA_COUNTY",
  projectName: "3286 N Marengo Ave — SFR Rebuild",
  projectType: "Single Family Residence (post-Eaton Fire rebuild)",
  address: "3286 N Marengo Ave, Altadena, CA 91001",
  badgeText: "VHFHSZ · CBC 2022",
  description: "R-3 occupancy. 2,400 SF two-story SFR rebuild in Very-High FHSZ.",
  processingNotes: {
    jurisdiction: "CA:LA_COUNTY (CBC 2022 · LA County Title 26)",
    ruleCount: 78,
    citationCount: 3,
  },
  report: {
    scope: {
      occupancies: ["R-3", "U"],
      construction_type: "V-B",
      building_area_sf: 2400,
      stories_above: 2,
      height_ft: 24,
      sprinklered: false,
      ambiguities: [
        "Parcel is in CalFire VHFHSZ (LRA). Verify CBC Chapter 7A material schedule is on the architectural set.",
        "No defensible-space site plan supplied with PRC §4291 compliance notes.",
      ],
      wui_zone: { in_wui: true, haz_class: "Very High", sra_type: "LRA", county: "Los Angeles" },
    },
    findings: [
      {
        rule_id: "FIRE-WUI-7A-SIDING",
        code_ref: "CBC §704A.1 · Chapter 7A",
        description:
          "In VHFHSZ, exterior wall covering within the first 5 ft of grade must be noncombustible or ignition-resistant per CBC §704A.",
        discipline: "Fire & Life Safety",
        severity: "critical",
        status: "fail",
        summary:
          "Plan shows wood siding within 5 ft of grade. CBC Ch. 7A requires noncombustible siding in the bottom 5 ft in VHFHSZ.",
        evidence: [
          "Elevation A3.1: lap siding continues to grade. No noncombustible base specified.",
          "CalFire FHSZ GIS: Very High (LRA) confirmed at this address.",
        ],
        citation: {
          text:
            "Exterior walls of buildings or structures shall be constructed with materials that comply with one of the following: noncombustible materials, exterior fire-retardant-treated wood, heavy timber, log wall construction, or wall assemblies that meet SFM 12-7A-1.",
          source_url:
            "https://up.codes/viewer/california/ca-building-code-2022/chapter/7A/sfm-materials-and-construction-methods-for-exterior-wildfire-exposure#704A.2",
          source_title: "CBC 2022 §704A.2 — Exterior Walls",
          source_domain: "up.codes",
        },
      },
      {
        rule_id: "EGRESS-EERO-001",
        code_ref: "CRC R310.1 · IFC 1030.2",
        description:
          "Every sleeping room shall have an emergency escape and rescue opening (EERO): ≥5.7 sf net clear, sill height ≤44 in AFF, minimum 24 in clear height + 20 in clear width.",
        discipline: "Building & Safety",
        severity: "critical",
        status: "fail",
        summary:
          "Upstairs bedroom 3 window: 16×36 slider w/ 48-in sill exceeds 44-in max AFF and is under 5.7 sf net clear opening required for emergency escape.",
        evidence: [
          "Floor plan A2.1: bedroom 3 W-3 noted 16×36 horizontal slider, sill @ 48 in AFF.",
          "Net clear opening calc: 14 × 16 = 224 sq in = 1.55 sf. Required: 5.7 sf.",
        ],
        citation: {
          text:
            "Basements, habitable attics and every sleeping room shall have not less than one operable emergency escape and rescue opening. The minimum net clear opening shall be 5.7 square feet.",
          source_url: "https://up.codes/viewer/california/ca-residential-code-2022/chapter/3/building-planning#R310.1",
          source_title: "CRC 2022 §R310.1 — Emergency Escape and Rescue Openings",
          source_domain: "up.codes",
        },
      },
      {
        rule_id: "ENERGY-T24-PV",
        code_ref: "T24 Part 6 §150.1(c)14",
        description:
          "Newly constructed low-rise residential buildings shall include a photovoltaic system sized per the prescriptive PV equation in T24 §150.1(c)14.",
        discipline: "Environmental",
        severity: "high",
        status: "fail",
        summary:
          "No PV system shown on roof plan. California Title 24 requires a sized photovoltaic system on all new SFD.",
        evidence: [
          "Roof plan A2.2 shows no PV array, no PV cutsheet on E0.1.",
          "T24 prescriptive PV size for 2,400 sf in CZ 9: ~3.2 kW DC nameplate.",
        ],
        citation: {
          text:
            "A PV system meeting the minimum qualification requirements as specified in Joint Appendix JA11 shall be installed on newly constructed low-rise residential buildings.",
          source_url: "https://energycodeace.com/site/custom/public/reference-ace-2022/index.html#!Documents/section1501buildingenvelope.htm",
          source_title: "T24 §150.1(c)14 — Photovoltaic Systems",
          source_domain: "energycodeace.com",
        },
      },
      {
        rule_id: "NEC-GFCI-KITCHEN",
        code_ref: "NEC 210.8(A)(7)",
        description:
          "All 125-volt, single-phase, 15- and 20-ampere receptacles serving countertop surfaces in dwelling kitchens shall have GFCI protection.",
        discipline: "Electrical",
        severity: "medium",
        status: "warn",
        summary:
          "Two countertop receptacles within 6 ft of sink not annotated GFCI; required for dwelling unit kitchens.",
        evidence: ["Power plan E1.1: receptacles R-14 and R-15 missing GFCI symbol."],
      },
      {
        rule_id: "FIRE-WUI-VENT",
        code_ref: "CBC §708A.4",
        description:
          "Attic, eave, and crawl-space vents in WUI zones shall be listed ember-resistant or have a noncombustible corrosion-resistant 1/16-in to 1/8-in mesh.",
        discipline: "Fire & Life Safety",
        severity: "high",
        status: "warn",
        summary: "Eave vent type not specified on roof framing plan. Ember-resistant vent requirement cannot be confirmed.",
        evidence: ["Roof framing plan A4.1: vents shown by symbol only, no spec note or schedule entry."],
      },
      {
        rule_id: "PRC-4291-DEFENSE",
        code_ref: "PRC §4291",
        description:
          "Parcels in or adjacent to SRA/LRA fire zones must maintain 100 ft of defensible space, with managed Zone 1 (0–30 ft) and reduced-fuel Zone 2 (30–100 ft).",
        discipline: "Planning & Zoning",
        severity: "medium",
        status: "warn",
        summary: "No defensible-space landscape plan provided. PRC §4291 site notes required for VHFHSZ rebuild.",
        evidence: ["Sheet index lacks an L-series landscape sheet."],
      },
      {
        rule_id: "STRUCT-SHEAR-001",
        code_ref: "CBC §2308.6",
        description:
          "Conventional light-frame construction in Seismic Design Category D shall provide wall bracing per CBC §2308.6 unless engineered shear walls are detailed.",
        discipline: "Structural",
        severity: "high",
        status: "pass",
        summary: "Engineered shear wall schedule provided on S2.1 with hold-down callouts at all marked locations.",
        evidence: ["Sheet S2.1: shear wall schedule SW-1..SW-4 with Simpson HDU8-SDS holdowns."],
      },
      {
        rule_id: "OCC-CLASS-001",
        code_ref: "CBC §310.1",
        description: "Occupancy classification must be stated on the cover sheet.",
        discipline: "General",
        severity: "low",
        status: "pass",
        summary: "R-3 / U occupancy confirmed on cover sheet.",
        evidence: ['Cover sheet A0.0: "Occupancy: R-3 / U · Type V-B · Unsprinklered."'],
      },
    ],
    completeness: {
      score: 42,
      grade: "F",
      headline: "3 critical items missing. Return to applicant before substantive review.",
      missing_items: [
        "Chapter 7A noncombustible base detail at exterior walls",
        "EERO compliance at bedroom 3 (window size + sill height)",
        "Title 24 prescriptive PV system on roof plan + E sheet",
      ],
      reviewer_questions: [
        "Is the rebuild scope eligible for the LA County post-Eaton 'like-for-like' fee waiver?",
        "Confirm Class A roof assembly per CBC §705A.3 — roof spec not called out on A4.0.",
      ],
      assessment:
        "Eaton-Fire rebuild with three Chapter-7A / T24 gaps that must be cured before review opens. Pre-screen recommends a 3-item correction notice to applicant; substantive structural review can proceed in parallel once items are returned.",
    },
    stats: { total: 8, pass: 2, fail: 3, warn: 3, info: 0 },
  },
};

// ────────────────────────────── LA SFR + ADU ───────────────────────────

const LA_SFR_ADU: DemoScenario = {
  id: "la-sfr-adu",
  label: "SFR + ADU Addition",
  location: "Los Angeles, CA",
  jurisdiction: "CA:LOS_ANGELES",
  projectName: "1847 Loma Vista Dr — ADU Addition",
  projectType: "Single Family Residence + Accessory Dwelling Unit",
  address: "1847 Loma Vista Dr, Los Angeles, CA 90046",
  badgeText: "WUI · CBC 2022",
  description: "R-3 / U. 645 SF ADU addition on a High FHSZ parcel in Hollywood Hills.",
  processingNotes: {
    jurisdiction: "CA:LOS_ANGELES (CBC 2022 · LAMC)",
    ruleCount: 64,
    citationCount: 2,
  },
  report: {
    scope: {
      occupancies: ["R-3", "U"],
      construction_type: "V-B",
      building_area_sf: 2745,
      stories_above: 2,
      height_ft: 22,
      sprinklered: false,
      ambiguities: [
        "Address is in High FHSZ (SRA). Verify CBC Chapter 7A material schedules are on the architectural drawings.",
        "ADU setback from interior side property line not dimensioned on site plan.",
      ],
      wui_zone: { in_wui: true, haz_class: "High", sra_type: "SRA", county: "Los Angeles" },
    },
    findings: [
      {
        rule_id: "FIRE-WUI-7A",
        code_ref: "CBC Chapter 7A · CA Gov Code §51182",
        description:
          "CBC Chapter 7A applies to all new construction and additions in High or Very High FHSZ. Material schedules for roof, walls, eaves, vents, decks and gutters must appear on the drawings.",
        discipline: "Fire & Life Safety",
        severity: "critical",
        status: "fail",
        summary:
          "No wildfire-resistive material schedule found on architectural drawings. Chapter 7A compliance documentation required.",
        evidence: [
          "Architectural drawings reviewed — no Table 7A-1 material schedule sheet found.",
          "CalFire FHSZ GIS: High FHSZ (SRA) confirmed at this address.",
        ],
        citation: {
          text:
            "Section 701A.3 — The provisions of this chapter shall apply to all new buildings and structures located within a State Responsibility Area (SRA) or within a Local Responsibility Area (LRA) that has been designated as a Very High Fire Hazard Severity Zone.",
          source_url:
            "https://up.codes/viewer/california/ca-building-code-2022/chapter/7A/sfm-materials-and-construction-methods-for-exterior-wildfire-exposure#701A.3",
          source_title: "CBC 2022 Chapter 7A — §701A.3 Application",
          source_domain: "up.codes",
        },
      },
      {
        rule_id: "ADU-SETBACK-001",
        code_ref: "LAMC 12.21-A.33(e)",
        description: "ADU setback from interior side and rear property lines must be ≥4 ft and dimensioned on the site plan.",
        discipline: "Planning & Zoning",
        severity: "high",
        status: "fail",
        summary: "ADU interior setback not dimensioned on site plan. Reviewer cannot confirm 4-ft minimum.",
        evidence: ["Site plan A1.0: ADU footprint shown but no setback dimension from south property line."],
        citation: {
          text:
            "An accessory dwelling unit that is attached to, or located within, the proposed or existing primary dwelling shall be set back no less than four (4) feet from the rear and side property lines.",
          source_url:
            "https://library.municode.com/ca/los_angeles/codes/municipal_code?nodeId=CH12PLZO_ART2DERE_S12.21MAUSRE",
          source_title: "LAMC §12.21-A — Minimum Yard Requirements",
          source_domain: "library.municode.com",
        },
      },
      {
        rule_id: "FIRE-WUI-VENT",
        code_ref: "CBC §708A.4",
        description: "Eave vents in WUI zones must be ember-resistant per CBC §708A.4. Vent spec required on drawings.",
        discipline: "Fire & Life Safety",
        severity: "high",
        status: "warn",
        summary: "Eave vent type not specified on drawings. Ember-resistant vent requirement cannot be confirmed.",
        evidence: ["Roof framing plan A4.1: vents shown by symbol but no spec note or schedule entry."],
      },
      {
        rule_id: "ARCH-EXT-MAT-001",
        code_ref: "CBC §705A.2",
        description: "Exterior wall covering must be identified on drawings and comply with CBC §705A ignition-resistant standards.",
        discipline: "Architectural",
        severity: "medium",
        status: "warn",
        summary: "Exterior wall cladding material not called out on elevations.",
        evidence: ['Elevation sheets A3.1–A3.4 show "siding" by symbol only; no material specification.'],
      },
      {
        rule_id: "EGRESS-001",
        code_ref: "IBC §1006.3.2",
        description: "Dwelling units and sleeping rooms shall have not less than one emergency escape and rescue opening complying with IBC §1030.",
        discipline: "Building & Safety",
        severity: "critical",
        status: "pass",
        summary: "Emergency escape openings confirmed in all sleeping rooms.",
        evidence: ["Floor plan A2.0: EERO symbols at bedroom windows with sill height and opening dimensions noted."],
      },
      {
        rule_id: "OCC-CLASS-001",
        code_ref: "CBC §310.1",
        description: "Occupancy classification must be stated on the cover sheet.",
        discipline: "General",
        severity: "low",
        status: "pass",
        summary: "R-3 / U occupancy confirmed on cover sheet.",
        evidence: ['Cover sheet A0.1: "Occupancy: R-3 / U · Type V-B Unsprinklered."'],
      },
    ],
    completeness: {
      score: 74,
      grade: "C",
      headline: "2 required items missing. Return to applicant before substantive review.",
      missing_items: [
        "CBC Chapter 7A material schedule (Table 7A-1 or equivalent) not on drawings",
        "ADU interior setback not dimensioned on site plan",
      ],
      reviewer_questions: [
        "Is the ADU to be sprinklered? LAMC §57.310.4 may require it if main dwelling > 3,600 SF.",
        "Confirm roof covering product meets CBC §703A.1 Class A rating.",
      ],
      assessment:
        "Submittal has clear WUI Chapter 7A gaps and a missing ADU setback dimension — both are quick-return items. Recommend returning with a 2-item correction notice before opening for substantive review.",
    },
    stats: { total: 6, pass: 2, fail: 2, warn: 2, info: 0 },
  },
};

// ────────────────────────────── SF Commercial TI ──────────────────────

const SF_COMMERCIAL_TI: DemoScenario = {
  id: "sf-commercial-ti",
  label: "Commercial Office TI",
  location: "San Francisco, CA",
  jurisdiction: "CA:SAN_FRANCISCO",
  projectName: "450 Sutter St — Suite 1200 TI",
  projectType: "Commercial Office Tenant Improvement",
  address: "450 Sutter St, Suite 1200, San Francisco, CA 94108",
  badgeText: "B Occ · Sprinklered",
  description: "B occupancy. 4,200 SF office TI on the 12th floor. CBC 2022 + SFBC.",
  processingNotes: {
    jurisdiction: "CA:SAN_FRANCISCO (CBC 2022 · SFBC)",
    ruleCount: 71,
    citationCount: 1,
  },
  report: {
    scope: {
      occupancies: ["B"],
      construction_type: "I-A",
      building_area_sf: 4200,
      stories_above: 1,
      height_ft: null,
      sprinklered: true,
      ambiguities: ["Occupant load not stated on drawings — cannot confirm egress capacity without a calculation."],
    },
    findings: [
      {
        rule_id: "COMP-OL-001",
        code_ref: "CBC §1004.1",
        description:
          "Occupant load shall be determined by dividing the floor area assigned to that use by the occupant load factor in CBC Table 1004.5. The calculated occupant load must appear on the floor plan.",
        discipline: "Building & Safety",
        severity: "high",
        status: "fail",
        summary: "No occupant load calculation provided. Cannot confirm exit capacity compliance without it.",
        evidence: ["Floor plan A2.0: no OL table or OL count shown.", "Code note sheet A0.2 omits occupant load."],
        citation: {
          text:
            "The occupant load shall be the number of persons for which the means of egress of a building or portion thereof is designed. The occupant load shall be calculated by dividing the floor area in square feet assigned to that use by the occupant load factor for such use listed in Table 1004.5.",
          source_url: "https://up.codes/viewer/california/ca-building-code-2022/chapter/10/means-of-egress#1004.1",
          source_title: "CBC 2022 §1004.1 — Design Occupant Load",
          source_domain: "up.codes",
        },
      },
      {
        rule_id: "ADA-ROUTE-001",
        code_ref: "CBC §11B-206.2.1",
        description: "At least one accessible route shall connect accessible building entrances with all accessible spaces within the building.",
        discipline: "Accessibility",
        severity: "medium",
        status: "warn",
        summary: "Accessible route from elevator lobby to primary work area not clearly delineated on floor plan.",
        evidence: ["Floor plan A2.0: elevator location shown but accessible path through reception area not dimensioned."],
      },
      {
        rule_id: "FIRE-SPR-001",
        code_ref: "CBC §903.3.1.1",
        description: "Where required, automatic sprinkler systems shall be designed and installed in accordance with NFPA 13.",
        discipline: "Fire & Life Safety",
        severity: "critical",
        status: "pass",
        summary: "Existing NFPA 13 sprinkler system confirmed. TI scope note states system to remain and be adjusted.",
        evidence: ['M0.1: "Existing automatic sprinkler system (NFPA 13) to remain. Contractor to adjust heads per final furniture layout."'],
      },
      {
        rule_id: "EGRESS-002",
        code_ref: "CBC §1006.3.3",
        description: "Spaces with occupant load >49 shall have a minimum of 2 exits or exit access doorways.",
        discipline: "Building & Safety",
        severity: "high",
        status: "pass",
        summary: "3 exit access doors shown on floor plan leading to building stairwells.",
        evidence: ["Floor plan A2.0: exit doors at NE corner (Stair 1), SW corner (Stair 2), and E side (Stair 3)."],
      },
      {
        rule_id: "MECH-VENT-001",
        code_ref: "CBC §1202.1",
        description: "Minimum ventilation rates for occupied spaces shall be provided per CBC §1202 and ASHRAE 62.1.",
        discipline: "Mechanical",
        severity: "medium",
        status: "pass",
        summary: "Mechanical schedule on Sheet M2.0 confirms ASHRAE 62.1 compliance.",
        evidence: ["Sheet M2.0: ventilation schedule with CFM per person and per SF for all zones."],
      },
    ],
    completeness: {
      score: 88,
      grade: "B",
      headline: "1 required item missing. Reviewer may proceed with one correction notice.",
      missing_items: ["Occupant load calculation (CBC §1004.1) — add OL table to floor plan"],
      reviewer_questions: [
        "Confirm accessible route from elevator lobby is clear of reception desk swing path.",
        "Verify sprinkler head relocation matches final reflected ceiling plan.",
      ],
      assessment:
        "Well-organized TI submittal. The single missing occupant load calculation is a quick add. Recommend one-item correction notice; reviewer may proceed with substantive review in parallel.",
    },
    stats: { total: 5, pass: 3, fail: 1, warn: 1, info: 0 },
  },
};

export const DEMO_SCENARIOS: DemoScenario[] = [ALTADENA_SFR, LA_SFR_ADU, SF_COMMERCIAL_TI];
