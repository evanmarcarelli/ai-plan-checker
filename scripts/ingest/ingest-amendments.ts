#!/usr/bin/env -S deno run --allow-env --allow-net --allow-read
// =====================================================================
// Amendment ingest CLI — Session B: 15 CA city amendment ordinances
//
// Usage:
//   deno run --allow-env --allow-net scripts/ingest/ingest-amendments.ts [options]
//
// Options:
//   --jurisdiction <key>  Only one city (e.g. CA:LOS_ANGELES). Default: all 15.
//   --dry-run             Fetch + chunk; skip embed + DB write.
//   --verbose             Log each chunk.
//   --supabase-url <url>
//   --supabase-key <key>
//   --openai-key  <key>
//
// How it works:
//   1. For each AmendmentSource, fetch the building code chapter URL
//      (Municode / amlegal / direct .gov) using our HTML fetcher.
//   2. Run the same chunker as pipeline.ts, tagging chunks with the
//      city's jurisdiction_key (e.g. 'CA:LOS_ANGELES').
//   3. Also fetch ADU section URLs when present.
//   4. Embed all chunks and upsert to code_chunks.
//
// AMENDMENT-SPECIFIC LOGIC
// ------------------------
// Amendment text on Municode follows a pattern like:
//   "Section 14.04.110 is amended to read as follows: ..."
//   "The following sections are added to Chapter 91: ..."
//   "Section 202 General Definitions — insert the following: ..."
//
// The chunker detects these patterns and adds a flag so the researcher
// knows a chunk is a LOCAL AMENDMENT vs. base code text.
// =====================================================================

import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import { CA_AMENDMENT_SOURCES, AmendmentSource } from "./amendment-sources.ts";
import { chunkDocument, CodeChunk, hashText } from "./chunker.ts";
import { embedAll, EmbedResult } from "./embedder.ts";
import { browserFetchText, closeBrowser } from "./browser_fetch.ts";

// Hosts that serve JS-rendered SPAs and need Chromium to read content.
// Plain hosts (amlegal, direct_gov) stay on fetch() — Chromium isn't free.
function needsJsRendering(host: AmendmentSource["host"]): boolean {
  return host === "municode" || host === "ecode360";
}

// =====================================================================
// CLI args
// =====================================================================
interface CliArgs {
  jurisdictionFilter: string | null;
  dryRun: boolean;
  verbose: boolean;
  supabaseUrl: string;
  supabaseKey: string;
  openaiKey: string;
}

function parseArgs(): CliArgs {
  const args = Deno.args;
  const get = (f: string) => { const i = args.indexOf(f); return i >= 0 ? args[i+1] : null; };
  return {
    jurisdictionFilter: get("--jurisdiction"),
    dryRun:    args.includes("--dry-run"),
    verbose:   args.includes("--verbose"),
    supabaseUrl: get("--supabase-url") ?? Deno.env.get("SUPABASE_URL") ?? "",
    supabaseKey: get("--supabase-key") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    openaiKey:   get("--openai-key")   ?? Deno.env.get("OPENAI_API_KEY") ?? "",
  };
}

// =====================================================================
// Fetch + extract (same as pipeline.ts)
// =====================================================================
const UA = "PlanRoomBot/1.0 (+https://planroom.app/bot)";

async function fetchText(url: string): Promise<string | null> {
  try {
    const r = await fetch(url, {
      headers: { "User-Agent": UA, "Accept": "text/html,*/*;q=0.8" },
      redirect: "follow",
      signal: AbortSignal.timeout(20_000),
    });
    if (!r.ok) return null;
    const html = await r.text();
    return extractText(html);
  } catch { return null; }
}

function extractText(html: string): string {
  let body = html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<head\b[^>]*>[\s\S]*?<\/head>/gi, " ")
    .replace(/<nav\b[^>]*>[\s\S]*?<\/nav>/gi, " ")
    .replace(/<header\b[^>]*>[\s\S]*?<\/header>/gi, " ")
    .replace(/<footer\b[^>]*>[\s\S]*?<\/footer>/gi, " ")
    .replace(/<aside\b[^>]*>[\s\S]*?<\/aside>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ");
  const main = body.match(/<(?:article|main)\b[^>]*>([\s\S]*?)<\/(?:article|main)>/i);
  if (main) body = main[1];
  return body.replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&[a-z0-9#]+;/gi, " ").replace(/\s+/g, " ").trim();
}

// =====================================================================
// SPA / JS-rendered shell detection
//
// Municode, eCode360 and similar hosts serve Angular/React shells that
// look like a 200 OK to fetch() but contain zero code text. Without this
// guard the ingester would either:
//   (a) skip with a misleading "could not fetch" message, or
//   (b) embed boilerplate as if it were code (much worse — pollutes
//       vector search and produces ungrounded citations).
//
// Heuristic: real building-code chapters are large (>= 1000 chars of
// extracted text) and contain at least 2 of the standard code keywords.
// Anything else gets rejected with a loud, host-aware error so the
// operator sees the actual problem (JS rendering, not a network error).
// =====================================================================
const CODE_KEYWORDS = [
  "section", "chapter", "shall", "building", "code", "article",
  "ordinance", "permit",
];
const MIN_REAL_BODY_CHARS = 1000;
const MIN_KEYWORD_HITS = 2;

interface BodyHealth {
  ok: boolean;
  length: number;
  keyword_hits: number;
  reason: string | null;
}

function inspectFetchedBody(text: string | null): BodyHealth {
  if (text == null) {
    return { ok: false, length: 0, keyword_hits: 0, reason: "fetch_failed_or_non_2xx" };
  }
  if (text.length < MIN_REAL_BODY_CHARS) {
    return {
      ok: false,
      length: text.length,
      keyword_hits: 0,
      reason: text.length === 0
        ? "extracted_empty_likely_js_shell"
        : "extracted_too_short_likely_js_shell",
    };
  }
  const lower = text.toLowerCase();
  let hits = 0;
  for (const kw of CODE_KEYWORDS) {
    if (new RegExp(`\\b${kw}\\b`).test(lower)) hits++;
  }
  if (hits < MIN_KEYWORD_HITS) {
    return { ok: false, length: text.length, keyword_hits: hits, reason: "no_code_keywords_likely_landing_page" };
  }
  return { ok: true, length: text.length, keyword_hits: hits, reason: null };
}

// =====================================================================
// Amendment-aware chunk augmentation
//
// Detects if a chunk's text describes a local amendment (vs. base code)
// and prepends a marker so the researcher knows it's jurisdiction-specific.
// =====================================================================
const AMENDMENT_PATTERNS = [
  /is (?:hereby )?amended to read/i,
  /shall be amended by/i,
  /is deleted (?:in its entirety)?/i,
  /is added to (?:read|chapter)/i,
  /following (?:language|text|section) is added/i,
  /local amendment/i,
  /notwithstanding.*CBC/i,
  /in lieu of.*section/i,
];

function isAmendmentText(text: string): boolean {
  return AMENDMENT_PATTERNS.some(re => re.test(text));
}

function augmentAmendmentChunks(chunks: CodeChunk[], cityName: string): CodeChunk[] {
  return chunks.map(c => {
    if (!isAmendmentText(c.chunk_text)) return c;
    return {
      ...c,
      // Prefix with a clear marker so vector search scores city amendments higher
      // for city-specific queries, and the researcher knows it's a local change.
      chunk_text: `[LOCAL AMENDMENT — ${cityName}]\n${c.chunk_text}`,
      // Mark as amendment in the section_title
      section_title: c.section_title
        ? `[Amendment] ${c.section_title}`
        : "[Local Amendment]",
    };
  });
}

// =====================================================================
// Upsert chunks to Supabase
// =====================================================================
async function upsertChunks(
  supabase: SupabaseClient,
  chunks: CodeChunk[],
  embeddings: EmbedResult[],
  dryRun: boolean,
): Promise<{ inserted: number }> {
  if (dryRun || chunks.length === 0) return { inserted: chunks.length };

  const rows = chunks.map((c, i) => ({
    corpus_key:       `AMENDMENTS:${c.jurisdiction_key}`,
    jurisdiction_key: c.jurisdiction_key,
    code_name:        c.code_name,
    part:             c.part,
    chapter:          c.chapter,
    chapter_title:    c.chapter_title,
    section_ref:      c.section_ref,
    section_title:    c.section_title,
    subsection:       c.subsection,
    chunk_text:       c.chunk_text,
    token_count:      c.token_count,
    source_url:       c.source_url,
    code_year:        c.code_year,
    content_hash:     hashText(`${c.jurisdiction_key}::${c.chunk_text}`),
    embedding:        embeddings[i]?.embedding?.length > 0
                        ? JSON.stringify(embeddings[i].embedding)
                        : null,
  }));

  const { error } = await supabase
    .from("code_chunks")
    .upsert(rows, { onConflict: "content_hash", ignoreDuplicates: true });

  if (error) {
    console.error("  [db] upsert error:", error.message);
    return { inserted: 0 };
  }
  return { inserted: rows.length };
}

// Track sources that produced zero ingestable chunks so main() can exit
// non-zero. Without this, a fully-broken ingest looks like a success.
const failedSources: string[] = [];

// =====================================================================
// Process one city
// =====================================================================
async function processAmendmentSource(
  src: AmendmentSource,
  supabase: SupabaseClient,
  args: CliArgs,
): Promise<void> {
  console.log(`\n${"─".repeat(60)}`);
  console.log(`[amend] ${src.cityName} (${src.jurisdictionKey})`);
  console.log(`        ${src.buildingCodeChapterUrl}`);

  const urlsToFetch = [src.buildingCodeChapterUrl];
  if (src.aduSectionUrl) urlsToFetch.push(src.aduSectionUrl);

  const allChunks: CodeChunk[] = [];
  const fetchFailures: Array<{ url: string; reason: string; length: number }> = [];
  const useBrowser = needsJsRendering(src.host);
  if (useBrowser && args.verbose) {
    console.log(`  [fetch] host=${src.host} → routing through headless Chromium`);
  }

  for (const url of urlsToFetch) {
    const text = useBrowser
      ? await browserFetchText(url)
      : await fetchText(url);
    const health = inspectFetchedBody(text);
    if (!health.ok) {
      fetchFailures.push({ url, reason: health.reason ?? "unknown", length: health.length });
      const hostHint = useBrowser
        ? ` (host=${src.host} via headless Chromium still produced no code text — selector may need tuning; see scripts/ingest/INGEST_NOTES.md)`
        : "";
      console.error(
        `  [skip] ${url}\n         reason=${health.reason} extracted_chars=${health.length} keyword_hits=${health.keyword_hits}${hostHint}`,
      );
      continue;
    }

    const rawChunks = chunkDocument(text!, {
      corpusKey: `AMENDMENTS:${src.jurisdictionKey}`,
      jurisdictionKey: src.jurisdictionKey,
      codeName: `${src.cityName} Building Code Amendments`,
      part: null,
      chapter: null,
      chapterTitle: null,
      sourceUrl: url,
      codeYear: src.ibcYear,
    });

    const augmented = augmentAmendmentChunks(rawChunks, src.cityName);
    allChunks.push(...augmented);

    if (args.verbose) {
      console.log(`  [chunk] ${augmented.length} chunks from ${url}`);
      augmented.slice(0, 2).forEach((c, i) => {
        console.log(`    ${i + 1}. ${c.section_ref ?? "—"}: ${c.chunk_text.slice(0, 100)}...`);
      });
    }
  }

  console.log(`  [chunk] Total: ${allChunks.length} chunks for ${src.cityName}`);

  if (allChunks.length === 0) {
    console.error(`  [FAIL] ${src.cityName}: 0 chunks ingested. URL failures:`);
    for (const f of fetchFailures) {
      console.error(`         - ${f.url}  (${f.reason}, ${f.length} chars)`);
    }
    console.error(`         Add this source to the broken-host list once you have a fix path.`);
    failedSources.push(src.jurisdictionKey);
    return;
  }

  if (args.dryRun) {
    console.log(`  [dry-run] Would embed + insert ${allChunks.length} chunks`);
    return;
  }

  // Embed
  console.log(`  [embed] Embedding ${allChunks.length} chunks...`);
  const embeddings: EmbedResult[] = [];
  for await (const batch of embedAll(
    allChunks.map(c => `${c.section_ref ?? ""}\n${c.chunk_text}`),
    args.openaiKey,
    48,   // smaller batch for amendments (they tend to be denser)
  )) {
    embeddings.push(...batch.results);
  }

  const { inserted } = await upsertChunks(supabase, allChunks, embeddings, args.dryRun);
  console.log(`  [done] ${src.cityName}: ${inserted} chunks inserted`);
}

// =====================================================================
// Main
// =====================================================================
async function main() {
  const args = parseArgs();

  if (!args.dryRun && (!args.supabaseUrl || !args.supabaseKey)) {
    console.error("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required");
    Deno.exit(1);
  }
  if (!args.dryRun && !args.openaiKey) {
    console.error("ERROR: OPENAI_API_KEY required (or use --dry-run)");
    Deno.exit(1);
  }

  const supabase = createClient(args.supabaseUrl, args.supabaseKey, {
    auth: { persistSession: false },
  });

  const sources = args.jurisdictionFilter
    ? CA_AMENDMENT_SOURCES.filter(s => s.jurisdictionKey === args.jurisdictionFilter)
    : CA_AMENDMENT_SOURCES;

  if (sources.length === 0) {
    console.error(`No source for: ${args.jurisdictionFilter}`);
    console.error("Available:", CA_AMENDMENT_SOURCES.map(s => s.jurisdictionKey).join(", "));
    Deno.exit(1);
  }

  console.log("\nPlan Room AHJ — Amendment Ingest (Session B)");
  console.log(`Mode: ${args.dryRun ? "DRY RUN" : "LIVE"}`);
  console.log(`Cities: ${sources.map(s => s.cityName).join(", ")}`);
  console.log(`Est. chunks: ~${sources.reduce((n, s) => n + s.estimatedChunks, 0)}`);

  const t0 = Date.now();
  try {
    for (const src of sources) {
      await processAmendmentSource(src, supabase, args);
    }
  } finally {
    // Always release Chromium, even on partial failure, so the process
    // exits cleanly and CI runners don't leak zombie browsers.
    await closeBrowser();
  }

  console.log(`\nAmendment ingest done in ${((Date.now() - t0) / 1000).toFixed(1)}s`);

  if (failedSources.length > 0) {
    console.error(
      `\n[FAIL] ${failedSources.length}/${sources.length} sources produced 0 chunks: ${failedSources.join(", ")}`,
    );
    console.error(`       Exiting non-zero so CI / scripts don't treat this as success.`);
    Deno.exit(2);
  }
}

main().catch(err => { console.error("Fatal:", err); Deno.exit(1); });
