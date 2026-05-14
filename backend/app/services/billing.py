"""Stripe integration: Checkout sessions, Customer Portal, webhook handling."""
from typing import Dict, Optional, Tuple
import stripe
from app.config import settings
from app.services import db
from app.utils.logger import get_logger

logger = get_logger(__name__)

stripe.api_key = settings.stripe_secret_key

# Map Stripe price ID -> (plan_tier, credits_per_month). -1 = unlimited.
PRICE_TO_PLAN: Dict[str, Tuple[str, int]] = {
    settings.stripe_price_starter:      ("starter",       10),
    settings.stripe_price_professional: ("professional",  50),
    settings.stripe_price_unlimited:    ("unlimited",     -1),
}


def get_or_create_customer(user_id: str, email: Optional[str]) -> str:
    """Return the Stripe customer ID for this user, creating one if needed."""
    profile = db.get_profile(user_id) or {}
    if profile.get("stripe_customer_id"):
        return profile["stripe_customer_id"]
    customer = stripe.Customer.create(
        email=email,
        metadata={"supabase_user_id": user_id},
    )
    db.admin().table("profiles").update({"stripe_customer_id": customer.id}).eq("id", user_id).execute()
    return customer.id


def create_checkout_session(user_id: str, email: Optional[str], price_id: str) -> str:
    """Create a Stripe Checkout Session and return its URL."""
    if price_id not in PRICE_TO_PLAN:
        raise ValueError(f"Unknown price_id: {price_id}")

    customer_id = get_or_create_customer(user_id, email)
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.frontend_url}/dashboard?checkout=success",
        cancel_url=f"{settings.frontend_url}/billing?checkout=canceled",
        client_reference_id=user_id,
        subscription_data={"metadata": {"supabase_user_id": user_id}},
        allow_promotion_codes=True,
    )
    return session.url


def create_portal_session(user_id: str, email: Optional[str]) -> str:
    """Create a Customer Portal session URL for managing/canceling subscription."""
    customer_id = get_or_create_customer(user_id, email)
    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{settings.frontend_url}/dashboard",
    )
    return portal.url


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    if not settings.stripe_webhook_secret:
        # In dev, accept unverified events for easier testing — log loudly
        logger.warning("STRIPE_WEBHOOK_SECRET not set; accepting unverified event")
        import json
        return stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def handle_event(event: stripe.Event) -> None:
    """Process Stripe webhook events to update subscription state in our DB."""
    etype = event["type"]
    obj = event["data"]["object"]
    logger.info(f"Stripe event: {etype}")

    if etype == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        subscription_id = obj.get("subscription")
        if user_id and subscription_id:
            sub = stripe.Subscription.retrieve(subscription_id)
            _apply_subscription(user_id, sub)

    elif etype in ("customer.subscription.created", "customer.subscription.updated"):
        user_id = (obj.get("metadata") or {}).get("supabase_user_id")
        if not user_id:
            user_id = _find_user_by_customer(obj.get("customer"))
        if user_id:
            _apply_subscription(user_id, obj)

    elif etype == "customer.subscription.deleted":
        user_id = (obj.get("metadata") or {}).get("supabase_user_id") or _find_user_by_customer(obj.get("customer"))
        if user_id:
            db.admin().table("profiles").update({
                "plan_tier": "free",
                "plan_credits_per_month": 1,
                "subscription_status": "canceled",
                "stripe_subscription_id": None,
            }).eq("id", user_id).execute()

    elif etype == "invoice.payment_succeeded":
        # Top up credits for the new billing period
        sub_id = obj.get("subscription")
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            user_id = (sub.get("metadata") or {}).get("supabase_user_id") or _find_user_by_customer(sub.get("customer"))
            if user_id:
                _grant_monthly_credits(user_id, sub)


def _find_user_by_customer(customer_id: Optional[str]) -> Optional[str]:
    if not customer_id:
        return None
    res = db.admin().table("profiles").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
    return res.data[0]["id"] if res.data else None


def _apply_subscription(user_id: str, sub) -> None:
    price_id = sub["items"]["data"][0]["price"]["id"] if sub.get("items") else None
    tier_credits = PRICE_TO_PLAN.get(price_id, ("unknown", 0))
    tier, credits = tier_credits

    from datetime import datetime, timezone
    period_end_ts = sub.get("current_period_end")
    period_end_iso = datetime.fromtimestamp(period_end_ts, tz=timezone.utc).isoformat() if period_end_ts else None

    profile = db.get_profile(user_id) or {}
    # Top up credits when first becoming active (or upgrading); leave alone if already on this tier
    new_credits = profile.get("credits_remaining") or 0
    if tier != profile.get("plan_tier") or profile.get("subscription_status") != "active":
        if credits == -1:
            new_credits = 9999  # "unlimited" — set high; we don't decrement to zero on Unlimited
        else:
            new_credits = max(new_credits, credits)

    db.admin().table("profiles").update({
        "plan_tier": tier,
        "plan_credits_per_month": credits,
        "stripe_subscription_id": sub["id"],
        "subscription_status": sub.get("status"),
        "subscription_current_period_end": period_end_iso,
        "credits_remaining": new_credits,
    }).eq("id", user_id).execute()


def _grant_monthly_credits(user_id: str, sub) -> None:
    """On a successful invoice payment, refill the monthly credit allotment."""
    price_id = sub["items"]["data"][0]["price"]["id"] if sub.get("items") else None
    tier, credits = PRICE_TO_PLAN.get(price_id, ("unknown", 0))
    if credits == -1:
        new_credits = 9999  # unlimited
    else:
        new_credits = credits
    db.admin().table("profiles").update({
        "credits_remaining": new_credits,
    }).eq("id", user_id).execute()
    logger.info(f"Granted {new_credits} credits to {user_id} ({tier})")
