"""Tests for app.services.plan_library — dedupe, revisions, sheet rows."""
from typing import Any, Dict, List, Optional

import pytest

from app.models.schemas import ExtractedPlanData, PlanType
from app.services import plan_library


# ── fakes ─────────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, db: "_FakeSupabase", name: str):
        self._db = db
        self._name = name
        self._filters: Dict[str, Any] = {}
        self._insert_payload = None

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def update(self, payload):
        self._insert_payload = ("update", payload)
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        rows = self._db.tables.setdefault(self._name, [])
        if self._insert_payload is not None and not isinstance(self._insert_payload, tuple):
            payload = self._insert_payload
            inserted = payload if isinstance(payload, list) else [payload]
            out = []
            for p in inserted:
                row = dict(p)
                row.setdefault("id", f"{self._name}-{len(rows) + 1}")
                rows.append(row)
                out.append(row)
            return type("R", (), {"data": out})()
        # select path with eq filters
        data = [
            r for r in rows
            if all(r.get(k) == v for k, v in self._filters.items())
        ]
        return type("R", (), {"data": data})()


class _FakeSupabase:
    def __init__(self):
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        self.rpc_results: Dict[str, List[Dict[str, Any]]] = {}
        self.rpc_calls: List[tuple] = []

    def table(self, name):
        return _FakeQuery(self, name)

    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        result = self.rpc_results.get(fn, [])
        return type("Q", (), {"execute": lambda _s: type("R", (), {"data": result})()})()


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _FakeSupabase()
    monkeypatch.setattr(plan_library.db, "admin", lambda: fake)
    updates: List[tuple] = []
    monkeypatch.setattr(
        plan_library.db, "update_job", lambda job_id, fields: updates.append((job_id, fields))
    )
    fake.job_updates = updates
    return fake


def _plan_data(**overrides) -> ExtractedPlanData:
    base = dict(
        file_hash="abc123",
        page_count=3,
        project_name="Test Project",
        project_address="123 Main St, Pasadena, CA",
        occupancy_type="B",
        construction_type="V-B",
        plan_type=PlanType.COMMERCIAL,
        raw_text_by_page={1: "COVER " * 10, 2: "PLAN " * 10, 3: "OCR page\n--- OCR (Textract) ---\nmore"},
        sheet_index=[
            {"page_number": 1, "sheet_number": "T-1.0", "sheet_title": "TITLE",
             "discipline": "general", "category": "building_safety",
             "source": "title_block", "confidence": 0.9},
            {"page_number": 2, "sheet_number": "A-1.0", "sheet_title": "FLOOR PLAN",
             "discipline": "architectural", "category": "building_safety",
             "source": "title_block", "confidence": 0.85},
            {"page_number": 3, "sheet_number": None, "sheet_title": None,
             "discipline": None, "category": None, "source": None, "confidence": 0.0},
            {"page_number": None, "sheet_number": "S-1", "sheet_title": "FOUNDATION",
             "discipline": "structural", "category": "building_safety",
             "source": "index_only", "confidence": 0.5},
        ],
    )
    base.update(overrides)
    return ExtractedPlanData(**base)


# ── tests ─────────────────────────────────────────────────────────────


def test_persist_creates_document_and_sheets(fake_db):
    doc_id = plan_library.persist_plan_document("job-1", "user-1", _plan_data())
    assert doc_id is not None

    docs = fake_db.tables["plan_documents"]
    assert len(docs) == 1
    assert docs[0]["file_hash"] == "abc123"
    assert docs[0]["project_address"] == "123 Main St, Pasadena, CA"
    assert docs[0]["revision_of"] is None

    sheets = fake_db.tables["plan_sheets"]
    # 3 pages + 1 index-only sheet
    assert len(sheets) == 4
    page2 = next(s for s in sheets if s["page_number"] == 2)
    assert page2["sheet_number"] == "A-1.0"
    assert page2["discipline"] == "architectural"
    page3 = next(s for s in sheets if s["page_number"] == 3)
    assert page3["used_ocr"] is True
    idx_only = next(s for s in sheets if s["page_number"] is None)
    assert idx_only["sheet_number"] == "S-1"
    assert idx_only["source"] == "index_only"

    # Job linked back to the corpus.
    assert fake_db.job_updates and fake_db.job_updates[0][1]["file_hash"] == "abc123"


def test_persist_dedupes_same_hash(fake_db):
    first = plan_library.persist_plan_document("job-1", "user-1", _plan_data())
    second = plan_library.persist_plan_document("job-2", "user-1", _plan_data())
    assert first == second
    assert len(fake_db.tables["plan_documents"]) == 1
    # Sheets are not duplicated on the dedupe path.
    assert len(fake_db.tables["plan_sheets"]) == 4
    # Both jobs got linked.
    assert len(fake_db.job_updates) == 2


def test_persist_chains_revisions(fake_db):
    plan_library.persist_plan_document("job-1", "user-1", _plan_data())
    prior_id = fake_db.tables["plan_documents"][0]["id"]
    # The RPC returns the prior doc as a revision candidate.
    fake_db.rpc_results["find_plan_revision_candidates"] = [{"id": prior_id}]

    plan_library.persist_plan_document(
        "job-2", "user-1", _plan_data(file_hash="def456")
    )
    docs = fake_db.tables["plan_documents"]
    assert len(docs) == 2
    assert docs[1]["revision_of"] == prior_id


def test_persist_skips_without_hash(fake_db):
    assert plan_library.persist_plan_document("job-1", "user-1", _plan_data(file_hash=None)) is None
    assert "plan_documents" not in fake_db.tables or not fake_db.tables["plan_documents"]


def test_persist_never_raises_on_db_failure(monkeypatch):
    def boom():
        raise RuntimeError("supabase down")
    monkeypatch.setattr(plan_library.db, "admin", boom)
    assert plan_library.persist_plan_document("job-1", "user-1", _plan_data()) is None


def test_search_sheets_calls_rpc(fake_db):
    fake_db.rpc_results["search_plan_sheets"] = [{"sheet_number": "A-1.0"}]
    rows = plan_library.search_sheets("user-1", "type v-b", disciplines=["architectural"])
    assert rows == [{"sheet_number": "A-1.0"}]
    fn, params = fake_db.rpc_calls[-1]
    assert fn == "search_plan_sheets"
    assert params["p_user_id"] == "user-1"
    assert params["p_disciplines"] == ["architectural"]


def test_search_sheets_empty_on_failure(monkeypatch):
    def boom():
        raise RuntimeError("rpc missing")
    monkeypatch.setattr(plan_library.db, "admin", boom)
    assert plan_library.search_sheets("user-1", "anything") == []
