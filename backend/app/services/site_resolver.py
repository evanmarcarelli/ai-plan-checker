"""Resolve a user-entered project address into a site context.

address -> US Census Geocoder (free, keyless, US-only) -> {state, county,
city} + coordinates -> adoption resolver -> the code stack a run will use.

This is the upload-time pre-check layer. The web tier calls it from
POST /site/resolve so the dashboard can show the customer which code stack
applies (and warn about unsupported jurisdictions) BEFORE a credit is spent.
The worker calls it again at pipeline start to attach the same context to the
job — it re-resolves rather than trusting a client-sent blob, because the web
and worker are separate processes and the input is just an address string.

The Census geocoder's geography layers are what make this authoritative:
"Incorporated Places" vs "Counties" is exactly the city-vs-unincorporated
distinction the adoption map keys on (governing authority), which frontend
autocomplete services blur.

Synchronous on purpose (httpx sync client, matching adoption/resolver.py) so
both tiers can share it; async callers wrap it in asyncio.to_thread.

GIS overlay lookups (CAL FIRE FHSZ, FEMA NFHL, LA GeoHub) will extend the
returned context in a later step — the shape leaves room for them.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import httpx

from app.code_library.adoption.resolver import get_resolver
from app.services.gis_overlays import resolve_overlays
from app.utils.logger import get_logger

logger = get_logger(__name__)

CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
GEOCODE_TIMEOUT_SEC = 8.0

# In-process TTL cache. Adoption stacks and geography boundaries change on a
# scale of months; a day-long TTL means the dashboard pre-check, the upload,
# and revision re-runs of the same project cost one geocode total per process.
_CACHE_TTL_SEC = 24 * 3600
_CACHE_MAX = 512
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Census place names carry a legal-status suffix ("Los Angeles city",
# "Ojai city", "Apple Valley town") that the adoption map's names don't.
_PLACE_SUFFIX = re.compile(r"\s+(city|town|village|municipality|borough)$", re.IGNORECASE)


def _cache_key(address: str) -> str:
    return re.sub(r"\s+", " ", address.strip().lower())


def _census_geocode(address: str) -> Optional[Dict[str, Any]]:
    """Geocode via the Census Bureau, returning coordinates plus the
    geography layers (state / county / incorporated place). None when the
    address doesn't match anything."""
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    r = httpx.get(CENSUS_GEOCODER, params=params, timeout=GEOCODE_TIMEOUT_SEC)
    r.raise_for_status()
    matches = r.json().get("result", {}).get("addressMatches") or []
    if not matches:
        return None
    m = matches[0]
    geos = m.get("geographies") or {}
    coords = m.get("coordinates") or {}

    states = geos.get("States") or []
    counties = geos.get("Counties") or []
    places = geos.get("Incorporated Places") or []

    city = places[0].get("NAME") if places else None
    if city:
        city = _PLACE_SUFFIX.sub("", city).strip()

    return {
        "matched": m.get("matchedAddress"),
        "lat": coords.get("y"),
        "lon": coords.get("x"),
        "state": states[0].get("NAME") if states else None,
        "state_code": states[0].get("STUSAB") if states else None,
        "county": counties[0].get("NAME") if counties else None,  # "Los Angeles County"
        "city": city,                                             # None ⇒ unincorporated
    }


def resolve_site(address: str) -> Dict[str, Any]:
    """Address -> geocode -> adoption stack -> site context dict.

    Never raises on a bad/unmatched address: the dict carries
    geocode_failed + warnings so callers (the dashboard card, the worker)
    can degrade to plan-text extraction instead of blocking the upload.
    Network/HTTP errors from the geocoder are also swallowed into
    geocode_failed — the pre-check must not take the upload path down.
    """
    key = _cache_key(address)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_SEC:
            return hit[1]

    geo: Optional[Dict[str, Any]] = None
    try:
        geo = _census_geocode(address)
    except Exception as e:
        logger.warning(f"[site] census geocode failed for {address!r}: {e}")

    resolver = get_resolver()
    warnings = []

    if geo:
        stack = resolver.resolve(geo["state_code"], geo["county"], geo["city"])
    else:
        warnings.append(
            "We couldn't verify this address — the review will read the "
            "project location from the plans instead. Double-check for typos."
        )
        # Last resort: name-match the raw string so an unmistakable
        # "..., Los Angeles, CA" still resolves a stack for the card.
        stack = resolver._resolve_from_freetext(address)

    if stack.level in ("city", "county"):
        support = "full"
    elif stack.level == "state":
        support = "state"
        place = (geo or {}).get("city") or (geo or {}).get("county") or "this jurisdiction"
        warnings.append(
            f"No local adoption record for {place} yet — the "
            f"{(geo or {}).get('state_code') or 'state'} statewide code stack "
            f"will be used and city/county amendments won't be checked."
        )
    else:
        support = "baseline"
        warnings.append(
            "This jurisdiction isn't in our adoption library yet — a generic "
            "2021 IBC baseline applies and local amendments won't be checked."
        )

    # GIS overlays — fire hazard, flood, coastal, and the LA-city layers.
    # Only when geocoding produced a point; per-layer failures are recorded
    # inside the result, a wholesale failure degrades to "no overlay data".
    overlays: Dict[str, Any] = {}
    if geo and geo.get("lat") is not None and geo.get("lon") is not None:
        try:
            overlays = resolve_overlays(
                geo["lat"], geo["lon"],
                state_code=geo.get("state_code"), city=geo.get("city"),
            )
        except Exception as e:
            logger.warning(f"[site] overlay resolve failed for {address!r}: {e}")
            overlays = {}

    overlay_warnings, scope_reasons = _overlay_warnings(overlays, (geo or {}).get("county"))
    warnings.extend(overlay_warnings)

    context: Dict[str, Any] = {
        "address": {
            "input": address.strip(),
            "matched": (geo or {}).get("matched"),
            "lat": (geo or {}).get("lat"),
            "lon": (geo or {}).get("lon"),
        },
        "jurisdiction": {
            "city": (geo or {}).get("city"),
            "county": (geo or {}).get("county"),
            "state": (geo or {}).get("state"),
            "state_code": (geo or {}).get("state_code"),
        },
        "adoption": {
            "matched_id": stack.matched_id,
            "level": stack.level,
            "authority": stack.authority,
            "headline": stack.headline_code_version(),
            "code_versions": stack.code_versions,
            "amendments": stack.amendments,
            "overlays": stack.overlays,
        },
        "overlays": overlays,
        "pilot_scope": {
            # None (unknown) when we had no point to check — only a real
            # overlay sweep may claim "likely in scope".
            "likely_in_scope": (not scope_reasons) if overlays.get("checked") else None,
            "reasons": scope_reasons,
        },
        "support_level": support,
        "warnings": warnings,
        "geocode_failed": geo is None,
        "resolved_at": datetime.utcnow().isoformat(),
    }

    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            # Drop the oldest half rather than tracking LRU order — this cache
            # exists to dedupe bursts (pre-check then upload then re-run), not
            # to be a database.
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: _CACHE_MAX // 2]:
                _cache.pop(k, None)
        _cache[key] = (now, context)

    return context


def _overlay_warnings(overlays: Dict[str, Any], county: Optional[str]) -> tuple:
    """Translate overlay verdicts into customer-facing warnings and
    out-of-pilot-scope reasons.

    Two tiers, mirroring the archetype gate: overlays that kick a submittal
    out of pilot scope (HPOZ, hillside, Ventura VHFHSZ) become scope_reasons;
    overlays that stay in scope but change the review (coastal, methane,
    SFHA flood, liquefaction, non-Ventura fire zones) become plain warnings.
    Errored layers are silent here — unknown is not "no", but it isn't a
    warning either.
    """
    warnings: list = []
    reasons: list = []
    if not overlays:
        return warnings, reasons

    is_ventura = bool(county and "ventura" in county.lower())

    fire = overlays.get("fire_hazard") or {}
    if fire.get("in_zone"):
        sev = fire.get("severity") or "mapped"
        resp = fire.get("responsibility") or "?"
        msg = (
            f"{sev} Fire Hazard Severity Zone ({resp}) — CBC Chapter 7A "
            f"wildfire-resistive construction requirements apply."
        )
        if is_ventura and (sev == "Very High" or resp == "SRA"):
            reasons.append(f"Ventura County {sev} FHSZ ({resp})")
            msg += " This puts the project outside the current AI pilot scope."
        warnings.append(msg)

    coastal = overlays.get("coastal") or {}
    if coastal.get("in_zone"):
        # Coastal is IN scope (since 2026-06: Coastal Act corpus layer +
        # certified-LCP standards) — inform, don't reject.
        warnings.append(
            "Inside the California Coastal Zone — a coastal development permit "
            "applies. Coastal Act (PRC Div. 20) and certified-LCP standards are "
            "included in this review."
        )

    hpoz = overlays.get("hpoz") or {}
    if hpoz.get("in_zone"):
        name = hpoz.get("name")
        reasons.append(f"HPOZ{f' ({name})' if name else ''}")
        warnings.append(
            f"Historic Preservation Overlay Zone{f' — {name}' if name else ''} — "
            f"historic review applies and the project is outside the current AI pilot scope."
        )

    hillside = overlays.get("hillside") or {}
    if hillside.get("in_zone"):
        reasons.append("LA Hillside Ordinance area")
        warnings.append(
            "LA Hillside Ordinance area — hillside development standards apply "
            "and the project is outside the current AI pilot scope."
        )

    methane = overlays.get("methane") or {}
    if methane.get("in_zone"):
        kind = methane.get("kind") or "Methane Zone"
        warnings.append(f"LA {kind} — LADBS methane mitigation requirements apply.")

    flood = overlays.get("flood") or {}
    if flood.get("in_sfha"):
        warnings.append(
            f"FEMA Special Flood Hazard Area (Zone {flood.get('zone') or '?'}) — "
            f"flood-resistant construction and elevation requirements apply."
        )

    liq = overlays.get("liquefaction") or {}
    if liq.get("in_zone"):
        warnings.append(
            "Mapped liquefaction hazard zone — a site-specific geotechnical "
            "report is typically required."
        )

    return warnings, reasons
