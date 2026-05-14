import json
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import anthropic
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Base class for all plan checker agents."""

    def __init__(self, name: str):
        self.name = name
        self._client: Optional[anthropic.AsyncAnthropic] = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    @abstractmethod
    def _get_system_prompt(self) -> str:
        pass

    @abstractmethod
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        pass

    async def _call_llm(self, user_content: str, max_tokens: int = None) -> str:
        """Call Claude and return the response text."""
        if not settings.anthropic_api_key:
            logger.warning(f"[{self.name}] No Anthropic API key - returning mock response")
            return self._mock_response(user_content)

        try:
            client = self._get_client()
            response = await client.messages.create(
                model=settings.anthropic_model,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": user_content}],
                max_tokens=max_tokens or settings.anthropic_max_tokens,
            )
            return response.content[0].text if response.content else ""
        except Exception as e:
            logger.error(f"[{self.name}] LLM call failed: {e}")
            return self._mock_response(user_content)

    def _mock_response(self, content: str) -> str:
        return f"[MOCK RESPONSE - No API Key] Agent {self.name} processed the input."

    def _parse_json_response(self, text: str) -> Optional[Any]:
        """Extract JSON from LLM response text."""
        try:
            return json.loads(text)
        except Exception:
            pass

        patterns = [
            r"```json\s*([\s\S]+?)\s*```",
            r"```\s*([\s\S]+?)\s*```",
            r"\{[\s\S]+\}",
            r"\[[\s\S]+\]",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    raw = match.group(0) if pattern.startswith(r"\{") or pattern.startswith(r"\[") else match.group(1)
                    return json.loads(raw)
                except Exception:
                    continue

        logger.warning(f"[{self.name}] Could not parse JSON from response: {text[:200]}")
        return None
