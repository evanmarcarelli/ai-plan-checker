"""Few-shot example corrections per department category.

#4 — These are de-identified examples of how a real LADBS examiner phrases
corrections, distilled from real correction sets (no project data). Injected
into each department reviewer's system prompt so the model matches the
specificity, tone, and code-citation style of an actual examiner instead of
producing generic findings.

Keep these GENERIC (no addresses, names, plan-check numbers) — they teach
pattern, not project facts.
"""
from typing import Dict, List

EXAMPLE_CORRECTIONS: Dict[str, List[str]] = {
    "building_safety": [
        "Provide complete cross sections specifying ceiling heights; where ceiling "
        "height exceeds 14 ft the area shall be counted twice in floor-area calculations.",
        "Provide a wall schedule clarifying wall thickness and material; add wall "
        "tags to the dimension plan.",
        "Each sheet of the architectural and structural plans must bear the "
        "signature and registration of an architect or engineer licensed in California.",
    ],
    "zoning": [
        "Provide a Residential Floor Area (RFA) summary per structure with any "
        "exemptions used; attic areas with ceiling height over 7 ft must be "
        "included (see RFA definition, LAMC 12.03).",
        "Identify the lowest point of grade within 5 ft of the building perimeter "
        "as the Datum Point on the plot plan, sections, and elevations; building "
        "height is measured from it.",
        "Show overall dimensions and setbacks to all property lines on the site plan.",
        "Clarify fire-rebuild eligibility (EO-1 vs EO-8) in the scope of work; EO-1 "
        "allows a maximum 10% increase in height and footprint.",
    ],
    "fire": [
        "Add fire sprinklers (NFPA 13D) to the single-family-dwelling scope of work.",
        "In a Very High Fire Hazard Severity Zone, comply with the CA Wildland-Urban "
        "Interface Code as amended by LAMC Chapter V, Article 7.1; add the required "
        "ignition-resistant construction notes.",
        "New buildings in a Very High FHSZ shall comply with LAMC Section 91.7207.",
    ],
    "electrical": [
        "Show a minimum 1-inch listed raceway for a dedicated 208/240-volt EVSE "
        "branch circuit, originating at the service or subpanel and terminating "
        "near the charging location.",
        "Specify the service entrance ampacity and main breaker rating on the "
        "electrical plans.",
    ],
    "plumbing": [
        "Add note: plumbing fixture flow rates shall comply with the maximum flow "
        "rates in CALGreen Section 4.303.1.",
        "Provide a plumbing fixture schedule; where a shower has more than one head, "
        "the combined flow shall not exceed 2.0 gpm at 80 psi.",
    ],
    "mechanical": [
        "Bathroom exhaust fans shall be ENERGY STAR compliant, ducted to the "
        "exterior, and controlled by a humidity control.",
        "State that fireplaces are direct-vent, sealed-combustion type and "
        "incorporate the manufacturer's specifications onto the plans.",
        "Declare minimum outdoor-air ventilation rates on the mechanical schedule.",
    ],
    "energy": [
        "Identify the roofing product SRI (or solar reflectance + thermal emittance) "
        "and show it meets the minimum cool-roof values for the roof slope.",
        "Incorporate the Mandatory Requirements Checklist for new residential "
        "buildings (Form GRN 4) into the plans.",
        "Incorporate the VOC and Formaldehyde Limits (Form GRN 11) into the plans.",
    ],
    "accessibility": [
        "Provide an accessible route connecting accessible parking, the public way, "
        "and the primary entrance.",
        "Provide at least one accessible toilet compartment with compliant "
        "clearances, grab bars, and dispenser heights per CBC 11B-604.",
    ],
    "public_works": [
        "Obtain Low Impact Development (LID) sign-off from the Watershed Protection "
        "Division for new construction over 500 sq ft of impervious area.",
        "Show driveway approach, curb cut, and right-of-way improvements matching "
        "the civil plans.",
    ],
    "environmental": [
        "Incorporate the Storm Water Pollution Control plan (Form GRN 1) into the "
        "construction plans.",
        "For methane-zone parcels, provide the methane mitigation system per the "
        "LADBS standard and identify the zone on the plans.",
    ],
}


def few_shot_block(category: str) -> str:
    """Return a prompt block of example corrections for a category, or '' if
    none are defined for it."""
    examples = EXAMPLE_CORRECTIONS.get(category) or []
    if not examples:
        return ""
    bullets = "\n".join(f'- "{e}"' for e in examples)
    return (
        "EXAMPLE CORRECTIONS in your domain (how a real building-department "
        "examiner phrases findings — match this specificity, tone, and code-"
        "citation style; these are examples only, not facts about THIS plan):\n"
        + bullets
    )
