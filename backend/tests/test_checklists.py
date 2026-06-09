"""Tests for the correction-checklist ingestion + per-department injection.

These cover the deterministic plumbing (load → select → requirements). The
LLM-dependent depth (how many corrections actually surface on a real plan) is
validated separately by the golden-set harness, which needs an API key.
"""
from app.code_library.checklists.loader import load_checklists, select_checklist
from app.code_library.checklists.checker import checklist_requirements
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
