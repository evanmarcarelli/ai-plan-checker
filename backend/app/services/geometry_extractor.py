"""Geometry extraction from the PDF drawing vector layer.

Net-new pipeline (feature-flagged via GEOMETRY_EXTRACTION_ENABLED). Where the
surveyor has always parsed dimensions out of *text labels*, this service reads the
actual drawn geometry. What it produces:

  • per-page routing (vector vs raster) and a primitive census;
  • the calibrated drawing scale, parsed from the printed scale note (the reliable
    anchor on real sets) and back-filled into ExtractedPlanData.scale;
  • a positioned, real-unit catalog of the architect's stated dimensions;
  • clear distances measured face-to-face between gray-filled (poché) walls —
    `gray_wall_rects_display` + `measure_region_clear` — used by geometry_vision.

OCG layer names are read where present and used as a routing signal, but on real
exports they are often flattened, so wall identification relies on gray FILL, not
layers. Design mirrors textract_extractor / vision_extractor: a module-level
singleton with an `enabled` property and graceful degradation (any failure logs
and returns what it has). Costs $0 and changes nothing when the flag is off.
"""

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple, Any

import fitz  # PyMuPDF
import numpy as np

from app.config import settings
from app.models.schemas import GeometryData, PageGeometry, SheetScale
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Layer (OCG) role classification ─────────────────────────────────────────
# AIA CAD layer names encode a discipline prefix (A-/S-/M-/E-/G-) and a major
# group (WALL, ANNO, DIM, AREA, ...). We only need a coarse role: which paths are
# walls (measurable structure), which are dimension annotations (scale signal),
# and which are noise to drop (hatch/solid fills/poché). Substring match is
# deliberate — real names are messy ("S-Wall", "Wall- new", "A-ANNO-DIM-1_4").
# ORDER MATTERS: check DIM before ANNO ("JRN-DIMS" is a dimension, not generic anno).

_ROLE_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("dim",    ("DIM",)),
    ("hatch",  ("HATCH", "SOLID FILL", "POCHE", "FILL PATTERN")),
    ("wall",   ("WALL",)),
    ("area",   ("AREA",)),
    ("anno",   ("ANNO", "TEXT", "NOTE", "SYMB", "TITL", "TTLB", "TITLE BLOCK", "DETL")),
]

# Roles whose presence means "this page carries recognized, measurable CAD layers"
# — used by the per-page router to tag a page `vector_layered`. Generic
# dumping-ground layers (0, P, T, H, CAD_DEFAULT_LAYER, PDFn_Geometry) → "other".
_RECOGNIZED_GEOM_ROLES = {"wall", "dim", "area"}


def classify_layer(name: Optional[str]) -> str:
    """Map an OCG layer name to a coarse role.

    Returns one of: wall | dim | area | hatch | anno | other.
    None / unknown / generic names → "other".
    """
    if not name:
        return "other"
    upper = name.upper()
    for role, needles in _ROLE_RULES:
        if any(n in upper for n in needles):
            return role
    return "other"


def read_layers(doc: "fitz.Document") -> List[str]:
    """All OCG (optional content group) layer names declared in the document.

    Empty list when the PDF has no layers (flattened / scanned export), which is
    itself a useful signal: no layers → wall-ID must fall back to vision (Phase D).
    """
    try:
        ocgs = doc.get_ocgs() or {}
    except Exception as e:  # older/edge PDFs
        logger.warning(f"[geometry] get_ocgs failed: {e}")
        return []
    names = {info.get("name") for info in ocgs.values() if isinstance(info, dict)}
    return sorted(n for n in names if n)


# ── Dimension-token parsing (Phase A) ───────────────────────────────────────
# CAD PDFs print dimensions with typographic glyphs: prime ′ (U+2032), double-
# prime ″ (U+2033), Unicode minus − (U+2212) — NOT ASCII ' " -. Handle both, plus
# decimal-feet survey notation (170.00') and fractional inches (6 1/2").
_FT = r"['′]"
_IN = r'["″]'
_DASH = r"[-−]"
# Order matters — try the richest forms first.
_DIM_PATTERNS = [
    # feet-dash-inches(-fraction):  10'-6"   12'-6 1/2"   10′−6″
    re.compile(rf"^(\d+){_FT}{_DASH}(\d{{1,2}})(?:\s+(\d+)/(\d+))?{_IN}?$"),
    # decimal feet:  170.00'  50'  12.5′
    re.compile(rf"^(\d+(?:\.\d+)?){_FT}$"),
    # inches(-fraction) only:  44"   6 1/2″
    re.compile(rf"^(\d{{1,3}})(?:\s+(\d+)/(\d+))?{_IN}$"),
]


def parse_dimension_to_inches(token: str) -> Optional[float]:
    """Parse an architectural dimension token to inches, or None if it isn't one."""
    s = (token or "").strip()
    if not s:
        return None
    m = _DIM_PATTERNS[0].match(s)
    if m:
        ft = int(m.group(1)); inch = int(m.group(2))
        frac = (int(m.group(3)) / int(m.group(4))) if m.group(3) and int(m.group(4)) else 0.0
        return ft * 12 + inch + frac
    m = _DIM_PATTERNS[1].match(s)
    if m:
        return float(m.group(1)) * 12.0
    m = _DIM_PATTERNS[2].match(s)
    if m:
        inch = int(m.group(1))
        frac = (int(m.group(2)) / int(m.group(3))) if m.group(2) and int(m.group(3)) else 0.0
        return inch + frac
    return None


# Scale note:  1/4"=1'-0"   3/8" = 1'   1"=20'   1:48   NTS
_SCALE_INCH_EQ_FT = re.compile(
    rf"(\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s*{_IN}?\s*=\s*(\d+(?:\.\d+)?){_FT}", re.I)
_SCALE_RATIO = re.compile(r"\b1\s*:\s*(\d{1,4})\b")


def _to_float(num: str) -> float:
    if "/" in num:
        a, b = num.split("/")
        denom = float(b)
        return float(a) / denom if denom else 0.0
    return float(num)


def parse_scale_note(text: str) -> Optional[Tuple[str, float, float]]:
    """Find a drawing-scale note in page text.

    Returns (scale_text, points_per_foot, confidence) or None.
    points_per_foot converts a drawn length in PDF points to real feet:
      "1/4\"=1'"  → 0.25in * 72 / 1ft = 18 pt/ft
      "1:48"      → 864 / 48           = 18 pt/ft
    """
    if not text:
        return None
    m = _SCALE_INCH_EQ_FT.search(text)
    if m:
        paper_in = _to_float(m.group(1))
        real_ft = float(m.group(2))
        if paper_in > 0 and real_ft > 0:
            return (m.group(0).strip(), paper_in * 72.0 / real_ft, 0.9)
    m = _SCALE_RATIO.search(text)
    if m:
        n = int(m.group(1))
        if n > 0:
            return (f"1:{n}", 864.0 / n, 0.75)
    return None


def _explode_segments(drawings: list) -> list:
    """Flatten get_drawings() paths into straight segments as
    (x0,y0,x1,y1,length_pts,role). Curves ('c') are skipped here — door swing
    arcs are handled in Phase C. Coordinates are in unrotated page space."""
    segs = []
    for d in drawings:
        role = classify_layer(d.get("layer"))
        for it in d.get("items", []):
            op = it[0]
            if op == "l":
                p1, p2 = it[1], it[2]
                segs.append((p1.x, p1.y, p2.x, p2.y,
                             ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5, role))
            elif op == "re":
                r = it[1]
                corners = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                for i in range(4):
                    (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
                    segs.append((ax, ay, bx, by,
                                 ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5, role))
            elif op == "qu":
                q = it[1]
                pts = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
                for i in range(4):
                    (ax, ay), (bx, by) = pts[i], pts[(i + 1) % 4]
                    segs.append((ax, ay, bx, by,
                                 ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5, role))
    return segs


def harvest_dimension_tokens(page: "fitz.Page") -> List[Dict[str, Any]]:
    """Dimension-value tokens with positions: {text, inches, cx, cy}.
    cx/cy are the token center in the SAME space as get_drawings(): empirically
    (verified on rotated sheets) get_text("words") and get_drawings() both report
    unrotated page coordinates, so NO derotation is applied — derotating here
    pushed tokens off-page (negative coords) and broke token↔segment association."""
    out: List[Dict[str, Any]] = []
    for w in page.get_text("words"):
        inches = parse_dimension_to_inches(w[4])
        if inches is None:
            continue
        out.append({"text": w[4], "inches": inches,
                    "cx": (w[0] + w[2]) / 2, "cy": (w[1] + w[3]) / 2})
    return out


def gray_wall_rects_display(page: "fitz.Page", gray_lo: float = 0.3,
                            gray_hi: float = 0.75) -> np.ndarray:
    """Wall rectangles in DISPLAY space, identified by GRAY FILL.

    Architectural floor plans poché walls with a solid gray fill (≈0.5) — in the
    vector data this is distinct from black (0.0) annotation strokes, giving a
    LAYER-INDEPENDENT way to find walls (verified sub-¼-inch accurate vs labels).
    Returns an (N,4) numpy array of (x0,y0,x1,y1) in display points — the
    orientation a rendered page (and Claude vision) sees. Empty array if none."""
    rot = page.rotation_matrix
    out = []
    for d in page.get_drawings():
        f = d.get("fill")
        # Near-neutral gray only: test BOTH the mean (in the poché band) AND a low
        # channel spread, so saturated fills whose mean lands in range — pure blue
        # (0,0,1)→0.33, yellow (1,1,0)→0.67 — are not mistaken for walls.
        if (d.get("type") in ("f", "fs") and f
                and gray_lo <= sum(f) / len(f) <= gray_hi
                and max(f) - min(f) <= 0.1):
            r = d.get("rect")
            if not r:
                continue
            rd = r * rot
            x0, x1 = sorted((rd.x0, rd.x1)); y0, y1 = sorted((rd.y0, rd.y1))
            out.append((x0, y0, x1, y1))
    return np.asarray(out) if out else np.empty((0, 4))


def _wall_clusters(walls: np.ndarray, axis: str, cx: float, cy: float,
                   band_lo: float, band_hi: float, thin_max: float = 30.0,
                   min_run: float = 20.0, merge: float = 8.0) -> list:
    """Wall faces crossing the measurement line, clustered (a single wall is often
    drawn as several adjacent gray rects). Returns sorted [(center, lo_face,
    hi_face)] along the measurement axis. `axis='V'` measures horizontally (uses
    vertical walls crossing y=cy); `axis='H'` measures vertically."""
    x0, y0, x1, y1 = walls[:, 0], walls[:, 1], walls[:, 2], walls[:, 3]
    wx = x1 - x0; wy = y1 - y0
    if axis == "V":   # vertical walls (thin in x, long in y) crossing y=cy
        m = (wx <= thin_max) & (wy >= min_run) & (y0 <= cy) & (y1 >= cy) & (x1 >= band_lo) & (x0 <= band_hi)
        cen = (x0[m] + x1[m]) / 2; lo = x0[m]; hi = x1[m]
    else:             # horizontal walls (thin in y, long in x) crossing x=cx
        m = (wy <= thin_max) & (wx >= min_run) & (x0 <= cx) & (x1 >= cx) & (y1 >= band_lo) & (y0 <= band_hi)
        cen = (y0[m] + y1[m]) / 2; lo = y0[m]; hi = y1[m]
    if cen.size == 0:
        return []
    order = np.argsort(cen); cen, lo, hi = cen[order], lo[order], hi[order]
    clusters: list = []
    for c, l, h in zip(cen, lo, hi):
        if clusters and c - clusters[-1][0] < merge:
            a = clusters[-1]
            clusters[-1] = ((a[0] + c) / 2, min(a[1], l), max(a[2], h))
        else:
            clusters.append((c, l, h))
    return clusters


def measure_region_clear(walls: np.ndarray, region: Tuple[float, float, float, float],
                         axis: str, ppf: float, pad: float = 24.0
                         ) -> Optional[Tuple[float, float, int]]:
    """Clear distance in FEET across a region, measured FACE-TO-FACE between the
    gray walls nearest the region's two edges. `axis='V'` → measure horizontal
    width; `axis='H'` → measure vertical height. All coords in DISPLAY points (the
    space `gray_wall_rects_display` returns, and a vision pixel box × 72/dpi).

    Returns (clear_ft, confidence, interior_wall_count) or None. Confidence is high
    (0.9) when the region is bracketed cleanly and LOW (0.4) when an interior wall
    sits between the brackets (an ambiguous region — honestly advisory under the
    Hybrid gate rather than a silently-wrong number).

    This is the geometry half of vision-guided measurement: vision supplies WHERE +
    which axis (semantics); this supplies the precise wall-to-wall distance
    (precision) — verified sub-¼-inch vs labels on gray-walled floor plans."""
    if walls is None or len(walls) == 0 or ppf <= 0 or axis not in ("H", "V"):
        return None
    rx0, ry0, rx1, ry1 = region
    cx = (rx0 + rx1) / 2; cy = (ry0 + ry1) / 2
    if axis == "V":
        clusters = _wall_clusters(walls, axis, cx, cy, rx0 - pad, rx1 + pad)
        edge_lo, edge_hi = rx0, rx1
    else:
        clusters = _wall_clusters(walls, axis, cx, cy, ry0 - pad, ry1 + pad)
        edge_lo, edge_hi = ry0, ry1
    if len(clusters) < 2:
        return None
    left = min(clusters, key=lambda c: abs(c[0] - edge_lo))
    right = min(clusters, key=lambda c: abs(c[0] - edge_hi))
    if right[0] <= left[0]:
        return None
    interior = [c for c in clusters if left[0] + 8 < c[0] < right[0] - 8]
    clear = (right[1] - left[2]) / ppf   # right wall's near face − left wall's near face
    if clear <= 0:
        return None
    confidence = 0.9 if not interior else 0.4
    return (round(clear, 2), confidence, len(interior))


def corroborate_scale(tokens: List[Dict[str, Any]], segs: list, ppf: float,
                      min_inches: float = 24.0, max_assoc_pts: float = 120.0,
                      len_tol: float = 0.12) -> Tuple[int, int]:
    """Self-consistency check, NOT a scale estimator. Given a candidate
    points_per_foot, count how many LINEAR-DIMENSION tokens have a nearby segment
    whose drawn length matches the token's stated value (stated_feet * ppf, within
    len_tol). A token is "corroborated" if the drawing agrees with its own label
    under this scale. Returns (corroborated, checked).

    Only tokens >= min_inches are checked: small inch-only tokens are usually
    spacing/hardware notes ("16\" O.C.") with no dimension line, which depress the
    rate without measuring scale. On real sheets, clean dimension sheets corroborate
    50-100%; misses are dimension strings drawn as split segments (a Phase-C
    span-matching problem, not a scale error).

    Robust to tick/extension-line noise: checks for the EXISTENCE of a
    matching-length segment near the token, not the single nearest segment (usually
    a 7pt tick)."""
    if not tokens or not segs or ppf <= 0:
        return (0, 0)
    a = np.asarray([[(s[0] + s[2]) / 2, (s[1] + s[3]) / 2, s[4]] for s in segs], dtype=float)
    mx, my, lens = a[:, 0], a[:, 1], a[:, 2]
    keep = lens >= 18.0  # below ~1ft drawn — too short to be a real dimension line
    mx, my, lens = mx[keep], my[keep], lens[keep]
    if mx.size == 0:
        return (0, 0)
    corr = 0; checked = 0
    for t in tokens:
        if t["inches"] < min_inches:
            continue
        feet = t["inches"] / 12.0
        checked += 1
        target = feet * ppf
        near = (mx - t["cx"]) ** 2 + (my - t["cy"]) ** 2 <= max_assoc_pts ** 2
        if near.any() and (np.abs(lens[near] - target) <= len_tol * target).any():
            corr += 1
    return (corr, checked)


class GeometryExtractor:
    """Reads geometry from a plan-set PDF. Sync (fitz is sync); slotted into
    pdf_processor.extract() alongside the textract enhancement."""

    # A page with at least this many drawing paths is treated as vector content.
    VECTOR_MIN_PATHS = 50
    # Density at which we call vector_coverage saturated (rough heuristic only).
    VECTOR_SATURATION = 1000.0

    @property
    def enabled(self) -> bool:
        return bool(settings.geometry_extraction_enabled)

    def extract(self, file_path: str) -> Optional[GeometryData]:
        """Top-level entry. Returns a populated GeometryData, or None on failure
        / when the document yields nothing geometric."""
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            logger.error(f"[geometry] could not open {file_path}: {e}")
            return None

        try:
            layer_names = read_layers(doc)
            cap = settings.geometry_max_pages or doc.page_count
            pages: List[PageGeometry] = []
            for i in range(min(doc.page_count, cap)):
                try:
                    pages.append(self._page_geometry(doc[i], i + 1))
                except Exception as e:
                    logger.warning(f"[geometry] page {i + 1} failed (skipping): {e}")
                    pages.append(PageGeometry(page=i + 1, path="raster"))

            stats = self._summarize(pages, layer_names)
            dominant = self._dominant_scale(pages)
            # Plausibility guard: a page whose scale deviates sharply from the
            # document's dominant scale is suspect (e.g. a detail note "4\"=1'"
            # that may be a text-mangled "1/4\""). Downgrade its confidence so it
            # can NEVER silently drive a wrong measurement — the worst failure mode.
            if dominant and dominant.points_per_foot:
                dom = dominant.points_per_foot
                for p in pages:
                    s = p.scale
                    if s and s.points_per_foot and abs(s.points_per_foot - dom) / dom > 0.5:
                        s.confidence = min(s.confidence, 0.3)
                        s.source = (s.source or "note") + ":off-dominant"
            stats["scaled_pages"] = sum(1 for p in pages if p.scale and p.scale.points_per_foot)
            logger.info(
                f"[geometry] {file_path}: {stats['pages']} pages, "
                f"{len(layer_names)} layers, routing={stats['routing']}, "
                f"scaled={stats['scaled_pages']}, "
                f"dominant_scale={dominant.scale_text if dominant else None}"
            )
            return GeometryData(pages=pages, layers=layer_names,
                                dominant_scale=dominant, stats=stats)
        except Exception as e:
            logger.error(f"[geometry] extraction failed: {e}")
            return None
        finally:
            doc.close()

    # ── Phase 0: per-page routing + primitive census ────────────────────────
    def _page_geometry(self, page: "fitz.Page", page_num: int) -> PageGeometry:
        drawings = page.get_drawings()
        ndraw = len(drawings)

        # Census primitives by drawing type and by layer role.
        by_role: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for d in drawings:
            role = classify_layer(d.get("layer"))
            by_role[role] = by_role.get(role, 0) + 1
            t = d.get("type") or "?"        # 'f' fill, 's' stroke, 'fs' both
            by_type[t] = by_type.get(t, 0) + 1

        # Image-block census (raster detector): a scanned sheet is ~0 drawings +
        # one big image block; a vector sheet may still embed small logos/photos.
        img_blocks = 0
        try:
            raw = page.get_text("rawdict")
            img_blocks = sum(1 for b in raw.get("blocks", []) if b.get("type") == 1)
        except Exception:
            pass

        has_geom_layers = any(by_role.get(r, 0) > 0 for r in _RECOGNIZED_GEOM_ROLES)
        if ndraw < self.VECTOR_MIN_PATHS and img_blocks > 0:
            path = "raster"
        elif has_geom_layers:
            path = "vector_layered"
        else:
            path = "vector_unlayered"

        counts = {f"role:{k}": v for k, v in by_role.items()}
        counts.update({f"type:{k}": v for k, v in by_type.items()})
        counts["total"] = ndraw
        counts["image_blocks"] = img_blocks

        pg = PageGeometry(
            page=page_num,
            path=path,
            vector_coverage=min(1.0, ndraw / self.VECTOR_SATURATION),
            primitive_counts=counts,
        )

        # ── Phase A/B: dimension harvest + scale calibration (layer-independent) ──
        if path != "raster":
            try:
                text = page.get_text("text")
                tokens = harvest_dimension_tokens(page)
                pg.measured_features["dimension_token_count"] = len(tokens)
                # Positioned dimension catalog in real units — genuine new data for
                # the reviewers (the architect's own stated dimensions, parsed and
                # deduped). Distinct values, capped to bound persistence size.
                pg.measured_features["stated_dimensions_in"] = sorted(
                    {round(t["inches"], 2) for t in tokens})[:80]
                pg.scale = self._calibrate(page_num, text)
            except Exception as e:
                logger.warning(f"[geometry] page {page_num} scale/harvest failed: {e}")
        return pg

    def _calibrate(self, page_num: int, text: str) -> Optional[SheetScale]:
        """Calibrate the sheet scale from the printed scale note — the authoritative
        anchor (verified reliable on real sets). Returns None when no note is
        present; we don't fabricate a scale from geometry alone (naive
        dimension-line association is too noisy to trust as an estimator — the
        self-consistency check `corroborate_scale` is used for validation only)."""
        note = parse_scale_note(text)
        if not note:
            return None
        scale_text, ppf, base_conf = note
        return SheetScale(page=page_num, scale_text=scale_text, points_per_foot=ppf,
                          source="note", confidence=round(base_conf, 2))

    @staticmethod
    def _dominant_scale(pages: List[PageGeometry]) -> Optional[SheetScale]:
        """The plan-set's prevailing scale: the most common points_per_foot among
        confidently-scaled pages (most architectural sheets share one scale)."""
        votes = Counter()
        rep: Dict[float, SheetScale] = {}
        for p in pages:
            s = p.scale
            if s and s.points_per_foot and s.confidence >= 0.6:
                key = round(s.points_per_foot, 1)
                votes[key] += 1
                rep.setdefault(key, s)
        if not votes:
            return None
        best = votes.most_common(1)[0][0]
        return rep[best]

    @staticmethod
    def _summarize(pages: List[PageGeometry], layer_names: List[str]) -> Dict[str, Any]:
        routing: Dict[str, int] = {}
        for p in pages:
            routing[p.path] = routing.get(p.path, 0) + 1
        return {
            "pages": len(pages),
            "layer_count": len(layer_names),
            "routing": routing,
            "vector_layered_pages": routing.get("vector_layered", 0),
        }


geometry_extractor = GeometryExtractor()
