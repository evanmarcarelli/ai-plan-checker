import fitz  # PyMuPDF
import pdfplumber
import hashlib
import re
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from app.models.schemas import ExtractedPlanData, PlanElement, PlanType
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PDFProcessor:
    """
    Extract text, metadata, and structural elements from PDF plan sets.
    Uses PyMuPDF for fast text extraction and pdfplumber for table/layout analysis.
    """

    def __init__(self):
        self.max_pages_for_full_extraction = 50

    def compute_file_hash(self, file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Main extraction entry point. Returns raw extracted data dict.
        """
        logger.info(f"Extracting PDF: {file_path}")
        result = {
            "file_path": file_path,
            "file_hash": self.compute_file_hash(file_path),
            "pages": {},
            "metadata": {},
            "title_block": None,
            "all_text": "",
            "page_count": 0,
        }

        try:
            doc = fitz.open(file_path)
            result["page_count"] = len(doc)
            result["metadata"] = dict(doc.metadata)

            all_texts = []
            for page_num in range(min(len(doc), self.max_pages_for_full_extraction)):
                page = doc[page_num]
                text = page.get_text("text")
                result["pages"][page_num + 1] = text
                all_texts.append(text)

            result["all_text"] = "\n\n".join(all_texts)

            # Extract title block from first or last page
            result["title_block"] = self._extract_title_block(doc)

            doc.close()

        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
            # Fallback to pdfplumber
            try:
                result.update(self._extract_with_pdfplumber(file_path))
            except Exception as e2:
                logger.error(f"pdfplumber extraction also failed: {e2}")

        return result

    def _extract_title_block(self, doc: fitz.Document) -> Optional[str]:
        """
        Title blocks are typically in the bottom-right corner of drawings.
        Check last page, first page, and page with largest text area.
        """
        title_block_texts = []

        # Check first 3 pages and last page
        pages_to_check = list(range(min(3, len(doc))))
        if len(doc) > 3:
            pages_to_check.append(len(doc) - 1)

        for page_num in pages_to_check:
            page = doc[page_num]
            rect = page.rect

            # Bottom-right quadrant (where title blocks usually live)
            bottom_right = fitz.Rect(
                rect.width * 0.5, rect.height * 0.6,
                rect.width, rect.height
            )

            blocks = page.get_text("blocks", clip=bottom_right)
            if blocks:
                block_text = " ".join([b[4] for b in blocks if len(b) > 4])
                if block_text.strip():
                    title_block_texts.append(block_text)

        return "\n---\n".join(title_block_texts) if title_block_texts else None

    def _extract_with_pdfplumber(self, file_path: str) -> Dict[str, Any]:
        result = {"pages": {}, "all_text": ""}
        with pdfplumber.open(file_path) as pdf:
            all_texts = []
            for i, page in enumerate(pdf.pages[:self.max_pages_for_full_extraction]):
                text = page.extract_text() or ""
                result["pages"][i + 1] = text
                all_texts.append(text)
            result["all_text"] = "\n\n".join(all_texts)
        return result

    def parse_plan_data(self, raw: Dict[str, Any]) -> ExtractedPlanData:
        """
        Parse raw extracted text into structured plan data.
        """
        all_text = raw.get("all_text", "")
        title_block = raw.get("title_block", "") or ""

        plan_data = ExtractedPlanData(
            raw_text_by_page=raw.get("pages", {}),
            title_block_text=title_block,
        )

        # Extract project info
        plan_data.project_name = self._extract_project_name(all_text, title_block)
        plan_data.project_address = self._extract_address(all_text, title_block)
        plan_data.plan_type = self._determine_plan_type(all_text)
        plan_data.architect = self._extract_professional(all_text, "architect")
        plan_data.engineer = self._extract_professional(all_text, "engineer")
        plan_data.occupancy_type = self._extract_occupancy(all_text)
        plan_data.construction_type = self._extract_construction_type(all_text)

        # Extract dimensions
        plan_data.dimensions = self._extract_dimensions(all_text)
        plan_data.building_height = plan_data.dimensions.get("building_height")
        plan_data.building_area = plan_data.dimensions.get("building_area")

        # Extract elements
        plan_data.elements = self._extract_elements(all_text)
        plan_data.materials = self._extract_materials(all_text)

        return plan_data

    def _extract_project_name(self, text: str, title_block: str) -> Optional[str]:
        patterns = [
            r'PROJECT(?:\s+NAME)?[:\s]+([^\n]{5,60})',
            r'(?:^|\n)([A-Z][A-Z\s]{4,50}(?:BUILDING|CENTER|PLAZA|TOWER|COMPLEX|FACILITY|RESIDENCE|OFFICE))',
        ]
        combined = title_block + "\n" + text
        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_address(self, text: str, title_block: str) -> Optional[str]:
        patterns = [
            r'(?:PROJECT\s+)?ADDRESS[:\s]+([^\n]{10,100})',
            r'(?:LOCATED\s+AT|SITE\s+ADDRESS)[:\s]+([^\n]{10,100})',
            r'\d+\s+[A-Z][a-z]+\s+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Way|Court|Ct)[,\s]+[A-Z][a-z]+',
        ]
        combined = title_block + "\n" + text
        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                return match.group(0 if '\\d+' in pattern else 1).strip()
        return None

    def _determine_plan_type(self, text: str) -> PlanType:
        text_lower = text.lower()
        if any(w in text_lower for w in ["commercial", "office", "retail", "restaurant", "hotel"]):
            return PlanType.COMMERCIAL
        if any(w in text_lower for w in ["residential", "dwelling", "house", "apartment", "condo"]):
            return PlanType.RESIDENTIAL
        if any(w in text_lower for w in ["industrial", "warehouse", "manufacturing", "factory"]):
            return PlanType.INDUSTRIAL
        if "mixed use" in text_lower or "mixed-use" in text_lower:
            return PlanType.MIXED_USE
        return PlanType.UNKNOWN

    def _extract_professional(self, text: str, role: str) -> Optional[str]:
        pattern = rf'{role}[:\s]+([A-Z][a-zA-Z\s.,]+(?:AIA|PE|SE|RA)?)'
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_occupancy(self, text: str) -> Optional[str]:
        # Anchor to the IBC group letters (A/B/E/F/H/I/M/R/S/U) plus optional
        # subgroup digit. The previous broad `[A-Z][-\d]*` matched the "C" in
        # "CERTIFICATE OF OCCUPANCY" — the single most common false positive
        # on real architectural sets. Also disallow generic phrasing like
        # "CERTIFICATE OF OCCUPANCY" / "OCCUPANCY PERMIT" by requiring a
        # colon, "CLASS", "TYPE", "GROUP", or "CLASSIFICATION" between the
        # word and the value.
        pattern = (
            r'OCCUPANCY\s+(?:CLASS|TYPE|GROUP|CLASSIFICATION)[:\s]+'
            r'([ABEFHIMRSU](?:-\d+)?(?:[,/]\s*[ABEFHIMRSU](?:-\d+)?)*)'
            r'|OCCUPANCY[:\s]+([ABEFHIMRSU](?:-\d+)?(?:[,/]\s*[ABEFHIMRSU](?:-\d+)?)*)\b'
        )
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        return (match.group(1) or match.group(2)).strip()

    def _extract_construction_type(self, text: str) -> Optional[str]:
        pattern = r'(?:CONSTRUCTION|CONST\.?)\s+TYPE[:\s]+((?:TYPE\s+)?[IVX]+[-A-Z]*)'
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    @staticmethod
    def _safe_float(v: str) -> Optional[float]:
        """Parse a regex-captured value to float. Returns None if junk (e.g. '.' or '')."""
        if not v:
            return None
        s = v.strip().rstrip(".").lstrip(".")
        if not s or not any(c.isdigit() for c in s):
            return None
        try:
            return float(v.replace(",", ""))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(v: str) -> Optional[int]:
        if not v:
            return None
        try:
            return int(v.replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _extract_dimensions(self, text: str) -> Dict[str, Any]:
        dims = {}

        # Building height
        height_match = re.search(
            r'(?:BUILDING|TOTAL|MAX(?:IMUM)?)\s+HEIGHT[:\s]+([\d.]+)\s*(?:FT|FEET|\'|INCHES|")?',
            text, re.IGNORECASE
        )
        if height_match:
            v = self._safe_float(height_match.group(1))
            if v is not None:
                dims["building_height"] = v

        # Building area / square footage
        area_match = re.search(
            r'(?:TOTAL|GROSS|BUILDING)\s+(?:FLOOR\s+)?AREA[:\s]+([\d,]+)\s*(?:SF|SQ\.?\s*FT\.?|SQUARE\s+FEET)',
            text, re.IGNORECASE
        )
        if area_match:
            v = self._safe_float(area_match.group(1))
            if v is not None:
                dims["building_area"] = v

        # Corridor / hallway widths
        corridor_matches = re.findall(
            r'(?:CORRIDOR|HALLWAY|HALL|PASSAGE)\s*(?:WIDTH)?[:\s]*([\d.]+)\s*(?:"|INCHES|IN\.?|\')?',
            text, re.IGNORECASE
        )
        widths = [v for v in (self._safe_float(m) for m in corridor_matches) if v is not None]
        if widths:
            dims["corridor_widths"] = widths

        # Door widths
        door_matches = re.findall(
            r'(?:DOOR|DOORWAY)\s*(?:WIDTH|W\.?)[:\s]*([\d.]+)\s*(?:"|INCHES|IN\.?|\')?',
            text, re.IGNORECASE
        )
        widths = [v for v in (self._safe_float(m) for m in door_matches) if v is not None]
        if widths:
            dims["door_widths"] = widths

        # Stair dimensions
        stair_width = re.search(
            r'STAIR(?:S|WAY)?\s*(?:WIDTH)?[:\s]*([\d.]+)\s*(?:"|INCHES|IN\.?|\')?',
            text, re.IGNORECASE
        )
        if stair_width:
            v = self._safe_float(stair_width.group(1))
            if v is not None:
                dims["stair_width"] = v

        # Ceiling height
        ceiling_match = re.search(
            r'(?:CEILING|CLG\.?)\s*(?:HEIGHT|HT\.?)[:\s]*([\d.]+)\s*(?:\'|FT|FEET)?',
            text, re.IGNORECASE
        )
        if ceiling_match:
            v = self._safe_float(ceiling_match.group(1))
            if v is not None:
                dims["ceiling_height"] = v

        # Occupant load
        occupant_match = re.search(
            r'(?:OCCUPANT|OCCUPANCY)\s+LOAD[:\s]*([\d,]+)',
            text, re.IGNORECASE
        )
        if occupant_match:
            v = self._safe_int(occupant_match.group(1))
            if v is not None:
                dims["occupant_load"] = v

        return dims

    def _extract_elements(self, text: str) -> List[PlanElement]:
        elements = []
        text_lower = text.lower()

        # Check for sprinklers
        if re.search(r'sprinkler|nfpa\s*13', text, re.IGNORECASE):
            elements.append(PlanElement(
                element_type="fire_suppression",
                description="Fire sprinkler system referenced",
                raw_text="sprinkler system"
            ))

        # Check for egress
        if re.search(r'exit|egress|means of egress', text, re.IGNORECASE):
            elements.append(PlanElement(
                element_type="egress",
                description="Egress elements present",
                raw_text="exit/egress"
            ))

        # Check for ADA/accessibility
        if re.search(r'ada|accessible|accessibility|wheelchair|handicap', text, re.IGNORECASE):
            elements.append(PlanElement(
                element_type="accessibility",
                description="ADA/accessibility elements present",
                raw_text="ADA"
            ))

        # Check for electrical panels
        if re.search(r'electrical\s+panel|main\s+panel|sub\s*panel|mep', text, re.IGNORECASE):
            elements.append(PlanElement(
                element_type="electrical",
                description="Electrical panel(s) referenced",
                raw_text="electrical panel"
            ))

        # HVAC
        if re.search(r'hvac|mechanical|ductwork|ventilation', text, re.IGNORECASE):
            elements.append(PlanElement(
                element_type="mechanical",
                description="HVAC/mechanical elements present",
                raw_text="HVAC"
            ))

        return elements

    def _extract_materials(self, text: str) -> List[str]:
        materials = []
        material_keywords = [
            "concrete", "masonry", "steel", "wood", "timber", "cmu",
            "drywall", "gypsum", "brick", "glass", "aluminum", "composite"
        ]
        text_lower = text.lower()
        for mat in material_keywords:
            if mat in text_lower:
                materials.append(mat)
        return materials


pdf_processor = PDFProcessor()
