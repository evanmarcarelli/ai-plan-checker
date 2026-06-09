"""Tests for the code-table provider + seed (migration 008 code_table_cells).

Two guarantees that matter for a liability product:
  1. With the DB off, the provider returns the EXACT legacy hardcoded values —
     so moving to the provider changes no compliance result.
  2. The seed rows round-trip losslessly back through the provider to the
     original tables — so populating Postgres can't silently alter a limit.

All DB-free: the Postgres path is exercised with the fetch monkeypatched.
"""
import pytest

from app.code_library.deterministic import tables as T
from app.code_library.deterministic import table_store as TS
from app.code_library.deterministic import checkers
from scripts.ingest.tables_to_postgres import build_rows


@pytest.fixture(autouse=True)
def _fresh_cache():
    TS.clear_cache()
    yield
    TS.clear_cache()


# ── 1. Fallback parity: DB off -> exact legacy values ────────

def test_fallback_matches_hardcoded_tables():
    # Default CODE_STORE=disk -> provider returns the tables.py dicts verbatim.
    assert TS.t506_2() == T.IBC_T506_2
    assert TS.t504_4() == T.IBC_T504_4
    assert TS.min_exits_by_load() == T.MIN_EXITS_BY_LOAD
    assert TS.fixture_ratios() == T.FIXTURE_RATIOS
    assert TS.high_rise_ft() == T.HIGH_RISE_FT


# ── 2. Seed -> provider round-trip is lossless ───────────────

def test_seed_rows_roundtrip_through_provider(monkeypatch):
    rows = build_rows()

    def fake_fetch(table_id, adoption_id=None):
        return [r for r in rows if r["table_id"] == table_id and r["adoption_id"] is None]

    monkeypatch.setattr(TS, "_use_db", lambda: True)
    from app.code_library import store
    monkeypatch.setattr(store, "fetch_table_cells", fake_fetch)
    TS.clear_cache()

    assert TS.t506_2() == T.IBC_T506_2
    assert TS.t504_4() == T.IBC_T504_4
    assert TS.min_exits_by_load() == T.MIN_EXITS_BY_LOAD
    assert TS.fixture_ratios() == T.FIXTURE_RATIOS
    assert TS.high_rise_ft() == T.HIGH_RISE_FT


def test_build_rows_encodes_sentinels_and_numbers():
    rows = build_rows()
    by = {(r["table_id"], r["row_key"], r["col_key"]): r for r in rows}
    # numeric cell
    a2_vb = by[(TS.T506_2_ID, "A-2", "V-B")]
    assert a2_vb["value_num"] == 6000 and a2_vb["value_sentinel"] is None
    assert a2_vb["unit"] == "sf"
    # sentinel cell (Not Permitted)
    i2_iib = by[(TS.T506_2_ID, "I-2", "II-B")]
    assert i2_iib["value_sentinel"] == "NP" and i2_iib["value_num"] is None
    # unbounded exits bucket encodes as 'inf'
    assert any(r["table_id"] == TS.MIN_EXITS_ID and r["row_key"] == "inf" for r in rows)


# ── 3. DB path reconstruction details ────────────────────────

def test_db_path_reconstructs_matrix_and_prefers_adoption(monkeypatch):
    # Base says A-2/V-B = 6000; an LA amendment raises it to 7000.
    fake = {
        TS.T506_2_ID: [
            {"adoption_id": None, "row_key": "A-2", "col_key": "V-B",
             "value_num": 6000, "value_sentinel": None},
            {"adoption_id": "ca:los_angeles", "row_key": "A-2", "col_key": "V-B",
             "value_num": 7000, "value_sentinel": None},
        ],
    }

    def fake_fetch(table_id, adoption_id=None):
        rows = fake.get(table_id, [])
        scoped = [r for r in rows if adoption_id and r["adoption_id"] == adoption_id]
        base = [r for r in rows if r["adoption_id"] is None]
        return scoped or base

    monkeypatch.setattr(TS, "_use_db", lambda: True)
    from app.code_library import store
    monkeypatch.setattr(store, "fetch_table_cells", fake_fetch)
    TS.clear_cache()

    assert TS.t506_2()["A-2"]["V-B"] == 6000               # base
    assert TS.t506_2(adoption_id="ca:los_angeles")["A-2"]["V-B"] == 7000  # amended


# ── 4. Checkers still behave identically through the provider ─

def test_checkers_use_provider_values():
    # A-2 / V-B tabular area is 6000 sf.
    assert checkers.check_allowable_area("A-2", "V-B", 5000).status == "pass"
    assert checkers.check_allowable_area("A-2", "V-B", 7000).status == "fail"
    # I-2 not permitted in II-B.
    assert checkers.check_allowable_area("I-2", "II-B", 1000).status == "fail"
    # Min exits: OL 600 -> 3 required.
    assert checkers.required_min_exits(600) == 3
    assert checkers.required_min_exits(100) == 2
    # High-rise threshold 75 ft.
    assert checkers.is_high_rise(80) is True
    assert checkers.is_high_rise(70) is False
