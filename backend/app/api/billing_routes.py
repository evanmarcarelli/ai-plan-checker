"""Stripe billing endpoints: checkout, portal, webhook."""
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from app.config import settings
from app.services import billing, db
from app.services.auth import get_current_user
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "professional" | "unlimited"


PLAN_TO_PRICE = {
    "starter":      lambda: settings.stripe_price_starter,
    "professional": lambda: settings.stripe_price_professional,
    "unlimited":    lambda: settings.stripe_price_unlimited,
}


@router.post("/billing/checkout")
async def create_checkout(
    body: CheckoutRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if body.plan not in PLAN_TO_PRICE:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")
    price_id = PLAN_TO_PRICE[body.plan]()
    if not price_id:
        raise HTTPException(status_code=500, detail=f"Plan {body.plan} not configured")
    try:
        url = billing.create_checkout_session(user["id"], user.get("email"), price_id)
        return {"url": url}
    except Exception as e:
        logger.error(f"Checkout creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/billing/portal")
async def create_portal(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        url = billing.create_portal_session(user["id"], user.get("email"))
        return {"url": url}
    except Exception as e:
        logger.error(f"Portal creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = billing.verify_webhook(payload, stripe_signature or "")
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        billing.handle_event(event)
    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        # Return 200 so Stripe doesn't retry indefinitely on our bugs
    return {"received": True}
