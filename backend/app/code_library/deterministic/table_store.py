"""Provider for code reference tables (IBC 506.2 / 504.4 / 1006.3.2, IPC 403.1).

Serves the SAME data shapes the deterministic checkers already expect, but
sourced DB-first from code_table_cells (migration 008) with the hardcoded
`tables.py` dicts as the fallback. Same safe-cutover pattern as the corpus
loader: until CODE_STORE=postgres and the cells are seeded, this returns the
exact legacy values, so behavior is unchanged.

Why this matters: it retires the "abbreviated, hand-transcribed Python dict"
liability (tables.py's own comment: "for a licensed production deployment
these come from the corpus"). Once seeded, the limits a compliance result
turns on are queryable data with provenance — and can be scoped per
adoption_id (a jurisdiction that amends an allowable-area cell).
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple, Union

from app.code_library.deterministic import tables as _fallback
from app.utils.logger import get_logger

logger = get_logger(__name__)

Cell = Union[int, str]  # int | "UL" | "NP"

# Canonical table ids (edition-qualified). The hardcoded set is the IBC/IPC
# 2021 abbreviated values, so that's the edition tag.
T506_2_ID = "IBC:2021:T506.2"
T504_4_ID = "IBC:2021:T504.4"
MIN_EXITS_ID = "IBC:2021:1006.3.2"
FIXTURES_ID = "IPC:2021:T403.1"
HIGH_RISE_ID = "IBC:2021:403"

_lock = threading.RLock()
_cache: Dict[Tuple[str, Optional[str]], object] = {}


def clear_cache() -> None:
    """Drop memoized tables (tests / after a re-seed)."""
    with _lock:
        _cache.clear()


def _use_db() -> bool:
    try:
        from app.config import settings
        return getattr(settings, "code_store", "disk").lower() == "postgres"
    except Exception:
        return False


def _strict() -> bool:
    try:
        from app.config import settings
        return _use_db() and bool(getattr(settings, "code_store_strict", False))
    except Exception:
        return False


def _cells(table_id: str, adoption_id: Optional[str]) -> List[dict]:
    """Fetch rows for a table from Postgres; [] if DB off/empty/unavailable.

    When CODE_STORE=postgres but the table has NO rows, warn loudly: the code
    will silently use the hardcoded fallback, whose values can DIVERGE from the
    DB — and these are the allowable-area / story / exit limits a pass/fail
    turns on. Silent divergence here is the scariest table-store failure."""
    if not _use_db():
        return []
    try:
        from app.code_library import store
        rows = store.fetch_table_cells(table_id, adoption_id)
    except Exception as e:
        if _strict():
            raise RuntimeError(f"[table_store] STRICT MODE: fetch {table_id} failed: {e}") from e
        logger.warning(f"[table_store] fetch {table_id} failed; using hardcoded fallback: {e}")
        return []
    if not rows:
        msg = f"CODE_STORE=postgres but {table_id} has no rows in code_table_cells"
        if _strict():
            raise RuntimeError(f"[table_store] STRICT MODE: {msg} — refusing the "
                               f"hardcoded fallback. Seed: python -m scripts.ingest.tables_to_postgres")
        logger.warning(
            "[table_store] %s — using the HARDCODED fallback (values may diverge from "
            "the DB). Seed it: python -m scripts.ingest.tables_to_postgres", msg,
        )
    return rows


def _cell_value(row: dict) -> Cell:
    """Reconstruct a single cell: sentinel ('UL'/'NP') or integer."""
    sentinel = row.get("value_sentinel")
    if sentinel:
        return sentinel
    v = row.get("value_num")
    return int(v) if v is not None else None


def _memo(key: Tuple[str, Optional[str]], builder):
    with _lock:
        if key not in _cache:
            _cache[key] = builder()
        return _cache[key]


# ── matrix tables (occupancy × construction) ─────────────────

def _matrix(table_id: str, adoption_id: Optional[str], fallback: dict) -> Dict[str, Dict[str, Cell]]:
    def build():
        rows = _cells(table_id, adoption_id)
        if not rows:
            return fallback
        out: Dict[str, Dict[str, Cell]] = {}
        for r in rows:
            out.setdefault(r["row_key"], {})[r["col_key"]] = _cell_value(r)
        return out
    return _memo((table_id, adoption_id), build)


def t506_2(adoption_id: Optional[str] = None) -> Dict[str, Dict[str, Cell]]:
    """Table 506.2 — allowable area factor (sf/story) by occupancy × construction."""
    return _matrix(T506_2_ID, adoption_id, _fallback.IBC_T506_2)


def t504_4(adoption_id: Optional[str] = None) -> Dict[str, Dict[str, Cell]]:
    """Table 504.4 — allowable stories by occupancy × construction."""
    return _matrix(T504_4_ID, adoption_id, _fallback.IBC_T504_4)


# ── min exits by occupant load (ordered buckets) ─────────────

def min_exits_by_load(adoption_id: Optional[str] = None) -> List[Tuple[Optional[int], int]]:
    """IBC 1006.3.2 — [(max_load, exits)], ordered ascending, unbounded bucket last."""
    def build():
        rows = _cells(MIN_EXITS_ID, adoption_id)
        if not rows:
            return _fallback.MIN_EXITS_BY_LOAD
        buckets: List[Tuple[Optional[int], int]] = []
        for r in rows:
            rk = (r.get("row_key") or "").strip().lower()
            bound = None if rk in ("inf", "ul", "none", "") else int(rk)
            buckets.append((bound, int(r["value_num"])))
        # ascending by bound, with the unbounded (None) bucket last
        buckets.sort(key=lambda b: (b[0] is None, b[0] if b[0] is not None else 0))
        return buckets
    return _memo((MIN_EXITS_ID, adoption_id), build)


# ── fixture ratios (occupancy → {wc, lav}) ───────────────────

def fixture_ratios(adoption_id: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """IPC Table 403.1 — {occupancy: {'wc': ratio, 'lav': ratio}}."""
    def build():
        rows = _cells(FIXTURES_ID, adoption_id)
        if not rows:
            return _fallback.FIXTURE_RATIOS
        out: Dict[str, Dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["row_key"], {})[r["col_key"]] = int(r["value_num"])
        return out
    return _memo((FIXTURES_ID, adoption_id), build)


# ── high-rise threshold (scalar) ─────────────────────────────

def high_rise_ft(adoption_id: Optional[str] = None) -> int:
    """IBC 403 high-rise height threshold in feet."""
    def build():
        rows = _cells(HIGH_RISE_ID, adoption_id)
        if not rows:
            return _fallback.HIGH_RISE_FT
        return int(rows[0]["value_num"])
    return _memo((HIGH_RISE_ID, adoption_id), build)
