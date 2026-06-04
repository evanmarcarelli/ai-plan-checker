"""Tests for the ported deterministic rule engine + citation gate.

These are the regression guard for the code-math. They do NOT touch the LLM,
the network, or a real PDF — the whole point of the deterministic engine is
that it is pure and testable.
"""
from app.code_library.deterministic.checkers import (
    check_allowable_area,
    check_allowable_stories,
    check_min_exits,
    required_min_exits,
)
from app.code_library.deterministic.citation_gate import apply_citation_gate
from app.code_library.deterministic.engine import (
    evaluate_plan,
    normalize_construction_type,
    normalize_occupancy,
)
from app.models.schemas import (
    CodeRequirement,
    ComplianceFinding,
    ComplianceStatus,
    ExtractedPlanData,
)


# ---------------- checker primitives ----------------

def test_area_over_limit_fails():
    r = check_allowable_area("B", "V-B", 12000)  # B/V-B limit 9000
    assert r.status == "fail"


def test_area_within_limit_passes():
    r = check_allowable_area("B", "V-B", 8000)
    assert r.status == "pass"


def test_area_unlimited_passes():
    r = check_allowable_area("B", "I-A", 999999)
    assert r.status == "pass"


def test_area_missing_input_is_info():
    assert check_allowable_area(None, "V-B", 8000).status == "info"


def test_stories_non_sprinklered_loses_a_floor():
    # B/V-B tabular limit is 2; non-sprinklered drops to 1.
    assert check_allowable_stories("B", "V-B", 2, sprinklered=False).status == "fail"
    assert check_allowable_stories("B", "V-B", 2, sprinklered=True).status == "pass"


def test_min_exits_thresholds():
    assert required_min_exits(500) == 2
    assert required_min_exits(501) == 3
    assert required_min_exits(1001) == 4
    assert check_min_exits(600, declared_exits=2).status == "fail"
    assert check_min_exits(600, declared_exits=3).status == "pass"


# ---------------- normalization ----------------

def test_normalize_occupancy():
    assert normalize_occupancy("Group B Business") == "B"
    assert normalize_occupancy("R-3 single family") == "R-3"
    assert normalize_occupancy(None) is None


def test_normalize_construction_type():
    assert normalize_construction_type("Type V-B") == "V-B"
    assert normalize_construction_type("II-A") == "II-A"
    assert normalize_construction_type("I-B construction") == "I-B"


# ---------------- engine ----------------

def _plan(**kw) -> ExtractedPlanData:
    base = dict(
        project_address="1 Main St, Los Angeles, CA",
        occupancy_type="B",
        construction_type="V-B",
        raw_text_by_page={1: "site plan"},
    )
    base.update(kw)
    return ExtractedPlanData(**base)


def test_engine_flags_area_and_stories():
    pd = _plan(per_story_area=12000, building_area=12000, stories=3)
    findings = {f.code_requirement.code_id: f for f in evaluate_plan(pd)}
    assert findings["COM-AREA-ALLOWABLE"].status == ComplianceStatus.NON_COMPLIANT
    assert findings["COM-STORIES-ALLOWABLE"].status == ComplianceStatus.NON_COMPLIANT


def test_engine_drops_passing_by_default():
    pd = _plan(per_story_area=2000, building_area=2000, stories=1)
    ids = {f.code_requirement.code_id for f in evaluate_plan(pd)}
    # Area is within limit, so the area rule should not appear as a finding.
    assert "COM-AREA-ALLOWABLE" not in ids


def test_wui_rules_skip_without_zone():
    pd = _plan()  # no wui_zone
    ids = {f.code_requirement.code_id for f in evaluate_plan(pd)}
    assert "FIRE-WUI-VENT" not in ids
    assert "FIRE-WUI-DECK" not in ids


def test_wui_rules_apply_with_zone():
    pd = _plan(wui_zone="very_high")
    findings = {f.code_requirement.code_id: f for f in evaluate_plan(pd)}
    # Spec absent from the sparse plan text -> fail once gated in.
    assert findings["FIRE-WUI-VENT"].status == ComplianceStatus.NON_COMPLIANT


# ---------------- citation gate ----------------

class _FakeSource:
    """Minimal corpus stub: knows exactly one section."""

    def __init__(self, known_section="302.1", text="verbatim code text"):
        self._known = known_section
        self._text = text

    def verify_citation(self, c):
        return self._known in (c or "")

    def get_source_text(self, c):
        return self._text if self.verify_citation(c) else None


def test_gate_downgrades_unverifiable_assertion():
    f = ComplianceFinding(
        finding_id="1",
        code_requirement=CodeRequirement(code_id="X", section="IBC Table 506.2", description="x"),
        status=ComplianceStatus.NON_COMPLIANT,
        description="area over limit",
        source_citation="IBC Table 506.2",
        verified=False,
    )
    stats = apply_citation_gate([f], _FakeSource(known_section="999"), enforce=True)
    assert f.status == ComplianceStatus.NEEDS_REVIEW
    assert stats.downgraded == 1


def test_gate_verifies_and_enriches_when_in_corpus():
    f = ComplianceFinding(
        finding_id="1",
        code_requirement=CodeRequirement(code_id="X", section="302.1", description="x"),
        status=ComplianceStatus.NON_COMPLIANT,
        description="occupancy issue",
        source_citation="IBC 302.1",
        verified=False,
    )
    stats = apply_citation_gate([f], _FakeSource(known_section="302.1"), enforce=True)
    assert f.verified is True
    assert f.source_text == "verbatim code text"
    assert f.status == ComplianceStatus.NON_COMPLIANT  # not downgraded
    assert stats.verified == 1


def test_ladbs_rules_only_inject_when_flagged():
    pd = _plan(plan_type="residential", occupancy_type="R-3")
    no_ladbs = {f.code_requirement.code_id for f in evaluate_plan(pd, ladbs_sfd=False)}
    with_ladbs = {f.code_requirement.code_id for f in evaluate_plan(pd, ladbs_sfd=True)}
    assert not any(i.startswith("LADBS-SFD") for i in no_ladbs)
    assert any(i.startswith("LADBS-SFD") for i in with_ladbs)


def test_ladbs_rfa_flags_missing_then_passes_when_present():
    base = dict(project_address="X, Los Angeles, CA", plan_type="residential",
                occupancy_type="R-3", construction_type="V-B")
    missing = ExtractedPlanData(raw_text_by_page={1: "site plan only"}, **base)
    present = ExtractedPlanData(
        raw_text_by_page={1: "RFA residential floor area calculations on A2203"}, **base)
    miss = {f.code_requirement.code_id: f for f in evaluate_plan(missing, ladbs_sfd=True)}
    pres = {f.code_requirement.code_id for f in evaluate_plan(present, ladbs_sfd=True)}
    assert miss["LADBS-SFD-RFA"].status == ComplianceStatus.NON_COMPLIANT
    assert "LADBS-SFD-RFA" not in pres   # present -> not flagged


def test_ladbs_wui_rules_gate_on_zone():
    base = dict(project_address="X, Los Angeles, CA", plan_type="residential",
                occupancy_type="R-3", raw_text_by_page={1: "no fire notes"})
    no_zone = {f.code_requirement.code_id for f in evaluate_plan(ExtractedPlanData(**base), ladbs_sfd=True)}
    with_zone = {f.code_requirement.code_id
                 for f in evaluate_plan(ExtractedPlanData(wui_zone="very_high", **base), ladbs_sfd=True)}
    assert "LADBS-SFD-WUI" not in no_zone        # gated out without a fire zone
    assert "LADBS-SFD-WUI" in with_zone          # fires in VHFHSZ when notes absent


def test_deterministic_context_feeds_reviewers_by_category():
    """#2: department reviewers receive their category's verified findings as
    authoritative context, and only their category's."""
    from app.agents.departments import ALL_DEPARTMENTS

    pd = _plan(per_story_area=12000, building_area=12000, stories=3)
    det = evaluate_plan(pd)  # produces building_safety findings (area/stories)

    by_cat = {cls().category: cls() for cls in ALL_DEPARTMENTS}
    building = by_cat.get("building_safety")
    assert building is not None
    block = building._deterministic_context(det)
    # The building reviewer sees the area/story findings as authoritative.
    assert "VERIFIED DETERMINISTIC FINDINGS" in block
    assert "do NOT recompute" in block.lower() or "Do NOT recompute" in block
    assert "COM-AREA-ALLOWABLE" in block

    # A department whose category has no findings sees nothing (no false
    # context). public_works has no deterministic rules.
    public_works = by_cat.get("public_works")
    if public_works is not None:
        assert public_works._deterministic_context(det) == ""

    # No findings -> empty context.
    assert building._deterministic_context([]) == ""
    assert building._deterministic_context(None) == ""


def test_per_department_plan_retrieval_routes_pages():
    """#3: each department sees the title page plus its own domain pages."""
    from app.agents.departments import ALL_DEPARTMENTS

    by_cat = {cls().category: cls() for cls in ALL_DEPARTMENTS}
    pd = ExtractedPlanData(raw_text_by_page={
        1: "TITLE SHEET. Code analysis: occupancy B, construction type V-B.",
        2: "ELECTRICAL panel schedule, 400A service entrance, GFCI receptacles, grounding.",
        3: "PLUMBING fixture schedule, water closet, lavatory, backflow, drain vent.",
        4: "MECHANICAL HVAC ductwork exhaust ventilation combustion air refrigerant.",
    })

    def pages_seen(cat):
        txt = by_cat[cat]._relevant_plan_text(pd)
        return sorted(int(s.split("]")[0]) for s in txt.split("[PAGE ")[1:])

    assert pages_seen("electrical") == [1, 2]
    assert pages_seen("plumbing") == [1, 3]
    assert pages_seen("mechanical") == [1, 4]
    # Title page is always the anchor.
    assert 1 in pages_seen("building_safety")


def test_per_department_retrieval_degrades_safely():
    """#3: no plan text -> empty string (no crash, no regression)."""
    from app.agents.departments import ALL_DEPARTMENTS
    dept = ALL_DEPARTMENTS[0]()
    assert dept._relevant_plan_text(None) == ""
    assert dept._relevant_plan_text(ExtractedPlanData()) == ""


def test_few_shot_corrections_in_every_department_prompt():
    """#4: each department's system prompt carries domain example corrections,
    and the examples contain no project PII."""
    import re
    from app.agents.departments import ALL_DEPARTMENTS
    from app.agents.few_shot_corrections import EXAMPLE_CORRECTIONS

    for cls in ALL_DEPARTMENTS:
        d = cls()
        assert "EXAMPLE CORRECTIONS" in d._get_system_prompt(), d.category

    blob = " ".join(sum(EXAMPLE_CORRECTIONS.values(), []))
    assert not re.search(r"16026|miami way|walker|scofield|B26VN", blob, re.I)


def test_gate_enrich_mode_never_downgrades():
    f = ComplianceFinding(
        finding_id="1",
        code_requirement=CodeRequirement(code_id="X", section="IBC 506.2", description="x"),
        status=ComplianceStatus.NON_COMPLIANT,
        description="x",
        source_citation="IBC 506.2",
        verified=False,
    )
    apply_citation_gate([f], _FakeSource(known_section="999"), enforce=False)
    assert f.status == ComplianceStatus.NON_COMPLIANT  # left alone in enrich mode
