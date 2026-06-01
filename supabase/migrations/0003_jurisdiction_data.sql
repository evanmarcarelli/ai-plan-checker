-- =====================================================================
-- Plan Room AHJ — migration 0003: jurisdiction data + WUI zone cache
--
-- Adds:
--   wui_zone_cache  — caches CalFire FHSZ GIS results per address
--                     so we don't re-query for every re-triage.
--                     Keyed on a normalized address hash. TTL = 1 year.
--
--   submittals.wui_zone — JSONB column storing the resolved WUI zone
--                     result on the submittal row for fast dashboard
--                     querying (avoids joining to wui_zone_cache).
--
-- No changes to existing tables' RLS — new tables use service-role
-- writes and authenticated reads (consistent with the rest of the schema).
-- =====================================================================

-- =====================================================================
-- wui_zone_cache
-- =====================================================================
create table if not exists public.wui_zone_cache (
  id              uuid primary key default gen_random_uuid(),
  -- Input address (raw, for debuggability)
  address_input   text not null,
  -- Stable cache key — normalized + hashed by the app layer
  address_hash    text not null,
  -- Geocoded coordinates (US Census Geocoder)
  matched_address text,                    -- what the geocoder matched
  lat             double precision,
  lng             double precision,
  -- CalFire FHSZ result
  haz_class       text,                    -- 'Moderate' | 'High' | 'Very High' | null
  sra_type        text,                    -- 'SRA' | 'LRA' | 'FRA' | null
  county          text,
  in_wui          boolean not null default false,
  state           text,                    -- 'CA'
  -- Cache control
  cached_at       timestamptz not null default now(),
  expires_at      timestamptz not null default (now() + interval '365 days')
);

create unique index if not exists wui_zone_cache_hash_idx
  on public.wui_zone_cache(address_hash);

create index if not exists wui_zone_cache_expires_idx
  on public.wui_zone_cache(expires_at)
  where in_wui = true;   -- fast lookup for "what's currently in WUI?"

-- RLS: authenticated users can read; service role writes
alter table public.wui_zone_cache enable row level security;
drop policy if exists "wui_cache: authenticated read" on public.wui_zone_cache;
create policy "wui_cache: authenticated read"
  on public.wui_zone_cache for select
  using (auth.role() = 'authenticated');
-- No client-side insert policy; service role (edge functions) writes via bypass.

-- =====================================================================
-- Add wui_zone column to submittals
-- (idempotent — column may already exist if migration was partially run)
-- =====================================================================
do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public'
       and table_name   = 'submittals'
       and column_name  = 'wui_zone'
  ) then
    alter table public.submittals
      add column wui_zone jsonb;
    comment on column public.submittals.wui_zone is
      'CalFire FHSZ WUI zone result from the Surveyor (CA projects only). '
      'Shape: { in_wui, haz_class, sra_type, county, lat, lng, matched_address, source }.';
  end if;
end $$;

-- =====================================================================
-- Helpful view: CA submittals in a WUI zone
-- Useful for supervisor dashboard (how many active WUI submittals?)
-- =====================================================================
create or replace view public.wui_submittals as
  select
    s.id,
    s.agency_id,
    s.project_name,
    s.project_address,
    s.status,
    s.received_at,
    (s.wui_zone->>'haz_class')  as wui_haz_class,
    (s.wui_zone->>'sra_type')   as wui_sra_type,
    (s.wui_zone->>'county')     as wui_county,
    (s.wui_zone->>'in_wui')::boolean as in_wui
  from public.submittals s
  where s.wui_zone is not null
    and (s.wui_zone->>'in_wui')::boolean = true;

-- RLS on the view is inherited from submittals; no separate policy needed.

-- =====================================================================
-- Cleanup helper: purge expired WUI cache entries
-- Run periodically (e.g., monthly via pg_cron) to keep the table lean.
-- =====================================================================
create or replace function public.purge_expired_wui_cache()
returns integer
language plpgsql security definer set search_path = public as $$
declare
  deleted_count integer;
begin
  delete from public.wui_zone_cache where expires_at < now();
  get diagnostics deleted_count = row_count;
  return deleted_count;
end;
$$;
