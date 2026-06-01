# Plan Room AHJ — Eval Harness

You can't improve what you can't measure. This directory holds the
ground-truth fixtures + the harness that exercises the triage pipeline
against them and reports precision/recall/F1 per rule and per archetype.

## Files

- `cases/*.json` — one fixture per case. Schema:
  ```json
  {
    "slug": "stable-kebab-case",
    "title": "human label",
    "jurisdiction_key": "CA:LOS_ANGELES",
    "archetype": "la_sfr_typ_vb_ministerial",
    "project_address": "optional",
    "plan_text": "raw extracted text from the plan set",
    "ground_truth": [
      { "rule_id": "COM-OCCUPANCY-DECL", "expected_status": "pass", "expected_severity": "critical" }
    ]
  }
  ```
- `run-eval.ts` — Deno harness. Loads fixtures, runs `runTriage()`,
  classifies each (case, rule_id) as TP / FP / FN / TN, writes
  `eval_runs` + `eval_run_results` rows.

## Migrations

- `supabase/migrations/0006_eval_harness.sql` — `eval_cases`,
  `eval_ground_truth`, `eval_runs`, `eval_run_results`.

## Running

```bash
# 1. Apply the migration
supabase db push

# 2. One-time: upload the fixture set + ground truth into the DB
deno run --allow-env --allow-net --allow-read \
  scripts/eval/run-eval.ts --sync --dry-run

# 3. Run the deterministic-only eval (cheap, CI-safe)
deno run --allow-env --allow-net --allow-read \
  scripts/eval/run-eval.ts --label "baseline-no-llm"

# 4. Run with LLM extraction + research enabled (costs $$)
deno run --allow-env --allow-net --allow-read \
  scripts/eval/run-eval.ts --use-llm --use-research --label "v1.1-prompt-tuning"

# 5. Inspect results
psql "$SUPABASE_DB_URL" -c "
  select label, use_llm, use_research, precision, recall, f1, completed_at
  from eval_runs order by started_at desc limit 10;
"
```

## What to add next

- Real-world plan-set fixtures (redacted), not just synthetic ones.
  Target: 50–100 LA plan sets with reviewer correction lists as ground
  truth. A per-archetype F1 of 0.90 on 50+ real fixtures is what makes
  a defensible pilot accuracy claim.
- Out-of-scope cases (`archetype: out_of_scope`) measure the intake
  classifier (Task #2) — they intentionally have an empty
  `ground_truth` array and are skipped by rule-eval comparison.
- Per-severity F1 breakdown — critical-rule false negatives cost more
  than minor-rule ones; weight accordingly when comparing runs.
