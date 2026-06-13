"""California Energy Code (Title 24, Part 6) ingester — 2025 adopted edition.

WHY ITS OWN MODULE
The Energy Code is published by the California Energy Commission, not ICC, and
is structured nothing like the ICC codes the licensed_pdf parser handles:

    SUBCHAPTER 7   SINGLE-FAMILY RESIDENTIAL BUILDINGS — MANDATORY ...
    SECTION 150.0 – MANDATORY FEATURES AND DEVICES
    (a) ...  1. ...  A. ...  i. ...

Sections are numbered 100.0 … 180.4 (globally unique across the code) and the
heading carries an en/em-dash before an ALL-CAPS title. Per-page running
headers repeat the SECTION and SUBCHAPTER banners, and the front matter is a
dot-leader table of contents — both are stripped here.

SOURCE / LICENSE
We ingest the CEC's own adopted publication "2025 Building Energy Efficiency
Standards … Title 24, Part 6" (CEC-400-2025-010-F), a California government
regulation — public domain (a state edict), so chunks are stamped
source_tier="official_gov" / license_status="edict".

IMPORTANT — do NOT ingest the CEC's "Restructured … For Information Only"
PDF: it renumbers every section and is explicitly *not* the adopted code, so
its citations would not match what a plan checker enforces.

GRANULARITY
Chunks are section-level (e.g. "150.1"); the (a)/(b)/(c) subsection text lives
inside each chunk and oversize sections are split by the shared chunker on
paragraph boundaries. Section-level citations are correct, just coarse;
subsection-level parsing is a possible future refinement.
"""
from __future__ import annotations

import bisect
import re
from pathlib import Path
from typing import List, Optional

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.licensed_pdf import extract_pdf_text
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

CODE_SHORT = "T24-P6"
CODE_NAME = "California Energy Code (Title 24, Part 6)"
VERSION = "2025 (CEC-400-2025-010-F, eff. 2026-01-01)"
JURISDICTIONS = ["CA"]
OUTPUT = "ca_energy_code_2025.jsonl"

# "SECTION 150.1 – PERFORMANCE ..." (case-insensitive: multifamily uses
# "Section 160.0 – General"). Separator is en-dash, em-dash, or hyphen.
_SECTION_RE = re.compile(
    r"(?im)^[ \t]*SECTION[ \t]+(1\d\d\.\d{1,2})[ \t]*[–—-][ \t]*(.+?)[ \t]*$"
)
# "SUBCHAPTER 8 SINGLE-FAMILY ..." banner (stripped from bodies as furniture).
_SUBCHAPTER_RE = re.compile(r"(?im)^[ \t]*SUBCHAPTER[ \t]+\d{1,2}\b.*$")

# Per-page running furniture and TOC residue.
_FURNITURE_RES = [
    re.compile(r"(?m)^.*\.{4,}.*$"),                                   # dot-leader TOC
    re.compile(r"(?m)^\s*Page\s+\d{1,4}\s*$"),                         # "Page 628"
    re.compile(r"(?m)^\s*\d{1,4}\s*$"),                                # bare page numbers
    re.compile(r"(?im)^\s*2025 Building Energy Efficiency Standards.*$"),
    re.compile(r"(?im)^\s*CALIFORNIA CODE OF REGULATIONS.*$"),         # page footer
    re.compile(r"(?im)^\s*TITLE 24[, ].*PART 6.*$"),                   # page footer
]

# Section number → (subchapter no., short subchapter title). Hardcoded because
# the section→subchapter correspondence is fixed in the Energy Code, and the
# nearest-preceding-banner heuristic is systematically off-by-one (the page
# running header precedes the subchapter banner). 150.x straddles three
# subchapters, so it is keyed on the full section, others on the 1xx prefix.
_SUBCHAPTER_BY_SECTION = {
    "150.0": (7, "Single-Family Residential Buildings — Mandatory Features and Devices"),
    "150.1": (8, "Single-Family Residential Buildings — Performance and Prescriptive Compliance Approaches"),
    "150.2": (9, "Single-Family Residential Buildings — Additions and Alterations"),
}
_SUBCHAPTER_BY_PREFIX = {
    "100": (1, "All Occupancies — General"),
    "110": (2, "All Occupancies — Mandatory Requirements for the Manufacture, Construction, and Installation of Systems and Equipment"),
    "120": (3, "Nonresidential, Hotel/Motel Occupancies, and Covered Processes — Mandatory Requirements"),
    "130": (4, "Nonresidential and Hotel/Motel Occupancies — Mandatory Requirements"),
    "140": (5, "Nonresidential and Hotel/Motel Occupancies — Performance and Prescriptive Compliance Approaches"),
    "141": (6, "Nonresidential and Hotel/Motel Occupancies — Additions, Alterations, and Repairs"),
    "160": (10, "Multifamily Buildings — Mandatory Requirements"),
    "170": (11, "Multifamily Buildings — Performance and Prescriptive Compliance Approaches"),
    "180": (12, "Multifamily Buildings — Additions, Alterations, and Repairs"),
}

# Occupancy hint per subchapter group → extra BM25 tag.
_OCCUPANCY_TAG = {
    1: "all-occupancies", 2: "all-occupancies",
    3: "nonresidential", 4: "nonresidential", 5: "nonresidential", 6: "nonresidential",
    7: "single-family", 8: "single-family", 9: "single-family",
    10: "multifamily", 11: "multifamily", 12: "multifamily",
}


def _subchapter_for(section: str):
    if section in _SUBCHAPTER_BY_SECTION:
        return _SUBCHAPTER_BY_SECTION[section]
    return _SUBCHAPTER_BY_PREFIX.get(section.split(".")[0], (None, ""))


def _section_sort_key(num: str):
    a, b = num.split(".")
    return (int(a), int(b))


def _sanitize_title(title: str) -> str:
    """Cut a page footer that PDF extraction glued onto a heading line
    (180.4's title came through as 'WHOLE BUILDINGCALIFORNIA CODE OF ...')."""
    for marker in ("CALIFORNIA CODE OF REGULATIONS", "2025 Building Energy"):
        i = title.find(marker)
        if i > 0:
            title = title[:i]
    return title.strip()


def _clean_body(span: str) -> str:
    """Drop running-header SECTION/SUBCHAPTER banner lines from a section's
    body. Prose cross-references ('Exception to Section 150.0(a)') are NOT at
    heading shape and are preserved."""
    span = _SECTION_RE.sub("", span)
    span = _SUBCHAPTER_RE.sub("", span)
    span = re.sub(r"\n{3,}", "\n\n", span)
    return span.strip()


def parse_energy_code_text(
    text: str, *, source_url: str = "", max_sections: Optional[int] = None
) -> List[RawSection]:
    """Split adopted Energy Code text into section-level RawSections.

    Pure function (string → sections) so it is testable without a PDF.
    """
    # 1) Slice out the regulatory body, excluding the front-matter table of
    #    contents and the back-matter appendices. Both contain section-number-
    #    shaped lines (TOC entries, "Documents Incorporated by Reference", a
    #    bundled Mechanical Code reference TOC) that would otherwise be mistaken
    #    for real sections — so the slice must happen before parsing.
    #    body_start: the first *body* "SECTION 100.0 – SCOPE" header. A body
    #    header line ends right at its title; a TOC entry for the same section
    #    carries trailing dot-leaders and a page number ("… SCOPE …… 1"), so
    #    end-anchoring on SCOPE excludes every TOC entry and lands on the real
    #    start of the regulatory text.
    body_start = 0
    mb = re.search(r"(?im)^[ \t]*SECTION[ \t]+100\.0[ \t]*[–—-][ \t]*SCOPE[ \t]*$", text)
    if mb:
        body_start = mb.start()
    sliced = text[body_start:]

    #    tail: the earliest back-matter heading after the body start. The Part 6
    #    standards (100.0–180.4) are followed by appended reference material —
    #    the "Documents Incorporated by Reference" appendices and a bundled
    #    Mechanical Code duct-systems reference table — each of which contains
    #    section-number-shaped lines. Cut at whichever appears first. (The front
    #    TOC's own copies of these are already excluded by body_start.)
    tail = len(sliced)
    for pat in (
        r"(?im)^\s*APPENDIX\s+1-[A-Z]\b",
        r"(?im)^\s*CALIFORNIA MECHANICAL CODE, CALIFORNIA CODE OF REGULATIONS, ?TITLE 24,? ?PART 4",
    ):
        mm = re.search(pat, sliced)
        if mm:
            tail = min(tail, mm.start())
    body = sliced[:tail]

    # 2) Strip furniture (dot-leader residue, page numbers, footers).
    for rx in _FURNITURE_RES:
        body = rx.sub("", body)

    # 3) Section numbers are globally unique. Within the sliced body, the FIRST
    #    occurrence of each number is its real start; later occurrences are
    #    per-page running headers. Each section runs to the next NEW section's
    #    first occurrence. Lowercase prose cross-references ("Section 150.0(a)")
    #    never match the uppercase heading regex.
    occ = [(m.start(), m.group(1), _sanitize_title(m.group(2)))
           for m in _SECTION_RE.finditer(body)]
    first: dict = {}
    for pos, num, title in occ:
        first.setdefault(num, (pos, title))

    ordered = sorted(first.items(), key=lambda kv: _section_sort_key(kv[0]))

    sections: List[RawSection] = []
    for num, (pos, title) in ordered:
        end = len(body)
        for pos2, num2, _ in occ:
            if pos2 > pos and num2 != num:
                end = pos2
                break
        sub_no, sub_title = _subchapter_for(num)
        breadcrumb = [CODE_NAME]
        if sub_no is not None:
            breadcrumb.append(f"Subchapter {sub_no} — {sub_title}")
        tags = ["energy", "title-24", "part-6"]
        if sub_no in _OCCUPANCY_TAG:
            tags.append(_OCCUPANCY_TAG[sub_no])
        sections.append(RawSection(
            breadcrumb=breadcrumb,
            section_number=num,
            title=title or num,
            text=_clean_body(body[pos:end]),
            source_url=source_url,
            extra_tags=tags,
        ))
        if max_sections and len(sections) >= max_sections:
            break
    return sections


def ingest_energy_code(pdf_path: str, max_sections: Optional[int] = None) -> int:
    """Parse the adopted CEC Energy Code PDF and write ca_energy_code_2025.jsonl.

    Returns chunks written. Stamped source_tier='official_gov' /
    license_status='edict' (a California state regulation, public domain).
    """
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"Energy Code PDF not found: {pdf_path}")

    text = extract_pdf_text(str(p))
    # Guard against the renumbered draft being passed by mistake.
    if "not been formally adopted" in text.lower():
        raise ValueError(
            f"{p.name} looks like the CEC 'Restructured … For Information Only' "
            f"draft (renumbered, not adopted). Ingest the adopted edition "
            f"(CEC-400-2025-010-F) instead — its section numbers match enforcement."
        )

    sections = parse_energy_code_text(text, source_url=f"file://{p.resolve()}",
                                      max_sections=max_sections)
    logger.info(f"[energy-code] parsed {len(sections)} sections from {p.name}")

    target = IngestTarget(
        code_short=CODE_SHORT,
        code_name=CODE_NAME,
        version=VERSION,
        jurisdictions=list(JURISDICTIONS),
        output_filename=OUTPUT,
        force_category="energy",   # whole Part 6 routes to the energy reviewer
    )
    chunks = []
    for c in chunk_many(sections, target):
        c["source_tier"] = "official_gov"
        c["license_status"] = "edict"
        chunks.append(c)

    write_jsonl(target, chunks)
    return len(chunks)
