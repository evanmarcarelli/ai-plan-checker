"""Supabase database client and helpers."""
from functools import lru_cache
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from supabase import create_client, Client
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache()
def _service_client() -> Client:
    """Service-role client — used by the backend, bypasses RLS."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase credentials not configured")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def admin() -> Client:
    return _service_client()


# ---------- Storage ----------

def download_plan(storage_path: str) -> bytes:
    """Download a PDF from the plan-uploads bucket. Service role bypasses RLS."""
    return admin().storage.from_("plan-uploads").download(storage_path)


def delete_plan(storage_path: str) -> None:
    """Best-effort delete of a stored plan after processing completes."""
    try:
        admin().storage.from_("plan-uploads").remove([storage_path])
    except Exception:
        pass


# ---------- Jobs ----------

def create_job(
    user_id: str,
    filename: str,
    file_size: int,
    storage_path: Optional[str] = None,
    credit_charged: bool = False,
) -> str:
    """Enqueue a job (status 'pending'). A worker claims and runs it; the web
    tier never processes it inline. credit_charged is persisted so a later
    failure can refund idempotently without the web request being involved.

    Backward-compatible: if the credit_charged column isn't present yet
    (migration 007 not applied), retry the insert without it so uploads keep
    working."""
    base = {
        "user_id": user_id,
        "filename": filename,
        "file_size": file_size,
        "storage_path": storage_path,
        "status": "pending",
        "progress": 0,
    }
    try:
        res = admin().table("jobs").insert({**base, "credit_charged": credit_charged}).execute()
    except Exception:
        # Pre-migration: column may not exist. Fall back to the base insert.
        res = admin().table("jobs").insert(base).execute()
    return res.data[0]["id"]


def update_job(job_id: str, fields: Dict[str, Any]) -> None:
    if "updated_at" not in fields:
        fields["updated_at"] = datetime.utcnow().isoformat()
    admin().table("jobs").update(fields).eq("id", job_id).execute()


# Legacy staleness window, used ONLY by the pre-migration-007 fallback in
# fail_if_orphaned (and the unused mark_stale_jobs_failed admin helper). Once
# migration 007 is applied, job liveness is governed by the lease
# (lease_expires_at) + attempts, not by updated_at staleness.
STALE_JOB_SEC = 90

_ORPHAN_ERROR = (
    "Processing was interrupted (the server restarted or ran out of memory). "
    "Please run the check again."
)


def mark_stale_jobs_failed(older_than_sec: int = STALE_JOB_SEC) -> int:
    """Bulk-fail orphaned jobs. Called on startup so a restart that killed
    in-flight jobs surfaces them as failed instead of an eternal spinner."""
    cutoff = (datetime.utcnow() - timedelta(seconds=older_than_sec)).isoformat()
    res = (
        admin().table("jobs")
        .update({"status": "failed", "error": _ORPHAN_ERROR,
                 "updated_at": datetime.utcnow().isoformat()})
        .in_("status", ["pending", "processing"])
        .lt("updated_at", cutoff)
        .execute()
    )
    return len(res.data or [])


def _is_past(ts: Any) -> bool:
    """True if an ISO timestamp is strictly in the past (naive UTC compare)."""
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return False
    return datetime.utcnow() > t


def fail_if_orphaned(row: Dict[str, Any]) -> Dict[str, Any]:
    """Read-time guard for the dashboard: surface a genuinely-dead job as
    failed so the UI stops polling it.

    With the lease-based queue (migration 007), the worker's reaper is the
    authoritative cleanup. This guard is the fast path for the read endpoint:
    a job is only declared dead when it has *exhausted its retries* AND its
    lease has expired. A queued ('pending') job, or a 'processing' job with a
    live lease or attempts remaining, is left alone — it will run / be retried.

    Falls back to the pre-migration updated_at staleness heuristic when the
    lease columns aren't present yet."""
    if not row or row.get("status") not in ("pending", "processing"):
        return row

    # New lease-aware path.
    if "lease_expires_at" in row or "attempts" in row:
        attempts = row.get("attempts") or 0
        max_attempts = row.get("max_attempts") or 3
        lease = row.get("lease_expires_at")
        if attempts >= max_attempts and _is_past(lease):
            update_job(row["id"], {"status": "failed", "error": _ORPHAN_ERROR})
            try:
                refund_job_credit(row["id"])
            except Exception:
                pass
            return {**row, "status": "failed", "error": _ORPHAN_ERROR}
        return row

    # Fallback: pre-migration heartbeat-staleness heuristic.
    ts = row.get("updated_at") or row.get("created_at")
    if not ts:
        return row
    try:
        last = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return row
    if datetime.utcnow() - last < timedelta(seconds=STALE_JOB_SEC):
        return row
    update_job(row["id"], {"status": "failed", "error": _ORPHAN_ERROR})
    return {**row, "status": "failed", "error": _ORPHAN_ERROR}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    res = admin().table("jobs").select("*").eq("id", job_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_job_for_user(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    res = admin().table("jobs").select("*").eq("id", job_id).eq("user_id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def list_jobs_for_user(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    res = (
        admin().table("jobs")
        .select("id, filename, status, progress, created_at, completed_at, summary, plan_data")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ---------- Findings ----------

def insert_findings(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    admin().table("findings").insert(rows).execute()


def list_findings_for_job(job_id: str) -> List[Dict[str, Any]]:
    res = (
        admin().table("findings")
        .select("*")
        .eq("job_id", job_id)
        .order("severity")
        .execute()
    )
    return res.data or []


# ---------- Agent logs ----------

def insert_log(job_id: str, agent: str, level: str, message: str, data: Optional[Dict] = None) -> None:
    try:
        admin().table("agent_logs").insert({
            "job_id": job_id,
            "agent": agent,
            "level": level,
            "message": message,
            "data": data,
        }).execute()
    except Exception as e:
        logger.warning(f"insert_log failed: {e}")


def list_logs_for_job(job_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    res = (
        admin().table("agent_logs")
        .select("*")
        .eq("job_id", job_id)
        .order("ts")
        .limit(limit)
        .execute()
    )
    return res.data or []


# ---------- Profile / credits ----------

def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    res = admin().table("profiles").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def _rpc_scalar(fn: str, params: Dict[str, Any]):
    """Call a Postgres function that returns a single integer and unwrap it.
    Returns the int, or None when the function returned no row / isn't
    deployed yet. Never raises — callers fall back to the read-modify-write
    path on None so deploying code ahead of migration 006 stays safe."""
    try:
        res = admin().rpc(fn, params).execute()
    except Exception:
        return None
    data = res.data
    if data is None:
        return None
    # PostgREST returns either the scalar directly or a single-element list.
    if isinstance(data, list):
        return data[0] if data else None
    return data


def decrement_credits(user_id: str, amount: int = 1) -> int:
    """Atomically decrement credits. Returns the new balance, or -1 if
    insufficient. Uses the DB-side decrement_credits_atomic() (migration
    006) so two concurrent uploads can't both pass a stale balance check.
    Falls back to a read-modify-write only if the RPC isn't deployed."""
    new_balance = _rpc_scalar("decrement_credits_atomic", {"p_user_id": user_id, "p_amount": amount})
    if new_balance is not None:
        return int(new_balance)
    # Fallback: RPC missing (migration 006 not yet run). Non-atomic, but
    # preserves the pre-migration behavior rather than failing the upload.
    profile = get_profile(user_id)
    if not profile:
        return -1
    current = profile.get("credits_remaining", 0) or 0
    if current < amount:
        return -1
    updated = current - amount
    admin().table("profiles").update({"credits_remaining": updated}).eq("id", user_id).execute()
    return updated


def add_credits(user_id: str, amount: int) -> int:
    """Atomically add credits (refunds + pack grants). Returns the new
    balance, or -1 if the profile is missing. Uses add_credits_atomic()
    (migration 006); falls back to read-modify-write if not deployed."""
    new_balance = _rpc_scalar("add_credits_atomic", {"p_user_id": user_id, "p_amount": amount})
    if new_balance is not None:
        return int(new_balance)
    profile = get_profile(user_id)
    if not profile:
        return -1
    updated = (profile.get("credits_remaining", 0) or 0) + amount
    admin().table("profiles").update({"credits_remaining": updated}).eq("id", user_id).execute()
    return updated


# ============================================================
# Job queue (migration 007): lease-based claim + idempotent refund
#
# These wrap the Postgres functions from migration 007. Each degrades
# safely if the migration hasn't been applied yet, so deploying code ahead
# of the migration never 500s — the worker simply idles until the functions
# exist. See migrations/007_job_queue.sql for the SQL contracts.
# ============================================================

def claim_next_job(worker_id: str, lease_sec: int = 180) -> Optional[Dict[str, Any]]:
    """Atomically claim the next runnable job for this worker (FOR UPDATE SKIP
    LOCKED). Returns the claimed row, or None when the queue is empty / the
    RPC isn't deployed yet."""
    try:
        res = admin().rpc(
            "claim_next_job",
            {"p_worker_id": worker_id, "p_lease_sec": lease_sec},
        ).execute()
    except Exception as e:
        logger.warning(f"claim_next_job RPC unavailable (apply migration 007?): {e}")
        return None
    data = res.data
    if not data:
        return None
    return data[0] if isinstance(data, list) else data


def heartbeat_job(job_id: str, worker_id: str, lease_sec: int = 180) -> bool:
    """Extend this worker's lease on a job. Returns True if the lease was
    extended (we still own it), False if it was reclaimed or the RPC is
    missing. The fallback just touches updated_at so a pre-migration deploy
    still shows the job as alive."""
    try:
        res = admin().rpc(
            "heartbeat_job",
            {"p_job_id": job_id, "p_worker_id": worker_id, "p_lease_sec": lease_sec},
        ).execute()
        return bool(res.data)
    except Exception:
        try:
            update_job(job_id, {})
        except Exception:
            pass
        return False


def refund_job_credit(job_id: str) -> bool:
    """Idempotently refund the one credit a failed job consumed. Returns True
    only if a refund actually happened on this call. Safe to call on any job:
    a no-op when the job wasn't charged or was already refunded."""
    val = _rpc_scalar("refund_job_credit", {"p_job_id": job_id})
    if val is not None:
        return bool(val)
    # Fallback (pre-migration 007): emulate the idempotent refund in Python.
    # Best-effort and not perfectly atomic, but guarded by the same flags.
    row = get_job(job_id)
    if not row or not row.get("credit_charged", False) or row.get("credit_refunded", False):
        return False
    add_credits(row["user_id"], 1)
    try:
        update_job(job_id, {"credit_refunded": True})
    except Exception:
        pass
    return True


def fail_exhausted_jobs() -> int:
    """Reaper: fail + refund jobs that exhausted their retries and whose lease
    expired. Returns the count failed this sweep (0 if the RPC is missing)."""
    val = _rpc_scalar("fail_exhausted_jobs", {})
    return int(val) if val is not None else 0


# ============================================================
# Collaboration: report_shares, finding_comments, chat_messages
# ============================================================

def create_share(
    *,
    job_id: str,
    created_by: str,
    token: str,
    role: str = "commenter",
    invited_email: Optional[str] = None,
    invited_name: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    res = admin().table("report_shares").insert({
        "job_id": job_id,
        "created_by": created_by,
        "token": token,
        "role": role,
        "invited_email": invited_email,
        "invited_name": invited_name,
        "expires_at": expires_at,
    }).execute()
    return res.data[0]


def list_shares_for_job(job_id: str) -> List[Dict[str, Any]]:
    res = (admin().table("report_shares")
           .select("id, invited_email, invited_name, role, token, expires_at, revoked_at, last_used_at, created_at")
           .eq("job_id", job_id)
           .order("created_at", desc=True)
           .execute())
    return res.data or []


def get_share_by_token(token: str) -> Optional[Dict[str, Any]]:
    res = admin().table("report_shares").select("*").eq("token", token).limit(1).execute()
    if not res.data:
        return None
    share = res.data[0]
    if share.get("revoked_at"):
        return None
    if share.get("expires_at"):
        try:
            exp = datetime.fromisoformat(share["expires_at"].replace("Z", "+00:00"))
            if exp < datetime.utcnow().replace(tzinfo=exp.tzinfo):
                return None
        except Exception:
            pass
    return share


def touch_share(share_id: str) -> None:
    try:
        admin().table("report_shares").update({"last_used_at": datetime.utcnow().isoformat()}).eq("id", share_id).execute()
    except Exception:
        pass


def revoke_share(share_id: str) -> None:
    admin().table("report_shares").update({"revoked_at": datetime.utcnow().isoformat()}).eq("id", share_id).execute()


# ----- comments -----

def add_finding_comment(
    *,
    job_id: str,
    finding_ref: str,
    author_display: str,
    body: str,
    author_user_id: Optional[str] = None,
    author_share_id: Optional[str] = None,
    author_email: Optional[str] = None,
) -> Dict[str, Any]:
    res = admin().table("finding_comments").insert({
        "job_id": job_id,
        "finding_ref": finding_ref,
        "author_user_id": author_user_id,
        "author_share_id": author_share_id,
        "author_display": author_display,
        "author_email": author_email,
        "body": body,
    }).execute()
    return res.data[0]


def list_comments_for_finding(job_id: str, finding_ref: str) -> List[Dict[str, Any]]:
    res = (admin().table("finding_comments")
           .select("id, finding_ref, author_display, body, created_at, author_user_id, author_share_id")
           .eq("job_id", job_id)
           .eq("finding_ref", finding_ref)
           .order("created_at")
           .execute())
    return res.data or []


def list_comments_for_job(job_id: str) -> List[Dict[str, Any]]:
    res = (admin().table("finding_comments")
           .select("id, finding_ref, author_display, body, created_at")
           .eq("job_id", job_id)
           .order("created_at")
           .execute())
    return res.data or []


# ----- chat -----

def add_chat_message(
    *,
    job_id: str,
    role: str,
    content: str,
    citations: Optional[List[Dict[str, Any]]] = None,
    author_user_id: Optional[str] = None,
    author_share_id: Optional[str] = None,
    author_display: Optional[str] = None,
) -> Dict[str, Any]:
    res = admin().table("chat_messages").insert({
        "job_id": job_id,
        "role": role,
        "content": content,
        "citations": citations or [],
        "author_user_id": author_user_id,
        "author_share_id": author_share_id,
        "author_display": author_display,
    }).execute()
    return res.data[0]


def list_chat_messages(job_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    res = (admin().table("chat_messages")
           .select("id, role, content, citations, author_display, created_at")
           .eq("job_id", job_id)
           .order("created_at")
           .limit(limit)
           .execute())
    return res.data or []
