// =====================================================================
// Pre-baked demo scenario data for the marketing page interactive demo.
//
// Each scenario is a realistic TriageReport produced by running the
// actual pipeline once against representative plan text.  The demo
// renders these client-side — zero backend calls, zero API cost.
// =====================================================================

// ── Shared types (mirrors the backend TriageReport shape) ─────────────

export interface DemoCitation {
  text: string
  source_url: string
  source_title: string
  source_domain: string
  confidence: number
  notes?: string
}

export interface DemoFinding {
  rule_id: string
  code_ref: string
  description: string
  discipline: string
  severity: string
  status: 'pass' | 'fail' | 'warn' | 'info'
  summary: string
  evidence: string[]
  confidence: number
  citation?: DemoCitation
}

export interface DemoWuiZone {
  in_wui: boolean
  haz_class: string | null
  sra_type: string | null
  county: string | null
}

export interface DemoScope {
  occupancies: string[]
  occupancy_primary: string | null
  construction_type: string | null
  building_area_sf: number | null
  stories_above: number | null
  height_ft: number | null
  sprinklered: boolean | null
  occupant_load: number | null
  travel_distance_ft: number | null
  has_kitchen: boolean
  has_elevator: boolean
  mixed_occupancy: boolean
  ambiguities: string[]
  source: 'llm' | 'regex' | 'merged'
  wui_zone?: DemoWuiZone
}

export interface DemoCompleteness {
  score: number
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  headline: string
  missing_items: string[]
  reviewer_questions: string[]
  assessment: string
}

export interface DemoTriageReport {
  pipeline_version: string
  generated_at: string
  scope: DemoScope
  findings: DemoFinding[]
  completeness: DemoCompleteness
  stats: { total: number; pass: number; fail: number; warn: number; info: number }
}

export interface DemoScenario {
  id: string
  label: string
  location: string
  jurisdiction: string
  projectName: string
  projectType: string
  address: string
  badgeText: string
  badgeColor: 'red' | 'blue' | 'slate'
  description: string
  processingNotes: {
    jurisdiction: string
    ruleCount: number
    citationCount: number
  }
  report: DemoTriageReport
}

// ── Scenario 1: LA SFR + ADU (WUI High FHSZ) ─────────────────────────

const LA_SFR_ADU: DemoScenario = {
  id: 'la-sfr-adu',
  label: 'SFR + ADU Addition',
  location: 'Los Angeles, CA',
  jurisdiction: 'CA:LOS_ANGELES',
  projectName: '1847 Loma Vista Dr — ADU Addition',
  projectType: 'Single Family Residence + Accessory Dwelling Unit',
  address: '1847 Loma Vista Dr, Los Angeles, CA 90046',
  badgeText: 'WUI · CBC 2022',
  badgeColor: 'red',
  description: 'R-3/U occupancy. 645 SF ADU addition on a High FHSZ parcel in Hollywood Hills.',
  processingNotes: {
    jurisdiction: 'CA:LOS_ANGELES (CBC 2022 · LAMC)',
    ruleCount: 47,
    citationCount: 2,
  },
  report: {
    pipeline_version: 'ahj-1.0',
    generated_at: '2026-05-27T14:32:11Z',
    scope: {
      occupancies: ['R-3', 'U'],
      occupancy_primary: 'R-3',
      construction_type: 'V-B',
      building_area_sf: 2745,
      stories_above: 2,
      height_ft: 22,
      sprinklered: false,
      occupant_load: 8,
      travel_distance_ft: 42,
      has_kitchen: true,
      has_elevator: false,
      mixed_occupancy: true,
      ambiguities: [
        'Address is in High FHSZ (SRA). Verify CBC Chapter 7A material schedules are on the architectural drawings.',
        'ADU setback from interior side property line not dimensioned on site plan.',
      ],
      source: 'llm',
      wui_zone: {
        in_wui: true,
        haz_class: 'High',
        sra_type: 'SRA',
        county: 'Los Angeles',
      },
    },
    findings: [
      {
        rule_id: 'FIRE-WUI-7A',
        code_ref: 'CBC Chapter 7A · CA Gov Code §51182',
        description:
          'CBC Chapter 7A applies to all new construction and additions in High or Very High FHSZ. Material schedules for roof covering, exterior walls, eaves, vents, decks, and gutters must be shown on the drawings.',
        discipline: 'Fire & Life Safety',
        severity: 'critical',
        status: 'fail',
        summary:
          'No wildfire-resistive material schedule found on architectural drawings. Chapter 7A compliance documentation required.',
        evidence: [
          'Architectural drawings reviewed — no Table 7A-1 material schedule sheet found.',
          'CalFire FHSZ GIS: High FHSZ (SRA) confirmed at this address.',
        ],
        confidence: 0.93,
        citation: {
          text: 'Section 701A.3 — The provisions of this chapter shall apply to all new buildings and structures located within a State Responsibility Area (SRA) or within a Local Responsibility Area (LRA) that has been designated as a Very High Fire Hazard Severity Zone.',
          source_url:
            'https://up.codes/viewer/california/ca-building-code-2022/chapter/7A/sfm-materials-and-construction-methods-for-exterior-wildfire-exposure#701A.3',
          source_title: 'CBC 2022 Chapter 7A — §701A.3 Application',
          source_domain: 'up.codes',
          confidence: 0.95,
        },
      },
      {
        rule_id: 'ADU-SETBACK-001',
        code_ref: 'LAMC 12.21-A.33(e)',
        description:
          'ADU setback from interior side and rear property lines must be ≥ 4 ft. Dimension must be clearly shown on the site plan.',
        discipline: 'Zoning',
        severity: 'major',
        status: 'fail',
        summary:
          'ADU interior setback not dimensioned on site plan. Reviewer cannot confirm 4-ft minimum.',
        evidence: [
          'Site plan Sheet A1.0: ADU footprint shown but no setback dimension from south property line.',
        ],
        confidence: 0.87,
        citation: {
          text: 'An accessory dwelling unit that is attached to, or located within, the proposed or existing primary dwelling shall be set back no less than four (4) feet from the rear and side property lines.',
          source_url:
            'https://library.municode.com/ca/los_angeles/codes/municipal_code?nodeId=CH12PLZO_ART2DERE_S12.21MAUSRE',
          source_title: 'LAMC §12.21-A — Minimum Yard Requirements',
          source_domain: 'library.municode.com',
          confidence: 0.91,
        },
      },
      {
        rule_id: 'FIRE-WUI-VENT',
        code_ref: 'CBC §708A.4',
        description:
          'Eave vents in WUI zones must be ember-resistant per CBC §708A.4. Vent manufacturer and model or a spec note must appear on drawings.',
        discipline: 'Fire & Life Safety',
        severity: 'major',
        status: 'warn',
        summary:
          'Eave vent type not specified on drawings. Ember-resistant vent requirement cannot be confirmed.',
        evidence: [
          'Roof framing plan Sheet A4.1: vents shown by symbol but no spec note or schedule entry.',
        ],
        confidence: 0.78,
      },
      {
        rule_id: 'ARCH-EXT-MAT-001',
        code_ref: 'CBC §705A.2',
        description:
          'Exterior wall covering must be identified on drawings and comply with CBC §705A ignition-resistant standards.',
        discipline: 'Architectural',
        severity: 'moderate',
        status: 'warn',
        summary: 'Exterior wall cladding material not called out on elevations.',
        evidence: [
          'Elevation sheets A3.1–A3.4 show "siding" by symbol only; no material specification.',
        ],
        confidence: 0.74,
      },
      {
        rule_id: 'EGRESS-001',
        code_ref: 'IBC §1006.3.2',
        description:
          'Dwelling units and sleeping rooms shall have not less than one emergency escape and rescue opening complying with IBC §1030.',
        discipline: 'Egress',
        severity: 'critical',
        status: 'pass',
        summary: 'Emergency escape openings confirmed in all sleeping rooms.',
        evidence: [
          'Floor plan Sheet A2.0: EERO symbols at bedroom windows with sill height and opening dimensions noted.',
        ],
        confidence: 0.96,
      },
      {
        rule_id: 'OCC-CLASS-001',
        code_ref: 'CBC §310.1',
        description: 'Occupancy classification must be stated on the cover sheet.',
        discipline: 'General',
        severity: 'moderate',
        status: 'pass',
        summary: 'R-3 / U occupancy confirmed on cover sheet.',
        evidence: ['Cover sheet A0.1: "Occupancy: R-3 / U · Type V-B Unsprinklered."'],
        confidence: 0.99,
      },
    ],
    completeness: {
      score: 74,
      grade: 'C',
      headline: '2 required items missing. Return to applicant before substantive review.',
      missing_items: [
        'CBC Chapter 7A material schedule (Table 7A-1 or equivalent) not on drawings',
        'ADU interior setback not dimensioned on site plan',
      ],
      reviewer_questions: [
        'Is the ADU to be sprinklered? LAMC §57.310.4 may require it if main dwelling > 3,600 SF.',
        'Confirm roof covering product meets CBC §703A.1 Class A rating.',
      ],
      assessment:
        'Submittal has clear WUI Chapter 7A gaps and a missing ADU setback dimension — both are quick-return items. Recommend returning with a 2-item correction notice before opening for substantive review.',
    },
    stats: { total: 6, pass: 2, fail: 2, warn: 2, info: 0 },
  },
}

// ── Scenario 2: SF Commercial Office TI ──────────────────────────────

const SF_COMMERCIAL_TI: DemoScenario = {
  id: 'sf-commercial-ti',
  label: 'Commercial Office TI',
  location: 'San Francisco, CA',
  jurisdiction: 'CA:SAN_FRANCISCO',
  projectName: '450 Sutter St — Suite 1200 TI',
  projectType: 'Commercial Office Tenant Improvement',
  address: '450 Sutter St, Suite 1200, San Francisco, CA 94108',
  badgeText: 'B Occ · Sprinklered',
  badgeColor: 'blue',
  description: 'B occupancy. 4,200 SF office TI on the 12th floor. CBC 2022 + SFBC.',
  processingNotes: {
    jurisdiction: 'CA:SAN_FRANCISCO (CBC 2022 · SFBC)',
    ruleCount: 47,
    citationCount: 1,
  },
  report: {
    pipeline_version: 'ahj-1.0',
    generated_at: '2026-05-27T14:35:22Z',
    scope: {
      occupancies: ['B'],
      occupancy_primary: 'B',
      construction_type: 'I-A',
      building_area_sf: 4200,
      stories_above: 1,
      height_ft: null,
      sprinklered: true,
      occupant_load: null,
      travel_distance_ft: 188,
      has_kitchen: false,
      has_elevator: true,
      mixed_occupancy: false,
      ambiguities: [
        'Occupant load not stated on drawings — cannot confirm egress capacity without a calculation.',
      ],
      source: 'llm',
    },
    findings: [
      {
        rule_id: 'COMP-OL-001',
        code_ref: 'CBC §1004.1',
        description:
          'Occupant load shall be determined by dividing the floor area assigned to that use by the occupant load factor in CBC Table 1004.5. The calculated occupant load must appear on the floor plan.',
        discipline: 'Life Safety',
        severity: 'major',
        status: 'fail',
        summary:
          'No occupant load calculation provided. Cannot confirm exit capacity compliance without it.',
        evidence: [
          'Floor plan Sheet A2.0: no OL table or OL count shown.',
          'Code note sheet A0.2 omits occupant load.',
        ],
        confidence: 0.97,
        citation: {
          text: 'The occupant load shall be the number of persons for which the means of egress of a building or portion thereof is designed. The occupant load shall be calculated by dividing the floor area in square feet assigned to that use by the occupant load factor for such use listed in Table 1004.5.',
          source_url:
            'https://up.codes/viewer/california/ca-building-code-2022/chapter/10/means-of-egress#1004.1',
          source_title: 'CBC 2022 §1004.1 — Design Occupant Load',
          source_domain: 'up.codes',
          confidence: 0.97,
        },
      },
      {
        rule_id: 'ADA-ROUTE-001',
        code_ref: 'CBC §11B-206.2.1',
        description:
          'At least one accessible route shall connect accessible building entrances with all accessible spaces within the building.',
        discipline: 'Accessibility',
        severity: 'moderate',
        status: 'warn',
        summary:
          'Accessible route from elevator lobby to primary work area not clearly delineated on floor plan.',
        evidence: [
          'Floor plan Sheet A2.0: elevator location shown but accessible path through reception area not dimensioned.',
        ],
        confidence: 0.71,
      },
      {
        rule_id: 'FIRE-SPR-001',
        code_ref: 'CBC §903.3.1.1',
        description:
          'Where required, automatic sprinkler systems shall be designed and installed in accordance with NFPA 13.',
        discipline: 'Fire & Life Safety',
        severity: 'critical',
        status: 'pass',
        summary:
          'Existing NFPA 13 sprinkler system confirmed. TI scope note states system to remain and be adjusted.',
        evidence: [
          'M0.1: "Existing automatic sprinkler system (NFPA 13) to remain. Contractor to adjust heads per final furniture layout."',
        ],
        confidence: 0.99,
      },
      {
        rule_id: 'EGRESS-002',
        code_ref: 'CBC §1006.3.3',
        description: 'Spaces with occupant load >49 shall have a minimum of 2 exits or exit access doorways.',
        discipline: 'Egress',
        severity: 'major',
        status: 'pass',
        summary: '3 exit access doors shown on floor plan leading to building stairwells.',
        evidence: [
          'Floor plan A2.0: exit doors at NE corner (Stair 1), SW corner (Stair 2), and E side (Stair 3).',
        ],
        confidence: 0.95,
      },
      {
        rule_id: 'MECH-VENT-001',
        code_ref: 'CBC §1202.1',
        description:
          'Minimum ventilation rates for occupied spaces shall be provided per CBC §1202 and ASHRAE 62.1.',
        discipline: 'Mechanical',
        severity: 'moderate',
        status: 'pass',
        summary: 'Mechanical schedule on Sheet M2.0 confirms ASHRAE 62.1 compliance.',
        evidence: [
          'Sheet M2.0: ventilation schedule with CFM per person and per SF for all zones.',
        ],
        confidence: 0.93,
      },
    ],
    completeness: {
      score: 88,
      grade: 'B',
      headline: '1 required item missing. Reviewer may proceed with one correction notice.',
      missing_items: [
        'Occupant load calculation (CBC §1004.1) — add OL table to floor plan',
      ],
      reviewer_questions: [
        'Confirm accessible route from elevator lobby is clear of reception desk swing path.',
        'Verify sprinkler head relocation matches final reflected ceiling plan.',
      ],
      assessment:
        'Well-organized TI submittal. The single missing occupant load calculation is a quick add. Recommend one-item correction notice; reviewer may proceed with substantive review in parallel.',
    },
    stats: { total: 5, pass: 3, fail: 1, warn: 1, info: 0 },
  },
}

// ── Scenario 3: Seattle DADU ──────────────────────────────────────────

const SEATTLE_DADU: DemoScenario = {
  id: 'seattle-dadu',
  label: 'Detached ADU (DADU)',
  location: 'Seattle, WA',
  jurisdiction: 'WA:SEATTLE',
  projectName: '2341 NW 58th St — DADU',
  projectType: 'New Detached Accessory Dwelling Unit',
  address: '2341 NW 58th St, Seattle, WA 98107',
  badgeText: 'WSBC 2021 · SMC',
  badgeColor: 'slate',
  description: 'R-3. New 820 SF single-story DADU in SF 5000 zone in Ballard. SMC + WSBC 2021.',
  processingNotes: {
    jurisdiction: 'WA:SEATTLE (WSBC 2021 · SMC 23.44)',
    ruleCount: 47,
    citationCount: 2,
  },
  report: {
    pipeline_version: 'ahj-1.0',
    generated_at: '2026-05-27T14:38:05Z',
    scope: {
      occupancies: ['R-3'],
      occupancy_primary: 'R-3',
      construction_type: 'V-B',
      building_area_sf: 820,
      stories_above: 1,
      height_ft: 14,
      sprinklered: false,
      occupant_load: 4,
      travel_distance_ft: 28,
      has_kitchen: true,
      has_elevator: false,
      mixed_occupancy: false,
      ambiguities: [
        'Lot coverage calculation not shown — cannot confirm DADU meets SMC 23.44.041 35% limit.',
        'Impervious surface total not calculated on site plan.',
      ],
      source: 'llm',
    },
    findings: [
      {
        rule_id: 'SMC-LOT-COV-001',
        code_ref: 'SMC 23.44.041(C)',
        description:
          'Total lot coverage of all structures shall not exceed 35% for SF 5000 zones. A lot coverage calculation must be provided on the site plan.',
        discipline: 'Zoning',
        severity: 'critical',
        status: 'fail',
        summary:
          'No lot coverage calculation on site plan. Cannot confirm compliance with 35% maximum.',
        evidence: [
          'Site plan Sheet C1.0: footprints of existing house and DADU shown but no coverage percentage calculated.',
        ],
        confidence: 0.96,
        citation: {
          text: 'In single-family zones, the total lot coverage of all structures on the lot, including any accessory dwelling unit, shall not exceed the maximum lot coverage permitted in the zone. For SF 5000 zones, the maximum lot coverage is 35 percent of the lot area.',
          source_url:
            'https://library.municode.com/wa/seattle/codes/municipal_code?nodeId=TIT23LAUSCO_SUBTITLE_IIILAUSRE_CH23.44REUSREZO_23.44.041ACDUUN',
          source_title: 'SMC 23.44.041 — Accessory Dwelling Units',
          source_domain: 'library.municode.com',
          confidence: 0.94,
        },
      },
      {
        rule_id: 'WSBC-FIRE-SEP-001',
        code_ref: 'WSBC R302.1',
        description:
          'Exterior walls and projections within 3 ft of the property line require fire-resistance-rated construction and protected openings.',
        discipline: 'Fire & Life Safety',
        severity: 'major',
        status: 'fail',
        summary:
          'Fire separation distance from south property line not dimensioned on site plan.',
        evidence: [
          'Site plan Sheet C1.0: DADU footprint shown near south line but no dimension to property line provided.',
        ],
        confidence: 0.84,
        citation: {
          text: 'Projections shall not extend to a point closer than 2 feet from the lot line. Exterior walls less than 3 feet from the lot line shall not have openings and shall be of not less than 1-hour fire-resistance-rated construction.',
          source_url:
            'https://up.codes/viewer/washington/wa-residential-code-2021/chapter/3/building-planning#R302.1',
          source_title: 'WSBC 2021 R302.1 — Exterior Walls',
          source_domain: 'up.codes',
          confidence: 0.89,
        },
      },
      {
        rule_id: 'SMC-IMP-SURF-001',
        code_ref: 'SMC 23.44.041(D)',
        description:
          'Total impervious surface shall not exceed 65% of lot area in SF 5000 zones. A calculation with existing + proposed impervious area must appear on the site plan.',
        discipline: 'Zoning',
        severity: 'moderate',
        status: 'warn',
        summary:
          'Impervious surface total not calculated. Verify existing + proposed stays under 65%.',
        evidence: [
          'Site plan Sheet C1.0: hardscape and DADU footprint shown but no impervious surface table.',
        ],
        confidence: 0.79,
      },
      {
        rule_id: 'OCC-CLASS-001',
        code_ref: 'WSBC R101.2',
        description: 'Construction documents shall specify the occupancy classification on the cover sheet.',
        discipline: 'General',
        severity: 'moderate',
        status: 'pass',
        summary: 'R-3 occupancy confirmed on cover sheet.',
        evidence: ['Cover sheet: "Occupancy: R-3 — Accessory Dwelling Unit."'],
        confidence: 0.99,
      },
      {
        rule_id: 'FIRE-WUI-7A',
        code_ref: 'CBC Chapter 7A · CA Gov Code §51182',
        description: 'Wildfire-resistive construction under CBC Chapter 7A applies only to CA FHSZ zones.',
        discipline: 'Fire & Life Safety',
        severity: 'critical',
        status: 'info',
        summary: 'WUI zone check not applicable — non-CA jurisdiction. No CalFire FHSZ classification.',
        evidence: [],
        confidence: 1.0,
      },
    ],
    completeness: {
      score: 68,
      grade: 'C',
      headline: '2 required items missing. Return for lot coverage + fire separation dimensions.',
      missing_items: [
        'Lot coverage calculation (SMC 23.44.041) — add coverage table to site plan',
        'Fire separation distance from south property line (WSBC R302.1) — add dimension',
      ],
      reviewer_questions: [
        'Is the DADU planned for short-term rental? Seattle requires registration under SMC 23.42.060.',
        'Confirm DADU will not exceed 1,000 SF — the SMC limit for DADUs in SF 5000 zones.',
      ],
      assessment:
        'Both fails are site plan items the applicant can address on a single revised sheet. The impervious surface warning may resolve once the lot coverage calculation is added. Recommend returning with a 2-item correction notice.',
    },
    stats: { total: 5, pass: 1, fail: 2, warn: 1, info: 1 },
  },
}

// ── Exports ────────────────────────────────────────────────────────────

export const DEMO_SCENARIOS: DemoScenario[] = [LA_SFR_ADU, SF_COMMERCIAL_TI, SEATTLE_DADU]
