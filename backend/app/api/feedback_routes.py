"""Public feedback board: anyone signed in can post a feature request or
issue, and anyone signed in can upvote (one vote per user per post).

Why it lives in the product instead of a third-party tool (Canny etc.):
keeps the data in our Supabase, no extra subscription, and the upvote
list doubles as a product-priority signal we own.

Auth model: sign-in required to post or vote. Reading the list is also
auth-required for now (we can flip to anonymous later if we want a
fully public marketing surface).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes import limiter
from app.services import db
from app.services.auth import get_current_user
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────

class CreatePostBody(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    body: str = Field("", max_length=4000)
    author_display: Optional[str] = Field(None, max_length=80)


class FeedbackPostOut(BaseModel):
    id: str
    title: str
    body: str
    status: str
    author_display: str
    author_user_id: Optional[str] = None
    votes: int
    user_has_voted: bool
    created_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

_SETUP_HINT = (
    "The feedback board database tables are missing. "
    "Apply backend/migrations/004_feedback.sql in the Supabase SQL editor."
)


def _is_missing_table_error(e: Exception) -> bool:
    """Postgres raises 42P01 (undefined_table) through PostgREST when a
    migration hasn't been applied. Match on the code or the message so we
    don't depend on the exact exception class supabase-py raises."""
    s = str(e)
    return "42P01" in s or "does not exist" in s


def _display_for_user(user: Dict[str, Any], override: Optional[str] = None) -> str:
    """Pick what name to show for this user's posts/votes. Prefer the
    explicit override (form input), then the profile display_name, then
    the part of the email before @."""
    if override:
        return override.strip()[:80]
    profile = db.get_profile(user["id"]) or {}
    if profile.get("display_name"):
        return str(profile["display_name"])[:80]
    if profile.get("firm_name"):
        return str(profile["firm_name"])[:80]
    email = user.get("email") or ""
    return (email.split("@", 1)[0] or "Someone")[:80]


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/feedback")
@limiter.limit("60/minute")
async def list_feedback(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List all feedback posts sorted by vote count desc, then recency."""
    try:
        posts_res = (db.admin().table("feedback_posts")
                     .select("id, title, body, status, author_display, author_user_id, created_at")
                     .order("created_at", desc=True)
                     .execute())
        posts = posts_res.data or []

        if not posts:
            return {"posts": []}

        post_ids = [p["id"] for p in posts]

        # Pull all votes for these posts in one query
        votes_res = (db.admin().table("feedback_votes")
                     .select("post_id, voter_user_id")
                     .in_("post_id", post_ids)
                     .execute())
        votes = votes_res.data or []
    except Exception as e:
        if _is_missing_table_error(e):
            logger.error(f"feedback tables missing: {e}")
            raise HTTPException(status_code=503, detail=_SETUP_HINT)
        raise

    # Tally
    counts: Dict[str, int] = {pid: 0 for pid in post_ids}
    my_voted = set()
    for v in votes:
        counts[v["post_id"]] = counts.get(v["post_id"], 0) + 1
        if v["voter_user_id"] == user["id"]:
            my_voted.add(v["post_id"])

    out = [
        FeedbackPostOut(
            id=p["id"],
            title=p["title"],
            body=p.get("body") or "",
            status=p.get("status") or "open",
            author_display=p.get("author_display") or "Anonymous",
            author_user_id=p.get("author_user_id"),
            votes=counts.get(p["id"], 0),
            user_has_voted=p["id"] in my_voted,
            created_at=p.get("created_at"),
        )
        for p in posts
    ]
    # Sort by votes desc, then created_at desc (already in created order from DB)
    out.sort(key=lambda x: (-x.votes,))
    return {"posts": [o.model_dump() for o in out]}


@router.post("/feedback")
@limiter.limit("10/minute;30/day")
async def create_feedback(
    body: CreatePostBody,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    display = _display_for_user(user, body.author_display)
    try:
        res = db.admin().table("feedback_posts").insert({
            "author_user_id": user["id"],
            "author_display": display,
            "title": body.title.strip(),
            "body": body.body.strip(),
            "status": "open",
        }).execute()
    except Exception as e:
        if _is_missing_table_error(e):
            logger.error(f"feedback tables missing: {e}")
            raise HTTPException(status_code=503, detail=_SETUP_HINT)
        raise
    if not res.data:
        raise HTTPException(status_code=500, detail="Could not create post")
    row = res.data[0]
    # Author auto-votes for their own post
    try:
        db.admin().table("feedback_votes").insert({
            "post_id": row["id"],
            "voter_user_id": user["id"],
        }).execute()
    except Exception:
        pass  # already-voted constraint is fine
    return {"post": row}


@router.post("/feedback/{post_id}/vote")
@limiter.limit("60/minute")
async def toggle_vote(
    post_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Idempotent toggle: if the user has voted, remove the vote; otherwise add it."""
    try:
        existing = (db.admin().table("feedback_votes")
                    .select("post_id")
                    .eq("post_id", post_id)
                    .eq("voter_user_id", user["id"])
                    .limit(1)
                    .execute())
    except Exception as e:
        if _is_missing_table_error(e):
            logger.error(f"feedback tables missing: {e}")
            raise HTTPException(status_code=503, detail=_SETUP_HINT)
        raise
    if existing.data:
        db.admin().table("feedback_votes") \
            .delete() \
            .eq("post_id", post_id) \
            .eq("voter_user_id", user["id"]) \
            .execute()
        return {"voted": False}
    try:
        db.admin().table("feedback_votes").insert({
            "post_id": post_id,
            "voter_user_id": user["id"],
        }).execute()
    except Exception as e:
        # Composite PK protects against double-vote race; ignore the conflict
        logger.warning(f"feedback vote insert conflict: {e}")
    return {"voted": True}
