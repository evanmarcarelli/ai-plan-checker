---
description: Measure Architechtura accuracy with the free, local harnesses (deterministic P/R/F1 + benchmark citation-validity) and report a scorecard vs pilot.py / BENCHMARK targets. The shared "measure" primitive every optimization gates on.
argument-hint: "[live] [--case <slug>] [--min-f1 <x>] [--with-gate]"
allowed-tools: Bash, Read
---

You are the **eval primitive** for Architechtura. Produce one honest scorecard. Do not change any code.

## What to run

The arguments are: `$ARGUMENTS`

### Always run (free, local, no API key)

1. **Deterministic engine** — is the explicit code-math right (run from `backend/`):
   ```bash
   cd backend && python -m scripts.eval.run_eval --verbose
   ```
   - If `--case <slug>` was passed, add it. If `--min-f1 <x>` was passed, add it (it exits non-zero below the bar). Add `--with-gate` if requested (also scores post citation-gate).
   - Cases live in `backend/scripts/eval/cases/*.json` (28 today). Reports per-case + OVERALL tp/fp/fn/tn + prec/rec/F1 + the archetype-gate accuracy.

2. **Benchmark dry run** — schema + citation validity, no API (the anti-hallucination metric):
   ```bash
   python -m benchmarks
   ```
   (from repo root). Citation Validity < 1.00 means the system is inventing section numbers.

### Only if the first arg is `live` (costs API credits — confirm budget first)

```bash
python -m benchmarks --live        # real LLM pipeline on synthetic features
python -m benchmarks --live-pdf    # full pipeline incl. Surveyor extraction
```
Never run `live` without an `ANTHROPIC_API_KEY` set and explicit go-ahead — locally there is no key (mocks only), so a live number would be meaningless.

## How to report

Print a single scorecard table comparing measured vs target. Targets:

| Metric | Source | v1 target | Ship target |
|---|---|---|---|
| Deterministic OVERALL F1 | run_eval | — (track delta) | — |
| Per-finding precision | `pilot.py` PilotTargets | 0.90 | 0.90 |
| Per-finding recall | `pilot.py` PilotTargets | 0.85 | 0.85 |
| Out-of-scope rejection (archetype gate) | `pilot.py` | 0.95 | 0.95 |
| Citation Validity | benchmarks | 0.95 | 1.00 |
| Critical Recall (live) | benchmarks | 0.80 | 0.95 |
| Forbidden Hits (live) | benchmarks | ≤2/case | 0 |

Then state plainly: **PASS/FAIL against each target**, and list the top 3 mismatches from the `--verbose` output (case, rule, expected vs actual). End with one line: the single OVERALL F1 number, so a caller (e.g. `/optimize`) can diff it before/after a change.

If a harness errors (missing dep, import error), report the exact error — do not paper over it with a guessed number.
