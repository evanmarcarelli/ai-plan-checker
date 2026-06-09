"""Build a structured Checklist JSON from a published correction-list PDF.

Usage:
    python -m app.code_library.checklists.build_from_pdf <pdf> --id oc_2019_crc_r3 \
        --jurisdiction "Orange County, CA" --authority "OC Public Works" \
        --edition "2019 CRC" --occupancy R-3 \
        --title "2019 CRC R-3 Plan Check Correction List" --url "https://..."

Tuned to the lettered-section / "<Letter><n>." item format used by OC, LADBS,
and most California departments. Other publishers may need the regexes adjusted
— that's expected; this is an ingestion *tool*, not a universal parser.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from app.code_library.checklists.schema import Checklist, ChecklistItem, ChecklistSource

# Section discipline → department reviewer (codes match agents/departments.py).
_DEPT_BY_DISCIPLINE = {
    "plan_requirements": "building_safety",
    "general_construction": "building_safety",
    "general_construction_requirements": "building_safety",
    "occupancy": "building_safety",
    "occupancy_requirements": "building_safety",
    "finishes": "building_safety",
    "glazing": "building_safety",
    "skylights": "building_safety",
    "fireplaces": "building_safety",
    "exiting": "building_safety",
    "exiting_requirements": "building_safety",
    "roof": "building_safety",
    "roof_construction_and_covering": "building_safety",
    "noise_control": "building_safety",
    "energy": "energy",
    "mechanical": "mechanical",
    "plumbing": "plumbing",
    "electrical": "electrical",
}

# Page header/footer boilerplate to drop before parsing (OC list; harmless elsewhere).
_NOISE = re.compile(
    r"\d+\s*N\.\s*Ross|P\.O\.\s*Box|ocpublicworks|myOCeServices|\d{3}\.\d{3}\.\d{4}"
    r"|Santa Ana, CA|^\s*Page\s+\d+|^\s*\d+\s*$",
    re.IGNORECASE,
)
_CODE_RE = r"CRC|CBC|CEC|CPC|CMC|CGBC|CESC|CEnC|ASCE|NEC"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_pdf(pdf_path: str) -> list[ChecklistItem]:
    doc = fitz.open(pdf_path)
    lines = []
    for i in range(doc.page_count):
        for ln in doc[i].get_text().splitlines():
            if ln.strip() and not _NOISE.search(ln):
                lines.append(ln)
    text = "\n".join(lines)

    # Locate discipline headers: "A. PLAN REQUIREMENTS"
    headers = list(re.finditer(r"(?m)^([A-Z])\.\s+([A-Z][A-Z /&-]{3,55})\s*$", text))
    items: list[ChecklistItem] = []
    seen_ids: dict[str, int] = {}  # source lists sometimes repeat a number
    for h_idx, h in enumerate(headers):
        disc_name = h.group(2).strip().title()
        disc_code = _slug(h.group(2))
        dept = _DEPT_BY_DISCIPLINE.get(disc_code, "building_safety")
        body_end = headers[h_idx + 1].start() if h_idx + 1 < len(headers) else len(text)
        body = text[h.end():body_end]
        # Items: "<Letter><n>. <text...>" until the next item id or end of section.
        for m in re.finditer(r"(?ms)^([A-Z]\d{1,2})\.\s+(.+?)(?=^[A-Z]\d{1,2}\.|\Z)", body):
            raw = re.sub(r"\s+", " ", m.group(2)).strip()
            cite_m = re.search(rf"\[([^\]]*?(?:{_CODE_RE})[^\]]*?)\]", raw)
            citation = cite_m.group(1).strip() if cite_m else None
            clean = re.sub(rf"\s*\[[^\]]*?(?:{_CODE_RE})[^\]]*?\]\s*", " ", raw).strip()
            if len(clean) < 8:
                continue
            item_id = m.group(1)
            if item_id in seen_ids:
                seen_ids[item_id] += 1
                item_id = f"{item_id}-{seen_ids[item_id]}"
            else:
                seen_ids[item_id] = 1
            items.append(ChecklistItem(
                item_id=item_id,
                discipline=disc_name,
                discipline_code=disc_code,
                text=clean,
                code_citation=citation,
                department_code=dept,
            ))
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--id", required=True)
    ap.add_argument("--jurisdiction", required=True)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--edition", required=True)
    ap.add_argument("--occupancy", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--url", required=True)
    a = ap.parse_args()

    items = parse_pdf(a.pdf)
    checklist = Checklist(
        id=a.id,
        source=ChecklistSource(
            jurisdiction=a.jurisdiction, authority=a.authority, edition=a.edition,
            occupancy=a.occupancy, doc_title=a.title, url=a.url,
            retrieved=date.today().isoformat(),
        ),
        items=items,
    )
    out = Path(__file__).resolve().parent / "data" / f"{a.id}.json"
    out.write_text(checklist.model_dump_json(indent=2))
    print(f"Wrote {len(items)} items across "
          f"{len({i.discipline_code for i in items})} disciplines -> {out}")


if __name__ == "__main__":
    main()
