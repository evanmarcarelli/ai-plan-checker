"""LADBS publications ingester.

Pulls the legally-clean, publicly-downloadable Los Angeles building-department
content into the corpus — the layer that bypasses the Cloudflare-blocked
American Legal path. Three kinds:

  - bulletins    : LADBS Information Bulletins (how LADBS interprets the code)
  - corrections  : LADBS Standard Corrections Lists (what examiners actually
                   cite — highest-value ground truth for a plan checker)
  - amendments   : LA local amendments to the CA codes (LAMC Ch. IX edits)

These live on dbs.lacity.gov as directly-linked PDFs (no Cloudflare). The
ingester fetches the index page(s), collects PDF links (one optional level of
same-host recursion for category listings), downloads each PDF, extracts text
with pdfplumber, classifies + chunks via the shared chunker, and writes JSONL
tagged `jurisdictions: ["CA:Los Angeles"]`.

CLI:
    python -m app.code_library.ingest ladbs --kind corrections --max 20
"""
from __future__ import annotations

import io
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.code_library.ingest.base import IngestTarget, RawSection
from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Up2CodeAI-Ingester/1.0 "
    "(+contact: esmith.marc@gmail.com - fetching public LADBS publications)"
)
DEFAULT_DELAY_SEC = 1.0
DEFAULT_TIMEOUT = 45
HOST = "dbs.lacity.gov"

# Currency guard. The LADBS publications index mixes current docs with an
# archive (2007/2010/2011/2013 editions). Injecting superseded code text would
# let the citation gate "verify" findings against dead code — worse than
# nothing. Skip any doc whose detected edition year predates this cutoff.
# (Current cycle: 2025 Title 24 / 2023 LARC.)
MIN_EDITION_YEAR = 2022
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _superseded_year(stem: str, text: str) -> int | None:
    """Return the doc's edition year if it is clearly superseded (< cutoff),
    else None. Looks at the filename first (most reliable), then the head of
    the text. Only flags when a year is actually present."""
    for hay in (stem, (text or "")[:300]):
        m = _YEAR_RE.search(hay)
        if m:
            yr = int(m.group(0))
            return yr if yr < MIN_EDITION_YEAR else None
    return None

# Seed index pages per kind. Multiple seeds are merged.
KIND_SEEDS: Dict[str, List[str]] = {
    "bulletins": [
        "https://dbs.lacity.gov/forms-publications/publications/information-bulletins-guidelines",
    ],
    "corrections": [
        "https://dbs.lacity.gov/forms-and-publications/publications",
    ],
    "amendments": [
        "https://dbs.lacity.gov/los-angeles-city-code-documents",
    ],
}

# (code_short, code_name) per kind — drives the corpus chunk metadata.
KIND_META: Dict[str, Tuple[str, str]] = {
    "bulletins": ("LADBS-IB", "LADBS Information Bulletins"),
    "corrections": ("LADBS-SCL", "LADBS Standard Corrections Lists"),
    "amendments": ("LA-AMEND", "LA Amendments to California Codes"),
}


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )


def _is_pdf(href: str) -> bool:
    return ".pdf" in (href or "").lower()


def _same_host(url: str) -> bool:
    return urlparse(url).netloc.endswith(HOST)


def _looks_like_category(href: str, text: str) -> bool:
    """A same-host link worth following one level to find more PDFs."""
    h = (href or "").lower()
    t = (text or "").lower()
    return (
        _same_host(urljoin(f"https://{HOST}/", h))
        and any(k in h or k in t for k in (
            "bulletin", "publication", "correction", "amendment", "code", "guideline"
        ))
        and not _is_pdf(h)
    )


def collect_pdf_links(
    client: httpx.Client,
    seeds: List[str],
    *,
    follow: bool = True,
    delay: float = DEFAULT_DELAY_SEC,
    max_index_pages: int = 25,
) -> List[str]:
    """Collect absolute PDF URLs from seed index pages, optionally following
    one level of same-host category pages."""
    pdfs: Set[str] = set()
    visited: Set[str] = set()
    queue: List[Tuple[str, int]] = [(s, 0) for s in seeds]

    while queue and len(visited) < max_index_pages:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            time.sleep(delay)
            resp = client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[ladbs] index fetch failed {url}: {e}")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            absolute = urljoin(url, href)
            if _is_pdf(absolute) and _same_host(absolute):
                pdfs.add(absolute.split("#")[0])
            elif follow and depth == 0 and _looks_like_category(href, a.get_text(" ", strip=True)):
                if absolute not in visited:
                    queue.append((absolute, 1))

    return sorted(pdfs)


def _pdf_text(data: bytes) -> str:
    """Extract text from a PDF byte blob using pdfplumber."""
    import pdfplumber

    parts: List[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(txt)
    return "\n".join(parts)


# Bulletin/doc number from a filename, e.g.
#   "ib-p-bc-2020-049-foundation.pdf" -> "P/BC 2020-049"
#   "standard-correction-list-electrical.pdf" -> "ELECTRICAL"
_DOCNUM_RE = re.compile(r"\b((?:p[-/](?:bc|gi|gr|zc|mcr))[-\s]?\d{4}[-\s]?\d{1,4})\b", re.IGNORECASE)


def _derive_number_title(pdf_url: str, text: str) -> Tuple[str, str]:
    stem = Path(urlparse(pdf_url).path).stem
    m = _DOCNUM_RE.search(stem.replace("-", " "))
    if m:
        number = m.group(1).upper().replace(" ", "-").replace("/", "/")
    else:
        number = stem.upper()[:40]
    # Title = first substantive line of the document text, else the slug.
    title = ""
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) >= 8 and not line.isdigit():
            title = line[:120]
            break
    if not title:
        title = stem.replace("-", " ").replace("_", " ").title()[:120]
    return number, title


def fetch_sections(
    kind: str,
    *,
    max_docs: Optional[int] = None,
    delay: float = DEFAULT_DELAY_SEC,
) -> Iterable[RawSection]:
    """Yield one RawSection per LADBS PDF for the given kind."""
    seeds = KIND_SEEDS.get(kind)
    if not seeds:
        raise ValueError(f"unknown LADBS kind {kind!r}; choose from {list(KIND_SEEDS)}")

    label = KIND_META[kind][1]
    with _client() as client:
        links = collect_pdf_links(client, seeds, delay=delay)
        logger.info(f"[ladbs] {kind}: found {len(links)} PDF link(s)")
        yielded = 0
        for pdf_url in links:
            if max_docs is not None and yielded >= max_docs:
                logger.info(f"[ladbs] hit max_docs={max_docs}, stopping")
                return
            try:
                time.sleep(delay)
                resp = client.get(pdf_url)
                resp.raise_for_status()
                text = _pdf_text(resp.content)
            except Exception as e:
                logger.warning(f"[ladbs] skip {pdf_url}: {type(e).__name__}: {e}")
                continue
            if len(text.strip()) < 100:
                logger.warning(f"[ladbs] skip {pdf_url}: too little text ({len(text)} chars)")
                continue
            stem = Path(urlparse(pdf_url).path).stem
            old_year = _superseded_year(stem, text)
            if old_year is not None:
                logger.info(f"[ladbs] skip {stem}: superseded {old_year} edition (< {MIN_EDITION_YEAR})")
                continue
            number, title = _derive_number_title(pdf_url, text)
            yield RawSection(
                breadcrumb=[label, title],
                section_number=number,
                title=title,
                text=text,
                source_url=pdf_url,
            )
            yielded += 1


def ingest_ladbs(kind: str, *, max_docs: Optional[int] = None) -> int:
    """Run a LADBS ingest end to end. Returns number of chunks written."""
    from app.code_library.ingest.chunker import chunk_many
    from app.code_library.ingest.writer import write_jsonl

    code_short, code_name = KIND_META[kind]
    target = IngestTarget(
        code_short=code_short,
        code_name=code_name,
        version="2025",
        jurisdictions=["CA:Los Angeles"],
        output_filename=f"ladbs_{kind}.jsonl",
    )
    sections = list(fetch_sections(kind, max_docs=max_docs))
    logger.info(f"[ladbs] {kind}: {len(sections)} doc(s) fetched; chunking + writing")
    chunks = list(chunk_many(iter(sections), target))
    write_jsonl(target, chunks)   # hardened: refuses to clobber on empty
    return len(chunks)
