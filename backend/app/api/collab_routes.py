"""Collaboration endpoints: share invites, finding comments, AI assistant chat.

The goal is viral growth: any logged-in user can mint share tokens that let
external collaborators (contractors, building inspectors) view a report and
comment on individual findings WITHOUT signing up. Every guest sees the
Architechtura branding, which is the organic distribution play.

Auth model:
    - Owners: standard Supabase JWT via get_current_user
    - Guests: pass `X-Share-Token: <token>` instead of Authorization
    - Either is accepted on guest endpoints via the get_actor() dep

All writes go through the backend service role so RLS doesn't need
guest-aware policies — the token check IS the policy.

NOTE: deliberately NO `from __future__ import annotations` here. With it,
FastAPI 0.109 + Pydantic 2.5.x cannot resolve request-body models
(CreateShareBody etc.) — they become lazy forward-refs and route
registration raises PydanticUndefinedAnnotation, crashing the app on boot.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address

from app.api.routes import limiter      # reuse the same Limiter instance
from app.services import db
from app.services.auth import get_current_user
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ============================================================
# Actor resolution: owner (JWT) or guest (share token)
# ============================================================

class Actor(BaseModel):
    """Resolved caller. EITHER user_id (owner) OR share_id (guest) is set."""
    user_id: Optional[str] = None
    email: Optional[str] = None
    share_id: Optional[str] = None
    job_id: Optional[str] = None
    role: str = "owner"        # "owner" | "viewer" | "commenter"
    display: str = "Anonymous"

    @property
    def is_owner(self) -> bool:
        return self.user_id is not None and self.share_id is None

    @property
    def can_comment(self) -> bool:
        return self.is_owner or self.role == "commenter"


async def get_actor(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_share_token: Optional[str] = Header(None, alias="X-Share-Token"),
    x_guest_name: Optional[str] = Header(None, alias="X-Guest-Name"),
) -> Actor:
    """Resolve the caller to either an owner (JWT) or a guest (share token).

    Header precedence: a valid Authorization wins; otherwise X-Share-Token.
    """
    # Try owner JWT first
    if authorization and authorization.lower().startswith("bearer "):
        try:
            user = await get_current_user(authorization=authorization)
            return Actor(
                user_id=user["id"],
                email=user.get("email"),
                role="owner",
                display=user.get("email") or "Owner",
            )
        except HTTPException:
            pass  # fall through to token attempt

    # Try guest share token
    if x_share_token:
        share = db.get_share_by_token(x_share_token)
        if share:
            db.touch_share(share["id"])
            return Actor(
                share_id=share["id"],
                job_id=share["job_id"],
                role=share.get("role", "commenter"),
                email=share.get("invited_email"),
                display=(x_guest_name or share.get("invited_name") or share.get("invited_email") or "Guest"),
            )

    raise HTTPException(status_code=401, detail="Sign in or provide a valid share token")


def _new_token() -> str:
    # URL-safe, 32 bytes ~ 43 chars. Enough entropy that brute force is infeasible.
    return secrets.token_urlsafe(32)


# ============================================================
# SHARES — owner-only mint + list + revoke
# ============================================================

class CreateShareBody(BaseModel):
    invited_email: Optional[str] = None
    invited_name: Optional[str] = None
    role: str = Field("commenter", pattern="^(viewer|commenter)$")
    expires_in_days: Optional[int] = Field(default=30, ge=1, le=365)


class ShareOut(BaseModel):
    id: str
    token: str
    role: str
    invited_email: Optional[str]
    invited_name: Optional[str]
    expires_at: Optional[str]
    revoked_at: Optional[str]
    last_used_at: Optional[str]
    created_at: Optional[str]
    share_url: str


@router.post("/reports/{job_id}/shares", response_model=ShareOut)
@limiter.limit("20/hour")
async def create_share(
    job_id: str,
    body: CreateShareBody,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Mint a share token. Owner only."""
    job = db.get_job_for_user(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    expires_at = None
    if body.expires_in_days:
        expires_at = (datetime.utcnow().replace(tzinfo=timezone.utc)
                      + timedelta(days=body.expires_in_days)).isoformat()

    token = _new_token()
    share = db.create_share(
        job_id=job_id,
        created_by=user["id"],
        token=token,
        role=body.role,
        invited_email=body.invited_email,
        invited_name=body.invited_name,
        expires_at=expires_at,
    )

    # Build the public share URL using the frontend URL configured for this env
    from app.config import settings as _s
    base = (_s.frontend_url or "").rstrip("/")
    share_url = f"{base}/shared/{token}" if base else f"/shared/{token}"

    return ShareOut(
        id=share["id"],
        token=token,
        role=share["role"],
        invited_email=share.get("invited_email"),
        invited_name=share.get("invited_name"),
        expires_at=share.get("expires_at"),
        revoked_at=share.get("revoked_at"),
        last_used_at=share.get("last_used_at"),
        created_at=share.get("created_at"),
        share_url=share_url,
    )


@router.get("/reports/{job_id}/shares")
async def list_shares(
    job_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List all shares an owner has minted for this job."""
    if not db.get_job_for_user(job_id, user["id"]):
        raise HTTPException(status_code=404, detail="Job not found")
    rows = db.list_shares_for_job(job_id)
    return {"shares": rows}


@router.delete("/reports/{job_id}/shares/{share_id}")
async def revoke_share(
    job_id: str,
    share_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Revoke a share. Owner only."""
    if not db.get_job_for_user(job_id, user["id"]):
        raise HTTPException(status_code=404, detail="Job not found")
    if not db.revoke_share(share_id, job_id=job_id):
        raise HTTPException(status_code=404, detail="Share not found")
    return {"ok": True}


# ============================================================
# GUEST-FACING report fetch via token (NO auth required)
# ============================================================

@router.get("/shared/{token}")
@limiter.limit("60/minute")
async def get_shared_report(token: str, request: Request):
    """Fetch the shared report. No login required — anyone with the token sees it.

    Returned payload includes a stripped report (no PII like the owner's
    full email) and the share's role so the UI knows whether to show the
    comment box.
    """
    share = db.get_share_by_token(token)
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found, expired, or revoked")

    db.touch_share(share["id"])
    job = db.get_job(share["job_id"])
    if not job:
        raise HTTPException(status_code=404, detail="Report not found")

    findings = db.list_findings_for_job(share["job_id"])
    return {
        "share": {
            "id": share["id"],
            "role": share["role"],
            "job_id": share["job_id"],
            "invited_name": share.get("invited_name"),
        },
        "report": {
            "id": job["id"],
            "filename": job.get("filename"),
            "status": job.get("status"),
            "jurisdiction": job.get("jurisdiction"),
            "summary": job.get("summary"),
            "department_reviews": job.get("department_reviews"),
            "recommendations": job.get("recommendations"),
            "completed_at": job.get("completed_at"),
        },
        "findings": findings,
    }


# ============================================================
# COMMENTS — both owners and authorized guests can post
#
# A finding is addressed by (job_id, finding_ref) where finding_ref is the
# code citation, e.g. "IBC 1011.5.2". This is stable across re-runs, unlike
# the report's ephemeral per-run finding_id.
# ============================================================

def _assert_job_access(actor: Actor, job_id: str) -> None:
    """Owner-of-job, or guest whose token is scoped to this job."""
    if actor.is_owner:
        if not db.get_job_for_user(job_id, actor.user_id):
            raise HTTPException(status_code=404, detail="Report not found")
    else:
        if actor.job_id != job_id:
            raise HTTPException(status_code=403, detail="Token does not grant access to this report")


class CommentBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)
    author_display: Optional[str] = None  # used by guests if X-Guest-Name not set


@router.post("/reports/{job_id}/findings/{finding_ref}/comments")
@limiter.limit("30/minute")
async def add_comment(
    job_id: str,
    finding_ref: str,
    body: CommentBody,
    request: Request,
    actor: Actor = Depends(get_actor),
):
    if not actor.can_comment:
        raise HTTPException(status_code=403, detail="This share is view-only")
    _assert_job_access(actor, job_id)

    display = (body.author_display or actor.display or "Guest")[:80]
    row = db.add_finding_comment(
        job_id=job_id,
        finding_ref=finding_ref,
        author_display=display,
        body=body.body.strip(),
        author_user_id=actor.user_id,
        author_share_id=actor.share_id,
        author_email=actor.email,
    )
    return {"comment": row}


@router.get("/reports/{job_id}/findings/{finding_ref}/comments")
@limiter.limit("120/minute")
async def list_comments(
    job_id: str,
    finding_ref: str,
    request: Request,
    actor: Actor = Depends(get_actor),
):
    """Anyone with view access to the parent report can read comments."""
    _assert_job_access(actor, job_id)
    return {"comments": db.list_comments_for_finding(job_id, finding_ref)}


@router.get("/reports/{job_id}/comments")
@limiter.limit("120/minute")
async def list_all_comments(
    job_id: str,
    request: Request,
    actor: Actor = Depends(get_actor),
):
    """All comments across the report — used to show counts without N requests."""
    _assert_job_access(actor, job_id)
    return {"comments": db.list_comments_for_job(job_id)}
