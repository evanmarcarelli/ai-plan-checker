from typing import Dict, Any
from app.agents.base import BaseAgent
from app.models.schemas import Jurisdiction
from app.code_library.adapter import CorpusCodeSource
from app.utils.logger import get_logger

logger = get_logger(__name__)


class LibrarianAgent(BaseAgent):
    """Agent 2: The Librarian — deterministic code retrieval. NO LLM CALL.

    The Librarian used to make an LLM call to "refine" the code list down to
    20-25 items. That output was discarded by the workflow — the 10 department
    reviewers pull codes straight from the corpus (`code_db.get_applicable_codes`),
    never from the Librarian's refined list. So the LLM call was pure wasted
    spend: 1 of 12 calls per run, for nothing.

    Code retrieval is now fully deterministic (the BM25 corpus + jurisdiction
    filter). Removing the LLM call cuts ~8% of per-run calls at ZERO accuracy
    cost — the discarded output cannot have been contributing accuracy.

    Guarded by tests/test_cost_optimizations.py::test_librarian_makes_no_llm_call_regression
    """

    def __init__(self):
        super().__init__(name="Librarian")
        self.code_db = CorpusCodeSource()

    def _get_system_prompt(self) -> str:
        # BaseAgent requires this (abstract), but the Librarian never calls the
        # LLM, so it is intentionally inert.
        return "Deterministic code librarian — makes no LLM calls."

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        jurisdiction: Jurisdiction = state.get("jurisdiction") or Jurisdiction()
        plan_data = state.get("plan_data")
        plan_type = (
            plan_data.plan_type.value
            if plan_data and plan_data.plan_type
            else "commercial"
        )

        codes = self.code_db.get_applicable_codes(
            state=jurisdiction.state_code,
            city=jurisdiction.city,
            plan_type=plan_type,
            county=jurisdiction.county,
        )
        logger.info(
            f"[Librarian] {len(codes)} applicable codes for "
            f"{jurisdiction.city or 'Unknown'}, {jurisdiction.state_code or 'Unknown'} "
            f"(deterministic — no LLM call)"
        )

        return {
            "code_requirements": codes,
            "jurisdiction_amendments": self.code_db.get_jurisdiction_amendments(
                jurisdiction.state_code, jurisdiction.city
            ),
            "code_version": self.code_db.get_code_version(jurisdiction.state_code),
            "sources_used": ["code_library/bm25"],
        }
