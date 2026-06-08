"""
Vision-based title-sheet extractor.

When PyMuPDF text-layer extraction yields garbage values for the code data
summary (occupancy, construction type, building height/area, address), this
service renders the candidate title-sheet pages and asks Claude vision to read
the same fields directly off the drawing.

This is the second-leg fix for "all reviews come back needs_review with zero
corrections": the cause was structured fields = null in the JSON sent to
department reviewers. Filling them via vision is the highest-leverage fix —
the regex extractor in pdf_processor.py only matches very narrow label
formats and frequently returns None or false positives (e.g. "C" for
occupancy from "CERTIFICATE OF OCCUPANCY") on real architectural sets.
"""
import asyncio
import base64
import json
import re
from typing import Dict, List, Optional, Any

import anthropic
import fitz  # PyMuPDF

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Keywords that suggest a page is the title sheet / code data summary.
# Hits per page are summed; pages with the most hits are sent to vision first.
TITLE_SHEET_KEYWORDS = [
    "code data", "code summary", "code analysis", "project data", "project info",
    "applicable codes", "design codes", "building code", "occupancy",
    "occupancy group", "construction type", "type of construction",
    "sheet index", "scope of work", "title sheet", "cover sheet",
    "general notes", "zoning", "deferred submittal",
]

# Sheet-number patterns that conventionally label a title / cover / code sheet
# (T-1.0, T1, G-0.0, G0, CS-1, A0.0, A-0). Used to boost a page's title-sheet
# score even when its body text is sparse (vector-drawn sheets extract little
# selectable text).
_TITLE_SHEET_NUMBER = re.compile(
    r"\b(?:T|G|CS|A)[\s-]?0*1?\.?0\b|\btitle\s+sheet\b|\bcover\s+sheet\b",
    re.IGNORECASE,
)


VISION_SYSTEM = """You are an expert architectural plan reviewer. You are looking at one
sheet from an architectural/engineering plan set — most likely the title
sheet, which contains the project info and code data summary box.

Read the drawing and return the values shown for each field. If a field is
not legibly shown on this sheet, return null for that field — do NOT guess.

Return ONLY a JSON object, no prose, matching this exact schema:
{
  "project_name": "string or null",
  "project_address": "string or null (full street address as shown)",
  "city": "string or null",
  "state_code": "2-letter code or null",
  "occupancy_type": "string or null (e.g. R-3, B, A-2, M)",
  "construction_type": "string or null (e.g. V-B, II-A, I-A)",
  "building_height_ft": number_or_null,
  "building_area_sf": number_or_null,
  "stories": integer_or_null,
  "sprinklered": "yes|no|null",
  "applicable_codes": ["array of code names like '2022 CBC', '2021 IRC'"],
  "scope_of_work": "string or null (1 sentence)",
  "is_title_sheet": true_or_false
}

Use the exact occupancy and construction codes shown on the drawing. Do not
invent values. If the sheet is clearly NOT a title sheet (e.g. a site plan or
foundation plan with no code data), set is_title_sheet=false and most fields
to null."""


_RETRIABLE = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    asyncio.TimeoutError,
)


class VisionTitleSheetExtractor:
    """Renders candidate title-sheet pages and asks Claude vision to extract
    the structured fields the regex extractor misses."""

    # 150 DPI keeps title-block text legible on a 24x18 sheet (~2700x2000 px)
    # while staying well under the 5 MB per-image limit at JPEG q=80.
    RENDER_DPI = 150
    MAX_CANDIDATE_PAGES = 4   # cost cap: each vision call is ~$0.01-0.03
    PER_CALL_TIMEOUT = 90     # vision calls run ~2x longer than text-only

    def __init__(self):
        self._client: Optional[anthropic.AsyncAnthropic] = None
        self.last_error: Optional[str] = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    def pick_title_sheet_pages(self, raw_pages: Dict[int, str]) -> List[int]:
        """Score each page by how many title-sheet keywords it contains, return
        the top N. Page 1 is always included if not already in the list — many
        architects do put the code data summary on page 1 even when later
        sheets also mention codes."""
        scored: List[tuple] = []
        for pg, text in raw_pages.items():
            low = (text or "").lower()
            hits = sum(1 for kw in TITLE_SHEET_KEYWORDS if kw in low)
            # A title/cover/code sheet-number (T-1.0, G-0, CS-1, A0.0) is a
            # strong signal even on a sheet whose body text barely extracts.
            if _TITLE_SHEET_NUMBER.search(text or ""):
                hits += 3
            if hits > 0:
                scored.append((hits, pg))
        scored.sort(reverse=True)
        candidates = [pg for _, pg in scored[: self.MAX_CANDIDATE_PAGES]]
        if 1 in raw_pages and 1 not in candidates:
            candidates.insert(0, 1)
        return candidates[: self.MAX_CANDIDATE_PAGES] or [1]

    def _render_page_to_jpeg_b64(self, doc: fitz.Document, page_num_1based: int) -> Optional[str]:
        try:
            page = doc[page_num_1based - 1]
            pix = page.get_pixmap(dpi=self.RENDER_DPI)
            jpeg_bytes = pix.tobytes(output="jpeg", jpg_quality=80)
            return base64.standard_b64encode(jpeg_bytes).decode("ascii")
        except Exception as e:
            logger.warning(f"[vision] failed to render page {page_num_1based}: {e}")
            return None

    async def extract(self, file_path: str, raw_pages: Dict[int, str]) -> Dict[str, Any]:
        """Run vision extraction on the most likely title-sheet page(s).

        Returns the merged JSON schema documented in VISION_SYSTEM, or {} if
        vision could not run (no API key, all retries failed, no page
        renderable). Callers should treat every returned field as optional
        and only use it to fill values they don't already have.
        """
        if not settings.anthropic_api_key:
            self.last_error = "ANTHROPIC_API_KEY env var is empty on the server"
            logger.warning(f"[vision] {self.last_error} — skipping vision extraction")
            return {}

        try:
            doc = await asyncio.to_thread(fitz.open, file_path)
        except Exception as e:
            self.last_error = f"open failed: {e}"
            logger.warning(f"[vision] {self.last_error}")
            return {}

        candidates = self.pick_title_sheet_pages(raw_pages)
        logger.info(f"[vision] candidate title-sheet pages: {candidates}")

        merged: Dict[str, Any] = {}
        try:
            for pg in candidates:
                # Rasterizing a page at 150 DPI is blocking CPU work; keep it
                # off the event loop so the loop can serve progress/health.
                b64 = await asyncio.to_thread(self._render_page_to_jpeg_b64, doc, pg)
                if not b64:
                    continue
                result = await self._call_vision(b64, pg)
                if not result:
                    continue
                self._merge(merged, result)
                # Early-exit: once one page returns is_title_sheet=true AND
                # both occupancy + construction, additional pages are pure
                # spend — they won't add anything the workflow uses.
                if (
                    result.get("is_title_sheet")
                    and result.get("occupancy_type")
                    and result.get("construction_type")
                ):
                    logger.info(f"[vision] page {pg} produced full code-data summary — stopping early")
                    break
        finally:
            doc.close()

        return merged

    @staticmethod
    def _merge(into: Dict[str, Any], src: Dict[str, Any]) -> None:
        """Fill any field that's still missing in `into` with a non-null value
        from `src`. First non-null value wins — don't overwrite existing
        answers from an earlier (likely better) page."""
        for k, v in src.items():
            if v in (None, "", []):
                continue
            if into.get(k) in (None, "", []):
                into[k] = v

    async def _call_vision(self, b64: str, page_num: int) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            },
            {
                "type": "text",
                "text": (
                    f"This is page {page_num} of the plan set. Read the "
                    "fields per the system prompt and return JSON only."
                ),
            },
        ]
        for attempt in range(2):
            try:
                resp = await asyncio.wait_for(
                    client.messages.create(
                        # Sonnet handles vision fine and is ~5x cheaper than Opus.
                        # The cost cap matters because every job hits this path.
                        model=settings.anthropic_model_cheap,
                        system=VISION_SYSTEM,
                        messages=[{"role": "user", "content": content}],
                        max_tokens=1024,
                    ),
                    timeout=self.PER_CALL_TIMEOUT,
                )
                self.last_error = None
                text = resp.content[0].text if resp.content else ""
                return self._parse_json(text)
            except _RETRIABLE as e:
                logger.warning(
                    f"[vision] transient on page {page_num} attempt {attempt + 1}: "
                    f"{type(e).__name__}: {e}"
                )
                if attempt == 1:
                    self.last_error = f"{type(e).__name__}: {e}"
                continue
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.error(f"[vision] non-retriable on page {page_num}: {self.last_error}")
                return None
        return None

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None


vision_title_extractor = VisionTitleSheetExtractor()
