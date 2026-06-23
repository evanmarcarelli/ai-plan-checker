"""Unit tests for the department routing pre-screen (select_departments).

Pure-function tests — no LLM, no network. They assert WHICH departments run
for representative archetypes, and that the router FAILS OPEN on every
unknown / out-of-scope / unmapped signal.
"""
from app.agents.archetype import ArchetypeResult
from app.agents.departments import ALL_DEPARTMENTS
from app.agents.routing import select_departments
from app.config.pilot import (
    ARCHETYPE_LA_COASTAL_ZONE,
    ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL,
    ARCHETYPE_LA_TI_COMMERCIAL,
    ARCHETYPE_MULTIFAMILY_NEW_CONSTRUCTION,
    ARCHETYPE_UNCLASSIFIED,
    ARCHETYPE_VENTURA_TI_COMMERCIAL,
)

# The full panel of department categories, derived from the real registry so
# the test tracks the production department list automatically.
ALL_CATEGORIES = {cls.category for cls in ALL_DEPARTMENTS}


def _arch(name: str, in_scope: bool) -> ArchetypeResult:
    return ArchetypeResult(archetype=name, in_pilot_scope=in_scope)


def test_sfr_complete_runs_all_departments():
    """A complete SFR is ground-up site work — every department applies."""
    result = select_departments(
        ALL_CATEGORIES, _arch(ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL, True)
    )
    assert result == ALL_CATEGORIES


def test_commercial_ti_skips_public_works_and_environmental():
    """Interior TI: no site/soil/ROW work, so Public Works + Environmental
    are provably inapplicable and skipped — everything else still runs."""
    result = select_departments(
        ALL_CATEGORIES, _arch(ARCHETYPE_LA_TI_COMMERCIAL, True)
    )
    assert result == ALL_CATEGORIES - {"public_works", "environmental"}
    # The substantive reviewers must NOT be skipped.
    for kept in ("building_safety", "fire", "electrical", "plumbing",
                 "mechanical", "accessibility", "energy", "zoning"):
        assert kept in result


def test_ventura_commercial_ti_skips_same_set():
    result = select_departments(
        ALL_CATEGORIES, _arch(ARCHETYPE_VENTURA_TI_COMMERCIAL, True)
    )
    assert result == ALL_CATEGORIES - {"public_works", "environmental"}


def test_out_of_scope_archetype_runs_all():
    """Out-of-pilot archetype (e.g. multifamily new construction) must fail
    OPEN — the full panel runs even though it's not in the skip map."""
    result = select_departments(
        ALL_CATEGORIES, _arch(ARCHETYPE_MULTIFAMILY_NEW_CONSTRUCTION, False)
    )
    assert result == ALL_CATEGORIES


def test_unclassified_runs_all():
    """Unknown archetype -> run everything."""
    result = select_departments(
        ALL_CATEGORIES, _arch(ARCHETYPE_UNCLASSIFIED, False)
    )
    assert result == ALL_CATEGORIES


def test_none_archetype_runs_all():
    """No archetype object at all (classification did not run) -> fail open."""
    assert select_departments(ALL_CATEGORIES, None) == ALL_CATEGORIES


def test_in_scope_but_unmapped_archetype_runs_all():
    """An in-pilot archetype with no entry in the skip map (e.g. coastal)
    runs the full panel — only mapped archetypes ever skip a department."""
    result = select_departments(
        ALL_CATEGORIES, _arch(ARCHETYPE_LA_COASTAL_ZONE, True)
    )
    assert result == ALL_CATEGORIES


def test_result_is_always_subset_of_input():
    """The router never invents a category outside the provided panel."""
    panel = {"building_safety", "fire"}  # a deliberately tiny panel
    result = select_departments(
        panel, _arch(ARCHETYPE_LA_TI_COMMERCIAL, True)
    )
    assert result <= panel


def test_disabled_default_setting_is_false():
    """Dark-launch guarantee: routing is OFF by default so merging changes
    nothing in production."""
    from app.config import settings
    assert settings.department_routing_enabled is False
