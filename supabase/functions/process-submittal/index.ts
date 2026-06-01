// =====================================================================
// POST /functions/v1/process-submittal
//
// Body: { submittal_id: string, plan_text?: string, use_llm?: boolean }
//   - If plan_text is provided, use it directly (browser-side OCR/extract)
//   - Otherwise, fetch from submittal_files.extracted_text in the DB
//
// Returns: { triage_run_id, completeness, stats }
//
// This is the main pipeline trigger. Front-end calls this after upload.
// =====================================================================
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import { authenticate, audit, corsResponse, CORS } from "../_shared/auth.ts";
import { makeLlmClient } from "../_shared/llm.ts";
import { runTriage, PIPELINE_VERSION } from "../_shared/triage.ts";
import { surveyJurisdiction, JurisdictionProfile } from "../_shared/surveyor.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return corsResponse({ error: "method not allowed" }, { status: 405 });

  const authed = await authenticate(req);
  if (authed instanceof Response) return authed;
  const { user, supabase, agencyId } = authed;

  let body: {
    submittal_id?: string;
    plan_text?: string;
    use_llm?: boolean;
    use_research?: boolean;
    max_citations?: number;
  };
  try { body = await req.json(); } catch { return corsResponse({ error: "bad body" }, { status: 400 }); }
  if (!body.submittal_id) return corsResponse({ error: "submittal_id required" }, { status: 400 });

  // Verify the submittal belongs to this agency
  const { data: submittal, error: subErr } = await supabase
    .from("submittals")
    .select("id, agency_id, project_name, project_address")
    .eq("id", body.submittal_id)
    .eq("agency_id", agencyId)
    .single();
  if (subErr || !submittal) return corsResponse({ error: "submittal not found" }, { status: 404 });

  // Get the plan text — from request body or DB. Also pull text_blocks
  // (per-page spans with bounding boxes) when available, so findings can
  // carry coordinates back to the dashboard for PDF annotation overlay.
  let planText = body.plan_text;
  let textBlocks: import("../_shared/extract.ts").TextBlock[] = [];
  if (!planText) {
    const { data: files } = await supabase
      .from("submittal_files")
      .select("extracted_text, text_blocks")
      .eq("submittal_id", body.submittal_id);
    planText = (files ?? []).map(f => f.extracted_text || "").join("\n\n");
    for (const f of files ?? []) {
      const tb = f.text_blocks as import("../_shared/extract.ts").TextBlock[] | null;
      if (Array.isArray(tb)) textBlocks.push(...tb);
    }
    if (!planText.trim()) {
      return corsResponse({
        error: "no_text",
        message: "No extracted text on file. Run OCR or upload text first.",
      }, { status: 400 });
    }
  }

  // Load agency rule overrides + custom rules + jurisdiction key + pilot scope
  const { data: agency } = await supabase
    .from("agencies")
    .select("id, custom_rules, rule_overrides, jurisdiction_key, pilot_archetypes")
    .eq("id", agencyId)
    .single();

  // -------- Surveyor: resolve jurisdiction profile + WUI zone --------
  // Done BEFORE triaging so the triage runner gets jurisdiction-aware
  // source hints for each code citation lookup AND the CalFire WUI zone
  // (CA only) is attached to the scope before rule evaluation.
  const jurisdictionKey = (agency?.jurisdiction_key as string | null) ?? "baseline";
  let jurisdictionProfile: JurisdictionProfile | undefined;
  try {
    jurisdictionProfile = await surveyJurisdiction(
      jurisdictionKey,
      submittal.project_address ?? undefined,
      supabase,
    );
  } catch (err) {
    // Non-fatal — triage continues with generic web search if surveyor fails
    console.warn("[process-submittal] surveyor failed:", err);
  }

  // Mark submittal as triaging
  await supabase.from("submittals").update({ status: "triaging" }).eq("id", body.submittal_id);

  // Create the triage_run row first so LLM cost rows can reference it
  const { data: runRow, error: runErr } = await supabase
    .from("triage_runs")
    .insert({
      submittal_id: body.submittal_id,
      agency_id: agencyId,
      pipeline_version: PIPELINE_VERSION,
      report: {},  // filled in below
    })
    .select("id")
    .single();
  if (runErr || !runRow) {
    console.error("could not create triage_run:", runErr);
    return corsResponse({ error: "could not start triage" }, { status: 500 });
  }
  const triageRunId = runRow.id;

  const llm = makeLlmClient();
  const startedAt = Date.now();

  let report;
  try {
    report = await runTriage(
      llm,
      { agencyId, submittalId: body.submittal_id, triageRunId },
      {
        id: agencyId,
        custom_rules: agency?.custom_rules ?? [],
        rule_overrides: agency?.rule_overrides ?? {},
        pilot_archetypes: (agency?.pilot_archetypes as string[] | undefined) as
          import("../_shared/archetype.ts").ProjectArchetype[] | undefined,
      },
      planText,
      {
        useLlm: body.use_llm !== false,
        textBlocks,
        // Live web-search verification of failing critical/major findings.
        // Skipped automatically if useLlm=false (the research step is
        // gated on LLM availability). Caller can disable explicitly via
        // body.use_research = false. Capped at 5 citations per audit
        // because each ~$0.05-0.20.
        research: (body.use_research !== false && body.use_llm !== false) ? {
          supabase,
          jurisdictionKey,
          maxCitations: typeof body.max_citations === "number" ? body.max_citations : 5,
          jurisdictionProfile,   // from Surveyor — enables jurisdiction-aware source routing
        } : undefined,
      },
    );
  } catch (err) {
    console.error("triage failed:", err);
    await supabase.from("submittals").update({ status: "received" }).eq("id", body.submittal_id);
    await supabase.from("triage_runs").delete().eq("id", triageRunId);
    return corsResponse({ error: "triage failed", message: (err as Error).message }, { status: 500 });
  }

  // Calculate llm cost for this run from llm_usage rows
  const { data: usage } = await supabase
    .from("llm_usage")
    .select("cost_usd")
    .eq("triage_run_id", triageRunId);
  const totalCost = (usage ?? []).reduce((s, u) => s + Number(u.cost_usd ?? 0), 0);

  // Persist the report
  await supabase
    .from("triage_runs")
    .update({
      report: report,
      findings_total: report.stats.total,
      findings_fail: report.stats.fail,
      findings_warn: report.stats.warn,
      findings_pass: report.stats.pass,
      completeness_score: report.completeness.score,
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - startedAt,
      llm_calls: usage?.length ?? 0,
      llm_cost_usd: totalCost,
    })
    .eq("id", triageRunId);

  // Cache the headline scope + completeness on the submittal row.
  // Include wui_zone if the Surveyor resolved one (CA projects only).
  // If the archetype gate rejected the submittal, mark the status
  // explicitly so the dashboard can route it to manual triage.
  const finalStatus = report.archetype.in_pilot_scope ? "triaged" : "out_of_pilot_scope";
  await supabase.from("submittals").update({
    status: finalStatus,
    scope: report.scope,   // scope already contains wui_zone from triage.ts enrichment
    project_archetype: report.archetype.archetype,
    archetype_reasoning: {
      in_pilot_scope: report.archetype.in_pilot_scope,
      reasoning: report.archetype.reasoning,
      excluded_overlays: report.archetype.excluded_overlays,
    },
    completeness_score: report.completeness.score,
    triage_grade: report.completeness.grade,
    // Store resolved WUI zone top-level for quick dashboard querying
    ...(jurisdictionProfile?.wuiZone
      ? { wui_zone: jurisdictionProfile.wuiZone }
      : {}),
  }).eq("id", body.submittal_id);

  await audit(
    supabase, agencyId, user.id, "submittal", body.submittal_id,
    report.archetype.in_pilot_scope ? "triaged" : "out_of_pilot_scope",
    {
      triage_run_id: triageRunId,
      project_archetype: report.archetype.archetype,
      in_pilot_scope: report.archetype.in_pilot_scope,
      completeness_score: report.completeness.score,
      grade: report.completeness.grade,
      duration_ms: Date.now() - startedAt,
      llm_cost_usd: totalCost,
    },
  );

  return corsResponse({
    triage_run_id: triageRunId,
    archetype: report.archetype,
    completeness: report.completeness,
    stats: report.stats,
    duration_ms: Date.now() - startedAt,
    llm_cost_usd: totalCost,
  });
});
