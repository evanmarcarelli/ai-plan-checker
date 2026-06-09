# PhiCodes AI Benchmark Harness

This is where we measure whether the AI is actually good enough to ship.

Without benchmarks, "the system works" is a vibe. With them, it's a number we
can move and defend in a sales conversation.

## What gets measured

| Metric | Why it matters |
|---|---|
| **Citation Validity** | Fraction of findings whose section number exists in our real code corpus. < 1.0 = the system is inventing section numbers. This is the headline anti-hallucination metric. |
| **Critical Recall** | Of the critical (life-safety) findings the architect expected, what fraction did we surface. Most important metric for trust. |
| **Precision / Recall / F1** | Standard accuracy across all expected findings. |
| **Forbidden Hits** | Number of findings we should NOT have flagged. Catches false-positive regressions (e.g. flagging commercial codes on an SFR). |

## How to run

```bash
# 1. Dry-run (no API calls). Validates the corpus + scoring + citation
#    verification pipeline. Should always score citation_validity = 1.00.
#    Run this in CI.
python -m benchmarks

# 2. Live run against the real LLM-backed pipeline. Costs API credits.
python -m benchmarks --live

# 3. Save live results to disk, then re-score without re-running.
python -m benchmarks --live --save-cache
python -m benchmarks --from-cache
```

## How to add a new case

Drop a folder in `benchmarks/cases/<your_case_id>/`:

```
benchmarks/cases/my_new_case/
    ground_truth.yaml       # required — expected findings + must_not_flag
    plan_features.yaml      # optional — synthetic Surveyor output for --live
    plan.pdf                # optional — for a real PDF run (not yet wired)
```

Ground truth schema:

```yaml
description: short paragraph
jurisdiction:
  state: CA
  city: Altadena
plan_type: residential
expected_findings:
  - section: "IBC 1011.5.2"
    severity: critical | high | medium | low
    status: non_compliant | needs_review
    notes: |
      Why the architect expects this flag.
must_not_flag:
  - "ADA 208.2"   # this section should never come back for this case
```

## Calibration: where we are vs where we need to be

| Metric | Today (dry) | v1 target (live) | Ship target |
|---|---|---|---|
| Citation Validity | 1.00 | 0.95+ | 1.00 |
| Critical Recall   | 1.00 | 0.80+ | 0.95+ |
| Precision         | 1.00 | 0.50+ | 0.75+ |
| Forbidden Hits    | 0    | ≤ 2/case | 0 |

If a live run scores below the v1 target, do not ship to paying customers.
