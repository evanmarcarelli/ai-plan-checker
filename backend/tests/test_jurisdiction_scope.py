"""Tests for resolver-driven jurisdiction scoping (#3).

Retrieval is now scoped by the adoption resolver's corpus_layer_keys instead of
ad-hoc chunk-level applies_to(). These lock in:
  - the resolver emits the layer keys the chunks are actually tagged with;
  - a chunk applies iff it's in those layers ('*' base always applies);
  - an LA-scoped query excludes other-jurisdiction chunks but keeps base+state;
  - CorpusCodeSource end-to-end scopes the real corpus correctly.
"""
import pytest

from app.code_library.corpus_loader import CodeChunk, CodeCorpus, CodeRetriever
from app.code_library.adoption.resolver import get_resolver
from app.code_library.adapter import CorpusCodeSource


def _chunk(cid, juris, text="egress width minimum 44 inches", cat="building_safety"):
    return CodeChunk(chunk_id=cid, code_name="IBC", code_short="IBC", version="2021",
                     section=cid, category=cat, text=text, jurisdictions=juris)


# ── resolver bridge: keys match the corpus tag vocabulary ────

def test_resolver_emits_corpus_layer_keys_for_la():
    keys = get_resolver().resolve("CA", None, "Los Angeles").corpus_layer_keys
    assert "*" in keys and "CA" in keys and "CA:Los Angeles" in keys


def test_resolver_state_only_excludes_city_layer():
    keys = get_resolver().resolve("CA", None, None).corpus_layer_keys
    assert "*" in keys and "CA" in keys
    assert "CA:Los Angeles" not in keys


# ── in_layers semantics ──────────────────────────────────────

def test_in_layers_base_always_applies():
    assert _chunk("x", ["*"]).in_layers(["*", "CA"]) is True
    assert _chunk("x", ["*"]).in_layers([]) is True


def test_in_layers_excludes_other_jurisdiction():
    la = _chunk("x", ["CA:Los Angeles"])
    assert la.in_layers(["*", "CA", "CA:Los Angeles"]) is True
    assert la.in_layers(["*", "CA"]) is False           # state-only plan
    assert la.in_layers(["*", "NY"]) is False           # different state


# ── retriever scoping ────────────────────────────────────────

def test_retriever_layer_keys_scope():
    corpus = CodeCorpus()
    corpus.add(_chunk("base", ["*"]))
    corpus.add(_chunk("ca", ["CA"]))
    corpus.add(_chunk("la", ["CA:Los Angeles"]))
    corpus.add(_chunk("ny", ["NY"]))
    r = CodeRetriever(corpus)

    # min_score floor disabled: this test isolates jurisdiction filtering from
    # BM25 relevance (identical docs give negative IDF, irrelevant here).
    la_hits = {c.chunk_id for c in r.search("egress width", layer_keys=["*", "CA", "CA:Los Angeles"],
                                            min_score=-1e9, k=10)}
    assert la_hits == {"base", "ca", "la"}              # NY excluded

    state_hits = {c.chunk_id for c in r.search("egress width", layer_keys=["*", "CA"],
                                               min_score=-1e9, k=10)}
    assert state_hits == {"base", "ca"}                 # LA + NY excluded


# ── end-to-end through CorpusCodeSource on the real corpus ───

def test_corpus_source_scopes_la_vs_other_city():
    cs = CorpusCodeSource()
    la = cs.get_applicable_codes("CA", "Los Angeles")
    other = cs.get_applicable_codes("CA", "Fresno")

    la_ids = {r.code_id for r in la}
    other_ids = {r.code_id for r in other}

    # LADBS bulletins are tagged CA:Los Angeles — present for LA, absent elsewhere.
    la_only = {r.code_id for r in la if r.code_id.startswith("LADBS")}
    assert la_only, "expected LA-specific LADBS items for a Los Angeles plan"
    assert not (la_only & other_ids), "LA-only items must not leak into another city"
    # Base + state codes are shared (non-empty intersection).
    assert la_ids & other_ids, "base/state codes should apply to both"
