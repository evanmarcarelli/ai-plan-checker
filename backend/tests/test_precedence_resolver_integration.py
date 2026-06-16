"""Integration tests: precedence policy built from the REAL adoption map.

Pure / offline — exercises the adoption_map.yaml precedence data through the
resolver and build_policy, then runs the resolver on synthetic cross-layer
provisions.
"""
import pytest

from app.code_library.adoption.resolver import get_resolver
from app.code_library.adoption.schema import AmendmentRelationship
from app.code_library.precedence import build_policy, resolve_precedence
from app.models.schemas import CodeRequirement


@pytest.fixture(scope="module")
def resolver():
    return get_resolver()


def test_la_city_policy_has_relations_and_carveouts(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    assert s.amendment_relations.get("building") == "more_restrictive"
    assert s.amendment_relations.get("zoning") == "replaces"
    # The zoning carve-outs are surfaced on the resolved stack.
    assert "adu" in s.preemptions and "sb9" in s.preemptions
    assert "66310" in s.preemptions["adu"]["statute"]


def test_malibu_adopts_la_county_by_reference_structured(resolver):
    s = resolver.resolve("CA", "Los Angeles County", "Malibu")
    # Coastal is an additive overlay; building is more-restrictive-governs.
    assert s.amendment_relations.get("coastal") == "overlay"
    assert s.amendment_relations.get("building") == "more_restrictive"
    # The prose "adopts LA County by reference" is now structured data.
    rec = resolver.by_id["ca_malibu_city"]
    assert rec.adopts_by_reference == ["ca_los_angeles_county"]
    assert rec.amendment_relations["coastal"].relationship == AmendmentRelationship.OVERLAY


def test_cross_jurisdiction_more_restrictive_malibu(resolver):
    s = resolver.resolve("CA", "Los Angeles County", "Malibu")
    policy = build_policy(s, state="CA", site_context=None, plan_data=None)
    base = CodeRequirement(
        code_id="CBC 1011.5", section="1011.5", category="building_safety",
        description="stair width minimum 44 inches", layer_key="*",
    )
    local = CodeRequirement(
        code_id="MMC 1011.5", section="1011.5", category="building_safety",
        description="stair width minimum 48 inches", layer_key="CA:Malibu",
    )
    d = resolve_precedence([base, local], policy)[0]
    assert d.basis == "more_restrictive"
    assert d.governing.code_id == "MMC 1011.5"            # 48" governs
    assert d.governing_layer == "CA:Malibu"
    assert "*" in d.superseded_layers
