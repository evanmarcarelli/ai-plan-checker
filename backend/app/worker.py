"""Dedicated job worker — run as its own service:  python -m app.worker

Claims plan-check jobs from the Postgres-backed queue (db.claim_next_job,
which uses FOR UPDATE SKIP LOCKED) and runs them via job_processor.run_job.
The web service NEVER runs the pipeline; it only enqueues. That separation is
what eliminates the recurring bug class (event-loop stalls, web-tier OOM,
orphaned in-request jobs).

Lifecycle guarantees:
  * One job at a time per worker process (memory-safe). Scale by running
    more worker instances — SKIP LOCKED means they never collide.
  * A lease + heartbeat keeps a long job alive; a crashed worker's lease
    expires and the job is re-claimed (bounded by max_attempts).
  * A periodic reaper fails (and refunds) jobs that exhaust their retries.
  * SIGTERM (Render sends this on deploy) → stop claiming, finish the
    in-flight job, exit cleanly.
"""
import asyncio
import os
import signal
import socket
import uuid

from app.services import db
from app.services.job_processor import run_job
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How long a claim is held before it's considered abandoned. Generous
# relative to HEARTBEAT_SEC (20s) so a brief event-loop hiccup never causes
# a double-claim; small enough that a truly dead worker's job recovers fast.
LEASE_SEC = int(os.getenv("WORKER_LEASE_SEC", "180"))
# Idle poll interval when the queue is empty.
IDLE_SLEEP_SEC = float(os.getenv("WORKER_IDLE_SLEEP_SEC", "2"))
# How often to run the exhausted-job reaper.
REAP_EVERY_SEC = float(os.getenv("WORKER_REAP_EVERY_SEC", "60"))

_shutdown = asyncio.Event()


def _request_shutdown() -> None:
    if not _shutdown.is_set():
        logger.info("Shutdown signal received — finishing current job, then exiting")
    _shutdown.set()


async def _run() -> None:
    worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
    logger.info(f"Worker {worker_id} starting (lease={LEASE_SEC}s, idle_poll={IDLE_SLEEP_SEC}s)")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except (NotImplementedError, RuntimeError):
            # Windows / no event-loop signal support — fall back to signal.signal.
            signal.signal(sig, lambda *_: _request_shutdown())

    last_reap = 0.0
    while not _shutdown.is_set():
        # Periodic reaper: fail + refund jobs that used up their attempts.
        now = loop.time()
        if now - last_reap >= REAP_EVERY_SEC:
            try:
                n = await asyncio.to_thread(db.fail_exhausted_jobs)
                if n:
                    logger.warning(f"Reaper failed {n} exhausted job(s)")
            except Exception as e:
                logger.warning(f"Reaper error: {e}")
            last_reap = now

        # Claim the next job (atomic; returns None when the queue is empty).
        try:
            job = await asyncio.to_thread(db.claim_next_job, worker_id, LEASE_SEC)
        except Exception as e:
            logger.error(f"claim_next_job error: {e}")
            job = None

        if not job:
            # Sleep, but wake immediately on shutdown.
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=IDLE_SLEEP_SEC)
            except asyncio.TimeoutError:
                pass
            continue

        logger.info(f"Worker {worker_id} claimed job {job['id']} (attempt {job.get('attempts')})")
        try:
            await run_job(job["id"], worker_id, LEASE_SEC)
        except Exception as e:
            # A crash here leaves no terminal mark on purpose: the lease will
            # expire and another claim retries the job (up to max_attempts).
            logger.error(f"run_job crashed for {job['id']}: {e}", exc_info=True)

    logger.info("Worker stopped cleanly")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
