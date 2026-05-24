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
    plan: str  # "starter" | "professional" | "unlimited" (legacy subscription)


# Pay-per-use credit pack request. Only the four published pack sizes are valid.
VALID_PACKS = {1, 5, 25, 100}


class PackCheckoutRequest(BaseModel):
    pack: int

    @classmethod
    def validate_pack(cls, v: int) -> int:
        if v not in VALID_PACKS:
            raise ValueError(f"pack must be one of {sorted(VALID_PACKS)}")
        return v


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


@router.post("/billing/checkout-pack")
async def create_pack_checkout(
    body: PackCheckoutRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Start a one-time-payment Stripe Checkout for a credit pack.

    The marketing landing page advertises 4 packs (1 / 5 / 25 / 100); this
    endpoint validates the request, asks Stripe for a Checkout URL, and
    hands it back so the frontend can redirect. Credits are granted by
    the webhook on payment success — not here.
    """
    if body.pack not in VALID_PACKS:
        raise HTTPException(
            status_code=400,
            detail=f"pack must be one of {sorted(VALID_PACKS)}; got {body.pack}",
        )
    try:
        url = billing.create_pack_checkout(user["id"], user.get("email"), body.pack)
        return {"url": url, "pack": body.pack}
    except ValueError as e:
        # Config errors (missing STRIPE_PRICE_PACK_N, etc.) — surface verbatim.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Surface the underlying Stripe error so the user can diagnose
        # (test vs live key mismatch, missing webhook, bad price id, etc.).
        # Endpoint is auth-required, so no risk of leaking to anonymous users.
        logger.error(f"Pack checkout creation failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Checkout creation failed ({type(e).__name__}): {e}",
        )


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
