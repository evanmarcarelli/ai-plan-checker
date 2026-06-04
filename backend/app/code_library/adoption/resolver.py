"""Adoption resolver.

address / jurisdiction  ->  adoption record  ->  layer stack

Loads `adoption_map.yaml` (validated by schema.py), matches the most-specific
record for a jurisdiction, folds in inherited parents, and returns a
ResolvedStack the adapter / workflow / engine consume.

Singleton load mirrors corpus_loader.get_corpus(). The optional address path
uses the free US Census Geocoder (no API key, US-only) and degrades to a pure
name match when offline.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel

from app.code_library.adoption.schema import AdoptionRecord
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAP_PATH = Path(__file__).resolve().parent / "adoption_map.yaml"
CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


class ResolvedStack(BaseModel):
    """The resolved code stack for a jurisdiction."""
    matched_id: str
    level: str
    authority: Optional[str] = None
    effective_edition: Optional[str] = None
    prior_edition: Optional[str] = None
    permit_date_note: Optional[str] = None
    # discipline -> human-readable version string, e.g.
    # "building": "2025 CBC (Title 24 Pt 2, based on 2024 IBC)"
    code_versions: Dict[str, str] = {}
    # discipline -> local amendment label
    amendments: Dict[str, str] = {}
    overlays: List[str] = []
    corpus_layer_keys: List[str] = []
    # access flags so callers know what still needs a license/feed
    buy_license_layers: List[str] = []
    blocked_layers: List[str] = []

    def headline_code_version(self) -> str:
        """Single-string summary for the legacy get_code_version() contract."""
        b = self.code_versions.get("building")
        e = self.code_versions.get("energy")
        if b and e:
            return f"{b} + {e}"
        return b or self.effective_edition or "2021 IBC"


class AdoptionResolver:
    def __init__(self, records: List[AdoptionRecord]):
        self.records = records
        self.by_id = {r.id: r for r in records}

    # ---- loading ----

    @classmethod
    def load(cls, path: Path = MAP_PATH) -> "AdoptionResolver":
        with path.open() as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get("records", [])
        records = [AdoptionRecord(**r) for r in raw]   # validate-on-load
        logger.info(f"[adoption] loaded {len(records)} adoption record(s) from {path.name}")
        return cls(records)

    # ---- resolution ----

    def resolve(
        self,
        state: Optional[str],
        county: Optional[str] = None,
        city: Optional[str] = None,
    ) -> ResolvedStack:
        """Match the most-specific record and fold in inherited parents."""
        best: Optional[AdoptionRecord] = None
        best_score = -1
        for r in self.records:
            s = r.matches(state, county, city)
            if s > best_score:
                best, best_score = r, s

        if best is None:
            # No state match at all — return a minimal baseline stack.
            return ResolvedStack(
                matched_id="baseline",
                level="baseline",
                effective_edition="2021 IBC",
                code_versions={"building": "2021 IBC"},
                corpus_layer_keys=["*"],
            )

        return self._build_stack(best)

    def _chain(self, record: AdoptionRecord) -> List[AdoptionRecord]:
        """Record + its inheritance chain, most-specific first."""
        chain = [record]
        seen = {record.id}
        cur = record
        while cur.inherits and cur.inherits in self.by_id and cur.inherits not in seen:
            cur = self.by_id[cur.inherits]
            chain.append(cur)
            seen.add(cur.id)
        return chain

    def _build_stack(self, record: AdoptionRecord) -> ResolvedStack:
        chain = self._chain(record)               # [city, state] say
        parents_first = list(reversed(chain))     # [state, city]

        # adopts: parent first, child overrides.
        adopts: Dict[str, object] = {}
        for r in parents_first:
            adopts.update(r.adopts)

        code_versions: Dict[str, str] = {}
        for disc, a in adopts.items():
            base = f" based on {a.base_model}" if a.base_model else ""
            part = f", {a.part}" if a.part else ""
            code_versions[disc] = f"{a.edition} {a.code}{part}{base}".strip()

        # amendments: collect local_amendments from the chain, child wins.
        amendments: Dict[str, str] = {}
        for r in reversed(chain):                 # state(none) -> city
            amendments.update(r.local_amendments)

        # overlays: union across the chain.
        overlays: List[str] = []
        for r in chain:
            for o in r.overlays:
                if o not in overlays:
                    overlays.append(o)

        # corpus keys: the most-specific record already encodes the full stack.
        corpus_layer_keys = record.corpus_layer_keys or ["*"]

        # edition cycle + permit-date note from whichever record declares it.
        effective_edition = next((r.edition_cycle for r in chain if r.edition_cycle), None)
        prior_edition = next((r.prior_edition for r in chain if r.prior_edition), None)
        prior_until = next((r.prior_effective_until for r in chain if r.prior_effective_until), None)
        permit_date_note = (
            f"Projects with a complete application on or before {prior_until} "
            f"may still be reviewed under the {prior_edition}."
            if prior_edition and prior_until else None
        )

        # access flags across the chain's sources.
        buy = sorted({s.kind for r in chain for s in r.sources if s.access == "buy_license"})
        blocked = sorted({s.kind for r in chain for s in r.sources if s.access == "cloudflare_blocked"})

        return ResolvedStack(
            matched_id=record.id,
            level=record.level,
            authority=record.authority,
            effective_edition=effective_edition,
            prior_edition=prior_edition,
            permit_date_note=permit_date_note,
            code_versions=code_versions,
            amendments=amendments,
            overlays=overlays,
            corpus_layer_keys=corpus_layer_keys,
            buy_license_layers=buy,
            blocked_layers=blocked,
        )

    # ---- address path (optional, network) ----

    def resolve_address(self, address: str, *, timeout: float = 6.0) -> ResolvedStack:
        """Geocode an address to {state, county, city} via the free US Census
        Geocoder, then resolve. Degrades to a name match on the raw string if
        the geocoder is unreachable."""
        state = county = city = None
        try:
            import httpx
            params = {
                "address": address,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "format": "json",
            }
            r = httpx.get(CENSUS_GEOCODER, params=params, timeout=timeout)
            r.raise_for_status()
            geos = (r.json().get("result", {})
                    .get("addressMatches", [{}])[0]
                    .get("geographies", {}))
            if geos:
                states = geos.get("States") or []
                counties = geos.get("Counties") or []
                places = geos.get("Incorporated Places") or []
                if states:
                    state = states[0].get("STUSAB") or states[0].get("NAME")
                if counties:
                    county = counties[0].get("NAME")  # e.g. "Los Angeles County"
                if places:
                    city = places[0].get("NAME")      # e.g. "Los Angeles city"
        except Exception as e:
            logger.warning(f"[adoption] census geocode failed ({e}); falling back to name match")

        # Fall back to parsing the raw string when geocode gave nothing.
        if not (state or county or city):
            return self._resolve_from_freetext(address)

        # Normalize Census suffixes ("Los Angeles County" -> county already ok;
        # "Los Angeles city" -> strip " city").
        if city and city.lower().endswith(" city"):
            city = city[:-5]
        return self.resolve(state, county, city)

    def _resolve_from_freetext(self, text: str) -> ResolvedStack:
        """Last-resort: match any record whose names appear in the string."""
        t = text.lower()
        # Try most-specific levels first.
        for level in ("city", "county", "state"):
            for r in self.records:
                if r.level != level:
                    continue
                if any(n.lower() in t for n in r.names):
                    return self._build_stack(r)
        return self.resolve(None)


# ---- singleton ----

_lock = threading.RLock()
_resolver: Optional[AdoptionResolver] = None


def get_resolver() -> AdoptionResolver:
    global _resolver
    with _lock:
        if _resolver is None:
            _resolver = AdoptionResolver.load()
        return _resolver


# ---- CLI ----

def _main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print('usage: python -m app.code_library.adoption.resolver "200 N Spring St, Los Angeles, CA"')
        return 2
    query = " ".join(args)
    res = get_resolver()
    # If it looks like an address (has a digit), try the geocode path.
    stack = res.resolve_address(query) if any(c.isdigit() for c in query) else res._resolve_from_freetext(query)

    print(f"\nQuery: {query}")
    print(f"Matched: {stack.matched_id} ({stack.level}) — {stack.authority}")
    print(f"Edition: {stack.effective_edition}")
    if stack.permit_date_note:
        print(f"Permit-date note: {stack.permit_date_note}")
    print("\nCode versions:")
    for disc, v in stack.code_versions.items():
        amd = stack.amendments.get(disc)
        print(f"  {disc:14} {v}" + (f"   + local: {amd}" if amd else ""))
    if stack.overlays:
        print(f"\nOverlays: {', '.join(stack.overlays)}")
    print(f"Corpus layers: {stack.corpus_layer_keys}")
    if stack.buy_license_layers:
        print(f"Buy-license layers: {', '.join(stack.buy_license_layers)}")
    if stack.blocked_layers:
        print(f"Blocked layers: {', '.join(stack.blocked_layers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
