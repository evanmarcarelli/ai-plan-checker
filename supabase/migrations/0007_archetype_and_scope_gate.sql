-- =====================================================================
-- Plan Room AHJ — migration 0007: project archetype + pilot scope gate
--
-- Adds the columns and enum value needed to gate triage on whether a
-- submittal falls inside the agency's current pilot scope. The actual
-- classification logic lives in supabase/functions/_shared/archetype.ts.
--
-- Why: accuracy claims on broad scope are indefensible. Restricting the
-- pilot to one or two well-characterized archetypes is the single
-- biggest accuracy lever before any model or prompt change.
-- =====================================================================

-- 1. agencies.pilot_archetypes — ordered array of in-scope archetype slugs.
--    Empty / null means "accept everything that classifyArchetype() returns
--    as in-scope by default" (legacy operation).
alter table public.agencies
  add column if not exists pilot_archetypes jsonb not null default '[]'::jsonb;

comment on column public.agencies.pilot_archetypes is
  'Allowlist of project archetypes the AI triage will run on. See supabase/functions/_shared/archetype.ts. Empty = default IN_SCOPE set.';

-- 2. submittals.project_archetype — the classifier's verdict, cached for
--    dashboards and analytics.
alter table public.submittals
  add column if not exists project_archetype text;

alter table public.submittals
  add column if not exists archetype_reasoning jsonb;

comment on column public.submittals.project_archetype is
  'Pilot archetype classification — drives whether AI triage runs or the submittal is routed to manual review.';

-- 3. submittal_status — add the new "out_of_pilot_scope" terminal state.
--    Postgres does not allow `alter type ... add value` inside a transaction
--    in older versions; this is idempotent via the exception trap.
do $$
begin
  alter type public.submittal_status add value if not exists 'out_of_pilot_scope';
exception
  when duplicate_object then null;
end $$;

create index if not exists submittals_archetype_idx
  on public.submittals(agency_id, project_archetype);
