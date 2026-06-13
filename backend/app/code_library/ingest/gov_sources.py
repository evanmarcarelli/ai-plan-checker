"""Auto-fetch registry for FREE, government-published code sources.

This is the "go to the site that hosts the free version and pull it in"
half of the corpus pipeline — but scoped strictly to sources that are
genuinely free to download and republish: government works and state/
federal edicts (public domain under Veeck / Georgia v. Public.Resource.Org).

Each entry declares where the authoritative free copy lives and which
ingester turns it into corpus chunks. Two fetch strategies:

  * download_pdf — a stable government URL to a PDF; we download it to the
    shared code-pdfs/ cache (idempotent) and hand the path to the ingester.
  * self_fetch  — the ingester already fetches its own source (ada.gov,
    leginfo, coastal.ca.gov); we just invoke it.

WHAT IS NOT HERE (by design): ICC- and IAPMO-published model codes adopted
into Title 24 — the CBC, CRC, CEBC, CFC (ICC) and CPC, CMC (IAPMO). Those
are copyrighted publications behind a paywall / bot-challenge; the compliant
path is a licensed local copy via the `licensed-pdf` / `vcbc` commands, NOT
auto-fetch. They are listed in KNOWN_LICENSED so `gov-fetch --list` can show
the operator the full picture (free vs. buy) in one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Shared local cache for downloaded source PDFs (same dir malibu_lip uses).
CODE_PDFS_DIR = (Path(__file__).resolve().parents[4] / ".." / "code-pdfs").resolve()

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class GovSource:
    key: str                         # CLI selector, e.g. "energy-code"
    name: str                        # human label
    scope: str                       # corpus jurisdiction layer, e.g. "CA"
    license: str                     # "public_domain" | "edict"
    strategy: str                    # "download_pdf" | "self_fetch"
    ingest: Callable[..., int]       # ingester; takes pdf_path for download_pdf
    url: Optional[str] = None        # required for download_pdf
    filename: Optional[str] = None   # cache filename for download_pdf
    note: str = ""


def _download_pdf(url: str, dest: Path, *, force: bool = False) -> Path:
    """Download a PDF to dest (cached, atomic, validated). Reuses an existing
    valid copy unless force=True. Raises on a non-PDF response (e.g. an HTML
    404 page) rather than caching garbage."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force and dest.stat().st_size > 10_000:
        with dest.open("rb") as f:
            if f.read(5) == b"%PDF-":
                logger.info(f"[gov-fetch] using cached {dest.name} "
                            f"({dest.stat().st_size/1_000_000:.1f} MB)")
                return dest

    logger.info(f"[gov-fetch] downloading {url}")
    with httpx.Client(timeout=300, follow_redirects=True,
                      headers={"User-Agent": _BROWSER_UA}) as c:
        r = c.get(url)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        if not (r.content[:5] == b"%PDF-" or "pdf" in ct):
            raise ValueError(
                f"[gov-fetch] {url} did not return a PDF (content-type={ct!r}, "
                f"{len(r.content)} bytes). The URL may have moved — update the "
                f"registry entry."
            )
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
    logger.info(f"[gov-fetch] saved {dest.name} ({dest.stat().st_size/1_000_000:.1f} MB)")
    return dest


# ── Lazy ingester imports (kept inside thunks so importing this registry is
# cheap and free of heavy parser deps until a source is actually fetched). ──

def _ingest_energy_code(pdf_path: str, max_sections=None) -> int:
    from app.code_library.ingest.energy_code import ingest_energy_code
    return ingest_energy_code(pdf_path, max_sections=max_sections)


def _ingest_ada(max_sections=None) -> int:
    from app.code_library.ingest.ada_gov import ingest_ada_2010
    return ingest_ada_2010(max_sections=max_sections)


def _ingest_leginfo(max_sections=None) -> int:
    from app.code_library.ingest.ca_leginfo import ingest_ca_leginfo
    return ingest_ca_leginfo(max_sections=max_sections)


def _ingest_coastal(max_sections=None) -> int:
    from app.code_library.ingest.ca_leginfo import ingest_ca_coastal_act
    return ingest_ca_coastal_act(max_sections=max_sections)


def _ingest_malibu(max_sections=None) -> int:
    from app.code_library.ingest.malibu_lip import ingest_malibu_lip
    return ingest_malibu_lip(max_sections=max_sections)


REGISTRY: List[GovSource] = [
    GovSource(
        key="energy-code",
        name="California Energy Code (Title 24, Part 6), 2025",
        scope="CA",
        license="edict",
        strategy="download_pdf",
        ingest=_ingest_energy_code,
        # Verified live 2026-06 (the Drupal "_0" re-upload of CEC-400-2025-010-F).
        url=("https://www.energy.ca.gov/sites/default/files/2025-07/"
             "CEC-400-2025-010-F_0.pdf"),
        filename="ca_energy_code_2025_adopted_CEC-400-2025-010-F.pdf",
        note="Adopted edition only — NOT the 'Restructured/For Information Only' draft.",
    ),
    GovSource(
        key="ada-2010",
        name="2010 ADA Standards for Accessible Design",
        scope="*",
        license="public_domain",
        strategy="self_fetch",
        ingest=_ingest_ada,
        note="US government work (ada.gov).",
    ),
    GovSource(
        key="ca-leginfo",
        name="California statutes (Gov Code VHFSZ / ADU, PRC 4291)",
        scope="CA",
        license="edict",
        strategy="self_fetch",
        ingest=_ingest_leginfo,
        note="leginfo.legislature.ca.gov — official, no Cloudflare.",
    ),
    GovSource(
        key="ca-coastal",
        name="California Coastal Act (PRC Div. 20)",
        scope="CA:Coastal",
        license="edict",
        strategy="self_fetch",
        ingest=_ingest_coastal,
    ),
    GovSource(
        key="malibu-lip",
        name="Malibu LCP Local Implementation Plan (certified)",
        scope="CA:Malibu",
        license="edict",
        strategy="self_fetch",
        ingest=_ingest_malibu,
        note="coastal.ca.gov certified plan PDF.",
    ),
]

# Adopted Title 24 / model codes that are NOT free to auto-fetch — listed so
# the operator sees the whole map. Ingest these from a licensed local copy.
KNOWN_LICENSED = [
    ("CBC",  "California Building Code (T24 Pt 2)",      "ICC",    "licensed-pdf"),
    ("CRC",  "California Residential Code (T24 Pt 2.5)", "ICC",    "licensed-pdf"),
    ("CEBC", "California Existing Building Code (T24 Pt 10)", "ICC", "licensed-pdf"),
    ("CFC",  "California Fire Code (T24 Pt 9)",          "ICC",    "licensed-pdf"),
    ("CPC",  "California Plumbing Code (T24 Pt 5)",      "IAPMO",  "licensed-pdf"),
    ("CMC",  "California Mechanical Code (T24 Pt 4)",    "IAPMO",  "licensed-pdf"),
    ("VCBC", "Ventura County Building Code (Ord. 4655)", "county", "vcbc"),
]


def get_source(key: str) -> Optional[GovSource]:
    return next((s for s in REGISTRY if s.key == key), None)


def fetch_and_ingest(key: str, *, force: bool = False,
                     max_sections: Optional[int] = None) -> int:
    """Fetch (or reuse cached) one registry source and ingest it. Returns the
    number of chunks written."""
    src = get_source(key)
    if src is None:
        raise KeyError(f"unknown gov source {key!r}; "
                       f"known: {', '.join(s.key for s in REGISTRY)}")
    logger.info(f"[gov-fetch] {src.key}: {src.name}")
    if src.strategy == "download_pdf":
        if not src.url:
            raise ValueError(f"{src.key} is download_pdf but has no url")
        pdf = _download_pdf(src.url, CODE_PDFS_DIR / (src.filename or f"{src.key}.pdf"),
                            force=force)
        return src.ingest(str(pdf), max_sections=max_sections)
    if src.strategy == "self_fetch":
        return src.ingest(max_sections=max_sections)
    raise ValueError(f"unknown strategy {src.strategy!r} for {src.key}")
