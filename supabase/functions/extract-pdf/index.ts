// =====================================================================
// POST /functions/v1/extract-pdf
//
// Body: { submittal_file_id: string }
//
// Pulls the PDF from Supabase Storage (the path lives on the
// submittal_files row), runs pdfjs against it, and writes back:
//   - extracted_text (with [PAGE:N] markers)
//   - text_blocks    (normalized bounding boxes, top-left origin)
//   - page_count
//   - has_text_layer
//
// Returns: { ok: true, page_count, blocks, has_text_layer }
//
// Auth: the caller must belong to the agency that owns the file.
// =====================================================================
import { authenticate, corsResponse, CORS } from "../_shared/auth.ts";
import { extractPdf } from "../_shared/pdf_extract.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return corsResponse({ error: "method not allowed" }, { status: 405 });

  const authed = await authenticate(req);
  if (authed instanceof Response) return authed;
  const { supabase, agencyId } = authed;

  let body: { submittal_file_id?: string };
  try { body = await req.json(); } catch { return corsResponse({ error: "bad body" }, { status: 400 }); }
  if (!body.submittal_file_id) {
    return corsResponse({ error: "submittal_file_id required" }, { status: 400 });
  }

  // Fetch the row first so we can a) confirm agency ownership and b) get the storage_path.
  const { data: file, error: fileErr } = await supabase
    .from("submittal_files")
    .select("id, agency_id, storage_path, mime_type, page_count")
    .eq("id", body.submittal_file_id)
    .single();

  if (fileErr || !file) return corsResponse({ error: "file not found" }, { status: 404 });
  if (file.agency_id !== agencyId) {
    return corsResponse({ error: "forbidden" }, { status: 403 });
  }

  // `supabase` from authenticate() is already the service-role client
  // — sufficient for Storage downloads and the row update below.
  const { data: blob, error: dlErr } = await supabase
    .storage
    .from("submittals")
    .download(file.storage_path);

  if (dlErr || !blob) {
    console.error("[extract-pdf] storage download failed:", dlErr);
    return corsResponse({ error: "download failed", message: dlErr?.message }, { status: 502 });
  }

  const bytes = new Uint8Array(await blob.arrayBuffer());

  let result;
  try {
    result = await extractPdf(bytes);
  } catch (err) {
    console.error("[extract-pdf] pdfjs failed:", err);
    return corsResponse({ error: "pdf parse failed", message: (err as Error).message }, { status: 500 });
  }

  // Persist back. Update only the fields this extractor produces — don't
  // touch ocr_required / ocr_completed_at (Textract owns those).
  const { error: updErr } = await supabase
    .from("submittal_files")
    .update({
      extracted_text: result.extracted_text,
      text_blocks: result.text_blocks,
      page_count: result.page_count,
      has_text_layer: result.has_text_layer,
    })
    .eq("id", body.submittal_file_id);

  if (updErr) {
    console.error("[extract-pdf] db update failed:", updErr);
    return corsResponse({ error: "db update failed", message: updErr.message }, { status: 500 });
  }

  return corsResponse({
    ok: true,
    page_count: result.page_count,
    blocks: result.text_blocks.length,
    has_text_layer: result.has_text_layer,
  });
});
