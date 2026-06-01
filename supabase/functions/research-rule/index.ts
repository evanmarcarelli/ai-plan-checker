// =====================================================================
// POST /functions/v1/research-rule
//
// Body: {
//   code_ref: string,                  // e.g., "IBC 1006.3.2"
//   jurisdiction_key?: string,          // 'baseline' | 'WA' | 'WA:SEATTLE'
//   context?: string,                   // optional context to refine the search
//   submittal_id?: string,              // for cost attribution
//   force_refresh?: boolean,            // bypass the cache
// }
//
// Returns: { citation, searches, fetches, iterations, from_cache, duration_ms }
//
// The agent loops: search → fetch → cite, with anti-hallucination
// guardrails that downgrade confidence if the LLM cites text that
// isn't in any page it actually fetched during this session.
// =====================================================================
import { authenticate, corsResponse, CORS } from "../_shared/auth.ts";
import { makeLlmClient } from "../_shared/llm.ts";
import { research } from "../_shared/research.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return corsResponse({ error: "method not allowed" }, { status: 405 });

  const authed = await authenticate(req);
  if (authed instanceof Response) return authed;
  const { agencyId } = authed;

  let body: { code_ref?: string; jurisdiction_key?: string; context?: string; submittal_id?: string; force_refresh?: boolean };
  try { body = await req.json(); } catch { return corsResponse({ error: "bad body" }, { status: 400 }); }
  if (!body.code_ref) return corsResponse({ error: "code_ref required" }, { status: 400 });

  // Resolve the jurisdiction key from the agency if not supplied
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );
  let jurisdictionKey = body.jurisdiction_key;
  if (!jurisdictionKey) {
    const { data: agency } = await supabase.from("agencies").select("jurisdiction_key").eq("id", agencyId).single();
    jurisdictionKey = (agency?.jurisdiction_key as string) ?? "baseline";
  }

  // Optional cache bypass — delete then re-run
  if (body.force_refresh) {
    await supabase.from("code_citations")
      .delete().eq("jurisdiction_key", jurisdictionKey).eq("code_ref", body.code_ref);
  }

  const llm = makeLlmClient();
  const result = await research(llm, supabase,
    { agencyId, submittalId: body.submittal_id },
    {
      jurisdictionKey,
      codeRef: body.code_ref,
      context: body.context,
    },
  );

  return corsResponse({
    citation: result.citation,
    searches: result.searches,
    fetches: result.fetches,
    iterations: result.iterations,
    from_cache: result.fromCache,
    duration_ms: result.durationMs,
  });
});
