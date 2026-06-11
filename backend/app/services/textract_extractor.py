"""AWS Textract OCR fallback for image-only / scan-heavy plan sheets.

Architecture: this is the middle tier between PyMuPDF (fast/free text-layer
extraction) and Claude vision (smart but expensive). Specifically:

    PyMuPDF text layer  →  TextractExtractor (this module)  →  Claude vision

For each page, if PyMuPDF returns fewer than `textract_min_chars_per_page`
characters of text we render that page to PNG and ship it to Textract's
sync `analyze_document` with TABLES + FORMS feature types. The result:

  - LINE text concatenated back into the page-text dict (closes the gap
    pdf_processor.py opens on scanned title sheets).
  - Key-value pairs from the code-data-summary table extracted as a
    `code_data_summary` dict that the surveyor agent can use directly.

We use the sync per-image API (`analyze_document`) instead of the
async multi-page PDF API (`start_document_analysis`) on purpose:

  - No S3 dependency. The async path requires uploading the PDF to S3,
    polling SNS or the job-status endpoint, and downloading paginated
    results. Operational overhead for a marginal latency win.
  - One Textract call per page = clean per-page cost accounting and
    easy retry on transient failures.
  - The page-level rate limit is per-account, not per-call — so 25
    sequential calls on a 25-page doc is fine.

Feature-flagged off by default. Costs $0 when disabled, and $0 per plan
whose PyMuPDF text layer extracts cleanly.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Render DPI. 200 is the documented Textract sweet spot — high enough to
# resolve dimension text on architectural sheets, low enough that one PNG
# stays under the 10MB single-page sync-API ceiling for normal sheet sizes.
RENDER_DPI = 200

# Single-image upper bound for the sync API. If a rendered page exceeds this,
# we drop to 150 DPI and retry once before giving up on that page.
TEXTRACT_SYNC_MAX_BYTES = 10 * 1024 * 1024


class TextractExtractor:
    """OCR fallback layer for pages PyMuPDF couldn't read.

    Public surface mirrors the rest of the extraction stack:
      `enhance(pages_text, file_path) -> {"pages": dict, "code_data_summary": dict}`
    """

    def __init__(self) -> None:
        self._client = None  # lazy-built so import never fails when AWS deps missing
        self._init_error: Optional[str] = None

    # ─────────────────────────────────────────────────────────────────
    # Lazy client init
    # ─────────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(settings.aws_textract_enabled and settings.aws_access_key_id)

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._init_error:
            return None
        try:
            import boto3  # noqa: WPS433 — lazy import, optional dep
        except ImportError as e:
            self._init_error = (
                f"boto3 not installed: {e}. Add 'boto3' to requirements.txt "
                "and rebuild the image, or unset AWS_TEXTRACT_ENABLED."
            )
            logger.error(f"[textract] {self._init_error}")
            return None
        try:
            self._client = boto3.client(
                "textract",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
        except Exception as e:
            self._init_error = f"failed to build Textract client: {e}"
            logger.error(f"[textract] {self._init_error}")
            return None
        return self._client

    # ─────────────────────────────────────────────────────────────────
    # Public entry
    # ─────────────────────────────────────────────────────────────────

    def enhance(
        self,
        file_path: str,
        pages_text: Dict[int, str],
    ) -> Dict[str, Any]:
        """Run Textract on pages whose existing text-layer extraction looks
        too thin to trust, and return enriched text + code-data summary.

        Returns:
            {
                "pages":              { page_num: enriched_text },
                "code_data_summary":  { "occupancy": "...", "construction_type": "...", ... },
                "stats": {
                    "pages_attempted": int,
                    "pages_ocr_succeeded": int,
                    "kv_pairs_found":    int,
                },
            }
        Always safe to call — if Textract is disabled or unreachable, this
        returns the same `pages` dict you handed in plus an empty summary.
        """
        result: Dict[str, Any] = {
            "pages": dict(pages_text),
            "code_data_summary": {},
            "stats": {"pages_attempted": 0, "pages_ocr_succeeded": 0, "kv_pairs_found": 0},
        }

        if not self.enabled:
            return result

        client = self._get_client()
        if client is None:
            return result

        target_pages = self._pages_needing_ocr(pages_text)
        if not target_pages:
            logger.info(
                "[textract] every page passed the min-char threshold; skipping OCR"
            )
            return result

        # Open the doc once; we'll render each target page on demand.
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            logger.error(f"[textract] failed to open {file_path}: {e}")
            return result

        try:
            for page_num in target_pages:
                if page_num < 1 or page_num > len(doc):
                    continue
                result["stats"]["pages_attempted"] += 1
                png_bytes = self._render_page_png(doc, page_num - 1)
                if png_bytes is None:
                    continue
                ocr = self._call_textract(client, png_bytes)
                if ocr is None:
                    continue
                # Merge OCR text into the page (preserve original text first
                # so we never destroy a partial text layer — we add to it).
                merged = self._merge_text(result["pages"].get(page_num, ""), ocr["text"])
                result["pages"][page_num] = merged
                # First page that yields code-data KVs wins for each field;
                # the title sheet is the typical hit and we don't want a
                # later sheet's "OCCUPANCY: B" overriding it. But unlike the
                # old strict first-page-wins, (a) later pages still FILL
                # fields the first page didn't have, and (b) disagreements
                # between pages are recorded as kv_conflicts so the audit
                # trail shows the value was contested rather than certain.
                if ocr["kv_pairs"]:
                    normalized = self._normalize_kv_pairs(ocr["kv_pairs"])
                    summary = result["code_data_summary"]
                    conflicts = result["stats"].setdefault("kv_conflicts", {})
                    for field, value in normalized.items():
                        if field not in summary:
                            summary[field] = value
                        elif summary[field] != value:
                            conflicts.setdefault(field, [summary[field]]).append(value)
                    result["stats"]["kv_pairs_found"] = len(summary)
                result["stats"]["pages_ocr_succeeded"] += 1
        finally:
            doc.close()

        logger.info(
            f"[textract] OCR done — attempted={result['stats']['pages_attempted']} "
            f"succeeded={result['stats']['pages_ocr_succeeded']} "
            f"kvs={result['stats']['kv_pairs_found']}"
        )
        return result

    # ─────────────────────────────────────────────────────────────────
    # Page selection
    # ─────────────────────────────────────────────────────────────────

    def _pages_needing_ocr(self, pages_text: Dict[int, str]) -> List[int]:
        """Pages whose text layer is too thin to trust. `textract_max_pages=0`
        means no cap — every thin page goes through OCR."""
        threshold = settings.textract_min_chars_per_page
        thin = sorted(
            p for p, t in pages_text.items() if len((t or "").strip()) < threshold
        )
        cap = settings.textract_max_pages
        if cap and cap > 0:
            return thin[:cap]
        return thin

    # ─────────────────────────────────────────────────────────────────
    # PNG rendering
    # ─────────────────────────────────────────────────────────────────

    def _render_page_png(self, doc: fitz.Document, page_index: int) -> Optional[bytes]:
        """Render a single page to PNG bytes. Drops DPI on retry if the first
        render is too big for the sync API."""
        for dpi in (RENDER_DPI, 150):
            try:
                page = doc[page_index]
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                buf = io.BytesIO()
                buf.write(pix.tobytes("png"))
                data = buf.getvalue()
                if len(data) <= TEXTRACT_SYNC_MAX_BYTES:
                    return data
                logger.info(
                    f"[textract] page {page_index+1} too large at {dpi}dpi "
                    f"({len(data)/1e6:.1f}MB); retrying lower"
                )
            except Exception as e:
                logger.error(f"[textract] render failed page {page_index+1}: {e}")
                return None
        logger.warning(
            f"[textract] page {page_index+1} still oversized after retry; skipping"
        )
        return None

    # ─────────────────────────────────────────────────────────────────
    # Textract call + result shaping
    # ─────────────────────────────────────────────────────────────────

    def _call_textract(self, client, png_bytes: bytes) -> Optional[Dict[str, Any]]:
        """Single sync analyze_document call with TABLES + FORMS. Returns
        {"text": str, "kv_pairs": List[Tuple[str, str]]} or None on failure."""
        try:
            resp = client.analyze_document(
                Document={"Bytes": png_bytes},
                FeatureTypes=["TABLES", "FORMS"],
            )
        except Exception as e:
            # Specific Textract errors we want to recognize so the operator
            # can fix the right thing.
            msg = str(e)
            if "InvalidSignatureException" in msg or "UnrecognizedClientException" in msg:
                logger.error(
                    "[textract] AWS auth rejected — check AWS_ACCESS_KEY_ID + "
                    "AWS_SECRET_ACCESS_KEY in env and that the IAM user has "
                    "AmazonTextractFullAccess (or a scoped equivalent)."
                )
            elif "AccessDeniedException" in msg:
                logger.error(
                    "[textract] AccessDenied — IAM user lacks textract:AnalyzeDocument."
                )
            elif "ProvisionedThroughputExceededException" in msg or "ThrottlingException" in msg:
                logger.warning(f"[textract] throttled, skipping page: {msg}")
            else:
                logger.error(f"[textract] analyze_document failed: {e}")
            return None

        blocks = resp.get("Blocks") or []
        return {
            "text": self._concat_lines(blocks),
            "kv_pairs": self._extract_kv_pairs(blocks),
        }

    @staticmethod
    def _concat_lines(blocks: List[Dict[str, Any]]) -> str:
        """Concatenate every LINE block in reading order. Textract returns
        them in top-down/left-right order already."""
        lines = [b.get("Text", "") for b in blocks if b.get("BlockType") == "LINE"]
        return "\n".join(l for l in lines if l)

    @staticmethod
    def _extract_kv_pairs(blocks: List[Dict[str, Any]]) -> List:
        """Walk the KEY_VALUE_SET blocks and resolve each KEY → VALUE pair via
        the Relationships graph. Returns [(key, value), ...]."""
        by_id = {b["Id"]: b for b in blocks if "Id" in b}

        def _text_for(block_id: str) -> str:
            block = by_id.get(block_id)
            if not block:
                return ""
            words: List[str] = []
            for rel in block.get("Relationships", []) or []:
                if rel.get("Type") != "CHILD":
                    continue
                for cid in rel.get("Ids", []):
                    child = by_id.get(cid)
                    if child and child.get("BlockType") == "WORD":
                        w = child.get("Text", "")
                        if w:
                            words.append(w)
            return " ".join(words).strip()

        pairs: List = []
        for block in blocks:
            if block.get("BlockType") != "KEY_VALUE_SET":
                continue
            entity_types = block.get("EntityTypes") or []
            if "KEY" not in entity_types:
                continue
            key_text = _text_for(block["Id"])
            # Find the VALUE block via the KEY's relationships.
            value_text = ""
            for rel in block.get("Relationships", []) or []:
                if rel.get("Type") != "VALUE":
                    continue
                for vid in rel.get("Ids", []):
                    value_text = _text_for(vid)
                    if value_text:
                        break
            if key_text and value_text:
                pairs.append((key_text, value_text))
        return pairs

    # ─────────────────────────────────────────────────────────────────
    # Normalization helpers
    # ─────────────────────────────────────────────────────────────────

    _KEY_ALIASES: Dict[str, str] = {
        # Map every label variant we've seen on real title sheets to the
        # canonical surveyor field name.
        "occupancy": "occupancy",
        "occupancy classification": "occupancy",
        "occupancy class": "occupancy",
        "occupancy group": "occupancy",
        "construction type": "construction_type",
        "type of construction": "construction_type",
        "const. type": "construction_type",
        "const type": "construction_type",
        "building area": "building_area",
        "total area": "building_area",
        "total floor area": "building_area",
        "gross floor area": "building_area",
        "building height": "building_height",
        "max building height": "building_height",
        "maximum height": "building_height",
        "stories": "stories",
        "number of stories": "stories",
        "no. of stories": "stories",
        "project address": "project_address",
        "site address": "project_address",
        "address": "project_address",
        "project name": "project_name",
        "project": "project_name",
        "code edition": "code_edition",
        "applicable code": "code_edition",
        "applicable codes": "code_edition",
        "building code": "code_edition",
        "occupant load": "occupant_load",
    }

    def _normalize_kv_pairs(self, pairs: List) -> Dict[str, str]:
        """Collapse Textract KV pairs to the canonical surveyor field names.
        Unknown keys are dropped — we don't want to feed noise into the LLM
        context."""
        out: Dict[str, str] = {}
        for raw_key, raw_value in pairs:
            key = (raw_key or "").strip().rstrip(":").lower()
            value = (raw_value or "").strip()
            if not key or not value:
                continue
            canonical = self._KEY_ALIASES.get(key)
            if canonical is None:
                continue
            # First occurrence wins — title-sheet code-data box appears
            # first in reading order.
            if canonical not in out:
                out[canonical] = value
        return out

    # ─────────────────────────────────────────────────────────────────
    # Merge OCR text with existing page text
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_text(existing: str, ocr_text: str) -> str:
        """Combine without losing either. If existing is empty, OCR wins.
        Otherwise append OCR after a marker so a downstream regex that
        matched against the original text layer still works."""
        existing = (existing or "").strip()
        ocr_text = (ocr_text or "").strip()
        if not existing:
            return ocr_text
        if not ocr_text:
            return existing
        return f"{existing}\n\n--- OCR (Textract) ---\n{ocr_text}"


textract_extractor = TextractExtractor()
