"""ADA 2010 Standards ingester — ada.gov (official, public domain).

The accessibility rules cite ADA sections (402 accessible routes, 603
toilet rooms, 703 signs, Table 208.2 parking ...) but the curated
ada_2010.jsonl seed held only a handful of sections, so most ADA citations
were unverifiable. ada.gov publishes the complete 2010 ADA Standards for
Accessible Design as one HTML page — federal government work, public
domain, no bot challenge. One fetch ingests the whole standard.

Page anatomy (stable): every numbered provision is a paragraph of the form

    <p><strong>404.2.3 Clear Width.</strong> Door openings shall ...</p>

with EXCEPTION/Advisory paragraphs following their parent provision, and
chapter headings as <h2>/<h3> ("Chapter 4: Accessible Routes"). We walk the
document in order, start a new section at each numbered <strong> heading,
and append the in-between paragraphs (exceptions, advisories, list items)
to the open section.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

ADA_2010_URL = "https://www.ada.gov/law-and-regs/design-standards/2010-stds/"
USER_AGENT = "ArchitechturaCodeIngest/1.0 (building-code compliance research)"

# "404.2.3 Clear Width." → number + title. Numbers in the 2010 Standards are
# always 3 digits before the first dot (chapters 1-10 → 101-1010 ranges).
_HEADING_RE = re.compile(r"^(\d{3,4}(?:\.\d+)*)\s+(.+?)\.?$")
_CHAPTER_RE = re.compile(r"Chapter\s+(\d+)\s*[:—–-]?\s*(.*)", re.IGNORECASE)

# Per-section text cap before handing to the chunker (which splits oversize
# anyway); guards against a runaway "section" if the page structure drifts.
_MAX_SECTION_CHARS = 30_000


def parse_ada_html(html: str, *, max_sections: Optional[int] = None) -> List[RawSection]:
    """Parse the 2010-standards page into RawSections."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.body or soup

    sections: List[RawSection] = []
    chapter: Optional[str] = None
    current_num: Optional[str] = None
    current_title: str = ""
    current_parts: List[str] = []

    def flush() -> None:
        nonlocal current_num, current_title, current_parts
        if current_num:
            text = "\n\n".join(p for p in current_parts if p).strip()
            # Heading-only sections (a parent like "603 Toilet and Bathing
            # Rooms" whose first child paragraph follows immediately) still
            # deserve a citable stub — the section exists; its scope is its
            # title plus its children.
            if not text and current_title:
                text = f"{current_title}. (Parent section — see subsections.)"
            if text:
                sections.append(RawSection(
                    breadcrumb=[c for c in ("2010 ADA Standards", chapter) if c],
                    section_number=current_num,
                    title=current_title,
                    text=text[:_MAX_SECTION_CHARS],
                    source_url=ADA_2010_URL,
                    extra_tags=["accessibility"],
                ))
        current_num, current_title, current_parts = None, "", []

    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "ol", "ul", "table"]):
        if max_sections and len(sections) >= max_sections:
            break
        name = el.name
        if name in ("h1", "h2", "h3", "h4"):
            head_txt = el.get_text(" ", strip=True)
            m = _CHAPTER_RE.search(head_txt)
            if m:
                flush()
                chapter = f"Chapter {m.group(1)} {m.group(2)}".strip()
                continue
            # Top-level sections ("603 Toilet and Bathing Rooms") are
            # headings, not <p><strong> paragraphs — without this branch the
            # x00-level sections (402, 603, 703 ...) never become citable.
            hm = _HEADING_RE.match(head_txt)
            if hm:
                flush()
                current_num = hm.group(1)
                current_title = hm.group(2).strip()
                current_parts = []
            continue
        if name == "p":
            strong = el.find("strong")
            head = strong.get_text(" ", strip=True) if strong else ""
            m = _HEADING_RE.match(head) if head else None
            # A new numbered provision starts here — but only when the
            # <strong> leads the paragraph (mid-paragraph bold cross-refs
            # like "see <strong>404</strong>" must not start a section).
            leads = False
            if strong is not None:
                for child in el.contents:
                    if isinstance(child, str):
                        if child.strip():
                            break
                        continue
                    leads = child is strong
                    break
            if m and leads:
                flush()
                current_num = m.group(1)
                current_title = m.group(2).strip()
                body = el.get_text(" ", strip=True)
                body = body[len(head):].strip() if body.startswith(head) else body
                current_parts = [body] if body else []
                continue
            # EXCEPTION / Advisory / continuation paragraph → append.
            if current_num:
                txt = el.get_text(" ", strip=True)
                if txt:
                    current_parts.append(txt)
            continue
        # Lists and tables that belong to the open section.
        if current_num:
            txt = el.get_text(" ", strip=True)
            if txt:
                current_parts.append(txt)
    flush()
    return sections


def ingest_ada_2010(max_sections: Optional[int] = None) -> int:
    """Fetch + ingest the complete 2010 ADA Standards. Returns chunks written."""
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    ) as client:
        resp = client.get(ADA_2010_URL)
        if resp.status_code != 200:
            raise RuntimeError(f"ada.gov returned HTTP {resp.status_code}")
        html = resp.text

    sections = parse_ada_html(html, max_sections=max_sections)
    logger.info(f"[ada-gov] parsed {len(sections)} numbered provisions")

    target = IngestTarget(
        code_short="ADA",
        code_name="2010 ADA Standards for Accessible Design",
        version="2010",
        jurisdictions=["*"],
        output_filename="ada_gov_2010.jsonl",
        # The ADA standard is accessibility, full stop — keyword-classifying
        # each section routed drinking-fountain/urinal clearances to the
        # plumbing reviewer and egress sections to fire.
        force_category="accessibility",
    )
    chunks = []
    for c in chunk_many(sections, target):
        c["source_tier"] = "official_gov"
        c["license_status"] = "edict"   # US government work — public domain
        chunks.append(c)
    write_jsonl(target, chunks)
    return len(chunks)
