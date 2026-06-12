"""Ventura County Building Code (VCBC) ingester — Ordinance 4655, 2025 ed.

The VCBC is the county's compiled building ordinance: Article 1 adopts the
2025 Title 24 parts (plus the IPMC and ISPSC), Articles 2-13 carry the
county's amendments to each adopted code, and Articles 14-16 are
county-original regulations (mobile homes, post-disaster recovery,
limited-density rural dwellings). It governs the unincorporated county —
the pilot jurisdiction layer "CA:Ventura County".

Source: the county's own publication (vcrma.org Building & Safety) — a
government edict, public domain. Downloaded once by the operator and parsed
locally; pass the PDF path.

PARSING — the body is ICC-shaped *within* each article (CHAPTER → SECTION →
"101.1 Title." subsections, licensed_pdf.py handles it), but the same
section numbers repeat across articles: CBC, CMC, CPC, and ISPSC amendments
all carry a "101.1 Title.", and a flat parse minted six colliding "101.1"
chunks. So we split on the bare "ARTICLE N" body headers first and give
each article its own code_short namespace (VCBC-CBC, VCBC-CPC, ...), which
also attributes every amendment to the code it amends.

Articles that defeat the strict ICC pattern get two fallbacks:
  * a relaxed numbering pattern ("90.4.1.1" CEC / "A4.8" CalGreen styles)
    tried when the strict parse finds nothing, and
  * the article's leading prose captured as one "adoption" chunk when it is
    substantive — Articles 7/9/10 are pure adoption statements (e.g. "CEBC
    Appendices A1-A5 adopted in their entirety") that would otherwise vanish.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.licensed_pdf import (
    _NUMBERED_RE,
    extract_pdf_text,
    parse_code_text,
)
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

VCBC_VERSION = "2025 (Ord. 4655, eff. 2026-01-01)"
VCBC_JURISDICTIONS = ["CA:Ventura County"]
VCBC_OUTPUT = "vcbc_2025_ord4655.jsonl"

# Bare body headers: "ARTICLE 5" alone on a line. The TOC's titled form
# ("ARTICLE 5 – AMENDMENTS TO ...") never matches this, so slicing on bare
# markers naturally excludes the cover/TOC/ordaining preamble.
_ARTICLE_BARE_RE = re.compile(r"^\s*ARTICLE\s+(\d{1,2})\s*$", re.MULTILINE)

# Relaxed subsection headings for non-ICC numbering inside an article:
# "90.4.1.1 Connection to electrical installations." (CEC style, 2 digits)
# "A4.8 All-electric appliances and equipment."      (CalGreen appendix)
# "Article 90.4.1 Powers and duties..."              (CEC with literal prefix)
# Same (number, title) group order parse_code_text expects.
_RELAXED_NUMBERED_RE = re.compile(
    r"^(?:Article\s+)?([A-Z]?\d{1,4}(?:\.\d+){1,4})\s+"
    r"([A-Z][^\n]{0,120}?\.)\s*",
    re.MULTILINE,
)

# Article title → which code the article amends. Titles are normalized
# (spaces/hyphens stripped) before matching because the ordinance's own body
# headers drift from its TOC: "MOBILEHOMES" vs "MOBILE HOMES", "LIMITED
# DENSITY" vs "LIMITED-DENSITY", and the typo "SWIMMIING POOL" (hence the
# "SPACODE" keyword, which survives it). Checked in order; the generic
# "CALIFORNIABUILDINGCODE" goes last because every other Title 24 part's
# name contains those words too. Articles whose title mentions "ADOPTION"
# (Article 1) keep the bare VCBC namespace.
# (normalized keyword, code_short suffix, display name, is_amendment_to_that_code)
_AMENDED_CODE_MAP: List[Tuple[str, str, str, bool]] = [
    ("RESIDENTIALCODE", "CRC", "California Residential Code", True),
    ("ELECTRICALCODE", "CEC", "California Electrical Code", True),
    ("MECHANICALCODE", "CMC", "California Mechanical Code", True),
    ("PLUMBINGCODE", "CPC", "California Plumbing Code", True),
    ("ENERGYCODE", "CENC", "California Energy Code", True),
    ("WILDLAND", "CWUIC", "California Wildland-Urban Interface Code", True),
    ("HISTORICAL", "CHBC", "California Historical Building Code", True),
    ("EXISTINGBUILDING", "CEBC", "California Existing Building Code", True),
    ("GREENBUILDING", "CGBC", "California Green Building Standards Code", True),
    ("PROPERTYMAINTENANCE", "IPMC", "International Property Maintenance Code", True),
    ("SPACODE", "ISPSC", "International Swimming Pool and Spa Code", True),
    ("MOBILEHOME", "MH", "Mobile Homes and Commercial Coaches", False),
    ("POSTDISASTER", "PDR", "Post-Disaster Recovery and Reconstruction", False),
    ("LIMITEDDENSITY", "LD", "Limited-Density Owner-Built Rural Dwellings", False),
    ("CALIFORNIABUILDINGCODE", "CBC", "California Building Code", True),
]

# Header/furniture lines stripped from an article's leading prose before
# deciding whether it is a substantive adoption statement: the ARTICLE line,
# all-caps heading lines, and "- 138 -" page numbers.
_LEAD_NOISE_RES = [
    re.compile(r"^\s*ARTICLE\s+\d{1,2}\s*$", re.MULTILINE),
    re.compile(r"^\s*-\s*\d{1,4}\s*-\s*$", re.MULTILINE),
    re.compile(r"^[^a-z\n]{2,90}$", re.MULTILINE),   # all-caps heading lines
]

# Leading prose shorter than this after noise-stripping is just header echo,
# not a citable adoption statement.
_LEAD_MIN_CHARS = 150


def _article_attribution(title: str) -> Tuple[Optional[str], Optional[str], bool]:
    """(code_short suffix, display name, is_amendment) for an article title."""
    t = re.sub(r"[^A-Z0-9]", "", title.upper())
    if "ADOPTION" in t:
        return None, None, False
    for kw, suffix, name, is_amendment in _AMENDED_CODE_MAP:
        if kw in t:
            return suffix, name, is_amendment
    return None, None, False


def _article_title(text: str, marker_end: int) -> str:
    """Join the contiguous non-blank lines right after a bare ARTICLE line —
    the header block is e.g. "AMENDMENTS TO THE\\nCALIFORNIA ENERGY CODE"
    and always ends at the first blank line."""
    lines: List[str] = []
    for raw in text[marker_end:].splitlines()[:5]:
        line = raw.strip()
        if not line:
            if lines:
                break
            continue
        lines.append(line)
        if sum(len(l) for l in lines) > 200:
            break
    return " ".join(lines)


def _clean_lead(lead: str) -> str:
    """Strip header echo and furniture from an article's leading prose."""
    for rx in _LEAD_NOISE_RES:
        lead = rx.sub("", lead)
    return re.sub(r"\n{3,}", "\n\n", lead).strip()


def parse_vcbc_articles(
    text: str, *, source_url: str = ""
) -> List[Tuple[int, str, List[RawSection]]]:
    """Split the compiled ordinance into per-article section lists.

    Pure function (string → articles) so the splitter is testable without a
    PDF. Returns (article number, article title, sections); every section's
    breadcrumb is prefixed with the article so chunk tags carry which code
    the amendment targets.
    """
    bare = [(m.start(), m.end(), int(m.group(1))) for m in _ARTICLE_BARE_RE.finditer(text)]
    articles: List[Tuple[int, str, List[RawSection]]] = []

    for i, (pos, hdr_end, n) in enumerate(bare):
        end = bare[i + 1][0] if i + 1 < len(bare) else len(text)
        chunk_text = text[pos:end]
        title = _article_title(text, hdr_end)
        crumb = f"VCBC Article {n} {title}".strip()

        sections = parse_code_text(chunk_text, source_url=source_url)
        if not sections:
            sections = parse_code_text(
                chunk_text, source_url=source_url, numbered_re=_RELAXED_NUMBERED_RE
            )

        # Leading prose before the first numbered section: the adoption
        # statement ("...Scope and Administration provisions of the Building
        # Code shall be used, as adopted..."). Keep it when substantive.
        first_num_pos = len(chunk_text)
        for rx in (_NUMBERED_RE, _RELAXED_NUMBERED_RE):
            m = rx.search(chunk_text)
            if m:
                first_num_pos = min(first_num_pos, m.start())
        lead = _clean_lead(chunk_text[:first_num_pos])
        if len(lead) >= _LEAD_MIN_CHARS:
            sections.insert(0, RawSection(
                breadcrumb=[crumb],
                section_number="adoption",
                title=f"Adoption and administration — {title.title()}",
                text=lead,
                source_url=source_url,
            ))

        # Prefix the article crumb; drop repeated numbers (a numbering slip
        # would mint two chunks with the same citation — keep the first).
        seen: set = set()
        deduped: List[RawSection] = []
        for s in sections:
            if s.section_number in seen:
                continue
            seen.add(s.section_number)
            s.breadcrumb = [crumb] + (s.breadcrumb or [])
            deduped.append(s)

        articles.append((n, title, deduped))

    return articles


def ingest_vcbc(pdf_path: str, max_sections: Optional[int] = None) -> int:
    """Parse the compiled VCBC ordinance PDF and write vcbc_2025_ord4655.jsonl.

    Returns chunks written. The ordinance is a county-published regulatory
    document — chunks are stamped license_status='edict'.
    """
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"VCBC PDF not found: {pdf_path}")

    text = extract_pdf_text(str(p))
    articles = parse_vcbc_articles(text, source_url=f"file://{p.resolve()}")
    total = sum(len(secs) for _, _, secs in articles)
    logger.info(
        f"[vcbc] parsed {total} sections across {len(articles)} articles from {p.name}"
    )

    chunks: List[dict] = []
    emitted = 0
    for n, title, sections in articles:
        suffix, code_display, is_amendment = _article_attribution(title)
        if suffix is None:
            short = "VCBC"
            name = "Ventura County Building Code (Ord. 4655)"
        elif is_amendment:
            short = f"VCBC-{suffix}"
            name = f"Ventura County Building Code — {code_display} Amendments"
        else:
            short = f"VCBC-{suffix}"
            name = f"Ventura County Building Code — {code_display}"

        target = IngestTarget(
            code_short=short,
            code_name=name,
            version=VCBC_VERSION,
            jurisdictions=list(VCBC_JURISDICTIONS),
            output_filename=VCBC_OUTPUT,
        )
        for s in sections:
            s.extra_tags = (s.extra_tags or []) + (
                ["ventura", "county", "vcbc"] + ([suffix.lower()] if suffix else [])
            )
        for c in chunk_many(sections, target):
            c["source_tier"] = "official_gov"
            c["license_status"] = "edict"
            chunks.append(c)
            emitted += 1
        logger.info(f"[vcbc] article {n} ({short}): {len(sections)} sections")
        if max_sections and emitted >= max_sections:
            chunks = chunks[:max_sections]
            break

    # A duplicated chunk_id means two articles landed in the same namespace
    # (an attribution miss) — a cited id would then resolve to the wrong
    # text half the time. Fail the build loudly rather than write it.
    seen_ids: set = set()
    dupes = sorted({c["chunk_id"] for c in chunks
                    if c["chunk_id"] in seen_ids or seen_ids.add(c["chunk_id"])})
    if dupes:
        raise ValueError(
            f"[vcbc] duplicate chunk_ids across articles ({dupes[:10]}…) — "
            f"extend _AMENDED_CODE_MAP so every article gets its own namespace"
        )

    write_jsonl(
        IngestTarget(
            code_short="VCBC",
            code_name="Ventura County Building Code (Ord. 4655)",
            version=VCBC_VERSION,
            jurisdictions=list(VCBC_JURISDICTIONS),
            output_filename=VCBC_OUTPUT,
        ),
        chunks,
    )
    return len(chunks)
