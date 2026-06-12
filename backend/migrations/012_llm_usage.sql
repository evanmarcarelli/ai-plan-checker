-- 012: per-job LLM token usage.
--
-- The worker persists the run's cumulative token usage (calls, input/output
-- tokens, cache reads/writes) after each completed job, so cost-per-run and
-- cache effectiveness are queryable instead of invisible. Nullable; the
-- worker writes it best-effort and tolerates the column being absent.

alter table public.jobs add column if not exists llm_usage jsonb;
