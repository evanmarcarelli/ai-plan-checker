"""Auth helpers — verify Supabase JWTs and provide a current_user dependency."""
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, status
from app.config import settings
from app.services.db import admin
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """FastAPI dependency: verify the bearer token via Supabase Auth.

    Returns a dict with at least {id, email}. Raises 401 on failure.
    """
    if not settings.require_auth:
        # Dev mode: pretend we're a fixed user
        return {"id": "00000000-0000-0000-0000-000000000000", "email": "dev@local"}

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    try:
        # supabase-py provides auth.get_user(jwt) which validates against the project
        user_resp = admin().auth.get_user(token)
        user = getattr(user_resp, "user", None) or (user_resp.get("user") if isinstance(user_resp, dict) else None)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        # supabase returns a User model
        user_id = getattr(user, "id", None) or user.get("id")
        email = getattr(user, "email", None) or user.get("email")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return {"id": user_id, "email": email}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Auth verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
