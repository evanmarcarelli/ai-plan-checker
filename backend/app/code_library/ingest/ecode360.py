"""General Code (ecode360.com) scraper.

ecode360 is the General Code platform. Not heavily used in LA County, but
some smaller cities and some unincorporated areas in adjacent counties use
it. Included for completeness so the publisher dispatch is uniform.

URL pattern:

    https://ecode360.com/<slug>           # TOC root, e.g. /BE2014 for Bellingham
    https://ecode360.com/<guid>           # leaf section by GUID

The TOC is rendered as a JS tree but the underlying anchors are present in
the server HTML — we walk those. Each section page has a `.section-content`
container with the verbatim text.

Shape mirrors the other ingesters.
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


ECODE360_BASE = "https://ecode360.com"
USER_AGENT = (
    "Up2CodeAI-Ingester/1.0 "
    "(+contact: esmith.marc@gmail.com - fetching public municipal code text)"
)
DEFAULT_DELAY_SEC = 1.0
DEFAULT_TIMEOUT = 30


class Ecode360Ingester(BaseIngester):
    name = "ecode360"

    def __init__(
        self,
        slug: str,
        *,
        delay_sec: float = DEFAULT_DELAY_SEC,
        max_sections: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.slug = slug
        self.root_url = f"{ECODE360_BASE}/{slug}"
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

    def fetch_sections(self, target: IngestTarget) -> Iterator[RawSection]:
        try:
            toc_html = self._get(self.root_url)
        except Exception as e:
            logger.error(
                f"[ecode360] failed to load root TOC at {self.root_url}: {e}"
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
                logger.warning(f"[ecode360] skip {leaf_url}: {e}")
                continue
            section = self._parse_leaf(html, leaf_url, breadcrumb)
            if section is None:
                continue
            yield section
            yielded += 1
            if self.max_sections is not None and yielded >= self.max_sections:
                logger.info(
                    f"[ecode360] hit max_sections={self.max_sections}, stopping"
                )
                return

    def _walk_toc(
        self,
        html: str,
        page_url: str,
        parents: List[str],
        visited_containers: set,
    ) -> Iterator[tuple]:
        if page_url in visited_containers:
            return
        visited_containers.add(page_url)

        soup = BeautifulSoup(html, "html.parser")
        # ecode360 TOC anchors are inside .toc-content and the link href is
        # the GUID for the node. We accept several selector forms because
        # the page markup varies between codes.
        anchors = soup.select(
            "a.tocLink, a.guidLink, "
            "div.toc-content a[href^='/'], "
            "nav a[href^='/']"
        )

        if not anchors:
            yield page_url, parents
            return

        for a in anchors:
            href = a.get("href")
            if not href or href.startswith("#"):
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
                    logger.warning(f"[ecode360] recurse failed for {absolute}: {e}")
                    continue
                yield from self._walk_toc(
                    child_html, absolute, new_parents, visited_containers
                )

    def _parse_leaf(
        self,
        html: str,
        url: str,
        breadcrumb: List[str],
    ) -> Optional[RawSection]:
        soup = BeautifulSoup(html, "html.parser")
        body_el = (
            soup.select_one("div.section-content")
            or soup.select_one("section.section")
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

    def _get(self, url: str) -> str:
        if self.delay_sec:
            time.sleep(self.delay_sec)
        resp = self._client.get(url)
        if resp.status_code == 403 and resp.headers.get("cf-mitigated") == "challenge":
            raise RuntimeError(
                "Cloudflare bot-challenge (403 cf-mitigated) on ecode360.com — "
                "use a headless-browser challenge solver or a licensed feed."
            )
        resp.raise_for_status()
        return resp.text


_LEAF_NUMBER_RE = re.compile(
    r"^\s*(?:§\s*|Section\s+|Sec\.\s+)?"
    r"([A-Z]?\d+[A-Z]?(?:[.-]\d+[A-Z]?){0,4})"
    r"\b",
    re.IGNORECASE,
)


def ingest_ecode360_slug(
    slug: str, target: IngestTarget, *, max_sections: Optional[int] = None
) -> int:
    from app.code_library.ingest.chunker import chunk_many
    from app.code_library.ingest.writer import write_jsonl

    logger.info(f"[ecode360] starting ingest for slug={slug}")
    ing = Ecode360Ingester(slug=slug, max_sections=max_sections)
    sections = list(ing.fetch_sections(target))
    logger.info(f"[ecode360] fetched {len(sections)} sections; chunking + writing")
    chunks = list(chunk_many(iter(sections), target))
    write_jsonl(target, chunks)
    return len(chunks)
