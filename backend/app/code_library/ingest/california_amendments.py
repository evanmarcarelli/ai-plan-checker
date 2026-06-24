"""California-wide code amendments ingester.

Pulls public California building-code text and county-level amendments from
the seed list in `california_targets.json` and writes one JSONL file per
source into the shared corpus. Designed to fit the existing pipeline shape
(`writer.write_jsonl`, BM25-ready chunks tagged with jurisdictions).

Source classes handled:

  * `internet_archive_item`         — IA metadata API → download canonical PDF
  * `county_ordinance_pdf_or_attachment` — direct PDF URL
  * `county_code_ordinance_html`    — HTML page (amlegal/codepub) — may be CF-blocked
  * `official_state_index` / `official_state_portal` — DGS index pages: walked
    one level to discover linked PDFs (publishers like ICC stay out of scope —
    those need a license).
  * Tier-1 county hunt              — DuckDuckGo HTML search with the spec's
    patterns, restricted to .gov / .ca.us domains and PDF results.

What it does NOT do (deliberate):

  * Bypass Cloudflare / paywalls / login walls.
  * Republish text from ICC or other licensed publishers.
  * Scrape the ICC public viewer (codes.iccsafe.org) — their ToS forbids it.
    The viewer is still useful for section lookup; the corpus links cite it.

Run:
    cd backend
    python -m app.code_library.ingest california --list
    python -m app.code_library.ingest california --target contra_costa_2025_19
    python -m app.code_library.ingest california --tier1-counties
    python -m app.code_library.ingest california --all          # everything

PDFs are cached under <repo>/../code-pdfs/california/ (same convention as
gov_sources.py). The cache is intentionally outside the repo to keep git
history slim; only the scraper + JSON spec + emitted JSONL chunks are tracked.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlencode

import httpx

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.writer import write_jsonl
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

THIS_DIR = Path(__file__).resolve().parent
SPEC_PATH = THIS_DIR / "california_targets.json"
# Same cache dir convention used by gov_sources.py / malibu_lip.py
CODE_PDFS_DIR = (THIS_DIR.parents[3] / ".." / "code-pdfs" / "california").resolve()
MANIFEST_PATH = CODE_PDFS_DIR / "manifest.jsonl"

# ── Polite-client constants ──────────────────────────────────────────────────

USER_AGENT = (
    "ai-plan-checker-research/1.0 (+https://github.com/evanmarcarelli/ai-plan-checker; "
    "code-corpus crawler; public records only)"
)
PER_DOMAIN_DELAY_S = 1.5     # ≤1 req/1.5s per domain
HTTP_TIMEOUT = 60
MAX_PDF_MB = 300             # refuse pathological downloads
MIN_PDF_BYTES = 4096         # anything smaller is almost certainly an error page
PDF_MAGIC = b"%PDF-"

# Tier-1 hunt: cap per-search results we'll try to fetch (politeness + signal)
MAX_HUNT_RESULTS_PER_QUERY = 4
# A discovered URL is only accepted if its host ends with one of these. Keeps
# us pinned to government/county domains and out of random SEO spam.
ACCEPTED_TLD_SUFFIXES = (
    ".gov", ".ca.gov", ".us", ".ca.us", ".co.us",
)

# ── Domain registry of robots.txt and last-fetch timestamps ──────────────────

_robots_cache: Dict[str, urllib.robotparser.RobotFileParser] = {}
_last_fetch: Dict[str, float] = {}


def _rate_limit(host: str) -> None:
    """Block until at least PER_DOMAIN_DELAY_S has passed for this host."""
    last = _last_fetch.get(host)
    now = time.monotonic()
    if last is not None:
        wait = (last + PER_DOMAIN_DELAY_S) - now
        if wait > 0:
            time.sleep(wait)
    _last_fetch[host] = time.monotonic()


def _robots_allows(url: str, ua: str = USER_AGENT) -> bool:
    """Return True iff robots.txt permits this UA to fetch the URL.

    Failure-open on parse errors (treat as allowed) since robots.txt is
    advisory and many static gov pages serve none."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return False
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urljoin(base, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            _robots_cache[base] = rp
            return True
        _robots_cache[base] = rp
    try:
        return rp.can_fetch(ua, url)
    except Exception:
        return True


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )


def _looks_cloudflare_blocked(resp: httpx.Response) -> bool:
    """Heuristic: CF challenge pages return 403 with a `cf-mitigated` header,
    or 503 with `cf-chl-bypass`. We refuse to retry against these — the
    operator must decide whether to add a headless solver."""
    if resp.status_code not in (403, 503):
        return False
    h = {k.lower(): v for k, v in resp.headers.items()}
    return any(
        k.startswith("cf-") for k in h
    ) or "cloudflare" in (h.get("server", "").lower())


# ── Manifest ─────────────────────────────────────────────────────────────────

@dataclass
class ManifestRecord:
    target_id: str
    jurisdiction: str
    source_url: str
    fetched_at: str  # ISO-8601 UTC
    status: str      # "ok" | "skipped:robots" | "skipped:cloudflare" | "error:<reason>"
    bytes: int = 0
    sha256: str = ""
    cache_path: str = ""
    chunk_count: int = 0
    notes: str = ""


def _append_manifest(rec: ManifestRecord) -> None:
    CODE_PDFS_DIR.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Fetching primitives ─────────────────────────────────────────────────────

def _fetch(url: str, client: httpx.Client) -> Optional[httpx.Response]:
    """Polite GET that respects robots.txt + per-domain rate limit. Returns
    None and logs the reason on any non-fetch outcome (robots block, CF
    challenge, network error). Caller decides what to do with that."""
    host = urlparse(url).netloc
    if not _robots_allows(url):
        logger.warning(f"[california] robots.txt disallows {url}")
        return None
    _rate_limit(host)
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        logger.error(f"[california] HTTP error fetching {url}: {e}")
        return None
    if _looks_cloudflare_blocked(r):
        logger.warning(
            f"[california] Cloudflare challenge for {url} "
            f"(status={r.status_code}); skipping per project policy"
        )
        return None
    if r.status_code >= 400:
        logger.warning(f"[california] {url} returned HTTP {r.status_code}")
        return None
    return r


def _save_pdf(content: bytes, cache_path: Path) -> Tuple[str, int]:
    """Write content to cache atomically. Returns (sha256, bytes_written)."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(content).hexdigest()
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(cache_path)
    return sha, len(content)


def _cache_path_for(target_id: str, jurisdiction: str, suffix: str) -> Path:
    safe_juris = re.sub(r"[^A-Za-z0-9._-]+", "_", jurisdiction.lower()).strip("_")
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", target_id.lower()).strip("_")
    return CODE_PDFS_DIR / safe_juris / f"{safe_id}{suffix}"


# ── Internet Archive resolution ─────────────────────────────────────────────

def _ia_item_id(url: str) -> Optional[str]:
    """Extract item id from an https://archive.org/details/<id> URL."""
    m = re.match(r"^https?://archive\.org/(?:details|download|metadata)/([^/?#]+)", url)
    return m.group(1) if m else None


def _ia_resolve_pdf(item_id: str, client: httpx.Client) -> Optional[str]:
    """Use the IA metadata endpoint to find the canonical PDF for an item.
    Prefers the largest text-bearing PDF over JP2/JPEG bundles."""
    meta_url = f"https://archive.org/metadata/{item_id}"
    r = _fetch(meta_url, client)
    if r is None:
        return None
    try:
        meta = r.json()
    except Exception:
        return None
    files = meta.get("files") or []
    pdfs = [
        f for f in files
        if isinstance(f.get("name"), str) and f["name"].lower().endswith(".pdf")
    ]
    if not pdfs:
        return None
    pdfs.sort(key=lambda f: int(f.get("size") or 0), reverse=True)
    return f"https://archive.org/download/{item_id}/{pdfs[0]['name']}"


# ── PDF parsing ─────────────────────────────────────────────────────────────

# Lazy import to keep `--list` and other no-fetch commands cheap.
def _open_pdf(path: Path):
    import fitz   # PyMuPDF
    return fitz.open(str(path))


_SECTION_HEAD = re.compile(
    r"""^\s*
        (?:
            (?P<sec>(?:CHAPTER|SECTION|ARTICLE)\s+[A-Z0-9.\-]+)   # CHAPTER 7A, SECTION 503
          | (?P<num>(?:R?\d+(?:\.\d+)+|R?\d+[A-Z]?\.\d+(?:\.\d+)*))  # R301.2, 1505.1.3
        )
        (?P<title>\s+[A-Z][^\n]{0,160})?
        \s*$
    """,
    re.VERBOSE,
)


FALLBACK_CHUNK_CHARS = 2000   # window size for the non-ICC fallback chunker
FALLBACK_CHUNK_OVERLAP = 200  # 10% overlap so cross-window phrases survive


def _parse_pdf_to_sections(pdf_path: Path) -> List[RawSection]:
    """Coarse ICC-style section split. Detects CHAPTER/SECTION/ARTICLE headers
    and numbered sections (`R301.2`, `1505.1.3`). When the document has no
    ICC structure (a staff report, a council resolution narrative, a one-off
    amendment letter), falls back to fixed-window chunks so the body text is
    still searchable instead of being silently dropped.

    The existing licensed_pdf / vcbc parsers are more sophisticated; this is
    the right tradeoff for amendment ordinances whose structure varies."""
    try:
        doc = _open_pdf(pdf_path)
    except Exception as e:
        logger.error(f"[california] could not open {pdf_path}: {e}")
        return []

    lines: List[str] = []
    for page in doc:
        try:
            text = page.get_text("text") or ""
        except Exception:
            continue
        lines.extend(text.splitlines())
    doc.close()

    sections: List[RawSection] = []
    current_breadcrumb: List[str] = []
    current_section: Optional[str] = None
    current_title: str = ""
    current_body: List[str] = []

    def _flush() -> None:
        nonlocal current_body
        if not (current_section or current_breadcrumb):
            return
        body = "\n".join(s.strip() for s in current_body).strip()
        if len(body) < 30:
            current_body = []
            return
        sections.append(RawSection(
            breadcrumb=list(current_breadcrumb),
            section_number=current_section or "body",
            title=current_title or (current_breadcrumb[-1] if current_breadcrumb else ""),
            text=body,
            source_url="",
            extra_tags=["california", "local_amendment"],
        ))
        current_body = []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            current_body.append("")
            continue
        m = _SECTION_HEAD.match(line)
        if not m:
            current_body.append(line)
            continue
        sec = m.group("sec")
        num = m.group("num")
        title_match = (m.group("title") or "").strip()
        if sec:
            # CHAPTER/SECTION/ARTICLE: starts a new top-level breadcrumb level
            _flush()
            current_breadcrumb = [sec.strip()]
            current_section = sec.strip()
            current_title = title_match
        else:
            # Numbered subsection
            _flush()
            current_section = num.strip()
            current_title = title_match
            if current_breadcrumb and current_breadcrumb[-1] != num:
                if len(current_breadcrumb) == 1:
                    current_breadcrumb.append(num)
                else:
                    current_breadcrumb[-1] = num
    _flush()

    if sections:
        return sections

    # ── Fallback: no ICC sections found → window-chunk the whole document.
    # Triggers on amendment ordinances that aren't ICC-shaped (staff reports,
    # council resolutions, single-topic letters). Keeps the text searchable
    # rather than silently dropping the document.
    body = "\n".join(lines).strip()
    if len(body) < FALLBACK_CHUNK_CHARS // 2:
        return []
    step = FALLBACK_CHUNK_CHARS - FALLBACK_CHUNK_OVERLAP
    out: List[RawSection] = []
    for i, start in enumerate(range(0, len(body), step)):
        chunk = body[start:start + FALLBACK_CHUNK_CHARS]
        if len(chunk.strip()) < 200:
            continue
        out.append(RawSection(
            breadcrumb=[f"doc:{pdf_path.stem}"],
            section_number=f"doc-{i:03d}",
            title=f"{pdf_path.stem} (window {i})",
            text=chunk,
            source_url="",
            extra_tags=["california", "local_amendment", "fallback_chunk"],
        ))
    return out


# ── Chunk builder (matches existing corpus shape) ───────────────────────────

def _slugify_section(num: str) -> str:
    return re.sub(r"[^A-Za-z0-9.\-]+", "-", num).strip("-").lower() or "body"


def _build_chunks(
    sections: Iterable[RawSection],
    *,
    target: IngestTarget,
    jurisdictions: List[str],
    source_url: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    code_prefix = target.code_short.lower().replace(" ", "-")
    for i, s in enumerate(sections):
        chunk_id = f"{code_prefix}-{_slugify_section(s.section_number)}-{i:04d}"
        out.append({
            "chunk_id": chunk_id,
            "code_name": target.code_name,
            "code_short": target.code_short,
            "version": target.version,
            "section": s.section_number,
            "title": s.title,
            "category": "building_safety",
            "jurisdictions": jurisdictions,
            "text": s.text,
            "tags": ["california", "local_amendment"] + (s.extra_tags or []),
            "source_tier": "official_gov",
            "license_status": "edict",
            "source_url": source_url,
            "breadcrumb": s.breadcrumb,
        })
    return out


# ── Per-target ingest routines ──────────────────────────────────────────────

def _ingest_pdf_target(
    target_meta: Dict[str, Any],
    pdf_url: str,
    *,
    target_id: str,
    jurisdiction: str,
    code_short: str,
    code_name: str,
    version: str,
    jurisdiction_tags: List[str],
    output_filename: str,
    client: httpx.Client,
) -> int:
    """Download a PDF, parse it, write JSONL, append manifest. Returns chunk count."""
    cache = _cache_path_for(target_id, jurisdiction, ".pdf")
    rec = ManifestRecord(
        target_id=target_id,
        jurisdiction=jurisdiction,
        source_url=pdf_url,
        fetched_at=_now_iso(),
        status="pending",
    )

    if cache.exists() and cache.stat().st_size >= MIN_PDF_BYTES:
        logger.info(f"[california] cache hit {cache.name} ({cache.stat().st_size/1_000_000:.1f} MB)")
        content = cache.read_bytes()
        rec.sha256 = hashlib.sha256(content).hexdigest()
        rec.bytes = len(content)
        rec.cache_path = str(cache)
    else:
        r = _fetch(pdf_url, client)
        if r is None:
            rec.status = "skipped:robots-or-cloudflare-or-http-error"
            _append_manifest(rec)
            return 0
        body = r.content
        if not body.startswith(PDF_MAGIC):
            rec.status = "error:not-a-pdf"
            rec.notes = f"content-type={(r.headers.get('content-type') or '').lower()!r}"
            _append_manifest(rec)
            return 0
        if len(body) > MAX_PDF_MB * 1_000_000:
            rec.status = "error:too-large"
            rec.notes = f"{len(body)/1_000_000:.1f}MB > {MAX_PDF_MB}MB"
            _append_manifest(rec)
            return 0
        sha, n = _save_pdf(body, cache)
        rec.sha256 = sha
        rec.bytes = n
        rec.cache_path = str(cache)

    sections = _parse_pdf_to_sections(cache)
    if not sections:
        rec.status = "error:no-sections-parsed"
        _append_manifest(rec)
        return 0

    target = IngestTarget(
        code_short=code_short,
        code_name=code_name,
        version=version,
        jurisdictions=jurisdiction_tags,
        output_filename=output_filename,
    )
    chunks = _build_chunks(
        sections,
        target=target,
        jurisdictions=jurisdiction_tags,
        source_url=pdf_url,
    )
    write_jsonl(target, chunks)
    rec.status = "ok"
    rec.chunk_count = len(chunks)
    _append_manifest(rec)
    return len(chunks)


def _ingest_internet_archive(item: Dict[str, Any], client: httpx.Client) -> int:
    item_id = _ia_item_id(item["url"]) or ""
    if not item_id:
        logger.warning(f"[california] could not parse IA id from {item['url']}")
        return 0
    pdf_url = _ia_resolve_pdf(item_id, client)
    if not pdf_url:
        logger.warning(f"[california] no PDF found in IA item {item_id}")
        return 0
    # Derive code metadata from the item name
    code_short, version = _derive_code_meta(item.get("name", ""), item_id)
    return _ingest_pdf_target(
        item,
        pdf_url,
        target_id=item["id"],
        jurisdiction="State of California",
        code_short=code_short,
        code_name=item["name"],
        version=version,
        jurisdiction_tags=["CA"],
        output_filename=f"ca_archive_{item['id']}.jsonl",
        client=client,
    )


def _ingest_direct_pdf_target(item: Dict[str, Any], client: httpx.Client) -> int:
    jurisdiction = item.get("jurisdiction", "California")
    return _ingest_pdf_target(
        item,
        item["source_url"],
        target_id=item["id"],
        jurisdiction=jurisdiction,
        code_short=item.get("code_short") or _derive_code_short(item),
        code_name=item["name"],
        version=item.get("version") or _derive_version(item),
        jurisdiction_tags=[f"CA:{jurisdiction}"],
        output_filename=f"ca_amendment_{item['id']}.jsonl",
        client=client,
    )


def _ingest_html_target(item: Dict[str, Any], client: httpx.Client) -> int:
    """Fetch an HTML index page (DGS / county codified text). Records the
    visit in the manifest; only descends one level when the page directly
    links to PDFs we can take. amlegal pages typically Cloudflare-block."""
    url = item.get("source_url") or item.get("url")
    rec = ManifestRecord(
        target_id=item["id"],
        jurisdiction=item.get("jurisdiction", "California"),
        source_url=url or "",
        fetched_at=_now_iso(),
        status="pending",
    )
    if not url:
        rec.status = "error:no-url"
        _append_manifest(rec)
        return 0
    r = _fetch(url, client)
    if r is None:
        rec.status = "skipped:robots-or-cloudflare-or-http-error"
        _append_manifest(rec)
        return 0
    html = r.text or ""
    rec.bytes = len(r.content or b"")
    rec.status = "ok:discovered"
    rec.notes = ""

    # Find first-level PDF links
    pdf_links = _extract_pdf_links(html, base_url=url)
    rec.notes = f"discovered_pdfs={len(pdf_links)}"
    _append_manifest(rec)

    if not pdf_links:
        return 0
    # Ingest discovered PDFs, capped to keep one HTML page from running away
    total = 0
    for i, link in enumerate(pdf_links[:6]):
        sub_id = f"{item['id']}__pdf_{i}"
        total += _ingest_pdf_target(
            item,
            link,
            target_id=sub_id,
            jurisdiction=item.get("jurisdiction", "California"),
            code_short=_derive_code_short(item),
            code_name=f"{item['name']} (linked PDF {i+1})",
            version=_derive_version(item),
            jurisdiction_tags=[f"CA:{item.get('jurisdiction', 'California')}"],
            output_filename=f"ca_discovered_{sub_id}.jsonl",
            client=client,
        )
    return total


def _extract_pdf_links(html: str, *, base_url: str) -> List[str]:
    """Pull href values pointing to PDFs from an HTML page (lightweight regex
    pass — keeps the dep on bs4 optional for this path)."""
    raw = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    out: List[str] = []
    seen = set()
    for href in raw:
        if "?" in href:
            base, _ = href.split("?", 1)
        else:
            base = href
        if not base.lower().endswith(".pdf"):
            continue
        full = urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out


# ── Tier-1 county amendment hunt (DuckDuckGo HTML interface) ────────────────

def _ddg_html_search(query: str, client: httpx.Client) -> List[Dict[str, str]]:
    """POST to html.duckduckgo.com/html/ and return [{title,url,snippet}, ...].

    Returns [] when the response is empty / blocked / unparseable. DDG's HTML
    interface is unauthenticated and bot-tolerant when used at a polite rate.
    We filter aggressively downstream — no need to inspect ads/JS UI."""
    url = "https://html.duckduckgo.com/html/"
    host = urlparse(url).netloc
    if not _robots_allows(url):
        return []
    _rate_limit(host)
    try:
        r = client.post(url, data={"q": query})
    except httpx.HTTPError as e:
        logger.warning(f"[california] DDG search failed: {e}")
        return []
    if r.status_code == 202 or "result__a" not in (r.text or ""):
        # 202 = soft bot challenge (homepage shell, no results). The HTML
        # interface used to be scrape-tolerant but has been tightening; if
        # you need real tier-1 hunt results, add per-county direct ordinance
        # URLs to california_targets.json (most robust path) or wire a
        # search API key (Bing/Brave/SerpAPI) — neither belongs in the
        # public free-tier code.
        logger.warning(
            f"[california] DDG returned no parseable results (status={r.status_code}); "
            f"hunt query yielded nothing — see code comment for the fix"
        )
        return []
    if r.status_code >= 400:
        return []
    html = r.text or ""
    # Result links live in <a class="result__a" href="...">
    hits = re.findall(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
        html,
    )
    out: List[Dict[str, str]] = []
    for href, title in hits:
        # DDG sometimes wraps the real URL in a redirect: /l/?uddg=<encoded>
        m = re.search(r"[?&]uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote
            real = unquote(m.group(1))
        else:
            real = href
        out.append({"url": real, "title": title.strip(), "snippet": ""})
    return out


def _accept_hunt_url(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    host = (p.netloc or "").lower()
    if any(host.endswith(suf) for suf in ACCEPTED_TLD_SUFFIXES):
        return True
    # Allow archive.org because we can pull canonical PDFs there reliably
    if host.endswith("archive.org"):
        return True
    return False


def _hunt_county(county: str, patterns: List[str], client: httpx.Client) -> int:
    """For one county, run each search pattern and ingest any PDFs found.
    Dedupes URLs across patterns. Returns total chunks ingested for the county."""
    seen: set = set()
    total = 0
    county_label = county.lower().replace(" ", "_") + "_county"
    for pat in patterns:
        q = pat.replace("county", county)
        logger.info(f"[california] hunt {county!r}: {q}")
        results = _ddg_html_search(q, client)
        accepted = 0
        for hit in results[:MAX_HUNT_RESULTS_PER_QUERY * 4]:  # filter heavy
            u = hit["url"]
            if u in seen:
                continue
            if not _accept_hunt_url(u):
                continue
            seen.add(u)
            accepted += 1
            if accepted > MAX_HUNT_RESULTS_PER_QUERY:
                break

            # Only fetch if URL looks like a PDF or is an archive.org item
            if u.lower().endswith(".pdf"):
                tid = f"hunt_{county_label}_{hashlib.sha1(u.encode()).hexdigest()[:8]}"
                total += _ingest_pdf_target(
                    {"id": tid, "name": hit.get("title") or u},
                    u,
                    target_id=tid,
                    jurisdiction=f"{county} County",
                    code_short=f"{_county_short(county)}-AMD",
                    code_name=f"{county} County Amendment ({hit.get('title') or 'untitled'})",
                    version="discovered",
                    jurisdiction_tags=[f"CA:{county} County"],
                    output_filename=f"ca_hunt_{tid}.jsonl",
                    client=client,
                )
            elif "archive.org/details/" in u:
                item_id = _ia_item_id(u) or ""
                if item_id:
                    pdf_url = _ia_resolve_pdf(item_id, client)
                    if pdf_url:
                        tid = f"hunt_{county_label}_ia_{item_id}"
                        total += _ingest_pdf_target(
                            {"id": tid, "name": hit.get("title") or u},
                            pdf_url,
                            target_id=tid,
                            jurisdiction=f"{county} County",
                            code_short=f"{_county_short(county)}-AMD",
                            code_name=f"{county} County (IA: {item_id})",
                            version="discovered",
                            jurisdiction_tags=[f"CA:{county} County"],
                            output_filename=f"ca_hunt_{tid}.jsonl",
                            client=client,
                        )
            # else: HTML page — record in manifest but don't descend
            else:
                _append_manifest(ManifestRecord(
                    target_id=f"hunt_{county_label}_html_{hashlib.sha1(u.encode()).hexdigest()[:8]}",
                    jurisdiction=f"{county} County",
                    source_url=u,
                    fetched_at=_now_iso(),
                    status="discovered:html-not-ingested",
                    notes=hit.get("title") or "",
                ))
    return total


def _county_short(county: str) -> str:
    return re.sub(r"[^A-Za-z]+", "", county).upper()[:6]


# ── Metadata heuristics ─────────────────────────────────────────────────────

def _derive_code_meta(name: str, item_id: str) -> Tuple[str, str]:
    """Pick a (code_short, version) pair from an IA item's display name.
    Falls back to generic CA-CODE / item-id when the name is opaque."""
    n = (name or "").lower() + " " + (item_id or "").lower()
    code_short = "CA-CODE"
    if "residential" in n:
        code_short = "CRC"
    elif "existing" in n:
        code_short = "CEBC"
    elif "fire" in n:
        code_short = "CFC"
    elif "building" in n:
        code_short = "CBC"
    version = "unknown"
    m = re.search(r"(19|20)\d{2}", name or item_id)
    if m:
        version = m.group(0)
    return code_short, version


def _derive_code_short(item: Dict[str, Any]) -> str:
    n = (item.get("name") or "").lower()
    if "residential" in n:
        return "CRC-AMD"
    if "fire" in n:
        return "CFC-AMD"
    if "energy" in n or "calgreen" in n:
        return "CALGREEN-AMD"
    return "CBC-AMD"


def _derive_version(item: Dict[str, Any]) -> str:
    n = (item.get("name") or "") + " " + (item.get("source_url") or "")
    m = re.search(r"(19|20)\d{2}", n)
    return m.group(0) if m else "current"


# ── Public entry points ─────────────────────────────────────────────────────

def load_spec() -> Dict[str, Any]:
    with SPEC_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def list_targets() -> List[Tuple[str, str, str]]:
    """Return [(target_id, type, name), ...] for the CLI `--list` command."""
    spec = load_spec()
    out: List[Tuple[str, str, str]] = []
    for section in ("canonical_sources", "core_code_targets",
                    "archive_targets", "local_amendment_targets"):
        for item in spec.get(section, []):
            out.append((item["id"], item.get("type", section), item["name"]))
    counties = spec.get("county_amendment_hunt_list", {}).get("tier_1_counties", [])
    for c in counties:
        out.append((f"hunt_{c.lower().replace(' ', '_')}_county",
                    "tier1_county_hunt", f"{c} County (DuckDuckGo hunt)"))
    return out


def ingest_target(target_id: str) -> int:
    """Run a single target by id. Returns chunk count written."""
    spec = load_spec()
    with _client() as client:
        # Search all sections for the id
        for section in ("canonical_sources", "core_code_targets",
                        "archive_targets", "local_amendment_targets"):
            for item in spec.get(section, []):
                if item["id"] != target_id:
                    continue
                return _dispatch_target(item, client)
        # Tier-1 county hunt
        for c in spec.get("county_amendment_hunt_list", {}).get("tier_1_counties", []):
            if f"hunt_{c.lower().replace(' ', '_')}_county" == target_id:
                patterns = spec["county_amendment_hunt_list"]["search_patterns"]
                return _hunt_county(c, patterns, client)
    logger.error(f"[california] unknown target id: {target_id}")
    return 0


def _dispatch_target(item: Dict[str, Any], client: httpx.Client) -> int:
    t = item.get("type", "")
    if t == "internet_archive_item":
        return _ingest_internet_archive(item, client)
    if t == "county_ordinance_pdf_or_attachment":
        return _ingest_direct_pdf_target(item, client)
    if t in ("county_code_ordinance_html", "official_state_index",
             "official_state_portal", "public_text_viewer", "discovery_seed"):
        return _ingest_html_target(item, client)
    # Fallback: treat as direct PDF if URL ends with .pdf, else HTML
    url = item.get("source_url") or item.get("url") or ""
    if url.lower().endswith(".pdf"):
        return _ingest_direct_pdf_target(item, client)
    if url:
        return _ingest_html_target(item, client)
    logger.warning(f"[california] target {item.get('id')} has no actionable URL")
    return 0


def ingest_tier1_counties(max_per_county: Optional[int] = None) -> int:
    spec = load_spec()
    counties = spec.get("county_amendment_hunt_list", {}).get("tier_1_counties", [])
    patterns = spec.get("county_amendment_hunt_list", {}).get("search_patterns", [])
    total = 0
    with _client() as client:
        for c in counties:
            n = _hunt_county(c, patterns, client)
            logger.info(f"[california] tier1 {c}: {n} chunks")
            total += n
    return total


def ingest_all() -> int:
    """Run every explicit target, then the tier-1 hunt. Returns total chunks."""
    spec = load_spec()
    total = 0
    with _client() as client:
        for section in ("archive_targets", "local_amendment_targets",
                        "canonical_sources", "core_code_targets"):
            for item in spec.get(section, []):
                try:
                    n = _dispatch_target(item, client)
                    logger.info(f"[california] {item['id']}: {n} chunks")
                    total += n
                except Exception as e:
                    logger.error(f"[california] {item['id']} failed: {type(e).__name__}: {e}")
        counties = spec.get("county_amendment_hunt_list", {}).get("tier_1_counties", [])
        patterns = spec.get("county_amendment_hunt_list", {}).get("search_patterns", [])
        for c in counties:
            try:
                n = _hunt_county(c, patterns, client)
                logger.info(f"[california] hunt {c}: {n} chunks")
                total += n
            except Exception as e:
                logger.error(f"[california] hunt {c} failed: {type(e).__name__}: {e}")
    logger.info(f"[california] DONE total chunks={total}; manifest={MANIFEST_PATH}")
    return total
