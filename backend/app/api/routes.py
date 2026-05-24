"""API routes — DB-backed job storage with Supabase auth."""
import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends, status, Request
from fastapi.responses import StreamingResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
import aiofiles
import jwt as _jwt

from app.config import settings
from app.models.schemas import (
    UploadResponse, JobStatusResponse, ProcessingJob, JobStatus,
    AgentLog, ComplianceReport,
)
from app.agents.workflow import PlanCheckerWorkflow
from app.services.export_service import export_service
from app.services import db
from app.services import email_service
from app.services.pdf_compressor import compress as compress_pdf
from app.services.auth import get_current_user
from app.utils.logger import get_logger

# ─────────────────────────────────────────────────────────────────────
# Admin bypass: emails in settings.admin_emails are exempt from both
# credit decrement on /upload AND the rate limit. Allowlist is env-driven
# so granting/revoking is a config change with no DB migration.
# ─────────────────────────────────────────────────────────────────────

def _is_admin_user(user: Dict[str, Any]) -> bool:
    """True if the resolved user's email is in the admin allowlist."""
    email = (user.get("email") or "").lower()
    return bool(email) and email in settings.admin_email_set


def _maybe_decrement_credits(user: Dict[str, Any]) -> int:
    """Decrement one credit for a normal user; bypass for admins.

    Returns the new credit balance (or a sentinel ≥ the limit for admins).
    Raises HTTPException 402 if a non-admin user is out of credits.
    """
    if not settings.require_auth:
        return 99_999
    if _is_admin_user(user):
        return 99_999
    new_balance = db.decrement_credits(user["id"], 1)
    if new_balance < 0:
        raise HTTPException(
            status_code=402,
            detail="No review credits remaining. Please purchase additional credits to continue.",
        )
    return new_balance


# Rate limiter — keyed by user id when available, falls back to IP.
# Admin emails get a unique key per request → never hit the per-user
# bucket → effectively unlimited.
def _rate_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        # Decode the JWT WITHOUT verification (we just want the email claim
        # to check the allowlist — real signature verification happens later
        # in get_current_user when the route actually runs).
        try:
            claims = _jwt.decode(token, options={"verify_signature": False})
            email = (claims.get("email") or "").lower()
            if email and email in settings.admin_email_set:
                return f"admin:{uuid.uuid4()}"
        except Exception:
            pass
        return f"u:{token[-24:]}"
    return get_remote_address(request)

limiter = Limiter(key_func=_rate_key)

logger = get_logger(__name__)

router = APIRouter()


def _job_row_to_response(row: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a DB row into the JobStatusResponse contract."""
    report = None
    if row.get("summary") or row.get("department_reviews"):
        report = {
            "report_id": row.get("id"),
            "job_id": row.get("id"),
            "generated_at": row.get("completed_at"),
            "jurisdiction": row.get("jurisdiction"),
            "plan_data": row.get("plan_data"),
            "summary": row.get("summary") or {},
            "department_reviews": row.get("department_reviews") or [],
            "recommendations": row.get("recommendations") or [],
            "code_versions": row.get("code_versions") or {},
            "sources_used": row.get("sources_used") or [],
            "auditor_notes": row.get("notes"),
            "findings": [],  # findings table is fetched separately if needed
        }
    return {
        "job_id": row["id"],
        "status": row["status"],
        "progress": row.get("progress", 0),
        "current_agent": row.get("current_agent"),
        "agents_completed": row.get("agents_completed") or [],
        "error": row.get("error"),
        "report": report,
        "logs": [],  # logs are fetched via separate endpoint
    }


# ============================================================
# Upload
# ============================================================

from pydantic import BaseModel as _BM


class StartReviewBody(_BM):
    """User has already uploaded the PDF to Supabase Storage; tell us where."""
    storage_path: str       # e.g. "<user_id>/<uuid>.pdf"
    filename: str           # original filename for display
    file_size: int          # bytes


@router.post("/upload", response_model=UploadResponse)
# Three layers of throttling on the most expensive endpoint:
#  - per-minute  : guards against burst abuse from a stolen token
#  - per-hour    : protects Anthropic budget if a user's script goes rogue
#  - per-day     : hard ceiling regardless of subscription (revisit when paid
#                  tiers are live; until then this caps free-tier blast radius)
# The credit-check below still enforces the subscription-level entitlement;
# this rate limit is the safety net BEFORE we touch the DB.
@limiter.limit("3/minute;15/hour;50/day")
async def start_review(
    request: Request,
    body: StartReviewBody,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Start a compliance review from a PDF already uploaded to Supabase Storage.

    The browser uploads the PDF directly to Supabase (bypassing this backend),
    then calls this endpoint with the storage path. We download the file
    here using the service role, then run the agent pipeline.

    Rate limited to 10 uploads/min per user.
    """
    # Fast-path validations only — return to the browser in <1 second.
    # All heavy work (storage download, PDF magic-byte check, compression,
    # 12-agent pipeline) happens in the background task below.

    if not body.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Defense-in-depth: storage path must be under this user's folder.
    # (Storage RLS already enforces this on upload, but we re-check here.)
    if not body.storage_path.startswith(f"{user['id']}/"):
        raise HTTPException(status_code=403, detail="Storage path does not belong to this user")

    max_size = settings.max_upload_size_mb * 1024 * 1024
    if body.file_size > max_size:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_size_mb}MB limit")

    # Credit check (admin allowlist bypasses; see _maybe_decrement_credits above).
    _maybe_decrement_credits(user)

    # Create DB row (instant)
    job_id = db.create_job(
        user_id=user["id"],
        filename=body.filename,
        file_size=body.file_size,
        storage_path=body.storage_path,
    )

    logger.info(f"Job {job_id} queued for user {user['id']}: {body.filename} ({body.file_size:,} bytes)")
    background_tasks.add_task(_fetch_and_process, job_id, body.storage_path, user["id"])

    return UploadResponse(
        job_id=job_id,
        message="Review started.",
        filename=body.filename,
        file_size=body.file_size,
    )


async def _fetch_and_process(job_id: str, storage_path: str, user_id: str):
    """Background: download from Storage, validate, compress, then run pipeline."""
    file_path = os.path.join(settings.upload_folder, f"{job_id}.pdf")

    # 1. Download from Supabase Storage
    try:
        content = db.download_plan(storage_path)
    except Exception as e:
        logger.error(f"Job {job_id}: storage download failed: {e}")
        db.update_job(job_id, {"status": "failed", "error": "Uploaded file not found in storage."})
        db.add_credits(user_id, 1)  # refund
        return

    # 2. Validate magic bytes
    if len(content) < 5 or content[:4] != b"%PDF":
        logger.error(f"Job {job_id}: not a valid PDF")
        db.update_job(job_id, {"status": "failed", "error": "File is not a valid PDF."})
        db.add_credits(user_id, 1)  # refund
        return

    # 3. Write to local disk
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # 4. Lossless compression (best-effort)
    try:
        _, before_b, after_b = compress_pdf(file_path)
        if after_b < before_b:
            saved = (1 - after_b / before_b) * 100
            logger.info(f"Job {job_id}: compressed {before_b:,} -> {after_b:,} bytes (-{saved:.1f}%)")
    except Exception as e:
        logger.warning(f"Job {job_id}: compression skipped ({e})")

    # 5. Run the 12-agent pipeline (and final cleanup) in the existing handler
    await _process_job(job_id, file_path, storage_path)


async def _process_job(job_id: str, file_path: str, storage_path: Optional[str] = None):
    """Background task: run the workflow and persist results to DB."""
    db.update_job(job_id, {"status": "processing", "progress": 0})

    workflow = PlanCheckerWorkflow()

    # Build a lightweight in-memory job shell for workflow state
    row = db.get_job(job_id)
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
        # Only push frequent status updates if progress changed
        if job_shell.progress != last_persisted_progress or job_shell.current_agent:
            db.update_job(job_id, {
                "progress": job_shell.progress,
                "current_agent": job_shell.current_agent,
                "agents_completed": job_shell.agents_completed,
            })
            last_persisted_progress = job_shell.progress

    try:
        report = await workflow.run(job_shell, file_path, log_callback=on_log)

        # Persist final report fields
        db.update_job(job_id, {
            "status": "completed",
            "progress": 100,
            "current_agent": None,
            "completed_at": datetime.utcnow().isoformat(),
            "jurisdiction": (report.jurisdiction.model_dump() if report.jurisdiction else None),
            "plan_data": (report.plan_data.model_dump() if report.plan_data else None),
            "summary": report.summary.model_dump() if report.summary else None,
            "department_reviews": [dr.model_dump() for dr in (report.department_reviews or [])],
            "recommendations": report.recommendations,
            "code_versions": report.code_versions,
            "sources_used": report.sources_used,
            "notes": report.auditor_notes,
        })

        # Persist findings rows for fast filtering
        row = db.get_job(job_id)
        finding_rows = []
        for f in (report.findings or []):
            req = f.code_requirement
            # find department for this finding
            dept_name = ""
            dept_code = ""
            for dr in report.department_reviews or []:
                if any(ff.finding_id == f.finding_id for ff in dr.findings):
                    dept_name = dr.department
                    dept_code = dr.department_code
                    break
            finding_rows.append({
                "job_id": job_id,
                "user_id": row["user_id"],
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
            # insert in chunks to stay under PG row limits
            for i in range(0, len(finding_rows), 100):
                db.insert_findings(finding_rows[i:i+100])

        logger.info(f"Job {job_id} completed: {len(finding_rows)} findings")

        # Send "your review is ready" email (no-op without RESEND_API_KEY)
        try:
            row2 = db.get_job(job_id)
            user_id2 = row2.get("user_id")
            profile = db.get_profile(user_id2) or {}
            client = db.admin()
            auth_user = client.auth.admin.get_user_by_id(user_id2) if user_id2 else None
            user_email = getattr(getattr(auth_user, "user", None), "email", None) if auth_user else None
            if user_email:
                email_service.send_report_ready(user_email, job_id, row2.get("filename", "your plan"))
        except Exception as e:
            logger.warning(f"send_report_ready failed for job {job_id}: {e}")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        db.update_job(job_id, {"status": "failed", "error": str(e)})
        # Refund the credit on failure
        try:
            db.add_credits(row["user_id"], 1)
        except Exception:
            pass
    finally:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        # Delete the original from Supabase Storage too — we've already processed it.
        if storage_path:
            db.delete_plan(storage_path)


# ============================================================
# Job retrieval
# ============================================================

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    row = db.get_job_for_user(job_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = _job_row_to_response(row)
    payload["logs"] = [
        {
            "timestamp": l["ts"],
            "agent": l["agent"],
            "level": l["level"],
            "message": l["message"],
            "data": l.get("data") or {},
        }
        for l in db.list_logs_for_job(job_id, limit=200)
    ]
    return payload


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(
    job_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    row = db.get_job_for_user(job_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "logs": db.list_logs_for_job(job_id)}


@router.get("/jobs")
async def list_jobs(user: Dict[str, Any] = Depends(get_current_user)):
    return {"jobs": db.list_jobs_for_user(user["id"])}


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    row = db.get_job_for_user(job_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    # RLS allows users to delete their own — but we use service role here, so check ownership manually (already done)
    db.admin().table("jobs").delete().eq("id", job_id).execute()
    return {"message": f"Job {job_id} deleted"}


# ============================================================
# Profile
# ============================================================

@router.get("/me")
async def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    profile = db.get_profile(user["id"]) or {}
    return {
        "id": user["id"],
        "email": user.get("email"),
        "credits_remaining": profile.get("credits_remaining", 0),
        "display_name": profile.get("display_name"),
        "firm_name": profile.get("firm_name"),
        "plan_tier": profile.get("plan_tier", "free"),
        "plan_credits_per_month": profile.get("plan_credits_per_month", 1),
        "subscription_status": profile.get("subscription_status"),
        "subscription_current_period_end": profile.get("subscription_current_period_end"),
    }


# ============================================================
# Exports
# ============================================================

@router.get("/jobs/{job_id}/export/pdf")
async def export_report_pdf(
    job_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    row = db.get_job_for_user(job_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")
    # Rebuild a ComplianceReport-like object for the export
    report = ComplianceReport(
        report_id=row["id"],
        job_id=row["id"],
        generated_at=datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else datetime.utcnow(),
        jurisdiction=row.get("jurisdiction"),
        plan_data=row.get("plan_data"),
        summary=row.get("summary") or {},
        recommendations=row.get("recommendations") or [],
        code_versions=row.get("code_versions") or {},
        sources_used=row.get("sources_used") or [],
        auditor_notes=row.get("notes"),
    )
    pdf_bytes = export_service.export_pdf(report)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="compliance-report-{job_id[:8]}.pdf"'},
    )


# ============================================================
# Data rights (GDPR + CCPA)
# ============================================================

@router.get("/me/export")
async def export_my_data(user: Dict[str, Any] = Depends(get_current_user)):
    """Return all data we hold about this user. GDPR right of access / CCPA right to know."""
    client = db.admin()
    profile = db.get_profile(user["id"]) or {}
    jobs = client.table("jobs").select("*").eq("user_id", user["id"]).execute().data or []
    findings = client.table("findings").select("*").eq("user_id", user["id"]).execute().data or []
    job_ids = [j["id"] for j in jobs]
    logs = []
    if job_ids:
        logs = client.table("agent_logs").select("*").in_("job_id", job_ids).execute().data or []
    payload = {
        "exported_at": datetime.utcnow().isoformat(),
        "user": {
            "id": user["id"],
            "email": user.get("email"),
        },
        "profile": profile,
        "jobs": jobs,
        "findings": findings,
        "agent_logs": logs,
    }
    body = json.dumps(payload, default=str, indent=2)
    return StreamingResponse(
        iter([body.encode("utf-8")]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="up2code-data-export-{user["id"][:8]}.json"'},
    )


@router.delete("/me")
async def delete_my_account(user: Dict[str, Any] = Depends(get_current_user)):
    """Permanently delete this user's account and all associated data.
    GDPR right to erasure / CCPA right to delete.
    """
    client = db.admin()
    user_id = user["id"]

    # Delete cascades: jobs -> findings, agent_logs (FK ON DELETE CASCADE)
    client.table("jobs").delete().eq("user_id", user_id).execute()
    client.table("profiles").delete().eq("id", user_id).execute()

    # Finally delete the auth user (this signs them out everywhere)
    try:
        client.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.error(f"auth.admin.delete_user failed for {user_id}: {e}")
        # Profile data is already gone; surface a soft error
        raise HTTPException(status_code=500, detail="Account data deleted but auth removal failed. Contact support.")

    return {"message": "Account permanently deleted."}


# ============================================================
# Finding feedback (for accuracy improvement + liability defense)
# ============================================================

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional

class FeedbackBody(_BaseModel):
    feedback: str   # "wrong" | "right" | "unclear"
    note: _Optional[str] = None

@router.post("/findings/{finding_id}/feedback")
@limiter.limit("60/minute")
async def submit_finding_feedback(
    finding_id: str,
    body: FeedbackBody,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if body.feedback not in ("wrong", "right", "unclear"):
        raise HTTPException(status_code=400, detail="feedback must be wrong|right|unclear")

    # Service role bypasses RLS but we still scope by user_id for safety
    res = db.admin().table("findings").update({
        "user_feedback": body.feedback,
        "feedback_note": body.note,
        "feedback_at": datetime.utcnow().isoformat(),
    }).eq("id", finding_id).eq("user_id", user["id"]).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Finding not found")
    return {"ok": True, "finding_id": finding_id, "feedback": body.feedback}
