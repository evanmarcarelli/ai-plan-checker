"""Municode (library.municode.com) scraper.

Municode hosts the LA Municipal Code (LAMC), LA County Code, and most of the
SE-LA / SGV cities. URL pattern (as of 2026):

    https://library.municode.com/ca/<slug>/codes/code_of_ordinances?nodeId=<NODE_ID>

The site renders an HTML TOC tree that we walk. Section pages contain the
verbatim code text inside a content container we extract.

This module mirrors amlegal.py in shape and contract so the CLI driver can
treat ingesters interchangeably:

    ing = MunicodeIngester(slug="losangeles_ca")
    for section in ing.fetch_sections(target):
        ...

Robustness notes:
  - Municode also occasionally throws bot-challenges. We surface the same
    explicit RuntimeError that amlegal does when that happens, so the
    operator sees the same recovery path.
  - The TOC is large (LAMC ≈ 17K sections); the `max_sections` cap is
    essential during test runs.
  - PDF fallback: a small number of Municode jurisdictions only publish
    PDF-rendered ordinances for certain titles. We do NOT handle those
    here on purpose — those titles land in the LADBS-style local-PDF path
    via `ingest_municode_files()`, which is intentionally lightweight.
"""
from __future__ import annotations

import re
import time
from typing import Iterable, Iterator, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.code_library.ingest.base import BaseIngester, IngestTarget, RawSection
from app.utils.logger import get_logger

logger = get_logger(__name__)


MUNICODE_BASE = "https://library.municode.com"
USER_AGENT = (
    "Up2CodeAI-Ingester/1.0 "
    "(+contact: esmith.marc@gmail.com - fetching public municipal code text)"
)
DEFAULT_DELAY_SEC = 1.0
DEFAULT_TIMEOUT = 30

# Slug → state path mapping. Municode URLs are /<state>/<city-slug>/...
# Default to CA since every entry in jurisdictions.yaml for municode is CA;
# parameterize if non-CA cities are added later.
DEFAULT_STATE_PATH = "ca"


class MunicodeIngester(BaseIngester):
    """Walks one Municode code book and yields RawSection per leaf node."""

    name = "municode"

    def __init__(
        self,
        slug: str,
        *,
        state_path: str = DEFAULT_STATE_PATH,
        delay_sec: float = DEFAULT_DELAY_SEC,
        max_sections: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.slug = slug
        self.state_path = state_path
        self.root_url = (
            f"{MUNICODE_BASE}/{state_path}/{slug}/codes/code_of_ordinances"
        )
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
                f"[municode] failed to load root TOC at {self.root_url}: {e}"
            )
            return iter(())

        visited_containers: set = set()
        visited_leaves: set = set()
        yielded = 0
        for leaf_url, breadcrumb in self._walk_toc(
            toc_html, self.root_url, parents=[], visited_containers=visited_containers,
        ):
            if leaf_url in visited_leaves:
                continue
            visited_leaves.add(leaf_url)
            try:
                html = self._get(leaf_url)
            except Exception as e:
                logger.warning(f"[municode] skip {leaf_url}: {e}")
                continue
            section = self._parse_leaf(html, leaf_url, breadcrumb)
            if section is None:
                continue
            yield section
            yielded += 1
            if self.max_sections is not None and yielded >= self.max_sections:
                logger.info(
                    f"[municode] hit max_sections={self.max_sections}, stopping"
                )
                return

    # ─────────────────────────────────────────────────────────────
    # TOC walk
    # ─────────────────────────────────────────────────────────────

    def _walk_toc(
        self,
        html: str,
        page_url: str,
        parents: List[str],
        visited_containers: set,
    ) -> Iterator[tuple]:
        """Depth-first walk. Yields (leaf_url, breadcrumb_list)."""
        if page_url in visited_containers:
            return
        visited_containers.add(page_url)

        soup = BeautifulSoup(html, "html.parser")
        # Municode's TOC anchors carry data-nodeid on the <a>. They live
        # under different containers depending on whether the page is the
        # root TOC or a section view, so the selector is permissive.
        anchors = soup.select(
            "a[data-nodeid], a.toc-link, "
            "nav a[href*='nodeId='], aside a[href*='nodeId=']"
        )

        if not anchors:
            yield page_url, parents
            return

        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            absolute = urljoin(page_url, href)
            label = " ".join(a.get_text(" ", strip=True).split())
            new_parents = parents + [label] if label else parents

            is_leaf = bool(_LEAF_NUMBER_RE.match(label or ""))
            if is_leaf:
                yield absolute, new_parents
            else:
                if absolute in visited_containers:
                    continue
                try:
                    child_html = self._get(absolute)
                except Exception as e:
                    logger.warning(f"[municode] recurse failed for {absolute}: {e}")
                    continue
                yield from self._walk_toc(
                    child_html, absolute, new_parents, visited_containers
                )

    # ─────────────────────────────────────────────────────────────
    # Leaf parsing
    # ─────────────────────────────────────────────────────────────

    def _parse_leaf(
        self,
        html: str,
        url: str,
        breadcrumb: List[str],
    ) -> Optional[RawSection]:
        soup = BeautifulSoup(html, "html.parser")
        body_el = (
            soup.select_one("div#codeContent")
            or soup.select_one("div.chunk-content")
            or soup.select_one("article")
            or soup.select_one("main")
        )
        if body_el is None:
            return None

        text = body_el.get_text("\n", strip=True)
        if len(text) < 50:
            return None

        last = breadcrumb[-1] if breadcrumb else ""
        m = _LEAF_NUMBER_RE.match(last)
        if m:
            section_number = m.group(1)
            title = last[m.end():].strip(" .-:") or section_number
        else:
            h = body_el.find(["h1", "h2", "h3"])
            section_number = h.get_text(strip=True) if h else "(unnumbered)"
            title = section_number

        return RawSection(
            breadcrumb=[b for b in breadcrumb if b],
            section_number=section_number,
            title=title,
            text=text,
            source_url=url,
        )

    # ─────────────────────────────────────────────────────────────
    # HTTP helper with throttling
    # ─────────────────────────────────────────────────────────────

    def _get(self, url: str) -> str:
        if self.delay_sec:
            time.sleep(self.delay_sec)
        resp = self._client.get(url)
        # Same bot-challenge handling as amlegal — fail loud, not silent.
        if resp.status_code == 403 and resp.headers.get("cf-mitigated") == "challenge":
            raise RuntimeError(
                "Cloudflare bot-challenge (403 cf-mitigated). Municode is "
                "blocking automated HTTP fetches. Plain scraping cannot proceed — "
                "use a headless-browser challenge solver or a licensed data feed."
            )
        if resp.status_code == 429:
            # Municode does aggressive rate limiting on TOC walks.
            raise RuntimeError(
                "HTTP 429 from Municode — increase delay_sec or run with a smaller --max."
            )
        resp.raise_for_status()
        return resp.text


# Same section-number matcher as amlegal — municipal codes share the
# Title.Chapter.Section convention.
_LEAF_NUMBER_RE = re.compile(
    r"^\s*(?:Sec\.\s+|Section\s+|§\s*)?"
    r"([A-Z0-9]+(?:[.-][A-Z0-9]+){1,4})"
    r"\b",
    re.IGNORECASE,
)


def ingest_municode_slug(
    slug: str, target: IngestTarget, *, max_sections: Optional[int] = None
) -> int:
    """CLI helper: build URL from slug, walk, write JSONL. Mirrors
    ingest_amlegal_slug()."""
    from app.code_library.ingest.chunker import chunk_many
    from app.code_library.ingest.writer import write_jsonl

    logger.info(f"[municode] starting ingest for slug={slug}")
    ing = MunicodeIngester(slug=slug, max_sections=max_sections)
    sections = list(ing.fetch_sections(target))
    logger.info(f"[municode] fetched {len(sections)} sections; chunking + writing")
    chunks = list(chunk_many(iter(sections), target))
    write_jsonl(target, chunks)
    return len(chunks)
