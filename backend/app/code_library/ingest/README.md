# Corpus ingest pipeline

Grows the BM25 code corpus (`../corpus/*.jsonl`) past the hand-curated seed
set by scraping public municipal code and chunking it into the same JSONL
shape the retriever loads.

## Sources covered

| Publisher | Module | Hosts | LA County coverage |
|-----------|--------|-------|--------------------|
| American Legal Publishing | `amlegal.py` | codelibrary.amlegal.com | Pasadena, Long Beach, Glendale, Burbank, Santa Monica, Beverly Hills, West Hollywood, Culver City, Inglewood, Compton, Torrance, Alhambra, Arcadia, Monrovia, Claremont, Pomona, West Covina, Covina, Glendora, San Gabriel, Monterey Park, Rosemead, Temple City, Sierra Madre, La Cañada Flintridge, South Pasadena, San Fernando, Santa Clarita, Lancaster, Palmdale |
| Municode | `municode.py` | library.municode.com | **LA city (LAMC)**, **LA County (unincorporated)**, Malibu, Calabasas, Agoura Hills, Westlake Village, Hidden Hills, Carson, Cerritos, Lakewood, Bellflower, Paramount, Downey, South Gate, Lynwood, Norwalk, La Mirada, Whittier, Pico Rivera, Montebello, Commerce, Santa Fe Springs, Bell, Bell Gardens, Maywood, Cudahy, Huntington Park, Vernon, Gardena, Lawndale, Hawthorne, El Monte, South El Monte, Baldwin Park, Irwindale, Azusa, Duarte, Bradbury, La Verne, San Dimas, Diamond Bar, Walnut, City of Industry, La Puente, Hawaiian Gardens, Artesia, Signal Hill, Avalon |
| Quality Code Publishing | `qcode.py` | qcode.us | Hermosa Beach, Manhattan Beach, Redondo Beach, El Segundo, Palos Verdes Estates, Rancho Palos Verdes, Rolling Hills, Rolling Hills Estates, Lomita, San Marino, La Habra Heights |
| General Code | `ecode360.py` | ecode360.com | (placeholder — verify slugs before use) |
| LADBS publications | `ladbs.py` | dbs.lacity.gov | LA City information bulletins, correction lists, amendments |
| **Licensed code PDFs** | `licensed_pdf.py` | local files (ICC purchase, state-published editions) | IBC / IFC / CBC / CRC / any ICC-style code the operator holds a license for |

> **Neighborhoods of Los Angeles** (Hollywood, Venice, Silver Lake, Echo Park,
> Studio City, etc.) are **not separate jurisdictions** — they sit inside the
> City of LA and are governed by the LAMC plus LADBS bulletins. They do not
> need separate ingester entries.

## Run it

```bash
cd backend

# show every configured target, flagging which are in LA County
python -m app.code_library.ingest list

# one jurisdiction, capped for a test run
python -m app.code_library.ingest amlegal  --jurisdiction pasadena_ca   --max 50
python -m app.code_library.ingest municode --jurisdiction losangeles_ca --max 50
python -m app.code_library.ingest qcode    --jurisdiction hermosabeach  --max 50

# every target for one publisher
python -m app.code_library.ingest amlegal  --all
python -m app.code_library.ingest municode --all

# THE LA WEDGE: every LA County jurisdiction across every publisher + LADBS
python -m app.code_library.ingest la-county

# cap chunks per jurisdiction while you verify slugs
python -m app.code_library.ingest la-county --max 25

# skip LADBS if you only want the municipal codes
python -m app.code_library.ingest la-county --skip-ladbs
```

Output: one `<publisher>_<slug>.jsonl` per jurisdiction in `../corpus/`. The
loader picks them up on the next process start (or call
`corpus_loader.reload_corpus()`).

## Slug verification (one-time, per jurisdiction)

The yaml ships with best-effort slugs marked `# verify`. Before running each
publisher's `--all`, do one pass to confirm the URL each slug resolves to.
Quick smoke test:

```bash
# Run a tiny --max so a wrong slug fails fast and cheap
python -m app.code_library.ingest municode --jurisdiction calabasas_ca --max 5
```

If you see `404` or `failed to load root TOC`, the slug is wrong. Open the
publisher's search UI, find the city, and update the `source_id` in
`jurisdictions.yaml`. Once it returns sections, drop the `# verify` comment.

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

**Currency guard (automatic).** The ingester skips any doc whose detected
edition year predates `MIN_EDITION_YEAR` (2022) — so a 2010 CALGreen or 2007
standards PDF can no longer land in the corpus and let the citation gate
"verify" findings against dead code.

**Known limitation — static pages only expose the archive (verified
2026-06).** All three public LADBS landing pages (`bulletins`, `corrections`,
`amendments`) resolve via static HTML to the *same* ~13 archive PDFs (mostly
2007–2013 editions, filtered out by the guard). The genuinely current docs —
the live Information Bulletins (e.g. P/GI 2023-026) and current Standard
Correction Lists — sit behind the site's **dynamic bulletin database / search
UI**, which one-level static scraping does not reach. Net yield from the
public static pages after the guard: ~1–2 current docs. **Meaningful LA corpus
growth needs one of:**
  1. a **headless-browser fetch** (Playwright/astral) that renders the
     bulletin-database pages (the same Path-A approach the Cloudflare note
     describes), or
  2. the **licensed 2025 CBC / Title 24 text** (ICC Digital Codes), or
  3. **hand-curated JSONL** for the specific current bulletins you care about.

## Licensed code PDFs (the compliant IBC / CBC / CRC path)

`licensed_pdf.py` ingests a model-code PDF the operator is **licensed to
use** — a purchased ICC PDF, a state-published edition, or a jurisdiction's
own published amendments. It parses the conventional ICC structure
(CHAPTER → SECTION → numbered subsections, with Exception detection), keeps
the hierarchy as the breadcrumb, and writes standard corpus chunks tagged
`source_tier/license_status = "licensed"` (which `jsonl_to_postgres`
preserves):

```bash
cd backend
python -m app.code_library.ingest licensed-pdf \
    --pdf ~/codes/IBC_2021.pdf \
    --code-short IBC --code-name "International Building Code" \
    --version 2021 --scope "*"

# California codes scope to the state layer:
python -m app.code_library.ingest licensed-pdf \
    --pdf ~/codes/CBC_2022_Part2.pdf \
    --code-short CBC --code-name "California Building Code" \
    --version 2022 --scope CA
```

**This is the path that closes the WUI citation gap.** The deterministic
WUI rules cite CBC 708A / 709A / Chapter 7A; until those sections are in the
corpus the citation gate correctly downgrades their findings to
needs-review. Ingesting the CBC (Part 2, Chapter 7A) recovers them. Note:
ingesting a licensed file does **not** create a right to republish its text —
the fair-use quote cap in `citation_retrieval.py` still bounds what users see.

## Current blocker: Cloudflare (as of 2026-06)

American Legal Publishing, Municode, qcode, and ecode360 may sit behind a
Cloudflare bot-challenge. Plain HTTP fetches return:

```
403 Forbidden   (cf-mitigated: challenge)
```

Each scraper detects this and **stops with a clear message** instead of
silently writing an empty file. A run that hits the challenge produces **0
chunks and leaves any existing corpus file intact** — a failed scrape can no
longer wipe good data (`writer.write_jsonl` refuses to overwrite with empty
and writes atomically via a `.tmp` rename).

To actually pull text you need one of:

1. **A licensed data feed** from the publisher (the clean path — also the
   only one without copyright exposure for republishing code text). For ICC
   I-Codes, see `docs/ICC_LICENSING_INQUIRY_EMAIL.md`.
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

## Citation-grounded retrieval

For the production grounding layer (structural retrieval, claim
verification, fair-use bounded quoting) see
`../citation_retrieval.py`. The ingesters above are the *supply* side;
`citation_retrieval` is the *consumption* side that turns chunks into
auditable agent citations.
