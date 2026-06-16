"""Tests for the code adoption map + resolver.

Pure / offline — the resolver's network path (Census geocoder) is not
exercised here; these assert the map loads, validates, and resolves the LA
stack with correct inheritance.
"""
import pytest

from app.code_library.adoption.resolver import AdoptionResolver, get_resolver


@pytest.fixture(scope="module")
def resolver() -> AdoptionResolver:
    return get_resolver()


def test_map_loads_and_validates(resolver):
    ids = {r.id for r in resolver.records}
    assert {"ca_state", "ca_los_angeles_city", "ca_los_angeles_county"} <= ids


def test_resolve_la_city_full_stack(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    assert s.matched_id == "ca_los_angeles_city"
    assert s.corpus_layer_keys == ["*", "CA", "CA:Los Angeles"]
    # Building edition inherited from the CA state base (2025 CBC / 2024 IBC).
    assert "2025 CBC" in s.code_versions["building"]
    assert "2024 IBC" in s.code_versions["building"]
    # Local amendment comes from the LA city record.
    assert "LABC" in s.amendments["building"]
    assert s.authority and "LADBS" in s.authority


def test_resolve_la_city_electrical_is_2023_nec(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    assert "2025 CEC" in s.code_versions["electrical"]
    assert "2023 NEC" in s.code_versions["electrical"]


def test_resolve_malibu_city(resolver):
    s = resolver.resolve("CA", "Los Angeles County", "Malibu")
    assert s.matched_id == "ca_malibu_city"
    # County layer included (Malibu adopts LA County Title 26 by reference);
    # CA:Coastal included statically (whole city inside the Coastal Zone).
    assert s.corpus_layer_keys == [
        "*", "CA", "CA:Los Angeles County", "CA:Malibu", "CA:Coastal",
    ]
    assert "coastal" in s.overlays and "very_high_fhsz" in s.overlays
    # Editions inherit from the CA state base; amendments are Malibu's own.
    assert "2025 CBC" in s.code_versions["building"]
    assert "MMC" in s.amendments["building"]
    assert "LIP" in s.amendments["coastal"]
    assert s.authority and "Malibu" in s.authority


def test_resolve_coastal_cities_ventura_to_long_beach(resolver):
    """Every coastal jurisdiction from Ventura County down to Long Beach
    resolves to its own record instead of falling through to county/state."""
    expectations = {
        ("Ventura", "Ventura"): "ca_ventura_city",
        ("Ventura", "Oxnard"): "ca_oxnard",
        ("Ventura", "Port Hueneme"): "ca_port_hueneme",
        ("Los Angeles", "Santa Monica"): "ca_santa_monica",
        ("Los Angeles", "El Segundo"): "ca_el_segundo",
        ("Los Angeles", "Manhattan Beach"): "ca_manhattan_beach",
        ("Los Angeles", "Hermosa Beach"): "ca_hermosa_beach",
        ("Los Angeles", "Redondo Beach"): "ca_redondo_beach",
        ("Los Angeles", "Torrance"): "ca_torrance",
        ("Los Angeles", "Palos Verdes Estates"): "ca_palos_verdes_estates",
        ("Los Angeles", "Rancho Palos Verdes"): "ca_rancho_palos_verdes",
        ("Los Angeles", "Long Beach"): "ca_long_beach",
        ("Los Angeles", "Avalon"): "ca_avalon",
    }
    for (county, city), expected_id in expectations.items():
        s = resolver.resolve("CA", county, city)
        assert s.matched_id == expected_id, f"{city} resolved to {s.matched_id}"
        assert "coastal" in s.overlays, f"{city} missing coastal overlay"
        # Editions always inherit the CA state base.
        assert "2025 CBC" in s.code_versions["building"]


def test_resolve_ventura_county_unincorporated(resolver):
    s = resolver.resolve("CA", "Ventura County", None)
    assert s.matched_id == "ca_ventura_county"
    assert s.corpus_layer_keys == ["*", "CA", "CA:Ventura County"]


def test_new_records_do_not_steal_existing_resolutions(resolver):
    """Adding 14 records must not disturb the LA city / county / Malibu matches
    (the name matcher is substring-fuzzy, so collisions are a real risk)."""
    assert resolver.resolve("CA", "Los Angeles", "Los Angeles").matched_id == "ca_los_angeles_city"
    assert resolver.resolve("CA", "Los Angeles", None).matched_id == "ca_los_angeles_county"
    assert resolver.resolve("CA", "Los Angeles County", "Malibu").matched_id == "ca_malibu_city"


def test_resolve_county_when_no_city(resolver):
    s = resolver.resolve("CA", "Los Angeles", None)
    assert s.matched_id == "ca_los_angeles_county"
    assert s.corpus_layer_keys == ["*", "CA", "CA:Los Angeles County"]


def test_unknown_ca_city_falls_back_to_state_base(resolver):
    s = resolver.resolve("CA", None, "Fresno")
    assert s.matched_id == "ca_state"
    assert s.corpus_layer_keys == ["*", "CA"]
    # State base still carries the 2025 edition.
    assert "2025 CBC" in s.code_versions["building"]


def test_non_ca_state_falls_back_to_baseline(resolver):
    s = resolver.resolve("TX", None, "Austin")
    # No TX record yet -> baseline stack, never a wrong CA answer.
    assert s.matched_id in ("baseline", "ca_state") or s.level == "baseline"
    assert s.matched_id != "ca_los_angeles_city"


def test_la_city_overlays_present(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    for o in ("very_high_fhsz", "hillside", "hpoz", "methane_zone"):
        assert o in s.overlays


def test_buy_license_layers_flagged(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    # The model code text is the only paid dependency — it must be flagged.
    assert any("title24" in k or "icc" in k for k in s.buy_license_layers)


def test_permit_date_note_for_edition_transition(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    assert s.permit_date_note and "2022 Title 24" in s.permit_date_note


def test_freetext_resolution(resolver):
    s = resolver._resolve_from_freetext("123 Spring St, Los Angeles, CA 90012")
    assert s.matched_id == "ca_los_angeles_city"


def test_headline_code_version_shape(resolver):
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    hv = s.headline_code_version()
    assert "2025 CBC" in hv and "Energy" in hv


def test_amendment_relations_backcompat(resolver):
    """The new structured precedence field is present AND the legacy prose
    `amendments` label is still a string (no caller breaks)."""
    s = resolver.resolve("CA", "Los Angeles", "Los Angeles")
    assert s.amendment_relations.get("building") == "more_restrictive"
    assert isinstance(s.amendments["building"], str)
    assert "LABC" in s.amendments["building"]
