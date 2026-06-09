"""Job worker — runnable two ways:

  1. In-process inside the web service (RUN_WORKER_IN_WEB=true, the DEFAULT):
     the app lifespan starts run_worker() as a background task, so a single
     Render deployment both serves the API AND drains the job queue. No second
     service to provision.

  2. As a dedicated process (`python -m app.worker`): a separate Render worker
     for horizontal scale. Set RUN_WORKER_IN_WEB=false on the web service when
     you run this so you're not paying for two worker pools.

Either way it claims jobs from the Postgres queue and runs them via
job_processor.run_job. Claiming is atomic once migration 007 is applied; before
that it falls back to a single-instance-safe conditional UPDATE (see
db.claim_next_job), so processing works even pre-migration.
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

LEASE_SEC = int(os.getenv("WORKER_LEASE_SEC", "180"))
IDLE_SLEEP_SEC = float(os.getenv("WORKER_IDLE_SLEEP_SEC", "2"))
REAP_EVERY_SEC = float(os.getenv("WORKER_REAP_EVERY_SEC", "60"))


async def run_worker(shutdown: asyncio.Event, *, label: str = "worker") -> None:
    """The claim → run → reap loop. Runs until `shutdown` is set. The CALLER
    owns signal handling (standalone wires SIGTERM; the web lifespan sets the
    event on app shutdown) so this is safe to run inside uvicorn."""
    worker_id = f"{socket.gethostname()}:{label}:{uuid.uuid4().hex[:8]}"
    logger.info(f"Worker {worker_id} starting (lease={LEASE_SEC}s, idle_poll={IDLE_SLEEP_SEC}s)")
    loop = asyncio.get_running_loop()
    last_reap = 0.0

    while not shutdown.is_set():
        # Periodic reaper (no-op until migration 007 exposes the RPC).
        now = loop.time()
        if now - last_reap >= REAP_EVERY_SEC:
            try:
                n = await asyncio.to_thread(db.fail_exhausted_jobs)
                if n:
                    logger.warning(f"Reaper failed {n} exhausted job(s)")
            except Exception as e:
                logger.warning(f"Reaper error: {e}")
            last_reap = now

        try:
            job = await asyncio.to_thread(db.claim_next_job, worker_id, LEASE_SEC)
        except Exception as e:
            logger.error(f"claim_next_job error: {e}")
            job = None

        if not job:
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=IDLE_SLEEP_SEC)
            except asyncio.TimeoutError:
                pass
            continue

        logger.info(f"Worker {worker_id} claimed job {job['id']} (attempt {job.get('attempts')})")
        try:
            await run_job(job["id"], worker_id, LEASE_SEC)
        except Exception as e:
            # Crash here leaves no terminal mark on purpose: lease expiry (or the
            # legacy staleness guard pre-migration) requeues / fails it later.
            logger.error(f"run_job crashed for {job['id']}: {e}", exc_info=True)

    logger.info(f"Worker {worker_id} stopped cleanly")


def _run_standalone() -> None:
    """Entry point for the dedicated worker process: own the signals, then run."""
    shutdown = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()

        def _request_shutdown() -> None:
            if not shutdown.is_set():
                logger.info("Shutdown signal received — finishing current job, then exiting")
            shutdown.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, lambda *_: _request_shutdown())

        await run_worker(shutdown, label="svc")

    asyncio.run(_main())


def main() -> None:
    _run_standalone()


if __name__ == "__main__":
    main()
