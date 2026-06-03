// =====================================================================
// POST /functions/v1/resolve-ambiguity
//
// Body: { submittal_id: string, ambiguity_id: string, value: unknown }
//
// Loads the most recent triage_runs row for the submittal, finds the
// matching ambiguity in report.scope.ambiguities by id, writes the
// reviewer's answer into resolved_value / resolved_at / resolved_by,
// then re-invokes process-submittal so findings reflect the resolved
// scope. Full re-triage on every resolve is the v1 cut — partial
// re-triage (only rules whose checker depends on the resolved field)
// is a follow-up ticket per the A2 commit.
//
// Returns: { ok: true, ambiguity, retriaged }
//
// Auth: caller must belong to the agency owning the submittal.
// =====================================================================
import { authenticate, audit, corsResponse, CORS } from "../_shared/auth.ts";
import type { Ambiguity } from "../_shared/extract.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return corsResponse({ error: "method not allowed" }, { status: 405 });

  const authed = await authenticate(req);
  if (authed instanceof Response) return authed;
  const { user, supabase, agencyId } = authed;

  let body: { submittal_id?: string; ambiguity_id?: string; value?: unknown };
  try { body = await req.json(); } catch { return corsResponse({ error: "bad body" }, { status: 400 }); }
  if (!body.submittal_id) return corsResponse({ error: "submittal_id required" }, { status: 400 });
  if (!body.ambiguity_id) return corsResponse({ error: "ambiguity_id required" }, { status: 400 });

  // Latest triage_runs row for this submittal — agency-scoped so a
  // member of another agency can't poke at it even with a guessed id.
  const { data: run, error: runErr } = await supabase
    .from("triage_runs")
    .select("id, report")
    .eq("submittal_id", body.submittal_id)
    .eq("agency_id", agencyId)
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (runErr || !run) {
    return corsResponse({ error: "no triage run for this submittal" }, { status: 404 });
  }

  // Clone the report so we can mutate in place without aliasing the row.
  const report = JSON.parse(JSON.stringify(run.report ?? {})) as {
    scope?: { ambiguities?: (string | Ambiguity)[] };
  };
  const ambList = report?.scope?.ambiguities ?? [];

  let updated: Ambiguity | null = null;
  for (let i = 0; i < ambList.length; i++) {
    const a = ambList[i];
    if (typeof a !== "object" || a === null) continue;
    if (a.id !== body.ambiguity_id) continue;
    a.resolved_value = body.value;
    a.resolved_at = new Date().toISOString();
    a.resolved_by = user.id;
    updated = a;
    break;
  }

  if (!updated) {
    return corsResponse({ error: "ambiguity not found in latest run" }, { status: 404 });
  }

  const { error: updErr } = await supabase
    .from("triage_runs")
    .update({ report })
    .eq("id", run.id);

  if (updErr) {
    console.error("[resolve-ambiguity] db update failed:", updErr);
    return corsResponse({ error: "db update failed", message: updErr.message }, { status: 500 });
  }

  await audit(
    supabase,
    agencyId,
    user.id,
    "triage_runs",
    run.id,
    "ambiguity_resolved",
    { ambiguity_id: updated.id, field: updated.field, value: body.value },
  );

  // Kick a fresh process-submittal so findings recompute against the
  // resolved scope. Best-effort: if the invoke fails the resolve still
  // sticks and the reviewer can manually re-trigger triage from the UI.
  let retriaged = false;
  try {
    const fnUrl = `${Deno.env.get("SUPABASE_URL")}/functions/v1/process-submittal`;
    const auth = req.headers.get("Authorization") ?? "";
    const resp = await fetch(fnUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": auth,
        "X-Agency-Id": agencyId,
      },
      body: JSON.stringify({ submittal_id: body.submittal_id }),
    });
    retriaged = resp.ok;
    if (!resp.ok) {
      console.warn("[resolve-ambiguity] re-triage non-OK:", resp.status, await resp.text());
    }
  } catch (err) {
    console.warn("[resolve-ambiguity] re-triage failed:", err);
  }

  return corsResponse({ ok: true, ambiguity: updated, retriaged });
});
