"""Tests for the citation-grounded retrieval layer.

Builds a tiny synthetic corpus directly (no JSONL on disk) and verifies the
verify_and_ground() grading + supporting-quote extraction work end-to-end.
"""
from __future__ import annotations

import pytest

from app.code_library.citation_retrieval import (
    CitationQuality,
    GroundedCitation,
    MAX_QUOTE_CHARS,
    MIN_CLAIM_SUPPORT_TOKENS,
    _parent_section,
    find_supporting_text,
    lookup_with_context,
    verify_and_ground,
)
from app.code_library.corpus_loader import CodeChunk, CodeCorpus


def _build_corpus() -> CodeCorpus:
    """Tiny synthetic corpus exercising parent/child relationships and
    multiple codes."""
    c = CodeCorpus()
    c.add(CodeChunk(
        chunk_id="ibc-1006.3",
        code_name="International Building Code",
        code_short="IBC",
        version="2024",
        section="1006.3",
        title="Egress from stories",
        category="building_safety",
        jurisdictions=["*"],
        text=(
            "The means of egress system serving any story shall comply with "
            "Section 1006.3. Two exits or exit access doorways from any "
            "story or occupied roof shall be provided where one of the "
            "conditions listed in Section 1006.3.2 exists."
        ),
        tags=["egress", "stair"],
    ))
    c.add(CodeChunk(
        chunk_id="ibc-1006.3.2",
        code_name="International Building Code",
        code_short="IBC",
        version="2024",
        section="1006.3.2",
        title="Single exits",
        category="building_safety",
        jurisdictions=["*"],
        text=(
            "A single exit or access to a single exit shall be permitted "
            "from any story or occupied roof where the occupant load and "
            "exit access travel distance do not exceed the values in Table "
            "1006.3.2(1) or 1006.3.2(2)."
        ),
        tags=["egress", "exit"],
    ))
    c.add(CodeChunk(
        chunk_id="lamc-12.21",
        code_name="Los Angeles Municipal Code",
        code_short="LAMC",
        version="2024",
        section="12.21",
        title="General Provisions",
        category="zoning",
        jurisdictions=["CA:Los Angeles"],
        text=(
            "No building or structure shall be erected, reconstructed, "
            "structurally altered, enlarged, moved or maintained except in "
            "conformity with the regulations of this article. Yards and "
            "other open spaces shall not be reduced below the requirements "
            "of this chapter."
        ),
        tags=["zoning", "setback"],
    ))
    return c


# ─────────────────────────────────────────────────────────────────────────
# Parent-section helper
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("section, expected", [
    ("1006.3.2", "1006.3"),
    ("1006.3", "1006"),
    ("1006", None),
    ("12.21", "12"),
    ("R301.2", "R301"),
])
def test_parent_section(section, expected):
    assert _parent_section(section) == expected


# ─────────────────────────────────────────────────────────────────────────
# Quote extraction
# ─────────────────────────────────────────────────────────────────────────


def test_find_supporting_text_picks_overlapping_sentence():
    chunk_text = (
        "The minimum front setback shall be 25 feet. "
        "All exterior lighting shall be shielded downward. "
        "Maximum building height in the R1 zone is 30 feet."
    )
    quote = find_supporting_text(
        chunk_text, "front setback of twenty-five feet is required"
    )
    assert quote is not None
    assert "front setback" in quote
    assert "exterior lighting" not in quote  # picked the right sentence


def test_find_supporting_text_returns_none_when_no_overlap():
    chunk_text = "Photovoltaic systems shall comply with NFPA 70."
    quote = find_supporting_text(
        chunk_text, "swimming pools require a four-foot fence"
    )
    assert quote is None


def test_find_supporting_text_respects_char_cap():
    long_sentence = "The minimum front setback " + ("shall apply " * 100) + "consistently."
    quote = find_supporting_text(long_sentence, "front setback shall apply")
    assert quote is not None
    assert len(quote) <= MAX_QUOTE_CHARS


# ─────────────────────────────────────────────────────────────────────────
# Structural lookup
# ─────────────────────────────────────────────────────────────────────────


def test_lookup_with_context_returns_chunk_and_parent():
    corpus = _build_corpus()
    chunk, parent = lookup_with_context(corpus, "IBC 1006.3.2")
    assert chunk is not None and chunk.section == "1006.3.2"
    assert parent is not None and parent.section == "1006.3"


def test_lookup_with_context_handles_top_level_section():
    corpus = _build_corpus()
    chunk, parent = lookup_with_context(corpus, "IBC 1006.3")
    assert chunk is not None
    # 1006 doesn't exist in our corpus → parent is None
    assert parent is None


def test_lookup_with_context_unknown_citation():
    corpus = _build_corpus()
    chunk, parent = lookup_with_context(corpus, "IBC 9999.9")
    assert chunk is None and parent is None


# ─────────────────────────────────────────────────────────────────────────
# verify_and_ground — the public entry
# ─────────────────────────────────────────────────────────────────────────


def test_verify_and_ground_verified_when_claim_overlaps_section():
    corpus = _build_corpus()
    g = verify_and_ground(
        "IBC 1006.3.2",
        "A single exit is permitted only where occupant load and travel "
        "distance do not exceed Table 1006.3.2 values.",
        corpus=corpus,
    )
    assert g.quality is CitationQuality.VERIFIED
    assert g.verbatim_quote
    assert "single exit" in g.verbatim_quote.lower()
    assert g.parent_section_text  # parent 1006.3 was attached
    assert g.code_short == "IBC"
    assert g.section == "1006.3.2"


def test_verify_and_ground_section_only_when_claim_does_not_match():
    """The cited section exists but the claim is about an unrelated topic."""
    corpus = _build_corpus()
    g = verify_and_ground(
        "IBC 1006.3.2",
        "Swimming pools require a four-foot perimeter fence with self-latching gate.",
        corpus=corpus,
    )
    assert g.quality is CitationQuality.SECTION_ONLY
    assert g.verbatim_quote == ""
    assert not g.is_admissible


def test_verify_and_ground_unverified_when_section_missing():
    corpus = _build_corpus()
    g = verify_and_ground(
        "IBC 9999.9",
        "Mythical section that does not exist.",
        corpus=corpus,
    )
    assert g.quality is CitationQuality.UNVERIFIED
    assert not g.is_admissible
    assert g.section == "9999.9"
    assert g.code_short == "IBC"


def test_verify_and_ground_municipal_citation():
    corpus = _build_corpus()
    g = verify_and_ground(
        "LAMC 12.21",
        "No building or structure shall be erected except in conformity with the regulations.",
        corpus=corpus,
        state="CA",
        city="Los Angeles",
    )
    assert g.quality is CitationQuality.VERIFIED
    assert "no building" in g.verbatim_quote.lower()


def test_grounded_citation_is_admissible_for_verified_and_partial():
    g_verified = GroundedCitation(
        citation="IBC 1006",
        code_short="IBC",
        code_name="x",
        section="1006",
        quality=CitationQuality.VERIFIED,
    )
    g_partial = GroundedCitation(
        citation="IBC 1006",
        code_short="IBC",
        code_name="x",
        section="1006",
        quality=CitationQuality.PARTIAL,
    )
    g_section_only = GroundedCitation(
        citation="IBC 1006",
        code_short="IBC",
        code_name="x",
        section="1006",
        quality=CitationQuality.SECTION_ONLY,
    )
    assert g_verified.is_admissible
    assert g_partial.is_admissible
    assert not g_section_only.is_admissible


def test_min_claim_support_tokens_is_enforced():
    """A claim that shares only one or two trivial tokens with the chunk text
    should not produce a VERIFIED grading."""
    corpus = _build_corpus()
    # 'door' appears once; not enough significant-token overlap to verify
    g = verify_and_ground(
        "IBC 1006.3",
        "doorway",  # single significant token
        corpus=corpus,
    )
    # Bigram overlap is also too thin → SECTION_ONLY, not VERIFIED.
    assert g.quality is not CitationQuality.VERIFIED
