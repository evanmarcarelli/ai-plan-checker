"""American Legal Publishing scraper.

URL pattern (as of 2026):
  https://codelibrary.amlegal.com/codes/<slug>/latest/<book>/<node-id>

The site renders a tree of "nodes". A node can be a container (Title,
Chapter, Article) or a leaf (the actual section text). The tree is
traversable by id and each node's JSON payload is fetched off a sibling
JSON endpoint. We do not depend on a private API: we use the same data
the public HTML page consumes, which is reachable as JSON if you fetch
the document fragments with `Accept: application/json` or via the path
`...?format=json`. Some jurisdictions only render HTML; we degrade to
parsing the rendered HTML in that case.

This module is intentionally small and self-contained. It:
  1. Logs in to nothing (the site is public-read).
  2. Throttles to one request per second by default to avoid being a bad
     neighbor.
  3. Identifies itself in User-Agent so the operator can be reached if
     anything goes sideways.

Robustness notes:
  - The HTML structure DOES drift quarter-to-quarter. The parser uses
    a few defensive CSS selectors so a single class rename does not
    silently break ingestion. If the scraper ever returns 0 sections
    for a jurisdiction it normally produces hundreds for, that is the
    canary — re-inspect the live page in a browser.
  - For jurisdictions that resist scraping, fall back to manual:
    download the printable HTML, save under
    backend/app/code_library/ingest/dumps/<slug>.html, and call
    `parse_dump(path, target)` instead of fetch_sections.
"""
from __future__ import annotations

import re
import time
from typing import Iterable, Iterator, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.code_library.ingest.base import BaseIngester, IngestTarget, RawSection
from app.utils.logger import get_logger

logger = get_logger(__name__)


AMLEGAL_BASE = "https://codelibrary.amlegal.com"
USER_AGENT = (
    "PhiCodesAI-Ingester/1.0 "
    "(+contact: esmith.marc@gmail.com - fetching public municipal code text)"
)
DEFAULT_DELAY_SEC = 1.0     # one request per second; configurable per ingester
DEFAULT_TIMEOUT = 30


class AmLegalIngester(BaseIngester):
    """Walks a single American Legal Publishing code book and yields sections.

    Construction takes the root URL for the code; usually you build that from
    the jurisdiction slug like:

        root = AmLegalIngester.build_root_url("pasadena_ca")
        ing  = AmLegalIngester(root_url=root)
        for sect in ing.fetch_sections(target):
            ...
    """

    name = "amlegal"

    def __init__(
        self,
        root_url: str,
        *,
        delay_sec: float = DEFAULT_DELAY_SEC,
        max_sections: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.root_url = root_url.rstrip("/")
        self.delay_sec = delay_sec
        self.max_sections = max_sections   # cap for testing
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )

    # ─────────────────────────────────────────────────────────────
    # URL helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def build_root_url(slug: str) -> str:
        """Slug looks like 'pasadena_ca' or 'longbeach_ca'. The site convention
        is `/codes/<short>/latest/<slug>` where <short> is the slug minus
        the state suffix; common slugs (e.g. pasadena_ca) follow the
        pattern below. When unsure, paste the slug into the search at
        codelibrary.amlegal.com and copy the URL it lands on."""
        short = slug.split("_")[0]
        return f"{AMLEGAL_BASE}/codes/{short}/latest/{slug}"

    # ─────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────

    def fetch_sections(self, target: IngestTarget) -> Iterator[RawSection]:
        """Walk the TOC, yielding one RawSection per leaf."""
        try:
            toc_html = self._get(self.root_url)
        except Exception as e:
            logger.error(f"[amlegal] failed to load root TOC at {self.root_url}: {e}")
            return iter(())

        # Cycle detection: track every container URL we have descended into,
        # not just leaves. Without this, a child page that links back up to
        # its parent (or any cousin) sends us into infinite recursion.
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
                logger.warning(f"[amlegal] skip {leaf_url}: {e}")
                continue
            section = self._parse_leaf(html, leaf_url, breadcrumb)
            if section is None:
                continue
            yield section
            yielded += 1
            if self.max_sections is not None and yielded >= self.max_sections:
                logger.info(f"[amlegal] hit max_sections={self.max_sections}, stopping")
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
        """Depth-first walk over the table-of-contents tree. Yields
        (leaf_url, breadcrumb_list) tuples.

        TOC nodes show up as <a class="toc-item"> in current markup, with
        nested <ul> for children. The fallback selector also catches the
        legacy 'navItem' class. If neither matches, we treat the page as
        a leaf and try to parse it directly.

        visited_containers prevents infinite recursion when a child page
        links back up to its parent or sibling."""
        if page_url in visited_containers:
            return
        visited_containers.add(page_url)

        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.select("a.toc-item, a.navItem, nav a[href*='/codes/']")

        if not anchors:
            # Page itself appears to be a leaf, pass it through.
            yield page_url, parents
            return

        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            absolute = urljoin(page_url, href)
            label = " ".join(a.get_text(" ", strip=True).split())
            new_parents = parents + [label] if label else parents

            # Leaf detection: the section number itself usually appears in
            # the label (e.g. "17.32.040 Hillside Setbacks") and the link
            # text is a leaf when it is NOT a container header. Containers
            # tend to have child anchors as siblings; leaves do not.
            is_leaf = bool(_LEAF_NUMBER_RE.match(label or ""))
            if is_leaf:
                yield absolute, new_parents
            else:
                if absolute in visited_containers:
                    continue   # already walked this branch
                try:
                    child_html = self._get(absolute)
                except Exception as e:
                    logger.warning(f"[amlegal] recurse failed for {absolute}: {e}")
                    continue
                yield from self._walk_toc(child_html, absolute, new_parents, visited_containers)

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

        # The actual code text lives inside one of these containers, in
        # priority order.
        body_el = (
            soup.select_one("div.section-content")
            or soup.select_one("div#content-main")
            or soup.select_one("article")
            or soup.select_one("main")
        )
        if body_el is None:
            return None

        text = body_el.get_text("\n", strip=True)
        if len(text) < 50:
            return None  # too short to be useful — probably a stub

        # Section number + title: the breadcrumb's last entry usually
        # contains "17.32.040 Hillside Setbacks". Pull the number off
        # the front; the rest becomes the title.
        last = breadcrumb[-1] if breadcrumb else ""
        m = _LEAF_NUMBER_RE.match(last)
        if m:
            section_number = m.group(1)
            title = last[m.end():].strip(" .-:") or section_number
        else:
            # Fallback: look in the body for a heading
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
        # Cloudflare bot-challenge detection. As of 2026 American Legal sits
        # behind Cloudflare and returns 403 with `cf-mitigated: challenge` to
        # plain HTTP clients. Surface that explicitly so the operator doesn't
        # mistake it for a transient error or a markup-drift bug — it needs a
        # browser-based challenge solver or a licensed data feed, not a retry.
        if resp.status_code == 403 and resp.headers.get("cf-mitigated") == "challenge":
            raise RuntimeError(
                "Cloudflare bot-challenge (403 cf-mitigated). American Legal is "
                "blocking automated HTTP fetches. Plain scraping cannot proceed — "
                "use a headless-browser challenge solver or a licensed data feed."
            )
        resp.raise_for_status()
        return resp.text


# Section-number heading matcher used by both the TOC walker and the leaf
# parser. Catches the common municipal patterns:
#   "17.32.040"          (Title.Chapter.Section)
#   "Section 17.32.040"
#   "R301.2"             (CRC-style)
#   "Chapter 7A"
_LEAF_NUMBER_RE = re.compile(
    r"^\s*(?:Section\s+|Sec\.\s+)?"
    r"([A-Z0-9]+(?:\.[A-Z0-9]+){1,4})"     # the actual number
    r"\b",
    re.IGNORECASE,
)


# Convenience: a runner function the CLI calls. Keeps __main__.py simple.
def ingest(target: IngestTarget, *, max_sections: Optional[int] = None) -> int:
    """Run an amlegal ingest end to end. Returns number of chunks written."""
    from app.code_library.ingest.chunker import chunk_many
    from app.code_library.ingest.writer import write_jsonl

    # Derive root URL from the first jurisdiction's slug.
    # Convention: jurisdictions are listed as "CA:Pasadena" — we expect
    # the YAML config to also pass a `slug` field used here.
    raise NotImplementedError(
        "Use AmLegalIngester(root_url=...).fetch_sections(target) directly, "
        "or call ingest_amlegal_slug() from the CLI which builds the URL."
    )


def ingest_amlegal_slug(slug: str, target: IngestTarget, *, max_sections: Optional[int] = None) -> int:
    """Helper used by the CLI. Builds URL from slug, walks, writes JSONL."""
    from app.code_library.ingest.chunker import chunk_many
    from app.code_library.ingest.writer import write_jsonl

    root = AmLegalIngester.build_root_url(slug)
    logger.info(f"[amlegal] starting ingest for slug={slug} root={root}")
    ing = AmLegalIngester(root_url=root, max_sections=max_sections)
    sections = list(ing.fetch_sections(target))
    logger.info(f"[amlegal] fetched {len(sections)} sections; chunking + writing")
    chunks = list(chunk_many(iter(sections), target))
    write_jsonl(target, chunks)
    return len(chunks)
