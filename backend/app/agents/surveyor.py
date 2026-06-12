import asyncio
import json
import re
from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.schemas import Jurisdiction, ExtractedPlanData, PlanType
from app.services.pdf_processor import pdf_processor
from app.services.vision_extractor import vision_title_extractor
from app.utils.logger import get_logger

logger = get_logger(__name__)

# State name to code mapping
STATE_MAP = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}

KNOWN_CITY_STATES = {
    "los angeles": "CA", "san francisco": "CA", "san diego": "CA", "sacramento": "CA",
    "altadena": "CA", "pasadena": "CA", "glendale": "CA", "burbank": "CA",
    "long beach": "CA", "santa monica": "CA", "anaheim": "CA", "irvine": "CA",
    "new york": "NY", "buffalo": "NY", "albany": "NY",
    "miami": "FL", "orlando": "FL", "tampa": "FL", "jacksonville": "FL",
    "houston": "TX", "dallas": "TX", "austin": "TX", "san antonio": "TX",
    "chicago": "IL", "springfield": "IL",
    "seattle": "WA", "spokane": "WA",
    "phoenix": "AZ", "tucson": "AZ",
    "denver": "CO", "boulder": "CO",
    "portland": "OR",
    "las vegas": "NV",
    "atlanta": "GA",
    "boston": "MA",
    "nashville": "TN",
    "charlotte": "NC",
    "minneapolis": "MN",
    "detroit": "MI",
}

SEISMIC_ZONES = {
    "CA": "D", "AK": "D", "WA": "C", "OR": "C",
    "NV": "C", "ID": "B", "UT": "C",
    "TN": "B", "MS": "B", "MO": "B",
    "SC": "B", "GA": "A",
    "FL": "A", "TX": "A", "NY": "B",
}

WIND_ZONES = {
    "FL": "III", "TX": "II", "LA": "II", "MS": "II",
    "NC": "II", "SC": "II", "GA": "I", "NY": "I",
    "CA": "I", "WA": "I",
}


class SurveyorAgent(BaseAgent):
    """
    Agent 1: The Surveyor
    Scans uploaded PDF to identify jurisdiction, plan type, and key metadata.
    Focuses on title blocks (bottom-right corner of drawings).
    """

    def __init__(self):
        super().__init__(name="Surveyor")

    def _get_system_prompt(self) -> str:
        return """You are an expert architectural plan reviewer specializing in jurisdiction identification.

Your task: Analyze extracted text from architectural/engineering plan sets to identify:
1. Project location (city, county, state)
2. Governing authority / AHJ (Authority Having Jurisdiction)
3. Plan type (commercial, residential, industrial, mixed-use)
4. Project name and address
5. Environmental zones (seismic, wind, flood, snow)

Focus especially on TEXT FROM TITLE BLOCKS (bottom-right of drawings) which contain:
- Project address
- Building department / permit info
- Architect/Engineer seals
- Project name

OUTPUT: Return ONLY valid JSON matching this schema:
{
  "city": "string or null",
  "county": "string or null",
  "state": "string (full name) or null",
  "state_code": "2-letter code or null",
  "country": "USA",
  "governing_authority": "string or null",
  "seismic_zone": "A/B/C/D or null",
  "wind_zone": "I/II/III or null",
  "flood_zone": "string or null",
  "confidence": 0.0 to 1.0,
  "plan_type": "commercial|residential|industrial|mixed_use|unknown",
  "project_name": "string or null",
  "project_address": "string or null"
}"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        file_path = state.get("file_path")
        if not file_path:
            raise ValueError("No file_path in state")

        logger.info(f"[Surveyor] Extracting PDF: {file_path}")

        # Extract PDF content. PyMuPDF text layer first; Textract OCR
        # fills in any pages whose text layer is too thin (gated by the
        # AWS_TEXTRACT_ENABLED flag). The pdf_processor handles all that
        # behind the call; we just consume what it returns.
        # Run the synchronous PyMuPDF/Textract extraction in a worker thread.
        # On a single uvicorn worker, calling this directly blocks the event
        # loop for the whole 50-page parse — which freezes the live progress
        # poll and can starve the /health check. to_thread keeps the loop free.
        raw_data = await asyncio.to_thread(pdf_processor.extract, file_path)
        plan_data = await asyncio.to_thread(pdf_processor.parse_plan_data, raw_data)

        # Surface Textract's canonical KV pairs (when present) onto plan_data
        # before vision runs. This means the surveyor's LLM context starts
        # with structured fields filled when Textract read them off the
        # title-sheet code-data box, and vision becomes the second opinion
        # rather than the only opinion.
        textract_kvs = raw_data.get("code_data_summary") or {}
        if textract_kvs:
            logger.info(
                f"[Surveyor] Textract code_data_summary populated "
                f"{len(textract_kvs)} field(s): {list(textract_kvs.keys())}"
            )
            self._apply_textract_fields(plan_data, textract_kvs)

        # Vision pass on the title sheet. The regex extractors above match very
        # narrow label formats and routinely miss the code data summary on real
        # architectural sets (or false-positive on it — e.g. "C" for occupancy
        # from "CERTIFICATE OF OCCUPANCY"). When those fields land as null on
        # the JSON sent to the 10 Department reviewers, every code requirement
        # comes back as needs_review for lack of anything to compare against.
        # Reading them visually off the title sheet is the highest-leverage
        # fill-in.
        vision_data = await vision_title_extractor.extract(
            file_path, raw_data.get("pages", {})
        )
        self._apply_vision_fields(plan_data, vision_data)

        # Deterministic-engine inputs the extractors already find but used to
        # drop on the floor: the regex extractor stores occupant load in the
        # dimensions dict, and vision reads "sprinklered" off the title sheet —
        # neither was copied to the schema fields the engine's egress and
        # story-sprinkler math reads, leaving those checks permanently
        # unevaluable.
        if plan_data.occupant_load is None:
            raw_ol = (plan_data.dimensions or {}).get("occupant_load")
            try:
                plan_data.occupant_load = int(float(str(raw_ol).replace(",", ""))) if raw_ol is not None else None
            except (TypeError, ValueError):
                pass
        if plan_data.actual_wc is None:
            wc = (plan_data.dimensions or {}).get("wc_count")
            plan_data.actual_wc = int(wc) if isinstance(wc, (int, float)) else None
        if plan_data.actual_lav is None:
            lav = (plan_data.dimensions or {}).get("lav_count")
            plan_data.actual_lav = int(lav) if isinstance(lav, (int, float)) else None
        if plan_data.sprinklered is None and vision_data:
            raw_spr = vision_data.get("sprinklered")
            if isinstance(raw_spr, bool):
                plan_data.sprinklered = raw_spr
            elif isinstance(raw_spr, str):
                low = raw_spr.strip().lower()
                if low in ("yes", "true", "y", "sprinklered", "nfpa 13", "nfpa 13d", "nfpa 13r"):
                    plan_data.sprinklered = True
                elif low in ("no", "false", "n", "non-sprinklered", "unsprinklered"):
                    plan_data.sprinklered = False

        # Round out the extraction audit trail with the vision outcome, so a
        # hollow report ("everything needs_review") is explainable later from
        # the persisted plan_data alone.
        try:
            plan_data.extraction_stats = {
                **(plan_data.extraction_stats or {}),
                "vision": {
                    "fields_read": sorted(
                        k for k, v in (vision_data or {}).items()
                        if v not in (None, "", []) and k != "is_title_sheet"
                    ),
                    "error": vision_title_extractor.last_error,
                },
            }
        except Exception:
            pass

        # Build context for LLM
        title_block = raw_data.get("title_block", "") or ""
        first_pages_text = ""
        for page_num in [1, 2, 3]:
            page_text = raw_data["pages"].get(page_num, "")
            if page_text:
                first_pages_text += f"\n--- PAGE {page_num} ---\n{page_text[:2000]}"

        import os as _os
        filename_hint = _os.path.basename(file_path)

        vision_summary = (
            f"VISION-READ TITLE-SHEET FIELDS (trust these over the text-extraction "
            f"fallback; null means vision could not read it):\n{json.dumps(vision_data, indent=2)}"
            if vision_data
            else "VISION-READ TITLE-SHEET FIELDS: (vision extraction skipped or returned empty)"
        )

        context = f"""FILENAME (often contains project address or city):
{filename_hint}

{vision_summary}

TITLE BLOCK TEXT (most important - bottom-right of drawings):
{title_block[:3000] if title_block else "No title block extracted"}

FIRST PAGES TEXT:
{first_pages_text[:4000]}

PDF METADATA:
{raw_data.get('metadata', {})}

Total pages: {raw_data.get('page_count', 0)}
"""

        # Call LLM
        logger.info("[Surveyor] Calling LLM for jurisdiction identification")
        response = await self._call_llm(context)

        # Parse response
        parsed = self._parse_json_response(response)

        # Build jurisdiction
        jurisdiction = Jurisdiction()
        if parsed and isinstance(parsed, dict):
            # No project_address fallback here: a street address is not a city,
            # and this field keys the adoption resolver + corpus scope — a
            # corrupted value silently produced a baseline/wrong code stack.
            # Leave it None and let the heuristic/county path handle it.
            jurisdiction.city = parsed.get("city")
            jurisdiction.county = parsed.get("county")
            jurisdiction.state = parsed.get("state")
            jurisdiction.state_code = parsed.get("state_code")
            jurisdiction.governing_authority = parsed.get("governing_authority")
            jurisdiction.seismic_zone = parsed.get("seismic_zone")
            jurisdiction.wind_zone = parsed.get("wind_zone")
            jurisdiction.flood_zone = parsed.get("flood_zone")
            try:
                jurisdiction.confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
            except (TypeError, ValueError):
                jurisdiction.confidence = 0.5

            if parsed.get("plan_type"):
                try:
                    plan_data.plan_type = PlanType(parsed["plan_type"])
                except Exception:
                    pass

            if parsed.get("project_name") and not plan_data.project_name:
                plan_data.project_name = parsed["project_name"]
            if parsed.get("project_address") and not plan_data.project_address:
                plan_data.project_address = parsed["project_address"]
        else:
            # Fallback: heuristic extraction
            jurisdiction = self._heuristic_jurisdiction(
                raw_data.get("all_text", ""),
                title_block
            )

        # Fill in seismic/wind zones from lookup tables if missing
        if jurisdiction.state_code and not jurisdiction.seismic_zone:
            jurisdiction.seismic_zone = SEISMIC_ZONES.get(jurisdiction.state_code)
        if jurisdiction.state_code and not jurisdiction.wind_zone:
            jurisdiction.wind_zone = WIND_ZONES.get(jurisdiction.state_code)

        logger.info(
            f"[Surveyor] Identified: {jurisdiction.city}, {jurisdiction.state_code} "
            f"(confidence: {jurisdiction.confidence:.0%})"
        )

        return {
            "jurisdiction": jurisdiction,
            "plan_data": plan_data,
            "raw_pdf_data": raw_data,
            "vision_data": vision_data,
            "vision_error": vision_title_extractor.last_error,
        }

    @staticmethod
    def _apply_vision_fields(plan_data: ExtractedPlanData, vision: Dict[str, Any]) -> None:
        """Fold vision-extracted title-sheet fields into plan_data. Vision
        wins for occupancy_type (the regex extractor's "C" false positive
        from "CERTIFICATE OF OCCUPANCY" is its single most common failure);
        for everything else vision only fills values the regex left blank
        so we don't clobber a correctly-parsed dimension."""
        if not vision:
            return
        # Override the well-known false positive. Anything else short-and-
        # bare-letter that fails the IBC group format (A/B/E/F/H/I/M/R/S/U
        # optionally with -digit) is almost certainly a regex misfire too.
        occ = vision.get("occupancy_type")
        if occ and (
            plan_data.occupancy_type is None
            or plan_data.occupancy_type == "C"
            or not re.match(r"^[ABEFHIMRSU](-\d+)?(\s*[,/]\s*[ABEFHIMRSU](-\d+)?)*$",
                            (plan_data.occupancy_type or "").strip(), re.IGNORECASE)
        ):
            plan_data.occupancy_type = occ
        if vision.get("construction_type") and not plan_data.construction_type:
            plan_data.construction_type = vision["construction_type"]
        if vision.get("building_height_ft") is not None and plan_data.building_height is None:
            try:
                plan_data.building_height = float(vision["building_height_ft"])
            except (TypeError, ValueError):
                pass
        if vision.get("building_area_sf") is not None and plan_data.building_area is None:
            try:
                plan_data.building_area = float(vision["building_area_sf"])
            except (TypeError, ValueError):
                pass
        if vision.get("stories") is not None and plan_data.stories is None:
            try:
                plan_data.stories = int(vision["stories"])
            except (TypeError, ValueError):
                pass
        if vision.get("project_name") and not plan_data.project_name:
            plan_data.project_name = vision["project_name"]
        if vision.get("project_address") and not plan_data.project_address:
            plan_data.project_address = vision["project_address"]

    @staticmethod
    def _apply_textract_fields(plan_data: ExtractedPlanData, kvs: Dict[str, str]) -> None:
        """Fold Textract code-data-summary KV pairs into plan_data BEFORE
        vision runs. Same conservative rule as vision: only fill values
        the regex extractor left blank, except for occupancy where we
        override the known-bad "C" false positive.

        Vision runs after this and may still override anything Textract
        couldn't read confidently — Textract is high-precision/low-recall
        on architectural sheets, vision is the inverse, and we want both
        contributing without either getting the last word for free.
        """
        if not kvs:
            return
        occ = kvs.get("occupancy")
        if occ and (
            plan_data.occupancy_type is None
            or plan_data.occupancy_type == "C"
        ):
            plan_data.occupancy_type = occ
        if kvs.get("construction_type") and not plan_data.construction_type:
            plan_data.construction_type = kvs["construction_type"]
        if kvs.get("project_name") and not plan_data.project_name:
            plan_data.project_name = kvs["project_name"]
        if kvs.get("project_address") and not plan_data.project_address:
            plan_data.project_address = kvs["project_address"]
        # Numeric fields: Textract returns raw strings like '45 FT' or
        # '12,500 SF'. Strip non-digit/decimal characters before casting.
        def _to_float(raw: str):
            try:
                cleaned = re.sub(r"[^\d.]", "", (raw or "").replace(",", ""))
                return float(cleaned) if cleaned else None
            except (TypeError, ValueError):
                return None
        if plan_data.building_height is None:
            v = _to_float(kvs.get("building_height", ""))
            if v is not None:
                plan_data.building_height = v
        if plan_data.building_area is None:
            v = _to_float(kvs.get("building_area", ""))
            if v is not None:
                plan_data.building_area = v
        if plan_data.stories is None:
            try:
                cleaned = re.sub(r"[^\d]", "", kvs.get("stories", "") or "")
                if cleaned:
                    plan_data.stories = int(cleaned)
            except (TypeError, ValueError):
                pass

    def _heuristic_jurisdiction(self, text: str, title_block: str) -> Jurisdiction:
        """Fallback heuristic extraction when LLM fails."""
        combined = (title_block + " " + text).lower()
        jurisdiction = Jurisdiction(confidence=0.3)

        # Try to find state
        for state_name, state_code in STATE_MAP.items():
            if state_name in combined:
                jurisdiction.state = state_name.title()
                jurisdiction.state_code = state_code
                jurisdiction.confidence = 0.5
                break

        # Try to find city
        for city, state_code in KNOWN_CITY_STATES.items():
            if city in combined:
                jurisdiction.city = city.title()
                if not jurisdiction.state_code:
                    jurisdiction.state_code = state_code
                    jurisdiction.confidence = 0.6
                break

        # Try ZIP code
        zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', text)
        if zip_match:
            jurisdiction.confidence = max(jurisdiction.confidence, 0.4)

        return jurisdiction
