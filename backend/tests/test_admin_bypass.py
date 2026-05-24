"""Regression guards for the admin bypass on credit decrement + rate limit.

Admins (allowlisted by email via the ADMIN_EMAILS env var) are exempt from:
  1. Credit decrement on /upload — so accuracy testing isn't gated by balance
  2. The 3/min · 15/hr · 50/day rate limit — so a sweep of 100 plans works

Both bypasses are scoped to the email allowlist (settings.admin_emails),
NOT a profile flag, so granting/revoking admin is an env-var change with
no DB migration.
"""
import uuid
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest

from app.config import settings


# ─────────────────────────────────────────────────────────────
# 1. Env-var parsing — ADMIN_EMAILS is a comma-separated string
# ─────────────────────────────────────────────────────────────

def test_admin_email_set_parses_comma_separated_case_insensitive():
    """admin_email_set must normalize whitespace and case so 'Boss@FIRM.com'
    matches 'boss@firm.com' in the allowlist."""
    with patch.object(settings, "admin_emails", "Boss@FIRM.com, dev@x.com,  "):
        result = settings.admin_email_set
    assert result == {"boss@firm.com", "dev@x.com"}


def test_admin_email_set_empty_when_unset():
    with patch.object(settings, "admin_emails", ""):
        assert settings.admin_email_set == set()


# ─────────────────────────────────────────────────────────────
# 2. is_admin_user predicate
# ─────────────────────────────────────────────────────────────

def test_is_admin_user_matches_allowlist():
    from app.api.routes import _is_admin_user
    with patch.object(settings, "admin_emails", "boss@firm.com,dev@x.com"):
        assert _is_admin_user({"id": "u1", "email": "boss@firm.com"}) is True
        assert _is_admin_user({"id": "u2", "email": "Boss@Firm.com"}) is True   # case-insensitive
        assert _is_admin_user({"id": "u3", "email": "random@elsewhere.com"}) is False
        assert _is_admin_user({"id": "u4", "email": None}) is False
        assert _is_admin_user({"id": "u5"}) is False                            # email missing


# ─────────────────────────────────────────────────────────────
# 3. Credit-check helper bypasses for admins, charges everyone else
# ─────────────────────────────────────────────────────────────

def test_maybe_decrement_credits_bypasses_for_admin():
    """Admin users must NOT have credits decremented on /upload."""
    from app.api import routes
    with patch.object(settings, "admin_emails", "boss@firm.com"), \
         patch.object(settings, "require_auth", True), \
         patch("app.services.db.decrement_credits") as dec:
        balance = routes._maybe_decrement_credits({"id": "u1", "email": "boss@firm.com"})
    assert balance > 0, "admin should see a positive balance sentinel"
    dec.assert_not_called()


def test_maybe_decrement_credits_charges_non_admin():
    """Non-admins must decrement normally."""
    from app.api import routes
    from fastapi import HTTPException
    with patch.object(settings, "admin_emails", "boss@firm.com"), \
         patch.object(settings, "require_auth", True), \
         patch("app.services.db.decrement_credits", return_value=4) as dec:
        balance = routes._maybe_decrement_credits({"id": "u2", "email": "random@x.com"})
    assert balance == 4
    dec.assert_called_once_with("u2", 1)


def test_maybe_decrement_credits_402_when_non_admin_out_of_credits():
    """Non-admin with zero balance must hit 402, NOT silently succeed."""
    from app.api import routes
    from fastapi import HTTPException
    with patch.object(settings, "admin_emails", ""), \
         patch.object(settings, "require_auth", True), \
         patch("app.services.db.decrement_credits", return_value=-1):
        with pytest.raises(HTTPException) as exc:
            routes._maybe_decrement_credits({"id": "u3", "email": "broke@x.com"})
    assert exc.value.status_code == 402


# ─────────────────────────────────────────────────────────────
# 4. Rate-limit key — admins get unique-per-request key (= unlimited)
# ─────────────────────────────────────────────────────────────

def _request_with_token(email: str):
    token = pyjwt.encode({"email": email, "sub": "x"}, "any", algorithm="HS256")
    req = MagicMock()
    req.headers.get.return_value = f"Bearer {token}"
    return req


def test_rate_key_admin_gets_unique_per_request_keys():
    """An admin's rate-limit key must be unique per request so they never
    accumulate against the per-user bucket → effectively unlimited."""
    from app.api.routes import _rate_key
    with patch.object(settings, "admin_emails", "boss@firm.com"):
        k1 = _rate_key(_request_with_token("boss@firm.com"))
        k2 = _rate_key(_request_with_token("boss@firm.com"))
    assert k1 != k2, "admin rate-key must be unique per call"
    assert k1.startswith("admin:")
    assert k2.startswith("admin:")


def test_rate_key_non_admin_is_stable():
    """Non-admin users must get the same key across requests with the same
    token — that's what makes the per-user limit work."""
    from app.api.routes import _rate_key
    req = _request_with_token("random@elsewhere.com")
    with patch.object(settings, "admin_emails", "boss@firm.com"):
        k1 = _rate_key(req)
        k2 = _rate_key(req)
    assert k1 == k2, "non-admin rate-key must be stable across requests"
    assert k1.startswith("u:")
