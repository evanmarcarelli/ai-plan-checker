"""Regression guards for LLM-call resilience on Render Free.

The symptom these tests defend against: Surveyor + Librarian complete,
then the 10 department reviewers fire in parallel, some get throttled or
timed out by Render Free's resource limits, the workflow catches each as
a generic exception and falls back to mock responses, and the user sees
"0% / all needs review" with no clue what happened.

The two changes we're locking in:
  1. _call_llm retries transient errors (timeout, connection, rate limit)
     before giving up. Auth / not-found errors fail fast (no retry — those
     are config bugs, not blips).
  2. Workflow limits concurrent department reviews via an asyncio.Semaphore
     so Render Free doesn't try to run 10 HTTPS calls in parallel.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic

from app.config import settings


@pytest.fixture(autouse=True)
def _api_key():
    """Force settings.anthropic_api_key non-empty so _call_llm goes down the
    real Anthropic path instead of the mock fallback in every test."""
    with patch.object(settings, "anthropic_api_key", "sk-ant-test"):
        yield


# ─────────────────────────────────────────────────────────────
# 1. _call_llm retries transient errors
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_llm_retries_on_transient_error_regression():
    """If the first Anthropic call raises a transient error (timeout,
    connection, rate limit), _call_llm must retry. Without this, every
    Render Free hiccup turns into a needs_review fallback."""
    from app.agents.surveyor import SurveyorAgent
    agent = SurveyorAgent()

    fake_content = MagicMock()
    fake_content.text = "{\"city\": \"Altadena\"}"
    fake_resp = MagicMock()
    fake_resp.content = [fake_content]

    attempts = {"count": 0}

    async def fake_create(**kw):
        attempts["count"] += 1
        if attempts["count"] == 1:
            # First attempt: transient timeout
            raise anthropic.APIConnectionError(request=MagicMock())
        return fake_resp

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(agent, "_get_client", return_value=mock_client):
        out = await agent._call_llm("hello")

    assert attempts["count"] == 2, f"expected one retry, got {attempts['count']} attempts"
    assert out == "{\"city\": \"Altadena\"}"
    assert agent.last_llm_error is None, "successful retry must clear last_llm_error"


@pytest.mark.asyncio
async def test_call_llm_does_not_retry_on_not_found_error_regression():
    """NotFoundError means the model name is wrong (config bug). Retrying
    burns budget on a failure that won't recover. Must fail fast."""
    from app.agents.surveyor import SurveyorAgent
    agent = SurveyorAgent()

    attempts = {"count": 0}

    async def fake_create(**kw):
        attempts["count"] += 1
        raise anthropic.NotFoundError(
            "model: claude-sonnet-fake", response=MagicMock(), body=None
        )

    mock_client = MagicMock()
    mock_client.messages.create = fake_create

    with patch.object(agent, "_get_client", return_value=mock_client):
        await agent._call_llm("hello")

    assert attempts["count"] == 1, "NotFoundError must NOT be retried"
    assert agent.last_llm_error is not None
    assert "NotFound" in agent.last_llm_error


# ─────────────────────────────────────────────────────────────
# 2. Workflow caps parallel department reviews
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_workflow_limits_concurrent_department_reviews_regression():
    """The workflow must NOT run all 10 department reviewers in unbounded
    parallel — Render Free chokes on 10 concurrent outbound HTTPS calls.
    Concurrency must be capped (we use 3)."""
    from app.agents import workflow as wf_module

    # The module should expose the limit so tests can assert + future tuning
    # is centralized.
    assert hasattr(wf_module, "DEPARTMENT_CONCURRENCY"), \
        "workflow module must expose DEPARTMENT_CONCURRENCY"
    assert 1 <= wf_module.DEPARTMENT_CONCURRENCY <= 5, \
        f"DEPARTMENT_CONCURRENCY should be a small bounded number (got {wf_module.DEPARTMENT_CONCURRENCY})"
