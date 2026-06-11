"""API routes — DB-backed job storage with Supabase auth.

This module is the WEB tier. It validates, authenticates, reserves credits,
and enqueues jobs — it never runs the plan-check pipeline. The pipeline lives
in app.worker / app.services.job_processor, in a separate process.
"""
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
import jwt as _jwt

from app.config import settings
from app.models.schemas import (
    UploadResponse, JobStatusResponse, ComplianceReport,
)
from app.services.export_service import export_service
from app.services import db
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
        # Fetch the per-job findings from the findings table and translate them
        # back into the ComplianceFinding shape the dashboard expects. The
        # findings ARE persisted (db.insert_findings runs at workflow end), but
        # this function used to hardcode []; that's why the dashboard's findings
        # table showed "0/0" even on completed jobs.
        finding_rows = db.list_findings_for_job(row["id"])
        findings = [
            {
                "finding_id": fr.get("id", "")[:8] if fr.get("id") else "",
                "code_requirement": {
                    "code_id":  fr.get("code_id") or "",
                    "code_name": fr.get("code_name") or "",
                    "section":  fr.get("code_section") or "",
                    "description": fr.get("description") or "",
                    "category": fr.get("category") or "general",
                    "requirement_type": "general",
                    "jurisdiction_specific": False,
                    "full_text": None,
                },
                "status": fr.get("status") or "needs_review",
                "plan_value": fr.get("plan_value"),
                "required_value": fr.get("required_value"),
                "description": fr.get("description") or "",
                "recommendation": fr.get("recommendation"),
                "severity": fr.get("severity") or "medium",
                "page_references": fr.get("page_references") or [],
                "category": fr.get("category") or "general",
            }
            for fr in finding_rows
        ]

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
            "findings": findings,
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
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Enqueue a compliance review for a PDF already uploaded to Supabase Storage.

    The browser uploads the PDF directly to Supabase (bypassing this backend),
    then calls this endpoint with the storage path. This handler does ONLY
    fast validation + credit reservation, then writes a 'pending' job row and
    returns. A dedicated worker process (app.worker) claims the job and runs
    the heavy pipeline (download, PDF parse, vision, 12 agents) out-of-band.

    Keeping all heavy/long/stateful work out of this web request is the whole
    point: it's why the event loop never stalls, the web tier never OOMs, and
    a redeploy can't orphan an in-flight job.
    """
    # Fast-path validations only — return to the browser in <1 second.

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
    # Whether this upload actually consumed a credit. Admins and the
    # no-auth dev mode are not charged, so the failure/timeout paths must
    # NOT refund them — otherwise each failed admin run mints a credit.
    charged = settings.require_auth and not _is_admin_user(user)

    # Enqueue: write a 'pending' job row (instant). The worker takes it from
    # here. credit_charged is persisted so the worker can refund idempotently
    # on failure without this request being in the loop.
    job_id = db.create_job(
        user_id=user["id"],
        filename=body.filename,
        file_size=body.file_size,
        storage_path=body.storage_path,
        credit_charged=charged,
    )

    logger.info(f"Job {job_id} enqueued for user {user['id']}: {body.filename} ({body.file_size:,} bytes)")

    return UploadResponse(
        job_id=job_id,
        message="Review started.",
        filename=body.filename,
        file_size=body.file_size,
    )


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
    # If the job's worker died (OOM/restart), it's frozen at "processing" with a
    # stale heartbeat — surface it as failed instead of polling it forever.
    row = db.fail_if_orphaned(row)
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


# ============================================================
# Plan library (migration 010) — the cross-job plan-set corpus
# ============================================================

@router.get("/plan-library")
async def list_plan_documents(user: Dict[str, Any] = Depends(get_current_user)):
    """The user's plan library: every distinct plan set, with revision links."""
    from app.services import plan_library
    return {"documents": plan_library.list_documents(user["id"])}


@router.get("/plan-library/search")
async def search_plan_library(
    q: str,
    disciplines: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: int = 20,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Ranked full-text search over the user's plan-sheet corpus.

    `disciplines` is a comma-separated filter, e.g. "structural,architectural".
    Returns sheet-level hits with page/sheet numbers and highlighted snippets,
    so both humans and agents can trace an answer back to a source sheet.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="q is required")
    from app.services import plan_library
    disc_list = [d.strip() for d in disciplines.split(",") if d.strip()] if disciplines else None
    rows = plan_library.search_sheets(
        user["id"], q, disciplines=disc_list, document_id=document_id, limit=limit
    )
    return {"query": q, "results": rows}


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

@router.get("/_diag/llm")
# Auth-free for browser debugging, but this makes a real (billable)
# Anthropic call — throttle hard so a discovered URL can't be looped to
# run up the API bill.
@limiter.limit("5/hour")
async def diag_llm(request: Request):
    """Diagnostic: tells you whether the Anthropic key on Render is set,
    whether it authenticates, and surfaces the actual error if it doesn't.

    Visit directly in a browser. Auth-free on purpose so the founder does not
    have to fight cookies/headers just to debug an outage. The response leaks
    only public info: whether the key is set, its sk-ant- prefix, the model
    names, and the result of a smallest-possible Anthropic call. The actual
    key value is never returned."""
    key = (settings.anthropic_api_key or "").strip()
    info: Dict[str, Any] = {
        "key_set": bool(key),
        "key_prefix": key[:7] if key else None,         # always "sk-ant-" for valid keys
        "key_length": len(key) if key else 0,
        "model_primary": settings.anthropic_model,
        "model_cheap": settings.anthropic_model_cheap,
    }
    if not key:
        info["status"] = "NO_KEY"
        info["hint"] = "ANTHROPIC_API_KEY env var is empty on Render. Set it and redeploy."
        return info
    # Try the smallest possible call. 1 token output, no caching, sync over async wrapper.
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model=settings.anthropic_model_cheap,
            max_tokens=1,
            messages=[{"role": "user", "content": "."}],
        )
        info["status"] = "OK"
        info["hint"] = "Anthropic auth + smallest-call test succeeded. LLM path is healthy."
    except Exception as e:
        info["status"] = "ERROR"
        info["error_type"] = type(e).__name__
        info["error"] = str(e)[:500]
        info["hint"] = (
            "The Anthropic SDK call itself failed. Common causes: invalid key, "
            "billing/credits exhausted on the Anthropic account, rate limit, or "
            "outbound network blocked from Render."
        )
    return info


@router.get("/_diag/textract")
# Auth-free for browser debugging, but this makes a real (billable) AWS
# Textract call — throttle so the URL can't be looped to run up the bill.
@limiter.limit("5/hour")
async def diag_textract(request: Request):
    """Diagnostic: confirm AWS Textract is configured and the IAM user has
    the right permission. Public on purpose (mirrors `/diag/llm`) so the
    founder can debug from a browser without auth fight. Returns only
    non-sensitive info: whether the flag is on, whether creds look set,
    the region, and the result of one minimal Textract API call against a
    1×1 white PNG (which exercises auth + permission without OCR'ing
    anything substantive)."""
    info: Dict[str, Any] = {
        "enabled_flag": settings.aws_textract_enabled,
        "key_set": bool(settings.aws_access_key_id),
        "secret_set": bool(settings.aws_secret_access_key),
        "region": settings.aws_region,
        "min_chars_per_page": settings.textract_min_chars_per_page,
        "max_pages": settings.textract_max_pages,
    }
    if not settings.aws_textract_enabled:
        info["status"] = "DISABLED"
        info["hint"] = (
            "AWS_TEXTRACT_ENABLED is false. Set to 'true' in Render env vars "
            "and redeploy to turn on the OCR fallback."
        )
        return info
    if not (settings.aws_access_key_id and settings.aws_secret_access_key):
        info["status"] = "NO_KEY"
        info["hint"] = (
            "AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY is empty on Render. "
            "Paste the IAM user's keys and redeploy."
        )
        return info
    try:
        from app.services.textract_extractor import textract_extractor
        client = textract_extractor._get_client()
        if client is None:
            info["status"] = "CLIENT_INIT_FAILED"
            info["error"] = textract_extractor._init_error or "unknown"
            info["hint"] = "Check the backend logs for the detailed boto3 init error."
            return info
        # Smallest possible call: a 1×1 white PNG. Exercises auth + the
        # textract:AnalyzeDocument permission without doing real OCR.
        # PNG header is well-known; we hand-build the smallest valid PNG
        # rather than pulling in PIL.
        import base64
        tiny_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        client.analyze_document(Document={"Bytes": tiny_png}, FeatureTypes=["FORMS"])
        info["status"] = "OK"
        info["hint"] = "Textract auth + AnalyzeDocument permission verified. OCR fallback is live."
    except Exception as e:
        info["status"] = "ERROR"
        info["error_type"] = type(e).__name__
        info["error"] = str(e)[:500]
        if "InvalidSignatureException" in info["error"] or "UnrecognizedClientException" in info["error"]:
            info["hint"] = "AWS key/secret rejected. Re-paste the values cleanly — common cause is a stray space or wrong AWS account."
        elif "AccessDenied" in info["error"]:
            info["hint"] = "IAM user lacks textract:AnalyzeDocument. Attach the AmazonTextractFullAccess policy (or a scoped equivalent) and re-test."
        elif "could not be found" in info["error"].lower() or "endpoint" in info["error"].lower():
            info["hint"] = f"AWS_REGION={settings.aws_region} may not have Textract. us-west-2 and us-east-1 always do."
        else:
            info["hint"] = "The Textract SDK call itself failed. Check the error above."
    return info


@router.get("/me")
async def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    profile = db.get_profile(user["id"]) or {}
    # is_admin is computed from the same allowlist that drives the upload
    # bypass, so the dashboard can render "Unlimited" instead of confusing
    # the founder by showing "0 credits" while uploads silently work.
    is_admin = _is_admin_user(user)
    return {
        "id": user["id"],
        "email": user.get("email"),
        "credits_remaining": profile.get("credits_remaining", 0),
        "is_admin": is_admin,
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
        headers={"Content-Disposition": f'attachment; filename="architechtura-data-export-{user["id"][:8]}.json"'},
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
