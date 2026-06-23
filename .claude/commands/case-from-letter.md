---
description: Turn a real AHJ correction letter into a ground-truth eval-case scaffold using the existing benchmarks.intake tool. This is the real signal-growth path (NOT the product feedback board, which is feature requests). A scaffold is not ground truth until a human signs off.
argument-hint: "<path/to/correction-letter.pdf> [--case-id <id>] [--jurisdiction \"CA:Los Angeles\"] [--plan-type residential]"
---

Scaffold a real benchmark case from a correction letter. Input: `$ARGUMENTS`.

## Steps
1. Confirm the file exists. Derive sensible defaults if flags are omitted (case-id from the filename; ask for jurisdiction/plan-type if not inferable — they matter for scoring).
2. Run the existing intake tool (from repo root):
   ```bash
   python -m benchmarks.intake <letter.pdf> --case-id <id> \
       --jurisdiction "<CA:City>" --plan-type <residential|commercial>
   ```
   It parses the numbered items, pulls the code sections each cites, guesses severity/status/objectivity, flags administrative noise, and writes an annotated `ground_truth.yaml` SCAFFOLD under `benchmarks/cases/<id>/`.
3. Show the scaffold and call out: which items are GUESSes needing verification, which look like administrative noise, and any cited sections that are NOT in our corpus (route those to `corpus-ingest`).

## Rules
- **A scaffold is not ground truth.** Per `benchmarks/README.md`, a licensed reviewer must verify the guesses, fill `acceptance_criteria`, and drop the as-submitted `plan.pdf` before it counts. Present it for that review — never silently promote it into the scored set.
- Each new verified case moves an archetype toward `PilotTargets.min_observations_per_archetype = 10`. Note which archetype this case strengthens.
- After a case is signed off, run `python -m benchmarks` (dry) to confirm it loads and citation validity stays 1.00.
