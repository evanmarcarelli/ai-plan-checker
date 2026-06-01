-- 0005_property_profile.sql
-- Property lookup cache (Session C).
--
-- Stores geocoded property profiles (FEMA flood zone, CA Coastal Zone,
-- LA County parcel data, LADBS permit history) for 30 days.  Avoids
-- repeating GIS API calls on re-submittals or plan revisions at the
-- same address.
--
-- Populated and read exclusively by:
--   supabase/functions/_shared/property.ts :: resolvePropertyProfile()
-- =====================================================================

create table if not exists property_lookup_cache (
  id             bigserial     primary key,
  -- Normalized-address hash (djb2 variant, 8-hex chars, computed in property.ts)
  address_hash   text          not null unique,
  address_input  text          not null,
  -- Full PropertyProfile serialized as JSONB
  profile_json   jsonb         not null,
  resolved_at    timestamptz   not null default now(),
  -- 30-day TTL; refreshed on every resolvePropertyProfile() write
  expires_at     timestamptz   not null,
  created_at     timestamptz   not null default now()
);

create index if not exists property_lookup_cache_expires_idx
  on property_lookup_cache(expires_at);

comment on table property_lookup_cache is
  'Cache for resolvePropertyProfile() — FEMA flood zone, CA Coastal Zone, LA parcel, LADBS permits. 30-day TTL.';

-- RLS: only the service-role key used by Edge Functions can access this.
-- No anon / authenticated policies needed.
alter table property_lookup_cache enable row level security;

-- =====================================================================
-- Maintenance helper: purge expired rows.
-- Called from a pg_cron job or an admin script; not called from the
-- hot path.
-- =====================================================================
create or replace function purge_expired_property_cache()
returns integer
language plpgsql
security definer
as $$
declare
  n integer;
begin
  delete from property_lookup_cache where expires_at < now();
  get diagnostics n = row_count;
  return n;
end;
$$;

comment on function purge_expired_property_cache() is
  'Deletes expired rows from property_lookup_cache. Returns count of rows deleted.';
