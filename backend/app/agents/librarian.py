import json
from typing import Dict, Any, List
from app.agents.base import BaseAgent
from app.models.schemas import CodeRequirement, Jurisdiction
from app.services.code_database import CodeDatabase
from app.utils.logger import get_logger

logger = get_logger(__name__)


class LibrarianAgent(BaseAgent):
    """
    Agent 2: The Librarian
    Retrieves relevant building codes for the identified jurisdiction.
    Uses mock database as primary, with LLM refinement.
    Runs on Sonnet (cheap) — structured filtering, doesn't need Opus.
    """

    @property
    def model_override(self):  # type: ignore[override]
        from app.config import settings as _s
        return _s.anthropic_model_cheap

    def __init__(self):
        super().__init__(name="Librarian")
        self.code_db = CodeDatabase()

    def _get_system_prompt(self) -> str:
        return """You are an expert building code librarian with comprehensive knowledge of:
- International Building Code (IBC) 2021
- International Fire Code (IFC) 2021
- National Electrical Code (NEC) 2023
- International Plumbing Code (IPC) 2021
- International Mechanical Code (IMC) 2021
- ADA Accessibility Guidelines 2010
- State and local amendments

YOUR TASK:
Given jurisdiction info and a list of available codes, select and return the 20-25 MOST RELEVANT
code requirements for this specific project. Consider:
1. The plan type (commercial vs residential changes requirements)
2. State-specific codes (CA seismic, FL hurricane, etc.)
3. Jurisdiction amendments

OUTPUT FORMAT — return a JSON array ONLY, no other text:
[
  {
    "code_id": "string",
    "code_name": "string",
    "section": "string",
    "description": "string",
    "category": "fire_safety|structural|electrical|plumbing|accessibility|energy|general",
    "requirement_type": "dimension|procedure|load|general",
    "min_value": number or null,
    "max_value": number or null,
    "unit": "string or null",
    "jurisdiction_specific": boolean,
    "full_text": "string"
  }
]"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        jurisdiction: Jurisdiction = state.get("jurisdiction")
        plan_data = state.get("plan_data")
        plan_type = plan_data.plan_type.value if plan_data else "commercial"

        if not jurisdiction:
            logger.warning("[Librarian] No jurisdiction in state, using generic codes")
            jurisdiction = Jurisdiction()

        logger.info(f"[Librarian] Fetching codes for {jurisdiction.city}, {jurisdiction.state_code}")

        # Get codes from database
        db_codes = self.code_db.get_applicable_codes(
            state=jurisdiction.state_code,
            city=jurisdiction.city,
            plan_type=plan_type
        )

        logger.info(f"[Librarian] Retrieved {len(db_codes)} codes from database")

        # Use LLM to refine and select most relevant
        context = f"""JURISDICTION:
City: {jurisdiction.city or 'Unknown'}
County: {jurisdiction.county or 'Unknown'}
State: {jurisdiction.state or 'Unknown'} ({jurisdiction.state_code or 'Unknown'})
Governing Authority: {jurisdiction.governing_authority or 'Unknown'}
Seismic Zone: {jurisdiction.seismic_zone or 'Unknown'}
Wind Zone: {jurisdiction.wind_zone or 'Unknown'}

PLAN TYPE: {plan_type}

AVAILABLE CODES (all {len(db_codes)} codes):
{json.dumps([c.model_dump() for c in db_codes], indent=2)[:6000]}

Select the 20-25 most relevant code requirements for this specific jurisdiction and plan type.
Prioritize jurisdiction-specific codes. Return as JSON array."""

        try:
            response = await self._call_llm(context)
            refined = self._parse_json_response(response)

            if refined and isinstance(refined, list) and len(refined) > 0:
                refined_codes = []
                for item in refined:
                    try:
                        refined_codes.append(CodeRequirement(**item))
                    except Exception:
                        continue
                if refined_codes:
                    db_codes = refined_codes
                    logger.info(f"[Librarian] LLM refined to {len(db_codes)} codes")
        except Exception as e:
            logger.warning(f"[Librarian] LLM refinement failed: {e}, using all DB codes")

        return {
            "code_requirements": db_codes,
            "jurisdiction_amendments": self.code_db.get_jurisdiction_amendments(
                jurisdiction.state_code, jurisdiction.city
            ),
            "code_version": self.code_db.get_code_version(jurisdiction.state_code),
            "sources_used": ["mock_database"],
        }
