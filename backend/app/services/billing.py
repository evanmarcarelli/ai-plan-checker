"""Stripe integration: Checkout sessions, Customer Portal, webhook handling."""
from typing import Dict, Optional, Tuple
import stripe
from app.config import settings
from app.services import db
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Strip the API key defensively. Render's env-var paste often appends a
# trailing newline that makes Stripe reject auth with a misleading error.
stripe.api_key = (settings.stripe_secret_key or "").strip()

# Strip env values defensively — Render's paste UI often appends a trailing
# newline that breaks dict lookups against Stripe's clean price IDs.
def _strip(s: Optional[str]) -> str:
    return (s or "").strip()

# Map Stripe price ID -> (plan_tier, credits_per_month). -1 = unlimited.
# Pack price IDs (Render env STRIPE_PRICE_PACK_*) are recurring subscriptions
# whose monthly grant equals the pack size. Credits roll over between months.
PRICE_TO_PLAN: Dict[str, Tuple[str, int]] = {
    _strip(settings.stripe_price_starter):      ("starter",         10),
    _strip(settings.stripe_price_professional): ("professional",    50),
    _strip(settings.stripe_price_unlimited):    ("unlimited",       -1),
    _strip(settings.stripe_price_pack_1):       ("try-one",          1),
    _strip(settings.stripe_price_pack_5):       ("single-project",   5),
    _strip(settings.stripe_price_pack_25):      ("firm-pack",       25),
    _strip(settings.stripe_price_pack_100):     ("annual",         100),
}
# Drop any "" key from unset env vars so unknown prices don't accidentally match.
PRICE_TO_PLAN.pop("", None)


def get_or_create_customer(user_id: str, email: Optional[str]) -> str:
    """Return the Stripe customer ID for this user, creating one if needed.

    Validates the stored ID against Stripe so a test→live key migration
    (or manual customer deletion) auto-heals instead of crashing checkout.
    """
    profile = db.get_profile(user_id) or {}
    stored_id = (profile.get("stripe_customer_id") or "").strip()
    if stored_id:
        try:
            stripe.Customer.retrieve(stored_id)
            return stored_id
        except stripe.error.InvalidRequestError:
            # Customer not found in current Stripe mode (e.g. test→live migration).
            # Clear the stale ID and fall through to create a fresh one.
            logger.warning(f"Stripe customer {stored_id} not found in current mode; recreating for user {user_id}")
            db.admin().table("profiles").update({"stripe_customer_id": None}).eq("id", user_id).execute()
    customer = stripe.Customer.create(
        email=email,
        metadata={"supabase_user_id": user_id},
    )
    db.admin().table("profiles").update({"stripe_customer_id": customer.id}).eq("id", user_id).execute()
    return customer.id


# ─────────────────────────────────────────────────────────────────────
# Pay-per-use credit packs (active pricing model)
#
# Pack size → (Stripe price-ID accessor, label). The accessor is a lambda
# so it reads `settings` lazily — the env var may be empty at module
# import time and filled in at deploy time.
# ─────────────────────────────────────────────────────────────────────
PACKS: Dict[int, Tuple] = {
    1:   (lambda: settings.stripe_price_pack_1,   "1 check"),
    5:   (lambda: settings.stripe_price_pack_5,   "5 checks"),
    25:  (lambda: settings.stripe_price_pack_25,  "25 checks"),
    100: (lambda: settings.stripe_price_pack_100, "100 checks"),
}


def create_pack_checkout(user_id: str, email: Optional[str], pack_size: int) -> str:
    """Create a recurring-subscription Stripe Checkout Session for a credit pack.

    Each pack price in Stripe is a monthly subscription whose allotment
    equals the pack size. Credits are granted on `invoice.payment_succeeded`
    (initial + each renewal) and roll over between months.
    """
    if pack_size not in PACKS:
        raise ValueError(f"Unknown pack size: {pack_size}")
    price_id = _strip(PACKS[pack_size][0]())
    if not price_id:
        raise ValueError(f"STRIPE_PRICE_PACK_{pack_size} is not configured")

    customer_id = get_or_create_customer(user_id, email)
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.frontend_url}/dashboard?purchase=success",
        cancel_url=f"{settings.frontend_url}/billing?purchase=canceled",
        client_reference_id=user_id,
        # Subscription-scoped metadata lets the invoice webhook reverse-map
        # to the user without depending on the customer-id lookup.
        subscription_data={"metadata": {
            "supabase_user_id": user_id,
            "pack_size": str(pack_size),
        }},
        metadata={
            "supabase_user_id": user_id,
            "pack_size": str(pack_size),
        },
        allow_promotion_codes=True,
    )
    return session.url


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
        # Two distinct flows share this event:
        #   mode == "payment"      → one-time credit pack (NEW pricing model)
        #   mode == "subscription" → legacy monthly tier (still supported)
        mode = obj.get("mode")
        user_id = obj.get("client_reference_id")
        if mode == "payment":
            _apply_pack_payment(user_id, obj)
        else:
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
        # Sole credit-grant trigger for subscription packs. Fires on initial
        # purchase AND each monthly renewal, so one path handles both.
        sub_id = obj.get("subscription")
        invoice_id = obj.get("id")
        amount_paid = obj.get("amount_paid") or 0
        currency = (obj.get("currency") or "usd").lower()
        if sub_id and invoice_id:
            sub = stripe.Subscription.retrieve(sub_id)
            user_id = (sub.get("metadata") or {}).get("supabase_user_id") or _find_user_by_customer(sub.get("customer"))
            if user_id:
                _grant_monthly_credits(user_id, sub, invoice_id, amount_paid, currency)


def _purchase_exists(column: str, value: str) -> bool:
    """True if a credit_purchases row already carries this idempotency key.
    Used to tell a benign duplicate webhook (the UNIQUE constraint fired on
    insert) apart from a genuine DB failure, so the former logs as info
    instead of a misleading error on the payments path."""
    try:
        res = db.admin().table("credit_purchases").select("id").eq(column, value).limit(1).execute()
        return bool(res.data)
    except Exception:
        return False


def _apply_pack_payment(user_id: Optional[str], session: Dict) -> None:
    """Grant credits on a one-time pack payment. Idempotent: writes a
    `credit_purchases` row keyed on Stripe session_id, so a re-fired
    webhook (Stripe retries on transient failures) is a no-op."""
    session_id = session.get("id")
    if not session_id:
        logger.warning("[pack] no session id on event; skipping")
        return

    meta = session.get("metadata") or {}
    if not user_id:
        user_id = meta.get("supabase_user_id")
    if not user_id:
        logger.warning(f"[pack] no user_id on session {session_id}; skipping")
        return

    try:
        credits = int(meta.get("credits", "0"))
    except (TypeError, ValueError):
        credits = 0
    if credits <= 0:
        logger.warning(f"[pack] session {session_id} has no credits metadata; skipping")
        return

    # Idempotency: skip if we've already processed this session.
    existing = (
        db.admin().table("credit_purchases")
        .select("id")
        .eq("stripe_session_id", session_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        logger.info(f"[pack] session {session_id} already credited; skipping")
        return

    # Log the purchase FIRST (the idempotency marker), then grant credits.
    # If the table insert fails the credits don't get granted — better than
    # the inverse (credits granted, no record).
    try:
        db.admin().table("credit_purchases").insert({
            "user_id": user_id,
            "stripe_session_id": session_id,
            "pack_size": credits,
            "credits_added": credits,
            "amount_cents": session.get("amount_total") or 0,
            "currency": (session.get("currency") or "usd").lower(),
        }).execute()
    except Exception as e:
        # A concurrent webhook delivery may have inserted first; the UNIQUE
        # constraint on stripe_session_id then rejects this one. That's the
        # idempotency guard working — not a failure.
        if _purchase_exists("stripe_session_id", session_id):
            logger.info(f"[pack] session {session_id} already credited (concurrent webhook); skipping")
        else:
            logger.error(f"[pack] failed to log purchase {session_id}: {e}")
        return

    new_balance = db.add_credits(user_id, credits)
    logger.info(f"[pack] granted {credits} credits to {user_id} (session {session_id}); new balance={new_balance}")


def _find_user_by_customer(customer_id: Optional[str]) -> Optional[str]:
    if not customer_id:
        return None
    res = db.admin().table("profiles").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
    return res.data[0]["id"] if res.data else None


def _sub_price_id(sub) -> str:
    """Price id of the subscription's first item, or "" when the items list
    is absent or empty — `if sub.get("items")` alone passes an items object
    whose data array is empty, and [0] then raises in the webhook handler."""
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return ""
    return _strip(items[0]["price"]["id"])


def _apply_subscription(user_id: str, sub) -> None:
    """Update plan metadata on subscription create/update. Credits are NOT
    granted here — that's the `invoice.payment_succeeded` path, which fires
    both on initial purchase and each renewal."""
    price_id = _sub_price_id(sub)
    tier, credits = PRICE_TO_PLAN.get(price_id, ("unknown", 0))

    from datetime import datetime, timezone
    period_end_ts = sub.get("current_period_end")
    period_end_iso = datetime.fromtimestamp(period_end_ts, tz=timezone.utc).isoformat() if period_end_ts else None

    db.admin().table("profiles").update({
        "plan_tier": tier,
        "plan_credits_per_month": credits,
        "stripe_subscription_id": sub["id"],
        "subscription_status": sub.get("status"),
        "subscription_current_period_end": period_end_iso,
    }).eq("id", user_id).execute()


def _grant_monthly_credits(
    user_id: str,
    sub,
    invoice_id: str,
    amount_paid: int = 0,
    currency: str = "usd",
) -> None:
    """Additively grant the monthly allotment for this subscription, with
    rollover. Idempotent on invoice_id — Stripe retries on transient failures
    are no-ops once we've written the credit_purchases row.
    """
    price_id = _sub_price_id(sub)
    tier, monthly = PRICE_TO_PLAN.get(price_id, ("unknown", 0))
    if monthly == 0:
        logger.warning(f"[invoice {invoice_id}] unknown price {price_id}; no credits granted")
        return

    # Idempotency: skip if this invoice was already credited (Stripe retries).
    existing = (
        db.admin().table("credit_purchases")
        .select("id")
        .eq("stripe_invoice_id", invoice_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        logger.info(f"[invoice {invoice_id}] already credited; skipping")
        return

    profile = db.get_profile(user_id) or {}
    current = profile.get("credits_remaining") or 0
    grant = 9999 if monthly == -1 else monthly
    new_balance = current + grant  # rollover: add, don't overwrite

    # Write the purchase row FIRST (the idempotency marker), then the balance.
    # If the insert fails we don't grant; better than the inverse.
    try:
        db.admin().table("credit_purchases").insert({
            "user_id": user_id,
            "stripe_invoice_id": invoice_id,
            "pack_size": grant,
            "credits_added": grant,
            "amount_cents": amount_paid,
            "currency": currency,
        }).execute()
    except Exception as e:
        # Concurrent delivery already inserted — UNIQUE(stripe_invoice_id)
        # rejected this one. Idempotency guard working, not a failure.
        if _purchase_exists("stripe_invoice_id", invoice_id):
            logger.info(f"[invoice {invoice_id}] already credited (concurrent webhook); skipping")
        else:
            logger.error(f"[invoice {invoice_id}] failed to log purchase: {e}")
        return

    db.admin().table("profiles").update({
        "credits_remaining": new_balance,
    }).eq("id", user_id).execute()
    logger.info(f"[invoice {invoice_id}] +{grant} credits to {user_id} ({tier}); balance {current} → {new_balance}")
