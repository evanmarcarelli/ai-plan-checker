"""Regression guards for the durable, lease-based job queue (migration 007).

These lock in the architectural fix that replaced the in-process
BackgroundTasks pipeline:

  1. The web /upload endpoint only ENQUEUES — it never runs the pipeline.
     The job is left 'pending' for a worker to claim.
  2. Credit refunds are IDEMPOTENT — a retry or double-call can't mint a
     credit (the credit_refunded flag guards it), even on the pre-migration
     Python fallback path.
  3. claim_next_job degrades gracefully if migration 007 isn't applied yet
     (returns None instead of 500ing the worker).
  4. A terminal job failure refunds exactly once.
"""
import uuid as _uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import app
from app.services import db as dbmod
from app.services import job_processor


DEV_USER = "00000000-0000-0000-0000-000000000000"


# ─────────────────────────────────────────────────────────────
# 1. The web tier enqueues; it does not process.
# ─────────────────────────────────────────────────────────────

class _EnqueueOnlyDB:
    """Minimal db stand-in that records what the route did."""
    def __init__(self):
        self.jobs = {}

    def create_job(self, user_id, filename, file_size, storage_path=None, credit_charged=False):
        jid = str(_uuid.uuid4())
        self.jobs[jid] = {
            "id": jid, "user_id": user_id, "filename": filename,
            "file_size": file_size, "storage_path": storage_path,
            "status": "pending", "credit_charged": credit_charged,
        }
        return jid

    def decrement_credits(self, *a, **k):
        return 99_999


def test_upload_enqueues_pending_and_does_not_process(monkeypatch):
    """POST /upload must create a 'pending' job and return immediately —
    no pipeline runs in the request. If the pipeline ever leaks back into
    the web process, the regression that caused event-loop stalls / web OOM
    is back."""
    from app.config import settings
    from app.services.auth import get_current_user

    monkeypatch.setattr(settings, "require_auth", False)
    fake = _EnqueueOnlyDB()
    monkeypatch.setattr(routes, "db", fake)
    if hasattr(routes, "limiter"):
        monkeypatch.setattr(routes.limiter, "enabled", False)

    # The web module must not even import the pipeline anymore.
    assert not hasattr(routes, "PlanCheckerWorkflow"), \
        "routes.py must not import the pipeline — that's the worker's job"
    assert not hasattr(routes, "_process_job"), \
        "the in-process job runner must be gone from the web tier"

    app.dependency_overrides[get_current_user] = lambda: {"id": DEV_USER, "email": "a@b.com"}
    try:
        client = TestClient(app)
        body = {"storage_path": f"{DEV_USER}/{_uuid.uuid4()}.pdf",
                "filename": "plan.pdf", "file_size": 1000}
        res = client.post("/api/v1/upload", json=body)
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]
    assert fake.jobs[job_id]["status"] == "pending"


# ─────────────────────────────────────────────────────────────
# 2 & 4. Idempotent refund (pre-migration Python fallback path).
# ─────────────────────────────────────────────────────────────

def test_refund_job_credit_is_idempotent_on_fallback(monkeypatch):
    """With the RPC absent (migration not applied), the Python fallback must
    still refund at most once: the second call sees credit_refunded=True and
    is a no-op."""
    store = {
        "job1": {"id": "job1", "user_id": "u1",
                 "credit_charged": True, "credit_refunded": False},
    }
    add_calls = []

    # Force the fallback branch (RPC "not deployed").
    monkeypatch.setattr(dbmod, "_rpc_scalar", lambda fn, params: None)
    monkeypatch.setattr(dbmod, "get_job", lambda jid: store.get(jid))
    monkeypatch.setattr(dbmod, "add_credits", lambda uid, amt: add_calls.append((uid, amt)))

    def _update(jid, fields):
        store[jid].update(fields)
    monkeypatch.setattr(dbmod, "update_job", _update)

    assert dbmod.refund_job_credit("job1") is True       # first refund happens
    assert dbmod.refund_job_credit("job1") is False      # second is a no-op
    assert add_calls == [("u1", 1)], "credit must be added exactly once"
    assert store["job1"]["credit_refunded"] is True


def test_refund_skipped_when_not_charged(monkeypatch):
    """Admin / dev-mode jobs were never charged → never refunded."""
    store = {"j": {"id": "j", "user_id": "u", "credit_charged": False, "credit_refunded": False}}
    add_calls = []
    monkeypatch.setattr(dbmod, "_rpc_scalar", lambda fn, params: None)
    monkeypatch.setattr(dbmod, "get_job", lambda jid: store.get(jid))
    monkeypatch.setattr(dbmod, "add_credits", lambda uid, amt: add_calls.append((uid, amt)))
    monkeypatch.setattr(dbmod, "update_job", lambda jid, fields: None)

    assert dbmod.refund_job_credit("j") is False
    assert add_calls == []


def test_terminal_fail_marks_failed_and_refunds_once(monkeypatch):
    """A deterministic job failure must mark the row failed AND refund once."""
    calls = {"update": [], "refund": []}
    monkeypatch.setattr(job_processor.db, "update_job",
                        lambda jid, fields: calls["update"].append((jid, fields)))
    monkeypatch.setattr(job_processor.db, "refund_job_credit",
                        lambda jid: calls["refund"].append(jid) or True)

    job_processor._terminal_fail("jobX", "boom")

    assert calls["update"] == [("jobX", {"status": "failed", "error": "boom"})]
    assert calls["refund"] == ["jobX"]


# ─────────────────────────────────────────────────────────────
# 3. claim_next_job degrades gracefully before the migration.
# ─────────────────────────────────────────────────────────────

def test_claim_next_job_returns_none_when_rpc_missing(monkeypatch):
    """If the claim_next_job function isn't deployed, the worker must get
    None (idle) rather than an exception that crashes the loop."""
    class _Raises:
        def rpc(self, *a, **k):
            raise RuntimeError("function public.claim_next_job does not exist")
    monkeypatch.setattr(dbmod, "admin", lambda: _Raises())

    assert dbmod.claim_next_job("worker-1", 180) is None


def test_fail_exhausted_jobs_returns_zero_when_rpc_missing(monkeypatch):
    monkeypatch.setattr(dbmod, "_rpc_scalar", lambda fn, params: None)
    assert dbmod.fail_exhausted_jobs() == 0
