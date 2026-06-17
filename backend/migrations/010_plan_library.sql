-- ============================================================
-- Migration 010: plan-set library (cross-job plan corpus)
--
-- WHY
-- Until now an uploaded plan set lived only as a per-job JSONB blob
-- (jobs.plan_data). That makes four things impossible:
--   1. Dedupe       — the SHA256 hash was computed and thrown away, so a
--                     re-upload re-ran (and re-billed) the whole pipeline.
--   2. Revisions    — "rev 2 of the same project" had no link to rev 1.
--   3. Retrieval    — agents (and humans) could not search across plan
--                     sets ("find the sheets that mention Type V-B" /
--                     "what did the structural sheets of this project say").
--   4. Traceability — findings could not point back to a durable
--                     sheet-level source.
--
-- This migration adds the durable plan corpus:
--   * plan_documents — one row per distinct uploaded plan set (per user),
--                      keyed by file_hash for dedupe, with revision links.
--   * plan_sheets    — one row per extracted page/sheet, carrying the
--                      sheet number, discipline, title, and full text with
--                      a generated FTS index for retrieval.
--   * jobs.file_hash / jobs.plan_document_id — link jobs to the corpus.
--   * search_plan_sheets() — ranked FTS search scoped to a user.
--
-- Everything is idempotent (IF NOT EXISTS / CREATE OR REPLACE) and the
-- backend degrades gracefully when this migration is not applied (the
-- plan_library service catches and logs persistence failures).
-- ============================================================

-- ── plan_documents: one per distinct uploaded plan set ──────────
create table if not exists public.plan_documents (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  file_hash       text not null,            -- SHA256 of the uploaded PDF
  source_job_id   uuid references public.jobs(id) on delete set null,
  filename        text,
  page_count      integer,
  project_name    text,
  project_address text,
  permit_number   text,
  jurisdiction_city  text,
  jurisdiction_state text,
  occupancy_type  text,
  construction_type text,
  plan_type       text,
  -- Revision chain: newest upload of the same project points at the
  -- document it supersedes. NULL = first known revision.
  revision_of     uuid references public.plan_documents(id) on delete set null,
  extraction_stats jsonb,
  created_at      timestamptz default now(),
  -- One corpus entry per distinct file per user. A re-upload of the same
  -- bytes links to the existing document instead of duplicating it.
  constraint plan_documents_user_hash_uniq unique (user_id, file_hash)
);

create index if not exists plan_documents_user_idx
  on public.plan_documents (user_id, created_at desc);
create index if not exists plan_documents_address_idx
  on public.plan_documents (user_id, lower(project_address));
create index if not exists plan_documents_permit_idx
  on public.plan_documents (user_id, permit_number);

-- ── plan_sheets: one per extracted page/sheet ────────────────────
create table if not exists public.plan_sheets (
  id               uuid primary key default gen_random_uuid(),
  plan_document_id uuid not null references public.plan_documents(id) on delete cascade,
  user_id          uuid not null references auth.users(id) on delete cascade,
  page_number      integer,                 -- NULL for index-only sheets
  sheet_number     text,                    -- 'A-1.0', 'S-2' ... NULL if unidentified
  sheet_title      text,                    -- 'FLOOR PLAN' from the drawing index
  discipline       text,                    -- architectural|structural|mechanical|...
  category         text,                    -- department category (building_safety|fire|...)
  source           text,                    -- title_block|label|index_match|index_only
  confidence       real default 0,
  used_ocr         boolean default false,
  char_count       integer default 0,
  text             text,                    -- full extracted page text
  fts              tsvector generated always as (
                     to_tsvector('english',
                       coalesce(sheet_number,'') || ' ' ||
                       coalesce(sheet_title,'')  || ' ' ||
                       coalesce(discipline,'')   || ' ' ||
                       coalesce(text,''))
                   ) stored,
  created_at       timestamptz default now()
);

create index if not exists plan_sheets_doc_idx
  on public.plan_sheets (plan_document_id, page_number);
create index if not exists plan_sheets_user_idx on public.plan_sheets (user_id);
create index if not exists plan_sheets_discipline_idx
  on public.plan_sheets (user_id, discipline);
create index if not exists plan_sheets_fts_idx on public.plan_sheets using gin (fts);

-- ── job linkage columns ──────────────────────────────────────────
alter table public.jobs add column if not exists file_hash text;
alter table public.jobs add column if not exists plan_document_id uuid
  references public.plan_documents(id) on delete set null;
create index if not exists jobs_file_hash_idx on public.jobs (user_id, file_hash);

-- ── search_plan_sheets: ranked FTS over a user's plan corpus ────
create or replace function public.search_plan_sheets(
  p_user_id     uuid,
  p_query       text,
  p_disciplines text[] default null,
  p_document_id uuid   default null,
  p_limit       int    default 20
)
returns table (
  sheet_id uuid, plan_document_id uuid, page_number int, sheet_number text,
  sheet_title text, discipline text, project_name text, project_address text,
  filename text, snippet text, rank real
)
language sql
security definer
set search_path = public
as $$
  with tsq as (select websearch_to_tsquery('english', coalesce(p_query,'')) q)
  select s.id, s.plan_document_id, s.page_number, s.sheet_number,
         s.sheet_title, s.discipline, d.project_name, d.project_address,
         d.filename,
         ts_headline('english', coalesce(s.text,''), (select q from tsq),
                     'MaxFragments=2, MaxWords=25, MinWords=10') as snippet,
         ts_rank_cd(s.fts, (select q from tsq)) as rank
  from plan_sheets s
  join plan_documents d on d.id = s.plan_document_id
  where s.user_id = p_user_id
    and s.fts @@ (select q from tsq)
    and (p_disciplines is null or s.discipline = any(p_disciplines))
    and (p_document_id is null or s.plan_document_id = p_document_id)
  order by rank desc
  limit p_limit;
$$;

-- ── find_plan_revisions: prior documents that look like the same project ──
-- Used at persist time to chain revisions: same user, same normalized
-- address (or same permit number), different file hash.
create or replace function public.find_plan_revision_candidates(
  p_user_id uuid,
  p_address text,
  p_permit  text,
  p_exclude_hash text
)
returns setof public.plan_documents
language sql
security definer
set search_path = public
as $$
  select d.* from plan_documents d
  where d.user_id = p_user_id
    and d.file_hash is distinct from p_exclude_hash
    and (
      (p_address is not null and p_address <> ''
        and lower(d.project_address) = lower(p_address))
      or (p_permit is not null and p_permit <> ''
        and d.permit_number = p_permit)
    )
  order by d.created_at desc;
$$;

-- ============================================================
-- ROW LEVEL SECURITY — owners read their own corpus; the backend
-- writes via the service role (bypasses RLS), same as findings.
-- ============================================================
alter table public.plan_documents enable row level security;
alter table public.plan_sheets    enable row level security;

create policy "Users can read own plan documents"
  on public.plan_documents for select
  using (auth.uid() = user_id);

create policy "Users can read own plan sheets"
  on public.plan_sheets for select
  using (auth.uid() = user_id);

-- ── API lockdown ─────────────────────────────────────────────
-- Both functions are SECURITY DEFINER and take a caller-supplied p_user_id, so
-- leaving them EXECUTE-able by anon/authenticated via PostgREST would let a
-- signed-in user read ANOTHER user's plan corpus by passing their id. The
-- backend calls them ONLY with the service role. Re-applied after the
-- CREATE OR REPLACE above, which resets the function ACL to default each run.
revoke all on function public.search_plan_sheets(uuid, text, text[], uuid, integer)  from public, anon, authenticated;
revoke all on function public.find_plan_revision_candidates(uuid, text, text, text)  from public, anon, authenticated;
grant execute on function public.search_plan_sheets(uuid, text, text[], uuid, integer) to service_role;
grant execute on function public.find_plan_revision_candidates(uuid, text, text, text) to service_role;
