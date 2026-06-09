"""Seed code_table_cells (migration 008) from the hardcoded reference tables.

Moves the abbreviated IBC/IPC matrices out of tables.py and into queryable,
provenance-bearing rows, so the deterministic engine reads code-table limits
from data instead of a hand-transcribed Python dict. Idempotent: upserts on
(table_id, adoption_id, row_key, col_key).

    python -m scripts.ingest.tables_to_postgres --dry-run
    python -m scripts.ingest.tables_to_postgres

After seeding, set CODE_STORE=postgres so the checkers read these rows; until
then they transparently use the same values from tables.py.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

from app.code_library.deterministic import tables as T
from app.code_library.deterministic import table_store as TS
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _cell(value) -> Dict[str, Any]:
    """Split a Cell into (value_num, value_sentinel)."""
    if isinstance(value, str):          # 'UL' | 'NP'
        return {"value_num": None, "value_sentinel": value}
    return {"value_num": value, "value_sentinel": None}


def build_rows() -> List[Dict[str, Any]]:
    """Pure: turn the hardcoded tables into code_table_cells rows. base scope
    (adoption_id=None). Kept side-effect-free so it's unit-testable."""
    rows: List[Dict[str, Any]] = []

    def matrix(table_id, data, unit, section):
        for row_key, cols in data.items():
            for col_key, val in cols.items():
                rows.append({
                    "table_id": table_id, "adoption_id": None,
                    "row_key": row_key, "col_key": col_key, "unit": unit,
                    "source_section": section, **_cell(val),
                })

    matrix(TS.T506_2_ID, T.IBC_T506_2, "sf", "506.2")
    matrix(TS.T504_4_ID, T.IBC_T504_4, "stories", "504.4")

    # min exits by occupant load: row_key = upper bound ('inf' = unbounded)
    for max_load, exits in T.MIN_EXITS_BY_LOAD:
        rows.append({
            "table_id": TS.MIN_EXITS_ID, "adoption_id": None,
            "row_key": "inf" if max_load is None else str(max_load),
            "col_key": "exits", "value_num": exits, "value_sentinel": None,
            "unit": "exits", "source_section": "1006.3.2",
        })

    # fixture ratios: row_key = occupancy, col_key = 'wc'|'lav'
    for occ, d in T.FIXTURE_RATIOS.items():
        for fixture, ratio in d.items():
            rows.append({
                "table_id": TS.FIXTURES_ID, "adoption_id": None,
                "row_key": occ, "col_key": fixture, "value_num": ratio,
                "value_sentinel": None, "unit": "occupants_per_fixture",
                "source_section": "403.1",
            })

    # high-rise scalar threshold
    rows.append({
        "table_id": TS.HIGH_RISE_ID, "adoption_id": None,
        "row_key": "threshold", "col_key": "ft", "value_num": T.HIGH_RISE_FT,
        "value_sentinel": None, "unit": "ft", "source_section": "403",
    })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = build_rows()
    by_table: Dict[str, int] = {}
    for r in rows:
        by_table[r["table_id"]] = by_table.get(r["table_id"], 0) + 1
    logger.info(f"Built {len(rows)} cells: " +
                ", ".join(f"{k}={v}" for k, v in by_table.items()))

    if args.dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    from app.services import db
    client = db.admin()
    # Upsert in one call; conflict target matches the NULLS NOT DISTINCT constraint.
    client.table("code_table_cells").upsert(
        rows, on_conflict="table_id,adoption_id,row_key,col_key"
    ).execute()
    logger.info(f"Upserted {len(rows)} table cells.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
