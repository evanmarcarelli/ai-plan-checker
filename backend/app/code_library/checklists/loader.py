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


def select_checklist(occupancy: Optional[str], state: Optional[str] = "CA") -> Optional[Checklist]:
    """Pick the best correction list for an occupancy (e.g. 'R-3').

    Match on occupancy first, then prefer same-state. Until we ingest more
    jurisdictions, a CA residential list is a reasonable default for any R-3 —
    the items are state-code (CRC) based, not OC-specific.
    """
    lists = load_checklists()
    if not lists:
        return None
    occ = (occupancy or "").upper().replace(" ", "")
    matches = [c for c in lists if occ and occ in c.source.occupancy.upper().replace(" ", "")]
    if matches:
        pool = matches
    elif occ.startswith("R"):
        # Residential without an exact list → any residential list is a safe
        # default (items are state CRC-based, not jurisdiction-specific).
        pool = [c for c in lists if c.source.occupancy.upper().startswith("R")]
    else:
        # Commercial / unknown occupancy: no applicable list yet. Return None so
        # the pipeline behaves exactly as before — never apply residential
        # corrections to a commercial plan.
        return None
    if not pool:
        return None
    state_hits = [c for c in pool if state and state.upper() in c.source.jurisdiction.upper()]
    return (state_hits or pool)[0]
