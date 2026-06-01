-- =====================================================================
-- Plan Room AHJ — migration 0006: eval harness
--
-- Tracks how the triage pipeline performs against a curated set of
-- ground-truth plan-set fixtures. Every prompt/model/retrieval change
-- should bump a new eval_run and surface deltas against the last run
-- before being shipped.
--
-- Tables:
--   eval_cases               — one row per fixture (plan_text + metadata)
--   eval_ground_truth        — expected status for each rule on a case
--   eval_runs                — one row per harness execution
--   eval_run_results         — actual finding vs expected for one (run, case, rule)
--
-- The harness lives at scripts/eval/run-eval.ts and writes to these
-- tables. Read-only from the Next.js dashboard for accuracy reporting.
-- =====================================================================

-- =====================================================================
-- 1. eval_cases — the curated fixture set
-- =====================================================================
create table if not exists public.eval_cases (
  id               uuid primary key default gen_random_uuid(),
  -- Stable slug for cross-run diffing (e.g. 'la-sfr-v5b-complete')
  slug             text unique not null,
  title            text not null,
  jurisdiction_key text not null,           -- 'CA:LOS_ANGELES'
  -- The pilot archetype this case belongs to. Out-of-scope cases use
  -- 'out_of_scope' so we can verify the intake classifier rejects them.
  archetype        text not null,           -- 'la_sfr_typ_vb_ministerial' | 'la_ti_commercial' | 'out_of_scope' | ...
  project_address  text,
  plan_text        text not null,
  -- Free-text describing what's true about this case (for diff context)
  notes            text,
  source           text not null default 'synthetic',  -- 'synthetic' | 'real_redacted' | 'public_record'
  created_at       timestamptz not null default now()
);

create index if not exists eval_cases_archetype_idx on public.eval_cases(archetype);
create index if not exists eval_cases_jurisdiction_idx on public.eval_cases(jurisdiction_key);

-- =====================================================================
-- 2. eval_ground_truth — expected pipeline output per rule per case
--
-- For each (case, rule_id) the human curator says what the *correct*
-- status is. If a rule_id is not listed for a case, the harness treats
-- it as "don't care" (skipped in precision/recall).
-- =====================================================================
create table if not exists public.eval_ground_truth (
  id               uuid primary key default gen_random_uuid(),
  case_id          uuid not null references public.eval_cases(id) on delete cascade,
  rule_id          text not null,
  expected_status  text not null check (expected_status in ('pass','fail','warn','info')),
  -- Severity the curator would assign — used to weight per-severity F1
  expected_severity text check (expected_severity in ('critical','major','moderate','minor')),
  -- Why a human would call it this way — useful when a regression flips it
  rationale        text,
  created_at       timestamptz not null default now(),
  unique (case_id, rule_id)
);

create index if not exists eval_ground_truth_case_idx on public.eval_ground_truth(case_id);

-- =====================================================================
-- 3. eval_runs — one row per harness execution
-- =====================================================================
create table if not exists public.eval_runs (
  id                uuid primary key default gen_random_uuid(),
  pipeline_version  text not null,           -- mirrors PIPELINE_VERSION
  -- What was different about this run vs prior (model name change, prompt edit, etc.)
  label             text not null,
  git_sha           text,
  use_llm           boolean not null default false,
  use_research      boolean not null default false,
  -- Aggregate metrics
  cases_total       integer not null default 0,
  checks_total      integer not null default 0,
  tp                integer not null default 0,  -- true positive (expected fail, got fail)
  fp                integer not null default 0,  -- false positive (expected pass/warn, got fail)
  fn                integer not null default 0,  -- false negative (expected fail, got pass/warn)
  tn                integer not null default 0,  -- true negative (expected pass, got pass)
  precision         numeric(5,4),
  recall            numeric(5,4),
  f1                numeric(5,4),
  -- Per-archetype JSON: { "la_sfr_typ_vb_ministerial": { p: .., r: .., f1: .. }, ... }
  per_archetype     jsonb not null default '{}'::jsonb,
  -- Per-rule JSON same shape
  per_rule          jsonb not null default '{}'::jsonb,
  -- Cost + perf
  duration_ms       integer,
  llm_cost_usd      numeric(10,4) default 0,
  started_at        timestamptz not null default now(),
  completed_at      timestamptz
);

create index if not exists eval_runs_started_idx on public.eval_runs(started_at desc);

-- =====================================================================
-- 4. eval_run_results — drill-down: actual vs expected per (run, case, rule)
-- =====================================================================
create table if not exists public.eval_run_results (
  id              uuid primary key default gen_random_uuid(),
  run_id          uuid not null references public.eval_runs(id) on delete cascade,
  case_id         uuid not null references public.eval_cases(id) on delete cascade,
  rule_id         text not null,
  expected_status text not null,
  actual_status   text not null,
  -- Classification: 'tp' | 'fp' | 'fn' | 'tn' | 'wrong_status' (e.g. expected warn got fail)
  outcome         text not null,
  finding_summary text,
  cited           boolean default false,
  citation_confidence numeric(5,4)
);

create index if not exists eval_run_results_run_idx on public.eval_run_results(run_id);
create index if not exists eval_run_results_case_idx on public.eval_run_results(case_id);
create index if not exists eval_run_results_outcome_idx on public.eval_run_results(outcome);

-- =====================================================================
-- 5. RLS — eval data is global (not agency-scoped). Read for authenticated,
--    writes via service role only.
-- =====================================================================
alter table public.eval_cases         enable row level security;
alter table public.eval_ground_truth  enable row level security;
alter table public.eval_runs          enable row level security;
alter table public.eval_run_results   enable row level security;

drop policy if exists "eval_cases: authenticated read" on public.eval_cases;
create policy "eval_cases: authenticated read" on public.eval_cases for select using (auth.role() = 'authenticated');

drop policy if exists "eval_ground_truth: authenticated read" on public.eval_ground_truth;
create policy "eval_ground_truth: authenticated read" on public.eval_ground_truth for select using (auth.role() = 'authenticated');

drop policy if exists "eval_runs: authenticated read" on public.eval_runs;
create policy "eval_runs: authenticated read" on public.eval_runs for select using (auth.role() = 'authenticated');

drop policy if exists "eval_run_results: authenticated read" on public.eval_run_results;
create policy "eval_run_results: authenticated read" on public.eval_run_results for select using (auth.role() = 'authenticated');
