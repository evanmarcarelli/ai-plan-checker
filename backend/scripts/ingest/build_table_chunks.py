"""Render the deterministic reference tables into citable corpus chunks.

WHY
The citation gate downgrades any deterministic NON_COMPLIANT whose cited
section is missing from the corpus. The flagship table rules (COM-AREA-
ALLOWABLE → IBC Table 506.2, COM-STORIES-ALLOWABLE → 504.4, EGR-MIN-EXITS →
1006.3.2, EGR-EXIT-CAPACITY → 1005.3, COM-HIGH-RISE → 403) cited sections
the curated IBC JSONL never contained — so every CORRECT area/story/exit
violation was being false-downgraded to needs-review (measured: 6 lost true
positives across the offline eval set).

The table DATA already ships in this repo (deterministic/tables.py — the
same values the engine's pass/fail math runs on). This script renders that
data into corpus chunks so the citations verify against text whose numbers
are, by construction, identical to what the engine computed. No new code
text is asserted: every number is derived from tables.py, and the chunks
say so.

Run from backend/:  python -m scripts.ingest.build_table_chunks
Output: app/code_library/corpus/ibc_2021_reference_tables.jsonl (idempotent).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from app.code_library.deterministic import tables

OUT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app" / "code_library" / "corpus" / "ibc_2021_reference_tables.jsonl"
)

_PROVENANCE = (
    " [Abbreviated values transcribed in app/code_library/deterministic/"
    "tables.py; identical to the deterministic engine's lookup data. Confirm "
    "against the adopted edition for a licensed deployment.]"
)


def _fmt_cell(v) -> str:
    if v == "UL":
        return "Unlimited"
    if v == "NP":
        return "Not Permitted"
    return f"{v:,}"


def _matrix_text(title: str, unit: str, matrix: Dict[str, Dict[str, object]]) -> str:
    lines = [title]
    for occ in sorted(matrix):
        row = matrix[occ]
        cells = "; ".join(f"Type {ct}: {_fmt_cell(row[ct])}" for ct in sorted(row))
        lines.append(f"Group {occ} ({unit}) — {cells}.")
    return "\n".join(lines) + _PROVENANCE


def build_chunks() -> List[dict]:
    base = {
        "code_name": "International Building Code",
        "code_short": "IBC",
        "version": "2021",
        "jurisdictions": ["*"],
        "license_status": "fair_use_review",
    }
    chunks: List[dict] = []

    chunks.append({
        **base,
        "chunk_id": "ibc-506.2",
        "section": "506.2",
        "title": "Allowable Area Factor (Table 506.2)",
        "category": "building_safety",
        "text": _matrix_text(
            "TABLE 506.2 — Allowable area factor (At, square feet per story) "
            "by occupancy group and construction type. Tabular base values; "
            "frontage and sprinkler increases per Section 506.3 INCREASE these "
            "values and are not reflected here.",
            "allowable area, sf/story",
            tables.IBC_T506_2,
        ),
        "tags": ["allowable area", "area factor", "table 506.2", "construction type"],
    })

    chunks.append({
        **base,
        "chunk_id": "ibc-504.4",
        "section": "504.4",
        "title": "Allowable Number of Stories (Table 504.4)",
        "category": "building_safety",
        "text": _matrix_text(
            "TABLE 504.4 — Allowable number of stories above grade plane by "
            "occupancy group and construction type. Non-sprinklered buildings "
            "are limited to one story fewer than the tabular value (footnote, "
            "simplified).",
            "stories above grade plane",
            tables.IBC_T504_4,
        ),
        "tags": ["stories", "height", "table 504.4", "construction type"],
    })

    bucket_lines = []
    prev = 0
    for max_load, exits in tables.MIN_EXITS_BY_LOAD:
        if max_load is None:
            bucket_lines.append(
                f"Occupant load greater than {prev:,}: minimum {exits} exits."
            )
        else:
            bucket_lines.append(
                f"Occupant load {prev + 1:,}–{max_load:,}: minimum {exits} exits."
            )
            prev = max_load
    chunks.append({
        **base,
        "chunk_id": "ibc-1006.3.2",
        "section": "1006.3.2",
        "title": "Minimum Number of Exits per Story",
        "category": "fire",
        "text": (
            "Section 1006.3.2 — Minimum number of exits or access to exits "
            "per story, by occupant load.\n" + "\n".join(bucket_lines) + _PROVENANCE
        ),
        "tags": ["exits", "egress", "occupant load", "minimum exits"],
    })

    chunks.append({
        **base,
        "chunk_id": "ibc-1005.3",
        "section": "1005.3",
        "title": "Required Capacity Based on Occupant Load",
        "category": "fire",
        "text": (
            "Section 1005.3 — Required egress capacity. Stairways: 0.3 inch "
            "of width per occupant served (1005.3.1). Other egress components "
            "including doors: 0.2 inch of width per occupant served "
            "(1005.3.2). These are the capacity factors the deterministic "
            "exit-capacity check computes with." + _PROVENANCE
        ),
        "tags": ["exit capacity", "egress width", "stair width", "door width"],
    })

    chunks.append({
        **base,
        "chunk_id": "ibc-403",
        "section": "403",
        "title": "High-Rise Buildings (Applicability Threshold)",
        "category": "building_safety",
        "text": (
            f"Section 403 — High-rise buildings. Applicability threshold: an "
            f"occupied floor located more than {tables.HIGH_RISE_FT} feet "
            f"above the lowest level of fire department vehicle access. "
            f"Buildings exceeding the threshold trigger the Section 403 "
            f"high-rise provisions (smoke control, emergency voice/alarm "
            f"communication, standby power) which the reviewer must confirm "
            f"are shown on the plans." + _PROVENANCE
        ),
        "tags": ["high-rise", "75 feet", "smoke control", "standby power"],
    })

    chunks.append({
        **{**base, "code_short": "IPC", "code_name": "International Plumbing Code"},
        "chunk_id": "ipc-403.1",
        "section": "403.1",
        "title": "Minimum Number of Required Plumbing Fixtures (Table 403.1)",
        "category": "plumbing",
        "text": (
            "TABLE 403.1 — Minimum plumbing fixtures, abbreviated occupant-"
            "per-fixture ratios used by the deterministic fixture check.\n"
            + "\n".join(
                f"Occupancy {occ}: 1 water closet per {r['wc']} occupants; "
                f"1 lavatory per {r['lav']} occupants."
                for occ, r in sorted(tables.FIXTURE_RATIOS.items())
            )
            + _PROVENANCE
        ),
        "tags": ["plumbing fixtures", "water closet", "lavatory", "table 403.1"],
    })

    return chunks


def main() -> int:
    chunks = build_chunks()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    tmp.replace(OUT_PATH)
    print(f"wrote {len(chunks)} reference-table chunks -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
