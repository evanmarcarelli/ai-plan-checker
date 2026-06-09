"""Tests for the provision tree (#2) + amendment resolution.

All DB-free: build_provision_rows and apply_amendments are pure; resolve_provision
is exercised with the store monkeypatched.
"""
import pytest

from app.code_library import structure
from app.code_library.corpus_loader import CodeChunk
from app.code_library import amendments as A
from scripts.ingest.build_provisions import build_provision_rows


def _chunk(section, title, text="...", code="IBC", ver="2021"):
    return CodeChunk(chunk_id=f"{code}-{section}".lower(), code_name=code, code_short=code,
                     version=ver, section=section, title=title, category="building_safety",
                     text=text, jurisdictions=["*"])


# ── path helpers ─────────────────────────────────────────────

def test_ancestor_paths():
    assert structure.ancestor_paths("c10.s1004.s1004_1") == [
        "c10", "c10.s1004", "c10.s1004.s1004_1"]


@pytest.mark.parametrize("label,number", [
    ("c10", "10"), ("s1004", "1004"), ("s1004_1", "1004.1"), ("sr302_1", "r302.1"),
])
def test_path_label_to_number(label, number):
    assert structure.path_label_to_number(label) == number


# ── tree derivation ──────────────────────────────────────────

def test_build_provision_tree_materializes_ancestors():
    rows = build_provision_rows([_chunk("1004.1.1", "Areas Without Fixed Seating")])
    by_path = {r["path"]: r for r in rows}

    # Chapter + section + subsection + leaf all exist.
    assert set(by_path) == {"c10", "c10.s1004", "c10.s1004.s1004_1", "c10.s1004.s1004_1.s1004_1_1"}
    # Parent links chain correctly.
    assert by_path["c10"]["parent_path"] is None
    assert by_path["c10.s1004"]["parent_path"] == "c10"
    assert by_path["c10.s1004.s1004_1.s1004_1_1"]["parent_path"] == "c10.s1004.s1004_1"
    # Kinds + numbers.
    assert by_path["c10"]["kind"] == "chapter" and by_path["c10"]["heading"] == "Chapter 10"
    assert by_path["c10.s1004"]["number"] == "1004"
    # Leaf keeps its real heading + text; interior nodes have no text.
    leaf = by_path["c10.s1004.s1004_1.s1004_1_1"]
    assert leaf["heading"] == "Areas Without Fixed Seating" and leaf["text"] == "..."
    assert by_path["c10.s1004"]["text"] is None


def test_real_chunk_wins_over_derived_ancestor():
    # A chunk for 1004 AND a deeper chunk for 1004.1.1 → the 1004 node must
    # carry the real chunk's heading/text, not a derived placeholder.
    rows = build_provision_rows([
        _chunk("1004.1.1", "Exception"),
        _chunk("1004", "Occupant Load", text="real chapter-section text"),
    ])
    by_path = {r["path"]: r for r in rows}
    assert by_path["c10.s1004"]["heading"] == "Occupant Load"
    assert by_path["c10.s1004"]["text"] == "real chapter-section text"


# ── amendment resolution (pure) ──────────────────────────────

def test_replace_and_strike_and_add():
    base = "base text"
    rep = [{"op": "replace", "new_text": "LA text", "ordinance_cite": "LAMC 1",
            "needs_review": False}]
    assert A.apply_amendments(base, rep).text == "LA text"

    strike = [{"op": "strike", "ordinance_cite": "LAMC 2", "needs_review": False}]
    assert A.apply_amendments(base, strike).text is None

    add = [{"op": "add", "new_text": "extra", "ordinance_cite": "LAMC 3", "needs_review": False}]
    assert A.apply_amendments(base, add).text == "base text\nextra"


def test_needs_review_amendment_is_not_applied():
    # The human gate: an unreviewed amendment must never change the effective text.
    base = "base text"
    pending = [{"op": "replace", "new_text": "UNREVIEWED", "ordinance_cite": "LAMC X",
                "needs_review": True}]
    res = A.apply_amendments(base, pending)
    assert res.text == "base text" and res.applied == []


def test_effective_date_cutoff():
    base = "base"
    amds = [{"op": "replace", "new_text": "2025 text", "ordinance_cite": "O-25",
             "effective_date": "2025-01-01", "needs_review": False}]
    # A 2023 permit doesn't see a 2025 amendment.
    assert A.apply_amendments(base, amds, as_of="2023-06-01").text == "base"
    assert A.apply_amendments(base, amds, as_of="2026-01-01").text == "2025 text"


def test_later_ordinance_wins():
    base = "base"
    amds = [
        {"op": "replace", "new_text": "v1", "ordinance_cite": "O-1", "effective_date": "2022-01-01", "needs_review": False},
        {"op": "replace", "new_text": "v2", "ordinance_cite": "O-2", "effective_date": "2024-01-01", "needs_review": False},
    ]
    res = A.apply_amendments(base, amds)
    assert res.text == "v2" and res.applied == ["O-1", "O-2"]


# ── resolve_provision wired to the store ─────────────────────

def test_resolve_provision_merges_base_and_amendment(monkeypatch):
    from app.code_library import store
    monkeypatch.setattr(store, "fetch_provision",
                        lambda e, p: {"text": "base egress rule"})
    monkeypatch.setattr(store, "fetch_amendments",
                        lambda a, p: [{"op": "replace", "new_text": "LA egress rule",
                                       "ordinance_cite": "LAMC 91.1004", "needs_review": False}])
    res = A.resolve_provision("IBC:2021", "c10.s1004", "ca:los_angeles")
    assert res.text == "LA egress rule"
    assert res.base_text == "base egress rule"
    assert res.applied == ["LAMC 91.1004"]


def test_resolve_provision_base_only_when_no_amendments(monkeypatch):
    from app.code_library import store
    monkeypatch.setattr(store, "fetch_provision", lambda e, p: {"text": "base"})
    monkeypatch.setattr(store, "fetch_amendments", lambda a, p: [])
    res = A.resolve_provision("IBC:2021", "c10.s1004", "ca:los_angeles")
    assert res.text == "base" and res.applied == []
