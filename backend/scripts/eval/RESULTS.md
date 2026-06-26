# Deterministic-engine eval — trend log

Accuracy is a tracked number, not a vibe. Append one row per meaningful run so
"did it get better than last time" has an answer.

## How to record a run

```bash
cd backend
SHA=$(git rev-parse --short HEAD)
# snapshot for regression compares (commit it):
python3 -m scripts.eval.run_eval --json > scripts/eval/baselines/$(date +%F)-$SHA.json
# gate any change against the last baseline (exits non-zero on regression):
python3 -m scripts.eval.run_eval --baseline scripts/eval/baselines/<prev>.json
```

Two independent signals to watch:
- **strict F1** — does the engine assert hard `fail`s correctly (the confusion matrix).
- **surfacing recall** — of the findings a real reviewer flagged (`reviewer_finding: true`),
  how many did the engine surface as `fail|warn`. A conservative `warn` that surfaces a real
  issue counts; only a `pass`/`info` that buries one misses. This is the dimension the
  confusion matrix cannot see for soft (needs_review) rules.

Watch the **gated** (`--with-gate`) number as the real-world figure — it falls when the
corpus is too thin to verify a citation (see `tests/test_rule_citation_coverage.py`).

| date       | sha     | mode   | tp | fp | fn | prec  | rec   | f1    | surfacing | notes |
|------------|---------|--------|----|----|----|-------|-------|-------|-----------|-------|
| 2026-06-23 | fc2110c | engine | 41 |  0 |  0 | 1.000 | 1.000 | 1.000 | 1.000 | EGR-CORRIDOR/STAIR-WIDTH hardened on OL>=50 — first runs to score these as true positives (was 0 tp, invisible). |
| 2026-06-23 | fc2110c | gated  | 39 |  0 |  2 | 1.000 | 0.951 | 0.975 | 1.000 | 2 fn = corpus gaps: FIRE-WUI-DECK (CBC 709A un-ingested), LADBS-SFD-HILLSIDE-FIRE. Real-world ceiling until 709A lands. |
| 2026-06-23 | wip     | engine | 49 |  0 |  0 | 1.000 | 1.000 | 1.000 | 1.000 | 8 stair-GEOMETRY rules (EGR/CRC tread·riser·guard·handrail) hardened on stair_type=standard — +8 tp from two new `*-stair-geometry-standard` cases (soft `*-violation` twins kept). All 8 now score (was 0 tp, recall n/a). Re-snapshot at commit. |
| 2026-06-23 | wip     | gated  | 47 |  0 |  2 | 1.000 | 0.959 | 0.979 | 1.000 | Same 2 corpus-gap fn (709A, hillside-fire); shape rules are requires_citation=False so pass the gate unchanged. Gated recall ticks up (0.951->0.959) as the tp denominator grows. |

> Note: the ungated engine number is back at 1.000 because ground truth was realigned to the
> now-correct hard-fail behavior. The ungated path is **re-saturated** — genuine de-saturation
> needs letter-backed cases the engine currently gets wrong (see plan Phase 2). The **gated**
> path (0.975) is the honest, unsaturated figure today.
