"""
API endpoint tests.
Run with: pytest tests/test_api.py -v
"""
import pytest
import io
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
from app.main import app

client = TestClient(app)


def make_fake_pdf() -> bytes:
    """Create a minimal valid-looking PDF bytes."""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


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


class TestUploadEndpoint:

    def test_upload_requires_pdf(self):
        r = client.post(
            "/api/v1/upload",
            files={"file": ("test.txt", b"not a pdf", "text/plain")},
        )
        assert r.status_code == 400

    def test_upload_pdf_accepted(self):
        with patch("app.api.routes.process_job", new_callable=AsyncMock):
            r = client.post(
                "/api/v1/upload",
                files={"file": ("plan.pdf", make_fake_pdf(), "application/pdf")},
            )
        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data
        assert data["filename"] == "plan.pdf"
        assert len(data["job_id"]) > 0

    def test_upload_returns_job_id(self):
        with patch("app.api.routes.process_job", new_callable=AsyncMock):
            r = client.post(
                "/api/v1/upload",
                files={"file": ("myplans.pdf", make_fake_pdf(), "application/pdf")},
            )
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        # Fetch job status
        r2 = client.get(f"/api/v1/jobs/{job_id}")
        assert r2.status_code == 200
        assert r2.json()["job_id"] == job_id


class TestJobEndpoints:

    def test_get_nonexistent_job(self):
        r = client.get("/api/v1/jobs/nonexistent-job-id")
        assert r.status_code == 404

    def test_list_jobs(self):
        r = client.get("/api/v1/jobs")
        assert r.status_code == 200
        assert "jobs" in r.json()

    def test_delete_job(self):
        with patch("app.api.routes.process_job", new_callable=AsyncMock):
            upload_r = client.post(
                "/api/v1/upload",
                files={"file": ("test.pdf", make_fake_pdf(), "application/pdf")},
            )
        job_id = upload_r.json()["job_id"]

        r = client.delete(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200

        r2 = client.get(f"/api/v1/jobs/{job_id}")
        assert r2.status_code == 404

    def test_export_requires_completed_job(self):
        with patch("app.api.routes.process_job", new_callable=AsyncMock):
            upload_r = client.post(
                "/api/v1/upload",
                files={"file": ("test.pdf", make_fake_pdf(), "application/pdf")},
            )
        job_id = upload_r.json()["job_id"]

        # Export should fail for pending/processing job
        r = client.get(f"/api/v1/jobs/{job_id}/export/pdf")
        assert r.status_code == 400
