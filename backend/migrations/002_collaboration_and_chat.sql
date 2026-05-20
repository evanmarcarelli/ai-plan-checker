-- ============================================================
-- Migration 002: collaboration + AI assistant chat
--
-- Adds three tables on top of the v1 schema:
--   report_shares    — share-token-based access to a job/report for guests
--                      who don't (yet) have an account
--   finding_comments — threaded discussion attached to a specific finding;
--                      authored by either a logged-in user OR a guest who
--                      has a valid share token
--   chat_messages    — per-job AI-assistant conversation persisted so any
--                      collaborator looking at the report can see what's been
--                      asked and answered
-- ============================================================

-- ---------- report_shares ----------
-- Each row = one invitation to view/comment on a job's report.
-- token is the secret the guest passes via X-Share-Token header.
create table if not exists public.report_shares (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete cascade,
  invited_email text,                            -- nullable: open link
  invited_name  text,                            -- display name shown in UI
  role text not null default 'commenter',        -- 'viewer' | 'commenter'
  token text not null unique,                    -- URL-safe random
  expires_at timestamptz,                        -- nullable = never expires
  revoked_at timestamptz,                        -- soft delete
  last_used_at timestamptz,
  created_at timestamptz default now()
);

create index if not exists report_shares_job_id_idx on public.report_shares(job_id);
create index if not exists report_shares_token_idx  on public.report_shares(token);
create index if not exists report_shares_created_by_idx on public.report_shares(created_by);

-- ---------- finding_comments ----------
-- author_user_id is set when the commenter is logged in.
-- otherwise author_share_id + author_display points to the guest's share row.
create table if not exists public.finding_comments (
  id uuid primary key default gen_random_uuid(),
  finding_id uuid not null references public.findings(id) on delete cascade,
  job_id uuid not null references public.jobs(id) on delete cascade,
  author_user_id  uuid references auth.users(id) on delete set null,
  author_share_id uuid references public.report_shares(id) on delete set null,
  author_display  text not null,                 -- always populated for rendering
  author_email    text,                          -- optional; for "notify the author"
  body text not null,
  created_at timestamptz default now()
);

create index if not exists finding_comments_finding_id_idx on public.finding_comments(finding_id);
create index if not exists finding_comments_job_id_created_idx on public.finding_comments(job_id, created_at);

-- ---------- chat_messages ----------
-- Per-job AI-assistant conversation. role = 'user' | 'assistant' | 'system'.
create table if not exists public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  author_user_id  uuid references auth.users(id) on delete set null,
  author_share_id uuid references public.report_shares(id) on delete set null,
  author_display  text,
  role text not null,                            -- 'user' | 'assistant'
  content text not null,
  citations jsonb default '[]'::jsonb,           -- list of {citation, source_text}
  created_at timestamptz default now()
);

create index if not exists chat_messages_job_id_created_idx on public.chat_messages(job_id, created_at);

-- ---------- updated_at not needed: these tables are append-only ----------

-- ============================================================
-- ROW LEVEL SECURITY
-- All collab tables: the backend writes via the service role and exposes
-- access through application-level token checks. RLS is restrictive by
-- default; only owners can read directly via the anon key.
-- ============================================================
alter table public.report_shares    enable row level security;
alter table public.finding_comments enable row level security;
alter table public.chat_messages    enable row level security;

-- Owners (the user who ran the job) can read shares + comments + chat on their jobs
create policy "Owners read own shares"
  on public.report_shares for select
  using (auth.uid() = created_by);

create policy "Owners insert own shares"
  on public.report_shares for insert
  with check (auth.uid() = created_by);

create policy "Owners update own shares"
  on public.report_shares for update
  using (auth.uid() = created_by);

create policy "Owners read finding comments on own jobs"
  on public.finding_comments for select
  using (
    auth.uid() = (select user_id from public.jobs where jobs.id = finding_comments.job_id)
  );

create policy "Owners read chat messages on own jobs"
  on public.chat_messages for select
  using (
    auth.uid() = (select user_id from public.jobs where jobs.id = chat_messages.job_id)
  );

-- All writes from guests go through the backend (service role), so there is
-- NO anon insert policy — that's intentional. The backend validates the
-- share token then writes on behalf of the guest.
