"""Load structured correction checklists and pick the one that applies."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from app.code_library.checklists.schema import Checklist
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def load_checklists() -> List[Checklist]:
    """Load every checklist JSON in data/. Cached for the process lifetime."""
    out: List[Checklist] = []
    for path in sorted(_DATA_DIR.glob("*.json")):
        try:
            out.append(Checklist.model_validate_json(path.read_text()))
        except Exception as e:  # one bad file shouldn't sink the rest
            logger.warning(f"[checklists] failed to load {path.name}: {e}")
    logger.info(f"[checklists] loaded {len(out)} checklist(s), "
                f"{sum(len(c.items) for c in out)} items total")
    return out


def _local_specificity(cl: Checklist) -> int:
    """Count of inherently-local items (zoning) — a proxy for how jurisdiction-
    specific a list is. A statewide-code list (e.g. OC, all CRC-cited) scores 0;
    the LADBS sheet (LA Municipal zoning section) scores high. Used to pick the
    *least* local list when no jurisdiction matches the plan."""
    return sum(1 for i in cl.items if i.department_code == "zoning")


def select_checklist(
    occupancy: Optional[str],
    state: Optional[str] = "CA",
    city: Optional[str] = None,
) -> Optional[Checklist]:
    """Pick the best correction list for an (occupancy, jurisdiction).

    1. Filter to lists matching the occupancy (commercial gets None — never
       borrow a residential list).
    2. Prefer a list whose jurisdiction names the plan's city/county (LA plan →
       LADBS, Orange plan → OC) so LA-specific zoning items don't leak elsewhere.
    3. Otherwise, among same-state lists, fall back to the *least* jurisdiction-
       specific one — its items are statewide-code based and safe to apply to any
       plan in that state.
    """
    lists = load_checklists()
    if not lists:
        return None
    occ = (occupancy or "").upper().replace(" ", "")
    matches = [c for c in lists if occ and occ in c.source.occupancy.upper().replace(" ", "")]
    if matches:
        pool = matches
    elif occ.startswith("R"):
        pool = [c for c in lists if c.source.occupancy.upper().startswith("R")]
    else:
        # Commercial / unknown occupancy: no applicable list yet. Return None so
        # the pipeline behaves exactly as before.
        return None
    if not pool:
        return None
    # Exact jurisdiction (city/county) match wins outright.
    if city:
        cl = city.strip().lower()
        jur = [c for c in pool if cl and cl in c.source.jurisdiction.lower()]
        if jur:
            return jur[0]
    # No jurisdiction match → prefer same-state, then the least-local list.
    state_hits = [c for c in pool if state and state.upper() in c.source.jurisdiction.upper()]
    candidates = state_hits or pool
    return min(candidates, key=_local_specificity)
