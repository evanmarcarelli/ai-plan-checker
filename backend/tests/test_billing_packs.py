"""Regression guards for the pay-per-use credit-pack checkout flow.

The marketing page advertises 4 credit packs (1 / 5 / 25 / 100 checks) at
$60 / $179 / $772 / $2,999. These tests lock in the backend wiring:

  1. POST /api/v1/billing/checkout-pack with a valid pack returns a Stripe
     Checkout URL (currently 404 — the endpoint does not exist).
  2. Invalid pack sizes are rejected at the request boundary, not at Stripe.
  3. The Stripe webhook, on a one-time `checkout.session.completed` event
     carrying metadata.credits, grants the right number of credits to the
     user (currently the handler only knows subscription events).
  4. Re-firing the same webhook event MUST NOT double-grant credits. Stripe
     retries on transient failures; without idempotency we'd grant 2× /
     N× credits per purchase.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import get_current_user


FAKE_USER = {"id": "user_abc123", "email": "architect@firm.com"}


@pytest.fixture
def client():
    """TestClient with auth overridden to a fixed fake user."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    yield TestClient(app)
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────
# 1. Checkout endpoint accepts a valid pack and returns Stripe URL
# ─────────────────────────────────────────────────────────────

def test_checkout_pack_endpoint_returns_stripe_url_regression(client):
    """POST /billing/checkout-pack {pack: 25} must return 200 with a Stripe URL.
    Today this 404s — the endpoint does not exist yet."""
    with patch("app.services.billing.create_pack_checkout",
               return_value="https://checkout.stripe.com/c/pay/cs_test_xyz") as m:
        res = client.post("/api/v1/billing/checkout-pack", json={"pack": 25})

    assert res.status_code == 200, f"expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    assert body.get("url", "").startswith("https://checkout.stripe.com"), \
        f"expected a Stripe Checkout URL, got {body!r}"
    # The service was called with the right args (user id, email, pack size)
    assert m.called
    args, kwargs = m.call_args
    pack_arg = kwargs.get("pack_size") if "pack_size" in kwargs else (args[2] if len(args) > 2 else None)
    assert pack_arg == 25, f"create_pack_checkout was not called with pack=25 (got {pack_arg!r})"


# ─────────────────────────────────────────────────────────────
# 2. Validation — only 1, 5, 25, 100 are valid packs
# ─────────────────────────────────────────────────────────────

def test_checkout_pack_rejects_invalid_pack_size(client):
    """Random pack sizes must be rejected at the request boundary, NOT at
    Stripe. Today this hits Stripe with an undefined price → opaque 500."""
    with patch("app.services.billing.create_pack_checkout") as m:
        res = client.post("/api/v1/billing/checkout-pack", json={"pack": 7})
    assert res.status_code in (400, 422), \
        f"expected 4xx for invalid pack, got {res.status_code}"
    assert not m.called, "create_pack_checkout should never have been called"


# ─────────────────────────────────────────────────────────────
# 3. Webhook grants credits on one-time pack payment
# ─────────────────────────────────────────────────────────────

def _pack_payment_event(session_id: str = "cs_test_abc", credits: int = 25):
    """Build a fake Stripe `checkout.session.completed` event for a pack purchase."""
    return {
        "id": f"evt_{session_id}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "object": "checkout.session",
            "mode": "payment",                           # one-time, NOT subscription
            "client_reference_id": FAKE_USER["id"],
            "customer": "cus_xxx",
            "amount_total": credits * 6000,              # placeholder, not asserted
            "currency": "usd",
            "metadata": {
                "supabase_user_id": FAKE_USER["id"],
                "credits": str(credits),
                "pack_size": str(credits),
            },
        }},
    }


def test_webhook_pack_payment_credits_user_regression():
    """A one-time pack payment webhook must add `credits` to the user."""
    from app.services import billing

    # Mock add_credits and the credit_purchases insert (idempotency log)
    with patch("app.services.db.add_credits") as add_credits, \
         patch("app.services.db.admin") as admin:
        # Idempotency check: first time → no existing row, insert succeeds
        chain = MagicMock()
        admin.return_value = chain
        chain.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        chain.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "cp_1"}])

        billing.handle_event(_pack_payment_event(credits=25))

    add_credits.assert_called_once()
    user_arg, amt_arg = add_credits.call_args.args[:2] if add_credits.call_args.args else (
        add_credits.call_args.kwargs.get("user_id"),
        add_credits.call_args.kwargs.get("amount"),
    )
    assert user_arg == FAKE_USER["id"], f"wrong user_id (got {user_arg!r})"
    assert amt_arg == 25, f"wrong credit amount (got {amt_arg!r})"


# ─────────────────────────────────────────────────────────────
# 4. Webhook is idempotent — duplicate events do NOT double-grant
# ─────────────────────────────────────────────────────────────

def test_webhook_pack_payment_is_idempotent_regression():
    """Stripe retries webhooks. The same session_id firing twice must
    grant credits exactly once."""
    from app.services import billing

    with patch("app.services.db.add_credits") as add_credits, \
         patch("app.services.db.admin") as admin:
        chain = MagicMock()
        admin.return_value = chain

        # First call: no existing row → insert succeeds → credits granted
        # Second call: row already exists → insert is the idempotency marker, skip
        select_chain = chain.table.return_value.select.return_value.eq.return_value.limit.return_value.execute
        select_chain.side_effect = [
            MagicMock(data=[]),                          # first time: empty
            MagicMock(data=[{"id": "cp_1"}]),            # second time: already logged
        ]
        chain.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "cp_1"}])

        event = _pack_payment_event(session_id="cs_dup", credits=5)
        billing.handle_event(event)
        billing.handle_event(event)   # exact same event a second time

    assert add_credits.call_count == 1, \
        f"credits granted {add_credits.call_count}× — webhook is NOT idempotent"
