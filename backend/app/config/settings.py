from pydantic_settings import BaseSettings, SettingsConfigDict
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
    # Production Vercel URL is included by default so CORS works even if
    # the regex below (in main.py) ever changes shape. Preview / branch
    # deploys are still covered by the regex.
    allowed_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://ai-plan-checker.vercel.app",
    ]

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"           # premium model, used by Surveyor
    # Sonnet 4-6 is the current cheap model (companion to Opus 4-8). "claude-sonnet-4-7"
    # does not exist in Anthropic's catalog and any call referencing it returns 404,
    # which silently degrades every department reviewer to needs_review. Do not
    # change to "4-7" without verifying with the Anthropic API first.
    # Opus 4-8 shares 4-7's request surface (adaptive thinking only; no temperature/
    # top_p/budget_tokens/prefill), so the upgrade is a model-ID swap with no code change.
    anthropic_model_cheap: str = "claude-sonnet-4-6"   # ~5x cheaper, used by 10 department reviewers
    # AI assistant chat uses the cheapest tier — these are short, grounded
    # clarification answers, not plan reviews. Haiku 4.5 is ~3x cheaper than
    # Sonnet 4.6 ($1/$5 vs $3/$15 per 1M tok). Bare alias resolves (same form
    # as anthropic_model_cheap above). Override via ANTHROPIC_MODEL_CHAT if needed.
    anthropic_model_chat: str = "claude-haiku-4-5"
    anthropic_max_tokens: int = 4096
    # Prompt-cache TTL for the cached code-requirements prefix (base.py `_call_llm`).
    # "5m" (Anthropic default) only hits if the next plan in the same jurisdiction
    # lands within 5 minutes; "1h" keeps the cache warm across plans reviewed up to
    # an hour apart — the realistic pattern for a plan-check service, where the same
    # jurisdiction recurs. 1h writes cost 2x vs 1.25x for 5m, so it pays off once a
    # cached block is reused ~3x within the hour. Drop to "5m" if traffic is sparse
    # (one plan per jurisdiction per hour). Env: PROMPT_CACHE_TTL.
    prompt_cache_ttl: str = "1h"
    # #6 — Per-department model tier. Department CATEGORIES listed here use the
    # premium model (anthropic_model) instead of the cheap one. Empty by
    # default: every reviewer stays on Sonnet (no surprise cost). Set the env
    # var STRONG_REVIEW_CATEGORIES="building_safety,fire" to upgrade the
    # judgment-heavy reviewers once credits allow — no code change needed.
    strong_review_categories: str = ""

    # How many department reviewers run concurrently. 2 is the Render Free
    # ceiling (see workflow.py for the empirical reasoning); bump via env
    # DEPARTMENT_CONCURRENCY after a dyno upgrade — no code change needed.
    department_concurrency: int = 2

    # Department routing pre-screen. When True, the workflow runs only the
    # departments app.agents.routing.select_departments deems applicable for
    # the resolved archetype (provably-irrelevant reviewers are skipped — a
    # direct token + latency win). The router FAILS OPEN: unknown / out-of-
    # scope / unmapped archetypes run the full panel. Default False = dark
    # launch: production behavior is byte-identical until a budgeted live
    # recall check validates routing, then flip via DEPARTMENT_ROUTING_ENABLED.
    department_routing_enabled: bool = False

    # Adversarial-critic model. Empty = the premium model (anthropic_model).
    # Was hardcoded in critic.py, bypassing configuration entirely.
    anthropic_model_critic: str = ""

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
    # Skip the best-effort PDF compression pass for files larger than this.
    # pdf_compressor.compress() runs doc.save(garbage=4, clean=True,
    # deflate_images=True), which rewrites the whole document in memory; on big
    # plan sets that transient spike is a top OOM cause on a 512 MB dyno, and the
    # compressed file is only used locally then deleted. Env: PDF_COMPRESS_MAX_MB.
    # Set to 0 to disable the gate (always attempt compression).
    pdf_compress_max_mb: int = 25
    upload_folder: str = "./uploads"
    export_folder: str = "./exports"

    # Code corpus source: "disk" (legacy JSONL + BM25, default) or "postgres"
    # (structured code_chunks from migration 008). "postgres" falls back to disk
    # if the table is empty/missing, so flipping this on is safe.
    code_store: str = "disk"
    # Strict postgres: when code_store="postgres" AND this is true, a missing/
    # empty DB corpus or table is a FATAL error instead of a silent fallback to
    # disk/hardcoded values. Turn this on once you trust the DB path — it makes
    # a misconfiguration loud-and-fatal rather than loud-and-degraded.
    code_store_strict: bool = False

    # Run the job-queue worker loop inside this web process (default). The
    # pipeline runs as a background task off the durable Postgres queue, so a
    # single deployment serves the API and processes jobs — no second service.
    # Set false and run `python -m app.worker` separately to scale the worker
    # out (then this web process only enqueues).
    run_worker_in_web: bool = True

    # AWS Textract (OCR fallback for image-only or scan-heavy plan sheets).
    # Off by default — only kicks in when set. When `aws_textract_enabled` is
    # true and a page yields too little text from the PyMuPDF text layer, the
    # page is rendered to PNG and run through Textract. Cheaper than Claude
    # vision per page (~$1.50/1k pages with TABLES+FORMS) and the structured
    # KV pairs feed the code-data-summary fields directly. Costs $0 when
    # off; costs $0 per plan whose text layer extracts cleanly.
    aws_textract_enabled: bool = False
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-west-2"
    # If a page's text layer yields fewer than this many chars, fall back to
    # Textract. 200 chars is roughly "title block but no labels readable" —
    # tuned to skip the cheap-and-clean PDFs and only pay for scans.
    textract_min_chars_per_page: int = 200
    # Cap pages-per-document sent to Textract. 0 = no cap (every thin page
    # gets OCR'd, full plan set covered). Set to a positive integer to bound
    # spend per plan if a particular workflow needs it.
    textract_max_pages: int = 0

    # ── Geometry extraction (net-new: measure the drawing vector layer) ──
    # Off by default — when off the pipeline behaves exactly as before. When on,
    # geometry_extractor pulls vector primitives via PyMuPDF page.get_drawings(),
    # calibrates the drawing scale from the printed scale note, and surfaces a
    # real-unit dimension catalog. Outputs land in ExtractedPlanData.geometry and
    # mirror into the `dimensions` dict so the reviewers consume them. $0 when off.
    # Perf note: a full pass is ~1 min on a 37-page set (get_drawings on dense
    # sheets); it runs in the background worker. Cap with geometry_max_pages if needed.
    geometry_extraction_enabled: bool = False
    # Phase D: Claude vision locates measurable features (corridors/egress/doors) and
    # the gray-wall geometry measures each precisely. Advisory. Costs vision tokens —
    # keep off until trusted. Requires geometry_extraction_enabled + an API key.
    geometry_vision_enabled: bool = False
    # Target long-edge pixels for the geometry-vision page render (Phase D). Kept
    # just under Anthropic's ~1568px image-resize threshold so the model sees the
    # image at the resolution we render — required for the returned (normalized)
    # feature boxes to map back to the page correctly.
    geometry_vision_max_px: int = 1536
    # Cap pages per document processed for geometry. 0 = no cap (covers the whole
    # set; floor plans can sit mid-document). Set positive to bound cost per plan.
    geometry_max_pages: int = 0

    # Playwright fallback for Cloudflare-blocked publishers
    # (amlegal, municode, qcode, ecode360). Off by default — turning this on
    # is an operational decision the operator owns. Renders the page in a
    # real Chromium with light stealth patches so the CF interstitial can
    # auto-solve. Per-host throttle keeps the fetch polite.
    playwright_enabled: bool = False
    playwright_user_agent: str = ""    # blank = use the module default UA
    playwright_delay_sec: float = 2.0  # min seconds between fetches per host
    playwright_timeout_sec: int = 60   # per-fetch hard cap (sec)

    # Standard correction checklists
    # Inject published plan-check correction-list items as extra requirements so
    # coverage matches a real plan check (a real residential set runs many pages
    # of corrections). On by default. The per-department cap balances depth
    # against the precision target and per-run token cost — raise it for more
    # depth, lower it if false positives creep in. Commercial occupancies get
    # nothing until a commercial list is ingested.
    checklist_review_enabled: bool = True
    checklist_max_per_department: int = 40

    # ── Anti-hallucination guards on LLM department findings ──
    # Contradiction guard: downgrade a NON_COMPLIANT whose cited section IS
    # in the corpus but whose text doesn't support the claim (wrong-section
    # cite). For text we have, the corpus is authoritative.
    citation_contradiction_guard: bool = True
    # Table cross-check: downgrade a NON_COMPLIANT citing IBC T506.2 / T504.4
    # / 403 whose claimed limit can't be reproduced from the deterministic
    # table store (an invented number hung on a real table).
    table_value_cross_check: bool = True

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"

    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

for folder in [settings.upload_folder, settings.export_folder]:
    os.makedirs(folder, exist_ok=True)
