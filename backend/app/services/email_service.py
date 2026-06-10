"""Transactional email via Resend.

When RESEND_API_KEY is not set, all sends are logged but skipped (no-op).
This keeps dev/test flows working without an account.
"""
from typing import Optional
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

FROM_ADDRESS = "Architechtura <noreply@up2code.ai>"


def _client():
    if not settings.resend_api_key:
        return None
    try:
        import resend
        resend.api_key = settings.resend_api_key
        return resend
    except Exception as e:
        logger.warning(f"Resend init failed: {e}")
        return None


def send(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Send a transactional email. Returns True on success."""
    client = _client()
    if not client:
        logger.info(f"[email:noop] to={to} subject={subject!r}")
        return False
    try:
        client.Emails.send({
            "from": FROM_ADDRESS,
            "to": to,
            "subject": subject,
            "html": html,
            "text": text or "",
            "reply_to": settings.support_email,
        })
        logger.info(f"[email:sent] to={to} subject={subject!r}")
        return True
    except Exception as e:
        logger.error(f"[email:fail] to={to} subject={subject!r}: {e}")
        return False


# --- Templates ---

def send_welcome(to: str, display_name: Optional[str] = None) -> bool:
    name = display_name or to.split("@", 1)[0]
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 520px;">
      <h2 style="color: #1e293b;">Welcome to AI Plan Checker, {name}.</h2>
      <p>You've got <strong>1 free pre-submittal review</strong> on us. Upload a PDF plan set and 12 specialist
      AI agents will check it against the building codes that apply to your jurisdiction.</p>
      <p><a href="{settings.frontend_url}/dashboard"
            style="display:inline-block; background:#4f7eff; color:#fff; padding:10px 16px; border-radius:8px; text-decoration:none;">
        Open the dashboard</a></p>
      <p style="font-size:12px; color:#64748b;">Reminder: every report is AI-generated for educational use only.
      Always verify with a licensed professional and the AHJ.</p>
    </div>
    """
    return send(to, "Welcome to AI Plan Checker", html)


def send_report_ready(to: str, job_id: str, filename: str) -> bool:
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 520px;">
      <h2 style="color: #1e293b;">Your review is ready</h2>
      <p>The 12-agent compliance review for <strong>{filename}</strong> has finished.</p>
      <p><a href="{settings.frontend_url}/dashboard?job={job_id}"
            style="display:inline-block; background:#4f7eff; color:#fff; padding:10px 16px; border-radius:8px; text-decoration:none;">
        View report</a></p>
    </div>
    """
    return send(to, "Your AI Plan Checker review is ready", html)
