"""Vision-guided geometry measurement (Phase D).

Deterministic geometry can measure precisely between walls but can't reliably tell
WHICH gap is the corridor / WHICH opening is the egress door on a cluttered floor
plan (interior partitions, fixtures, and dimension lines all look similar). This
module closes that gap with a division of labor:

  • Claude vision supplies the SEMANTICS — it looks at the rendered sheet and
    returns each measurable feature (corridor, egress door, room) as an image-pixel
    bounding box + which axis to measure. Vision is good at "that is the corridor."
  • The geometry supplies the PRECISION — `measure_region_clear` measures the exact
    face-to-face distance between the gray-filled walls in that region (verified
    sub-¼-inch vs labels). Geometry is good at "the gap is 3.71 ft."

Advisory by design (never an automatic permit failure): every measurement carries a
confidence, and ambiguous regions self-report low. Feature-flagged
(GEOMETRY_VISION_ENABLED, requires GEOMETRY_EXTRACTION_ENABLED + an API key) and a
clean no-op otherwise — it reuses vision_extractor's render/retry/parse pattern.

NOTE: the live vision call is untestable without ANTHROPIC_API_KEY; the coordinate
round-trip (verified exact) and the measurement half are testable and tested.
"""

import asyncio
import base64
import json
import re
from typing import Any, Dict, List, Optional

import anthropic
import fitz  # PyMuPDF

from app.config import settings
from app.models.schemas import ExtractedPlanData
from app.services.geometry_extractor import gray_wall_rects_display, measure_region_clear
from app.utils.logger import get_logger

logger = get_logger(__name__)


VISION_MEASURE_SYSTEM = """You are an expert architectural plan reviewer looking at ONE rendered
sheet from a building plan set. Your job is to locate code-relevant features that
should be MEASURED, so a downstream geometry tool can measure them precisely.

Only identify features you can clearly see on THIS sheet. If the sheet is not a
floor plan (e.g. an elevation, section, schedule, or notes page), return an empty
features list.

For each feature, give its bounding box as NORMALIZED coordinates [x0,y0,x1,y1] —
each value a fraction from 0.0 to 1.0 of the image (x = left→right, y = top→bottom,
origin = top-left). Normalized values are REQUIRED so the box stays correct no
matter how the image is scaled. Also give the axis to measure:
  - "width"  → measure the HORIZONTAL clear distance across the box
  - "height" → measure the VERTICAL clear distance across the box
Draw the box tight to the two walls/faces whose distance matters (e.g. for a
corridor, the two walls that bound its width).

Return ONLY a JSON object, no prose:
{
  "is_floor_plan": true_or_false,
  "features": [
    {
      "type": "corridor | egress_door | room | clearance",
      "label": "short human label, e.g. 'main hallway' or 'bedroom 2 door'",
      "bbox": [x0, y0, x1, y1],
      "measure_axis": "width | height",
      "code_note": "1 short phrase on why it matters, or null"
    }
  ]
}
All four bbox values must be between 0.0 and 1.0.

Do NOT estimate dimensions yourself — only locate. Prefer egress paths, corridors,
and door openings (the dimensions that drive code compliance)."""


_RETRIABLE = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    asyncio.TimeoutError,
)


class GeometryVisionMeasurer:
    """Renders vector floor-plan pages, asks vision to locate measurable features,
    then measures each precisely against the gray-wall geometry."""

    MAX_PAGES = 6             # cost cap — each page is one vision call
    PER_CALL_TIMEOUT = 90
    MIN_SCALE_CONF = 0.6      # don't measure on a page whose scale we don't trust

    def __init__(self):
        self._client: Optional[anthropic.AsyncAnthropic] = None
        self.last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(
            settings.geometry_extraction_enabled
            and settings.geometry_vision_enabled
            and settings.anthropic_api_key
        )

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def augment(self, file_path: str, plan_data: ExtractedPlanData) -> None:
        """Measure vision-located features and attach the results (advisory) to
        plan_data.geometry. No-op when disabled, no geometry, or no API key."""
        if not self.enabled or plan_data.geometry is None:
            return
        try:
            doc = await asyncio.to_thread(fitz.open, file_path)
        except Exception as e:
            self.last_error = f"open failed: {e}"
            logger.warning(f"[geomvision] {self.last_error}")
            return

        try:
            pages = self._candidate_pages(plan_data.geometry)
            logger.info(f"[geomvision] measuring {len(pages)} candidate page(s): {pages}")
            all_measurements: List[Dict[str, Any]] = []
            for pno in pages:
                # Per-page guard: a malformed page must not break the survey — this
                # is advisory enrichment. Mirrors extractor.extract's degradation.
                try:
                    pg_geo = next((p for p in plan_data.geometry.pages if p.page == pno), None)
                    if pg_geo is None or pg_geo.scale is None or not pg_geo.scale.points_per_foot:
                        continue
                    measured = await self._measure_page(doc, pno, pg_geo.scale.points_per_foot)
                    if measured:
                        pg_geo.advisory["vision_measurements"] = measured
                        all_measurements.extend(measured)
                except Exception as e:
                    self.last_error = f"{type(e).__name__}: {e}"
                    logger.warning(f"[geomvision] page {pno} measurement failed (skipping): {e}")
            if all_measurements:
                self._mirror_summary(plan_data, all_measurements)
        finally:
            doc.close()

    def _candidate_pages(self, geometry) -> List[int]:
        """Vector pages with a trustworthy scale, most-wall-dense first (likely the
        real floor plans), capped for cost."""
        scored = []
        for p in geometry.pages:
            if p.path == "raster" or p.scale is None or p.scale.confidence < self.MIN_SCALE_CONF:
                continue
            density = p.primitive_counts.get("total", 0)   # wall-dense ≈ a real plan
            scored.append((density, p.page))
        scored.sort(reverse=True)
        return [pg for _, pg in scored[: self.MAX_PAGES]]

    async def _measure_page(self, doc: "fitz.Document", page_num: int,
                            ppf: float) -> List[Dict[str, Any]]:
        page = doc[page_num - 1]
        b64 = await asyncio.to_thread(self._render_jpeg_b64, page, page_num)
        if not b64:
            return []
        result = await self._call_vision(b64, page_num)
        if not result or not result.get("is_floor_plan"):
            return []
        walls = await asyncio.to_thread(gray_wall_rects_display, page)
        if walls is None or len(walls) == 0:
            return []
        out: List[Dict[str, Any]] = []
        disp_w, disp_h = page.rect.width, page.rect.height   # display-space dims
        for feat in result.get("features", []):
            bbox = feat.get("bbox")
            axis = {"width": "V", "height": "H"}.get(feat.get("measure_axis"))
            if not bbox or len(bbox) != 4 or axis is None:
                continue
            try:
                nx0, ny0, nx1, ny1 = (float(v) for v in bbox)
            except (TypeError, ValueError):
                continue
            # Normalized [0..1] → display points. Robust to any server-side image
            # resize: the model reports in the frame it sees, whatever the pixels.
            region = (nx0 * disp_w, ny0 * disp_h, nx1 * disp_w, ny1 * disp_h)
            m = measure_region_clear(walls, region, axis, ppf)
            if m is None:
                continue
            clear_ft, conf, interior = m
            out.append({
                "page": page_num,
                "type": feat.get("type"),
                "label": feat.get("label"),
                "measured_ft": clear_ft,
                "measured_in": round(clear_ft * 12, 1),
                "confidence": conf,
                "interior_walls": interior,
                "code_note": feat.get("code_note"),
                "source": "vision+geometry",
            })
        logger.info(f"[geomvision] page {page_num}: {len(out)} feature(s) measured")
        return out

    def _render_jpeg_b64(self, page: "fitz.Page", page_num: int) -> Optional[str]:
        try:
            # Size the render so the long edge ≈ geometry_vision_max_px, just under
            # Anthropic's image-resize threshold — so the model perceives exactly
            # what we render and the normalized boxes it returns stay accurate.
            long_pt = max(page.rect.width, page.rect.height) or 1.0
            zoom = settings.geometry_vision_max_px / long_pt
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            return base64.standard_b64encode(
                pix.tobytes(output="jpeg", jpg_quality=80)
            ).decode("ascii")
        except Exception as e:
            logger.warning(f"[geomvision] render failed p{page_num}: {e}")
            return None

    async def _call_vision(self, b64: str, page_num: int) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text",
             "text": f"This is page {page_num}. Locate measurable code-relevant "
                     "features per the system prompt. Return JSON only."},
        ]
        for attempt in range(2):
            try:
                resp = await asyncio.wait_for(
                    client.messages.create(
                        model=settings.anthropic_model_cheap,   # Sonnet — vision-capable, cheap
                        system=VISION_MEASURE_SYSTEM,
                        messages=[{"role": "user", "content": content}],
                        max_tokens=1500,
                    ),
                    timeout=self.PER_CALL_TIMEOUT,
                )
                self.last_error = None
                text = resp.content[0].text if resp.content else ""
                return self._parse_json(text)
            except _RETRIABLE as e:
                logger.warning(f"[geomvision] transient p{page_num} attempt {attempt+1}: "
                               f"{type(e).__name__}: {e}")
                if attempt == 1:
                    self.last_error = f"{type(e).__name__}: {e}"
                continue
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.error(f"[geomvision] non-retriable p{page_num}: {self.last_error}")
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

    @staticmethod
    def _mirror_summary(plan_data: ExtractedPlanData, measurements: List[Dict[str, Any]]) -> None:
        """Surface high-confidence vision-measured features to the reviewers via the
        dimensions dict (auto-included in the reviewer prompt). Advisory tag is kept."""
        hi = [m for m in measurements if m["confidence"] >= 0.7]
        plan_data.dimensions["vision_measured_features"] = [
            {"type": m["type"], "label": m["label"], "measured_in": m["measured_in"],
             "confidence": m["confidence"]}
            for m in (hi or measurements)[:20]
        ]


geometry_vision_measurer = GeometryVisionMeasurer()
