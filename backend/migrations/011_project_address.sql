-- 011: user-provided project address + resolved site context on jobs.
--
-- The dashboard now collects the project address at upload (optional). The
-- web tier persists the raw input (project_address); the worker geocodes it
-- (US Census) and resolves the adoption stack before the pipeline runs,
-- snapshotting the result into site_context so a completed report records
-- exactly which jurisdiction/code-stack the run used — even if the adoption
-- map changes later.
--
-- Both columns are nullable: jobs without an address keep today's behavior
-- (Surveyor extracts the jurisdiction from the plan set).

alter table public.jobs add column if not exists project_address text;
alter table public.jobs add column if not exists site_context jsonb;
