"""Licensed-PDF code ingester — the bring-your-own-copy path for model codes.

WHY THIS EXISTS
The web scrapers (amlegal/municode/qcode/ecode360) are Cloudflare-blocked,
and bulk-republishing ICC model-code text scraped from the web carries
copyright exposure the README already documents. The clean path for IBC/IFC/
CBC/CRC and other ICC-derived codes is a copy the operator is LICENSED to
use: a purchased ICC PDF, a state-published edition (e.g. the California
Building Standards Commission publishes the CBC), or a jurisdiction's own
published amendments. This module ingests such a LOCAL PDF into the same
corpus JSONL the BM25 retriever and citation gate already consume.

LEGAL NOTE (operator responsibility): ingesting a file with this tool does
not create a right to republish its text. Chunks are tagged
license_status="licensed" and the fair-use quote cap in citation_retrieval
(MAX_QUOTE_CHARS) still bounds what is surfaced to users. Keep the source
PDF and your license/proof-of-purchase alongside the corpus for provenance.

PARSING
ICC-style codes are strongly conventional:
    CHAPTER 10 MEANS OF EGRESS
    SECTION 1004 OCCUPANT LOAD
    1004.1 Design occupant load. <body...>
    1004.1.1 Cumulative occupant loads. <body...>
    R301.2 Climatic and geographic design criteria. <body...>   (CRC/IRC)
    701A.3 Application. <body...>                               (CBC ch. 7A)
We split on numbered-section headings at line starts, carry the chapter and
SECTION headers as the breadcrumb, and hand the result to the shared
chunker (category classification + oversize splitting + JSONL shape).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

# "CHAPTER 10 MEANS OF EGRESS" / "CHAPTER 7A [SFM] MATERIALS AND..."
_CHAPTER_RE = re.compile(
    r"^\s*CHAPTER\s+(\d{1,2}[A-Z]?)\s*[—–-]?\s*(.{0,100}?)\s*$",
    re.MULTILINE,
)

# "SECTION 1004 OCCUPANT LOAD" / "SECTION 701A SCOPE"
_SECTION_HDR_RE = re.compile(
    r"^\s*SECTION\s+([A-Z]?\d{3,4}[A-Z]?)\s*[—–-]?\s*(.{0,100}?)\s*$",
    re.MULTILINE,
)

# "APPENDIX J GRADING" / "CBC APPENDIX Q EMERGENCY HOUSING" — appendix
# headers are chapter-level breadcrumbs (J101.1 lives under Appendix J, not
# under whatever CHAPTER preceded it). Uppercase-only so mixed-case TOC
# entries ("Appendix J--Amendments ... 52") don't match; the optional
# all-caps prefix covers compiled ordinances that write "CBC APPENDIX J".
_APPENDIX_RE = re.compile(
    r"^\s*(?:[A-Z]{2,6}\s+)?APPENDIX\s+([A-Z]\d?)\s*[—–-]?\s*(.{0,100}?)\s*$",
    re.MULTILINE,
)

# A numbered subsection heading at a line start: a section number, then the
# provision. We deliberately do NOT require a short "Title." here. Some
# provisions run straight into a long sentence whose first period is 200+ chars
# in (e.g. the CEBC 319.7.x list of building characteristics); the old pattern
# required a period within 120 chars and so failed to SEE those headings,
# silently gluing each one into its parent's body. Matching just "number + a
# prose start" fixes that; the optional title is split out by _TITLE_RE below,
# and table-of-contents rows are filtered with _TOC_NOISE_RE.
_NUMBERED_RE = re.compile(
    r"^([A-Z]?\d{3,4}[A-Z]?(?:\.\d+){1,4})\s+(?=[A-Za-z(\[])",
    re.MULTILINE,
)

# The ICC "Number Title. Body" form: a short capitalized title ending in a
# period, then the body sentence. Title chars exclude '.' so a section cross-
# reference ("...per Section 319.4.") or a decimal in the body is never mistaken
# for the title-terminating period. Absent (list-style provisions) → no title.
_TITLE_RE = re.compile(r"([A-Z][^\n.]{2,80}?)\.\s+(?=[A-Z(])")

# A numbered token sitting on a table-of-contents / list-of-tables row: dot
# leaders, or a right-aligned page or chapter-page folio (two+ spaces then a
# number, or "3-19"). Such a row is not a real section start — skipping it is
# what keeps TOC/relocations tables from becoming bogus chunks.
_TOC_NOISE_RE = re.compile(r"\.{4,}|\s{2,}\d{1,4}\s*$|\s\d{1,3}[-–]\d{1,3}\s*$")

# Page-furniture lines to strip before parsing: bare page numbers, edition
# footers, ALL-CAPS running heads that repeat every page.
_FURNITURE_RES = [
    re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE),                      # page numbers
    re.compile(r"^\s*-\s*\d{1,4}\s*-\s*$", re.MULTILINE),              # "- 138 -" style
    re.compile(r"^\s*\d{4}\s+(?:INTERNATIONAL|CALIFORNIA)[^\n]*$",     # ed. footer
               re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Copyright\s*©[^\n]*$", re.MULTILINE | re.IGNORECASE),
    # Public.Resource.Org / ICC licensed-copy watermark furniture (one per
    # page): a bare order/transaction number too long to be a page number, the
    # colored page-tab marker, and the effective-date running header. These are
    # common to ICC PDFs purchased through that channel (CEBC, CBC, CRC, …).
    re.compile(r"^\s*\d{5,}\s*$", re.MULTILINE),                       # bare order #
    re.compile(r"^\s*(?:BUFF|BLUE|TAN)\s*$", re.MULTILINE),            # page-tab color
    re.compile(r"^\s*(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|"
               r"AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{1,2},?\s+\d{4}\s*$",
               re.MULTILINE | re.IGNORECASE),                          # eff.-date header
    # Chapter-page folio on its own line, e.g. "3-20", "3-4" (CEBC/CRC print
    # the running folio as <chapter>-<page>). These leaked into provision
    # bodies as standalone-number debris — the Step-2 audit found dozens.
    re.compile(r"^\s*\d{1,2}[-–]\d{1,3}\s*$", re.MULTILINE),
    # Column-break artifact: a line that is nothing but ">" markers, left by
    # PyMuPDF when it linearizes a multi-column page.
    re.compile(r"^\s*>+\s*$", re.MULTILINE),
]


def _strip_page_furniture(text: str) -> str:
    for rx in _FURNITURE_RES:
        text = rx.sub("", text)
    return text


def extract_pdf_text(pdf_path: str, max_pages: Optional[int] = None) -> str:
    """Whole-document text via PyMuPDF (fast; the codes are born-digital)."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        n = len(doc) if not max_pages else min(len(doc), max_pages)
        return "\n".join(doc[i].get_text("text") for i in range(n))
    finally:
        doc.close()


def parse_code_text(
    text: str,
    *,
    source_url: str = "",
    max_sections: Optional[int] = None,
    numbered_re: Optional[re.Pattern] = None,
) -> List[RawSection]:
    """Split ICC-style code text into RawSections with hierarchy breadcrumbs.

    Pure function (string → sections) so the parser is testable without a
    PDF. Chapter, SECTION, and APPENDIX headers become breadcrumb levels;
    each numbered subsection becomes one RawSection whose text runs to the
    next heading. `numbered_re` swaps the subsection-heading pattern for
    sources whose numbering deviates from the 3-4 digit ICC convention
    (e.g. county compilations writing "90.4.1.1" or "A4.8"); it must keep
    the (number, title) group order.
    """
    text = _strip_page_furniture(text)
    heading_re = numbered_re or _NUMBERED_RE

    # Collect every structural marker position, sorted by offset.
    markers: List[Tuple[int, str, str, str]] = []  # (pos, kind, number, title)
    for m in _CHAPTER_RE.finditer(text):
        markers.append((m.start(), "chapter", m.group(1), m.group(2).strip()))
    for m in _APPENDIX_RE.finditer(text):
        markers.append((m.start(), "appendix", m.group(1), m.group(2).strip()))
    for m in _SECTION_HDR_RE.finditer(text):
        markers.append((m.start(), "section_hdr", m.group(1), m.group(2).strip()))
    for m in heading_re.finditer(text):
        # Drop TOC / list-of-tables rows (see _TOC_NOISE_RE) — they're not
        # section starts.
        nl = text.find("\n", m.start())
        heading_line = text[m.start(): nl if nl != -1 else len(text)]
        if _TOC_NOISE_RE.search(heading_line):
            continue
        # A custom numbered_re may capture a title in group 2 (legacy contract,
        # e.g. vcbc._RELAXED_NUMBERED_RE); the default _NUMBERED_RE captures only
        # the number and the title is derived from the body below.
        try:
            grp_title = (m.group(2) or "").strip().rstrip(".")
        except IndexError:
            grp_title = ""
        markers.append((m.start(), "numbered", m.group(1), grp_title))
    markers.sort(key=lambda t: t[0])

    sections: List[RawSection] = []
    chapter_crumb: Optional[str] = None
    section_crumb: Optional[str] = None

    for i, (pos, kind, number, title) in enumerate(markers):
        if kind == "chapter":
            chapter_crumb = f"Chapter {number}" + (f" {title}" if title else "")
            section_crumb = None
            continue
        if kind == "appendix":
            chapter_crumb = f"Appendix {number}" + (f" {title}" if title else "")
            section_crumb = None
            continue
        if kind == "section_hdr":
            section_crumb = f"Section {number}" + (f" {title}" if title else "")
            # The SECTION header itself often carries scope text up to the
            # first numbered subsection; that text lands in the first
            # numbered child, which is what gets cited in practice.
            continue

        # numbered subsection: body runs to the next marker (any kind).
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        # Skip past the matched heading prefix ("number + spaces"). The default
        # _NUMBERED_RE stops right before the provision text, so `after` still
        # holds any "Title." that needs splitting; a legacy regex that captured
        # the title in group 2 leaves `title` already set and ends past it.
        heading_match = heading_re.match(text, pos)
        after = text[(heading_match.end() if heading_match else pos):end].strip()
        if not title:
            tm = _TITLE_RE.match(after)
            if tm:
                title = tm.group(1).strip()
                after = after[tm.end():].strip()
        body = after
        breadcrumb = [c for c in (chapter_crumb, section_crumb) if c]
        extra = ["exception"] if re.search(r"^\s*Exceptions?\s*:", body, re.MULTILINE) else None
        sections.append(RawSection(
            breadcrumb=breadcrumb,
            section_number=number,
            title=title,
            text=body,
            source_url=source_url,
            extra_tags=extra,
        ))
        if max_sections and len(sections) >= max_sections:
            break

    return sections


def ingest_licensed_pdf(
    pdf_path: str,
    target: IngestTarget,
    *,
    max_pages: Optional[int] = None,
    max_sections: Optional[int] = None,
) -> int:
    """Parse one licensed code PDF and write its chunks to the corpus.

    Returns the number of chunks written. Refuses to overwrite an existing
    corpus file when parsing yields zero sections (same safety contract as
    the scrapers' writer).
    """
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info(f"[licensed-pdf] extracting {p.name} ...")
    text = extract_pdf_text(str(p), max_pages=max_pages)
    sections = parse_code_text(
        text, source_url=f"file://{p.resolve()}", max_sections=max_sections
    )
    logger.info(f"[licensed-pdf] parsed {len(sections)} numbered sections from {p.name}")

    chunks = []
    for c in chunk_many(sections, target):
        # Provenance: the operator holds the license; the chunk says so.
        c["source_tier"] = "licensed"
        c["license_status"] = "licensed"
        chunks.append(c)

    write_jsonl(target, chunks)
    return len(chunks)
