"""Deterministic rule evaluator.

Runs the rule knowledge base over ExtractedPlanData and returns high-trust
ComplianceFindings. Mirrors evaluateAll() in plan-room-ahj's evaluate.ts:
the LLM is never asked to do the code-math — these findings are computed.

Status mapping (CheckResult -> ComplianceStatus):
    pass  -> COMPLIANT
    fail  -> NON_COMPLIANT
    warn  -> NEEDS_REVIEW
    info  -> NOT_APPLICABLE   (could not evaluate; missing input)
"""
from __future__ import annotations

import re
import uuid
from typing import List, Optional

from app.code_library.deterministic import checkers as ck
from app.code_library.deterministic.rules import (
    BASELINE_RULES,
    CALFIRE_WUI_RULES,
    CALGREEN_MANDATORY_RULES,
    DISCIPLINE_TO_CATEGORY,
    Rule,
)
from app.models.schemas import (
    CodeRequirement,
    ComplianceFinding,
    ComplianceStatus,
    ExtractedPlanData,
)

# severity (rule) -> severity (ComplianceFinding scale)
_SEVERITY_MAP = {
    "critical": "critical",
    "major": "high",
    "moderate": "medium",
    "minor": "low",
}

_STATUS_MAP = {
    "pass": ComplianceStatus.COMPLIANT,
    "fail": ComplianceStatus.NON_COMPLIANT,
    "warn": ComplianceStatus.NEEDS_REVIEW,
    "info": ComplianceStatus.NOT_APPLICABLE,
}

# IBC occupancy group token, e.g. "B", "A-2", "R-3", "S-1".
_OCC_RE = re.compile(r"\b([ABEFHIMRS](?:-\d)?)\b")
# Construction type token, e.g. "V-B", "II-A", "I-A".
_CTYPE_RE = re.compile(r"\b(I{1,3}|IV|V)(?:-([AB]))?\b")


def normalize_occupancy(raw: Optional[str]) -> Optional[str]:
    """Pull an IBC occupancy group token out of a free-text occupancy string."""
    if not raw:
        return None
    m = _OCC_RE.search(raw.upper())
    return m.group(1) if m else None


def normalize_construction_type(raw: Optional[str]) -> Optional[str]:
    """Normalize a construction-type string to canonical 'V-B' / 'II-A' form."""
    if not raw:
        return None
    m = _CTYPE_RE.search(raw.upper().replace("TYPE", "").strip())
    if not m:
        return None
    roman, letter = m.group(1), m.group(2)
    return f"{roman}-{letter}" if letter else roman


def _plan_text(plan_data: ExtractedPlanData) -> str:
    """Concatenate everything the keyword checks should search."""
    parts: List[str] = []
    if plan_data.title_block_text:
        parts.append(plan_data.title_block_text)
    for _, page_text in sorted((plan_data.raw_text_by_page or {}).items()):
        if page_text:
            parts.append(page_text)
    for el in plan_data.elements or []:
        if el.raw_text:
            parts.append(el.raw_text)
    return "\n".join(parts)


def _check_required_keyword(text: str, patterns: List[str]) -> ck.CheckResult:
    """At least one pattern must match somewhere in the plan text."""
    if not text:
        return ck.CheckResult("warn", "No plan text available to search.")
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return ck.CheckResult("pass", f"Found required element matching /{pat}/.")
    return ck.CheckResult(
        "fail",
        f"Required element not found (searched {len(patterns)} pattern(s)).",
    )


def _evaluate_rule(rule: Rule, plan_data: ExtractedPlanData, text: str) -> ck.CheckResult:
    """Dispatch one rule to its checker. Returns a CheckResult."""
    t = rule.check.get("type")
    occ = normalize_occupancy(plan_data.occupancy_type)
    ctype = normalize_construction_type(plan_data.construction_type)
    # Optional fields the Surveyor may or may not populate yet.
    occupant_load = getattr(plan_data, "occupant_load", None)
    sprinklered = getattr(plan_data, "sprinklered", None)

    if t == "required_keyword":
        return _check_required_keyword(text, rule.check.get("patterns", []))

    if t == "occupancy_declared":
        return (ck.CheckResult("pass", f"Occupancy declared: {plan_data.occupancy_type}.")
                if occ else ck.CheckResult("fail", "Occupancy classification not declared."))

    if t == "construction_type_declared":
        return (ck.CheckResult("pass", f"Construction type declared: {plan_data.construction_type}.")
                if ctype else ck.CheckResult("fail", "Construction type not declared."))

    if t == "occupant_load_declared":
        return (ck.CheckResult("pass", f"Occupant load declared: {occupant_load}.")
                if occupant_load is not None
                else ck.CheckResult("warn", "Design occupant load not declared."))

    if t == "allowable_area_check":
        # Per-story area is the right input for Table 506.2; fall back to the
        # gross building area when per-story isn't broken out.
        area = getattr(plan_data, "per_story_area", None) or plan_data.building_area
        return ck.check_allowable_area(occ, ctype, area)

    if t == "stories_check":
        return ck.check_allowable_stories(occ, ctype, plan_data.stories, sprinklered)

    if t == "high_rise_check":
        return ck.check_high_rise(plan_data.building_height, sprinklered)

    if t == "num_exits_check":
        declared_exits = getattr(plan_data, "declared_exits", 0) or 0
        return ck.check_min_exits(occupant_load, declared_exits)

    if t == "exit_capacity_check":
        door_w = getattr(plan_data, "declared_door_width_in", 0) or 0
        stair_w = getattr(plan_data, "declared_stair_width_in", 0) or 0
        return ck.check_exit_capacity(occupant_load, door_w, stair_w)

    if t == "plumbing_fixture_calc":
        actual_wc = getattr(plan_data, "actual_wc", None)
        actual_lav = getattr(plan_data, "actual_lav", None)
        return ck.check_fixtures(occ, occupant_load, actual_wc, actual_lav)

    if t == "wui_zone_check":
        # WUI zone is an address-derived overlay (CalFire FHSZ). Until the
        # Surveyor attaches a wui_zone, this can't be evaluated — return info
        # so it is dropped rather than false-flagged.
        wui_zone = getattr(plan_data, "wui_zone", None)
        if not wui_zone:
            return ck.CheckResult("info", "No WUI zone resolved for this project.")
        return ck.CheckResult(
            "warn",
            "Project is in a WUI fire hazard zone — verify CBC Chapter 7A "
            "ignition-resistant construction (roofing, walls, decks, vents, glazing) is specified.",
        )

    if t == "wui_keyword_check":
        # Two-stage: only applies inside a WUI zone; once gated, the spec
        # keyword must be present or it's a fail. No zone -> info (skip).
        wui_zone = getattr(plan_data, "wui_zone", None)
        if not wui_zone:
            return ck.CheckResult("info", "Not in a WUI zone — rule does not apply.")
        kw = _check_required_keyword(text, rule.check.get("patterns", []))
        if kw.status == "pass":
            return kw
        return ck.CheckResult(
            "fail",
            "WUI zone: required ignition-resistant spec not found on plans.",
        )

    return ck.CheckResult("info", f"No checker implemented for '{t}'.")


def _to_finding(rule: Rule, result: ck.CheckResult) -> ComplianceFinding:
    """Map a (Rule, CheckResult) pair to a ComplianceFinding."""
    status = _STATUS_MAP.get(result.status, ComplianceStatus.NEEDS_REVIEW)
    category = DISCIPLINE_TO_CATEGORY.get(rule.discipline, "building_safety")
    code_req = CodeRequirement(
        code_id=rule.id,
        code_name=rule.code_ref.split("·")[0].strip(),
        section=rule.code_ref,
        description=rule.description,
        category=category,
        requirement_type="deterministic",
        source="deterministic_engine",
    )
    return ComplianceFinding(
        finding_id=str(uuid.uuid4()),
        code_requirement=code_req,
        status=status,
        description=result.summary,
        recommendation=(rule.description if status == ComplianceStatus.NON_COMPLIANT else None),
        severity=_SEVERITY_MAP.get(rule.severity, "medium"),
        category=category,
        # Provenance: these come from the deterministic engine, not the LLM.
        # The citation gate fills verified/source_text/source_citation for the
        # ones that require_citation; declarative rules are inherently verified.
        verified=not rule.requires_citation,
        source_citation=rule.code_ref,
    )


def evaluate_plan(
    plan_data: ExtractedPlanData,
    *,
    rules: Optional[List[Rule]] = None,
    overlays: Optional[List[str]] = None,
    ladbs_sfd: bool = False,
    include_passing: bool = False,
) -> List[ComplianceFinding]:
    """Run the deterministic rule set over plan_data.

    By default only actionable findings (NON_COMPLIANT / NEEDS_REVIEW) are
    returned — NOT_APPLICABLE (couldn't evaluate) and COMPLIANT are dropped
    unless include_passing=True. This keeps the deterministic findings tight
    and high-signal alongside the LLM department reviews.

    `overlays` (from the adoption resolver, e.g. ["very_high_fhsz", "hillside"])
    drives which overlay rule sets are injected. When omitted, the rule set is
    inferred from the project address (CA -> WUI + CALGreen).
    """
    rules = rules if rules is not None else default_rules_for(
        plan_data, overlays=overlays, ladbs_sfd=ladbs_sfd
    )
    text = _plan_text(plan_data)
    findings: List[ComplianceFinding] = []
    for rule in rules:
        result = _evaluate_rule(rule, plan_data, text)
        if not include_passing and result.status in ("pass", "info"):
            continue
        findings.append(_to_finding(rule, result))
    return findings


def default_rules_for(
    plan_data: ExtractedPlanData,
    overlays: Optional[List[str]] = None,
    ladbs_sfd: bool = False,
) -> List[Rule]:
    """Pick the rule set. Baseline always; CA overlays when applicable.

    When `overlays` is supplied (from the adoption resolver) it is
    authoritative: a fire-hazard overlay injects the CalFire WUI rules. When
    omitted, fall back to inferring CA from the project address. CALGreen is
    injected for any CA jurisdiction. WUI rules gate internally on wui_zone,
    so including them never produces a false positive on a non-WUI parcel.

    `ladbs_sfd=True` injects the LADBS Single-Family-Dwelling overlay rules
    (learned from real LADBS corrections) — the LA-specific completeness items
    a LADBS examiner checks on an SFD/duplex.
    """
    rules = list(BASELINE_RULES)
    state = (getattr(plan_data, "state_code", None) or "").upper()
    address = (plan_data.project_address or "").upper()
    is_ca = state == "CA" or ", CA" in address or "CALIFORNIA" in address

    if overlays is not None:
        fire_overlay = any(o in overlays for o in ("very_high_fhsz", "high_fhsz", "fhsz"))
        if fire_overlay:
            rules += CALFIRE_WUI_RULES
        if is_ca:
            rules += CALGREEN_MANDATORY_RULES
    elif is_ca:
        rules += CALFIRE_WUI_RULES + CALGREEN_MANDATORY_RULES

    if ladbs_sfd:
        from app.code_library.deterministic.ladbs_rules import LADBS_SFD_RULES
        rules += LADBS_SFD_RULES
    return rules


def rules_for_jurisdiction(state: Optional[str]) -> List[Rule]:
    """Rule set for a given state code, independent of a plan object."""
    rules = list(BASELINE_RULES)
    if (state or "").upper() == "CA":
        rules += CALFIRE_WUI_RULES + CALGREEN_MANDATORY_RULES
    return rules
