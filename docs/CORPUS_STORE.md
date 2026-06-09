# Structured code corpus — store & cutover

Foundation (step 1) for moving the building-code corpus off flat in-memory
JSONL onto a structured Postgres store, **without breaking the running BM25
system.** This is additive and feature-flagged: nothing changes until you set
`CODE_STORE=postgres` and run the backfill.

## What this solves (and what it defers)

| Problem (from the teardown) | Addressed here | How |
|---|---|---|
| Corpus not in the DB | ✅ | `code_chunks` table + backfill script |
| No hierarchy / inheritance | ✅ **done** | `provisions` tree built from corpus + `get_provision_ancestors` |
| Amendments → base & local both match | ✅ **done** | resolver `corpus_layer_keys` scoping + `amendments` resolution engine |
| Tables as hardcoded dicts | ✅ **done** | `code_table_cells` + `table_store` provider (DB-first, dict fallback) |
| No provenance / license tracking | ✅ | `source_tier` + `license_status` on every chunk/edition |
| BM25-only, no semantic recall | ✅ (schema) | nullable `embedding halfvec` + `search_code_chunks` RRF |

**Deferred on purpose** (one item left): generating embeddings to activate the
semantic half of `search_code_chunks` — needs an embedding vendor/key (Voyage,
OpenAI; Anthropic has no embeddings endpoint). The schema + RRF seam are ready.

## Jurisdiction scoping (done — #3)

Retrieval is scoped via the adoption resolver's `corpus_layer_keys`
(`CA/Los Angeles → ['*','CA','CA:Los Angeles']`), the same source that drives
code versions — so reviewers can't pull another jurisdiction's rules. See
`CorpusCodeSource._layers` + `CodeRetriever(..., layer_keys=...)`.

## Provision tree + amendments (done — #2)

`scripts/ingest/build_provisions.py` derives the structural tree (chapter →
section → subsection, ~312 nodes from the current corpus) from each leaf's
`ltree` path, so `get_provision_ancestors` (migration 009) returns a real
breadcrumb for context assembly. *Honest limit:* interior nodes we have no
chunk for carry the number + a generic heading and **no verbatim text** (we
don't have licensed full chapter text) — the structure is real, the prose for
un-sourced ancestors is not.

`app/code_library/amendments.py` resolves `base ⊕ local deltas`:
`apply_amendments()` is a pure strike/replace/add/delete engine, gated so an
amendment only applies when `needs_review=False` (the human gate) and is
effective on/before the permit date. Real LA ordinance rows are the human-
reviewed feed that populates the `amendments` table; the engine + tests are in
place to consume them safely.

Seed both:
```bash
cd backend
python -m scripts.ingest.build_provisions --dry-run   # show tree shape
python -m scripts.ingest.build_provisions             # upsert provisions
```

## Code reference tables (done)

The IBC/IPC matrices (allowable area 506.2, stories 504.4, min exits 1006.3.2,
fixture ratios 403.1, high-rise threshold) are no longer a hand-transcribed
Python dict that compliance results turn on. `app/code_library/deterministic/
table_store.py` serves the same shapes the checkers expect, **DB-first** from
`code_table_cells` with `tables.py` as the fallback — so behavior is identical
until you seed + flip `CODE_STORE=postgres`, and a jurisdiction can override a
single cell via `adoption_id`.

Seed it (idempotent):
```bash
cd backend
python -m scripts.ingest.tables_to_postgres --dry-run   # show cell counts
python -m scripts.ingest.tables_to_postgres             # upsert into code_table_cells
```
A test asserts the seed round-trips losslessly back to the original tables, so
populating Postgres cannot silently change a limit.

## Efficiency choice

The **read surface is the denormalized `code_chunks` table** — already scoped
per `adoption_id`, already search-ready (FTS now, vectors later). The
normalized `provisions`/`amendments` tables exist for lineage and future
automated ordinance diffing, but the hot path never joins them. This avoids
materialized-view refresh machinery while still giving hierarchy (via `path`)
and the no-conflict guarantee (via `adoption_id`).

## Files

| File | Role |
|---|---|
| `migrations/008_structured_corpus.sql` | editions, adoptions, provisions(ltree), amendments, **code_chunks**, code_table_cells + `search_code_chunks` (hybrid RRF) + `get_chunk_ancestors` |
| `app/code_library/structure.py` | pure transforms: `section_to_ltree`, `adoption_id_for_chunk`, `build_context_header` |
| `app/code_library/store.py` | Postgres reads (fetch/search/ancestors); degrades to empty if migration/Supabase absent |
| `app/code_library/corpus_loader.py` | `CodeChunk` gains optional structured fields; `CODE_STORE` selects disk vs postgres; retriever gains `adoption_id` scope |
| `scripts/ingest/jsonl_to_postgres.py` | idempotent backfill of JSONL → `code_chunks` |
| `tests/test_code_store.py` | DB-free tests for all of the above |

## Cutover (safe, reversible)

1. **Apply** `migrations/008_structured_corpus.sql` in Supabase (idempotent;
   needs the `ltree` and `vector` extensions, both standard on Supabase).
2. **Backfill**:
   ```bash
   cd backend
   python -m scripts.ingest.jsonl_to_postgres --dry-run   # inspect plan + license flags
   python -m scripts.ingest.jsonl_to_postgres             # write code_chunks
   ```
   The dry run prints which editions are flagged `fair_use_review` — that's
   your licensing worklist before commercial launch (see the legal note below).
3. **Flip the flag**: set `CODE_STORE=postgres` (Render env). The loader reads
   `code_chunks` and builds the same in-memory BM25 corpus — identical behavior,
   data now in the DB. If the table is empty/missing it auto-falls back to disk,
   so a misconfiguration can't take the corpus down.
4. **Verify**: run the eval suite (`scripts/eval/run_eval.py`, `test_citation_retrieval`)
   against `CODE_STORE=postgres`. Behavior should match disk; citations resolve.

To roll back: unset `CODE_STORE`. Zero data loss — the JSONL is untouched.

## `adoption_id` and the no-conflict guarantee

`CodeRetriever.search(..., adoption_id="ca:los_angeles")` returns **only** chunks
scoped to that adoption (plus base chunks with no adoption). A base rule and a
local amendment can no longer both surface for one query. Today the agents still
call the legacy geo path (`state`/`city`); switching them to pass `adoption_id`
(resolved from your existing `adoption/resolver.py`) is the step-2 change that
makes the guarantee active end-to-end.

## Provenance / license — why it's a column, not a footnote

Every chunk and edition carries `source_tier` and `license_status`. Model-code
editions (IBC/IFC/IPC/NEC) default to `fair_use_review`; adopted government text
(LADBS, Title 24, ADA) defaults to `edict`. This makes "where did this citation
come from and are we cleared to use it commercially?" a queryable property — the
backbone of the "100% citation-verified" claim and the defense against the
licensing risk discussed in the pipeline plan. You can add a query-time filter
on `license_status` to exclude anything not cleared for production.
