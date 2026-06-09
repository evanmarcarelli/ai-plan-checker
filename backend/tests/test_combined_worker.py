"""Tests for the in-process worker + pre-migration fallback claim.

These lock in the "single deploy just works" behavior:
  - claim_next_job degrades to a conditional UPDATE when the migration-007 RPC
    isn't there, so jobs still process (and two workers can't double-claim);
  - run_worker runs the claim/run loop and stops cleanly on its shutdown event.
"""
import asyncio

import pytest

from app.services import db as dbmod
from app import worker


# ── fallback claim (pre-migration-007) ───────────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store):
        self.store, self.op, self.payload, self.filters = store, None, None, {}

    def select(self, *a, **k):
        self.op = "select"; return self

    def update(self, payload):
        self.op = "update"; self.payload = payload; return self

    def eq(self, k, v):
        self.filters[k] = v; return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self.op == "select":
            pend = [{"id": j["id"]} for j in self.store.values() if j["status"] == "pending"]
            return _Result(pend[:1])
        if self.op == "update":
            j = self.store.get(self.filters.get("id"))
            # conditional: only claim if it's still in the expected status
            if j and j["status"] == self.filters.get("status", j["status"]):
                j.update(self.payload)
                return _Result([j])
            return _Result([])           # racing worker already took it
        return _Result([])


class _Client:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Query(self.store)

    def rpc(self, *a, **k):
        raise RuntimeError("function public.claim_next_job(...) does not exist")


def test_fallback_claim_flips_pending_to_processing(monkeypatch):
    store = {"j1": {"id": "j1", "status": "pending", "created_at": "2026-01-01", "user_id": "u"}}
    client = _Client(store)
    monkeypatch.setattr(dbmod, "admin", lambda: client)
    monkeypatch.setattr(dbmod, "get_job", lambda jid: store.get(jid))

    job = dbmod.claim_next_job("worker-1", 180)     # RPC raises -> fallback
    assert job is not None and job["id"] == "j1"
    assert store["j1"]["status"] == "processing"
    # nothing pending left
    assert dbmod.claim_next_job("worker-1", 180) is None


def test_fallback_claim_no_double_claim(monkeypatch):
    # Once claimed (processing), a second worker's conditional update matches
    # nothing -> returns None rather than re-running the same job.
    store = {"j1": {"id": "j1", "status": "processing", "created_at": "x", "user_id": "u"}}
    client = _Client(store)
    monkeypatch.setattr(dbmod, "admin", lambda: client)
    monkeypatch.setattr(dbmod, "get_job", lambda jid: store.get(jid))
    assert dbmod.claim_next_job("worker-2", 180) is None


# ── run_worker loop ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_worker_exits_when_already_shut_down(monkeypatch):
    monkeypatch.setattr(worker.db, "fail_exhausted_jobs", lambda: 0)
    monkeypatch.setattr(worker.db, "claim_next_job", lambda wid, lease: None)
    ev = asyncio.Event()
    ev.set()                                        # pre-set -> loop body never runs
    await asyncio.wait_for(worker.run_worker(ev, label="t"), timeout=5)   # returns -> no hang


@pytest.mark.asyncio
async def test_run_worker_processes_one_job_then_stops(monkeypatch):
    seq = [{"id": "j1", "attempts": 1}]
    processed = []
    ev = asyncio.Event()

    monkeypatch.setattr(worker.db, "fail_exhausted_jobs", lambda: 0)
    monkeypatch.setattr(worker.db, "claim_next_job", lambda wid, lease: seq.pop(0) if seq else None)

    async def fake_run(job_id, worker_id, lease):
        processed.append(job_id)
        ev.set()                                    # ask the loop to stop after one

    monkeypatch.setattr(worker, "run_job", fake_run)

    await asyncio.wait_for(worker.run_worker(ev, label="t"), timeout=5)
    assert processed == ["j1"]


def test_run_worker_in_web_defaults_on():
    from app.config import settings
    assert getattr(settings, "run_worker_in_web", True) is True


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_inprocess_worker(monkeypatch):
    """The single-service guarantee: the app lifespan spawns the worker loop on
    startup and stops it cleanly on shutdown."""
    import app.main as main_mod

    started = asyncio.Event()
    stopped = {"v": False}

    async def fake_run_worker(shutdown, label="worker"):
        started.set()
        await shutdown.wait()
        stopped["v"] = True

    # lifespan does `from app.worker import run_worker` at call time.
    monkeypatch.setattr("app.worker.run_worker", fake_run_worker)

    async with main_mod.lifespan(main_mod.app):
        await asyncio.wait_for(started.wait(), timeout=2)       # worker started
    assert stopped["v"] is True                                  # stopped on exit
