"""Deterministic plan-check rule engine.

Ported from the Architechtura (plan-room-ahj) TypeScript engine. The core idea:
LLM department reviewers are good at reading messy plans but silently
miscalculate multi-step arithmetic 5-15% of the time — the fastest way to
lose reviewer trust. So the code-math (allowable area, story limits, exit
counts, fixture counts) is done by pure, unit-tested Python functions, and
the LLM is never asked to do arithmetic.

Public surface:
    evaluate_plan(plan_data) -> List[ComplianceFinding]
        Run every applicable deterministic rule over the extracted plan
        data and return high-trust findings.

    BASELINE_RULES / CALFIRE_WUI_RULES / CALGREEN_MANDATORY_RULES
        The rule definitions, mirroring the TS knowledge base.
"""
from app.code_library.deterministic.engine import evaluate_plan, rules_for_jurisdiction
from app.code_library.deterministic.rules import (
    BASELINE_RULES,
    CALFIRE_WUI_RULES,
    CALGREEN_MANDATORY_RULES,
    CBC_2025_RULES,
    Rule,
)

__all__ = [
    "evaluate_plan",
    "rules_for_jurisdiction",
    "BASELINE_RULES",
    "CALFIRE_WUI_RULES",
    "CALGREEN_MANDATORY_RULES",
    "CBC_2025_RULES",
    "Rule",
]
