// =====================================================================
// POST /functions/v1/draft-comment
//
// Body: {
//   review_id: string,           // the active review
//   finding_id?: string,         // optional triage finding to base the draft on
//   code_ref?: string,           // override / supply
//   reviewer_note?: string,      // rough reviewer note ("egress capacity short")
//   severity?: 'correction_required' | 'clarification' | 'advisory',
// }
//
// Returns: { body: string, code_ref: string, severity: string }
//
// Does NOT save the comment — front-end shows the draft, reviewer edits,
// then a separate POST to /save-comment commits it (handled by direct
// Supabase insert from the reviewer dashboard).
// =====================================================================
import { authenticate, corsResponse, CORS } from "../_shared/auth.ts";
import { makeLlmClient } from "../_shared/llm.ts";

const COMMENT_SCHEMA = {
  type: "object",
  properties: {
    body: { type: "string" },
    code_ref: { type: "string" },
    severity: { type: "string", enum: ["correction_required", "clarification", "advisory"] },
  },
  required: ["body", "code_ref", "severity"],
};

const COMMENT_SYSTEM = `You are a senior plan-check reviewer at a city building department,
drafting a formal correction comment that will be sent to the applicant.

Format guide:
- Open with "Provide" or "Clarify" or "Confirm" — never with the deficiency itself.
- Cite the specific code section, including subsection number when relevant.
- State what is missing or incorrect, then state what the applicant must do.
- Keep it to 1-3 sentences. Polite, technical, neutral. Never accusatory.
- Do NOT offer a design solution — only state what the code requires and what
  the applicant must provide.
- Do NOT include the comment number or any preamble — just the body text.

Severity guide:
- correction_required: a code-required item is missing or non-compliant.
- clarification: information is needed to determine compliance.
- advisory: not blocking approval, but the reviewer recommends attention.

Examples of good comment bodies:

  "Provide a code analysis sheet that identifies the occupancy classification,
  construction type, allowable area, and allowable height per IBC Tables 506.2
  and 504.4."

  "Clarify the discrepancy in stated occupant load: the cover sheet indicates
  220, while the life-safety plan shows 320. Per IBC 1004, the higher value
  governs unless a separate calculation is provided."

  "The exit door schedule shows 36-inch clear width at the main entry, which
  provides 36 inches of egress capacity. Per IBC 1005.3.2, the design occupant
  load of 580 requires a minimum of 116 inches of door egress capacity. Provide
  additional exits or revise door widths."

Respond with JSON only, matching the schema. No preamble, no commentary.`;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return corsResponse({ error: "method not allowed" }, { status: 405 });

  const authed = await authenticate(req, { requiredRoles: ["admin", "supervisor", "reviewer"] });
  if (authed instanceof Response) return authed;
  const { user, supabase, agencyId } = authed;

  let body: {
    review_id?: string;
    finding_id?: string;
    code_ref?: string;
    reviewer_note?: string;
    severity?: "correction_required" | "clarification" | "advisory";
  };
  try { body = await req.json(); } catch { return corsResponse({ error: "bad body" }, { status: 400 }); }
  if (!body.review_id) return corsResponse({ error: "review_id required" }, { status: 400 });

  // Load context: the review, its submittal, the triage report
  const { data: review } = await supabase
    .from("reviews")
    .select("id, submittal_id, triage_run_id, agency_id")
    .eq("id", body.review_id)
    .eq("agency_id", agencyId)
    .single();
  if (!review) return corsResponse({ error: "review not found" }, { status: 404 });

  const { data: submittal } = await supabase
    .from("submittals")
    .select("project_name, project_address, scope")
    .eq("id", review.submittal_id)
    .single();

  // If the reviewer pointed at a specific triage finding, dig it out
  let finding: Record<string, unknown> | null = null;
  if (body.finding_id && review.triage_run_id) {
    const { data: run } = await supabase
      .from("triage_runs")
      .select("report")
      .eq("id", review.triage_run_id)
      .single();
    const findings = (run?.report as { findings?: Array<Record<string, unknown>> })?.findings ?? [];
    finding = findings.find((f) => f.rule_id === body.finding_id) ?? null;
  }

  const llm = makeLlmClient();

  const userMsg =
`Project: ${submittal?.project_name || "(unnamed)"} at ${submittal?.project_address || "(no address)"}.

${finding ? `The system flagged this rule:
  rule_id:    ${finding.rule_id}
  code_ref:   ${finding.code_ref}
  severity:   ${finding.severity}
  finding:    ${finding.summary}
  description:${finding.description}
${(finding as { citation?: { text: string; source_url: string; source_title: string; confidence: number } }).citation
  ? `\nVerified code text (retrieved live from ${(finding as { citation: { source_title: string } }).citation.source_title}, confidence ${(finding as { citation: { confidence: number } }).citation.confidence}):
  "${(finding as { citation: { text: string } }).citation.text.slice(0, 500)}"
Source: ${(finding as { citation: { source_url: string } }).citation.source_url}
Use this verified text when constructing your citation. Quote it minimally and accurately.`
  : ""}
` : ""}

${body.reviewer_note ? `Reviewer's rough note: ${body.reviewer_note}` : ""}

${body.code_ref ? `Cite this code section: ${body.code_ref}` : ""}

${body.severity ? `Severity should be: ${body.severity}` : ""}

Draft the comment body the reviewer should send to the applicant. If the
reviewer's note conflicts with the system finding, defer to the reviewer's
note (the reviewer has eyes on the drawings; the system only sees text).`;

  try {
    const draft = await llm.structured<{ body: string; code_ref: string; severity: string }>(
      { agencyId, submittalId: review.submittal_id, purpose: "draft_comment" },
      {
        tier: "balanced",
        system: COMMENT_SYSTEM,
        user: userMsg,
        schema: COMMENT_SCHEMA,
      },
    );
    return corsResponse(draft);
  } catch (err) {
    console.error("draft-comment failed:", err);
    return corsResponse({ error: "draft failed", message: (err as Error).message }, { status: 500 });
  }
});
