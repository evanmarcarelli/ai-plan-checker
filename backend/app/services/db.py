"""Supabase database client and helpers."""
from functools import lru_cache
from typing import Any, Dict, List, Optional
from datetime import datetime
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
) -> str:
    res = admin().table("jobs").insert({
        "user_id": user_id,
        "filename": filename,
        "file_size": file_size,
        "storage_path": storage_path,
        "status": "pending",
        "progress": 0,
    }).execute()
    return res.data[0]["id"]


def update_job(job_id: str, fields: Dict[str, Any]) -> None:
    if "updated_at" not in fields:
        fields["updated_at"] = datetime.utcnow().isoformat()
    admin().table("jobs").update(fields).eq("id", job_id).execute()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    res = admin().table("jobs").select("*").eq("id", job_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_job_for_user(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    res = admin().table("jobs").select("*").eq("id", job_id).eq("user_id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def list_jobs_for_user(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    res = (
        admin().table("jobs")
        .select("id, filename, status, progress, created_at, completed_at, summary")
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


def decrement_credits(user_id: str, amount: int = 1) -> int:
    """Atomically decrement credits. Returns the new balance, or -1 if insufficient."""
    profile = get_profile(user_id)
    if not profile:
        return -1
    current = profile.get("credits_remaining", 0) or 0
    if current < amount:
        return -1
    new_balance = current - amount
    admin().table("profiles").update({"credits_remaining": new_balance}).eq("id", user_id).execute()
    return new_balance


def add_credits(user_id: str, amount: int) -> int:
    profile = get_profile(user_id)
    if not profile:
        return -1
    new_balance = (profile.get("credits_remaining", 0) or 0) + amount
    admin().table("profiles").update({"credits_remaining": new_balance}).eq("id", user_id).execute()
    return new_balance


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
    finding_id: str,
    job_id: str,
    author_display: str,
    body: str,
    author_user_id: Optional[str] = None,
    author_share_id: Optional[str] = None,
    author_email: Optional[str] = None,
) -> Dict[str, Any]:
    res = admin().table("finding_comments").insert({
        "finding_id": finding_id,
        "job_id": job_id,
        "author_user_id": author_user_id,
        "author_share_id": author_share_id,
        "author_display": author_display,
        "author_email": author_email,
        "body": body,
    }).execute()
    return res.data[0]


def list_comments_for_finding(finding_id: str) -> List[Dict[str, Any]]:
    res = (admin().table("finding_comments")
           .select("id, author_display, body, created_at, author_user_id, author_share_id")
           .eq("finding_id", finding_id)
           .order("created_at")
           .execute())
    return res.data or []


def list_comments_for_job(job_id: str) -> List[Dict[str, Any]]:
    res = (admin().table("finding_comments")
           .select("id, finding_id, author_display, body, created_at")
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
