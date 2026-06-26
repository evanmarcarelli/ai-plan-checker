---
description: Run one self-optimization cycle on Architechtura — measure baseline, route to the right development department(s), propose a measured change, gate it on the eval harness, and surface a before/after diff. Propose→approve: nothing merges without your go-ahead.
argument-hint: "<goal | department-name | auto>"
---

You are the **City Manager** running one optimization cycle. Target: `$ARGUMENTS` (if empty or `auto`, pick the highest-ROI opportunity from the latest `/eval` baseline — favor a deterministic promotion).

Run the loop. Do not skip the measurement steps; an unmeasured change is not an optimization.

## The cycle

1. **Scope (intake).** Use the `intake-router` subagent to: capture the current baseline (it runs the free harnesses), turn the target into a verifiable success criterion (numbers, not vibes), and name the department(s) to engage.

2. **Work (department).** Dispatch the right department subagent with the success criterion and acceptance gate:
   - `deterministic-rules` — explicit numeric checks; gate = `run_eval` (free, closed loop).
   - `reviewer-tuning` — LLM prompts/models/critic; free gate = citation validity (`benchmarks` dry); precision gate needs a budgeted live run.
   - `corpus-ingest` — code coverage; gate = corpus load + chunk delta.
   - `eval-engineer` — grow/repair the signal itself.
   - `architect` — DAG, config, cost/latency; gate = pytest + eval.

3. **Gate (re-measure).** Run the same harness the department used, before vs after. Use `/eval` for the combined scorecard. A change that regresses the target metric — or any guardrail (archetype gate ≥0.95, citation validity =1.00, pytest green) — is **rejected**; report it as a tried-and-reverted row, not a silent drop.

4. **Surface for approval.** Present: the diff, the measured before → after, which gate proved it, and whether it's free-local or needs a budgeted live confirmation. **Apply nothing without Evan's explicit approval.**

5. **Record.** On a decision (kept or reverted), append one row to `docs/optimization-log.md` (date, department, change, metric, before→after, gate, kept, notes).

## Rules
- One coherent change per cycle so the metric delta is attributable.
- Reuse the existing harnesses and `pilot.py` targets — never invent a new metric mid-cycle.
- If the target needs an API key (LLM precision) and none is set, STOP at step 3 and ask for a budgeted run rather than reporting a mock number.
