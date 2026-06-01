#!/usr/bin/env -S deno run --allow-env --allow-net --allow-read
// =====================================================================
// Ingest pipeline CLI — Session A: CA base codes
//
// Usage:
//   deno run --allow-env --allow-net scripts/ingest/pipeline.ts [options]
//
// Options:
//   --corpus <key>        Only ingest one corpus (e.g. CBC:2022). Default: all.
//   --dry-run             Fetch + chunk but don't write to DB or embed.
//   --reembed             Re-embed chunks that already have an embedding.
//   --supabase-url <url>  Override SUPABASE_URL env.
//   --supabase-key <key>  Override SUPABASE_SERVICE_ROLE_KEY env.
//   --openai-key  <key>   Override OPENAI_API_KEY env.
//   --concurrency <n>     Simultaneous section fetches (default: 4).
//   --verbose             Log each chunk as it's processed.
//
// Environment variables (can be in .env.local at project root):
//   SUPABASE_URL
//   SUPABASE_SERVICE_ROLE_KEY
//   OPENAI_API_KEY
//
// Example — ingest only CBC Chapter 7A, dry-run first:
//   deno run --allow-env --allow-net scripts/ingest/pipeline.ts \
//     --corpus CBC:2022:7A --dry-run
//
// Then for real:
//   deno run --allow-env --allow-net scripts/ingest/pipeline.ts \
//     --corpus CBC:2022:7A
//
// Full corpus ingest (one-time, ~20 minutes, ~$0.02 in API costs):
//   deno run --allow-env --allow-net scripts/ingest/pipeline.ts
// =====================================================================

import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import { ALL_CODE_SOURCES, CodeSource, totalEstimatedChunks } from "./sources.ts";
import { chunkDocument, CodeChunk, hashText } from "./chunker.ts";
import { embedAll, EmbedResult } from "./embedder.ts";

// =====================================================================
// CLI argument parsing
// =====================================================================
interface CliArgs {
  corpusFilter: string | null;
  dryRun: boolean;
  reembed: boolean;
  supabaseUrl: string;
  supabaseKey: string;
  openaiKey: string;
  concurrency: number;
  verbose: boolean;
}

function parseArgs(): CliArgs {
  const args = Deno.args;
  const get = (flag: string) => {
    const i = args.indexOf(flag);
    return i >= 0 ? args[i + 1] : null;
  };
  const has = (flag: string) => args.includes(flag);

  return {
    corpusFilter:  get("--corpus"),
    dryRun:        has("--dry-run"),
    reembed:       has("--reembed"),
    supabaseUrl:   get("--supabase-url") ?? Deno.env.get("SUPABASE_URL") ?? "",
    supabaseKey:   get("--supabase-key") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    openaiKey:     get("--openai-key")   ?? Deno.env.get("OPENAI_API_KEY") ?? "",
    concurrency:   parseInt(get("--concurrency") ?? "8", 10),
    verbose:       has("--verbose"),
  };
}

// =====================================================================
// Fetch a page and return readable text
// (mirrors the fetchReadable() logic from _shared/search.ts)
// =====================================================================
const USER_AGENT = "PlanRoomBot/1.0 (+https://planroom.app/bot)";
const FETCH_TIMEOUT_MS = 20_000;

async function fetchPageText(url: string): Promise<string | null> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort("fetch timeout"), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(url, {
      signal: ac.signal,
      headers: {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      redirect: "follow",
    });
    if (!r.ok) return null;
    const html = await r.text();
    return extractText(html);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
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

  let text = body.replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&[a-z0-9#]+;/gi, " ")
    .replace(/\s+/g, " ").trim();

  return text;
}

// =====================================================================
// Extract section links from a TOC page
// =====================================================================
function extractSectionLinks(html: string, urlPattern: RegExp, baseUrl: string): string[] {
  const hrefRe = /href="([^"]+)"/gi;
  const urls = new Set<string>();
  let m: RegExpExecArray | null;
  while ((m = hrefRe.exec(html)) !== null) {
    const href = m[1];
    // Resolve relative URLs
    let fullUrl: string;
    try {
      fullUrl = new URL(href, baseUrl).href;
    } catch { continue; }
    if (urlPattern.test(fullUrl)) {
      urls.add(fullUrl);
    }
  }
  return [...urls];
}

// =====================================================================
// Upsert chunks into Supabase (skip duplicates via content_hash)
// =====================================================================
async function upsertChunks(
  supabase: SupabaseClient,
  chunks: CodeChunk[],
  embeddings: EmbedResult[],
  dryRun: boolean,
): Promise<{ inserted: number; skipped: number }> {
  if (dryRun) {
    return { inserted: chunks.length, skipped: 0 };
  }

  const rows = chunks.map((chunk, i) => ({
    corpus_key:       chunk.corpus_key,
    jurisdiction_key: chunk.jurisdiction_key,
    code_name:        chunk.code_name,
    part:             chunk.part,
    chapter:          chunk.chapter,
    chapter_title:    chunk.chapter_title,
    section_ref:      chunk.section_ref,
    section_title:    chunk.section_title,
    subsection:       chunk.subsection,
    chunk_text:       chunk.chunk_text,
    token_count:      chunk.token_count,
    source_url:       chunk.source_url,
    code_year:        chunk.code_year,
    content_hash:     chunk.content_hash,
    embedding:        embeddings[i]?.embedding?.length > 0
                        ? JSON.stringify(embeddings[i].embedding)
                        : null,
  }));

  const { error } = await supabase
    .from("code_chunks")
    .upsert(rows, {
      onConflict: "content_hash",
      ignoreDuplicates: true,
    });

  if (error) {
    console.error("  [db] upsert error:", error.message);
    return { inserted: 0, skipped: chunks.length };
  }

  return { inserted: rows.length, skipped: 0 };
}

// =====================================================================
// Process one code source
// =====================================================================
async function processSource(
  source: CodeSource,
  supabase: SupabaseClient,
  args: CliArgs,
): Promise<void> {
  console.log(`\n${"=".repeat(64)}`);
  console.log(`[ingest] ${source.corpusKey} — ${source.codeName}`);
  console.log(`         TOC: ${source.tocUrl}`);
  console.log(`         Est. ${source.estimatedChunks} chunks`);

  // Fetch the TOC page to get section links
  console.log("  [fetch] TOC page...");
  const tocResponse = await fetch(source.tocUrl, {
    headers: { "User-Agent": USER_AGENT },
  }).catch(() => null);

  if (!tocResponse?.ok) {
    console.error(`  [skip] Could not fetch TOC: ${source.tocUrl}`);
    return;
  }

  const tocHtml = await tocResponse.text();
  const sectionUrls = extractSectionLinks(
    tocHtml,
    source.sectionUrlPattern,
    source.tocUrl,
  );

  // Filter by chapter inclusion/exclusion list
  const filtered = sectionUrls.filter(url => {
    if (source.chaptersToSkip?.some(ch => url.includes(ch))) return false;
    if (source.chaptersToInclude?.length) {
      return source.chaptersToInclude.some(ch => url.includes(ch));
    }
    return true;
  });

  // Priority sort: earlier slugs in chaptersToInclude fetch first.
  // Source authors order the include list with rule-cited chapters
  // first (e.g. IBC chapter-5 / chapter-10 before admin chapters),
  // so the corpus is useful even mid-ingest if the run is interrupted.
  const priorityIndex = (url: string): number => {
    const includes = source.chaptersToInclude;
    if (!includes?.length) return 0;
    for (let i = 0; i < includes.length; i++) {
      if (url.includes(includes[i])) return i;
    }
    return includes.length;  // unmatched URLs to the back
  };
  filtered.sort((a, b) => priorityIndex(a) - priorityIndex(b));

  // If no links found (JavaScript-rendered site), treat TOC text as one chunk
  const urlsToFetch = filtered.length > 0 ? filtered : [source.tocUrl];
  console.log(`  [fetch] Found ${urlsToFetch.length} section URLs to ingest`);

  let totalChunks = 0;
  let totalInserted = 0;
  const allChunks: CodeChunk[] = [];

  // Fetch sections in fixed-size batches. Promise.allSettled means one
  // 404 or hung connection doesn't sink the whole batch — failures are
  // logged per-URL but the run continues.
  const batchSize = Math.max(1, args.concurrency);
  for (let i = 0; i < urlsToFetch.length; i += batchSize) {
    const batch = urlsToFetch.slice(i, i + batchSize);
    const results = await Promise.allSettled(batch.map(async (url) => {
      if (args.verbose) console.log(`  [fetch] ${url}`);
      const text = await fetchPageText(url);
      if (!text) return { url, chunks: [] as CodeChunk[] };

      const chapterMatch = url.match(/chapter-([^/]+)/i);
      const chapter = chapterMatch ? `Chapter ${chapterMatch[1].toUpperCase()}` : null;

      const chunks = chunkDocument(text, {
        corpusKey: source.corpusKey,
        jurisdictionKey: source.jurisdictionKey,
        codeName: source.codeName,
        part: source.part,
        chapter,
        chapterTitle: null,
        sourceUrl: url,
        codeYear: source.codeYear,
      });
      return { url, chunks };
    }));

    for (const r of results) {
      if (r.status === "fulfilled") {
        allChunks.push(...r.value.chunks);
        if (args.verbose && r.value.chunks.length) {
          console.log(`    → ${r.value.chunks.length} chunks from ${r.value.url}`);
        }
      } else {
        console.warn(`  [fetch] failed:`, r.reason);
      }
    }

    if (!args.verbose) {
      const done = Math.min(i + batchSize, urlsToFetch.length);
      console.log(`  [fetch] progress ${done}/${urlsToFetch.length} (${allChunks.length} chunks so far)`);
    }
  }
  totalChunks += allChunks.length;
  console.log(`  [chunk] ${totalChunks} chunks extracted`);

  if (allChunks.length === 0) {
    console.warn("  [warn] No chunks extracted — section URLs may be JS-rendered");
    console.warn("         Consider downloading official PDFs and using --text-file mode");
    return;
  }

  if (args.dryRun) {
    console.log(`  [dry-run] Would embed and insert ${totalChunks} chunks (skipped)`);
    if (args.verbose) {
      allChunks.slice(0, 3).forEach((c, i) => {
        console.log(`\n  Chunk ${i + 1}: ${c.section_ref ?? "no ref"} — ${c.chunk_text.slice(0, 120)}...`);
      });
    }
    return;
  }

  // Embed in batches
  console.log(`  [embed] Embedding ${allChunks.length} chunks...`);
  const allEmbeddings: EmbedResult[] = [];

  for await (const batch of embedAll(
    allChunks.map(c => `${c.section_ref ?? ""}\n${c.chunk_text}`),
    args.openaiKey,
  )) {
    allEmbeddings.push(...batch.results);
  }

  // Upsert to DB
  console.log(`  [db] Upserting ${allChunks.length} chunks...`);
  const { inserted, skipped } = await upsertChunks(
    supabase, allChunks, allEmbeddings, args.dryRun,
  );
  totalInserted += inserted;

  console.log(`  [done] ${source.corpusKey}: ${totalInserted} inserted, ${skipped} skipped (duplicates)`);
}

// =====================================================================
// Main
// =====================================================================
async function main() {
  const args = parseArgs();

  if (!args.supabaseUrl || !args.supabaseKey) {
    console.error("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required");
    console.error("Set them as env vars or pass --supabase-url / --supabase-key");
    Deno.exit(1);
  }
  if (!args.openaiKey && !args.dryRun) {
    console.error("ERROR: OPENAI_API_KEY is required for embedding (or use --dry-run)");
    Deno.exit(1);
  }

  const supabase = createClient(args.supabaseUrl, args.supabaseKey, {
    auth: { persistSession: false },
  });

  const sources = args.corpusFilter
    ? ALL_CODE_SOURCES.filter(s => s.corpusKey === args.corpusFilter)
    : ALL_CODE_SOURCES;

  if (sources.length === 0) {
    console.error(`No source found for corpus key: ${args.corpusFilter}`);
    console.error("Available keys:", ALL_CODE_SOURCES.map(s => s.corpusKey).join(", "));
    Deno.exit(1);
  }

  console.log(`\nPlan Room AHJ — Code Corpus Ingest Pipeline`);
  console.log(`Mode: ${args.dryRun ? "DRY RUN" : "LIVE"}`);
  console.log(`Sources: ${sources.map(s => s.corpusKey).join(", ")}`);
  console.log(`Est. total chunks: ${sources.reduce((n, s) => n + s.estimatedChunks, 0)}`);
  console.log(`Est. embed cost: ~$${(sources.reduce((n, s) => n + s.estimatedChunks, 0) * 500 / 1_000_000 * 0.02).toFixed(4)}`);

  const t0 = Date.now();

  for (const source of sources) {
    await processSource(source, supabase, args);
  }

  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`\n${"=".repeat(64)}`);
  console.log(`Ingest complete in ${elapsed}s`);

  if (!args.dryRun) {
    // Show final corpus stats
    const { data: stats } = await supabase.from("corpus_stats").select("*");
    if (stats?.length) {
      console.log("\nCorpus stats:");
      console.table(stats.map(s => ({
        corpus: s.corpus_key,
        jurisdiction: s.jurisdiction_key,
        chunks: s.active_chunks,
        pending_embed: s.pending_embed,
      })));
    }
  }
}

main().catch(err => {
  console.error("Fatal:", err);
  Deno.exit(1);
});
