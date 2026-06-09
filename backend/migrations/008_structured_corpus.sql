-- ============================================================
-- Migration 008: structured code corpus (hierarchy + provenance + hybrid search)
--
-- WHY
-- Today the corpus is flat JSONL loaded into memory (rank_bm25). That makes
-- four problems unsolvable in the data model:
--   1. No hierarchy  -> an exception (1004.1.1) has no link to its chapter.
--   2. Amendments are a tag list -> base + local override both match one query.
--   3. Tables are hardcoded Python dicts -> not from corpus, error-prone.
--   4. No provenance -> can't prove a citation's source/license (liability).
--
-- This migration moves the corpus INTO Postgres and adds the structure:
--   * provisions      — the hierarchical tree (ltree), immutable base editions.
--   * amendments      — typed local deltas (strike/replace/add) per adoption.
--   * code_chunks     — DENORMALIZED, jurisdiction-scoped, search-ready read
--                       surface (the agents query this). Carries ltree `path`,
--                       `adoption_id`, provenance, FTS, and a NULLABLE embedding
--                       so we ship lexical search now and add vectors later with
--                       zero schema change.
--   * code_table_cells— occupancy/area/fixture matrices as queryable rows, so
--                       lookups are deterministic SQL, not LLM table-reading.
--
-- Design choice (efficiency): the read path hits the denormalized code_chunks
-- (already resolved per adoption_id), so there's no materialized-view refresh
-- machinery. The normalized provisions/amendments tables exist for lineage and
-- future automated diffing, populated by the same ingest.
--
-- All functions are SECURITY DEFINER with a pinned search_path (matches 006/007).
-- Everything is idempotent (IF NOT EXISTS / CREATE OR REPLACE).
-- ============================================================

create extension if not exists ltree;
create extension if not exists vector;

-- ── editions (immutable base model codes) ────────────────────
create table if not exists code_editions (
  id             text primary key,         -- 'ICC:IBC:2021', 'CA:CBC:2025'
  publisher      text not null,            -- 'ICC','CA-BSC','LADBS'
  title          text not null,
  year           int,
  source_tier    text not null default 'unspecified',  -- official_gov|pro_bulk|licensed|civic_repo|unspecified
  license_status text not null default 'review',        -- edict|licensed|fair_use_review|review
  source_url     text,
  retrieved_at   timestamptz,
  content_sha256 text
);

-- ── adoptions (a jurisdiction adopts an edition; mirrors AdoptionRecord.id) ──
create table if not exists adoptions (
  id              text primary key,        -- 'ca', 'ca:los_angeles' (== AdoptionRecord.id)
  jurisdiction    text not null,           -- display name
  level           text,                    -- state|county|city
  edition_id      text references code_editions(id),
  ordinance_cite  text,
  effective_date  date,
  source_url      text
);

-- ── provisions (the hierarchical tree; lineage + future diffing) ──
create table if not exists provisions (
  id           uuid primary key default gen_random_uuid(),
  edition_id   text not null references code_editions(id),
  path         ltree not null,             -- 'c10.s1004.s1004_1.s1004_1_1'
  parent_path  ltree,
  number       text not null,              -- '1004.1.1'
  kind         text not null default 'section',  -- chapter|section|subsection|exception|table|definition
  heading      text,
  text         text,
  unique (edition_id, path)
);
create index if not exists provisions_path_gist on provisions using gist (path);

-- ── amendments (typed local deltas keyed to a base provision) ──
create table if not exists amendments (
  id             uuid primary key default gen_random_uuid(),
  adoption_id    text not null references adoptions(id),
  target_path    ltree not null,
  op             text not null,            -- strike|replace|add|delete_section
  new_text       text,
  ordinance_cite text not null,
  effective_date date,
  needs_review   boolean not null default true   -- human gate before it goes live
);
create index if not exists amendments_adoption_idx on amendments (adoption_id);

-- ── code_chunks (DENORMALIZED read surface — the agents query this) ──
create table if not exists code_chunks (
  id             uuid primary key default gen_random_uuid(),
  chunk_id       text unique not null,     -- stable id from source (idempotent ingest)
  adoption_id    text,                     -- jurisdiction scope key (null = base/'*')
  edition_id     text,
  code_short     text not null,            -- 'IBC','ADA','T24','NEC'
  version        text not null,
  section        text not null,            -- '1004.1.1'
  path           ltree,                    -- hierarchical path (ancestor expansion)
  parent_section text,
  citation       text not null,            -- 'IBC 1004.1.1'
  discipline     text not null,            -- == category: building_safety|fire|electrical|...
  heading        text,
  context_header text,                     -- generated breadcrumb ("Ch10 Egress > §1004 ...")
  body           text not null,            -- VERBATIM code text (what we cite)
  jurisdictions  text[] not null default '{}',  -- verbatim source tags (back-compat with applies_to)
  tags           text[] not null default '{}',
  source_tier    text not null default 'unspecified',
  license_status text not null default 'review',
  content_sha256 text,
  embedding      halfvec(1024),            -- NULLABLE: lexical search works without it
  fts            tsvector generated always as (
                   to_tsvector('english',
                     coalesce(context_header,'') || ' ' ||
                     coalesce(heading,'')        || ' ' ||
                     coalesce(body,'')           || ' ' ||
                     array_to_string(tags,' '))
                 ) stored
);
create index if not exists code_chunks_fts_idx       on code_chunks using gin (fts);
create index if not exists code_chunks_path_gist      on code_chunks using gist (path);
create index if not exists code_chunks_scope_idx      on code_chunks (adoption_id, discipline);
create index if not exists code_chunks_section_idx    on code_chunks (lower(section));
create index if not exists code_chunks_citation_idx   on code_chunks (lower(citation));
-- Vector index is created but unused until embeddings are populated. Cheap on empty.
create index if not exists code_chunks_hnsw_idx
  on code_chunks using hnsw (embedding halfvec_cosine_ops) with (m = 16, ef_construction = 64);

-- ── code_table_cells (matrices as deterministic, queryable data) ──
create table if not exists code_table_cells (
  id            uuid primary key default gen_random_uuid(),
  table_id      text not null,            -- 'IBC:2021:T506.2'
  adoption_id   text,                     -- jurisdiction scope (null = base)
  row_key       text not null,            -- occupancy 'A-2'
  col_key       text not null,            -- construction 'V-B'
  value_num     numeric,                  -- 6000
  value_sentinel text,                    -- 'UL' | 'NP' (mutually exclusive with value_num)
  unit          text,                     -- 'sf' | 'stories' | 'ft'
  footnote_refs text[] not null default '{}',
  source_section text,                    -- governing section
  unique (table_id, coalesce(adoption_id,''), row_key, col_key)
);
create index if not exists code_table_cells_lookup_idx on code_table_cells (table_id, adoption_id);


-- ── search_code_chunks: hybrid (FTS + optional vector) with RRF ──
-- p_query_emb may be NULL (pre-embedding) -> pure lexical. Filters are NULL =
-- "no filter". adoption_ids should normally be passed to prevent cross-
-- jurisdiction results. Returns chunk rows + a fused score.
create or replace function public.search_code_chunks(
  p_query_text   text,
  p_query_emb    halfvec(1024) default null,
  p_adoption_ids text[]        default null,
  p_disciplines  text[]        default null,
  p_limit        int           default 20,
  p_pool         int           default 50
)
returns table (chunk_id text, citation text, section text, body text,
               context_header text, discipline text, adoption_id text, score double precision)
language sql
security definer
set search_path = public
as $$
  with tsq as (select websearch_to_tsquery('english', coalesce(p_query_text,'')) q),
  lex as (
    select c.chunk_id,
           row_number() over (order by ts_rank_cd(c.fts, (select q from tsq)) desc) r
    from code_chunks c
    where c.fts @@ (select q from tsq)
      and (p_adoption_ids is null or c.adoption_id = any(p_adoption_ids))
      and (p_disciplines  is null or c.discipline  = any(p_disciplines))
    limit p_pool
  ),
  sem as (
    select c.chunk_id,
           row_number() over (order by c.embedding <=> p_query_emb) r
    from code_chunks c
    where p_query_emb is not null
      and c.embedding is not null
      and (p_adoption_ids is null or c.adoption_id = any(p_adoption_ids))
      and (p_disciplines  is null or c.discipline  = any(p_disciplines))
    order by c.embedding <=> p_query_emb
    limit p_pool
  ),
  fused as (
    select chunk_id, sum(1.0/(60+r)) score   -- Reciprocal Rank Fusion, k=60
    from (select * from lex union all select * from sem) u
    group by chunk_id
  )
  select c.chunk_id, c.citation, c.section, c.body, c.context_header,
         c.discipline, c.adoption_id, f.score
  from fused f
  join code_chunks c using (chunk_id)
  order by f.score desc
  limit p_limit;
$$;


-- ── get_chunk_ancestors: ltree ancestor expansion (the 1004.1.1 fix) ──
-- Returns the chunk at p_path plus all its ancestors in the same adoption,
-- ordered root -> leaf, so an agent always sees inherited scope + the section.
create or replace function public.get_chunk_ancestors(
  p_adoption_id text,
  p_path        ltree
)
returns table (chunk_id text, citation text, section text, heading text,
               body text, depth int)
language sql
security definer
set search_path = public
as $$
  select distinct on (nlevel(c.path))
         c.chunk_id, c.citation, c.section, c.heading, c.body, nlevel(c.path) depth
  from code_chunks c
  where c.path @> p_path                      -- ancestors-or-self of p_path
    -- Prefer the adoption's own provision at each level, but fall back to the
    -- base (adoption_id null) ancestor so chapter scope is never missing.
    and (c.adoption_id is not distinct from p_adoption_id or c.adoption_id is null)
  -- distinct on level: the adoption-specific row sorts before the base row.
  order by nlevel(c.path),
           (c.adoption_id is not distinct from p_adoption_id) desc;
$$;
