#!/usr/bin/env -S deno run --allow-env --allow-net --allow-read
// =====================================================================
// CI / pre-pilot gate.
//
// Runs the eval harness and exits non-zero when the 90% pilot targets
// are not met. Use this as a pre-commit hook, a GitHub Actions step,
// or a manual "am I cleared to ship?" check.
//
// Usage:
//   deno run --allow-env --allow-net --allow-read \
//     scripts/eval/check-pilot-targets.ts [--label "ci-pr-1234"]
//
// Exit codes:
//   0   All PILOT_TARGETS met
//   1   At least one target missed → do not ship
//   2   Harness itself errored (env missing, DB down, etc.)
//
// What this script does NOT do:
//   - It does not change thresholds. Edit pilot_config.ts for that.
//   - It does not skip cases. Edit the fixture set for that.
//   - It does not retry. A flaky eval IS a failure.
// =====================================================================
import { main as runEval } from "./run-eval.ts";

try {
  const result = await runEval();
  if (!result?.pilotPass) {
    console.error("\nCI GATE: pilot targets missed — blocking ship.");
    Deno.exit(1);
  }
  console.log("\nCI GATE: pilot targets met — clear to ship.");
  Deno.exit(0);
} catch (err) {
  console.error("CI GATE: eval harness errored:", err);
  Deno.exit(2);
}
