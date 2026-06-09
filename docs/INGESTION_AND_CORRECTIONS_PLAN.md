# Ingestion & Corrections Depth — Plan

**Goal (priority #1):** correction output on the level of a real plan check (a real
residential set can run 17+ pages of corrections). Grow the database without
compromising accuracy.

## The core insight (evidence-backed)

A real plan checker does **not** generate 17 pages by reading raw code text. They
work down a **published "Standard Correction List"** — a structured, code-cited
checklist of every applicable requirement *and* every completeness item
("show X on plans", "specify Y"). Most real corrections are completeness items,
which a raw-code corpus will never produce.

These standard correction lists are **public department documents**. Example:
Orange County's *2019 CRC R-3 Plan Check Correction List* — 21 pages, 14
disciplines (A. Plan Requirements, B. General Construction, C. Occupancy,
D. Finishes, E. Glazing, F. Skylights, G. Fireplaces, H. Exiting, I. Roof,
J. Noise, K. Energy, L. Mechanical, M. Plumbing, N. Electrical), each item code-
cited (e.g. `A3. Indicate a job address on all sheets [CRC R106.1.1]`).

**Conclusion:** the lever for depth is a structured **correction checklist**, not
raw scrape volume. Current state: only ~6 deterministic checkers and a 1.3 MB /
9-file corpus — that's why output is shallow.

## Public correction-list sources (legitimate, government-published)

- LADBS Standard Corrections List + SFD/Duplex Plan Check Correction Sheets
  (dbs.lacity.gov / ladbs.org/forms-publications)
- Orange County 2019 Residential Plan Check Correction List (pwds.oc.gov)
- LA County Dept. of Public Works Residential Correction List (dpw.lacounty.gov)
- City of Huntington Beach Residential Correction List
- City of Baldwin Park Residential Plans Correction List
- Permit Sonoma Building & Grading Plan Check forms

## Workstream A — Corrections checklist (highest leverage)

1. Ingest the public standard correction lists (PDF/HTML) into a structured
   schema: `{ discipline, item_id, text, code_citation, applies_when }`.
2. Feed the checklist into BOTH the deterministic engine (new rules) AND the
   department agents, so every applicable item is evaluated — including
   completeness/"provide-this" items.
3. Per-occupancy variants (R-3 SFD, R-1/R-2 multifamily, commercial TI…).

**Accuracy guardrails:** every checklist item keeps its source URL + edition +
code citation; a finding ships only if it traces to an ingested, cited item
(extend the existing citation gate). Validate each new occupancy/jurisdiction
against golden plan sets before marking "supported."

## Workstream B — Code corpus expansion ("more bases")

The 4 platforms are config-driven via `ingest/jurisdictions.yaml` (one entry per
jurisdiction per publisher). To add bases:

1. Determine which publisher hosts each target jurisdiction (Municode/CivicPlus,
   American Legal, General Code/eCode360, Quality Code), add an entry with a
   `# verify` slug, confirm the URL, then run capped.
2. Expand by **adoption cluster** (state model + edition), not city-by-city.
3. **Rate-limit + provenance + respect ToS/robots.** The Cloudflare-bypass
   Playwright fetcher stays **opt-in/off-by-default** — no unsupervised mass
   scraping that defeats anti-bot. Prefer official/state sources where available.

## What we will NOT do

- No unsupervised, anti-bot-defeating mass scrape of the internet (ToS +
  copyright risk; ICC litigated UpCodes for reproducing codes).
- No raw ICC model-text scraping — license that spine instead (see prior memo).
- "Approved plan SETS" as training data: rare, often copyright/privacy-laden.
  Correction *lists/guides* are the safe, abundant, high-value source.

## Sequencing

1. Build the corrections-checklist schema + ingest 2-3 standard correction lists
   (LADBS + OC) → immediate depth jump for CA residential.
2. Wire checklist items into the engine + agents; enforce citation gate.
3. Golden-set validation for R-3 SFD.
4. Then expand corpus bases by adoption cluster.

## Built (this session)

- **WS1** `app/code_library/checklists/`: schema + `build_from_pdf.py` parser +
  `loader.py`. Ingested the OC 2019 CRC R-3 list → **239 code-cited correction
  items** across 14 disciplines (`data/oc_2019_crc_r3.json`). `coverage.py`
  reports depth (`python -m app.code_library.checklists.coverage`).
- **WS2** `checker.py` converts the applicable checklist into per-department
  `CodeRequirement`s; `workflow.py` injects them so each department reviewer
  evaluates them through the existing prompt + citation gate. Toggle via
  `settings.checklist_review_enabled` (default on),
  `settings.checklist_max_per_department` (default 40). For R-3 this adds **129
  correction items** across 5 departments. Commercial/unknown occupancy gets
  nothing (graceful) until a commercial list is ingested.
- **WS3** `tests/test_checklists.py` (5 passing) covers load → select → inject,
  provenance, citation-id uniqueness, and the commercial-skip guard. Full
  LLM-depth (how many surface on a labeled plan) still needs the golden-set
  eval harness + an API key.
- **WS4** `jurisdictions.yaml`: +13 non-LA CA metros (Sacramento, San Diego,
  Oakland, San Jose, Anaheim, …) across American Legal + Municode, marked
  `# verify`. 105 targets total.

## Built (second session)

- **Numbered-format parser:** `build_from_pdf.py --format numbered` handles the
  LADBS-style two-column correction *sheets* (bare `1.`/`2.` items under
  `A. SECTION` headers nested in `PART III: …`, citations trailing on their own
  line, lettered sub-items folded into the parent). Column-aware reconstruction
  (`_columned_lines`) reads each physical column top-to-bottom so items aren't
  scrambled; cover/supplemental-sheet boilerplate is filtered and bleed tails
  cut at the `ATTACHED:` sentinel. The item-extraction core
  (`_parse_numbered_lines`) is a pure, unit-tested function.
- **Ingested LADBS** SFD/Duplex Plan Check Correction Sheets (2020 LARC) →
  **125 code-cited correction items** across building_safety / zoning /
  public_works / fire (`data/ladbs_2020_larc_sfd.json`). Corpus is now **364
  items across 2 checklists**.
- **Jurisdiction-aware selection:** `select_checklist(occ, state, city)` now
  routes an LA plan to LADBS and any other CA plan to the *least* jurisdiction-
  specific list (OC, all statewide-CRC) — so LA-Municipal zoning items never
  leak onto a non-LA plan. Threaded `j.city`/`j.state_code` through
  `checklist_requirements` → workflow. Result: **LA R-3 → 90 items**,
  **non-LA CA R-3 → 129 items** (statewide codes only).
- **Precision guidance:** when completeness/checklist items are present the
  department reviewer prompt now instructs "flag ONLY what the plan does not
  show/satisfy" — clear miss → non_compliant, silence/ambiguity → needs_review
  (confidence < 0.55), never assert a violation from absence of excerpt text.
  This + the existing low-confidence gate protects the 90% precision target.
- **Settings:** `checklist_review_enabled` / `checklist_max_per_department` are
  now explicit in `settings.py` + `.env.example` (were getattr defaults).

> Caveat: live precision against the 90% target still needs a real R-3 run with
> an `ANTHROPIC_API_KEY` set (offline runs fall back to mock reviewers). The
> injection depth + jurisdiction routing above are verified offline.

## Next (clear follow-ups)

- **Run a live R-3 plan** with an API key to measure precision and tune
  `checklist_max_per_department` against the 90% target.
- **Ingest more numbered-format lists** now that the mode exists: LA County DPW
  + Huntington Beach (same two-column shape).
- **Ingest a commercial (B/M/A) correction list** to extend depth past R-3.
- **Verify the new `# verify` slugs/publishers**, then run capped ingests.
