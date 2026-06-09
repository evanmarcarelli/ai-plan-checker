"""Runs a single plan-check job end to end.

Deliberately framework-free (no FastAPI): the web tier only *enqueues* jobs;
a dedicated worker process (app.worker) *claims* them and calls run_job().
Keeping the heavy 12-agent pipeline out of the web process is what makes
event-loop stalls, web-tier OOM, and orphaned in-request jobs impossible.

INVARIANT: every CPU-bound step (PDF render, vision rasterization, lossless
compression) MUST run via asyncio.to_thread so the event loop stays free to
fire the lease heartbeat. If a blocking call ran directly on the loop for
longer than the lease, the heartbeat would stall and another worker could
reclaim a job that is actually still alive.
"""
import asyncio
import os
from datetime import datetime

import aiofiles

from app.config import settings
from app.models.schemas import ProcessingJob, JobStatus, AgentLog
from app.agents.workflow import PlanCheckerWorkflow
from app.services import db
from app.services import email_service
from app.services.pdf_compressor import compress as compress_pdf
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Per-attempt wall-clock ceiling for the pipeline itself. Well above the
# typical 90-120s end-to-end runtime, tight enough that a hung dependency
# surfaces as a clean failure instead of pinning a worker.
JOB_TIMEOUT_SEC = 12 * 60

# How often the worker extends its lease while a job runs. Must stay well
# under WORKER_LEASE_SEC (see app.worker) so a healthy-but-quiet job (a long
# silent Surveyor extraction) is never reclaimed as abandoned.
HEARTBEAT_SEC = 20


def _terminal_fail(job_id: str, message: str) -> None:
    """Mark a job failed for good and refund its credit idempotently.

    Used for *deterministic* failures (bad file, pipeline error, timeout) —
    retrying them would just fail again and burn money. A worker *crash*,
    by contrast, leaves no terminal mark, so the lease expires and the job
    is retried. refund_job_credit is a no-op if the job wasn't charged or
    was already refunded, so this is always safe to call.
    """
    db.update_job(job_id, {"status": "failed", "error": message})
    try:
        db.refund_job_credit(job_id)
    except Exception as e:
        logger.error(f"Job {job_id}: refund failed: {e}")


async def run_job(job_id: str, worker_id: str, lease_sec: int) -> None:
    """Process one claimed job: download → validate → compress → run the
    pipeline → persist. The job row is already 'processing' with a lease
    (set atomically by claim_next_job); this function keeps the lease alive
    and writes the terminal state."""
    row = db.get_job(job_id)
    if not row:
        logger.error(f"Job {job_id}: row vanished before processing")
        return

    storage_path = row.get("storage_path")
    file_path = os.path.join(settings.upload_folder, f"{job_id}.pdf")

    # Lease keep-alive. Runs for the whole job; cancelled in finally.
    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SEC)
            try:
                await asyncio.to_thread(db.heartbeat_job, job_id, worker_id, lease_sec)
            except Exception:
                pass

    heartbeat_task = asyncio.create_task(_heartbeat())

    try:
        # 1. Download from Supabase Storage (network I/O → thread).
        try:
            content = await asyncio.to_thread(db.download_plan, storage_path)
        except Exception as e:
            logger.error(f"Job {job_id}: storage download failed: {e}")
            _terminal_fail(job_id, "Uploaded file not found in storage.")
            return

        # 2. Validate magic bytes.
        if len(content) < 5 or content[:4] != b"%PDF":
            logger.error(f"Job {job_id}: not a valid PDF")
            _terminal_fail(job_id, "File is not a valid PDF.")
            return

        # 3. Write to local disk, then free the in-memory copy immediately.
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)
        del content

        # 4. Lossless compression (best-effort, CPU-bound → thread).
        try:
            _, before_b, after_b = await asyncio.to_thread(compress_pdf, file_path)
            if after_b < before_b:
                saved = (1 - after_b / before_b) * 100
                logger.info(f"Job {job_id}: compressed {before_b:,} -> {after_b:,} bytes (-{saved:.1f}%)")
        except Exception as e:
            logger.warning(f"Job {job_id}: compression skipped ({e})")

        # 5. Run the multi-agent pipeline + persist results.
        await _run_pipeline(job_id, file_path, row)

    finally:
        heartbeat_task.cancel()
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        # The original upload is no longer needed once processed.
        if storage_path:
            db.delete_plan(storage_path)


async def _run_pipeline(job_id: str, file_path: str, row: dict) -> None:
    """Run the workflow and persist the report, or fail terminally."""
    db.update_job(job_id, {"progress": 0})

    workflow = PlanCheckerWorkflow()

    job_shell = ProcessingJob(
        job_id=job_id,
        status=JobStatus.PROCESSING,
        filename=row.get("filename", "unknown.pdf"),
        file_size=row.get("file_size", 0),
        created_at=datetime.utcnow(),
    )

    last_persisted_progress = 0

    async def on_log(log: AgentLog):
        nonlocal last_persisted_progress
        db.insert_log(job_id, log.agent, log.level, log.message, log.data or None)
        if job_shell.progress != last_persisted_progress or job_shell.current_agent:
            db.update_job(job_id, {
                "progress": job_shell.progress,
                "current_agent": job_shell.current_agent,
                "agents_completed": job_shell.agents_completed,
            })
            last_persisted_progress = job_shell.progress

    try:
        report = await asyncio.wait_for(
            workflow.run(job_shell, file_path, log_callback=on_log),
            timeout=JOB_TIMEOUT_SEC,
        )

        db.update_job(job_id, {
            "status": "completed",
            "progress": 100,
            "current_agent": None,
            "completed_at": datetime.utcnow().isoformat(),
            "agents_completed": job_shell.agents_completed,
            "jurisdiction": (report.jurisdiction.model_dump() if report.jurisdiction else None),
            "plan_data": (report.plan_data.model_dump() if report.plan_data else None),
            "summary": report.summary.model_dump() if report.summary else None,
            "department_reviews": [dr.model_dump() for dr in (report.department_reviews or [])],
            "recommendations": report.recommendations,
            "code_versions": report.code_versions,
            "sources_used": report.sources_used,
            "notes": report.auditor_notes,
        })

        # Persist findings rows for fast filtering.
        row2 = db.get_job(job_id)
        finding_rows = []
        for f in (report.findings or []):
            req = f.code_requirement
            dept_name = ""
            dept_code = ""
            for dr in report.department_reviews or []:
                if any(ff.finding_id == f.finding_id for ff in dr.findings):
                    dept_name = dr.department
                    dept_code = dr.department_code
                    break
            finding_rows.append({
                "job_id": job_id,
                "user_id": row2["user_id"],
                "department": dept_name,
                "department_code": dept_code,
                "code_id": req.code_id,
                "code_section": req.section,
                "code_name": req.code_name,
                "category": req.category,
                "status": f.status.value if hasattr(f.status, "value") else f.status,
                "severity": f.severity,
                "plan_value": f.plan_value,
                "required_value": f.required_value,
                "description": f.description,
                "recommendation": f.recommendation,
                "page_references": f.page_references or [],
            })
        if finding_rows:
            for i in range(0, len(finding_rows), 100):
                db.insert_findings(finding_rows[i:i+100])

        logger.info(f"Job {job_id} completed: {len(finding_rows)} findings")

        # "Your review is ready" email (no-op without RESEND_API_KEY).
        try:
            row3 = db.get_job(job_id)
            user_id3 = row3.get("user_id")
            client = db.admin()
            auth_user = client.auth.admin.get_user_by_id(user_id3) if user_id3 else None
            user_email = getattr(getattr(auth_user, "user", None), "email", None) if auth_user else None
            if user_email:
                email_service.send_report_ready(user_email, job_id, row3.get("filename", "your plan"))
        except Exception as e:
            logger.warning(f"send_report_ready failed for job {job_id}: {e}")

    except asyncio.TimeoutError:
        msg = (
            f"Plan review exceeded the {JOB_TIMEOUT_SEC // 60}-minute processing "
            f"timeout. Please run the check again."
        )
        logger.error(f"Job {job_id} timed out: {msg}")
        _terminal_fail(job_id, msg)

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        _terminal_fail(job_id, str(e))
