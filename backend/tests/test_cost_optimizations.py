"""Regression guards for LLM-cost optimizations.

These tests lock in two cost reductions that must not silently regress:

1. The Librarian must make ZERO LLM calls. Its old LLM "refinement" output was
   discarded by the workflow (department agents pull codes straight from the
   corpus), so the call was pure wasted spend — 1 of 12 calls per run.

2. Department reviewers must send the stable code-requirements text as a
   `cache_prefix` so Anthropic prompt caching bills it at the cached rate
   (~90% off) on warm runs, instead of full price every time.

If either of these regresses, per-run API cost silently climbs. These tests
fail loudly if that happens.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.models.schemas import (
    CodeRequirement, ExtractedPlanData, Jurisdiction, PlanType,
)


@pytest.fixture
def residential_plan():
    return ExtractedPlanData(
        project_name="Test SFR",
        plan_type=PlanType.RESIDENTIAL,
        occupancy_type="R-3",
        construction_type="V-B",
        building_height=26.0,
        building_area=2400.0,
        stories=2,
    )


# ─────────────────────────────────────────────────────────────
# 1. Librarian must not call the LLM
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_librarian_makes_no_llm_call_regression():
    """The Librarian's job is deterministic code lookup. It must not spend an
    LLM call — the workflow discards any LLM 'refinement' it produces."""
    from app.agents.librarian import LibrarianAgent

    lib = LibrarianAgent()
    fail_if_called = AsyncMock(side_effect=AssertionError("Librarian must NOT call the LLM"))

    with patch.object(lib, "_call_llm", new=fail_if_called):
        state = {
            "jurisdiction": Jurisdiction(
                state_code="CA", city="Altadena", state="California"
            ),
            "plan_data": ExtractedPlanData(plan_type=PlanType.RESIDENTIAL),
        }
        result = await lib.execute(state)

    assert fail_if_called.await_count == 0, "Librarian must make zero LLM calls"
    # ...but it must still produce the deterministic outputs the workflow needs
    assert result.get("code_version"), "Librarian must still return a code_version"
    assert "jurisdiction_amendments" in result
    assert result.get("code_requirements"), "Librarian must still return applicable codes"


# ─────────────────────────────────────────────────────────────
# 2. _call_llm must support cache_prefix and emit cache_control
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_llm_marks_cache_prefix_regression():
    """When _call_llm receives a cache_prefix, the Anthropic request body must
    carry a cache_control block so the stable prefix is billed cached."""
    from app.agents.departments import BuildingSafetyAgent

    agent = BuildingSafetyAgent()

    class _FakeContent:
        text = "[]"

    class _FakeResp:
        content = [_FakeContent()]

    mock_create = AsyncMock(return_value=_FakeResp())
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch.object(settings, "anthropic_api_key", "test-key"), \
         patch.object(agent, "_get_client", return_value=mock_client):
        await agent._call_llm("FRESH PLAN DATA", cache_prefix="STABLE CODE TEXT BLOCK")

    kwargs = mock_create.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert isinstance(content, list), "cache_prefix should yield structured content blocks"
    cached = [b for b in content if isinstance(b, dict) and b.get("cache_control")]
    assert cached, "expected a cache_control block when cache_prefix is supplied"
    assert any("STABLE CODE TEXT BLOCK" in b.get("text", "") for b in cached), \
        "the cache_prefix text must be inside the cached block"


@pytest.mark.asyncio
async def test_call_llm_without_cache_prefix_is_plain_string():
    """No cache_prefix → plain string content (unchanged legacy behaviour)."""
    from app.agents.surveyor import SurveyorAgent

    agent = SurveyorAgent()

    class _FakeContent:
        text = "{}"

    class _FakeResp:
        content = [_FakeContent()]

    mock_create = AsyncMock(return_value=_FakeResp())
    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch.object(settings, "anthropic_api_key", "test-key"), \
         patch.object(agent, "_get_client", return_value=mock_client):
        await agent._call_llm("just a plain prompt")

    kwargs = mock_create.call_args.kwargs
    assert kwargs["messages"][0]["content"] == "just a plain prompt"


# ─────────────────────────────────────────────────────────────
# 3. Department reviewer must wire the code block through as cache_prefix
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_department_reviewer_passes_cache_prefix_regression(residential_plan):
    """The department reviewer must hand the (stable) verbatim code text to
    _call_llm as cache_prefix — that is what makes warm runs cheap."""
    from app.agents.departments import BuildingSafetyAgent

    agent = BuildingSafetyAgent()
    seen = {}

    async def fake_call_llm(user_content, max_tokens=None, cache_prefix=None):
        seen["cache_prefix"] = cache_prefix
        seen["user_content"] = user_content
        return "[]"

    with patch.object(agent, "_call_llm", new=fake_call_llm):
        reqs = [
            CodeRequirement(
                code_id="IBC 1011.5.2", code_name="International Building Code",
                section="1011.5.2", description="Stair riser/tread",
                category="building_safety",
                full_text="Stair riser heights shall be 7 inches maximum and 4 inches minimum.",
            )
        ]
        await agent.review(residential_plan, reqs, [], "2021 IBC")

    assert seen.get("cache_prefix"), "department reviewer must pass a non-empty cache_prefix"
    assert "Stair riser heights" in seen["cache_prefix"], \
        "verbatim code text belongs in the cached prefix, not the fresh part"
