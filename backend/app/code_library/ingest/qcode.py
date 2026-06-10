"""Quality Code Publishing (qcode.us) scraper.

Used by most South Bay / Peninsula beach cities (Hermosa, Manhattan, Redondo,
El Segundo, Palos Verdes Estates, Rancho Palos Verdes, etc.) and San Marino.

URL pattern (as of 2026):

    https://qcode.us/codes/<slug>/                # TOC root
    https://qcode.us/codes/<slug>/view.php?topic=<topic>&showAll=1&frames=on

qcode is older-school: server-rendered framesets in places, with a left-rail
TOC and a right-rail section view. We extract the topic tree from the index
page and the section body from `view.php?...&showAll=1`. The `showAll=1`
parameter inlines the full chapter, which is good for our chunker — we still
key on the section number inside the page text.

Shape mirrors municode.py / amlegal.py for CLI parity.
"""
from __future__ import annotations

import re
import time
from typing import Iterable, Iterator, List, Optional
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup

from app.code_library.ingest.base import BaseIngester, IngestTarget, RawSection
from app.utils.logger import get_logger

logger = get_logger(__name__)


QCODE_BASE = "https://qcode.us"
USER_AGENT = (
    "ArchitechturaAI-Ingester/1.0 "
    "(+contact: esmith.marc@gmail.com - fetching public municipal code text)"
)
DEFAULT_DELAY_SEC = 1.0
DEFAULT_TIMEOUT = 30


class QcodeIngester(BaseIngester):
    """Walks one qcode.us code book and yields RawSection per leaf section."""

    name = "qcode"

    def __init__(
        self,
        slug: str,
        *,
        delay_sec: float = DEFAULT_DELAY_SEC,
        max_sections: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.slug = slug
        self.root_url = f"{QCODE_BASE}/codes/{slug}/"
        self.delay_sec = delay_sec
        self.max_sections = max_sections
        self._client = client or httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )

    # ─────────────────────────────────────────────────────────────
    # Public entry
    # ─────────────────────────────────────────────────────────────

    def fetch_sections(self, target: IngestTarget) -> Iterator[RawSection]:
        try:
            toc_html = self._get(self.root_url)
        except Exception as e:
            logger.error(
                f"[qcode] failed to load root TOC at {self.root_url}: {e}"
            )
            return iter(())

        chapter_urls = self._extract_chapter_urls(toc_html, self.root_url)
        if not chapter_urls:
            logger.warning(
                f"[qcode] no chapter links found at {self.root_url} — "
                "TOC selectors may have drifted."
            )
            return iter(())

        yielded = 0
        for chapter_url, chapter_breadcrumb in chapter_urls:
            try:
                html = self._get(chapter_url)
            except Exception as e:
                logger.warning(f"[qcode] chapter fetch failed {chapter_url}: {e}")
                continue
            for section in self._parse_chapter(html, chapter_url, chapter_breadcrumb):
                yield section
                yielded += 1
                if self.max_sections is not None and yielded >= self.max_sections:
                    logger.info(
                        f"[qcode] hit max_sections={self.max_sections}, stopping"
                    )
                    return

    # ─────────────────────────────────────────────────────────────
    # TOC extraction
    # ─────────────────────────────────────────────────────────────

    def _extract_chapter_urls(
        self, html: str, page_url: str
    ) -> List[tuple]:
        """Return [(absolute_url, breadcrumb_list), ...] for every chapter
        in the code. qcode TOCs are flat (Title → Chapter) — we walk down
        one level deeper than the index by following each topic link with
        showAll=1 so the chapter renders all its sections inline."""
        soup = BeautifulSoup(html, "html.parser")
        # qcode uses `topic` query params on the left-rail anchors.
        anchors = soup.select("a[href*='view.php'], a[href*='topic=']")
        out: List[tuple] = []
        seen: set = set()
        current_title: Optional[str] = None

        for a in anchors:
            href = a.get("href", "")
            if not href:
                continue
            label = " ".join(a.get_text(" ", strip=True).split())
            # Heuristic: Title-level entries match "Title X" or all-caps
            # short labels; everything else is a chapter we want to fetch.
            if _TITLE_LABEL_RE.match(label):
                current_title = label
                continue
            # Force showAll=1 so the chapter page contains every section.
            absolute = urljoin(page_url, href)
            if "showAll=1" not in absolute:
                joiner = "&" if "?" in absolute else "?"
                absolute = f"{absolute}{joiner}showAll=1&frames=on"
            if absolute in seen:
                continue
            seen.add(absolute)
            breadcrumb = [current_title, label] if current_title else [label]
            out.append((absolute, breadcrumb))

        return out

    # ─────────────────────────────────────────────────────────────
    # Chapter body parsing
    # ─────────────────────────────────────────────────────────────

    def _parse_chapter(
        self,
        html: str,
        url: str,
        chapter_breadcrumb: List[str],
    ) -> Iterator[RawSection]:
        """A qcode chapter page with showAll=1 contains every section under
        the chapter in one HTML document. We split on section-number headings
        and yield one RawSection per split."""
        soup = BeautifulSoup(html, "html.parser")
        body_el = (
            soup.select_one("div#main")
            or soup.select_one("div.main")
            or soup.select_one("body")
        )
        if body_el is None:
            return

        # Section anchors look like <a name="00.00.000"></a> or
        # <h3>Section 00.00.000 Title</h3>. Pull text in document order and
        # split on a section-number line.
        full_text = body_el.get_text("\n", strip=True)
        if len(full_text) < 80:
            return

        # Lookahead split: each part either is the prefix before any section
        # OR starts with a section-number header followed by that section's
        # full body. We yield one RawSection per part that starts with a
        # valid header.
        parts = _SECTION_SPLIT_RE.split(full_text)
        matched_any = False
        for chunk in parts:
            chunk = chunk.strip()
            m = _SECTION_HEADER_RE.match(chunk)
            if not m:
                continue
            section_number = m.group(1)
            # Title runs from the end of the section number to the first
            # newline or sentence terminator.
            tail = chunk[m.end():].lstrip(" .-:")
            title = tail.split("\n", 1)[0].strip(" .-:") or section_number
            if len(chunk) < 50:
                continue
            matched_any = True
            yield RawSection(
                breadcrumb=[b for b in chapter_breadcrumb if b],
                section_number=section_number,
                title=title,
                text=chunk,
                source_url=url,
            )

        if not matched_any:
            # Couldn't find section boundaries — emit the whole chapter so
            # we at least capture it.
            yield RawSection(
                breadcrumb=[b for b in chapter_breadcrumb if b],
                section_number=(chapter_breadcrumb[-1] if chapter_breadcrumb else "(chapter)"),
                title=chapter_breadcrumb[-1] if chapter_breadcrumb else "",
                text=full_text,
                source_url=url,
            )

    # ─────────────────────────────────────────────────────────────
    # HTTP helper with throttling
    # ─────────────────────────────────────────────────────────────

    def _get(self, url: str) -> str:
        if self.delay_sec:
            time.sleep(self.delay_sec)
        resp = self._client.get(url)
        if resp.status_code == 403 and resp.headers.get("cf-mitigated") == "challenge":
            raise RuntimeError(
                "Cloudflare bot-challenge (403 cf-mitigated) on qcode.us — "
                "use a headless-browser challenge solver or a licensed feed."
            )
        resp.raise_for_status()
        return resp.text


_TITLE_LABEL_RE = re.compile(r"^(Title|TITLE)\s+[IVX0-9]+\b")
_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:Sec\.\s+|Section\s+|§\s*)?"
    r"(\d+\.\d+\.\d+[A-Z]?(?:\.\d+)?)"  # qcode is mostly Title.Chapter.Section
    r"\b",
    re.IGNORECASE,
)
# Split-style regex matches the same header so re.split keeps it.
_SECTION_SPLIT_RE = re.compile(
    r"(?=^\s*(?:Sec\.\s+|Section\s+|§\s*)?\d+\.\d+\.\d+[A-Z]?(?:\.\d+)?\b)",
    re.MULTILINE | re.IGNORECASE,
)


def ingest_qcode_slug(
    slug: str, target: IngestTarget, *, max_sections: Optional[int] = None
) -> int:
    from app.code_library.ingest.chunker import chunk_many
    from app.code_library.ingest.writer import write_jsonl

    logger.info(f"[qcode] starting ingest for slug={slug}")
    ing = QcodeIngester(slug=slug, max_sections=max_sections)
    sections = list(ing.fetch_sections(target))
    logger.info(f"[qcode] fetched {len(sections)} sections; chunking + writing")
    chunks = list(chunk_many(iter(sections), target))
    write_jsonl(target, chunks)
    return len(chunks)
