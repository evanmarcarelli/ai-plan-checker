"""GIS overlay lookups — point-in-polygon queries against public ArcGIS layers.

Given the geocoded coordinates from site_resolver, resolve the property
overlays that gate pilot scope and drive jurisdiction-specific rules:
fire hazard severity (CAL FIRE), FEMA flood zone, the CA Coastal Zone, and
the City-of-LA overlays (HPOZ, Hillside Ordinance, methane, liquefaction).
These are essentially impossible to extract reliably from plan text — the
archetype gate has been falling back to keyword cues — but trivial from a
point against the authoritative boundary layers.

All services are public and keyless. Every layer uses the same ArcGIS REST
query shape (point in, attributes out), so this module is a small registry +
one generic query function. Layers are scoped (national / CA / LA-city) so a
Boise address never pays for an LA HPOZ query.

Failure contract: a layer that errors or times out yields no verdict for that
overlay (absent key) and an entry in `errors` — never an exception. An
overlay lookup must not take down the upload pre-check or the pipeline.

Endpoints verified live 2026-06-11 (known in-zone / out-of-zone points):
- fhsz24_5 is CAL FIRE's current combined disclosure layer (SRA effective
  Apr 2024 + LRA 2025); the older services.gis.ca.gov FHSZ service is the
  superseded 2007/2011 data — don't "fix" the URL back to it.
- Coastal_Zone_Polygon is the Coastal Commission's POLYGON layer; the
  similarly-named Coastal_Zone_Boundary is a line and returns nothing for
  point-intersect queries.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

LAYER_TIMEOUT_SEC = 8.0


@dataclass(frozen=True)
class _Layer:
    key: str
    url: str          # layer endpoint, WITHOUT trailing /query
    out_fields: str
    scope: str        # "national" | "state_ca" | "la_city"


_LAYERS: List[_Layer] = [
    _Layer(
        key="fire_hazard",
        url=("https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
             "fhsz24_5/FeatureServer/0"),
        out_fields="FHSZ,FHSZ_Description,FHSZ_7Class,SRA22_2",
        scope="state_ca",
    ),
    _Layer(
        key="flood",
        url="https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28",
        out_fields="FLD_ZONE,ZONE_SUBTY,SFHA_TF",
        scope="national",
    ),
    _Layer(
        key="coastal",
        url=("https://services9.arcgis.com/wwVnNW92ZHUIr0V0/arcgis/rest/services/"
             "Coastal_Zone_Polygon/FeatureServer/0"),
        out_fields="FID",
        scope="state_ca",
    ),
    _Layer(
        key="hpoz",
        url=("https://maps.lacity.org/lahub/rest/services/"
             "City_Planning_Department/MapServer/10"),
        out_fields="NAME,DIST_TYPE",
        scope="la_city",
    ),
    _Layer(
        key="hillside",
        url="https://maps.lacity.org/lahub/rest/services/Special_Areas/MapServer/6",
        out_fields="H_TYPE",
        scope="la_city",
    ),
    _Layer(
        key="methane",
        url=("https://services1.arcgis.com/tzwalEyxl2rpamKs/arcgis/rest/services/"
             "Methane_Zones_and_Buffers/FeatureServer/0"),
        out_fields="ZONE_",
        scope="la_city",
    ),
    _Layer(
        key="liquefaction",
        url=("https://maps.lacity.org/lahub/rest/services/"
             "Geotechnical_and_Hydrological_Information/MapServer/5"),
        out_fields="*",
        scope="la_city",
    ),
]


def _point_query(layer: _Layer, lat: float, lon: float) -> List[Dict[str, Any]]:
    """Run one ArcGIS point-intersect query, returning feature attribute dicts."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": layer.out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    r = httpx.get(f"{layer.url}/query", params=params, timeout=LAYER_TIMEOUT_SEC)
    r.raise_for_status()
    body = r.json()
    # ArcGIS reports errors in a 200 body, not via HTTP status.
    if "error" in body:
        raise RuntimeError(body["error"].get("message") or "ArcGIS layer error")
    return [f.get("attributes") or {} for f in body.get("features") or []]


# ---------------------------------------------------------- normalization

def _norm_fire(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not feats:
        return {"in_zone": False}
    a = feats[0]
    severity = a.get("FHSZ_Description")          # Moderate | High | Very High
    responsibility = a.get("SRA22_2")             # SRA | LRA
    return {
        "in_zone": True,
        "severity": severity,
        "responsibility": responsibility,
        "label": a.get("FHSZ_7Class"),
    }


def _norm_flood(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not feats:
        return {"zone": None, "in_sfha": False}
    a = feats[0]
    return {
        "zone": a.get("FLD_ZONE"),
        "subtype": a.get("ZONE_SUBTY"),
        "in_sfha": (a.get("SFHA_TF") == "T"),
    }


def _norm_coastal(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"in_zone": bool(feats)}


def _norm_hpoz(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not feats:
        return {"in_zone": False}
    return {"in_zone": True, "name": feats[0].get("NAME")}


def _norm_hillside(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not feats:
        return {"in_zone": False}
    return {"in_zone": True, "type": feats[0].get("H_TYPE")}


def _norm_methane(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not feats:
        return {"in_zone": False}
    # ZONE_ is "Methane Zone" or "Methane Buffer Zone".
    return {"in_zone": True, "kind": feats[0].get("ZONE_")}


def _norm_liquefaction(feats: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"in_zone": bool(feats)}


_NORMALIZERS = {
    "fire_hazard": _norm_fire,
    "flood": _norm_flood,
    "coastal": _norm_coastal,
    "hpoz": _norm_hpoz,
    "hillside": _norm_hillside,
    "methane": _norm_methane,
    "liquefaction": _norm_liquefaction,
}


def _layers_for(state_code: Optional[str], city: Optional[str]) -> List[_Layer]:
    is_ca = (state_code or "").upper() == "CA"
    is_la_city = is_ca and (city or "").strip().lower() == "los angeles"
    out = []
    for layer in _LAYERS:
        if layer.scope == "national":
            out.append(layer)
        elif layer.scope == "state_ca" and is_ca:
            out.append(layer)
        elif layer.scope == "la_city" and is_la_city:
            out.append(layer)
    return out


def resolve_overlays(
    lat: float,
    lon: float,
    state_code: Optional[str] = None,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    """Query every overlay layer applicable to this point, concurrently.

    Returns {overlay_key: normalized verdict, ...} plus:
      checked: layer keys actually queried (so absence of a key can be told
               apart from "not applicable here")
      errors:  {layer_key: message} for layers that failed — those keys carry
               no verdict and downstream MUST treat them as unknown, not "no".
    """
    layers = _layers_for(state_code, city)
    result: Dict[str, Any] = {
        "checked": [l.key for l in layers],
        "errors": {},
    }
    if not layers:
        return result

    # Concurrent: total wall-clock ≈ the slowest single layer (~1s) instead of
    # the sum (~5s with all seven LA layers). Thread-per-layer is fine at this
    # fan-out; callers already run resolve_overlays itself off the event loop.
    with ThreadPoolExecutor(max_workers=len(layers)) as pool:
        futures = {pool.submit(_point_query, l, lat, lon): l for l in layers}
        for fut in as_completed(futures):
            layer = futures[fut]
            try:
                feats = fut.result()
                result[layer.key] = _NORMALIZERS[layer.key](feats)
            except Exception as e:
                logger.warning(f"[gis] {layer.key} lookup failed: {e}")
                result["errors"][layer.key] = str(e)

    return result
