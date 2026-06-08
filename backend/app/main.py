import re
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
from app.config import settings
from app.api.routes import router, limiter
from app.api.websocket import router as ws_router
from app.api.billing_routes import router as billing_router
from app.api.collab_routes import router as collab_router
from app.api.chat_routes import router as chat_router
from app.api.feedback_routes import router as feedback_router
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Sentry — only initialized when SENTRY_DSN is set.
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            environment=settings.environment,
            integrations=[FastApiIntegration()],
        )
        logger.info("Sentry initialized")
    except Exception as e:
        logger.warning(f"Sentry init failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    # A restart (deploy or OOM kill) destroys any in-flight background job, but
    # its DB row stays "processing" forever. Fail orphaned jobs now so users see
    # a clear error + retry instead of an eternal spinner.
    try:
        from app.services import db
        swept = db.mark_stale_jobs_failed()
        if swept:
            logger.warning(f"Startup: failed {swept} orphaned job(s) from a previous run")
    except Exception as e:
        logger.warning(f"Startup orphan sweep failed: {e}")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    description="Multi-Agent Building Code Compliance Verification",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS origin policy — single source of truth used by both the middleware
# AND the exception handlers below. App-level exception handlers in
# Starlette bypass middleware, so any 500 (or rate-limited 429) returns
# WITHOUT CORS headers unless we attach them manually. That bypass is what
# surfaces as "blocked by CORS policy: No 'Access-Control-Allow-Origin'
# header is present" in the browser — the real cause is the unhandled
# error, but the user sees CORS.
_ALLOWED_ORIGIN_REGEX = re.compile(
    r"https://ai-plan-checker(-[a-z0-9-]+)?\.vercel\.app"
)


def _allowed_origin(origin: str | None) -> str | None:
    """Return the origin if it's allowed by either the explicit list or
    the Vercel regex; otherwise None. Used to echo Origin back on error
    responses so the browser doesn't mistake a 500 for a CORS rejection."""
    if not origin:
        return None
    if origin in settings.allowed_origins:
        return origin
    if _ALLOWED_ORIGIN_REGEX.fullmatch(origin):
        return origin
    return None


def _attach_cors(request: Request, response: Response) -> Response:
    origin = _allowed_origin(request.headers.get("origin"))
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    # Allow every Vercel deployment of this project: production canonical
    # + every preview/branch/PR URL Vercel auto-generates.
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX.pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire rate limiter
app.state.limiter = limiter


# Rate-limit responses are produced by slowapi's handler, which sits
# outside the CORS middleware. Wrap it so 429s carry CORS headers too —
# otherwise an over-eager user sees "blocked by CORS" instead of a clean
# rate-limit error.
async def _rate_limit_handler_with_cors(request: Request, exc: RateLimitExceeded):
    response = _rate_limit_exceeded_handler(request, exc)
    return _attach_cors(request, response)


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler_with_cors)

app.include_router(router, prefix="/api/v1", tags=["Plan Checking"])
app.include_router(ws_router, prefix="/api/v1", tags=["WebSocket"])
app.include_router(billing_router, prefix="/api/v1", tags=["Billing"])
app.include_router(collab_router, prefix="/api/v1", tags=["Collaboration"])
app.include_router(chat_router, prefix="/api/v1", tags=["AI Assistant"])
app.include_router(feedback_router, prefix="/api/v1", tags=["Feedback"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    response = JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": str(exc)},
    )
    # App-level exception handlers in Starlette bypass middleware, so
    # CORS headers are not added automatically. Without these the browser
    # reports every 500 as "blocked by CORS policy" and hides the real
    # error from the developer console.
    return _attach_cors(request, response)


@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "environment": settings.environment,
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.app_version,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.debug,
    )
