"""GIS overlay client + its consumers (site warnings, archetype gate).

All ArcGIS calls are mocked — offline by construction. Under test: layer
scoping by geography, attribute normalization per layer, the error-isolation
contract (one dead layer never poisons the sweep), and the overlay-driven
archetype rejects that previously relied on plan-text cues.
"""
from unittest.mock import MagicMock

import pytest

from app.services import gis_overlays
from app.services.site_resolver import _overlay_warnings
from app.agents.archetype import classify_archetype
from app.agents.workflow import _property_profile_from_overlays
from app.models.schemas import ExtractedPlanData, Jurisdiction


# ---------------------------------------------------------------- scoping


def test_layer_scoping():
    national = {l.key for l in gis_overlays._layers_for("NY", "Buffalo")}
    assert national == {"flood"}

    ca = {l.key for l in gis_overlays._layers_for("CA", "Pasadena")}
    assert ca == {"flood", "fire_hazard", "coastal"}

    la = {l.key for l in gis_overlays._layers_for("CA", "Los Angeles")}
    assert la == {"flood", "fire_hazard", "coastal", "hpoz", "hillside",
                  "methane", "liquefaction"}


# ---------------------------------------------------- query + normalization


def _mock_arcgis(monkeypatch, features_by_url_fragment, broken_fragment=None):
    """Route httpx.get by URL substring to canned ArcGIS feature lists."""
    def fake_get(url, params=None, timeout=None):
        if broken_fragment and broken_fragment in url:
            raise RuntimeError("layer down")
        feats = []
        for fragment, attrs_list in features_by_url_fragment.items():
            if fragment in url:
                feats = [{"attributes": a} for a in attrs_list]
                break
        resp = MagicMock()
        resp.json.return_value = {"features": feats}
        resp.raise_for_status.return_value = None
        return resp
    monkeypatch.setattr(gis_overlays.httpx, "get", fake_get)


LA_VHFHSZ_POINT = {
    "fhsz24_5": [{"FHSZ": 3, "FHSZ_Description": "Very High",
                  "FHSZ_7Class": "LRA Very High", "SRA22_2": "LRA"}],
    "NFHL": [{"FLD_ZONE": "X", "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD",
              "SFHA_TF": "F"}],
    "Coastal_Zone_Polygon": [],
    "City_Planning_Department": [{"NAME": "Angelino Heights", "DIST_TYPE": "HPOZ"}],
    "Special_Areas": [{"H_TYPE": "Hillside Area"}],
    "Methane_Zones": [{"ZONE_": "Methane Buffer Zone"}],
    "Geotechnical": [],
}


def test_resolve_overlays_normalizes_all_layers(monkeypatch):
    _mock_arcgis(monkeypatch, LA_VHFHSZ_POINT)
    r = gis_overlays.resolve_overlays(34.07, -118.25, state_code="CA", city="Los Angeles")

    assert set(r["checked"]) == {"flood", "fire_hazard", "coastal", "hpoz",
                                 "hillside", "methane", "liquefaction"}
    assert r["errors"] == {}
    assert r["fire_hazard"] == {"in_zone": True, "severity": "Very High",
                                "responsibility": "LRA", "label": "LRA Very High"}
    assert r["flood"] == {"zone": "X", "subtype": "AREA OF MINIMAL FLOOD HAZARD",
                          "in_sfha": False}
    assert r["coastal"] == {"in_zone": False}
    assert r["hpoz"] == {"in_zone": True, "name": "Angelino Heights"}
    assert r["hillside"] == {"in_zone": True, "type": "Hillside Area"}
    assert r["methane"] == {"in_zone": True, "kind": "Methane Buffer Zone"}
    assert r["liquefaction"] == {"in_zone": False}


def test_one_dead_layer_does_not_poison_the_sweep(monkeypatch):
    _mock_arcgis(monkeypatch, LA_VHFHSZ_POINT, broken_fragment="NFHL")
    r = gis_overlays.resolve_overlays(34.07, -118.25, state_code="CA", city="Los Angeles")

    assert "flood" in r["errors"]
    assert "flood" not in r            # unknown, NOT a false "no"
    assert r["fire_hazard"]["in_zone"] is True


def test_arcgis_200_error_body_is_an_error(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        resp = MagicMock()
        resp.json.return_value = {"error": {"message": "Invalid layer"}}
        resp.raise_for_status.return_value = None
        return resp
    monkeypatch.setattr(gis_overlays.httpx, "get", fake_get)
    r = gis_overlays.resolve_overlays(40.7, -74.0, state_code="NY", city="New York")
    assert r["errors"] == {"flood": "Invalid layer"}


# ------------------------------------------------- site_resolver warnings


def test_overlay_warnings_scope_reasons():
    overlays = {
        "checked": ["fire_hazard", "coastal", "hpoz", "hillside", "methane", "flood"],
        "errors": {},
        "fire_hazard": {"in_zone": True, "severity": "Very High", "responsibility": "LRA"},
        "coastal": {"in_zone": True},
        "hpoz": {"in_zone": True, "name": "Angelino Heights"},
        "hillside": {"in_zone": False},
        "methane": {"in_zone": True, "kind": "Methane Zone"},
        "flood": {"zone": "AE", "in_sfha": True},
    }
    warnings, reasons = _overlay_warnings(overlays, county="Los Angeles County")

    # LA (not Ventura) Very-High fire is a warning but NOT an out-of-scope reason.
    assert any("Chapter 7A" in w for w in warnings)
    # Coastal is IN scope since the Coastal Act / LCP layers landed — it warns
    # (CDP applies, coastal codes included) but no longer rejects.
    assert reasons == ["HPOZ (Angelino Heights)"]
    assert any("Coastal Zone" in w and "included in this review" in w for w in warnings)
    assert any("methane" in w.lower() for w in warnings)
    assert any("Zone AE" in w for w in warnings)


def test_ventura_fire_zone_is_out_of_scope():
    overlays = {
        "checked": ["fire_hazard"], "errors": {},
        "fire_hazard": {"in_zone": True, "severity": "Very High", "responsibility": "SRA"},
    }
    _, reasons = _overlay_warnings(overlays, county="Ventura County")
    assert reasons == ["Ventura County Very High FHSZ (SRA)"]


# ------------------------------------------- archetype gate via GIS profile


def _profile(overlays, city="Los Angeles", county="Los Angeles County", state="CA"):
    site_context = {"overlays": overlays}
    j = Jurisdiction(city=city, county=county, state_code=state)
    return _property_profile_from_overlays(site_context, j)


def test_no_profile_without_overlay_sweep():
    assert _property_profile_from_overlays(None, Jurisdiction()) is None
    assert _property_profile_from_overlays({"overlays": {}}, Jurisdiction()) is None


def test_gis_hillside_rejects_before_text_cues():
    profile = _profile({
        "checked": ["hillside"], "errors": {},
        "hillside": {"in_zone": True, "type": "Hillside Area"},
    })
    result = classify_archetype(ExtractedPlanData(), "new single family dwelling", profile)
    assert not result.in_pilot_scope
    assert any("Hillside" in o for o in result.excluded_overlays)


def test_gis_hpoz_rejects():
    profile = _profile({
        "checked": ["hpoz"], "errors": {},
        "hpoz": {"in_zone": True, "name": "Angelino Heights"},
    })
    result = classify_archetype(ExtractedPlanData(), "new single family dwelling", profile)
    assert not result.in_pilot_scope
    assert any("HPOZ" in o for o in result.excluded_overlays)


def test_gis_ventura_vhfhsz_rejects():
    profile = _profile(
        {
            "checked": ["fire_hazard"], "errors": {},
            "fire_hazard": {"in_zone": True, "severity": "Very High", "responsibility": "LRA"},
        },
        city="Ojai", county="Ventura County",
    )
    assert profile.wui_zone.in_wui is True
    result = classify_archetype(ExtractedPlanData(), "new single family dwelling", profile)
    assert not result.in_pilot_scope
    assert any("VHFHSZ" in o for o in result.excluded_overlays)


def test_gis_coastal_is_in_pilot_scope():
    """Coastal classifies as the coastal archetype and stays IN pilot scope —
    the Coastal Act + LCP corpus layers made it supportable."""
    profile = _profile({
        "checked": ["coastal"], "errors": {},
        "coastal": {"in_zone": True},
    })
    result = classify_archetype(ExtractedPlanData(), "new single family dwelling", profile)
    assert result.archetype == "la_coastal_zone"
    assert result.in_pilot_scope
    assert result.excluded_overlays == []


def test_gis_all_clear_keeps_sfr_in_scope():
    profile = _profile({
        "checked": ["fire_hazard", "coastal", "hpoz", "hillside"], "errors": {},
        "fire_hazard": {"in_zone": False},
        "coastal": {"in_zone": False},
        "hpoz": {"in_zone": False},
        "hillside": {"in_zone": False},
    })
    result = classify_archetype(
        ExtractedPlanData(occupancy_type="R-3", construction_type="V-B",
                          building_area=2400.0, stories=2),
        "new single family dwelling",
        profile,
    )
    assert result.in_pilot_scope


def test_errored_layer_maps_to_unknown_not_false():
    """A layer in errors carries no verdict — the profile flag must be None,
    so a plan-text cue can still reject."""
    profile = _profile({
        "checked": ["hpoz", "hillside"], "errors": {"hpoz": "layer down"},
        "hillside": {"in_zone": False},
    })
    assert profile.in_hpoz is None
    assert profile.in_hillside is False
