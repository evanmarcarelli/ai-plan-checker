-- =====================================================================
-- Plan Room AHJ — multi-tenant schema
-- =====================================================================
-- Core entities:
--   agencies        — a city / county / building department
--   agency_members  — users belonging to one or more agencies, with role
--   submittals      — a plan set submitted to an agency
--   submittal_files — PDF / DWG attachments
--   triage_runs     — output of the AI triage pipeline (one per submittal version)
--   reviews         — a human reviewer's pass over a submittal
--   review_comments — individual code citations / requests for correction
--   feedback        — reviewer accept/edit/reject of AI-drafted output (training signal)
--   audit_log       — append-only history of state changes for compliance
--   llm_usage       — per-call cost tracking (we bill cities; we need to know our cost)
--
-- All tenant data is scoped to agency_id. RLS enforces:
--   - members of an agency see only their agency's data
--   - reviewers see all submittals; intake clerks see all but cannot delete
--   - applicants (future) see only their own submittals
-- =====================================================================

create extension if not exists "pgcrypto";

-- =====================================================================
-- 1. agencies
-- =====================================================================
create table if not exists public.agencies (
  id            uuid primary key default gen_random_uuid(),
  slug          text unique not null,            -- 'tacoma-wa', 'cityof-frederick'
  name          text not null,                   -- 'City of Tacoma — Planning & Development Services'
  state         text not null,                   -- 'WA'
  city          text,
  -- The AHJ's amendment package: which IBC year, custom rules turned on/off
  code_year     text not null default '2021',
  rule_overrides jsonb not null default '{}'::jsonb,
  custom_rules  jsonb not null default '[]'::jsonb,
  -- Contract / billing state — managed by sales, not the app
  plan          text not null default 'pilot',   -- pilot | starter | standard | enterprise
  contract_start date,
  contract_end   date,
  monthly_submittal_cap integer,                 -- soft cap; we just track usage
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- =====================================================================
-- 2. agency_members
--    One user can belong to multiple agencies (consultants, regional staff).
--    Role determines RLS access.
-- =====================================================================
create type public.member_role as enum (
  'admin',         -- agency settings, member management, all data
  'supervisor',    -- assigns submittals, sees all metrics
  'reviewer',      -- reviews submittals, writes comments
  'intake'         -- intake clerk: creates submittals, runs triage, cannot finalize reviews
);

create table if not exists public.agency_members (
  id          uuid primary key default gen_random_uuid(),
  agency_id   uuid not null references public.agencies(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  role        member_role not null default 'reviewer',
  display_name text,
  created_at  timestamptz not null default now(),
  unique (agency_id, user_id)
);

create index if not exists agency_members_user_idx on public.agency_members(user_id);
create index if not exists agency_members_agency_idx on public.agency_members(agency_id);

-- helper: which agencies does the calling user belong to?
create or replace function public.user_agency_ids() returns setof uuid
language sql stable security definer set search_path = public as $$
  select agency_id from public.agency_members where user_id = auth.uid();
$$;

create or replace function public.user_role_in(target_agency uuid) returns member_role
language sql stable security definer set search_path = public as $$
  select role from public.agency_members
  where user_id = auth.uid() and agency_id = target_agency
  limit 1;
$$;

-- =====================================================================
-- 3. submittals
-- =====================================================================
create type public.submittal_status as enum (
  'received',          -- just arrived, no triage yet
  'triaging',          -- AI pipeline running
  'triaged',           -- triage done, awaiting human review
  'in_review',         -- a reviewer has it
  'on_hold',           -- waiting on applicant
  'approved',
  'denied',
  'returned_incomplete' -- bounced back at intake before substantive review
);

create table if not exists public.submittals (
  id            uuid primary key default gen_random_uuid(),
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  -- The city's tracking number — usually a permit number.
  external_ref  text,
  project_name  text,
  project_address text,
  applicant_name text,
  applicant_email text,
  -- Substantive type — drives which rule profile applies
  project_type  text,                              -- 'commercial_new', 'commercial_ti', 'residential_addition', etc.
  scope_of_work text,                              -- free text from applicant
  status        submittal_status not null default 'received',
  -- Cached scope (extracted facts) — lives on submittal so dashboards
  -- don't have to join to triage_runs every render.
  scope         jsonb,                             -- { occupancies, construction_type, area, stories, ... }
  -- Cached triage summary
  completeness_score numeric(5,2),                 -- 0–100, "how ready is this for substantive review"
  triage_grade  text,                              -- A | B | C | D | F (proxy for "is this submittal-ready")
  -- Audit
  received_at   timestamptz not null default now(),
  due_at        timestamptz,                       -- city's promised turnaround
  closed_at     timestamptz,
  created_by    uuid references auth.users(id),
  -- Bookkeeping
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists submittals_agency_status_idx on public.submittals(agency_id, status, received_at desc);
create index if not exists submittals_agency_received_idx on public.submittals(agency_id, received_at desc);
create index if not exists submittals_external_ref_idx on public.submittals(agency_id, external_ref);

-- =====================================================================
-- 4. submittal_files  (the PDFs themselves)
-- =====================================================================
create table if not exists public.submittal_files (
  id            uuid primary key default gen_random_uuid(),
  submittal_id  uuid not null references public.submittals(id) on delete cascade,
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  -- Path inside the private 'submittals' Storage bucket: agency_id/submittal_id/filename.pdf
  storage_path  text not null,
  filename      text not null,
  size_bytes    bigint,
  mime_type     text,
  page_count    integer,
  -- Cached extracted text from the file (for quick re-runs without OCR)
  extracted_text text,
  has_text_layer boolean,
  ocr_required  boolean default false,
  ocr_completed_at timestamptz,
  uploaded_by   uuid references auth.users(id),
  created_at    timestamptz not null default now()
);

create index if not exists submittal_files_submittal_idx on public.submittal_files(submittal_id);

-- =====================================================================
-- 5. triage_runs  (one row per pipeline execution; submittals can be
--    re-triaged after revisions)
-- =====================================================================
create table if not exists public.triage_runs (
  id            uuid primary key default gen_random_uuid(),
  submittal_id  uuid not null references public.submittals(id) on delete cascade,
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  -- The full report — same shape as the architect-side tool, plus AHJ-specific fields
  report        jsonb not null,
  -- Per-finding confidence scores live inside report.findings[*].confidence
  -- For dashboards, we cache headline metrics here
  findings_total   integer default 0,
  findings_fail    integer default 0,
  findings_warn    integer default 0,
  findings_pass    integer default 0,
  completeness_score numeric(5,2),
  -- Pipeline metadata
  started_at    timestamptz not null default now(),
  completed_at  timestamptz,
  duration_ms   integer,
  llm_calls     integer default 0,
  llm_cost_usd  numeric(10,4) default 0,
  -- Pipeline version — so we can re-process older submittals when the
  -- pipeline improves and compare results.
  pipeline_version text not null
);

create index if not exists triage_runs_submittal_idx on public.triage_runs(submittal_id, started_at desc);

-- =====================================================================
-- 6. reviews  (a human reviewer's pass over a submittal)
-- =====================================================================
create type public.review_outcome as enum (
  'pending', 'approved', 'approved_with_conditions', 'denied', 'returned_incomplete'
);

create table if not exists public.reviews (
  id            uuid primary key default gen_random_uuid(),
  submittal_id  uuid not null references public.submittals(id) on delete cascade,
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  reviewer_id   uuid not null references auth.users(id),
  -- Review pass # (1, 2, 3 — applicants resubmit after corrections)
  cycle         integer not null default 1,
  -- The triage_run this reviewer started from
  triage_run_id uuid references public.triage_runs(id),
  outcome       review_outcome not null default 'pending',
  reviewer_notes text,                             -- internal notes, not sent to applicant
  -- Time tracking — for "is the AI saving us time?" metrics
  started_at    timestamptz not null default now(),
  completed_at  timestamptz,
  -- Bookkeeping
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists reviews_submittal_idx on public.reviews(submittal_id, cycle desc);
create index if not exists reviews_reviewer_idx on public.reviews(reviewer_id, started_at desc);

-- =====================================================================
-- 7. review_comments  (individual citations on a review)
--    These are the items that go in the comment letter to the applicant.
-- =====================================================================
create type public.comment_severity as enum ('correction_required', 'clarification', 'advisory');

create table if not exists public.review_comments (
  id            uuid primary key default gen_random_uuid(),
  review_id     uuid not null references public.reviews(id) on delete cascade,
  submittal_id  uuid not null references public.submittals(id) on delete cascade,
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  -- Which AI-flagged finding (if any) seeded this comment
  source_finding_id text,                          -- the rule_id from the triage report
  -- The actual comment as it will appear in the letter
  code_ref      text,                              -- 'IBC 1006.3.2'
  severity      comment_severity not null default 'correction_required',
  body          text not null,                     -- the formal applicant-facing language
  -- Provenance: did this start as an AI draft? Did the reviewer edit it?
  origin        text not null default 'human',     -- 'ai_draft' | 'ai_accepted' | 'ai_edited' | 'human'
  ai_draft_id   uuid,                              -- pointer for tracing
  -- Position
  display_order integer not null default 0,
  created_by    uuid not null references auth.users(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists comments_review_idx on public.review_comments(review_id, display_order);

-- =====================================================================
-- 8. feedback  (reviewer accept / edit / reject of AI output — training signal)
-- =====================================================================
create type public.feedback_kind as enum (
  'triage_finding',         -- on a triage finding (was it a real issue?)
  'comment_draft',          -- on an AI-drafted comment
  'extraction',             -- on extracted scope facts
  'pipeline_overall'        -- on the whole triage run
);

create type public.feedback_verdict as enum (
  'accepted',               -- "this was right, used as-is"
  'accepted_with_edits',    -- "right idea, I edited it"
  'rejected_false_positive',-- "not actually an issue"
  'rejected_irrelevant',    -- "real issue, but not what I'd flag"
  'missed'                  -- "you missed something I had to add manually"
);

create table if not exists public.feedback (
  id            uuid primary key default gen_random_uuid(),
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  user_id       uuid not null references auth.users(id),
  submittal_id  uuid references public.submittals(id) on delete cascade,
  review_id     uuid references public.reviews(id) on delete cascade,
  kind          feedback_kind not null,
  verdict       feedback_verdict not null,
  -- The thing being judged (e.g., the AI draft text, the rule_id)
  target        jsonb not null,
  -- Optional reviewer note ("flagged correctly but cited wrong section")
  note          text,
  created_at    timestamptz not null default now()
);

create index if not exists feedback_agency_kind_idx on public.feedback(agency_id, kind, created_at desc);

-- =====================================================================
-- 9. audit_log  (immutable history)
-- =====================================================================
create table if not exists public.audit_log (
  id            bigserial primary key,
  agency_id     uuid not null references public.agencies(id) on delete cascade,
  actor_id      uuid references auth.users(id),
  entity_type   text not null,                     -- 'submittal' | 'review' | 'comment' | 'agency'
  entity_id     uuid,
  action        text not null,                     -- 'created' | 'status_changed' | 'comment_added' | etc.
  diff          jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists audit_log_entity_idx on public.audit_log(entity_type, entity_id, created_at desc);
create index if not exists audit_log_agency_idx on public.audit_log(agency_id, created_at desc);

-- =====================================================================
-- 10. llm_usage  (per-call cost log)
--    Keep this so we can report the per-submittal cost to the AHJ
--    AND watch our own LLM spend.
-- =====================================================================
create table if not exists public.llm_usage (
  id            bigserial primary key,
  agency_id     uuid references public.agencies(id) on delete set null,
  submittal_id  uuid references public.submittals(id) on delete set null,
  triage_run_id uuid references public.triage_runs(id) on delete set null,
  provider      text not null,                     -- 'anthropic' | 'openai'
  model         text not null,                     -- 'claude-opus-4-7' etc.
  purpose       text not null,                     -- 'extract_scope' | 'draft_comment' | etc.
  input_tokens  integer,
  output_tokens integer,
  cost_usd      numeric(10,6),
  latency_ms    integer,
  created_at    timestamptz not null default now()
);

create index if not exists llm_usage_agency_idx on public.llm_usage(agency_id, created_at desc);

-- =====================================================================
-- 11. updated_at trigger (reused)
-- =====================================================================
create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists agencies_updated_at on public.agencies;
create trigger agencies_updated_at  before update on public.agencies      for each row execute function public.tg_set_updated_at();
drop trigger if exists submittals_updated_at on public.submittals;
create trigger submittals_updated_at before update on public.submittals  for each row execute function public.tg_set_updated_at();
drop trigger if exists reviews_updated_at on public.reviews;
create trigger reviews_updated_at    before update on public.reviews      for each row execute function public.tg_set_updated_at();
drop trigger if exists comments_updated_at on public.review_comments;
create trigger comments_updated_at   before update on public.review_comments for each row execute function public.tg_set_updated_at();

-- =====================================================================
-- 12. Row-level security
-- =====================================================================
alter table public.agencies        enable row level security;
alter table public.agency_members  enable row level security;
alter table public.submittals      enable row level security;
alter table public.submittal_files enable row level security;
alter table public.triage_runs     enable row level security;
alter table public.reviews         enable row level security;
alter table public.review_comments enable row level security;
alter table public.feedback        enable row level security;
alter table public.audit_log       enable row level security;
alter table public.llm_usage       enable row level security;

-- agencies: members can read their own agency
drop policy if exists "agencies: member read" on public.agencies;
create policy "agencies: member read"
  on public.agencies for select using (id in (select public.user_agency_ids()));

-- agency_members: a user can read all members of agencies they belong to
drop policy if exists "members: read" on public.agency_members;
create policy "members: read"
  on public.agency_members for select using (agency_id in (select public.user_agency_ids()));

-- submittals: members of the agency can read; intake/admin/supervisor can insert; only admin can delete
drop policy if exists "submittals: member read" on public.submittals;
drop policy if exists "submittals: staff insert" on public.submittals;
drop policy if exists "submittals: staff update" on public.submittals;
create policy "submittals: member read"
  on public.submittals for select using (agency_id in (select public.user_agency_ids()));
create policy "submittals: staff insert"
  on public.submittals for insert with check (
    public.user_role_in(agency_id) in ('admin','supervisor','intake','reviewer')
  );
create policy "submittals: staff update"
  on public.submittals for update using (
    public.user_role_in(agency_id) in ('admin','supervisor','reviewer','intake')
  );

-- submittal_files: same agency-scoped read; service role does all writes
drop policy if exists "files: member read" on public.submittal_files;
create policy "files: member read"
  on public.submittal_files for select using (agency_id in (select public.user_agency_ids()));

-- triage_runs: read-only to members; service role writes
drop policy if exists "triage: member read" on public.triage_runs;
create policy "triage: member read"
  on public.triage_runs for select using (agency_id in (select public.user_agency_ids()));

-- reviews: members read; reviewers create/update their own
drop policy if exists "reviews: member read" on public.reviews;
drop policy if exists "reviews: reviewer write" on public.reviews;
drop policy if exists "reviews: reviewer update" on public.reviews;
create policy "reviews: member read"
  on public.reviews for select using (agency_id in (select public.user_agency_ids()));
create policy "reviews: reviewer write"
  on public.reviews for insert with check (
    public.user_role_in(agency_id) in ('admin','supervisor','reviewer')
    and reviewer_id = auth.uid()
  );
create policy "reviews: reviewer update"
  on public.reviews for update using (
    reviewer_id = auth.uid()
    or public.user_role_in(agency_id) in ('admin','supervisor')
  );

-- comments: members read; reviewers write on their own reviews
drop policy if exists "comments: member read" on public.review_comments;
drop policy if exists "comments: reviewer write" on public.review_comments;
drop policy if exists "comments: reviewer update" on public.review_comments;
drop policy if exists "comments: reviewer delete" on public.review_comments;
create policy "comments: member read"
  on public.review_comments for select using (agency_id in (select public.user_agency_ids()));
create policy "comments: reviewer write"
  on public.review_comments for insert with check (
    auth.uid() = created_by
    and public.user_role_in(agency_id) in ('admin','supervisor','reviewer')
  );
create policy "comments: reviewer update"
  on public.review_comments for update using (
    auth.uid() = created_by
    or public.user_role_in(agency_id) in ('admin','supervisor')
  );
create policy "comments: reviewer delete"
  on public.review_comments for delete using (
    auth.uid() = created_by
    or public.user_role_in(agency_id) in ('admin','supervisor')
  );

-- feedback: members read & write their own
drop policy if exists "feedback: member read" on public.feedback;
drop policy if exists "feedback: self write" on public.feedback;
create policy "feedback: member read"
  on public.feedback for select using (agency_id in (select public.user_agency_ids()));
create policy "feedback: self write"
  on public.feedback for insert with check (
    auth.uid() = user_id
    and agency_id in (select public.user_agency_ids())
  );

-- audit_log: members read; service role writes
drop policy if exists "audit: member read" on public.audit_log;
create policy "audit: member read"
  on public.audit_log for select using (agency_id in (select public.user_agency_ids()));

-- llm_usage: agency admins read; service role writes
drop policy if exists "llm_usage: admin read" on public.llm_usage;
create policy "llm_usage: admin read"
  on public.llm_usage for select using (
    agency_id in (select public.user_agency_ids())
    and public.user_role_in(agency_id) in ('admin','supervisor')
  );

-- =====================================================================
-- 13. seed: a single demo agency for development (idempotent)
-- =====================================================================
insert into public.agencies (slug, name, state, city, code_year, plan)
values
  ('demo-city', 'City of Demo, WA — Building & Permits', 'WA', 'Demo City', '2021', 'pilot')
on conflict (slug) do nothing;
