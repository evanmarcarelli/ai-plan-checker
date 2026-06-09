"""Build a structured Checklist JSON from a published correction-list PDF.

Two source layouts are supported via --format:

  lettered  (default) — OC-style single-column lists where every item is an
            "<Letter><n>." marker (e.g. "A3.") under a "A. PLAN REQUIREMENTS"
            header and the code citation is bracketed inline ("... [CRC R106.1.1]").

  numbered  — LADBS-style two-column correction *sheets* where items are bare
            "<n>." markers under "A. GENERAL REQUIREMENTS" headers nested inside
            "PART III: ..." parts, the citation trails the text on its own line
            ("... R314.2"), and lettered sub-items ("a.", "b.") belong to the
            numbered item above them. These sheets are laid out in two physical
            columns, so the text is reconstructed column-by-column before parsing.

Usage:
    python -m app.code_library.checklists.build_from_pdf <pdf> --id oc_2019_crc_r3 \
        --jurisdiction "Orange County, CA" --authority "OC Public Works" \
        --edition "2019 CRC" --occupancy R-3 \
        --title "2019 CRC R-3 Plan Check Correction List" --url "https://..."

    python -m app.code_library.checklists.build_from_pdf <pdf> --format numbered \
        --id ladbs_2020_larc_sfd --jurisdiction "Los Angeles, CA" --authority LADBS \
        --edition "2020 LARC" --occupancy R-3 \
        --title "Single Family Dwelling/Duplex Plan Check Correction Sheets" --url "https://..."

This is an ingestion *tool*, not a universal parser — a new publisher whose
layout matches neither mode will need the regexes adjusted; that's expected.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import List

import fitz  # PyMuPDF

from app.code_library.checklists.schema import Checklist, ChecklistItem, ChecklistSource

# Section discipline → department reviewer (codes match agents/departments.py).
_DEPT_BY_DISCIPLINE = {
    # OC lettered-list disciplines.
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
    # LADBS numbered-sheet sections.
    "permit_application": "building_safety",
    "clearances": "public_works",
    "administration": "building_safety",
    "general_zoning_requirements": "zoning",
    "general_requirements": "building_safety",
    "occupancy_classification": "building_safety",
    "building_height_limitation": "building_safety",
    "fire_resistance_rated_construction": "building_safety",
    "fire_protection": "fire",
    "means_of_egress": "building_safety",
    "interior_environment": "building_safety",
    "building_envelope": "building_safety",
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


def parse_pdf(pdf_path: str, fmt: str = "lettered") -> List[ChecklistItem]:
    doc = fitz.open(pdf_path)
    if fmt == "numbered":
        return _parse_numbered_lines(_columned_lines(doc))
    return _parse_lettered(doc)


# --------------------------------------------------------------------------- #
# Lettered, single-column lists (OC and most CA county lists).
# --------------------------------------------------------------------------- #
def _parse_lettered(doc) -> List[ChecklistItem]:
    lines = []
    for i in range(doc.page_count):
        for ln in doc[i].get_text().splitlines():
            if ln.strip() and not _NOISE.search(ln):
                lines.append(ln)
    text = "\n".join(lines)

    # Locate discipline headers: "A. PLAN REQUIREMENTS"
    headers = list(re.finditer(r"(?m)^([A-Z])\.\s+([A-Z][A-Z /&-]{3,55})\s*$", text))
    items: List[ChecklistItem] = []
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


# --------------------------------------------------------------------------- #
# Numbered, two-column correction sheets (LADBS and similar).
# --------------------------------------------------------------------------- #

# Citations trail the text on their own: "R314.2", "T-R302.1(1)", "12.22C20(l)".
_NUM_CITE = re.compile(
    r"(?:T-\s?)?R\d{3}(?:\.\d+)*(?:\s?\([^)]*\))?"   # building/residential code
    r"|\b\d{2}\.\d{1,2}[A-Za-z0-9.()]+"               # LA zoning/admin code
    r"|AWPA\s*U1"
)
_NUM_PART = re.compile(r"^PART\s+([IVXLC]+)\s*:\s*(.+?)(?:\s*\(.*)?$")
_NUM_SECT = re.compile(r"^([A-Z])\.\s+([A-Z][A-Z][A-Z /&-]{2,55})$")
_NUM_ITEM = re.compile(r"^(\d{1,2})\.\s+(.*)$")
# Cover/supplemental-sheet refs and bleed sentinels that are never correction prose.
_NUM_DROP = re.compile(
    r"PC/STR/Corr|ladbs\.org|^Page\s|^\d+\s+of\s+\d+|ADDITIONAL CORRECTIONS"
    r"|customer-survey|^Plan (Review|Check)|Permit Application Number|^Job Address"
    r"|^P/[A-Z]{1,2}[\s-]|^\*{5,}",
    re.IGNORECASE,
)
# Once a supplemental-sheet checkbox list bleeds into an open item, cut the tail.
_NUM_TAIL = re.compile(r"\bATTACHED:")


def _columned_lines(doc, split: float | None = None) -> List[str]:
    """Reconstruct text in human reading order for two-column sheets.

    PyMuPDF's default extraction interleaves the two physical columns line by
    line, which scrambles every item. We instead split words at the page
    mid-line, read the left column fully top-to-bottom, then the right column,
    and group words into lines by vertical position.
    """
    out: List[str] = []
    for i in range(doc.page_count):
        pg = doc[i]
        mid = split if split is not None else pg.rect.width / 2
        for lo, hi in ((-1e9, mid), (mid, 1e9)):
            words = [w for w in pg.get_text("words") if lo <= (w[0] + w[2]) / 2 < hi]
            words.sort(key=lambda w: (round(w[1] / 3), w[0]))  # row band, then x
            line: List[str] = []
            last_y = None
            for w in words:
                y = w[1]
                if last_y is None or abs(y - last_y) <= 3:
                    line.append(w[4])
                else:
                    out.append(" ".join(line).strip())
                    line = [w[4]]
                last_y = y
            if line:
                out.append(" ".join(line).strip())
    return out


def _is_caps_banner(s: str) -> bool:
    """A multi-word all-caps line — supplemental-sheet banner text, never an item."""
    letters = [c for c in s if c.isalpha()]
    return len(s.split()) >= 2 and bool(letters) and all(c.isupper() for c in letters)


def _extract_citation(text: str) -> str | None:
    m = _NUM_CITE.search(text)
    return re.sub(r"\s+", "", m.group(0)) if m else None


def _parse_numbered_lines(lines: List[str]) -> List[ChecklistItem]:
    """Parse reading-order lines from a numbered two-column correction sheet.

    Kept as a pure list-of-lines function so it is unit-testable without a PDF.
    """
    items: List[ChecklistItem] = []
    seen_ids: dict[str, int] = {}
    started = False                 # ignore the cover page until the first PART
    part = sect_letter = sect_name = sect_code = None
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if not cur:
            return
        text = _NUM_TAIL.split(re.sub(r"\s+", " ", cur["text"]).strip())[0].strip()
        if len(text) >= 16:
            base = f"{cur['part']}.{cur['sect_letter']}.{cur['num']}"
            item_id = base
            if item_id in seen_ids:
                seen_ids[item_id] += 1
                item_id = f"{base}-{seen_ids[base]}"
            else:
                seen_ids[base] = 1
            items.append(ChecklistItem(
                item_id=item_id,
                discipline=cur["sect_name"],
                discipline_code=cur["sect_code"],
                text=text,
                code_citation=_extract_citation(text),
                department_code=_DEPT_BY_DISCIPLINE.get(cur["sect_code"], "building_safety"),
            ))
        cur = None

    for ln in lines:
        pm = _NUM_PART.match(ln)
        if pm:
            started = True
            part = pm.group(1)
            sect_letter = sect_name = sect_code = None
            flush()
            continue
        if not started or not ln or _NUM_DROP.search(ln):
            continue
        sm = _NUM_SECT.match(ln)
        if sm:
            flush()
            sect_letter = sm.group(1)
            sect_name = sm.group(2).strip().title()
            sect_code = _slug(sm.group(2))
            continue
        if _is_caps_banner(ln):
            continue
        im = _NUM_ITEM.match(ln)
        if im and sect_letter:
            flush()
            cur = {
                "part": part, "sect_letter": sect_letter, "sect_name": sect_name,
                "sect_code": sect_code, "num": im.group(1), "text": im.group(2),
            }
            continue
        if cur is not None:                     # continuation / lettered sub-item
            cur["text"] += " " + ln
    flush()
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--format", choices=("lettered", "numbered"), default="lettered",
                    help="source layout (default: lettered, OC-style)")
    ap.add_argument("--id", required=True)
    ap.add_argument("--jurisdiction", required=True)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--edition", required=True)
    ap.add_argument("--occupancy", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--url", required=True)
    a = ap.parse_args()

    items = parse_pdf(a.pdf, fmt=a.format)
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
    cited = sum(1 for i in items if i.code_citation)
    print(f"Wrote {len(items)} items ({cited} code-cited) across "
          f"{len({i.discipline_code for i in items})} disciplines -> {out}")


if __name__ == "__main__":
    main()
