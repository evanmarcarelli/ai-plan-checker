"""Site resolver (upload-time address pre-check) + workflow address cross-check.

The Census geocoder is mocked — these tests must run offline and never
depend on the real service. What's actually under test: the geography-layer
parsing (incorporated place vs county), the adoption-stack wiring, the
degrade-don't-raise contract, the TTL cache, and the conservative
mismatch heuristic.
"""
from unittest.mock import MagicMock

import pytest

from app.services import site_resolver
from app.agents.workflow import _address_mismatch_reason


CENSUS_LA_CITY = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "200 N SPRING ST, LOS ANGELES, CA, 90012",
                "coordinates": {"x": -118.2427, "y": 34.0537},
                "geographies": {
                    "States": [{"NAME": "California", "STUSAB": "CA"}],
                    "Counties": [{"NAME": "Los Angeles County"}],
                    "Incorporated Places": [{"NAME": "Los Angeles city"}],
                },
            }
        ]
    }
}

CENSUS_UNINCORPORATED = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "1 EXAMPLE RD, ALTADENA, CA, 91001",
                "coordinates": {"x": -118.13, "y": 34.19},
                "geographies": {
                    "States": [{"NAME": "California", "STUSAB": "CA"}],
                    "Counties": [{"NAME": "Los Angeles County"}],
                    # No "Incorporated Places" → unincorporated county area.
                },
            }
        ]
    }
}

CENSUS_NO_MATCH = {"result": {"addressMatches": []}}


@pytest.fixture(autouse=True)
def _clear_cache():
    site_resolver._cache.clear()
    yield
    site_resolver._cache.clear()


@pytest.fixture(autouse=True)
def _stub_overlays(monkeypatch):
    """Keep the GIS overlay sweep out of these tests (it has its own suite in
    test_gis_overlays.py) — resolve_site must never hit ArcGIS from here."""
    monkeypatch.setattr(site_resolver, "resolve_overlays", lambda *a, **k: {})


def _mock_get(monkeypatch, payload=None, exc=None):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        if exc:
            raise exc
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(site_resolver.httpx, "get", fake_get)
    return calls


# ---------------------------------------------------------------- resolve


def test_resolve_incorporated_city(monkeypatch):
    _mock_get(monkeypatch, CENSUS_LA_CITY)
    ctx = site_resolver.resolve_site("200 N Spring St, Los Angeles, CA")

    assert ctx["geocode_failed"] is False
    j = ctx["jurisdiction"]
    # " city" legal-status suffix stripped so the adoption map matches.
    assert j["city"] == "Los Angeles"
    assert j["county"] == "Los Angeles County"
    assert j["state_code"] == "CA"
    assert ctx["address"]["lat"] == pytest.approx(34.0537)
    # LA city has a local adoption record → full support, no warnings.
    assert ctx["support_level"] == "full"
    assert ctx["adoption"]["matched_id"] == "ca_los_angeles_city"
    assert ctx["warnings"] == []
    # Overlay sweep stubbed out ⇒ scope verdict must be unknown, not "in scope".
    assert ctx["pilot_scope"]["likely_in_scope"] is None


def test_overlays_feed_warnings_and_scope(monkeypatch):
    _mock_get(monkeypatch, CENSUS_LA_CITY)
    monkeypatch.setattr(site_resolver, "resolve_overlays", lambda *a, **k: {
        "checked": ["fire_hazard", "coastal", "hillside"],
        "errors": {},
        "fire_hazard": {"in_zone": True, "severity": "Very High", "responsibility": "LRA"},
        "coastal": {"in_zone": False},
        "hillside": {"in_zone": True, "type": "Hillside Area"},
    })
    ctx = site_resolver.resolve_site("1 Hillside Dr, Los Angeles, CA")

    assert ctx["overlays"]["fire_hazard"]["severity"] == "Very High"
    assert ctx["pilot_scope"]["likely_in_scope"] is False
    assert ctx["pilot_scope"]["reasons"] == ["LA Hillside Ordinance area"]
    assert any("Chapter 7A" in w for w in ctx["warnings"])
    assert any("Hillside Ordinance" in w for w in ctx["warnings"])


def test_resolve_unincorporated_falls_to_county(monkeypatch):
    """No incorporated place ⇒ city stays None and the COUNTY (or state)
    record governs — the distinction the whole pre-check exists for."""
    _mock_get(monkeypatch, CENSUS_UNINCORPORATED)
    ctx = site_resolver.resolve_site("1 Example Rd, Altadena, CA 91001")

    assert ctx["jurisdiction"]["city"] is None
    assert ctx["jurisdiction"]["county"] == "Los Angeles County"
    # Must NOT have matched the city-level LA record.
    assert ctx["adoption"]["level"] in ("county", "state")
    assert ctx["adoption"]["matched_id"] != "ca_los_angeles_city"


def test_unmatched_address_degrades(monkeypatch):
    _mock_get(monkeypatch, CENSUS_NO_MATCH)
    ctx = site_resolver.resolve_site("123 Nowhere Blvd, Los Angeles, CA")

    assert ctx["geocode_failed"] is True
    assert any("couldn't verify" in w.lower() for w in ctx["warnings"])
    # Freetext fallback still finds the LA stack from the raw string.
    assert ctx["adoption"]["matched_id"] == "ca_los_angeles_city"


def test_geocoder_down_never_raises(monkeypatch):
    _mock_get(monkeypatch, exc=RuntimeError("connection refused"))
    ctx = site_resolver.resolve_site("200 N Spring St, Los Angeles, CA")
    assert ctx["geocode_failed"] is True
    assert ctx["address"]["input"] == "200 N Spring St, Los Angeles, CA"


def test_cache_dedupes_geocoder_calls(monkeypatch):
    calls = _mock_get(monkeypatch, CENSUS_LA_CITY)
    a = site_resolver.resolve_site("200 N Spring St, Los Angeles, CA")
    b = site_resolver.resolve_site("  200 n spring st,  los angeles, ca ")  # same key
    assert len(calls) == 1
    assert a == b


# ------------------------------------------------- mismatch heuristic


def test_mismatch_different_street_numbers():
    reason = _address_mismatch_reason(
        "200 N Spring St, Los Angeles, CA", "450 Main St", "Los Angeles", "Los Angeles"
    )
    assert reason and "street numbers" in reason


def test_mismatch_different_city():
    reason = _address_mismatch_reason(
        "200 N Spring St, Los Angeles, CA", None, "Pasadena", "Los Angeles"
    )
    assert reason and "Pasadena" in reason


def test_no_mismatch_when_consistent():
    # Same street number, formatting differences only.
    assert _address_mismatch_reason(
        "200 N Spring St, Los Angeles, CA", "200 NORTH SPRING STREET", "Los Angeles", "Los Angeles"
    ) is None
    # Substring city match ("Los Angeles" vs "City of Los Angeles").
    assert _address_mismatch_reason(
        None, None, "City of Los Angeles", "Los Angeles"
    ) is None
    # Nothing to compare ⇒ never flags.
    assert _address_mismatch_reason(None, None, None, None) is None
