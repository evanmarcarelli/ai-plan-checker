"""Feedback board endpoint tests.

Same harness as test_api.py: auth bypassed via settings.require_auth=False,
the Supabase db layer replaced with an in-memory fake, limiter disabled.

The missing-table tests pin the contract added after the live 500: when
migration 004 hasn't been applied, the API must answer 503 with a setup
hint instead of an opaque internal_server_error.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# get_current_user returns this fixed identity when require_auth is False.
DEV_USER = "00000000-0000-0000-0000-000000000000"

MISSING_TABLE_ERR = Exception(
    'relation "public.feedback_posts" does not exist (code 42P01)'
)


class _Chain:
    """Chainable stand-in for a postgrest query builder: every method
    returns self, execute() yields the canned rows or raises."""

    def __init__(self, result=None, exc=None):
        self._result, self._exc = result, exc

    def __getattr__(self, _name):
        def _chain(*args, **kwargs):
            return self
        return _chain

    def execute(self):
        if self._exc:
            raise self._exc
        return type("R", (), {"data": self._result})()


class _FakeAdmin:
    def __init__(self, tables=None, exc=None):
        self._tables, self._exc = tables or {}, exc

    def table(self, name):
        if self._exc:
            return _Chain(exc=self._exc)
        return _Chain(result=self._tables.get(name, []))


def _fake_db(tables=None, exc=None):
    a = _FakeAdmin(tables, exc)
    return SimpleNamespace(admin=lambda: a, get_profile=lambda _uid: None)


@pytest.fixture(autouse=True)
def _bypass(monkeypatch):
    from app.config import settings
    import app.api.routes as routes

    monkeypatch.setattr(settings, "require_auth", False)
    if hasattr(routes, "limiter"):
        monkeypatch.setattr(routes.limiter, "enabled", False)
    yield


def _patch_db(monkeypatch, fake):
    import app.api.feedback_routes as fr
    monkeypatch.setattr(fr, "db", fake)


def _post(pid, title, votes_hint=0):
    return {
        "id": pid, "title": title, "body": "", "status": "open",
        "author_display": "Someone", "author_user_id": DEV_USER,
        "created_at": "2026-06-11T00:00:00+00:00",
    }


def test_list_sorts_by_votes_and_marks_my_vote(monkeypatch):
    tables = {
        "feedback_posts": [_post("p1", "older idea"), _post("p2", "popular idea")],
        "feedback_votes": [
            {"post_id": "p2", "voter_user_id": DEV_USER},
            {"post_id": "p2", "voter_user_id": "11111111-1111-1111-1111-111111111111"},
            {"post_id": "p1", "voter_user_id": "11111111-1111-1111-1111-111111111111"},
        ],
    }
    _patch_db(monkeypatch, _fake_db(tables))

    r = client.get("/api/v1/feedback")
    assert r.status_code == 200
    posts = r.json()["posts"]
    assert [p["id"] for p in posts] == ["p2", "p1"]
    assert posts[0]["votes"] == 2 and posts[0]["user_has_voted"] is True
    assert posts[1]["votes"] == 1 and posts[1]["user_has_voted"] is False


def test_list_empty_board(monkeypatch):
    _patch_db(monkeypatch, _fake_db({}))
    r = client.get("/api/v1/feedback")
    assert r.status_code == 200
    assert r.json() == {"posts": []}


def test_list_missing_table_returns_503_with_hint(monkeypatch):
    _patch_db(monkeypatch, _fake_db(exc=MISSING_TABLE_ERR))
    r = client.get("/api/v1/feedback")
    assert r.status_code == 503
    assert "004_feedback.sql" in r.json()["detail"]


def test_create_missing_table_returns_503_with_hint(monkeypatch):
    _patch_db(monkeypatch, _fake_db(exc=MISSING_TABLE_ERR))
    r = client.post("/api/v1/feedback", json={"title": "please add dark mode"})
    assert r.status_code == 503
    assert "004_feedback.sql" in r.json()["detail"]


def test_vote_missing_table_returns_503_with_hint(monkeypatch):
    _patch_db(monkeypatch, _fake_db(exc=MISSING_TABLE_ERR))
    r = client.post("/api/v1/feedback/p1/vote")
    assert r.status_code == 503
    assert "004_feedback.sql" in r.json()["detail"]
