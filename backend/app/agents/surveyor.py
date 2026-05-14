import json
import re
from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.schemas import Jurisdiction, ExtractedPlanData, PlanType
from app.services.pdf_processor import pdf_processor
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

        # Extract PDF content
        raw_data = pdf_processor.extract(file_path)
        plan_data = pdf_processor.parse_plan_data(raw_data)

        # Build context for LLM
        title_block = raw_data.get("title_block", "") or ""
        first_pages_text = ""
        for page_num in [1, 2, 3]:
            page_text = raw_data["pages"].get(page_num, "")
            if page_text:
                first_pages_text += f"\n--- PAGE {page_num} ---\n{page_text[:2000]}"

        import os as _os
        filename_hint = _os.path.basename(file_path)

        context = f"""FILENAME (often contains project address or city):
{filename_hint}

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
            jurisdiction.city = parsed.get("city") or plan_data.project_address
            jurisdiction.county = parsed.get("county")
            jurisdiction.state = parsed.get("state")
            jurisdiction.state_code = parsed.get("state_code")
            jurisdiction.governing_authority = parsed.get("governing_authority")
            jurisdiction.seismic_zone = parsed.get("seismic_zone")
            jurisdiction.wind_zone = parsed.get("wind_zone")
            jurisdiction.flood_zone = parsed.get("flood_zone")
            jurisdiction.confidence = float(parsed.get("confidence", 0.5))

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
        }

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
