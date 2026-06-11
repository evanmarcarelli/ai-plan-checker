"""Malibu LCP Local Implementation Plan ingester.

The LIP is the enforceable half of Malibu's certified Local Coastal Program
(adopted by the Coastal Commission 2002-09-13): height limits, setbacks,
ESHA buffers, bluff/shoreline development standards, grading limits, OWTS
requirements, and the CDP procedures the city applies to every coastal
submittal — which in Malibu means every submittal, since the whole city is
inside the Coastal Zone.

Source: the Coastal Commission's own publication of the certified plan
(https://www.coastal.ca.gov/ventura/malibu-lip-final.pdf) — a government
edict, public domain, no bot challenge. Downloaded once into the operator's
code-pdfs folder and parsed locally; pass pdf_path to reuse a copy.

PARSING — the LIP is NOT ICC-shaped (licensed_pdf.py splits on 4-digit
"1004.1"-style numbers and would find nothing). LIP headings are
"3.6 Residential Development Standards" / "4.6.1 Purpose" at line starts,
with chapters as "CHAPTER 4—ENVIRONMENTALLY SENSITIVE HABITAT AREAS".
The table of contents repeats every heading with dot-leaders, so TOC lines
are filtered by their leader characters before splitting.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import httpx

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.licensed_pdf import extract_pdf_text
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

LIP_URL = "https://www.coastal.ca.gov/ventura/malibu-lip-final.pdf"
DEFAULT_PDF_DIR = Path(__file__).resolve().parents[4] / ".." / "code-pdfs"

# "4.6.1 Purpose" / "3.6 Residential Development Standards" at line start.
# Title must be plain prose — TOC entries carry dot-leaders / page numbers
# and get rejected by the character class.
_LIP_HEADING_RE = re.compile(
    r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s+([A-Z][A-Za-z0-9 ,&/()'’-]{2,90})\s*$",
    re.MULTILINE,
)

# "CHAPTER 4—ENVIRONMENTALLY SENSITIVE..." (separator renders variously as
# em-dash, hyphen, or a stray CP1252 control char depending on extractor).
_LIP_CHAPTER_RE = re.compile(
    r"^\s*CHAPTER\s+(\d{1,2})[^A-Za-z0-9\n]{0,3}([A-Z][^\n]{3,90})\s*$",
    re.MULTILINE,
)

# Per-page running furniture in the Commission's PDF.
_FURNITURE_RES = [
    re.compile(r"^\s*City of Malibu LCP Local Implementation Plan\s*$", re.MULTILINE),
    re.compile(r"^\s*Adopted by the California Coastal Commission on September 13, 2002\s*$",
               re.MULTILINE),
    re.compile(r"^\s*Page\s+\d{1,3}\s*$", re.MULTILINE),
]


def parse_lip_text(text: str, *, source_url: str = LIP_URL,
                   max_sections: Optional[int] = None) -> List[RawSection]:
    """Split LIP text into RawSections (pure function — testable without a PDF)."""
    for rx in _FURNITURE_RES:
        text = rx.sub("", text)

    markers = []  # (pos, kind, number, title)
    for m in _LIP_CHAPTER_RE.finditer(text):
        markers.append((m.start(), "chapter", m.group(1), m.group(2).strip()))
    for m in _LIP_HEADING_RE.finditer(text):
        markers.append((m.start(), "section", m.group(1), m.group(2).strip()))
    markers.sort(key=lambda t: t[0])

    sections: List[RawSection] = []
    chapter_crumb: Optional[str] = None
    for i, (pos, kind, number, title) in enumerate(markers):
        if kind == "chapter":
            chapter_crumb = f"LIP Chapter {number} — {title}"
            continue
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        heading_end = text.index("\n", pos) + 1 if "\n" in text[pos:end] else pos
        body = text[heading_end:end].strip()
        if len(body) < 60:
            # TOC stragglers and bare cross-reference lines — not citable text.
            continue
        sections.append(RawSection(
            breadcrumb=[c for c in ("Malibu LCP Local Implementation Plan", chapter_crumb) if c],
            section_number=number,
            title=title,
            text=body,
            source_url=source_url,
            extra_tags=["coastal", "malibu", "lcp"],
        ))
        if max_sections and len(sections) >= max_sections:
            break
    return sections


def _ensure_pdf(pdf_path: Optional[str]) -> Path:
    if pdf_path:
        p = Path(pdf_path)
        if not p.exists():
            raise FileNotFoundError(f"LIP PDF not found: {pdf_path}")
        return p
    cache_dir = DEFAULT_PDF_DIR.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / "malibu-lip-final.pdf"
    if not p.exists():
        logger.info(f"[malibu-lip] downloading {LIP_URL} ...")
        r = httpx.get(LIP_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
        p.write_bytes(r.content)
        logger.info(f"[malibu-lip] saved {len(r.content):,} bytes to {p}")
    return p


def ingest_malibu_lip(pdf_path: Optional[str] = None,
                      max_sections: Optional[int] = None) -> int:
    """Parse the certified Malibu LIP and write malibu_lcp_lip.jsonl.

    Returns chunks written. The plan is a certified regulatory document
    published by a state agency — chunks are stamped license_status='edict'.
    """
    p = _ensure_pdf(pdf_path)
    text = extract_pdf_text(str(p))
    sections = parse_lip_text(text)
    logger.info(f"[malibu-lip] parsed {len(sections)} sections from {p.name}")
    if max_sections:
        sections = sections[:max_sections]

    target = IngestTarget(
        code_short="MALIBU-LIP",
        code_name="Malibu LCP Local Implementation Plan",
        version="2002 (as certified)",
        jurisdictions=["CA:Malibu"],
        output_filename="malibu_lcp_lip.jsonl",
    )
    chunks = []
    for c in chunk_many(sections, target):
        c["source_tier"] = "official_gov"
        c["license_status"] = "edict"
        chunks.append(c)
    write_jsonl(target, chunks)
    return len(chunks)
