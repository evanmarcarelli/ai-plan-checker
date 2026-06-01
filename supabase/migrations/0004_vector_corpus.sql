-- =====================================================================
-- Plan Room AHJ — migration 0004: vector code corpus
--
-- Adds the pgvector-powered code corpus that powers semantic search over
-- CA building codes (CBC, CRC, CMC, CPC, CEC, Title 24) and
-- jurisdiction-specific amendment ordinances.
--
-- How it fits into the pipeline:
--   1. An offline ingest script (scripts/ingest/pipeline.ts) chunks +
--      embeds code documents and upserts rows here.
--   2. At triage time, the Researcher calls search_code_chunks() via
--      Supabase RPC before falling back to live web search.
--   3. High-similarity corpus hits (>= 0.75) short-circuit the web
--      search entirely — zero search API cost, ~2ms latency.
--
-- Embedding model: OpenAI text-embedding-3-small (1536 dims).
-- Cost to embed full corpus (~1,740 chunks × ~500 tokens):
--   ~870K tokens × $0.02/MTok = ~$0.017 one-time cost. Essentially free.
-- =====================================================================

create extension if not exists vector;

-- =====================================================================
-- code_chunks  — the semantic search corpus
-- =====================================================================
create table if not exists public.code_chunks (
  id              uuid primary key default gen_random_uuid(),

  -- ---- Corpus identity -----------------------------------------------
  -- corpus_key: which code document this chunk came from.
  -- Format: {CODE}:{YEAR} or {CODE}:{YEAR}:{CHAPTER}
  -- Examples: 'CBC:2022', 'CRC:2022', 'TITLE24:P6:2022', 'CBC:2022:7A'
  corpus_key      text not null,

  -- jurisdiction_key: which jurisdictions this applies to.
  -- 'CA'             = all California jurisdictions (base state codes)
  -- 'CA:LOS_ANGELES' = LA-specific amendment text
  -- 'baseline'       = IBC/IRC national baseline
  jurisdiction_key text not null default 'CA',

  -- ---- Code location (structured for filtering) ----------------------
  code_name       text not null,           -- 'California Building Code 2022'
  part            text,                    -- 'Part 2', 'Part 6'
  chapter         text,                    -- 'Chapter 7A', 'Chapter 3'
  chapter_title   text,                    -- 'Wildfire Exposure'
  section_ref     text,                    -- 'CBC 701A.1', 'CRC R301.1'
  section_title   text,                    -- 'Scope'
  subsection      text,                    -- '701A.1.1' (optional)

  -- ---- Content -------------------------------------------------------
  chunk_text      text not null,
  token_count     integer,
  char_count      integer generated always as (length(chunk_text)) stored,

  -- ---- Embedding (OpenAI text-embedding-3-small = 1536 dims) ---------
  embedding       vector(1536),
  embedding_model text not null default 'text-embedding-3-small',

  -- ---- Provenance ----------------------------------------------------
  source_url      text,                    -- URL where this text was retrieved from
  code_year       text not null default '2022',
  ingested_at     timestamptz not null default now(),
  -- Checksum of chunk_text — used by the ingest pipeline to skip
  -- unchanged chunks on re-run (cheap incremental updates).
  content_hash    text,

  -- Soft-delete rather than hard delete so ingest pipeline can detect
  -- removed/superseded chunks without losing citation history.
  superseded_at   timestamptz
);

-- =====================================================================
-- Indexes
-- =====================================================================

-- IVFFlat index for ANN (approximate nearest-neighbor) search.
-- lists=100 is appropriate for 1,740 chunks. Rebuild with more lists
-- if the corpus grows past ~50K chunks: ALTER INDEX REBUILD.
create index if not exists code_chunks_embedding_idx
  on public.code_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100)
  where superseded_at is null;

-- Filterable indexes used in the WHERE clause before the vector scan
create index if not exists code_chunks_jurisdiction_idx
  on public.code_chunks(jurisdiction_key)
  where superseded_at is null;

create index if not exists code_chunks_corpus_key_idx
  on public.code_chunks(corpus_key)
  where superseded_at is null;

create index if not exists code_chunks_section_ref_idx
  on public.code_chunks(section_ref)
  where superseded_at is null;

create unique index if not exists code_chunks_content_hash_idx
  on public.code_chunks(content_hash)
  where content_hash is not null and superseded_at is null;

-- =====================================================================
-- RLS — readable by all authenticated users; service role writes
-- =====================================================================
alter table public.code_chunks enable row level security;

drop policy if exists "code_chunks: authenticated read" on public.code_chunks;
create policy "code_chunks: authenticated read"
  on public.code_chunks for select
  using (auth.role() = 'authenticated');

-- =====================================================================
-- search_code_chunks  — the RPC used by the Researcher at triage time
--
-- Parameters:
--   query_embedding   vector(1536)  — embedding of the search query
--   p_jurisdiction_keys text[]      — e.g. ARRAY['CA:LOS_ANGELES','CA','baseline']
--   p_match_count     int           — how many results to return (default 8)
--   p_min_similarity  float         — minimum cosine similarity (default 0.70)
--
-- Returns rows ordered by similarity DESC.
-- =====================================================================
create or replace function public.search_code_chunks(
  query_embedding  vector(1536),
  p_jurisdiction_keys text[],
  p_match_count    int     default 8,
  p_min_similarity float   default 0.70
)
returns table (
  id               uuid,
  corpus_key       text,
  jurisdiction_key text,
  code_name        text,
  chapter          text,
  chapter_title    text,
  section_ref      text,
  section_title    text,
  chunk_text       text,
  source_url       text,
  similarity       float
)
language sql stable set search_path = public
as $$
  select
    c.id,
    c.corpus_key,
    c.jurisdiction_key,
    c.code_name,
    c.chapter,
    c.chapter_title,
    c.section_ref,
    c.section_title,
    c.chunk_text,
    c.source_url,
    round(cast(1 - (c.embedding <=> query_embedding) as numeric), 4)::float as similarity
  from public.code_chunks c
  where
    c.superseded_at is null
    and c.embedding is not null
    and c.jurisdiction_key = any(p_jurisdiction_keys)
    and (1 - (c.embedding <=> query_embedding)) >= p_min_similarity
  order by c.embedding <=> query_embedding
  limit p_match_count;
$$;

-- Allow authenticated users to call this function
grant execute on function public.search_code_chunks to authenticated;

-- =====================================================================
-- lookup_chunk_by_section  — exact section reference lookup
-- Used as a fast path when the researcher has an exact code ref like
-- 'CBC 701A.1' — no embedding needed for exact section lookups.
-- =====================================================================
create or replace function public.lookup_chunk_by_section(
  p_section_ref       text,
  p_jurisdiction_keys text[]
)
returns setof public.code_chunks
language sql stable set search_path = public
as $$
  select c.*
  from public.code_chunks c
  where c.superseded_at is null
    and c.jurisdiction_key = any(p_jurisdiction_keys)
    and lower(c.section_ref) = lower(p_section_ref)
  order by c.ingested_at desc
  limit 3;
$$;

grant execute on function public.lookup_chunk_by_section to authenticated;

-- =====================================================================
-- corpus_stats  — handy view for the ingest pipeline + admin
-- =====================================================================
create or replace view public.corpus_stats as
  select
    corpus_key,
    jurisdiction_key,
    code_name,
    count(*) filter (where superseded_at is null)     as active_chunks,
    count(*) filter (where embedding is null
                      and superseded_at is null)       as pending_embed,
    max(ingested_at)                                   as last_ingested,
    min(ingested_at)                                   as first_ingested
  from public.code_chunks
  group by corpus_key, jurisdiction_key, code_name
  order by jurisdiction_key, corpus_key;

-- =====================================================================
-- Purge helper — supersede chunks that are no longer current
-- Call from the ingest pipeline after a fresh ingest run:
--   select purge_old_chunks('CBC:2022', 'CA', '2025-06-01'::timestamptz)
-- =====================================================================
create or replace function public.purge_old_chunks(
  p_corpus_key       text,
  p_jurisdiction_key text,
  p_before           timestamptz
)
returns integer
language plpgsql security definer set search_path = public as $$
declare
  updated_count integer;
begin
  update public.code_chunks
     set superseded_at = now()
   where corpus_key = p_corpus_key
     and jurisdiction_key = p_jurisdiction_key
     and ingested_at < p_before
     and superseded_at is null;
  get diagnostics updated_count = row_count;
  return updated_count;
end;
$$;
