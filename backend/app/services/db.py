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
