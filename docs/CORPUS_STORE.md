# Structured code corpus — store & cutover

Foundation (step 1) for moving the building-code corpus off flat in-memory
JSONL onto a structured Postgres store, **without breaking the running BM25
system.** This is additive and feature-flagged: nothing changes until you set
`CODE_STORE=postgres` and run the backfill.

## What this solves (and what it defers)

| Problem (from the teardown) | Addressed here | How |
|---|---|---|
| Corpus not in the DB | ✅ | `code_chunks` table + backfill script |
| No hierarchy / inheritance | ✅ (schema) | `ltree path` on every chunk + `get_chunk_ancestors` |
| Amendments → base & local both match | ✅ (capability) | `adoption_id` scope + retriever `adoption_id` filter |
| Tables as hardcoded dicts | ✅ (schema) | `code_table_cells` (populate next) |
| No provenance / license tracking | ✅ | `source_tier` + `license_status` on every chunk/edition |
| BM25-only, no semantic recall | ✅ (schema) | nullable `embedding halfvec` + `search_code_chunks` RRF |

**Deferred on purpose** (next steps, not this branch): generating embeddings,
populating the normalized `provisions`/`amendments` tree from structured
sources, populating `code_table_cells`, and flipping department agents to query
by `adoption_id`. The schema + seams for all of these are in place.

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
