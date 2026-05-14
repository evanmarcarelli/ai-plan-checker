-- ============================================================
-- ai-plan-checker initial schema
-- ============================================================

-- ---------- Enums ----------
create type job_status as enum ('pending','processing','completed','failed');
create type compliance_status as enum ('compliant','non_compliant','needs_review','not_applicable');
create type review_dept_status as enum ('pending','cleared','conditional','rejected');

-- ---------- Profiles (extends auth.users) ----------
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  display_name text,
  firm_name text,
  role text default 'reviewer',          -- 'reviewer' | 'admin'
  credits_remaining integer default 1,    -- 1 free review on signup
  stripe_customer_id text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ---------- Jobs ----------
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  file_size bigint default 0,
  storage_path text,                      -- supabase storage path (set when we upload to storage)
  status job_status default 'pending',
  progress integer default 0,
  current_agent text,
  agents_completed text[] default '{}',
  error text,
  jurisdiction jsonb,
  plan_data jsonb,
  summary jsonb,
  department_reviews jsonb,
  recommendations jsonb,
  code_versions jsonb,
  sources_used jsonb,
  notes text,
  llm_cost_usd numeric(10,4) default 0,
  llm_input_tokens integer default 0,
  llm_output_tokens integer default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  completed_at timestamptz
);

create index jobs_user_id_idx on public.jobs (user_id);
create index jobs_status_idx on public.jobs (status);
create index jobs_created_at_idx on public.jobs (created_at desc);

-- ---------- Findings (denormalized for filtering/search) ----------
create table public.findings (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  department text not null,               -- 'Building & Safety', 'Fire', etc.
  department_code text not null,          -- 'building_safety', 'fire', etc.
  code_id text not null,
  code_section text,
  code_name text,
  category text,
  status compliance_status not null,
  severity text default 'medium',         -- critical|high|medium|low
  plan_value text,
  required_value text,
  description text,
  recommendation text,
  page_references integer[] default '{}',
  created_at timestamptz default now()
);

create index findings_job_id_idx on public.findings (job_id);
create index findings_user_id_idx on public.findings (user_id);
create index findings_department_code_idx on public.findings (department_code);
create index findings_severity_idx on public.findings (severity);
create index findings_status_idx on public.findings (status);

-- ---------- Agent logs (live stream for the UI) ----------
create table public.agent_logs (
  id bigserial primary key,
  job_id uuid not null references public.jobs(id) on delete cascade,
  ts timestamptz default now(),
  agent text not null,
  level text default 'info',
  message text not null,
  data jsonb
);

create index agent_logs_job_id_ts_idx on public.agent_logs (job_id, ts);

-- ---------- updated_at trigger ----------
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();
create trigger jobs_set_updated_at before update on public.jobs
  for each row execute function public.set_updated_at();

-- ---------- Auto-create profile on signup ----------
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)));
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
alter table public.profiles    enable row level security;
alter table public.jobs        enable row level security;
alter table public.findings    enable row level security;
alter table public.agent_logs  enable row level security;

-- ---------- profiles: users can read/update only their own ----------
create policy "Users can read own profile"
  on public.profiles for select
  using (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = id);

-- ---------- jobs: users can CRUD only their own ----------
create policy "Users can read own jobs"
  on public.jobs for select
  using (auth.uid() = user_id);

create policy "Users can insert own jobs"
  on public.jobs for insert
  with check (auth.uid() = user_id);

create policy "Users can update own jobs"
  on public.jobs for update
  using (auth.uid() = user_id);

create policy "Users can delete own jobs"
  on public.jobs for delete
  using (auth.uid() = user_id);

-- ---------- findings: read-only for owners (backend writes via service role) ----------
create policy "Users can read own findings"
  on public.findings for select
  using (auth.uid() = user_id);

-- ---------- agent_logs: read-only for owners ----------
create policy "Users can read own agent logs"
  on public.agent_logs for select
  using (
    auth.uid() = (select user_id from public.jobs where jobs.id = agent_logs.job_id)
  );
