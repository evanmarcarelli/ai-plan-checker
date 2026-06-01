// =====================================================================
// Headless-browser fetcher for JS-rendered code-host SPAs.
//
// Municode (library.municode.com) and eCode360 (ecode360.com) serve
// AngularJS / React shells that plain fetch() can't read. This module
// uses astral (https://deno.land/x/astral) to drive a real Chromium
// instance so the SPA actually hydrates before we grab the body text.
//
// Design:
//   - One Chromium process for the whole ingest run; reused across
//     every URL. Spinning up Chromium per-URL would 10x the runtime.
//   - getBrowser() is lazy — Chromium is only launched on first call,
//     so non-SPA hosts (amlegal, direct_gov) keep paying zero.
//   - closeBrowser() must be called by the ingester in a finally so
//     a crash doesn't leak Chromium processes.
//
// First-run cost: astral auto-downloads Chromium to ~/.cache/astral
// (~150 MB). Subsequent runs reuse it. In CI, cache that directory.
//
// Permissions added to the ingester invocation:
//   --allow-env --allow-net --allow-read --allow-write --allow-run
// =====================================================================
import { launch, type Browser, type Page } from "https://deno.land/x/astral@0.4.7/mod.ts";

// =====================================================================
// Singleton browser
// =====================================================================
let browserPromise: Promise<Browser> | null = null;

async function getBrowser(): Promise<Browser> {
  if (browserPromise) return browserPromise;
  browserPromise = launch({
    headless: true,
    args: [
      "--no-sandbox",                  // required in some CI runners
      "--disable-dev-shm-usage",       // avoids /dev/shm crashes in containers
      "--disable-gpu",
      "--disable-background-networking",
    ],
  });
  return browserPromise;
}

export async function closeBrowser(): Promise<void> {
  if (!browserPromise) return;
  try {
    const browser = await browserPromise;
    await browser.close();
  } catch (err) {
    console.warn("[browser_fetch] close() failed:", (err as Error).message);
  } finally {
    browserPromise = null;
  }
}

// =====================================================================
// Fetch options
// =====================================================================
export interface BrowserFetchOptions {
  /** Selector that exists only after content hydrates. When omitted,
   *  we wait for network-idle + a fixed buffer instead. */
  waitForSelector?: string;
  /** Maximum total time for navigation + hydration, milliseconds.
   *  Municode pages typically hydrate in 2-4 s; 30 s gives slow
   *  CI runners plenty of headroom. */
  timeoutMs?: number;
  /** Extra quiet time after network-idle before extracting innerText,
   *  for SPAs that fire one more render tick after the last XHR. */
  postIdleBufferMs?: number;
}

const DEFAULTS: Required<BrowserFetchOptions> = {
  waitForSelector: "",
  timeoutMs: 30_000,
  postIdleBufferMs: 1_500,
};

// =====================================================================
// browserFetchText
//
// Returns body innerText after the SPA hydrates. Matches the contract
// of plain fetchText() in ingest-amendments.ts so the call sites can
// route on host without changing downstream logic.
//
// Returns null on any navigation / timeout / extraction failure. The
// caller's inspectFetchedBody() health check is the authoritative
// "did we actually get code text" gate.
// =====================================================================
export async function browserFetchText(
  url: string,
  options: BrowserFetchOptions = {},
): Promise<string | null> {
  const opts = { ...DEFAULTS, ...options };
  let page: Page | null = null;
  try {
    const browser = await getBrowser();
    page = await browser.newPage();
    // Block heavy assets — we only need the rendered DOM text.
    // astral exposes this via the underlying CDP session.
    await page.goto(url, { waitUntil: "networkidle2", timeout: opts.timeoutMs });

    if (opts.waitForSelector) {
      await page.waitForSelector(opts.waitForSelector, { timeout: opts.timeoutMs });
    } else {
      // No selector hint — give the SPA a beat after network settles.
      await new Promise((r) => setTimeout(r, opts.postIdleBufferMs));
    }

    // Extract visible text. We deliberately use innerText (not textContent)
    // so display:none / aria-hidden boilerplate is excluded.
    const text = await page.evaluate(
      // deno-lint-ignore no-explicit-any
      () => (globalThis as any).document?.body?.innerText ?? "",
    );
    return typeof text === "string" ? text.trim() : null;
  } catch (err) {
    console.warn(`[browser_fetch] ${url} failed: ${(err as Error).message}`);
    return null;
  } finally {
    if (page) {
      try { await page.close(); } catch { /* ignore */ }
    }
  }
}
