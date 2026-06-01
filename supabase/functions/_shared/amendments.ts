// =====================================================================
// Local amendment overlay — jurisdiction-generic.
//
// Every CA city adopts the 2022 CBC and then amends it. A generic-CBC
// answer is silently wrong on amended sections — and the wrong section
// is the one most likely to show up in a comment letter. This module
// asks the corpus a focused question for every code_ref the pipeline
// cares about:
//
//   "For jurisdiction X, is there an amendment to <section> we know about?"
//
// If yes, we attach an `amendment_note` to the finding so the reviewer
// sees, inline with the citation, that the local amendment took over.
//
// Scope: works for ANY jurisdiction_key — LA, Ventura County, San
// Francisco, etc. The only thing that varies between jurisdictions is
// whether `code_chunks` actually has rows for that key (populated by
// scripts/ingest/ingest-amendments.ts). When the corpus is empty for
// a given jurisdiction this module returns "no amendment" cleanly —
// no error, just an unannotated finding that defers to base CBC.
//
// Implementation:
//   - Vector code corpus (migration 0004) stores chunks keyed on
//     jurisdiction_key. e.g. 'CA:LOS_ANGELES' / 'CA:VENTURA_COUNTY'
//     chunks are the local amendments; 'CA' chunks are the base CBC.
//   - For each finding's code_ref we look up the most-specific
//     jurisdiction key in the fallback chain. A hit on the same (or
//     overlapping) section_ref means there's an amendment to surface.
//   - No LLM involved — this is a pure lookup.
//
// Cost: 1 RPC call per finding being annotated. ~2 ms. Skipped
// entirely for the synthetic 'baseline' jurisdiction.
// =====================================================================
import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import type { Finding } from "./evaluate.ts";

export interface AmendmentLookupResult {
  has_amendment: boolean;
  jurisdiction_key: string;
  base_section_ref: string;
  amended_section_ref: string | null;
  amended_text_excerpt: string | null;
  amended_source_url: string | null;
}

// Normalize a code_ref to a section number we can look up in the corpus.
// "IBC Table 506.2" → "506.2"
// "CBC Chapter 7A · CA Gov Code §51182" → "7A" (first applicable token)
// "IBC 1006.3.2" → "1006.3.2"
// Returns null when we can't extract a recognizable section token.
function extractSectionToken(codeRef: string): string | null {
  // Prefer dotted numeric like 1006.3.2 or 506.2 first
  const dotted = codeRef.match(/\b(\d{2,4}(?:\.\d+)+)\b/);
  if (dotted) return dotted[1];
  // Chapter token like "7A" or "Chapter 5"
  const chapter = codeRef.match(/Chapter\s+(\d+[A-Z]?)/i);
  if (chapter) return chapter[1].toUpperCase();
  // Standalone numeric section
  const numeric = codeRef.match(/\b(\d{3,4})\b/);
  if (numeric) return numeric[1];
  return null;
}

// Build the list of jurisdiction keys to probe, most-specific first.
// "CA:LOS_ANGELES" → ['CA:LOS_ANGELES', 'CA', 'baseline']
function jurisdictionFallbackChain(key: string): string[] {
  const chain: string[] = [key];
  if (key.includes(":")) {
    chain.push(key.split(":")[0]);   // state
  }
  if (key !== "baseline") chain.push("baseline");
  return chain;
}

/**
 * Look up whether the local jurisdiction has an amendment to the cited
 * code section. Designed to be called once per finding right before the
 * full research step.
 *
 * @returns AmendmentLookupResult, or null if we couldn't probe (e.g.,
 *          unparseable code_ref or RPC error). Callers should treat
 *          null as "no amendment data available" — do NOT escalate.
 */
export async function lookupAmendment(
  supabase: SupabaseClient,
  jurisdictionKey: string,
  codeRef: string,
): Promise<AmendmentLookupResult | null> {
  // Only meaningful for non-baseline jurisdictions
  if (jurisdictionKey === "baseline") return null;
  const section = extractSectionToken(codeRef);
  if (!section) return null;

  const chain = jurisdictionFallbackChain(jurisdictionKey);
  // Probe the most-specific key (e.g. CA:LOS_ANGELES) for any chunk
  // whose section_ref contains our token. The corpus' section_ref is
  // free-form text like "LABC 506.2" or "CBC 1006.3.2"; we substring-
  // match the dotted token rather than requiring an exact code_ref hit.
  // pg_trgm would be ideal here; we settle for ilike for now.
  try {
    const { data, error } = await supabase
      .from("code_chunks")
      .select("section_ref, chunk_text, source_url, jurisdiction_key")
      .eq("jurisdiction_key", chain[0])
      .ilike("section_ref", `%${section}%`)
      .is("superseded_at", null)
      .limit(1);

    if (error) {
      console.warn("[amendments] lookup failed:", error.message);
      return null;
    }
    if (!data || data.length === 0) {
      return {
        has_amendment: false,
        jurisdiction_key: chain[0],
        base_section_ref: section,
        amended_section_ref: null,
        amended_text_excerpt: null,
        amended_source_url: null,
      };
    }
    const hit = data[0];
    return {
      has_amendment: true,
      jurisdiction_key: hit.jurisdiction_key,
      base_section_ref: section,
      amended_section_ref: hit.section_ref,
      amended_text_excerpt: (hit.chunk_text ?? "").slice(0, 400),
      amended_source_url: hit.source_url ?? null,
    };
  } catch (err) {
    console.warn("[amendments] exception:", (err as Error).message);
    return null;
  }
}

/**
 * Annotate a finding in-place with amendment context, if any was found.
 * Adds a human-readable note to `finding.citation.notes` so the reviewer
 * sees the amendment alongside the cited section.
 */
export function applyAmendmentNote(
  finding: Finding,
  amendment: AmendmentLookupResult | null,
): void {
  if (!amendment?.has_amendment) return;
  const banner = `[LOCAL AMENDMENT — ${amendment.jurisdiction_key}] ` +
    `Section ${amendment.amended_section_ref ?? amendment.base_section_ref} is locally amended; ` +
    `verify against the amended text, not the base code.`;
  if (finding.citation) {
    finding.citation.notes = finding.citation.notes
      ? `${banner} · ${finding.citation.notes}`
      : banner;
  } else {
    // No citation yet — surface in the summary so the reviewer is not
    // misled by a base-code-only mental model.
    finding.summary = `${finding.summary} ${banner}`;
  }
}
