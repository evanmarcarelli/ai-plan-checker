"""Tests for the structured-corpus foundation (migration 008 + store + loader).

All DB-free: the structure helpers are pure, CodeChunk back-compat is a
constructor check, and the Postgres store is exercised with the client
monkeypatched so nothing touches Supabase.
"""
import pytest

from app.code_library import structure
from app.code_library.corpus_loader import CodeChunk, CodeCorpus, CodeRetriever


# ─────────────────────────────────────────────────────────────
# structure.section_to_ltree — chapter inheritance is the key property
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("section,expected", [
    ("1004.1.1", "c10.s1004.s1004_1.s1004_1_1"),
    ("506.2",    "c5.s506.s506_2"),
    ("302.1",    "c3.s302.s302_1"),
    ("1004",     "c10.s1004"),
])
def test_section_to_ltree_numeric_has_chapter(section, expected):
    assert structure.section_to_ltree(section) == expected


def test_section_to_ltree_letter_led_has_no_numeric_chapter():
    # Residential 'R302.1' must not invent a chapter from the digits.
    p = structure.section_to_ltree("R302.1")
    assert p == "sr302.sr302_1"
    assert not p.startswith("c")


def test_section_to_ltree_nonstandard_is_safe_label():
    p = structure.section_to_ltree("P/GI 2026-006")
    assert p == "sp_gi_2026_006"          # valid ltree label, no spaces/slashes


def test_section_to_ltree_empty():
    assert structure.section_to_ltree("") == "s_unknown"


def test_ancestor_containment_holds():
    # The whole point: the exception's path is a descendant of the section's.
    sec = structure.section_to_ltree("1004.1")
    exc = structure.section_to_ltree("1004.1.1")
    assert exc.startswith(sec + ".")       # ltree '@>' ancestor relationship


# ─────────────────────────────────────────────────────────────
# parent_section / adoption id derivation
# ─────────────────────────────────────────────────────────────

def test_parent_section():
    assert structure.parent_section("1004.1.1") == "1004.1"
    assert structure.parent_section("506") is None


@pytest.mark.parametrize("tag,expected", [
    ("*", None),
    ("CA", "ca"),
    ("CA:Los Angeles", "ca:los_angeles"),
    ("CA:Altadena", "ca:altadena"),
])
def test_normalize_adoption_id(tag, expected):
    assert structure.normalize_adoption_id(tag) == expected


def test_adoption_id_prefers_most_specific():
    assert structure.adoption_id_for_chunk(["*"]) is None
    assert structure.adoption_id_for_chunk(["CA", "CA:Los Angeles"]) == "ca:los_angeles"
    assert structure.adoption_id_for_chunk(["CA"]) == "ca"


def test_context_header_breadcrumb():
    h = structure.build_context_header(
        "IBC", "2021",
        ancestors=[("1004", "Occupant Load")],
        section="1004.1.1", heading="Areas Without Fixed Seating",
    )
    assert "2021 IBC" in h
    assert "§1004 Occupant Load" in h
    assert "§1004.1.1 Areas Without Fixed Seating" in h


# ─────────────────────────────────────────────────────────────
# CodeChunk back-compat: existing JSONL (no structured fields) still loads
# ─────────────────────────────────────────────────────────────

def test_codechunk_loads_without_structured_fields():
    c = CodeChunk(chunk_id="ibc-1004.1.1", code_name="IBC", code_short="IBC",
                  version="2021", section="1004.1.1", category="building_safety",
                  text="...", jurisdictions=["*"])
    assert c.path is None and c.adoption_id is None
    assert c.source_tier == "unspecified" and c.license_status == "review"


def test_codechunk_accepts_structured_fields():
    c = CodeChunk(chunk_id="x", code_name="IBC", code_short="IBC", version="2021",
                  section="1004.1.1", category="building_safety", text="...",
                  path="c10.s1004.s1004_1.s1004_1_1", adoption_id="ca:los_angeles",
                  license_status="edict")
    assert c.adoption_id == "ca:los_angeles"
    assert c.license_status == "edict"


# ─────────────────────────────────────────────────────────────
# Retriever adoption scoping: base + local amendment can't both match
# ─────────────────────────────────────────────────────────────

def test_retriever_adoption_scope_excludes_other_jurisdictions():
    corpus = CodeCorpus()
    corpus.add(CodeChunk(chunk_id="base", code_name="IBC", code_short="IBC",
                         version="2021", section="1004.1", category="building_safety",
                         text="occupant load factor base rule", adoption_id=None))
    corpus.add(CodeChunk(chunk_id="la", code_name="IBC", code_short="IBC",
                         version="2021", section="1004.1", category="building_safety",
                         text="occupant load factor LA amended rule",
                         adoption_id="ca:los_angeles"))
    corpus.add(CodeChunk(chunk_id="ny", code_name="IBC", code_short="IBC",
                         version="2021", section="1004.1", category="building_safety",
                         text="occupant load factor NY amended rule",
                         adoption_id="ny:new_york"))
    r = CodeRetriever(corpus)
    hits = r.search("occupant load factor", adoption_id="ca:los_angeles", min_score=0.0, k=10)
    ids = {c.chunk_id for c in hits}
    assert "ny" not in ids                 # other jurisdiction is excluded
    assert ids <= {"base", "la"}           # only base + the matching adoption


# ─────────────────────────────────────────────────────────────
# store.py degrades gracefully when Supabase/migration is absent
# ─────────────────────────────────────────────────────────────

def test_store_returns_empty_when_client_unavailable(monkeypatch):
    from app.code_library import store
    monkeypatch.setattr(store, "_admin", lambda: None)
    assert store.corpus_in_postgres() is False
    assert store.fetch_all_chunks() == []
    assert store.search("egress width") == []
    assert store.ancestors("ca:los_angeles", "c10.s1004") == []
