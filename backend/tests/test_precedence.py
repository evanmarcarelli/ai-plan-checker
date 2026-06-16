"""Unit tests for the legal-precedence resolver.

Pure / offline — operates on hand-built CodeRequirement objects and an explicit
PrecedencePolicy, isolating the "which law governs" algorithm from the corpus,
the adoption map, and the LLM.
"""
from app.code_library.precedence import (
    PrecedencePolicy,
    resolve_precedence,
)
from app.models.schemas import CodeRequirement


def _req(code_id, layer_key, *, category="building_safety", section="1011.5",
         description="", full_text="", min_value=None, max_value=None):
    return CodeRequirement(
        code_id=code_id, code_name="X", section=section, description=description,
        category=category, full_text=full_text, layer_key=layer_key,
        min_value=min_value, max_value=max_value,
    )


def _policy(layer_order, relations=None, active=None, preemptions=None):
    return PrecedencePolicy(
        layer_order=layer_order,
        relations=relations or {},
        preemptions=preemptions or {},
        active_carveouts=set(active or []),
    )


# ── (a) standards: more-restrictive governs ───────────────────────────────

def test_more_restrictive_minimum_picks_larger():
    base = _req("IBC 1011.5", "*", section="1011.5",
                description="egress stair width minimum 44 inches")
    local = _req("LABC 91.1011.5", "CA:Los Angeles", section="91.1011.5",
                 description="egress stair width minimum 48 inches")
    pol = _policy(["CA:Los Angeles", "CA", "*"], relations={"building": "more_restrictive"})
    decisions = resolve_precedence([base, local], pol)
    assert len(decisions) == 1
    d = decisions[0]
    assert d.basis == "more_restrictive"
    assert d.governing.code_id == "LABC 91.1011.5"        # 48" (larger minimum) governs
    assert d.governing_layer == "CA:Los Angeles"
    assert d.superseded_layers == ["*"]
    assert d.needs_review is False


def test_more_restrictive_maximum_picks_smaller():
    base = _req("IBC 506.2", "*", section="506.2",
                description="maximum allowable area 9,000 square feet")
    local = _req("LABC 91.506.2", "CA:Los Angeles", section="91.506.2",
                 description="maximum allowable area 6,000 square feet")
    pol = _policy(["CA:Los Angeles", "CA", "*"], relations={"building": "more_restrictive"})
    d = resolve_precedence([base, local], pol)[0]
    assert d.basis == "more_restrictive"
    assert d.governing.code_id == "LABC 91.506.2"         # 6,000 (smaller maximum) governs


# ── (c) overlays stack ────────────────────────────────────────────────────

def test_overlay_layer_stacks_keeps_all():
    base = _req("CBC 1234", "*", section="1234", description="base requirement")
    coastal = _req("LIP 1234", "CA:Coastal", section="1234", description="coastal add-on")
    pol = _policy(["CA:Coastal", "CA", "*"])
    d = resolve_precedence([base, coastal], pol)[0]
    assert d.basis == "overlay_stacks"
    assert d.superseded == [] and d.superseded_layers == []


# ── (b) zoning: local governs unless preempted ────────────────────────────

def test_zoning_local_governs_without_carveout():
    base = _req("CA 12.21", "CA", section="12.21", category="zoning",
                description="state zoning baseline")
    local = _req("LAMC 12.21", "CA:Los Angeles", section="12.21", category="zoning",
                 description="local setback rule")
    pol = _policy(["CA:Los Angeles", "CA", "*"], relations={"zoning": "replaces"})
    d = resolve_precedence([base, local], pol)[0]
    assert d.basis == "local_governs"
    assert d.governing.code_id == "LAMC 12.21"
    assert "CA" in d.superseded_layers


def test_zoning_preempted_by_adu():
    base = _req("Gov 66310", "CA", section="12.21", category="zoning",
                description="state ADU standard")
    local = _req("LAMC 12.21", "CA:Los Angeles", section="12.21", category="zoning",
                 description="local zoning standard")
    pol = _policy(
        ["CA:Los Angeles", "CA", "*"], relations={"zoning": "replaces"},
        active=["adu"],
        preemptions={"adu": {"topic": "zoning",
                             "statute": "Gov. Code 66310 et seq.",
                             "summary": "ADU law preempts local zoning."}},
    )
    d = resolve_precedence([base, local], pol)[0]
    assert d.basis == "state_preempts_local"
    assert d.governing.code_id == "Gov 66310"             # state governs over local
    assert d.governing_layer == "CA"
    assert "66310" in d.rationale


# ── (d) accessibility: stricter of ADA vs CBC 11B, both retained ──────────

def test_accessibility_ada_vs_11b_stricter():
    ada = _req("ADA 404.2.3", "*", section="404.2.3", category="accessibility",
               description="door clear width minimum 32 inches")
    cbc = _req("CBC 11B-404", "CA", section="404.2.3", category="accessibility",
               description="door clear width minimum 34 inches")
    pol = _policy(["CA", "*"])
    d = resolve_precedence([ada, cbc], pol)[0]
    assert d.basis == "ada_independent"
    assert d.governing.code_id == "CBC 11B-404"           # 34" (larger minimum) governs
    assert d.superseded == []                             # both retained for accessibility


# ── safety: ambiguous conflicts flag needs_review, never auto-pick ────────

def test_non_numeric_conflict_flags_needs_review():
    base = _req("CBC 1003", "*", section="1003",
                description="Provide an accessible means of egress per the adopted code.")
    local = _req("LABC 91.1003", "CA:Los Angeles", section="91.1003",
                 description="Provide an accessible means of egress per local amendment.")
    pol = _policy(["CA:Los Angeles", "CA", "*"], relations={"building": "more_restrictive"})
    d = resolve_precedence([base, local], pol)[0]
    assert d.needs_review is True
    assert d.basis == "more_restrictive"
    # Both provisions are still present for a human to adjudicate.
    assert len(d.members) == 2


def test_single_layer_is_trivial():
    only = _req("CBC 1011", "CA", section="1011", description="some rule")
    d = resolve_precedence([only], _policy(["CA", "*"]))[0]
    assert d.basis == "single_layer"
    assert d.superseded == []


def test_la_section_prefix_merges_topic():
    """Base '1011.5' and LA '91.1011.5' must collapse to ONE topic so the local
    amendment is compared against the base, not treated as unrelated."""
    base = _req("IBC 1011.5", "*", section="1011.5", description="base stair")
    la = _req("LABC 91.1011.5", "CA:Los Angeles", section="91.1011.5", description="LA stair")
    pol = _policy(["CA:Los Angeles", "CA", "*"], relations={"building": "more_restrictive"})
    decisions = resolve_precedence([base, la], pol)
    assert len(decisions) == 1
    assert len(decisions[0].members) == 2


# ── reviewer-facing governing-law block ───────────────────────────────────

def test_governing_law_block_renders_and_skips_single_layer():
    """The block the LLM reviewers see: a line for real precedence decisions,
    nothing for trivial single-layer topics (so prompt caching isn't churned)."""
    from app.agents.departments import DepartmentReviewer
    from app.code_library.precedence import GoverningDecision

    req = _req("LABC 91.1011.5", "CA:Los Angeles", section="91.1011.5")
    decided = GoverningDecision(
        topic="building_safety:1011.5", governing=req,
        governing_layer="CA:Los Angeles", basis="more_restrictive",
        rationale="More-restrictive governs.", superseded_layers=["*"],
    )
    block = DepartmentReviewer._governing_law_block([req], {req.code_id: decided})
    assert "GOVERNING LAW" in block and "CA:Los Angeles" in block and "more_restrictive" in block

    trivial = GoverningDecision(
        topic="building_safety:1011.5", governing=req,
        governing_layer="*", basis="single_layer", rationale="only one",
    )
    assert DepartmentReviewer._governing_law_block([req], {req.code_id: trivial}) == ""
    assert DepartmentReviewer._governing_law_block([req], None) == ""
