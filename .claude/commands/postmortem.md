---
description: Append one measured row to the optimization ledger (docs/optimization-log.md). A row, not an essay — every entry carries a before/after number and whether the change was kept. Negative results count.
argument-hint: "[short description of what was tried]"
---

Record an optimization outcome in `docs/optimization-log.md`. Subject: `$ARGUMENTS`.

1. Read the current ledger to match the table format.
2. Gather the facts (ask only for what you can't infer): which department, the one-line change, the metric that moved, before → after, which gate measured it (`run_eval` / `benchmarks --dry` / `benchmarks --live` / `pytest`), and **kept** = yes/no/pending.
3. Append exactly one table row. Convert any relative date to an absolute one.

## Rules
- One row per outcome. Keep `notes` to one sentence.
- If the change regressed and was reverted, still log it (kept = no) — a recorded dead end stops the loop from re-trying it.
- Do not edit prior rows; the ledger is append-only history.
- This is a measurement record, not a knowledge vault — if there's no number, there's no row.
