-- =====================================================================
-- Plan Room AHJ — migration 0002: research/citation cache
--
-- Adds two tables:
--   code_citations  — cached verified code text per (jurisdiction, code_ref).
--                     Reused across submittals so we don't re-search for
--                     the same rule. Expires after 90 days so amendments
--                     get picked up.
--   research_runs   — one row per agentic research session, for cost
--                     observability and debugging.
-- =====================================================================

-- =====================================================================
-- code_citations
-- =====================================================================
create table if not exists public.code_citations (
  id              uuid primary key default gen_random_uuid(),
  -- Scope: nullable agency_id means "baseline / non-jurisdiction-specific".
  -- Setting it to a real agency means "this is what was found for THIS
  -- city's amendments specifically" — keep them separate.
  agency_id       uuid references public.agencies(id) on delete cascade,
  jurisdiction_key text not null,                 -- 'baseline' | 'WA' | 'WA:SEATTLE' | etc.
  code_ref        text not null,                  -- 'IBC 1006.3.2'
  -- The verified content
  citation_text   text not null,                  -- the actual quoted code text
  source_url      text not null,                  -- where we found it
  source_title    text,                           -- page title for display
  source_domain   text,                           -- 'codepublishing.com', etc.
  -- Quality signals
  confidence      numeric(3,2) not null default 0.5,  -- 0.0–1.0
  verifier_model  text,                           -- which LLM verified
  -- Bookkeeping — reuse only fresh citations
  retrieved_at    timestamptz not null default now(),
  expires_at      timestamptz not null default (now() + interval '90 days'),
  -- Some rules legitimately have multiple citations (federal + state amendment)
  is_primary      boolean not null default true,
  notes           text,
  created_at      timestamptz not null default now()
);

create index if not exists code_citations_lookup_idx
  on public.code_citations(jurisdiction_key, code_ref, expires_at);
create index if not exists code_citations_agency_idx
  on public.code_citations(agency_id, code_ref) where agency_id is not null;

-- RLS — readable by all authenticated users (citations aren't sensitive)
alter table public.code_citations enable row level security;
drop policy if exists "citations: read" on public.code_citations;
create policy "citations: read"
  on public.code_citations for select using (true);
-- Writes: service role only (no client policy = locked from clients)

-- =====================================================================
-- research_runs — one row per agentic Researcher session
-- =====================================================================
create table if not exists public.research_runs (
  id              uuid primary key default gen_random_uuid(),
  agency_id       uuid references public.agencies(id) on delete cascade,
  submittal_id    uuid references public.submittals(id) on delete cascade,
  triage_run_id   uuid references public.triage_runs(id) on delete cascade,
  -- What was the Researcher trying to verify?
  goal            text not null,
  jurisdiction_key text,
  code_ref        text,
  -- Loop output
  iterations      integer not null default 0,
  searches_made   integer not null default 0,
  pages_fetched   integer not null default 0,
  citations_found integer not null default 0,
  -- Cost
  llm_cost_usd    numeric(10,6) default 0,
  search_cost_usd numeric(10,6) default 0,
  -- Outcome
  succeeded       boolean not null default false,
  outcome_summary text,
  -- The final citation (if found)
  citation_id     uuid references public.code_citations(id) on delete set null,
  -- Timing
  started_at      timestamptz not null default now(),
  completed_at    timestamptz,
  duration_ms     integer
);

create index if not exists research_runs_agency_idx
  on public.research_runs(agency_id, started_at desc);
create index if not exists research_runs_submittal_idx
  on public.research_runs(submittal_id, started_at desc);

alter table public.research_runs enable row level security;
drop policy if exists "research: agency read" on public.research_runs;
create policy "research: agency read"
  on public.research_runs for select using (
    agency_id is null or agency_id in (select public.user_agency_ids())
  );

-- =====================================================================
-- Helper: fetch a fresh, valid citation if one exists
-- =====================================================================
create or replace function public.lookup_citation(
  p_jurisdiction_key text,
  p_code_ref text
) returns public.code_citations
language sql stable security definer set search_path = public as $$
  select c.*
    from public.code_citations c
   where c.jurisdiction_key = p_jurisdiction_key
     and c.code_ref = p_code_ref
     and c.expires_at > now()
     and c.is_primary = true
   order by c.retrieved_at desc
   limit 1;
$$;

-- =====================================================================
-- Add jurisdiction_key + code_year to agencies for caching keys
-- (idempotent — column may already exist)
-- =====================================================================
do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_name='agencies' and column_name='jurisdiction_key'
  ) then
    alter table public.agencies add column jurisdiction_key text;
    update public.agencies
       set jurisdiction_key = case
         when city is not null and state is not null then state || ':' || upper(replace(city, ' ', '_'))
         when state is not null then state
         else 'baseline'
       end;
  end if;
end $$;
