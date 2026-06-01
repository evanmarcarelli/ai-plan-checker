-- =====================================================================
-- Plan Room AHJ — migration 0008: pilot-target verdict on eval_runs
--
-- Adds a single boolean + a JSON breakdown so the dashboard / CI gate
-- can ask "did this eval run pass the 90% pilot targets?" with one
-- column read instead of recomputing from per_archetype / per_rule.
-- =====================================================================

alter table public.eval_runs
  add column if not exists pilot_target_pass boolean,
  add column if not exists pilot_target_breakdown jsonb;

comment on column public.eval_runs.pilot_target_pass is
  'Boolean shortcut: did this eval run meet all PILOT_TARGETS thresholds defined in supabase/functions/_shared/pilot_config.ts?';

comment on column public.eval_runs.pilot_target_breakdown is
  'Per-check verdicts: [{ label, pass, detail }]. Same data printed by run-eval.ts under PILOT TARGETS.';

create index if not exists eval_runs_pilot_pass_idx
  on public.eval_runs(pilot_target_pass, started_at desc);
