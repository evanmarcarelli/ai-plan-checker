"""LADBS Single-Family-Dwelling overlay rules.

Derived from a REAL LADBS plan-check correction set (a Pacific Palisades
fire-rebuild SFD, plan check B26***, 158 corrections). These encode the
Los-Angeles-specific completeness items a LADBS examiner checks on an SFD/
duplex that the generic IBC/CRC baseline does NOT cover — the "LADBS moat".

Every rule here is a completeness check: "is the required LA note / calc /
form present on the plans?" Therefore requires_citation=False (a missing RFA
calc or anti-graffiti note is a structural omission, not a code-text
interpretation). They are keyword-presence checks against the plan text,
mirroring the BASELINE_RULES required_keyword pattern.

Source of truth: each rule's `correction_ref` maps back to the real examiner
correction it was learned from, so the eval can validate against ground truth.
"""
from __future__ import annotations

from typing import List

from app.code_library.deterministic.rules import Rule

# These rules apply to City-of-Los-Angeles residential (SFD/duplex) plan
# checks. The engine injects them when the adoption resolver matches
# ca_los_angeles_city and the plan type is residential.

LADBS_SFD_RULES: List[Rule] = [
    # ---- Zoning / Residential Floor Area (LAMC 12.03) — pure LA ----
    Rule("LADBS-SFD-RFA", "Zoning", "LAMC 12.03 (RFA)",
         "Provide a Residential Floor Area (RFA) summary per structure with exemptions; "
         "attic ceiling >7 ft counts, >14 ft counts twice (LAMC 12.03).",
         "major", {"type": "required_keyword",
                   "patterns": [r"\bRFA\b", r"residential\s+floor\s+area"]},
         requires_citation=False),
    Rule("LADBS-SFD-FOOTPRINT", "Zoning", "LADBS EO fire-rebuild",
         "Provide footprint calculations, existing vs. proposed (sq ft), per the fire-rebuild EO.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"footprint\s+(?:calc|area|sf|square)", r"existing.{0,20}proposed.{0,20}(?:sf|sq)"]},
         requires_citation=False),
    Rule("LADBS-SFD-DATUM", "Zoning", "LAMC 12.21.1 (height)",
         "Identify the Datum Point (lowest grade within 5 ft of perimeter) on the plot plan, "
         "sections and elevations; building height is measured from it.",
         "major", {"type": "required_keyword",
                   "patterns": [r"datum\s+point"]},
         requires_citation=False),
    Rule("LADBS-SFD-NATGRADE", "Zoning", "LAMC 12.21.1",
         "Height shall be measured to natural grade and may not be raised with retaining walls.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"natural\s+grade"]},
         requires_citation=False),
    Rule("LADBS-SFD-SETBACKS", "Zoning", "LAMC 12.21-C",
         "Show overall dimensions and setbacks to all property lines on the site plan.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"setback", r"property\s+line"]},
         requires_citation=False),

    # ---- LA administrative overlays ----
    Rule("LADBS-SFD-ANTIGRAFFITI", "General", "LAMC 91.6307 (anti-graffiti)",
         "Provide anti-graffiti finish within the first 9 ft above grade at exterior walls/doors "
         "(or record the maintenance affidavit).",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"anti[-\s]?graffiti", r"graffiti\s+finish"]},
         requires_citation=False),
    Rule("LADBS-SFD-EO-ELIGIBILITY", "General", "LA Emergency Order (fire rebuild)",
         "Identify fire-rebuild eligibility (EO-1 vs EO-8) in the scope of work; "
         "EO-1 allows max 10% height/footprint increase.",
         "major", {"type": "required_keyword",
                   "patterns": [r"\bEO[-\s]?1\b", r"\bEO[-\s]?8\b", r"\bE[-\s]?08\b", r"emergency\s+order"]},
         requires_citation=False),

    # ---- Fire rebuild / WUI (Palisades = Very High FHSZ) ----
    Rule("LADBS-SFD-SPRINKLER", "Fire & Life Safety", "CRC R309.2",
         "Fire sprinklers shall be included in the SFD scope of work (NFPA 13D), per LADBS.",
         "critical", {"type": "required_keyword",
                      "patterns": [r"fire\s+sprinkler", r"NFPA\s*13D", r"sprinkler.{0,10}scope"]},
         requires_citation=False),
    Rule("LADBS-SFD-WUI", "Fire & Life Safety", "LAMC Ch. V Art. 7.1 (CWUIC)",
         "VHFHSZ/HFHSZ: comply with the CA Wildland-Urban Interface Code as amended by "
         "LAMC Chapter V Article 7.1 (ignition-resistant construction notes).",
         "critical", {"type": "wui_keyword_check",
                      "patterns": [r"wildland[-\s]?urban", r"\bCWUIC\b", r"7\.1.*LAMC|LAMC.*7\.1",
                                   r"fire\s+hazard\s+severity"]},
         requires_citation=True),
    Rule("LADBS-SFD-HILLSIDE-FIRE", "Fire & Life Safety", "LAMC 91.7207",
         "VHFHSZ hillside: comply with LAMC Section 91.7207 (91.7201.2, 91.7202).",
         "major", {"type": "wui_keyword_check",
                   "patterns": [r"91\.7207", r"91\.7201", r"91\.7202"]},
         requires_citation=True),

    # ---- CALGreen / LADBS GRN forms (LA-specific form numbers) ----
    Rule("LADBS-SFD-GRN4", "Energy", "CALGreen / LADBS GRN 4",
         "Incorporate the Mandatory Requirements Checklist for new residential, Form GRN 4.",
         "major", {"type": "required_keyword",
                   "patterns": [r"GRN\s*4\b", r"mandatory\s+requirements\s+checklist"]},
         requires_citation=False),
    Rule("LADBS-SFD-GRN1-SWPP", "General", "CALGreen / LADBS GRN 1",
         "Incorporate the Storm Water Pollution Control plan, Form GRN 1.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"GRN\s*1\b", r"storm\s+water\s+pollution"]},
         requires_citation=False),
    Rule("LADBS-SFD-GRN11-VOC", "General", "CALGreen 4.504 / LADBS GRN 11",
         "Incorporate the VOC and Formaldehyde Limits, Form GRN 11.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"GRN\s*11\b", r"\bVOC\b", r"formaldehyde"]},
         requires_citation=False),
    Rule("LADBS-SFD-FLOWRATE", "Plumbing", "CALGreen 4.303.1",
         "Note required: plumbing fixture flow rates shall comply with CALGreen 4.303.1.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"4\.303\.1", r"flow\s+rate"]},
         requires_citation=False),
    Rule("LADBS-SFD-COOLROOF", "Energy", "Title 24 cool roof",
         "Identify roofing product SRI / solar reflectance + thermal emittance meeting "
         "the minimum cool-roof values for the slope.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"\bSRI\b", r"solar\s+reflectance", r"thermal\s+emittance", r"cool\s+roof"]},
         requires_citation=False),
    Rule("LADBS-SFD-EV-RACEWAY", "Electrical", "CALGreen 4.106.4 / CEC",
         "Show a min 1-inch listed raceway for a dedicated 208/240V EVSE branch circuit from "
         "the service/subpanel to the charging location.",
         "major", {"type": "required_keyword",
                   "patterns": [r"\bEVSE\b", r"EV\s+charg", r"208/240", r"raceway"]},
         requires_citation=False),
    Rule("LADBS-SFD-EXHAUST", "Mechanical", "CALGreen 4.506 / ASHRAE 62.2",
         "Bathroom exhaust fans shall be ENERGY STAR, ducted to exterior, humidity-controlled.",
         "moderate", {"type": "required_keyword",
                      "patterns": [r"exhaust\s+fan", r"ENERGY\s*STAR", r"humidity\s+control"]},
         requires_citation=False),
    Rule("LADBS-SFD-FIREPLACE", "Mechanical", "CALGreen 4.503.1",
         "Fireplaces shall be direct-vent, sealed-combustion type; incorporate manufacturer specs.",
         "minor", {"type": "required_keyword",
                   "patterns": [r"direct[-\s]?vent", r"sealed\s+combustion"]},
         requires_citation=False),
    Rule("LADBS-SFD-WALLSCHED", "Architectural", "LADBS plan-content",
         "Provide a wall schedule / wall types clarifying wall thickness and material.",
         "minor", {"type": "required_keyword",
                   "patterns": [r"wall\s+schedule", r"wall\s+type", r"wall\s+tag"]},
         requires_citation=False),
]


def ladbs_sfd_rules() -> List[Rule]:
    """The LADBS SFD overlay rule set (copy so callers can't mutate the module)."""
    return list(LADBS_SFD_RULES)
