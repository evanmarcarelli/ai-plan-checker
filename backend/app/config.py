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
    anthropic_model: str = "claude-opus-4-7"
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
    frontend_url: str = "http://localhost:3001"

    # Observability + transactional email — fill in when accounts are created
    sentry_dsn: str = ""
    resend_api_key: str = ""
    support_email: str = "esmith.marc@gmail.com"

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
