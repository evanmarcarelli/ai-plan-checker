"""Deterministic rule knowledge base.

Ported from plan-room-ahj/supabase/functions/_shared/rules.ts. A flat list
of typed rules the engine evaluates. Two rule families:

  - Numeric / table rules (allowable_area_check, stories_check, ...) run a
    pure checker from checkers.py.
  - Declarative-completeness rules (required_keyword, occupancy_declared, ...)
    check that a required element is *present* in the plan, not that a code
    limit is met.

`requires_citation` mirrors the TS flag: when True, a "fail" must carry a
verified corpus citation before it is surfaced as non-compliant; the
citation gate downgrades fail-without-citation to needs_review. Declarative
rules set it False (a missing field is a structural omission, not a code
interpretation that needs a section quote).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# severity: "critical" | "major" | "moderate" | "minor"
# Maps to ai-plan-checker's ComplianceFinding.severity scale
# (critical/high/medium/low) via engine._SEVERITY_MAP.


@dataclass
class Rule:
    id: str
    discipline: str          # maps to a department category
    code_ref: str
    description: str
    severity: str            # critical | major | moderate | minor
    check: Dict[str, Any]    # {"type": "...", ...params}
    requires_citation: bool = False
    # Applicability constraints. Empty = applies everywhere. Keys:
    #   plan_types:      run only for these plan types ("commercial", ...)
    #   occupancies:     run only for these groups/tokens ("A", "E", "R-1")
    #   not_occupancies: skip for these groups/tokens ("R-3", "U")
    # Gating is positive-evidence only (engine._rule_applies): unknown
    # occupancy/plan type falls OPEN, so missing extraction never silently
    # disables a check. Before this existed, every commercial rule ran on
    # every plan — ADA parking and NFPA 72 fired on private single-family
    # homes as auto-verified false positives.
    applies: Dict[str, Any] = field(default_factory=dict)


# Discipline -> department category (matches chunker.classify_category buckets).
DISCIPLINE_TO_CATEGORY = {
    "Commercial": "building_safety",
    "General": "building_safety",
    "Structural": "building_safety",
    "Architectural": "building_safety",
    "Accessibility": "accessibility",
    "Electrical": "electrical",
    "Mechanical": "mechanical",
    "Plumbing": "plumbing",
    "Fire & Life Safety": "fire",
    "Energy": "energy",
    "Zoning": "zoning",
}


CALFIRE_WUI_RULES: List[Rule] = [
    Rule(
        id="FIRE-WUI-7A",
        discipline="Fire & Life Safety",
        code_ref="CBC Chapter 7A · CA Gov Code §51182",
        description=(
            "Projects in a CalFire High or Very High Fire Hazard Severity Zone (FHSZ) "
            "require wildfire-resistive exterior construction per CBC Chapter 7A: "
            "ignition-resistant materials for roofing, exterior walls, decks, vents, and glazing."
        ),
        severity="critical",
        check={"type": "wui_zone_check"},
        requires_citation=True,
    ),
    Rule(
        id="FIRE-WUI-VENT",
        discipline="Fire & Life Safety",
        code_ref="CBC Section 708A",
        description=(
            "WUI zone: attic, crawl space, and foundation vents must be ember-resistant "
            "(CalFire-listed). Verify vent spec on architectural drawings."
        ),
        severity="major",
        # Gated on WUI zone — only applies when the project sits in a CalFire
        # FHSZ. The keyword list is the spec the engine looks for once gated.
        check={"type": "wui_keyword_check",
               "patterns": [r"ember[-\s]?resistant", r"708A", r"CalFire[-\s]?listed\s+vent"]},
        requires_citation=True,
    ),
    Rule(
        id="FIRE-WUI-DECK",
        discipline="Architectural",
        code_ref="CBC Section 709A",
        description=(
            "WUI zone: exterior decks and balconies >= 6 ft above grade or in Very High "
            "FHSZ must use ignition-resistant or noncombustible material. Deck material spec required."
        ),
        severity="major",
        check={"type": "wui_keyword_check",
               "patterns": [r"ignition[-\s]?resistant", r"noncombustible\s+deck", r"709A"]},
        requires_citation=True,
    ),
]


BASELINE_RULES: List[Rule] = [
    # ---- Building-scale code analysis ----
    Rule("COM-OCCUPANCY-DECL", "Commercial", "IBC 302",
         "Occupancy classification (Group A/B/E/F/H/I/M/R/S) shall be declared.",
         "critical", {"type": "occupancy_declared"}, requires_citation=False),
    Rule("COM-CONSTRUCTION-TYPE", "Commercial", "IBC 602",
         "Construction Type (I-A through V-B) shall be declared.",
         "critical", {"type": "construction_type_declared"}, requires_citation=False),
    Rule("COM-AREA-ALLOWABLE", "Commercial", "IBC Table 506.2",
         "Building area per story shall not exceed the tabular allowable area.",
         "critical", {"type": "allowable_area_check"}, requires_citation=True),
    # requires_citation=False: engine table math — the table-store values are
    # the provenance. Table 504.4's text is not in the corpus, so the gate
    # was silently downgrading every TRUE story-limit violation to
    # needs_review (caught by tests/test_rule_citation_coverage.py).
    Rule("COM-STORIES-ALLOWABLE", "Commercial", "IBC Table 504.4",
         "Number of stories shall not exceed the tabular limit.",
         "critical", {"type": "stories_check"}, requires_citation=False),
    # requires_citation=False: this is engine table math (the Table 504.3
    # values ARE the provenance) and the table's text is not yet in the
    # corpus — enforce-mode would mute every true positive, exactly what
    # happened to the WUI rules.
    Rule("COM-HEIGHT-ALLOWABLE", "Commercial", "IBC Table 504.3 · 504.2",
         "Building height in feet shall not exceed the tabular limit for the construction type.",
         "critical", {"type": "height_check"}, requires_citation=False),
    Rule("COM-HIGH-RISE", "Commercial", "IBC 403",
         "High-rise (>75 ft) provisions: smoke control, voice alarm, standby power.",
         "critical", {"type": "high_rise_check"}, requires_citation=True),

    # ---- Egress ----
    Rule("EGR-OCCUPANT-LOAD", "Fire & Life Safety", "IBC 1004",
         "Design occupant load shall be declared.",
         "critical", {"type": "occupant_load_declared"}, requires_citation=False),
    Rule("EGR-MIN-EXITS", "Fire & Life Safety", "IBC 1006.3.2",
         "Minimum exits: 2 (<=500), 3 (501-1000), 4 (>1000).",
         "critical", {"type": "num_exits_check"}, requires_citation=True),
    Rule("EGR-EXIT-CAPACITY", "Fire & Life Safety", "IBC 1005.3",
         "Egress width: 0.2 in/occupant doors, 0.3 in/occupant stairs.",
         "critical", {"type": "exit_capacity_check"}, requires_citation=True),
    Rule("EGR-PANIC-HARDWARE", "Fire & Life Safety", "IBC 1010.1.10",
         "Panic hardware required on Group A (OL >= 50) and Group E doors.",
         "major", {"type": "required_keyword",
                   "patterns": [r"panic\s+hardware", r"panic\s+bar"]}, requires_citation=False,
         applies={"occupancies": ["A", "E"]}),
    # The narrowest labeled corridor must clear the 44" general minimum
    # (IBC 1020.3, corridors serving OL >= 50). agg=min mirrors the examiner
    # reading: one pinch point below 44" is the violation. A missing corridor
    # dimension warns, never false-fails. Gated to commercial/mixed-use/
    # industrial — dwellings use the CRC R311 hallway regime (36"), so this
    # 44" standard does not apply to an SFR.
    Rule("EGR-CORRIDOR-WIDTH", "Fire & Life Safety", "IBC 1020.3",
         "Egress corridors serving an occupant load of 50 or more shall be a "
         "minimum of 44 inches clear width.",
         "major", {"type": "min_dimension_check", "dim": "corridor_widths",
                   "minimum": 44.0, "unit": " in", "label": "Narrowest corridor",
                   "agg": "min", "soft": True},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    # Commercial egress stairway minimum width (IBC 1011.2): stairways serving
    # an occupant load of 50 or more must be >= 44" clear width (36" is allowed
    # below 50). stair_width is a single extracted scalar (no closet-door
    # ambiguity), so this is the cleanest analogue to EGR-CORRIDOR-WIDTH. Same
    # soft posture: the engine sees the width but not the served occupant load,
    # so a sub-44" stair is needs_review, not a hard fail. Gated to non-dwelling
    # plan types — an SFR uses the CRC R318 36" stair regime (CRC-STAIR-WIDTH),
    # which would otherwise double-fire here.
    Rule("EGR-STAIR-WIDTH", "Fire & Life Safety", "IBC 1011.2",
         "Egress stairways serving an occupant load of 50 or more shall be a "
         "minimum of 44 inches clear width.",
         "major", {"type": "min_dimension_check", "dim": "stair_width",
                   "minimum": 44.0, "unit": " in", "label": "Stair width",
                   "soft": True},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    # Stair geometry (IBC 1011.5.2): riser height <= 7" and tread depth >= 11"
    # for standard straight-run stairs. soft posture: spiral stairs (1011.10),
    # winders, and alternating-tread devices (1011.14) carry different limits
    # the engine can't rule out from a single extracted scalar, so a reading
    # outside the straight-run bound is needs_review, not a hard fail. Gated to
    # non-dwelling plan types — an SFR uses the CRC R311.7.5 geometry (10"/7.75",
    # CRC-TREAD-DEPTH / CRC-RISER-HEIGHT), which would otherwise double-fire.
    Rule("EGR-TREAD-DEPTH", "Fire & Life Safety", "IBC 1011.5.2",
         "Stair treads shall have a minimum depth of 11 inches.",
         "major", {"type": "min_dimension_check", "dim": "tread_depth",
                   "minimum": 11.0, "unit": " in", "label": "Tread depth",
                   "soft": True,
                   "soft_note": " Confirm stair type (spiral / winder / "
                                "alternating-tread devices allow narrower treads)."},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    Rule("EGR-RISER-HEIGHT", "Fire & Life Safety", "IBC 1011.5.2",
         "Stair risers shall not exceed 7 inches in height.",
         "major", {"type": "max_dimension_check", "dim": "riser_height",
                   "maximum": 7.0, "unit": " in", "label": "Riser height",
                   "soft": True,
                   "soft_note": " Confirm stair type (spiral / winder / "
                                "alternating-tread devices allow taller risers)."},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    # Guards (IBC 1015.3): required >= 42" high along open-sided walking
    # surfaces. soft posture: specific stair-side conditions where the top rail
    # also serves as a handrail (34-38") are a documented exception, so a reading
    # below 42" is needs_review (could be a compliant stair-side guard), not a
    # hard fail. Gated to non-dwelling plan types — an SFR is scored by the CRC
    # twin (CRC-GUARD-HEIGHT) under R312.1.
    Rule("EGR-GUARD-HEIGHT", "Fire & Life Safety", "IBC 1015.3",
         "Guards shall be a minimum of 42 inches in height.",
         "major", {"type": "min_dimension_check", "dim": "guard_height",
                   "minimum": 42.0, "unit": " in", "label": "Guard height",
                   "soft": True,
                   "soft_note": " Confirm guard location (stair-side guards "
                                "serving as a handrail may be 34-38\")."},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),

    # ---- Required submittal items (completeness) ----
    Rule("GEN-CODE-ANALYSIS", "General", "IBC Ch. 3-5",
         "Code analysis sheet (occupancy, type, area, height) shall be provided.",
         "critical", {"type": "required_keyword",
                      "patterns": [r"code\s+analysis", r"occupancy\s+(?:group|classification)",
                                   r"construction\s+type"]}, requires_citation=False),
    Rule("FLS-SPRINKLER", "Fire & Life Safety", "IFC 903 · NFPA 13",
         "Sprinkler system per NFPA 13 where required.",
         "critical", {"type": "required_keyword",
                      "patterns": [r"NFPA\s*13", r"sprinkler\s+system"]}, requires_citation=False),
    Rule("FLS-ALARM", "Fire & Life Safety", "IFC 907 · NFPA 72",
         "Fire alarm system per NFPA 72 where required.",
         "critical", {"type": "required_keyword",
                      "patterns": [r"NFPA\s*72", r"fire\s+alarm"]}, requires_citation=False,
         # SFDs use CRC R310 smoke alarms, not NFPA 72 systems (see CRC pack).
         applies={"not_occupancies": ["R-3", "U"]}),
    Rule("NEC-SERVICE-RATING", "Electrical", "NEC 230.42",
         "Service entrance ampacity shall be specified.",
         "major", {"type": "required_keyword",
                   # Both orderings appear on real sheets: "400 A service" and
                   # "Electrical service: 200 A" (also subpanel/panel).
                   "patterns": [r"\d+\s*A(?:MP)?\s+(?:service|subpanel|panel)",
                                r"service[:\s]+\d+\s*A\b", r"main\s+breaker"]},
         requires_citation=False),
    # requires_citation=False: same table-store-provenance rationale as
    # COM-STORIES-ALLOWABLE — IPC Table 403.1's text is not in the corpus.
    Rule("PLUMB-FIXTURES", "Plumbing", "IPC Table 403.1",
         "Plumbing fixture count shall meet minimum ratios for occupancy.",
         "major", {"type": "plumbing_fixture_calc"}, requires_citation=False),
    Rule("ENR-IECC", "Energy", "IECC C401 · R401 · CA Title 24 Pt 6",
         "Energy code compliance path shall be identified (IECC, or Title 24 "
         "Part 6 / CF1R / CBECC for California).",
         "major", {"type": "required_keyword",
                   # CA plans cite Title 24 / CF1R / CBECC, never "IECC" — the
                   # IECC-only patterns failed exactly the CA jurisdictions the
                   # product targets, as an auto-verified major finding.
                   "patterns": [r"\bIECC\b", r"energy\s+code", r"Title\s*24",
                                r"\bT-?24\b", r"CF-?1R", r"CBECC"]},
         requires_citation=False),

    # ---- ADA (federal — public accommodations / commercial; a private
    #      single-family dwelling is NOT a covered entity) ----
    Rule("ADA-PARKING", "Accessibility", "ADA Table 208.2",
         "Accessible parking count shall meet ADA Table 208.2 ratio; at least one "
         "van-accessible space per facility (208.2.4).",
         "critical", {"type": "required_keyword",
                      "patterns": [r"accessible\s+parking", r"ADA\s+parking",
                                   r"van[-\s]accessible"]}, requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    Rule("ADA-ROUTE", "Accessibility", "ADA 402",
         "An accessible route shall connect accessible parking, public sidewalks, and "
         "the primary entrance (ADA 402, 206.2.1).",
         "critical", {"type": "required_keyword",
                      "patterns": [r"accessible\s+route", r"path\s+of\s+travel", r"POT\b"]},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    Rule("ADA-RESTROOM", "Accessibility", "ADA 603",
         "At least one accessible toilet compartment shall be provided per ADA 603/604.",
         "major", {"type": "required_keyword",
                   "patterns": [r"accessible\s+(?:restroom|toilet|water\s+closet)",
                                r"ADA\s+restroom", r"ANSI\s+A117\.1"]}, requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),
    Rule("ADA-SIGNAGE", "Accessibility", "ADA 703",
         "Permanent room signs shall have tactile characters and Braille per ADA 703.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"braille", r"tactile\s+sign", r"ADA\s+sign"]},
         requires_citation=False,
         applies={"plan_types": ["commercial", "industrial", "mixed_use"]}),

    # ---- NFPA completeness ----
    Rule("FLS-NFPA13R", "Fire & Life Safety", "NFPA 13R",
         "Residential occupancies (R-1, R-2) 4 stories or less may use NFPA 13R; declare 13 vs 13R.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"NFPA\s*13R", r"residential\s+sprinkler"]}, requires_citation=False,
         applies={"occupancies": ["R-1", "R-2"]}),
    Rule("FLS-NFPA101", "Fire & Life Safety", "NFPA 101",
         "Reference to NFPA 101 Life Safety Code shall appear on egress/life-safety analysis where required.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"NFPA\s*101", r"life\s+safety\s+code"]}, requires_citation=False),

    # ---- Mechanical ventilation (IMC) ----
    Rule("MECH-VENTILATION", "Mechanical", "IMC Table 403.3",
         "Minimum outdoor air ventilation rates per IMC Table 403.3 shall be declared.",
         "major", {"type": "required_keyword",
                   "patterns": [r"ventilation\s+rate", r"outdoor\s+air", r"IMC\s+(?:Table\s+)?403",
                                r"\bCFM/(?:person|occupant)\b"]}, requires_citation=False,
         # Dwellings ventilate under CRC/ASHRAE 62.2, not IMC commercial rates.
         applies={"not_occupancies": ["R-3", "U"]}),

    # ---- CRC R-3 dwelling scalar pack ----
    # Section numbers follow the 2025 CRC (Title 24 Pt 2.5, based on the 2024
    # IRC), which heavily renumbered Chapter 3 vs the 2022 CRC: ceiling height
    # R305->R313, stairways/egress door R311->R318, EERO R310->R319, sprinklers
    # R313->R309, smoke/CO alarms R314/R315->R310/R311. Cites are verified
    # against corpus/ca_crc_2025.jsonl via corpus_loader.has_section().
    # The product's main workload is SFD review, but the engine had ZERO CRC
    # numeric checks — all residential math was delegated to LLM checklist
    # review. These compare dimensions the extractor already pulls into
    # plan_data.dimensions; a missing dimension warns, never false-fails.
    Rule("CRC-CEILING-HT", "Architectural", "CRC R313.1",
         "Habitable rooms: minimum ceiling height 7 feet.",
         "major", {"type": "min_dimension_check", "dim": "ceiling_height",
                   "minimum": 7.0, "unit": " ft", "label": "Ceiling height"},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    Rule("CRC-STAIR-WIDTH", "Architectural", "CRC R318.7.1",
         "Stairways: minimum clear width 36 inches.",
         "major", {"type": "min_dimension_check", "dim": "stair_width",
                   "minimum": 36.0, "unit": " in", "label": "Stair width"},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    # R-3 stair geometry (CRC R318.5, the 2025 CRC renumber of IRC R311.7.5):
    # tread depth >= 10" and riser height <= 7-3/4". These differ from the IBC
    # straight-run numbers (11" / 7"), so an R-3 dwelling gets its own twin.
    # soft posture: spiral stairs (CRC R318.10), winders, and bulkhead/cellar
    # stairs carry different limits the engine can't rule out from a scalar.
    Rule("CRC-TREAD-DEPTH", "Architectural", "CRC R318.5",
         "Stair treads: minimum depth 10 inches.",
         "major", {"type": "min_dimension_check", "dim": "tread_depth",
                   "minimum": 10.0, "unit": " in", "label": "Tread depth",
                   "soft": True,
                   "soft_note": " Confirm stair type (spiral / winder stairs "
                                "allow narrower treads under CRC R318.5/.10)."},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    Rule("CRC-RISER-HEIGHT", "Architectural", "CRC R318.5",
         "Stair risers: maximum height 7-3/4 inches.",
         "major", {"type": "max_dimension_check", "dim": "riser_height",
                   "maximum": 7.75, "unit": " in", "label": "Riser height",
                   "soft": True,
                   "soft_note": " Confirm stair type (spiral / winder stairs "
                                "allow taller risers under CRC R318.5/.10)."},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    # R-3 guards (CRC R312.1.2): >= 42" along open-sided walking surfaces.
    # soft posture: CRC R312.1.2 permits 34-38" guards on the open side of
    # stairs where the top rail also serves as a handrail — an exception the
    # engine can't confirm from a scalar, so sub-42" is needs_review.
    Rule("CRC-GUARD-HEIGHT", "Architectural", "CRC R312.1.2",
         "Guards: minimum height 42 inches.",
         "major", {"type": "min_dimension_check", "dim": "guard_height",
                   "minimum": 42.0, "unit": " in", "label": "Guard height",
                   "soft": True,
                   "soft_note": " Confirm guard location (stair-side guards "
                                "serving as a handrail may be 34-38\" per CRC "
                                "R312.1.2 exc.)."},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    Rule("CRC-EGRESS-DOOR", "Architectural", "CRC R318.2",
         "At least one egress door: minimum 32-inch clear width.",
         "major", {"type": "min_dimension_check", "dim": "door_widths",
                   "minimum": 32.0, "unit": " in", "label": "Widest door",
                   # max: at least ONE door must satisfy R318.2 — closet doors
                   # are legitimately narrower, so min() would false-fail.
                   "agg": "max"},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    Rule("CRC-EGRESS-WINDOW", "Architectural", "CRC R319.1",
         "Sleeping rooms: emergency escape and rescue openings (egress windows) required.",
         "major", {"type": "required_keyword",
                   "patterns": [r"egress\s+window", r"emergency\s+escape\s+and\s+rescue",
                                r"\bR319\b"]},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
    Rule("CRC-SMOKE-CO", "Fire & Life Safety", "CRC R310 · R311",
         "Smoke alarms (R310) and carbon monoxide alarms (R311) shall be shown.",
         "critical", {"type": "required_keyword",
                      "patterns": [r"smoke\s+(?:alarm|detector)", r"carbon\s+monoxide",
                                   r"\bCO\s+alarm", r"\bR31[01]\b"]},
         requires_citation=False, applies={"occupancies": ["R-3"]}),
]


CALGREEN_MANDATORY_RULES: List[Rule] = [
    Rule("CAL-WATER-EFF", "Plumbing", "CALGreen 4.303.1",
         "Nonresidential plumbing fixtures shall meet CALGreen 4.303.1 maximum flow rates "
         "(1.28 gpf water closets, 0.5 gpm public lavatories).",
         "major", {"type": "required_keyword",
                   "patterns": [r"CALGreen", r"water[-\s]efficient\s+fixture", r"low[-\s]flow",
                                r"1\.28\s*gpf", r"0\.5\s*gpm"]}, requires_citation=False),
    Rule("CAL-CONST-WASTE", "General", "CALGreen 4.408.1",
         "Construction waste management plan shall divert >= 65% of non-hazardous C&D debris.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"construction\s+waste\s+management", r"waste\s+management\s+plan",
                                   r"CALGreen\s+4\.408"]}, requires_citation=False),
]


def rules_for_agency(
    baseline: List[Rule],
    custom_rules: List[Rule] = None,
    disabled: List[str] = None,
    severity_changes: Dict[str, str] = None,
) -> List[Rule]:
    """Merge baseline + custom - disabled, applying severity overrides.

    Mirrors rulesForAgency() in the TS engine.
    """
    custom_rules = custom_rules or []
    disabled_set = set(disabled or [])
    sev = severity_changes or {}
    out: List[Rule] = []
    for r in list(baseline) + list(custom_rules):
        if r.id in disabled_set:
            continue
        if r.id in sev:
            out.append(Rule(r.id, r.discipline, r.code_ref, r.description,
                            sev[r.id], r.check, r.requires_citation, r.applies))
        else:
            out.append(r)
    return out
