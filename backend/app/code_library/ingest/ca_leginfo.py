"""California statute ingester — leginfo.legislature.ca.gov (official, open).

The deterministic rules and department reviewers cite California STATUTES,
not just building-code sections: Gov. Code §51182 (defensible space duties
in a VHFSZ — cited by FIRE-WUI-7A), Pub. Resources Code §4291 (the parallel
defensible-space statute the Environmental reviewer leans on), and Gov. Code
§65852.2/§65852.22 (the state ADU/JADU law behind the Planning & Zoning
ADU checks). None of that text was in the corpus, so the citation gate
treated those citations as unverifiable.

leginfo.legislature.ca.gov is the Legislature's own publication of the
codes: state-published law (an edict of government — public domain), served
as plain HTML with no bot challenge. This ingester fetches a curated list of
sections (one page per section, 1 req/s, self-identifying UA) and writes
them through the shared chunker.

The list is deliberately curated rather than a whole-code crawl: statutes
run to tens of thousands of sections, and the corpus only needs the ones the
pipeline actually cites. Add to TARGET_SECTIONS as new rules land.
"""
from __future__ import annotations

import re
import time
from typing import Dict, Iterable, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = (
    "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
    "?lawCode={law_code}&sectionNum={section}"
)
DEFAULT_DELAY_SEC = 1.0
USER_AGENT = (
    "ArchitechturaCodeIngest/1.0 (building-code compliance research; "
    "polite: 1 req/s)"
)

LAW_NAMES: Dict[str, str] = {
    "GOV": "California Government Code",
    "PRC": "California Public Resources Code",
    "HSC": "California Health and Safety Code",
}

# (law_code, section, breadcrumb hint, extra tags)
# Curated to the sections the rules/departments actually cite.
TARGET_SECTIONS: List[Tuple[str, str, str, List[str]]] = [
    # ── Very High Fire Hazard Severity Zones (Gov. Code Ch. 6.8) ──
    ("GOV", "51175", "VHFSZ — legislative findings", ["wui", "fire hazard"]),
    ("GOV", "51177", "VHFSZ — definitions", ["wui", "defensible space"]),
    ("GOV", "51178", "VHFSZ — State Fire Marshal designation", ["wui", "fhsz"]),
    ("GOV", "51179", "VHFSZ — local agency designation", ["wui", "fhsz"]),
    ("GOV", "51182", "VHFSZ — defensible space duties", ["wui", "defensible space", "100 feet"]),
    ("GOV", "51189", "VHFSZ — building standards", ["wui", "ignition-resistant"]),
    # ── Defensible space (parallel statute, SRA) ──
    ("PRC", "4291", "Defensible space around structures", ["defensible space", "100 feet", "wui"]),
    # ── State ADU law (Planning & Zoning) ──
    # Recodified from Gov. Code §65852.2/§65852.22 to §§66310-66342 (2025);
    # the old section numbers return an empty display page.
    ("GOV", "66310", "Accessory dwelling units — definitions", ["adu", "accessory dwelling"]),
    ("GOV", "66314", "Accessory dwelling units — local ordinance standards", ["adu", "accessory dwelling", "setback"]),
    ("GOV", "66333", "Junior accessory dwelling units", ["jadu", "accessory dwelling"]),
]


def parse_section_html(html: str, section: str) -> Optional[str]:
    """Extract one statute section's text from a leginfo display page.

    Page anatomy (stable for years): the section body sits in a <div> as
    `<h6><b>51182.</b></h6>` followed by sibling <p> paragraphs. We find the
    matching <h6> and join every <p> under the same container.
    """
    soup = BeautifulSoup(html, "lxml")
    want = section.rstrip(".") + "."
    for h6 in soup.find_all("h6"):
        label = h6.get_text(" ", strip=True)
        if not label.startswith(want):
            continue
        container = h6.parent
        # climb out of the <font>/<b> wrappers until a div that has <p> kids
        for _ in range(3):
            if container is None:
                break
            paras = container.find_all("p")
            if paras:
                text = "\n\n".join(
                    p.get_text(" ", strip=True) for p in paras
                    if p.get_text(strip=True)
                )
                return text.strip() or None
            container = container.parent
    return None


def fetch_sections(
    targets: Iterable[Tuple[str, str, str, List[str]]] = TARGET_SECTIONS,
    *,
    client: Optional[httpx.Client] = None,
    delay_sec: float = DEFAULT_DELAY_SEC,
) -> List[Tuple[str, RawSection]]:
    """Fetch every target statute section. Returns (law_code, RawSection)
    pairs; sections that fail to fetch/parse are logged and skipped."""
    own_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30,
        follow_redirects=True,
    )
    out: List[Tuple[str, RawSection]] = []
    try:
        for law_code, section, hint, tags in targets:
            url = BASE_URL.format(law_code=law_code, section=section)
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    logger.error(f"[ca-leginfo] {law_code} {section}: HTTP {resp.status_code}")
                    continue
                text = parse_section_html(resp.text, section)
                if not text:
                    logger.error(f"[ca-leginfo] {law_code} {section}: body not found in page")
                    continue
                out.append((law_code, RawSection(
                    breadcrumb=[LAW_NAMES.get(law_code, law_code), hint],
                    section_number=section,
                    title=hint,
                    text=text,
                    source_url=url,
                    extra_tags=tags,
                )))
                logger.info(f"[ca-leginfo] fetched {law_code} {section} ({len(text)} chars)")
            except httpx.HTTPError as e:
                logger.error(f"[ca-leginfo] {law_code} {section}: {e}")
            time.sleep(delay_sec)
    finally:
        if own_client:
            client.close()
    return out


def ingest_ca_leginfo(max_sections: Optional[int] = None) -> int:
    """Fetch the curated statute set and write one corpus file per law code.

    Returns total chunks written. Statute text is an edict of government —
    chunks are stamped license_status='edict'.
    """
    targets = TARGET_SECTIONS[:max_sections] if max_sections else TARGET_SECTIONS
    fetched = fetch_sections(targets)

    total = 0
    by_law: Dict[str, List[RawSection]] = {}
    for law_code, sec in fetched:
        by_law.setdefault(law_code, []).append(sec)

    for law_code, sections in by_law.items():
        target = IngestTarget(
            code_short=law_code,
            code_name=LAW_NAMES.get(law_code, law_code),
            version="current",
            jurisdictions=["CA"],
            output_filename=f"ca_leginfo_{law_code.lower()}.jsonl",
        )
        chunks = []
        for c in chunk_many(sections, target):
            c["source_tier"] = "official_gov"
            c["license_status"] = "edict"
            chunks.append(c)
        write_jsonl(target, chunks)
        total += len(chunks)
    return total
