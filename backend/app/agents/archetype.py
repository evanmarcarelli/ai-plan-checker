"""Project archetype classifier — intake out-of-scope gate.

Ported from plan-room-ahj/supabase/functions/_shared/archetype.ts. Runs
at intake to decide whether a submittal is inside the current pilot
scope. Out-of-scope plans get rejected before the rule engine even
runs — keeping the accuracy claim defensible.

"Pilot scope" is an archetype allowlist (see config/pilot.py). Pure
function — no LLM, no network. Inputs are the extracted plan data,
the resolved property overlay (if any), and the raw plan text for
keyword cues. Reasoning is human-readable so reviewers can see why
something was excluded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from app.config.pilot import (
    ARCHETYPE_HIGH_RISE_OR_MID_RISE,
    ARCHETYPE_LA_COASTAL_ZONE,
    ARCHETYPE_LA_HILLSIDE_SFR,
    ARCHETYPE_LA_HPOZ_PROPERTY,
    ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL,
    ARCHETYPE_LA_TI_COMMERCIAL,
    ARCHETYPE_MIXED_USE_NEW_CONSTRUCTION,
    ARCHETYPE_MULTIFAMILY_NEW_CONSTRUCTION,
    ARCHETYPE_UNCLASSIFIED,
    ARCHETYPE_VENTURA_AG_BUILDING,
    ARCHETYPE_VENTURA_SFR_TYP_VB_MINISTERIAL,
    ARCHETYPE_VENTURA_TI_COMMERCIAL,
    ARCHETYPE_VENTURA_VHFHSZ_SFR,
    PILOT_ARCHETYPES_DEFAULT,
)
from app.models.schemas import ExtractedPlanData


# =====================================================================
# Property profile — lightweight, optional. Populated from GIS overlay
# lookups (services/gis_overlays.py via site_resolver) when the customer
# provided a project address at upload; absent otherwise, in which case
# the gate falls back to plan-text cues, which is still valuable.
# =====================================================================
@dataclass
class ParcelInfo:
    jurisdiction: Optional[str] = None
    zoning_code: Optional[str] = None


@dataclass
class CoastalZoneInfo:
    in_coastal_zone: bool = False


@dataclass
class WuiInfo:
    in_wui: bool = False
    haz_class: Optional[str] = None  # e.g. "very_high"


@dataclass
class PropertyProfile:
    parcel: Optional[ParcelInfo] = None
    coastal_zone: Optional[CoastalZoneInfo] = None
    wui_zone: Optional[WuiInfo] = None
    # GIS-resolved LA-city overlay flags. None = not checked (no address /
    # layer failed) — only an explicit True triggers a reject, so unknown
    # never masquerades as "in zone".
    in_hpoz: Optional[bool] = None
    in_hillside: Optional[bool] = None


# =====================================================================
# Result
# =====================================================================
@dataclass
class ArchetypeResult:
    archetype: str
    in_pilot_scope: bool
    reasoning: List[str] = field(default_factory=list)
    excluded_overlays: List[str] = field(default_factory=list)


# =====================================================================
# Plan-text regex cues
# =====================================================================
_VENTURA_TEXT_CUE = re.compile(
    r"\bventura\s+county\b|\bcounty\s+of\s+ventura\b|\bcamarillo\b|"
    r"\bsimi\s+valley\b|\bthousand\s+oaks\b|\boxnard\b|\bojai\b|"
    r"\bmoorpark\b|\bport\s+hueneme\b|\bfillmore\b|\bsanta\s+paula\b",
    re.IGNORECASE,
)
_WUI_TEXT_CUE = re.compile(
    r"\bvery\s+high\s+fire\s+hazard\s+severity\s+zone\b|\bVHFHSZ\b|"
    r"\bWUI\b|\bChapter\s+7A\b",
    re.IGNORECASE,
)
_AG_TEXT_CUE = re.compile(
    r"\bagricultural\s+(building|structure|exempt)|\bA-E\b|\bAE-\d|"
    r"\bopen\s+space\s+agricultural\b",
    re.IGNORECASE,
)
_HILLSIDE_CUES = re.compile(
    r"\bbaseline\s+hillside|\bBHO\b|\bhillside\s+ordinance\b|"
    r"\bmulholland\b.*\bspecific\s+plan|RE40-?1H|RE15-?1H",
    re.IGNORECASE,
)
_HPOZ_CUES = re.compile(
    r"\bHPOZ\b|\bhistoric\s+preservation\s+overlay",
    re.IGNORECASE,
)
_TI_CUES = re.compile(
    r"\btenant\s+improvement\b|\bTI\b\s+plans?|interior\s+alteration|"
    r"interior\s+remodel|\bsuite\s+\d",
    re.IGNORECASE,
)
_HILLSIDE_ZONING_CODE = re.compile(r"H$|HILLSIDE|\bBMO\b|\bBHO\b", re.IGNORECASE)
# A plan that declares a detached single-family dwelling. R-3 occupancy and
# Type V-B construction are the default for these, so this cue lets us classify
# an obvious SFR even when the title sheet never spells out "R-3"/"V-B" in
# selectable text (common on residential sets).
_SFR_TEXT_CUE = re.compile(
    r"\bsingle[\s-]*family\s+(dwelling|residence|home|house)\b|"
    r"\bone[\s-]*family\s+dwelling\b|\bSFD\b|\bSFR\b|"
    r"\b(new|proposed|\(n\))\s+single[\s-]*family\b",
    re.IGNORECASE,
)


# =====================================================================
# classify_archetype
#
# Order matters: we check "kicked out by overlay" cases first (cheapest
# reject), then identify the in-scope archetype, then fall back to
# unclassified.
# =====================================================================
def classify_archetype(
    scope: ExtractedPlanData,
    plan_text: str,
    property_profile: Optional[PropertyProfile] = None,
    pilot_archetypes: Optional[Sequence[str]] = None,
) -> ArchetypeResult:
    """Decide whether this submittal is in the pilot's allowlist.

    Args:
        scope: The Surveyor's extracted plan data.
        plan_text: Raw extracted text from the plan PDF (for keyword cues).
        property_profile: Optional GIS-resolved property overlays. When
            absent, the gate falls back to plan-text cues + scope.wui_zone.
        pilot_archetypes: Per-agency allowlist override. Falls back to
            PILOT_ARCHETYPES_DEFAULT when None or empty.

    Returns:
        ArchetypeResult with the assigned archetype, in_pilot_scope
        verdict, human-readable reasoning, and any overlay flags that
        kicked the case out.
    """
    reasoning: List[str] = []
    excluded: List[str] = []

    # ---- Jurisdiction detection (plan-text + parcel hint) --------------
    parcel = property_profile.parcel if property_profile else None
    is_ventura = bool(
        (parcel and parcel.jurisdiction and re.search(r"ventura", parcel.jurisdiction, re.IGNORECASE))
        or _VENTURA_TEXT_CUE.search(plan_text or "")
    )

    # ---- Hard rejects: parcel-derived overlays -------------------------
    if parcel and parcel.zoning_code:
        z = parcel.zoning_code.upper()
        if _HILLSIDE_ZONING_CODE.search(z):
            excluded.append("Hillside / BHO zoning")
            reasoning.append(f'Parcel zoning code "{z}" indicates Hillside overlay')
            return _finalize(ARCHETYPE_LA_HILLSIDE_SFR, excluded, reasoning, pilot_archetypes)

    if property_profile and property_profile.in_hillside:
        excluded.append("Hillside Ordinance (GIS)")
        reasoning.append("Address falls inside the LA Hillside Ordinance area (GIS overlay)")
        return _finalize(ARCHETYPE_LA_HILLSIDE_SFR, excluded, reasoning, pilot_archetypes)

    if property_profile and property_profile.in_hpoz:
        excluded.append("HPOZ (GIS)")
        reasoning.append("Address falls inside a Historic Preservation Overlay Zone (GIS overlay)")
        return _finalize(ARCHETYPE_LA_HPOZ_PROPERTY, excluded, reasoning, pilot_archetypes)

    if property_profile and property_profile.coastal_zone and property_profile.coastal_zone.in_coastal_zone:
        # Coastal is an in-pilot archetype (allowlist) since the Coastal Act +
        # LCP corpus layers landed — classify it, but don't mark it excluded.
        # Agencies that override the allowlist without it still get a clean
        # out-of-scope verdict from _finalize.
        reasoning.append(
            "Address is inside the CA Coastal Zone — coastal code stack "
            "(Coastal Act + certified LCP) applies"
        )
        return _finalize(ARCHETYPE_LA_COASTAL_ZONE, excluded, reasoning, pilot_archetypes)

    # ---- Ventura County VHFHSZ reject ----------------------------------
    wui = property_profile.wui_zone if property_profile else None
    if is_ventura and wui and wui.in_wui:
        haz = wui.haz_class or "very_high"
        excluded.append(f"Ventura VHFHSZ ({haz})")
        reasoning.append(
            f"Address falls in CalFire {haz} FHSZ — CBC Ch. 7A wildfire-resistive "
            "materials review out of pilot scope"
        )
        return _finalize(ARCHETYPE_VENTURA_VHFHSZ_SFR, excluded, reasoning, pilot_archetypes)

    # Fall back to scope.wui_zone (set by surveyor when address is known)
    # plus plan-text cue, since ai-plan-checker doesn't yet populate
    # PropertyProfile.
    scope_wui = getattr(scope, "wui_zone", None)
    if is_ventura and scope_wui in ("very_high", "high"):
        excluded.append(f"Ventura VHFHSZ ({scope_wui})")
        reasoning.append(
            f"Address is flagged as {scope_wui} FHSZ — CBC Ch. 7A out of pilot scope"
        )
        return _finalize(ARCHETYPE_VENTURA_VHFHSZ_SFR, excluded, reasoning, pilot_archetypes)

    if is_ventura and _WUI_TEXT_CUE.search(plan_text or ""):
        excluded.append("Ventura VHFHSZ (plan-text cue)")
        reasoning.append("Plan text references Ventura County WUI / Very-High FHSZ")
        return _finalize(ARCHETYPE_VENTURA_VHFHSZ_SFR, excluded, reasoning, pilot_archetypes)

    # ---- Ventura County agricultural building reject -------------------
    if is_ventura and _AG_TEXT_CUE.search(plan_text or ""):
        excluded.append("Ventura agricultural building")
        reasoning.append(
            "Plan text indicates an agricultural-zoned structure "
            "(county-specific exemptions apply)"
        )
        return _finalize(ARCHETYPE_VENTURA_AG_BUILDING, excluded, reasoning, pilot_archetypes)

    # ---- Plan-text overlay cues (when no property profile) -------------
    if _HILLSIDE_CUES.search(plan_text or ""):
        excluded.append("Hillside / BHO (plan-text cue)")
        reasoning.append("Plan text references Baseline Hillside Ordinance or Hillside zoning")
        return _finalize(ARCHETYPE_LA_HILLSIDE_SFR, excluded, reasoning, pilot_archetypes)

    if _HPOZ_CUES.search(plan_text or ""):
        excluded.append("HPOZ")
        reasoning.append("Plan text references HPOZ (Historic Preservation Overlay Zone)")
        return _finalize(ARCHETYPE_LA_HPOZ_PROPERTY, excluded, reasoning, pilot_archetypes)

    # ---- Building scale rejects ----------------------------------------
    height = getattr(scope, "building_height", None)
    if height is not None and height > 75:
        excluded.append("High-rise (> 75 ft)")
        reasoning.append(f"Building height {height} ft exceeds 75 ft high-rise threshold")
        return _finalize(ARCHETYPE_HIGH_RISE_OR_MID_RISE, excluded, reasoning, pilot_archetypes)

    stories = getattr(scope, "stories", None)
    if stories is not None and stories >= 5:
        excluded.append("Mid-rise (>= 5 stories)")
        reasoning.append(
            f"{stories} stories puts this above the pilot single-family / TI scope"
        )
        return _finalize(ARCHETYPE_HIGH_RISE_OR_MID_RISE, excluded, reasoning, pilot_archetypes)

    # ---- In-scope identification ---------------------------------------
    has_ti_cue = bool(_TI_CUES.search(plan_text or ""))

    occupancy = (getattr(scope, "occupancy_type", None) or "").upper().strip()
    construction = (getattr(scope, "construction_type", None) or "").upper().strip()

    # Detect mixed occupancy via "+" or "/" in the occupancy_type string
    # (ai-plan-checker doesn't have a dedicated mixed_occupancy flag yet).
    mixed_occupancy = bool(occupancy and re.search(r"[+/]| AND |,", occupancy))

    # TI = explicit "tenant improvement" / interior alteration cues
    if has_ti_cue and not mixed_occupancy:
        if is_ventura:
            reasoning.append("Ventura County commercial tenant improvement")
            return _finalize(
                ARCHETYPE_VENTURA_TI_COMMERCIAL, excluded, reasoning, pilot_archetypes
            )
        reasoning.append("Plan text identifies this as a commercial tenant improvement")
        return _finalize(ARCHETYPE_LA_TI_COMMERCIAL, excluded, reasoning, pilot_archetypes)

    # SFR Type V-B = R-3, single occupancy, V-B construction, modest scale
    is_r3 = "R-3" in occupancy or occupancy == "R-3"
    is_vb = construction in ("V-B", "VB", "TYPE V-B", "V B")

    per_story = getattr(scope, "per_story_area", None)
    building_area = getattr(scope, "building_area", None)
    area_used = per_story if per_story is not None else (building_area or 0)
    modest_area = area_used <= 10_000

    low_rise = stories is None or stories <= 3

    if is_r3 and is_vb and modest_area and low_rise:
        if is_ventura:
            reasoning.append(
                "Ventura County single-family R-3 / Type V-B, <= 3 stories, "
                "no VHFHSZ or ag overlay"
            )
            return _finalize(
                ARCHETYPE_VENTURA_SFR_TYP_VB_MINISTERIAL,
                excluded,
                reasoning,
                pilot_archetypes,
            )
        reasoning.append("Single-family R-3 / Type V-B with modest area and <= 3 stories")
        return _finalize(
            ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL, excluded, reasoning, pilot_archetypes
        )

    # Robust SFR fallback: a detached single-family dwelling is R-3 / Type V-B
    # by default. Many residential title sheets never put the literal "R-3" /
    # "V-B" strings in selectable text (and vision can't read a code-data box
    # that isn't on the sheet), so requiring them rejects obviously in-scope
    # homes. When the plan text declares a single-family dwelling, there's no
    # TI / multifamily / mixed-occupancy signal, and it's low-rise + modest
    # area, treat it as the in-scope SFR archetype. The overlay rejects
    # (hillside, HPOZ, coastal, fire-zone, high/mid-rise) already ran above, so
    # we can't mislabel one of those as a plain SFR here.
    sfr_by_text = bool(_SFR_TEXT_CUE.search(plan_text or ""))
    bigger_use = mixed_occupancy or "R-1" in occupancy or "R-2" in occupancy
    if sfr_by_text and not has_ti_cue and not bigger_use and modest_area and low_rise:
        note = (
            " (occupancy/construction not explicit in the plan text — inferred "
            "the R-3 / Type V-B default for a detached dwelling)"
        )
        if is_ventura:
            reasoning.append("Ventura County single-family dwelling declared in plan text" + note)
            return _finalize(
                ARCHETYPE_VENTURA_SFR_TYP_VB_MINISTERIAL, excluded, reasoning, pilot_archetypes
            )
        reasoning.append("Single-family dwelling declared in plan text" + note)
        return _finalize(
            ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL, excluded, reasoning, pilot_archetypes
        )

    # Multifamily new construction = R-1 or R-2 + no TI cue
    if ("R-1" in occupancy or "R-2" in occupancy) and not has_ti_cue:
        reasoning.append("R-1 / R-2 occupancy without TI markers — multifamily new construction")
        return _finalize(
            ARCHETYPE_MULTIFAMILY_NEW_CONSTRUCTION, excluded, reasoning, pilot_archetypes
        )

    # Mixed-use new construction
    if mixed_occupancy and not has_ti_cue:
        reasoning.append("Mixed-occupancy declaration without TI markers — likely new construction")
        return _finalize(
            ARCHETYPE_MIXED_USE_NEW_CONSTRUCTION, excluded, reasoning, pilot_archetypes
        )

    # Fallback: we couldn't confidently bucket it
    reasoning.append("Could not classify into a known archetype — manual triage required")
    return _finalize(ARCHETYPE_UNCLASSIFIED, excluded, reasoning, pilot_archetypes)


# =====================================================================
# Internal helpers
# =====================================================================
def _finalize(
    archetype: str,
    excluded: List[str],
    reasoning: List[str],
    pilot_archetypes: Optional[Sequence[str]],
) -> ArchetypeResult:
    """Bind an archetype label to its in_pilot_scope verdict.

    If the agency hasn't set a pilot allowlist, accept everything that
    would otherwise be in PILOT_ARCHETYPES_DEFAULT. If it has set one,
    the agency allowlist wins.
    """
    allow = pilot_archetypes if pilot_archetypes else PILOT_ARCHETYPES_DEFAULT
    return ArchetypeResult(
        archetype=archetype,
        in_pilot_scope=archetype in allow,
        reasoning=reasoning,
        excluded_overlays=excluded,
    )


# =====================================================================
# Human-readable reason for the dashboard / comment letter
# =====================================================================
def render_archetype_banner(result: ArchetypeResult) -> str:
    """One-line summary for the reviewer dashboard."""
    if result.in_pilot_scope:
        return f"In-pilot archetype: {result.archetype}. AI triage proceeded."
    why = (
        "; ".join(result.excluded_overlays)
        if result.excluded_overlays
        else (result.reasoning[-1] if result.reasoning else "Out of current pilot scope")
    )
    return (
        f"OUT OF PILOT SCOPE ({result.archetype}). Reason: {why}. Send to manual review."
    )
