// =====================================================================
// Researcher agent.
//
// Goal: given a (jurisdiction, code_ref, finding_summary) tuple, find
// the actual code text that governs and produce a verified citation:
//   { citation_text, source_url, source_title, confidence, notes }
//
// How it works (LLM tool-use loop):
//   1. The LLM is given a goal and three tools (search, fetch, cite).
//   2. It searches the web for authoritative sources, fetches the most
//      promising pages, and emits a final `cite` call with a quoted
//      passage from one of the fetched pages.
//   3. We validate the citation: the quoted text MUST appear verbatim
//      in one of the pages we fetched. Citations failing this check
//      are rejected (anti-hallucination guardrail).
//
// Caching: results are stored in code_citations keyed on
// (jurisdiction_key, code_ref). A cache hit short-circuits the loop.
// =====================================================================
import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import { LlmClient, ToolCall, ToolResult } from "./llm.ts";
import { webSearch, fetchReadable, SearchResult, FetchedPage, SEARCH_COST_PER_QUERY } from "./search.ts";
import { JurisdictionProfile, renderProfileForResearcher } from "./surveyor.ts";
import {
  searchCodeChunks, renderCorpusHits,
  CORPUS_CITE_THRESHOLD, CORPUS_FALLBACK_THRESHOLD,
} from "./corpus.ts";

export interface CodeCitation {
  citation_text: string;
  source_url: string;
  source_title: string;
  source_domain: string;
  confidence: number;
  notes?: string;
  // For audit / cache
  jurisdiction_key: string;
  code_ref: string;
}

export interface ResearchInput {
  jurisdictionKey: string;         // 'baseline' | 'WA' | 'WA:SEATTLE' | 'CA:LOS_ANGELES'
  codeRef: string;                  // 'IBC 1006.3.2' | 'LAMC 91.1.1' | 'CBC 7A-101' etc.
  context?: string;                 // e.g. the rule description, the finding summary
  jurisdictionProfile?: JurisdictionProfile; // from Surveyor — if present, researcher uses
                                             // jurisdiction-specific sources instead of generic search
}

export interface ResearchResult {
  citation: CodeCitation | null;
  searches: number;
  fetches: number;
  iterations: number;
  fromCache: boolean;
  durationMs: number;
}

const RESEARCHER_SYSTEM = `You are a building-code research assistant. Your job is to find the
authoritative text of a specific code section and produce a verified citation
the user can quote. You have three tools:

  search(query)             → returns the top web results (title + URL + snippet)
  fetch_page(url)           → returns the readable text of a webpage
  cite(citation_text, source_url, source_title, confidence, notes)
                            → records your final answer

Process:
  1. When a jurisdiction profile is provided (see below), try those sources
     FIRST — use the search hint to construct a site-scoped query, or fetch
     the baseUrl directly. Only fall back to generic web search if those
     sources don't contain the section you need.
  2. Without a profile, search the web for the specific code reference and
     jurisdiction. Prefer searches that include the code-section number AND
     the city/state.
  3. Prefer .gov, library.municode.com, ecode360.com, codepublishing.com,
     and up.codes over generic sites.
  4. Fetch the most authoritative-looking result. Read it.
  5. If the page contains the relevant code text, call cite() with a
     verbatim quoted passage (max 600 characters) and your confidence
     (0.0-1.0).
  6. If the page does not contain the section you need, fetch a
     different result OR search again with a refined query.

Hard rules:
  - The "citation_text" you submit MUST appear verbatim in a page you
    fetched. Do NOT paraphrase. Do NOT invent.
  - If you cannot find the section after 2 searches and 3 fetches,
    call cite() with confidence 0 and notes explaining what you found.
  - Do NOT cite from memory. Always retrieve.
  - Prefer the most jurisdiction-specific source: a city amendment beats
    a state code, which beats the generic IBC.

ICC copyright notice:
  IBC (International Building Code) text is copyrighted by the ICC. You
  MAY cite short verbatim passages (≤ 200 characters) for fair-use purposes
  when quoting from a legally-hosted source like up.codes or iccsafe.org.
  For longer passages, summarize in plain language and cite the section
  number — do NOT reproduce extended IBC text verbatim. This restriction
  does NOT apply to state codes (CBC, WSBC, NYSBC etc.) or municipal codes,
  which are public domain.

When you have a citation, call cite() once and stop.`;

const RESEARCHER_TOOLS = [
  {
    name: "search",
    description: "Search the web for authoritative code references. Returns up to 8 results with title/url/snippet.",
    input_schema: {
      type: "object" as const,
      properties: {
        query: { type: "string", description: "Search query, e.g. 'IBC 1006.3.2 minimum exits Chicago'" },
      },
      required: ["query"],
    },
  },
  {
    name: "fetch_page",
    description: "Fetch and extract the readable text of a webpage. Returns the page title and main body text.",
    input_schema: {
      type: "object" as const,
      properties: {
        url: { type: "string", description: "Full URL of the page to fetch" },
      },
      required: ["url"],
    },
  },
  {
    name: "cite",
    description: "Record the final verified citation and end the research session. Call this ONCE when done.",
    input_schema: {
      type: "object" as const,
      properties: {
        citation_text: { type: "string", description: "Verbatim quoted code text. MUST appear in a page you fetched." },
        source_url:    { type: "string", description: "URL of the page you quoted from" },
        source_title:  { type: "string", description: "Title of that page" },
        confidence:    { type: "number", description: "0.0–1.0 confidence the citation is correct + jurisdiction-applicable" },
        notes:         { type: "string", description: "Optional reviewer notes (e.g., 'amended by Seattle SMC 22.100.020')" },
      },
      required: ["citation_text", "source_url", "source_title", "confidence"],
    },
  },
];

export async function research(
  llm: LlmClient,
  supabase: SupabaseClient,
  ctx: { agencyId?: string; submittalId?: string; triageRunId?: string },
  input: ResearchInput,
): Promise<ResearchResult> {
  const t0 = Date.now();
  const { jurisdictionKey, codeRef, context = "", jurisdictionProfile } = input;

  // -------- 1. Cache lookup ----------------------------------------
  const { data: cached } = await supabase
    .from("code_citations")
    .select("citation_text, source_url, source_title, source_domain, confidence, notes, expires_at")
    .eq("jurisdiction_key", jurisdictionKey)
    .eq("code_ref", codeRef)
    .gt("expires_at", new Date().toISOString())
    .eq("is_primary", true)
    .order("retrieved_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (cached) {
    return {
      citation: {
        citation_text: cached.citation_text,
        source_url: cached.source_url,
        source_title: cached.source_title ?? "",
        source_domain: cached.source_domain ?? "",
        confidence: Number(cached.confidence),
        notes: cached.notes ?? undefined,
        jurisdiction_key: jurisdictionKey,
        code_ref: codeRef,
      },
      searches: 0,
      fetches: 0,
      iterations: 0,
      fromCache: true,
      durationMs: Date.now() - t0,
    };
  }

  // -------- 1b. Corpus first-pass (fast, cheap) --------------------
  // Before spinning up the full LLM tool-use loop, check the pre-indexed
  // vector corpus for a high-confidence section match.
  //
  //   similarity ≥ CORPUS_CITE_THRESHOLD (0.78):
  //     Synthesize a citation directly from the corpus chunk, write to
  //     code_citations, and return — no LLM calls at all.  ~$0.001 vs
  //     ~$0.10+ for the full researcher loop.
  //
  //   CORPUS_FALLBACK_THRESHOLD ≤ similarity < CORPUS_CITE_THRESHOLD:
  //     Inject the corpus text as a context hint so the LLM researcher
  //     can cite it or confirm via a live fetch.
  let corpusHintBlock = "";
  {
    const corpusResult = await searchCodeChunks(supabase, `${codeRef}\n${context}`, {
      jurisdictionKey,
      exactSectionRef: codeRef,
      topK: 4,
    }).catch(e => {
      console.warn("[research] corpus search error:", (e as Error).message);
      return null;
    });

    if (corpusResult?.hitFound) {
      if (corpusResult.bestSimilarity >= CORPUS_CITE_THRESHOLD) {
        // High-confidence corpus hit — return without LLM
        const best = corpusResult.chunks[0];
        let domain = "";
        try { domain = new URL(best.source_url ?? "").hostname; } catch { /* ignore */ }

        const citation: CodeCitation = {
          citation_text:    best.chunk_text.slice(0, 600),
          source_url:       best.source_url ?? "",
          source_title:     [best.section_ref, best.section_title].filter(Boolean).join(" — ")
                            || best.code_name,
          source_domain:    domain,
          confidence:       Math.round(corpusResult.bestSimilarity * 100) / 100,
          notes:            `[Corpus] ${best.code_name} · ${corpusResult.source} · ${(corpusResult.bestSimilarity * 100).toFixed(0)}% similarity`,
          jurisdiction_key: jurisdictionKey,
          code_ref:         codeRef,
        };

        // Cache the corpus-derived citation
        await supabase.from("code_citations").insert({
          agency_id:        ctx.agencyId ?? null,
          jurisdiction_key: jurisdictionKey,
          code_ref:         codeRef,
          citation_text:    citation.citation_text,
          source_url:       citation.source_url,
          source_title:     citation.source_title,
          source_domain:    citation.source_domain,
          confidence:       citation.confidence,
          verifier_model:   "corpus:text-embedding-3-small",
          notes:            citation.notes,
          is_primary:       true,
        }).catch(() => { /* non-fatal; don't break the response path */ });

        return {
          citation,
          searches:    0,
          fetches:     0,
          iterations:  0,
          fromCache:   false,
          durationMs:  Date.now() - t0,
        };
      }

      // Moderate corpus hit — inject as context for the LLM loop
      if (corpusResult.bestSimilarity >= CORPUS_FALLBACK_THRESHOLD) {
        corpusHintBlock = "\n\n" + renderCorpusHits(corpusResult, 3);
      }
    }
  }

  // -------- 2. Set up tool execution + tracking --------------------
  // Track every page we fetch so we can verify citation quotes.
  const fetchedPages: Map<string, FetchedPage> = new Map();
  let searchCount = 0;
  let fetchCount = 0;
  let pendingCitation: { citation_text: string; source_url: string; source_title: string; confidence: number; notes?: string } | null = null;

  async function executeTool(call: ToolCall): Promise<ToolResult> {
    if (call.name === "search") {
      searchCount++;
      const query = String(call.input.query ?? "");
      try {
        const results = await webSearch(query, 8);
        const slim = results.slice(0, 8).map((r: SearchResult) => ({
          url: r.url, title: r.title, snippet: r.snippet, authority: r.authority,
        }));
        return { tool_use_id: call.id, content: JSON.stringify(slim) };
      } catch (err) {
        return { tool_use_id: call.id, content: `search failed: ${(err as Error).message}`, is_error: true };
      }
    }
    if (call.name === "fetch_page") {
      fetchCount++;
      const url = String(call.input.url ?? "");
      try {
        const page = await fetchReadable(url);
        if (page.status >= 400) {
          return { tool_use_id: call.id, content: `fetch failed: HTTP ${page.status}`, is_error: true };
        }
        fetchedPages.set(page.url, page);
        // Trim to keep token use manageable; the LLM rarely needs more than 8KB
        const trimmed = page.text.slice(0, 8000);
        const truncMsg = page.text.length > 8000 ? "\n[…truncated…]" : "";
        return {
          tool_use_id: call.id,
          content: JSON.stringify({
            url: page.url, title: page.title,
            text: trimmed + truncMsg, fetched_bytes: page.bytes,
          }),
        };
      } catch (err) {
        return { tool_use_id: call.id, content: `fetch failed: ${(err as Error).message}`, is_error: true };
      }
    }
    if (call.name === "cite") {
      pendingCitation = call.input as typeof pendingCitation;
      return { tool_use_id: call.id, content: JSON.stringify({ acknowledged: true }) };
    }
    return { tool_use_id: call.id, content: "unknown tool", is_error: true };
  }

  // -------- 3. Run the loop ----------------------------------------
  // Build jurisdiction-aware context block (from Surveyor profile if available)
  const profileBlock = jurisdictionProfile
    ? `\n\n${renderProfileForResearcher(jurisdictionProfile)}`
    : "";

  const initialUser =
`Find the authoritative code text for the following.

Jurisdiction: ${jurisdictionKey}
Code reference: ${codeRef}
${context ? `Context: ${context}` : ""}${profileBlock}${corpusHintBlock}

Search for it using the jurisdiction-specific sources above (if provided). Read the most authoritative source. Cite a verbatim quoted passage.`;

  const loop = await llm.runToolLoop<{ ok: true } | null>(
    { agencyId: ctx.agencyId, submittalId: ctx.submittalId, triageRunId: ctx.triageRunId, purpose: "research_rule" },
    {
      tier: "balanced",
      system: RESEARCHER_SYSTEM,
      initialUser,
      tools: RESEARCHER_TOOLS,
      executeTool,
      maxIterations: 6,
      timeoutMs: 90_000,
      parseFinal: () => ({ ok: true }),
    },
  );

  // -------- 4. Validate the citation -------------------------------
  let citation: CodeCitation | null = null;
  if (pendingCitation) {
    const c = pendingCitation as { citation_text: string; source_url: string; source_title: string; confidence: number; notes?: string };
    const page = fetchedPages.get(c.source_url);
    let confidence = Number(c.confidence ?? 0);
    let notes = c.notes ?? "";

    if (!page) {
      // The model cited a URL it never fetched — anti-hallucination guard.
      confidence = 0;
      notes = `[GUARD] Citation source_url was not fetched during this session. ${notes}`;
    } else {
      // Quote-presence check: does the citation_text actually appear in the page?
      const hay = page.text.toLowerCase().replace(/\s+/g, " ");
      const needle = (c.citation_text ?? "").toLowerCase().replace(/\s+/g, " ").trim();
      // Allow partial — require at least 40 contiguous chars present
      const sample = needle.slice(0, Math.min(120, needle.length));
      if (sample.length < 20 || !hay.includes(sample.slice(0, 40))) {
        confidence = Math.min(confidence, 0.3);
        notes = `[GUARD] Quoted text not found verbatim in fetched page; downgraded confidence. ${notes}`;
      }
    }

    let domain = "";
    try { domain = new URL(c.source_url).hostname; } catch { /* ignore */ }

    citation = {
      citation_text: c.citation_text,
      source_url: c.source_url,
      source_title: c.source_title,
      source_domain: domain,
      confidence,
      notes: notes || undefined,
      jurisdiction_key: jurisdictionKey,
      code_ref: codeRef,
    };

    // Cache it (only if confidence > 0; we don't want to memoize failures)
    if (confidence > 0) {
      await supabase.from("code_citations").insert({
        agency_id: jurisdictionKey.includes(":") ? ctx.agencyId : null,
        jurisdiction_key: jurisdictionKey,
        code_ref: codeRef,
        citation_text: citation.citation_text,
        source_url: citation.source_url,
        source_title: citation.source_title,
        source_domain: citation.source_domain,
        confidence: citation.confidence,
        verifier_model: "claude-sonnet-4-6",
        notes: citation.notes,
        is_primary: true,
      });
    }
  }

  // -------- 5. Log the research run --------------------------------
  await supabase.from("research_runs").insert({
    agency_id: ctx.agencyId ?? null,
    submittal_id: ctx.submittalId ?? null,
    triage_run_id: ctx.triageRunId ?? null,
    goal: `verify ${codeRef} for ${jurisdictionKey}`,
    jurisdiction_key: jurisdictionKey,
    code_ref: codeRef,
    iterations: loop.iterations,
    searches_made: searchCount,
    pages_fetched: fetchCount,
    citations_found: citation && citation.confidence > 0 ? 1 : 0,
    search_cost_usd: searchCount * SEARCH_COST_PER_QUERY,
    succeeded: !!(citation && citation.confidence > 0),
    outcome_summary: citation
      ? (citation.confidence > 0 ? "verified" : "could not verify (confidence 0)")
      : "no citation produced",
    completed_at: new Date().toISOString(),
    duration_ms: Date.now() - t0,
  });

  return {
    citation: citation && citation.confidence > 0 ? citation : null,
    searches: searchCount,
    fetches: fetchCount,
    iterations: loop.iterations,
    fromCache: false,
    durationMs: Date.now() - t0,
  };
}
