import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import anthropic
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Errors worth retrying. These are transient: a brief connection drop, a rate
# limit, a server-side overload, a timeout. Everything else (auth, not_found,
# bad_request) means the config is wrong and retrying just wastes budget.
_RETRIABLE_LLM_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    asyncio.TimeoutError,
)


class BaseAgent(ABC):
    """Base class for all plan checker agents.

    Per-agent model selection: subclasses override `model_override` to swap
    to a cheaper or specialized model. Surveyor stays on the premium model
    (jurisdiction parsing is the hardest task); department reviewers and
    Librarian use Sonnet for ~5x cost savings on the same workload.
    """

    # When None, falls back to settings.anthropic_model (default = Opus).
    model_override: Optional[str] = None

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

    # Optional capture of the most recent error string. Useful so the
    # workflow can surface "LLM call failed: <reason>" in the per-job
    # agent logs instead of the mock-response silent fallback making every
    # finding come back as needs_review with no explanation.
    last_llm_error: Optional[str] = None

    async def _call_llm(
        self,
        user_content: str,
        max_tokens: int = None,
        cache_prefix: str = None,
    ) -> str:
        """Call Claude and return the response text.

        cache_prefix: optional STABLE text (e.g. verbatim code requirements that
        don't change between runs). When provided it is sent as a separate
        content block marked `cache_control: ephemeral`, so Anthropic prompt
        caching bills it at ~10% of the input rate on any repeat within the
        5-minute cache window. Caching is output-neutral — the model's response
        is byte-identical whether or not the prefix was cached.
        """
        if not settings.anthropic_api_key:
            self.last_llm_error = "ANTHROPIC_API_KEY env var is empty on the server"
            logger.warning(f"[{self.name}] {self.last_llm_error} - returning mock response")
            return self._mock_response(user_content)

        client = self._get_client()
        model = self.model_override or settings.anthropic_model

        if cache_prefix:
            # Cached prefix first, fresh content second. The cache_control
            # breakpoint caches everything up to and including this block
            # (system prompt + prefix).
            content = [
                {"type": "text", "text": cache_prefix,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": user_content},
            ]
        else:
            content = user_content

        # Retry loop for transient errors only. Each attempt has its own
        # explicit timeout (the Anthropic SDK's default is 10 min, far too
        # generous for Render-Free-induced hangs).
        MAX_ATTEMPTS = 3
        PER_CALL_TIMEOUT = 120  # seconds
        BACKOFF = [0, 2, 5]     # seconds before each attempt

        last_error: Optional[Exception] = None
        for attempt in range(MAX_ATTEMPTS):
            if BACKOFF[attempt]:
                await asyncio.sleep(BACKOFF[attempt])
            try:
                response = await asyncio.wait_for(
                    client.messages.create(
                        model=model,
                        system=self._get_system_prompt(),
                        messages=[{"role": "user", "content": content}],
                        max_tokens=max_tokens or settings.anthropic_max_tokens,
                    ),
                    timeout=PER_CALL_TIMEOUT,
                )
                # Success — clear any stale error state from a previous retry.
                self.last_llm_error = None
                return response.content[0].text if response.content else ""
            except _RETRIABLE_LLM_ERRORS as e:
                last_error = e
                logger.warning(
                    f"[{self.name}] transient LLM error on attempt "
                    f"{attempt + 1}/{MAX_ATTEMPTS}: {type(e).__name__}: {e}"
                )
                continue
            except Exception as e:
                # Non-retriable: auth, not_found, bad_request. Fail fast so
                # config bugs surface in the agent log instead of silently
                # burning the retry budget.
                self.last_llm_error = f"{type(e).__name__}: {e}"
                logger.error(f"[{self.name}] LLM call failed ({self.last_llm_error})")
                return self._mock_response(user_content)

        # Exhausted retries on transient errors. Record and fall back.
        self.last_llm_error = (
            f"{type(last_error).__name__}: {last_error} "
            f"(after {MAX_ATTEMPTS} attempts)"
        )
        logger.error(f"[{self.name}] LLM call gave up: {self.last_llm_error}")
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
