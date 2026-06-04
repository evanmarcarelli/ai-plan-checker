# Corpus ingest pipeline

Grows the BM25 code corpus (`../corpus/*.jsonl`) past the hand-curated seed
set by scraping public municipal code and chunking it into the same JSONL
shape the retriever loads.

## Run it

```bash
cd backend
# list configured targets
python -m app.code_library.ingest list
# one jurisdiction, capped for a test run
python -m app.code_library.ingest amlegal --jurisdiction pasadena_ca --max 50
# every amlegal jurisdiction
python -m app.code_library.ingest amlegal --all
```

Output: one `amlegal_<slug>.jsonl` per jurisdiction in `../corpus/`. The
loader picks them up on the next process start (or call
`corpus_loader.reload_corpus()`).

## LADBS publications (Los Angeles — works today, no Cloudflare)

`dbs.lacity.gov` serves its publications as directly-linked public PDFs, so
this path is unblocked and legally clean (public records of a government body).

```bash
cd backend
python -m app.code_library.ingest ladbs --kind corrections --max 20   # examiner correction lists (highest value)
python -m app.code_library.ingest ladbs --kind bulletins   --max 20   # Information Bulletins (code interpretations)
python -m app.code_library.ingest ladbs --kind amendments  --max 20   # LA amendments to the CA codes
python -m app.code_library.ingest ladbs                               # all three kinds
```

Output: `../corpus/ladbs_<kind>.jsonl`, tagged `jurisdictions: ["CA:Los Angeles"]`.

**Review currency before relying on it.** The LADBS publications index mixes
current and *archived* documents (e.g. the amendments page still links 2010
CALGreen / 2007 standards). Spot-check the pulled set and drop stale editions
so the citation gate doesn't verify findings against superseded code text. The
`corrections` and `bulletins` sets are generally the most current.

## Current blocker: Cloudflare (as of 2026-06)

American Legal Publishing (`codelibrary.amlegal.com`) now sits behind a
Cloudflare bot-challenge. Plain HTTP fetches return:

```
403 Forbidden   (cf-mitigated: challenge)
```

The scraper detects this and **stops with a clear message** instead of
silently writing an empty file. A run that hits the challenge produces **0
chunks and leaves any existing corpus file intact** — a failed scrape can no
longer wipe good data (`writer.write_jsonl` refuses to overwrite with empty
and writes atomically via a `.tmp` rename).

To actually pull text you need one of:

1. **A licensed data feed** from the publisher (the clean path — also the
   only one without copyright exposure for republishing code text).
2. **A headless-browser challenge solver** (Playwright/astral) that renders
   the page and passes the JS challenge. This is ToS-gray and is **not**
   wired here on purpose — bypassing a bot-challenge is a deliberate decision
   the operator must own.

Until one of those is in place, grow the corpus by **hand-authoring curated
JSONL** in `../corpus/` (the safe, copyright-clean path the seed set uses).

## Why the corpus matters (and how to measure it)

The citation gate (`../deterministic/citation_gate.py`) will only surface a
code-interpretation finding as hard non-compliant if it can back the citation
with verbatim corpus text. With a thin corpus it downgrades those to
needs-review. The eval harness quantifies the cost exactly:

```bash
python -m scripts.eval.run_eval              # engine only      → F1 1.000
python -m scripts.eval.run_eval --with-gate  # engine + gate    → F1 lower
```

The gap between the two F1 numbers is your corpus-coverage debt. Every
section you add that matches a cited rule closes part of it.
```
