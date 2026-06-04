"""
API endpoint tests.
Run with: pytest tests/test_api.py -v

These exercise the CURRENT API contract: auth is bypassed via
settings.require_auth=False (which makes get_current_user return a fixed dev
user), the Supabase-backed db layer is replaced with an in-memory fake, the
rate limiter is disabled, and the background processing task is a no-op so no
real pipeline / network runs.

The /upload endpoint takes a JSON StartReviewBody {storage_path, filename,
file_size} — the browser uploads the PDF to Supabase Storage directly and this
endpoint is told where it landed.
"""
import uuid as _uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from app.main import app

client = TestClient(app)

# get_current_user returns this fixed identity when require_auth is False.
DEV_USER = "00000000-0000-0000-0000-000000000000"


# ─── In-memory fake of the Supabase-backed db layer ──────────────────

class _FakeQuery:
    def __init__(self, store, table):
        self._store, self._table, self._op, self._eqs = store, table, None, {}

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, k, v):
        self._eqs[k] = v
        return self

    def execute(self):
        if self._op == "delete" and self._table == "jobs":
            self._store.pop(self._eqs.get("id"), None)
        return type("R", (), {"data": []})()


class _FakeAdmin:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _FakeQuery(self._store, name)


class FakeDB:
    """Minimal in-memory stand-in for app.services.db used by the routes."""

    def __init__(self):
        self._jobs = {}

    def create_job(self, user_id, filename, file_size, storage_path=None):
        jid = str(_uuid.uuid4())
        self._jobs[jid] = {
            "id": jid, "user_id": user_id, "filename": filename,
            "file_size": file_size, "storage_path": storage_path,
            "status": "pending", "progress": 0,
            "created_at": datetime.utcnow().isoformat(), "completed_at": None,
            "current_agent": None, "agents_completed": [], "error": None,
            "summary": None, "department_reviews": None,
        }
        return jid

    def get_job_for_user(self, job_id, user_id):
        r = self._jobs.get(job_id)
        return r if r and r["user_id"] == user_id else None

    def list_jobs_for_user(self, user_id):
        return [r for r in self._jobs.values() if r["user_id"] == user_id]

    def list_logs_for_job(self, job_id, limit=200):
        return []

    def list_findings_for_job(self, job_id):
        return []

    def update_job(self, *a, **k):
        pass

    def decrement_credits(self, *a, **k):
        return 99_999

    def admin(self):
        return _FakeAdmin(self._jobs)


@pytest.fixture(autouse=True)
def _bypass_and_mock(monkeypatch):
    """Bypass auth, mock the db, disable the limiter, no-op the background task."""
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "require_auth", False)
    fake = FakeDB()
    monkeypatch.setattr(routes, "db", fake)
    monkeypatch.setattr(routes, "_fetch_and_process", AsyncMock())
    # Disable rate limiting so repeated uploads in one run don't 429.
    if hasattr(routes, "limiter"):
        monkeypatch.setattr(routes.limiter, "enabled", False)
    yield fake


def _body(filename="plan.pdf", size=1000, owner=DEV_USER):
    return {
        "storage_path": f"{owner}/{_uuid.uuid4()}.pdf",
        "filename": filename,
        "file_size": size,
    }


# ─── Health ──────────────────────────────────────────────────────────

class TestHealthEndpoints:

    def test_root(self):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "running"
        assert "version" in data

    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


# ─── Upload / start-review ───────────────────────────────────────────

class TestUploadEndpoint:

    def test_upload_rejects_non_pdf(self):
        r = client.post("/api/v1/upload", json=_body(filename="notes.txt"))
        assert r.status_code == 400

    def test_upload_rejects_foreign_storage_path(self):
        # storage path not under this user's folder -> 403
        r = client.post("/api/v1/upload", json=_body(owner="someone-else"))
        assert r.status_code == 403

    def test_upload_accepted(self):
        r = client.post("/api/v1/upload", json=_body(filename="plan.pdf"))
        assert r.status_code == 200
        data = r.json()
        assert data["filename"] == "plan.pdf"
        assert len(data["job_id"]) > 0

    def test_upload_then_fetch_status(self):
        up = client.post("/api/v1/upload", json=_body())
        assert up.status_code == 200
        job_id = up.json()["job_id"]

        r = client.get(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["job_id"] == job_id


# ─── Jobs ────────────────────────────────────────────────────────────

class TestJobEndpoints:

    def test_get_nonexistent_job(self):
        r = client.get("/api/v1/jobs/nonexistent-job-id")
        assert r.status_code == 404

    def test_list_jobs(self):
        r = client.get("/api/v1/jobs")
        assert r.status_code == 200
        assert "jobs" in r.json()

    def test_delete_job(self):
        up = client.post("/api/v1/upload", json=_body())
        job_id = up.json()["job_id"]

        r = client.delete(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200

        r2 = client.get(f"/api/v1/jobs/{job_id}")
        assert r2.status_code == 404

    def test_export_requires_completed_job(self):
        up = client.post("/api/v1/upload", json=_body())
        job_id = up.json()["job_id"]

        # A pending job can't be exported -> 400.
        r = client.get(f"/api/v1/jobs/{job_id}/export/pdf")
        assert r.status_code == 400
