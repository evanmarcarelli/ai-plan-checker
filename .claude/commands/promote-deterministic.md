---
description: The signature efficiency move — find an INTERPRETED (LLM) check that a number could decide and promote it into the deterministic engine. Raises precision and cuts cost at the same time, and moves the check into the free, closed-loop optimization zone.
argument-hint: "[discipline or specific check, e.g. 'egress' or 'plumbing fixtures']"
---

Promote an interpreted check to an explicit one. Focus: `$ARGUMENTS` (if empty, scan for the best candidate).

## Find the candidate
A good promotion is a check that is currently done by an LLM department but is really arithmetic or a table lookup:
- Read the reviewer prompts in `backend/app/agents/departments.py` and the `pilot.py`/eval mismatches for recurring numeric judgments (areas, heights, story counts, egress/exit math, fixture counts, min dimensions, ratings).
- Cross-check what the deterministic engine already covers (`backend/app/code_library/deterministic/rules.py`, `checkers.py`, `tables.py`) so you don't duplicate.
- Pick the ONE with the clearest numeric rule and the highest flag frequency. If a check genuinely needs judgment ("adequate", design intent), it is NOT a candidate — leave it with `reviewer-tuning`.

## Implement (via the deterministic-rules department)
Dispatch the `deterministic-rules` subagent to produce ONE coherent diff:
1. A `Rule` in `rules.py` (discipline, `code_ref`, severity, `applies` gate that falls OPEN on unknown data).
2. A pure checker in `checkers.py` (or reuse `check_min_dimension` / a `table_store` lookup).
3. A `table_store`/`tables` entry if it needs a code value.
4. New eval case(s) in `backend/scripts/eval/cases/` proving it — ideally a violating case AND a clean true-negative.

## Gate + surface
- `cd backend && python -m scripts.eval.run_eval --verbose` before and after; report OVERALL F1 and archetype-gate deltas. `pytest tests/test_deterministic.py` green.
- Note the cost win: every promoted check is one fewer thing the Sonnet reviewers must reason about.
- **Propose → approve**, then log the result to `docs/optimization-log.md`.
