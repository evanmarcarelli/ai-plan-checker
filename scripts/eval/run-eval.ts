#!/usr/bin/env -S deno run --allow-env --allow-net --allow-read
// =====================================================================
// Eval harness — measures triage pipeline accuracy against fixtures.
//
// Usage:
//   deno run --allow-env --allow-net --allow-read \
//     scripts/eval/run-eval.ts [options]
//
// Options:
//   --label <text>      Label this run (default: 'local-dev')
//   --use-llm           Run with LLM extraction enabled ($ — opt in)
//   --use-research      Run with citation research enabled ($$ — opt in)
//   --case <slug>       Run only one fixture by slug
//   --dry-run           Don't write eval_runs / eval_run_results
//   --sync              Upsert eval_cases + eval_ground_truth from disk first
//
// Environment:
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  (write to eval_runs / etc.)
//   ANTHROPIC_API_KEY, OPENAI_API_KEY        (only if --use-llm)
//
// Loads JSON fixtures from scripts/eval/cases/*.json, runs the triage
// pipeline against each one, computes precision/recall vs. ground truth,
// and writes one eval_runs row + N eval_run_results rows.
//
// Read with: select * from eval_runs order by started_at desc limit 5;
// =====================================================================
import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import { runTriage, PIPELINE_VERSION } from "../../supabase/functions/_shared/triage.ts";
import { LlmClient } from "../../supabase/functions/_shared/llm.ts";
import { PILOT_TARGETS, formatPilotTargets } from "../../supabase/functions/_shared/pilot_config.ts";

// ---------------------------------------------------------------------
// Fixture types — mirror the on-disk JSON shape
// ---------------------------------------------------------------------
interface GroundTruthEntry {
  rule_id: string;
  expected_status: "pass" | "fail" | "warn" | "info";
  expected_severity?: "critical" | "major" | "moderate" | "minor";
  rationale?: string;
}

interface EvalCase {
  slug: string;
  title: string;
  jurisdiction_key: string;
  archetype: string;
  project_address?: string;
  source?: string;
  notes?: string;
  plan_text: string;
  ground_truth: GroundTruthEntry[];
}

// Outcome of comparing one (case, rule_id) pair
type Outcome = "tp" | "fp" | "fn" | "tn" | "wrong_status";

interface RuleStats { tp: number; fp: number; fn: number; tn: number }
const blank = (): RuleStats => ({ tp: 0, fp: 0, fn: 0, tn: 0 });

function classify(expected: string, actual: string): Outcome {
  if (expected === "fail" && actual === "fail") return "tp";
  if (expected === "fail" && (actual === "pass" || actual === "warn" || actual === "info")) return "fn";
  if (expected === "pass" && actual === "fail") return "fp";
  if (expected === "pass" && actual === "pass") return "tn";
  return "wrong_status";
}

function prf({ tp, fp, fn }: RuleStats) {
  const p = tp + fp === 0 ? null : tp / (tp + fp);
  const r = tp + fn === 0 ? null : tp / (tp + fn);
  const f1 = p == null || r == null || (p + r) === 0 ? null : 2 * p * r / (p + r);
  return { precision: p, recall: r, f1 };
}

// ---------------------------------------------------------------------
// CLI flag parsing — no external deps
// ---------------------------------------------------------------------
function parseArgs() {
  const a = Deno.args;
  const get = (flag: string): string | undefined => {
    const i = a.indexOf(flag);
    return i >= 0 ? a[i + 1] : undefined;
  };
  const has = (flag: string) => a.includes(flag);
  return {
    label:      get("--label") ?? "local-dev",
    caseFilter: get("--case"),
    useLlm:     has("--use-llm"),
    useResearch: has("--use-research"),
    dryRun:     has("--dry-run"),
    sync:       has("--sync"),
  };
}

// ---------------------------------------------------------------------
// Fixture loader
// ---------------------------------------------------------------------
async function loadFixtures(filter?: string): Promise<EvalCase[]> {
  const dir = new URL("./cases/", import.meta.url);
  const out: EvalCase[] = [];
  for await (const entry of Deno.readDir(dir)) {
    if (!entry.isFile || !entry.name.endsWith(".json")) continue;
    const txt = await Deno.readTextFile(new URL(entry.name, dir));
    const parsed = JSON.parse(txt) as EvalCase;
    if (filter && parsed.slug !== filter) continue;
    out.push(parsed);
  }
  out.sort((a, b) => a.slug.localeCompare(b.slug));
  return out;
}

// ---------------------------------------------------------------------
// Optional: sync fixtures from disk → DB (eval_cases + eval_ground_truth)
// ---------------------------------------------------------------------
async function syncFixturesToDb(supabase: SupabaseClient, cases: EvalCase[]) {
  for (const c of cases) {
    const { data: existing } = await supabase
      .from("eval_cases")
      .select("id")
      .eq("slug", c.slug)
      .maybeSingle();

    let caseId: string;
    if (existing) {
      caseId = existing.id;
      await supabase.from("eval_cases").update({
        title: c.title,
        jurisdiction_key: c.jurisdiction_key,
        archetype: c.archetype,
        project_address: c.project_address ?? null,
        plan_text: c.plan_text,
        notes: c.notes ?? null,
        source: c.source ?? "synthetic",
      }).eq("id", caseId);
    } else {
      const ins = await supabase.from("eval_cases").insert({
        slug: c.slug,
        title: c.title,
        jurisdiction_key: c.jurisdiction_key,
        archetype: c.archetype,
        project_address: c.project_address ?? null,
        plan_text: c.plan_text,
        notes: c.notes ?? null,
        source: c.source ?? "synthetic",
      }).select("id").single();
      if (ins.error || !ins.data) {
        console.warn(`[sync] insert case ${c.slug} failed:`, ins.error?.message);
        continue;
      }
      caseId = ins.data.id;
    }

    // Replace ground-truth rows for this case
    await supabase.from("eval_ground_truth").delete().eq("case_id", caseId);
    if (c.ground_truth.length) {
      await supabase.from("eval_ground_truth").insert(
        c.ground_truth.map((g) => ({
          case_id: caseId,
          rule_id: g.rule_id,
          expected_status: g.expected_status,
          expected_severity: g.expected_severity ?? null,
          rationale: g.rationale ?? null,
        })),
      );
    }
  }
  console.log(`[sync] upserted ${cases.length} cases.`);
}

// ---------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------
export async function main() {
  const args = parseArgs();
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !supabaseKey) {
    console.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.");
    Deno.exit(1);
  }
  const supabase = createClient(supabaseUrl, supabaseKey, { auth: { persistSession: false } });

  // The LLM client is only used when --use-llm. For deterministic runs we
  // still need to pass an instance because runTriage expects one; the
  // useLlm:false path never actually hits the API.
  const llm = new LlmClient(
    Deno.env.get("ANTHROPIC_API_KEY") ?? "",
    Deno.env.get("OPENAI_API_KEY") ?? "",
    supabase,
  );

  const cases = await loadFixtures(args.caseFilter);
  if (cases.length === 0) {
    console.error("No fixtures found.");
    Deno.exit(1);
  }
  console.log(`Loaded ${cases.length} fixture(s). useLlm=${args.useLlm} useResearch=${args.useResearch}`);

  if (args.sync) {
    await syncFixturesToDb(supabase, cases);
  }

  // Create the run row up-front so eval_run_results can FK to it
  let runId: string | null = null;
  const startedAt = Date.now();
  if (!args.dryRun) {
    const ins = await supabase.from("eval_runs").insert({
      pipeline_version: PIPELINE_VERSION,
      label: args.label,
      use_llm: args.useLlm,
      use_research: args.useResearch,
    }).select("id").single();
    if (ins.error || !ins.data) {
      console.error("Could not create eval_runs row:", ins.error?.message);
      Deno.exit(1);
    }
    runId = ins.data.id;
  }

  const perArchetype: Record<string, RuleStats> = {};
  const perRule: Record<string, RuleStats> = {};
  const total: RuleStats = blank();
  const rowsToInsert: Array<Record<string, unknown>> = [];

  // Run each fixture
  for (const c of cases) {
    // Out-of-scope cases have empty ground_truth — they exist to verify
    // the intake classifier (Task #2). Skip rule-eval comparison for now.
    if (c.archetype === "out_of_scope" && c.ground_truth.length === 0) {
      console.log(`[skip] ${c.slug} (out_of_scope — intake classifier test, not rule eval)`);
      continue;
    }

    console.log(`\n→ Running ${c.slug} (${c.archetype})`);
    // Bypass the archetype gate for in-scope cases so the harness can
    // exercise the rule engine even when fixtures are deliberately
    // incomplete (e.g. la-sfr-v5b-missing-code-analysis has no
    // occupancy → classifyArchetype would return 'unclassified' and
    // skip rule eval). The gate itself is tested separately by the
    // out_of_scope fixtures.
    const allArchetypes = [
      "la_sfr_typ_vb_ministerial", "la_ti_commercial",
      "la_hillside_sfr", "la_hpoz_property", "la_coastal_zone",
      "high_rise_or_mid_rise", "multifamily_new_construction",
      "mixed_use_new_construction", "unclassified",
    ] as const;
    const report = await runTriage(
      llm,
      { agencyId: "00000000-0000-0000-0000-000000000000", submittalId: "00000000-0000-0000-0000-000000000000" },
      { id: "00000000-0000-0000-0000-000000000000", pilot_archetypes: [...allArchetypes] },
      c.plan_text,
      {
        useLlm: args.useLlm,
        research: args.useResearch && args.useLlm ? {
          supabase,
          jurisdictionKey: c.jurisdiction_key,
          maxCitations: 5,
        } : undefined,
      },
    );

    // Build a lookup: rule_id → actual finding
    const actualByRule = new Map(report.findings.map(f => [f.rule_id, f]));

    let casePass = 0, caseFail = 0;
    for (const expected of c.ground_truth) {
      const actual = actualByRule.get(expected.rule_id);
      const actualStatus = actual?.status ?? "missing";
      const outcome = classify(expected.expected_status, actualStatus);

      // Aggregate
      const archBucket = perArchetype[c.archetype] ?? (perArchetype[c.archetype] = blank());
      const ruleBucket = perRule[expected.rule_id] ?? (perRule[expected.rule_id] = blank());
      for (const bucket of [total, archBucket, ruleBucket]) {
        if (outcome === "tp") bucket.tp++;
        else if (outcome === "fp") bucket.fp++;
        else if (outcome === "fn") bucket.fn++;
        else if (outcome === "tn") bucket.tn++;
      }
      if (outcome === "tp" || outcome === "tn") casePass++; else caseFail++;

      if (runId) {
        rowsToInsert.push({
          run_id: runId,
          case_id: null, // resolved below after we look up case ids
          rule_id: expected.rule_id,
          expected_status: expected.expected_status,
          actual_status: actualStatus,
          outcome,
          finding_summary: actual?.summary ?? null,
          cited: !!actual?.citation,
          citation_confidence: actual?.citation?.confidence ?? null,
          _case_slug: c.slug, // sentinel; stripped before insert
        });
      }
    }
    console.log(`   ${casePass}/${casePass + caseFail} checks correct`);
  }

  // Resolve case slugs → ids in one round-trip
  if (runId && rowsToInsert.length) {
    const slugs = [...new Set(rowsToInsert.map((r) => r._case_slug as string))];
    const { data: caseRows } = await supabase
      .from("eval_cases").select("id, slug").in("slug", slugs);
    const slugToId = new Map((caseRows ?? []).map(r => [r.slug, r.id]));
    for (const r of rowsToInsert) {
      r.case_id = slugToId.get(r._case_slug as string) ?? null;
      delete r._case_slug;
    }
    const insertable = rowsToInsert.filter(r => r.case_id);
    if (insertable.length) {
      const ins = await supabase.from("eval_run_results").insert(insertable);
      if (ins.error) console.warn("eval_run_results insert failed:", ins.error.message);
    } else {
      console.warn("No case_id matches — did you forget --sync?");
    }
  }

  // ---- Compute final aggregates and write the run row ----
  const overall = prf(total);
  const archAgg: Record<string, ReturnType<typeof prf> & RuleStats> = {};
  for (const [k, v] of Object.entries(perArchetype)) archAgg[k] = { ...v, ...prf(v) };
  const ruleAgg: Record<string, ReturnType<typeof prf> & RuleStats> = {};
  for (const [k, v] of Object.entries(perRule)) ruleAgg[k] = { ...v, ...prf(v) };

  console.log("\n========== RESULTS ==========");
  console.log(`Cases run:    ${cases.filter(c => c.ground_truth.length).length}`);
  console.log(`Total checks: ${total.tp + total.fp + total.fn + total.tn}`);
  console.log(`Precision:    ${overall.precision?.toFixed(3) ?? "n/a"}`);
  console.log(`Recall:       ${overall.recall?.toFixed(3) ?? "n/a"}`);
  console.log(`F1:           ${overall.f1?.toFixed(3) ?? "n/a"}`);
  console.log(`(TP=${total.tp}  FP=${total.fp}  FN=${total.fn}  TN=${total.tn})`);

  console.log("\nPer-archetype:");
  for (const [k, v] of Object.entries(archAgg)) {
    console.log(`  ${k.padEnd(30)} p=${v.precision?.toFixed(2) ?? "—"}  r=${v.recall?.toFixed(2) ?? "—"}  f1=${v.f1?.toFixed(2) ?? "—"}`);
  }

  console.log("\nWorst-performing rules (lowest F1, min 1 obs):");
  const sortedRules = Object.entries(ruleAgg)
    .filter(([, v]) => (v.tp + v.fp + v.fn + v.tn) > 0)
    .sort((a, b) => (a[1].f1 ?? 0) - (b[1].f1 ?? 0))
    .slice(0, 8);
  for (const [k, v] of sortedRules) {
    console.log(`  ${k.padEnd(28)} tp=${v.tp} fp=${v.fp} fn=${v.fn} tn=${v.tn}  f1=${v.f1?.toFixed(2) ?? "—"}`);
  }

  // ---- PILOT TARGETS verdict ----
  // Explicit pass/fail against the 90% brief. The check-pilot-targets.ts
  // CLI parses this same logic to exit non-zero in CI.
  console.log("\n========== PILOT TARGETS ==========");
  console.log(formatPilotTargets());
  const verdicts: Array<{ label: string; pass: boolean; detail: string }> = [];

  // 1. Per-finding precision
  const precPass = (overall.precision ?? 0) >= PILOT_TARGETS.per_finding_precision_min;
  verdicts.push({
    label: "Per-finding precision",
    pass: precPass,
    detail: `${(overall.precision ?? 0).toFixed(3)} vs ≥ ${PILOT_TARGETS.per_finding_precision_min.toFixed(2)}`,
  });

  // 2. Per-finding recall
  const recPass = (overall.recall ?? 0) >= PILOT_TARGETS.per_finding_recall_min;
  verdicts.push({
    label: "Per-finding recall",
    pass: recPass,
    detail: `${(overall.recall ?? 0).toFixed(3)} vs ≥ ${PILOT_TARGETS.per_finding_recall_min.toFixed(2)}`,
  });

  // 3. Per-archetype precision (only archetypes with enough observations)
  const archetypeFails: string[] = [];
  for (const [k, v] of Object.entries(archAgg)) {
    const obs = v.tp + v.fp + v.fn + v.tn;
    if (obs < PILOT_TARGETS.min_observations_per_archetype) continue;
    const archPass = (v.precision ?? 0) >= PILOT_TARGETS.per_finding_precision_min;
    if (!archPass) archetypeFails.push(`${k} (p=${v.precision?.toFixed(2)})`);
  }
  verdicts.push({
    label: "Per-archetype precision",
    pass: archetypeFails.length === 0,
    detail: archetypeFails.length === 0
      ? "all in-scope archetypes meet target"
      : `below target: ${archetypeFails.join(", ")}`,
  });

  let allPass = true;
  for (const v of verdicts) {
    const mark = v.pass ? "PASS" : "FAIL";
    console.log(`  [${mark}] ${v.label.padEnd(28)} ${v.detail}`);
    if (!v.pass) allPass = false;
  }
  console.log(`\nOverall pilot-target verdict: ${allPass ? "PASS — clear to ship pilot" : "FAIL — do not promote to pilot"}`);

  if (runId) {
    await supabase.from("eval_runs").update({
      cases_total: cases.filter(c => c.ground_truth.length).length,
      checks_total: total.tp + total.fp + total.fn + total.tn,
      tp: total.tp, fp: total.fp, fn: total.fn, tn: total.tn,
      precision: overall.precision,
      recall: overall.recall,
      f1: overall.f1,
      per_archetype: archAgg,
      per_rule: ruleAgg,
      pilot_target_pass: allPass,
      pilot_target_breakdown: verdicts,
      duration_ms: Date.now() - startedAt,
      completed_at: new Date().toISOString(),
    }).eq("id", runId);
    console.log(`\nRun ${runId} written to eval_runs.`);
  } else {
    console.log("\n(dry-run — nothing written)");
  }

  // Surface the verdict to the caller so wrappers (CI gate) can exit
  // non-zero without re-parsing the eval output.
  return { pilotPass: allPass, overall, archAgg, ruleAgg };
}

if (import.meta.main) {
  main().catch((err) => {
    console.error("Eval failed:", err);
    Deno.exit(1);
  });
}
