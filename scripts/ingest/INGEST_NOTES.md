# Ingest Notes

How the amendment ingester actually retrieves text from each
`host` type, what's known to work, and what to do when a source
breaks.

## Fetcher routing (current)

| `host`        | Fetcher                          | Notes |
|---------------|----------------------------------|-------|
| `municode`    | Headless Chromium (astral)       | Path A. SPA — plain `fetch()` returns 6 KB Angular shell. |
| `ecode360`    | Headless Chromium (astral)       | Also a SPA. Wired the same way as Municode. |
| `amlegal`     | Plain `fetch()`                  | Server-rendered; works as-is. |
| `direct_gov`  | Plain `fetch()`                  | PDFs / static HTML; works as-is. |

Routing logic lives in [ingest-amendments.ts](ingest-amendments.ts)
at `needsJsRendering(host)`. The browser is launched lazily by
[browser_fetch.ts](browser_fetch.ts) — non-SPA-only runs pay zero
Chromium cost.

## Path A — astral / headless Chromium

**What it does:** spins up one Chromium process per ingest run,
navigates to each SPA URL, waits for `networkidle2` plus 1.5 s for
the SPA to render the final tick, then extracts `document.body.innerText`.

**First-run cost:** astral auto-downloads Chromium (~150 MB) to
`~/.cache/astral`. Subsequent runs reuse it. In CI, the
[`ingest-amendments.yml`](/.github/workflows/ingest-amendments.yml)
workflow caches that directory.

**Per-page latency:** ~5–10 s vs. <1 s for plain fetch. For the two
pilot jurisdictions (LA City + Ventura County, ~3 URLs each), total
runtime is well under 2 minutes.

**Per-source selector override:** if a host renders content into a
specific element and we want a tighter wait than network-idle, pass
`{ waitForSelector: "article.chunk-content" }` to `browserFetchText()`
in the per-source loop. Today none of the sources need this — the
network-idle default works for both Municode and eCode360.

**Permissions added to the ingester invocation:**
```
--allow-env --allow-net --allow-read --allow-write --allow-run
```
The `--allow-run` is for spawning Chromium.

## Loud failures, not silent ones

`inspectFetchedBody()` in `ingest-amendments.ts` enforces two
sanity checks on every fetched URL (whether plain or headless):

1. Extracted text ≥ 1000 chars
2. ≥ 2 of these tokens present: `section`, `chapter`, `shall`,
   `building`, `code`, `article`, `ordinance`, `permit`

A failure logs `[skip] <url>` with a host-aware hint, and any
source that produces 0 chunks gets added to `failedSources`. The
ingester exits non-zero (code 2) when `failedSources` is non-empty
so CI / scripts don't treat a fully-broken ingest as success.

## When a Municode page stops working

Most likely cause: Municode shipped a new SPA build with a
different render contract. Diagnose in this order:

1. **Re-run with `--verbose`** and look at the `[skip]` log — does it
   say `extracted_too_short_likely_js_shell`? If the page just hasn't
   hydrated by the time we read `body.innerText`, bump
   `postIdleBufferMs` in `browser_fetch.ts`.
2. **Open the URL in a real browser, take a snapshot of the rendered
   DOM**, and find the selector that wraps the actual code text. Pass
   it as `{ waitForSelector: "..." }` in the call site.
3. **If Municode added auth/captcha**, Path A is over for them. Fall
   back to Path C (switch the affected sources to amlegal /
   direct_gov mirrors where available).

## What's verified vs. not (as of 2026-05-30)

- ✅ **Plain `fetch()` failure on Municode** verified live — returns
  Angular shell, `extractText` produces 0 chars
- ✅ **Routing logic** wired through `needsJsRendering(host)`
- ✅ **CLI exits non-zero** when any source produces 0 chunks
- ⚠️ **astral end-to-end on a live Municode page** NOT yet run from
  this machine (Deno not installed locally). First real test will be
  the user triggering the `ingest-amendments` workflow with
  `dry_run: true` against LA City + Ventura County.
- ⚠️ **Overlay annotation** (`amendments.ts → applyAmendmentNote`)
  has been jurisdiction-generic since shipped; it will activate for
  Ventura the moment Ventura chunks land in `code_chunks`. Not yet
  observed live because the corpus is empty for Ventura.

## Next failure modes to watch for

- Municode rate-limiting if we ever scale past ~50 URLs/run
- astral's Chromium binary going stale (re-download with
  `rm -rf ~/.cache/astral` if downloads or navigation start failing)
- Municode requiring cookie consent — would surface as a 0-chunk
  failure; fix is a `page.click()` on the accept-cookies button
  before the wait, added per-host

## Historical: why this file exists

Before 2026-05-30, the ingester silently produced 0 chunks for every
Municode source and reported success. That left the entire amendment
corpus empty for 13 of 15 sources without any operator-visible
signal. The fix had three parts: loud-failure guards (done), Path A
fetcher (done), and this doc so the next failure isn't silent again.
