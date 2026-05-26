from pydantic_settings import BaseSettings
from typing import Optional, List
from functools import lru_cache
import os
from pathlib import Path

# Resolve .env relative to this file so it works regardless of cwd
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Application
    app_name: str = "AI Plan Checker"
    app_version: str = "2.0.0"
    debug: bool = False
    environment: str = "development"

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:3000"
    allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:3001"]

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-7"           # premium model, used by Surveyor
    # Sonnet 4-6 is the current cheap model (companion to Opus 4-7). "claude-sonnet-4-7"
    # does not exist in Anthropic's catalog and any call referencing it returns 404,
    # which silently degrades every department reviewer to needs_review. Do not
    # change to "4-7" without verifying with the Anthropic API first.
    anthropic_model_cheap: str = "claude-sonnet-4-6"   # ~5x cheaper, used by 10 department reviewers
    anthropic_max_tokens: int = 4096

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    require_auth: bool = True

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_professional: str = ""
    stripe_price_unlimited: str = ""
    # Pay-per-use credit packs (the active pricing model — replaces tiers).
    # Set each to the Stripe Price ID once the products are created in the
    # Stripe Dashboard. Pack size = number of plan reviews granted on payment.
    stripe_price_pack_1:   str = ""
    stripe_price_pack_5:   str = ""
    stripe_price_pack_25:  str = ""
    stripe_price_pack_100: str = ""
    frontend_url: str = "http://localhost:3001"

    # Observability + transactional email — fill in when accounts are created
    sentry_dsn: str = ""
    resend_api_key: str = ""
    support_email: str = "esmith.marc@gmail.com"

    # Admin allowlist. Comma-separated emails. Members are exempt from:
    #   - credit decrement on /upload (so accuracy testing isn't gated by balance)
    #   - the per-user rate limit (so a sweep of 100 plans works in a day)
    # Granting / revoking admin is an env-var change — no DB migration.
    admin_emails: str = ""

    # Founder email is always an admin regardless of ADMIN_EMAILS env var.
    # This guarantees the founder is never accidentally locked out of their
    # own app by a missing or misspelled env var. To add additional admins,
    # set ADMIN_EMAILS to a comma-separated list on Render.
    _FOUNDER_FALLBACK: str = "esmith.marc@gmail.com"

    @property
    def admin_email_set(self) -> set:
        """Normalized lowercase set of admin emails for O(1) lookup.
        Always includes the founder fallback unioned with the env-var list."""
        base = {self._FOUNDER_FALLBACK.lower()}
        if not self.admin_emails:
            return base
        return base | {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    # File Storage
    max_upload_size_mb: int = 100
    upload_folder: str = "./uploads"
    export_folder: str = "./exports"

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"

    class Config:
        env_file = str(_ENV_PATH)
        case_sensitive = False
        extra = "ignore"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

for folder in [settings.upload_folder, settings.export_folder]:
    os.makedirs(folder, exist_ok=True)
