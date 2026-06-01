// =====================================================================
// Code corpus search — runtime module for Edge Functions.
//
// Used by the Researcher agent (research.ts) as a fast, cheap first-pass
// before falling back to live web search.
//
// Flow:
//   1. Exact section-ref lookup (zero embedding cost, ~1ms)
//   2. Vector similarity search (one embedding API call, ~100ms, ~$0.001)
//   3. If best similarity < CORPUS_FALLBACK_THRESHOLD → caller falls back
//      to live web search (existing behavior, unchanged)
//
// The corpus is populated offline by scripts/ingest/pipeline.ts.
// This module only reads; it never writes to code_chunks.
//
// Embedding model: OpenAI text-embedding-3-small (1536 dims).
// Requires OPENAI_API_KEY in Edge Function environment.
// =====================================================================

import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

// =====================================================================
// Types
// =====================================================================

export interface CodeChunkResult {
  id: string;
  corpus_key: string;
  jurisdiction_key: string;
  code_name: string;
  chapter: string | null;
  chapter_title: string | null;
  section_ref: string | null;
  section_title: string | null;
  chunk_text: string;
  source_url: string | null;
  similarity: number;
}

export interface CorpusSearchResult {
  chunks: CodeChunkResult[];
  // True when at least one chunk meets the min threshold — caller
  // should use the corpus rather than doing a live web search.
  hitFound: boolean;
  bestSimilarity: number;
  source: "exact_section" | "vector_search" | "none";
}

// =====================================================================
// Constants
// =====================================================================

// Similarity threshold above which we treat a corpus hit as authoritative
// and skip live web search. Tune empirically once the corpus is loaded.
export const CORPUS_CITE_THRESHOLD = 0.78;

// Below this we still return chunks as context hints, but recommend
// the researcher also do a live web search to confirm.
export const CORPUS_FALLBACK_THRESHOLD = 0.65;

const OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings";
const EMBED_MODEL = "text-embedding-3-small";
const EMBED_TIMEOUT_MS = 10_000;

// =====================================================================
// Jurisdiction key expansion
//
// For a city key like 'CA:LOS_ANGELES', we want to search chunks from:
//   - 'CA:LOS_ANGELES' (city-specific amendments)
//   - 'CA'             (state base codes)
//   - 'baseline'       (national IBC/NFPA/NEC/IPC/IMC/IECC)
//   - 'federal'        (ADA — applies everywhere, no state opt-out)
//
// This ensures the researcher always has the right hierarchy. ADA is
// federal law — it applies to every commercial project regardless of
// state adoption, so 'federal' is appended on every query.
// =====================================================================
export function expandJurisdictionKeys(jurisdictionKey: string): string[] {
  if (!jurisdictionKey || jurisdictionKey === "baseline") {
    return ["baseline", "federal"];
  }

  const keys: string[] = [jurisdictionKey];

  // If it's a city key (contains ':'), also include the state
  if (jurisdictionKey.includes(":")) {
    const state = jurisdictionKey.split(":")[0];
    keys.push(state);
  }

  // Always include baseline (national model codes) and federal (ADA)
  keys.push("baseline", "federal");

  return [...new Set(keys)];
}

// =====================================================================
// Embedding generation (OpenAI text-embedding-3-small)
// =====================================================================
async function generateEmbedding(text: string): Promise<number[] | null> {
  const apiKey = Deno.env.get("OPENAI_API_KEY");
  if (!apiKey) {
    console.warn("[corpus] OPENAI_API_KEY not set; skipping corpus search");
    return null;
  }

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort("embed timeout"), EMBED_TIMEOUT_MS);
  try {
    const r = await fetch(OPENAI_EMBED_URL, {
      method: "POST",
      signal: ac.signal,
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: EMBED_MODEL,
        input: text.slice(0, 8192),  // hard token cap
      }),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      console.warn(`[corpus] embed API ${r.status}: ${txt.slice(0, 200)}`);
      return null;
    }
    const j = await r.json();
    return (j.data?.[0]?.embedding as number[]) ?? null;
  } catch (err) {
    console.warn("[corpus] embed failed:", err);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// =====================================================================
// Step 1: Exact section lookup (zero embedding cost)
//
// If the code_ref is a well-formed section reference (e.g. 'CBC 701A.1'),
// try to find it directly in the corpus by exact section_ref match.
// This handles the common case where the triage finding already has a
// precise code reference.
// =====================================================================
async function exactSectionLookup(
  supabase: SupabaseClient,
  sectionRef: string,
  jurisdictionKeys: string[],
): Promise<CodeChunkResult[]> {
  const { data, error } = await supabase
    .rpc("lookup_chunk_by_section", {
      p_section_ref: sectionRef,
      p_jurisdiction_keys: jurisdictionKeys,
    });

  if (error) {
    console.warn("[corpus] exact lookup error:", error.message);
    return [];
  }

  return (data ?? []).map((row: Record<string, unknown>) => ({
    ...row,
    similarity: 1.0,  // exact match = max confidence
  })) as CodeChunkResult[];
}

// =====================================================================
// Step 2: Vector similarity search
// =====================================================================
async function vectorSearch(
  supabase: SupabaseClient,
  queryEmbedding: number[],
  jurisdictionKeys: string[],
  topK: number,
  minSimilarity: number,
): Promise<CodeChunkResult[]> {
  const { data, error } = await supabase
    .rpc("search_code_chunks", {
      query_embedding: queryEmbedding,
      p_jurisdiction_keys: jurisdictionKeys,
      p_match_count: topK,
      p_min_similarity: minSimilarity,
    });

  if (error) {
    console.warn("[corpus] vector search error:", error.message);
    return [];
  }

  return (data ?? []) as CodeChunkResult[];
}

// =====================================================================
// Public API: searchCodeChunks
//
// @param supabase         Supabase client (service role for edge functions)
// @param query            The search query — typically the codeRef + context
// @param options.jurisdictionKey  e.g. 'CA:LOS_ANGELES'
// @param options.topK             How many results to return (default 8)
// @param options.minSimilarity    Minimum similarity threshold (default 0.65)
// =====================================================================
export async function searchCodeChunks(
  supabase: SupabaseClient,
  query: string,
  options: {
    jurisdictionKey: string;
    topK?: number;
    minSimilarity?: number;
    // If provided, first try an exact section ref lookup before vector search.
    // Typically the codeRef from ResearchInput, e.g. 'CBC 701A.1'
    exactSectionRef?: string;
  },
): Promise<CorpusSearchResult> {
  const topK = options.topK ?? 8;
  const minSimilarity = options.minSimilarity ?? CORPUS_FALLBACK_THRESHOLD;
  const jurisdictionKeys = expandJurisdictionKeys(options.jurisdictionKey);

  // ---- Step 1: Exact section lookup (fast path, zero LLM cost) --------
  if (options.exactSectionRef) {
    const exactHits = await exactSectionLookup(
      supabase,
      options.exactSectionRef,
      jurisdictionKeys,
    );
    if (exactHits.length > 0) {
      return {
        chunks: exactHits,
        hitFound: true,
        bestSimilarity: 1.0,
        source: "exact_section",
      };
    }
  }

  // ---- Step 2: Vector search ------------------------------------------
  const embedding = await generateEmbedding(query);
  if (!embedding) {
    return { chunks: [], hitFound: false, bestSimilarity: 0, source: "none" };
  }

  const chunks = await vectorSearch(supabase, embedding, jurisdictionKeys, topK, minSimilarity);
  const bestSimilarity = chunks.length > 0 ? chunks[0].similarity : 0;

  return {
    chunks,
    hitFound: chunks.length > 0 && bestSimilarity >= minSimilarity,
    bestSimilarity,
    source: chunks.length > 0 ? "vector_search" : "none",
  };
}

// =====================================================================
// Render corpus result as context text for the researcher
//
// When the corpus returns high-similarity hits, this text is injected
// into the researcher's context so it can cite directly without a
// live web fetch.
// =====================================================================
export function renderCorpusHits(result: CorpusSearchResult, maxChunks = 3): string {
  if (!result.hitFound || result.chunks.length === 0) return "";

  const lines: string[] = [
    `Corpus search found ${result.chunks.length} relevant section(s) in the pre-indexed code corpus (source: ${result.source}):`,
    "",
  ];

  for (const chunk of result.chunks.slice(0, maxChunks)) {
    const ref = chunk.section_ref ?? chunk.corpus_key;
    const title = chunk.section_title ? ` — ${chunk.section_title}` : "";
    const sim = (chunk.similarity * 100).toFixed(0);
    lines.push(`### ${ref}${title} [${sim}% match]`);
    lines.push(`Source: ${chunk.source_url ?? chunk.code_name}`);
    lines.push(`Jurisdiction: ${chunk.jurisdiction_key}`);
    lines.push("");
    lines.push(chunk.chunk_text.slice(0, 1200));
    if (chunk.chunk_text.length > 1200) lines.push("[…truncated…]");
    lines.push("");
  }

  lines.push(
    result.bestSimilarity >= CORPUS_CITE_THRESHOLD
      ? `Confidence is HIGH (${(result.bestSimilarity * 100).toFixed(0)}% similarity). You may cite the top section directly without a live web fetch.`
      : `Confidence is MODERATE (${(result.bestSimilarity * 100).toFixed(0)}% similarity). Confirm with a live fetch of the source URL before citing.`,
  );

  return lines.join("\n");
}
