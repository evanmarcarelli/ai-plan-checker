"""Adversarial cross-model critic.

Ported from plan-room-ahj/supabase/functions/_shared/critic.ts. Every
"non-compliant" finding the department reviewers emit gets a second
pass from a different model than the one that produced it. The critic
is prompted ADVERSARIALLY — "find the reason this flag is wrong" —
rather than asked to agree.

Why adversarial: same-model critique tends to confirm rather than
challenge. The same family of failure modes (hallucinated cross-
references, missed sprinkler-mode negation, etc.) lives in both the
proposer and the critic when they share weights. Splitting models is
the cheapest way to get an independent read.

Default proposer/critic split:
  Proposer = Sonnet (used in extraction + department review)
  Critic   = Opus   (slower, sharper)

Cost: ~$0.02-0.05 per critique. Capped to PIPELINE_GATES.critic_max_findings_per_run
per submittal.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

from app.config import settings
from app.config.pilot import PIPELINE_GATES
from app.models.schemas import (
    ComplianceFinding,
    ComplianceStatus,
    ExtractedPlanData,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Default critic = Opus (different family from Sonnet proposer).
_DEFAULT_CRITIC_MODEL = "claude-opus-4-7"


@dataclass
class CritiqueVerdict:
    """The critic's read on whether a finding should ship as 'fail'."""
    agrees: bool                          # True iff critic backs the proposer
    confidence: float                     # 0-1, critic's confidence in its verdict
    critic_model: str                     # Which model did the critique
    dissent_reasoning: Optional[str] = None  # Required when agrees=False


_CRITIC_SYSTEM = """You are an adversarial code reviewer auditing another AI's findings on
a building permit plan set. Your job is NOT to agree with the proposer's flag — your
job is to FIND THE REASON THE FLAG IS WRONG.

A flag is wrong when ANY of these is true:
  - The proposer misread the plan text (occupancy, area, type, OL).
  - The cited code section does not actually apply to this occupancy / configuration.
  - The proposer's check ignored a sprinkler / frontage / NFPA increase that would clear it.
  - The proposer flagged a missing item that is actually present elsewhere in the text.
  - The deterministic check fired but the extracted input was low-confidence.
  - The local jurisdiction amended the section in a way the proposer didn't consider.

If, after looking carefully, you cannot find a reason the flag is wrong, agree —
but only then. Default to skepticism. Adversarial means adversarial.

Output JSON:
  agrees: boolean — true ONLY if you cannot find a reason the flag is wrong
  confidence: 0-1 — how confident YOU are in your verdict (not the proposer's)
  dissent_reasoning: required when agrees=false; one sentence explaining the rebuttal.

Respond with JSON only. No prose."""


async def critique_finding(
    finding: ComplianceFinding,
    scope: ExtractedPlanData,
    plan_text_excerpt: Optional[str] = None,
    critic_model: str = _DEFAULT_CRITIC_MODEL,
    client: Optional[anthropic.AsyncAnthropic] = None,
) -> CritiqueVerdict:
    """Run the adversarial critique on a single finding.

    Returns a verdict whose default (on any failure) is "no agreement,
    confidence 0" — i.e. uncritiqued, route to human review. That's the
    safe failure mode: never silently accept an uncritiqued fail.
    """
    if not settings.anthropic_api_key:
        logger.warning("[critic] ANTHROPIC_API_KEY missing — skipping critique")
        return CritiqueVerdict(
            agrees=False,
            confidence=0.0,
            critic_model=critic_model,
            dissent_reasoning="Critic skipped: no API key available.",
        )

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    summary = {
        "rule_id": finding.finding_id or finding.code_requirement.code_id,
        "code_ref": finding.code_requirement.section
        or finding.code_requirement.code_id,
        "severity": finding.severity,
        "status": finding.status.value if hasattr(finding.status, "value") else str(finding.status),
        "proposer_summary": finding.description,
        "extracted_scope": {
            "occupancy_type": getattr(scope, "occupancy_type", None),
            "construction_type": getattr(scope, "construction_type", None),
            "building_area": getattr(scope, "building_area", None),
            "per_story_area": getattr(scope, "per_story_area", None),
            "stories": getattr(scope, "stories", None),
            "building_height": getattr(scope, "building_height", None),
            "sprinklered": getattr(scope, "sprinklered", None),
            "occupant_load": getattr(scope, "occupant_load", None),
        },
        "cited_text": finding.source_text,
    }

    excerpt_block = (
        f"<plan_text_excerpt>\n{(plan_text_excerpt or '')[:4000]}\n</plan_text_excerpt>"
        if plan_text_excerpt
        else "(no plan-text excerpt provided)"
    )

    user_msg = (
        "Here is the finding to critique.\n\n"
        "<finding>\n"
        f"{json.dumps(summary, indent=2, default=str)}\n"
        "</finding>\n\n"
        f"{excerpt_block}\n\n"
        "Find the reason this flag is wrong. If you cannot find one, agree."
    )

    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=critic_model,
                max_tokens=512,
                system=_CRITIC_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            ),
            timeout=45.0,
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text

        parsed = _parse_critique_json(text)
        if parsed is None:
            logger.warning(
                "[critic] could not parse critique JSON for %s; treating as unverified",
                finding.finding_id,
            )
            return CritiqueVerdict(
                agrees=False,
                confidence=0.0,
                critic_model=critic_model,
                dissent_reasoning="Critic returned unparseable JSON.",
            )

        return CritiqueVerdict(
            agrees=bool(parsed.get("agrees", False)),
            confidence=float(parsed.get("confidence", 0.0)),
            critic_model=critic_model,
            dissent_reasoning=parsed.get("dissent_reasoning"),
        )

    except (asyncio.TimeoutError, anthropic.APIConnectionError, anthropic.APITimeoutError) as err:
        logger.warning("[critic] transient failure for %s: %s", finding.finding_id, err)
        return CritiqueVerdict(
            agrees=False,
            confidence=0.0,
            critic_model=critic_model,
            dissent_reasoning=f"Critic call timed out / connection failed: {err}",
        )
    except Exception as err:  # pragma: no cover - defensive
        logger.error("[critic] critique failed for %s: %s", finding.finding_id, err)
        return CritiqueVerdict(
            agrees=False,
            confidence=0.0,
            critic_model=critic_model,
            dissent_reasoning=f"Critic exception: {err}",
        )


def apply_critique(finding: ComplianceFinding, verdict: CritiqueVerdict) -> None:
    """Apply the critic verdict to the finding in-place.

      - Critic agrees:                       leave as non_compliant; bump confidence.
      - Critic disagrees with high conf:     downgrade to needs_review, attach dissent.
      - Critic disagrees with low conf:      leave as non_compliant but flag for human queue.

    The mutation surface is narrow — status, confidence, description only.
    """
    if verdict.agrees:
        finding.confidence = min(0.98, (finding.confidence or 1.0) * 1.1)
        return

    if verdict.confidence >= PIPELINE_GATES.critic_hard_downgrade_confidence:
        # High-confidence dissent → downgrade fail to needs_review
        finding.status = ComplianceStatus.NEEDS_REVIEW
        finding.description = (
            f"[DISPUTED BY CRITIC — {verdict.critic_model}] {finding.description} "
            f"Rebuttal: {verdict.dissent_reasoning or 'no reasoning provided'}."
        )
        finding.confidence = min(finding.confidence or 1.0, 0.4)
        return

    # Low-confidence dissent → leave as fail but lower confidence so the
    # dashboard routes this to human review with a "models disagree" tag.
    finding.description = (
        f"[CRITIC DISSENT — low conf {int((verdict.confidence or 0) * 100)}%] "
        f"{finding.description} "
        f"Concern: {verdict.dissent_reasoning or 'no reasoning provided'}."
    )
    finding.confidence = min(finding.confidence or 1.0, 0.6)


# =====================================================================
# JSON parsing — tolerant of fenced code blocks Claude sometimes emits
# =====================================================================
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_critique_json(text: str) -> Optional[dict]:
    """Pull the JSON object out of the critic response, fence-tolerant."""
    if not text:
        return None
    candidate = text.strip()
    fence_match = _FENCE_RE.search(candidate)
    if fence_match:
        candidate = fence_match.group(1).strip()
    # Fall back to first {...} balanced block if a stray prose intro slipped in.
    if not candidate.startswith("{"):
        first = candidate.find("{")
        last = candidate.rfind("}")
        if first >= 0 and last > first:
            candidate = candidate[first : last + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
