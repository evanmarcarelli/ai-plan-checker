"""Tests for the correction-checklist ingestion + per-department injection.

These cover the deterministic plumbing (load → select → requirements). The
LLM-dependent depth (how many corrections actually surface on a real plan) is
validated separately by the golden-set harness, which needs an API key.
"""
from app.code_library.checklists.loader import load_checklists, select_checklist
from app.code_library.checklists.checker import checklist_requirements
from app.code_library.checklists.build_from_pdf import _parse_numbered_lines
from app.models.schemas import ExtractedPlanData


def test_checklist_loads_with_items():
    lists = load_checklists()
    assert lists, "expected at least one ingested checklist"
    total = sum(len(c.items) for c in lists)
    assert total >= 100, f"expected a deep checklist, got {total} items"


def test_items_carry_provenance():
    cl = load_checklists()[0]
    assert cl.source.url and cl.source.edition and cl.source.jurisdiction
    # Every item must name a department and carry text.
    for it in cl.items:
        assert it.text and it.department_code


def test_select_matches_residential_and_skips_commercial():
    assert select_checklist("R-3") is not None
    assert select_checklist("R3") is not None
    # Commercial / unknown must NOT borrow the residential list.
    assert select_checklist("B") is None
    assert select_checklist(None) is None


def test_requirements_grouped_by_department_and_cited():
    reqs = checklist_requirements(ExtractedPlanData(occupancy_type="R-3"), max_per_department=40)
    assert reqs, "R-3 plan should get correction-list requirements"
    assert "building_safety" in reqs
    # The cap is honored.
    assert all(len(v) <= 40 for v in reqs.values())
    # Each injected requirement is uniquely citable (the gate keys on code_id).
    ids = [r.code_id for v in reqs.values() for r in v]
    assert len(ids) == len(set(ids)), "code_ids must be unique for the citation gate"
    # Completeness items keep their source URL for provenance.
    sample = reqs["building_safety"][0]
    assert sample.requirement_type == "completeness"
    assert sample.source.startswith("http")


def test_commercial_plan_gets_no_residential_corrections():
    assert checklist_requirements(ExtractedPlanData(occupancy_type="B")) == {}


def test_jurisdiction_steers_checklist_selection():
    # An LA plan should get the LADBS list; a non-LA CA plan should fall back to
    # the least jurisdiction-specific list (no LA-Municipal zoning leakage).
    la = select_checklist("R-3", state="CA", city="Los Angeles")
    other = select_checklist("R-3", state="CA", city="Fresno")
    assert la is not None and other is not None
    assert "los angeles" in la.source.jurisdiction.lower()
    # The fallback list carries no inherently-local (zoning) items.
    assert not any(i.department_code == "zoning" for i in other.items)


def test_numbered_parser_handles_two_column_sheet():
    lines = [
        "1. Cover-page instruction before any PART must be ignored.",
        "PART III: BUILDING CODE REQUIREMENTS",
        "1. An item under a PART but before any section is skipped.",
        "D. FIRE-RESISTANCE RATED CONSTRUCTION",
        "1. Provide 1-hr fire-resistance exterior walls if fire",
        "separation distance is:",
        "a. Less than 5’ [T-R302.1(1)], or",
        "b. Less than 3’ if sprinklered. R313",
        "2. Show how 1-hr fire-resistance is being provided.",
        "B. CLEARANCES",
        "1. Obtain all clearances as noted on the worksheet. ATTACHED: bleed tail",
    ]
    items = _parse_numbered_lines(lines)
    by_id = {it.item_id: it for it in items}
    # Cover-page item and the section-less item are dropped.
    assert "III.D.1" in by_id and "III.D.2" in by_id and "III.B.1" in by_id
    assert len(items) == 3
    d1 = by_id["III.D.1"]
    # Lettered sub-items are folded into the parent numbered item.
    assert "Less than 5" in d1.text and "sprinklered" in d1.text
    # Citation is extracted from the trailing/inline code reference.
    assert d1.code_citation == "T-R302.1(1)"
    assert d1.department_code == "building_safety"
    # Section drives the department mapping.
    assert by_id["III.B.1"].department_code == "public_works"
    # The supplemental-sheet bleed tail is cut at the ATTACHED: sentinel.
    assert "bleed" not in by_id["III.B.1"].text
