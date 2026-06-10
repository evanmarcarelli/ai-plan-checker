"""Tests for the silent-fallback hardening:

  1. jurisdiction scope FALLS OPEN — a degraded resolver scope never drops a code
  2. table_store WARNS LOUDLY when CODE_STORE=postgres but a table is empty
  3. the benchmark aggregate REFUSES a verdict below the min sample size
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.code_library.corpus_loader import CodeChunk, CodeCorpus, CodeRetriever


def _chunk(cid, juris, text="egress width minimum 44 inches"):
    return CodeChunk(chunk_id=cid, code_name="IBC", code_short="IBC", version="2021",
                     section=cid, category="building_safety", text=text, jurisdictions=juris)


# ── 1. fall-open scoping ─────────────────────────────────────

def test_retriever_fall_open_never_drops_a_code():
    """If the resolver missed the city (degraded layers ['*','CA']) but the plan
    IS in LA, an LA-tagged code must still be returned via applies_to — a missed
    code is the liability we're guarding against."""
    corpus = CodeCorpus()
    corpus.add(_chunk("base", ["*"]))
    corpus.add(_chunk("ca", ["CA"]))
    corpus.add(_chunk("la", ["CA:Los Angeles"]))
    corpus.add(_chunk("ny", ["NY"]))
    r = CodeRetriever(corpus)

    # Degraded layer set (resolver fell to state) + the real jurisdiction.
    hits = {c.chunk_id for c in r.search("egress width", layer_keys=["*", "CA"],
                                         state="CA", city="Los Angeles", min_score=-1e9, k=10)}
    assert "la" in hits, "fall-open must recover the LA code the degraded layers dropped"
    assert "ny" not in hits, "but still must not leak another jurisdiction"


def test_all_for_category_fall_open():
    corpus = CodeCorpus()
    corpus.add(_chunk("la", ["CA:Los Angeles"]))
    r = CodeRetriever(corpus)
    got = {c.chunk_id for c in r.all_for_category("building_safety",
                                                  state="CA", city="Los Angeles",
                                                  layer_keys=["*", "CA"])}
    assert "la" in got


# ── 2. table_store loud fallback ─────────────────────────────

def test_table_store_warns_when_db_on_but_empty(monkeypatch):
    from app.code_library.deterministic import table_store as TS, tables as T
    from app.code_library import store

    warned = []
    monkeypatch.setattr(TS, "_use_db", lambda: True)
    monkeypatch.setattr(store, "fetch_table_cells", lambda tid, aid=None: [])
    monkeypatch.setattr(TS.logger, "warning", lambda *a, **k: warned.append(str(a[0])))
    TS.clear_cache()
    try:
        res = TS.t506_2()
        assert res == T.IBC_T506_2                    # fell back to the hardcoded dict
        assert any("no rows in code_table_cells" in w for w in warned)
    finally:
        TS.clear_cache()


def test_table_store_silent_in_disk_mode(monkeypatch):
    # Disk mode (the default) must NOT warn — falling back is expected there.
    from app.code_library.deterministic import table_store as TS
    warned = []
    monkeypatch.setattr(TS, "_use_db", lambda: False)
    monkeypatch.setattr(TS.logger, "warning", lambda *a, **k: warned.append(str(a[0])))
    TS.clear_cache()
    try:
        TS.t506_2()
        assert warned == []
    finally:
        TS.clear_cache()


# ── 3. benchmark min-n verdict guard ─────────────────────────

@dataclass
class _Score:
    tp: int = 0; fp: int = 0; fn: int = 0
    critical_tp: int = 0; critical_fn: int = 0
    forbidden_hits: int = 0; cited_in_corpus: int = 0; total_findings: int = 0


def test_aggregate_flags_insufficient_data():
    from benchmarks import stats as S
    agg = S.aggregate([_Score(tp=1, critical_tp=1, cited_in_corpus=1, total_findings=1)])
    assert agg["sufficient"] is False
    assert "INSUFFICIENT DATA" in S.format_aggregate(agg)


def test_aggregate_sufficient_with_enough_data():
    from benchmarks import stats as S
    cases = [_Score(tp=2, critical_tp=2, cited_in_corpus=2, total_findings=2) for _ in range(25)]
    agg = S.aggregate(cases)                 # 25 cases, 50 critical findings
    assert agg["sufficient"] is True
    assert "INSUFFICIENT DATA" not in S.format_aggregate(agg)
