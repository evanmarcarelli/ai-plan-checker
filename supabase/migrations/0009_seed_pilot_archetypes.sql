-- =====================================================================
-- Plan Room AHJ — migration 0009: seed pilot_archetypes for demo agency
--
-- Without this seed, agencies.pilot_archetypes is empty and the archetype
-- gate falls back to the in-code IN_SCOPE default. That works, but it
-- means changing the per-agency allowlist requires a code deploy.
-- This migration seeds the demo-city agency with the brief's full
-- in-pilot list so the gate is queryable + tweakable from the
-- agencies row going forward.
--
-- Source of truth for the slug list: docs/PILOT_BRIEF.md ("In-pilot
-- scope" table) and supabase/functions/_shared/pilot_config.ts.
-- =====================================================================

update public.agencies
   set pilot_archetypes = jsonb_build_array(
         'la_sfr_typ_vb_ministerial',
         'la_ti_commercial'
       )
 where slug = 'demo-city'
   and (pilot_archetypes is null or pilot_archetypes = '[]'::jsonb);
