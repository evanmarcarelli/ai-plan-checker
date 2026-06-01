// =====================================================================
// Shared types + auth helpers for AHJ edge functions
// =====================================================================
import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

export const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

export function corsResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...CORS,
      ...(init.headers ?? {}),
    },
  });
}

export interface AuthedRequest {
  user: { id: string; email: string };
  supabase: SupabaseClient;       // service-role client
  agencyId: string;               // resolved & validated
  role: string;                   // member role within that agency
}

/**
 * Authenticate the request, resolve which agency the user is acting on
 * (via X-Agency-Id header or body field), and verify membership + role.
 */
export async function authenticate(
  req: Request,
  options: { requiredRoles?: string[] } = {},
): Promise<AuthedRequest | Response> {
  const auth = req.headers.get("Authorization") ?? "";
  const jwt = auth.replace(/^Bearer\s+/i, "");
  if (!jwt) return corsResponse({ error: "missing auth" }, { status: 401 });

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );

  const { data, error } = await supabase.auth.getUser(jwt);
  if (error || !data?.user) {
    return corsResponse({ error: "invalid token" }, { status: 401 });
  }

  const url = new URL(req.url);
  const fromHeader = req.headers.get("X-Agency-Id");
  const fromQuery = url.searchParams.get("agency_id");
  const agencyId = fromHeader || fromQuery || "";
  if (!agencyId) {
    return corsResponse({ error: "missing X-Agency-Id" }, { status: 400 });
  }

  const { data: member } = await supabase
    .from("agency_members")
    .select("role")
    .eq("user_id", data.user.id)
    .eq("agency_id", agencyId)
    .maybeSingle();

  if (!member) {
    return corsResponse({ error: "not a member of this agency" }, { status: 403 });
  }
  if (options.requiredRoles && !options.requiredRoles.includes(member.role)) {
    return corsResponse({ error: "insufficient role" }, { status: 403 });
  }

  return {
    user: { id: data.user.id, email: data.user.email ?? "" },
    supabase,
    agencyId,
    role: member.role,
  };
}

/**
 * Append an audit-log entry. Best-effort; never throws.
 */
export async function audit(
  sb: SupabaseClient,
  agencyId: string,
  actorId: string | null,
  entity: string,
  entityId: string | null,
  action: string,
  diff: unknown = null,
): Promise<void> {
  try {
    await sb.from("audit_log").insert({
      agency_id: agencyId,
      actor_id: actorId,
      entity_type: entity,
      entity_id: entityId,
      action,
      diff,
    });
  } catch (err) {
    console.warn("audit log failed:", err);
  }
}
