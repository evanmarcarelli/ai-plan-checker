# Durable job queue — architecture & runbook

## TL;DR of the problem this fixes

For weeks, a string of "unrelated" backend fixes were all the **same root
cause** wearing different hats:

| Commit | Symptom | Real cause |
|---|---|---|
| `e795197` recover orphaned jobs | jobs frozen at "processing" forever | in-process task dies on OOM/redeploy |
| `ba450c4` blocking PDF off event loop | dashboard frozen at 5%, `/health` starved | CPU work running on the web event loop |
| `81c6db4` stop OOM crashes | 503s, OOM-kill, `/health` trips | pipeline shares the web process's RAM |
| heartbeat / sweep / 12-min timeout | "stuck at 5% for 15 min" | scaffolding to prop up jobs run in the wrong place |

All of it traced to one decision: **the plan-check pipeline ran inside the web
process** via FastAPI `BackgroundTasks`. A web process is meant to be
ephemeral (accept request, respond in <1s, stay light). Running a 90s–12min,
PDF-rasterizing, memory-hungry, 12-agent job inside it is the mismatch that
produced the whole bug class.

## The fix: split web from worker

```
                 ┌─────────────┐   enqueue (status=pending)   ┌──────────────┐
  browser  ──▶   │  web tier   │ ───────────────────────────▶ │  Postgres    │
                 │ (app.main)  │                               │  jobs table  │
                 │  validate   │ ◀── status/logs (read) ────── │  = the queue │
                 │  + enqueue  │                               └──────┬───────┘
                 └─────────────┘                                      │ claim
                                                                      │ (FOR UPDATE
                                                              ┌───────▼───────┐ SKIP LOCKED)
                                                              │  worker tier  │
                                                              │ (app.worker)  │
                                                              │  run pipeline │
                                                              └───────────────┘
```

- **Web** (`app.main` / `app.api.routes`) only validates, reserves a credit,
  and writes a `pending` job row. It never imports or runs the pipeline.
- **Worker** (`app.worker` → `app.services.job_processor`) claims jobs
  atomically, runs the pipeline, holds a **lease** it heartbeats, and writes
  the terminal state.

This makes the entire old bug class *structurally impossible*:

- **No orphaned jobs.** A worker crash/redeploy leaves the lease to expire;
  another claim retries the job (bounded by `max_attempts`). The reaper
  (`fail_exhausted_jobs`) fails + refunds anything that exhausts its retries.
- **No event-loop stalls in the web tier.** The web process does no heavy
  work, so status polls and `/health` are always responsive.
- **No web-tier OOM.** A whole plan set is never held in the web process;
  that's why the web service can run on `starter` (512MB) again.

## Failure semantics (important)

There are two distinct failure modes, handled differently on purpose:

1. **Deterministic job failure** (bad PDF, pipeline exception, per-attempt
   timeout) → `job_processor._terminal_fail` marks the job `failed` and
   refunds **once**. Retrying these would just fail again and burn LLM money,
   so they are *not* retried.
2. **Worker death** (OOM, redeploy, SIGKILL) → no terminal mark is written, so
   the lease simply expires and the job is re-claimed and retried, up to
   `max_attempts` (default 3).

Refunds are **idempotent**: `refund_job_credit` flips a `credit_refunded` flag
in the same transaction as the balance bump, so a retry or double-call can
never mint a credit. (This closes the "orphaned jobs are not auto-refunded"
gap noted in `e795197`.)

## Invariant the worker relies on

Every CPU-bound step in the pipeline (PDF render, vision rasterization,
compression) **must** run via `asyncio.to_thread`. If a blocking call sat on
the event loop longer than the lease, the heartbeat couldn't fire and another
worker could reclaim a job that's actually still alive. The known blockers are
already threaded (`surveyor`, `vision_extractor`, and now `compress`). Keep it
that way.

## Files

| File | Role |
|---|---|
| `migrations/007_job_queue.sql` | adds lease/attempt/refund columns + `claim_next_job`, `heartbeat_job`, `refund_job_credit`, `fail_exhausted_jobs` |
| `app/worker.py` | `run_worker()` claim → run → reap loop; runs in-process (web lifespan) or standalone (`python -m app.worker`) |
| `app/main.py` | lifespan starts/stops the in-process worker when `RUN_WORKER_IN_WEB=true` (default) |
| `app/services/job_processor.py` | the pipeline runner (download → validate → compress → run → persist) |
| `app/api/routes.py` | web tier, **enqueue-only** (the worker does the work, even when co-located) |
| `app/services/db.py` | queue RPC wrappers + a conditional-claim fallback that works pre-migration |
| `render.yaml` | web `standard` runs combined by default; optional `up2code-worker` for scale-out |

## Single-service by default (no second service, no hard migration dependency)

The worker loop runs **inside the web service** by default
(`RUN_WORKER_IN_WEB=true`), as a background task started by the app lifespan.
So a normal deploy of the existing `up2code-backend` service already processes
jobs — there is **nothing extra to provision**.

It also works **before migration 007 is applied**: `claim_next_job` falls back
to a conditional `UPDATE pending -> processing` (atomic per row, so no double-
claim). Applying migration 007 is an *upgrade* — it adds leases, bounded retry,
and idempotent refunds — not a prerequisite for jobs to run.

## Deploy / runbook

**Default (single service):**
1. **Deploy.** `autoDeploy: true` redeploys `up2code-backend` on push. The web
   process serves the API *and* runs the worker loop. Confirm in the logs:
   - `In-process job worker started (RUN_WORKER_IN_WEB=true)`
   - `Worker <id> starting (lease=180s ...)`; on upload, `claimed job <id>`.
2. **Apply migration 007** in the Supabase SQL editor when convenient
   (`backend/migrations/007_job_queue.sql`, idempotent) to enable leases +
   idempotent refunds. Jobs already process without it; this hardens recovery.
3. **Verify** a real upload completes end-to-end on the dashboard.

**Optional — scale the worker onto its own service** (only when one process
can't keep up):
1. Apply migration 007 (required for safe multi-instance claiming).
2. Set `RUN_WORKER_IN_WEB=false` on the web service (it then only enqueues; can
   drop to `starter`).
3. Provision the `up2code-worker` service from the blueprint and set its
   `sync: false` secrets. Raise `numInstances` for more throughput.

### Tunables (worker env vars)

| Var | Default | Meaning |
|---|---|---|
| `WORKER_LEASE_SEC` | 180 | how long a claim is held before it's reclaimable |
| `WORKER_IDLE_SLEEP_SEC` | 2 | poll interval when the queue is empty |
| `WORKER_REAP_EVERY_SEC` | 60 | how often to fail+refund exhausted jobs |

### Scaling

Raise the worker's `numInstances` in `render.yaml`. `FOR UPDATE SKIP LOCKED`
guarantees instances never claim the same job, so throughput scales linearly
with no coordination.

## Tests

- `tests/test_job_queue.py` — enqueue-only web path, idempotent refund
  (including the pre-migration fallback), graceful RPC-missing behavior,
  terminal-fail-refunds-once.
- `tests/test_api.py` — updated: the web tier no longer has an in-process task
  to stub; `FakeDB` carries the new queue columns.
