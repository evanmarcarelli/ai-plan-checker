// =====================================================================
// Web search + fetch client.
//
// Uses Brave Search API for queries (cleaner than scraping Google,
// has a generous free tier, and unlike Google doesn't require pre-
// approval to index .gov sites at scale). Falls back to Bing/Serper
// if BRAVE_API_KEY is unset.
//
// Also exposes a polite fetcher with a hard size limit and an HTML-
// to-readable-text extractor so we don't pass 500KB of nav chrome
// to the LLM.
// =====================================================================

export interface SearchResult {
  url: string;
  title: string;
  snippet: string;
  // Heuristic authority score: .gov > municode/ecode > generic
  authority: number;
}

const TRUSTED_DOMAINS = [
  // Authoritative free sources for code text
  ".gov",
  "law.cornell.edu",
  "codepublishing.com",
  "library.municode.com",
  "municode.com",
  "ecode360.com",
  "amlegal.com",
  "publicaccess.dla.mil",
  "iccsafe.org",          // ICC public read-only previews
  "ashrae.org",
  "nfpa.org",             // free read-only access
  "energy.gov",
];

function authorityScore(url: string): number {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.endsWith(".gov")) return 1.0;
    for (const d of TRUSTED_DOMAINS) {
      if (host.includes(d.replace(/^\./, ""))) return 0.85;
    }
    if (host.includes("upcodes.com")) return 0.7;
    return 0.4;
  } catch {
    return 0.3;
  }
}

// =====================================================================
// Search providers
// =====================================================================
async function searchBrave(query: string, count: number): Promise<SearchResult[]> {
  const key = Deno.env.get("BRAVE_API_KEY");
  if (!key) throw new Error("BRAVE_API_KEY not set");

  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}&safesearch=moderate`;
  const r = await fetch(url, {
    headers: {
      "Accept": "application/json",
      "X-Subscription-Token": key,
      "Accept-Encoding": "gzip",
    },
  });
  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`brave search ${r.status}: ${txt.slice(0, 200)}`);
  }
  const j = await r.json();
  const items = (j.web?.results ?? []) as Array<{ url: string; title: string; description: string }>;
  return items.map((it) => ({
    url: it.url,
    title: it.title ?? "",
    snippet: it.description ?? "",
    authority: authorityScore(it.url),
  }));
}

async function searchSerper(query: string, count: number): Promise<SearchResult[]> {
  const key = Deno.env.get("SERPER_API_KEY");
  if (!key) throw new Error("SERPER_API_KEY not set");

  const r = await fetch("https://google.serper.dev/search", {
    method: "POST",
    headers: { "X-API-KEY": key, "Content-Type": "application/json" },
    body: JSON.stringify({ q: query, num: count }),
  });
  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`serper search ${r.status}: ${txt.slice(0, 200)}`);
  }
  const j = await r.json();
  const items = (j.organic ?? []) as Array<{ link: string; title: string; snippet: string }>;
  return items.map((it) => ({
    url: it.link,
    title: it.title ?? "",
    snippet: it.snippet ?? "",
    authority: authorityScore(it.link),
  }));
}

// =====================================================================
// Public: webSearch
// =====================================================================
export async function webSearch(query: string, count = 10): Promise<SearchResult[]> {
  // Prefer Brave (cleaner data + better .gov coverage), fall back to Serper
  let results: SearchResult[] = [];
  try {
    results = await searchBrave(query, count);
  } catch (err) {
    if (Deno.env.get("SERPER_API_KEY")) {
      try { results = await searchSerper(query, count); }
      catch (err2) { console.warn("both search providers failed:", err, err2); throw err2; }
    } else {
      throw err;
    }
  }
  // Sort by authority then by original rank
  return results
    .map((r, i) => ({ ...r, _rank: i }))
    .sort((a, b) => b.authority - a.authority || a._rank - b._rank)
    .map(({ _rank: _, ...r }) => r);
}

// =====================================================================
// Web fetcher with readable-text extraction
// =====================================================================
const FETCH_TIMEOUT_MS = 15_000;
const MAX_BYTES = 500_000;          // 500KB cap per page
const USER_AGENT = "PlanRoomBot/1.0 (+https://planroom.app/bot)";

export interface FetchedPage {
  url: string;
  status: number;
  title: string;
  text: string;            // readable text, nav/footer/script stripped
  bytes: number;
  truncated: boolean;
}

export async function fetchReadable(url: string): Promise<FetchedPage> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort("timeout"), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(url, {
      signal: ac.signal,
      headers: {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      redirect: "follow",
    });
    if (!r.ok) {
      return { url, status: r.status, title: "", text: "", bytes: 0, truncated: false };
    }
    const reader = r.body?.getReader();
    if (!reader) return { url, status: r.status, title: "", text: "", bytes: 0, truncated: false };

    let bytes = 0;
    const chunks: Uint8Array[] = [];
    let truncated = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > MAX_BYTES) {
        truncated = true;
        await reader.cancel();
        break;
      }
      chunks.push(value);
    }

    const html = new TextDecoder().decode(concatChunks(chunks));
    const { title, text } = extractReadable(html);
    return { url, status: r.status, title, text, bytes, truncated };
  } finally {
    clearTimeout(timer);
  }
}

function concatChunks(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((n, c) => n + c.byteLength, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.byteLength; }
  return out;
}

// =====================================================================
// Readable-text extraction
//
// Removes <script>, <style>, <nav>, <header>, <footer>, <aside>;
// keeps the visible text of <article>, <main>, <section>, body.
// Not as good as Mozilla Readability but works without a DOM lib.
// =====================================================================
function extractReadable(html: string): { title: string; text: string } {
  const titleMatch = html.match(/<title[^>]*>([^<]*)<\/title>/i);
  const title = (titleMatch?.[1] ?? "").trim();

  // Strip the obviously non-content tags (and their content)
  let body = html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript\b[^>]*>[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<head\b[^>]*>[\s\S]*?<\/head>/gi, " ")
    .replace(/<svg\b[^>]*>[\s\S]*?<\/svg>/gi, " ")
    .replace(/<nav\b[^>]*>[\s\S]*?<\/nav>/gi, " ")
    .replace(/<header\b[^>]*>[\s\S]*?<\/header>/gi, " ")
    .replace(/<footer\b[^>]*>[\s\S]*?<\/footer>/gi, " ")
    .replace(/<aside\b[^>]*>[\s\S]*?<\/aside>/gi, " ")
    .replace(/<form\b[^>]*>[\s\S]*?<\/form>/gi, " ")
    // Remove HTML comments
    .replace(/<!--[\s\S]*?-->/g, " ");

  // Prefer <main> or <article> contents if present
  const main = body.match(/<(article|main)\b[^>]*>([\s\S]*?)<\/\1>/i);
  if (main) body = main[2];

  // Strip remaining tags
  let text = body.replace(/<[^>]+>/g, " ");
  // Decode common HTML entities
  text = text
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&[a-z0-9#]+;/gi, " ");
  // Collapse whitespace
  text = text.replace(/\s+/g, " ").trim();
  return { title, text };
}

// =====================================================================
// Cost tracking helpers
// =====================================================================
export const SEARCH_COST_PER_QUERY = 0.005;   // Brave free-tier estimate
export const FETCH_COST_PER_PAGE   = 0;        // free
