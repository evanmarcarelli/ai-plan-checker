-- ============================================================
-- Migration 007: durable, lease-based job queue
--
-- WHY THIS EXISTS
-- The pipeline used to run inside the web process via FastAPI
-- BackgroundTasks. That single decision produced a recurring class of
-- bugs: jobs orphaned at "processing" on an OOM/redeploy, the event loop
-- stalling on PDF/vision work, and the web tier OOM-killing itself. The
-- fix is to move the pipeline into a dedicated worker process that pulls
-- work from a real queue. This migration turns the existing `jobs` table
-- INTO that queue.
--
-- DESIGN
--  * claim_next_job  — one atomic FOR UPDATE SKIP LOCKED claim. Many
--                      workers can pull different jobs with zero contention.
--                      Also re-claims jobs whose lease expired (the worker
--                      that held them crashed), up to max_attempts.
--  * heartbeat_job   — a running worker extends its lease so a long-but-
--                      healthy job is never mistaken for abandoned.
--  * refund_job_credit — idempotent one-credit refund (credit_refunded flag
--                      makes a retry / double-call safe). This closes the
--                      "orphaned jobs are not auto-refunded" gap left by the
--                      old in-process recovery code.
--  * fail_exhausted_jobs — reaper: a job that used up its attempts and whose
--                      lease has expired is failed (and refunded) for good.
--
-- All functions are SECURITY DEFINER with a pinned search_path, matching
-- migration 006. The backend calls them with the service-role key.
--
-- BACKWARD COMPATIBILITY: the application code calls these via RPC with a
-- safe fallback (see db.py), and the new columns are added with IF NOT
-- EXISTS + defaults, so deploying code ahead of this migration never
-- breaks uploads — uploads simply queue until the worker + functions exist.
-- ============================================================

alter table public.jobs
  add column if not exists locked_by        text,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists attempts         integer not null default 0,
  add column if not exists max_attempts     integer not null default 3,
  add column if not exists credit_charged   boolean not null default false,
  add column if not exists credit_refunded  boolean not null default false;

-- Supports the claim query's ordering + predicate.
create index if not exists jobs_queue_idx
  on public.jobs (status, lease_expires_at, created_at);


-- ── claim_next_job ───────────────────────────────────────────
-- Atomically claim the next runnable job for this worker. Returns the
-- claimed row (now status='processing' with a fresh lease), or no row when
-- the queue is empty. Runnable = a 'pending' job, OR a 'processing' job
-- whose lease expired (its worker died) — provided attempts remain.
create or replace function public.claim_next_job(
  p_worker_id text,
  p_lease_sec integer default 180
)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
    from public.jobs
   where (status = 'pending'
          or (status = 'processing' and lease_expires_at < now()))
     and attempts < max_attempts
   order by created_at
   for update skip locked
   limit 1;

  if v_id is null then
    return;   -- empty queue
  end if;

  return query
  update public.jobs
     set status           = 'processing',
         locked_by        = p_worker_id,
         lease_expires_at = now() + make_interval(secs => p_lease_sec),
         attempts         = attempts + 1,
         updated_at       = now()
   where id = v_id
  returning *;
end;
$$;


-- ── heartbeat_job ────────────────────────────────────────────
-- Extend the lease for a job this worker still owns. Returns the new
-- expiry, or NULL if the worker no longer owns it (lease was reclaimed) —
-- which signals the worker it should stop.
create or replace function public.heartbeat_job(
  p_job_id    uuid,
  p_worker_id text,
  p_lease_sec integer default 180
)
returns timestamptz
language sql
security definer
set search_path = public
as $$
  update public.jobs
     set lease_expires_at = now() + make_interval(secs => p_lease_sec),
         updated_at       = now()
   where id = p_job_id
     and locked_by = p_worker_id
     and status = 'processing'
  returning lease_expires_at;
$$;


-- ── refund_job_credit ────────────────────────────────────────
-- Idempotently refund the one credit a failed job consumed. The
-- credit_refunded flag (flipped in the same transaction as the balance
-- bump) guarantees a retry or a double-call can never double-refund.
-- Returns true only when a refund actually happened on this call.
create or replace function public.refund_job_credit(
  p_job_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user     uuid;
  v_charged  boolean;
  v_refunded boolean;
begin
  select user_id, credit_charged, credit_refunded
    into v_user, v_charged, v_refunded
    from public.jobs
   where id = p_job_id
   for update;

  if not found or not v_charged or v_refunded then
    return false;   -- nothing to refund, or already refunded
  end if;

  update public.profiles
     set credits_remaining = credits_remaining + 1
   where id = v_user;

  update public.jobs
     set credit_refunded = true,
         updated_at = now()
   where id = p_job_id;

  return true;
end;
$$;


-- ── fail_exhausted_jobs ──────────────────────────────────────
-- Reaper: permanently fail (and idempotently refund) any job that has used
-- up its attempts and whose lease has expired. Called periodically by the
-- worker. Returns the number of jobs failed this sweep.
create or replace function public.fail_exhausted_jobs()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  r record;
  n integer := 0;
begin
  for r in
    select id from public.jobs
     where status in ('pending', 'processing')
       and attempts >= max_attempts
       and (lease_expires_at is null or lease_expires_at < now())
     for update skip locked
  loop
    update public.jobs
       set status = 'failed',
           error  = 'Processing failed after repeated attempts. Please run the check again.',
           updated_at = now()
     where id = r.id;
    perform public.refund_job_credit(r.id);
    n := n + 1;
  end loop;
  return n;
end;
$$;
