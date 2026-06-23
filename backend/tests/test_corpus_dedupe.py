"""Tests for chunk_id dedupe at corpus load (corpus_loader._dedupe_chunks).

The corpus had two real duplicate classes the dedupe must handle without ever
dropping authoritative building-code text:
  * the same provision ingested twice — a hand-authored ADA seed AND the
    official gov text (different source_tier);
  * a malformed re-ingest where `text` is a fragment (a page number) colliding
    with the real section (same source_tier, much shorter text).
Legitimately distinct chunk_ids (a long section split into many chunks) must be
left completely untouched.
"""
from __future__ import annotations

from app.code_library.corpus_loader import CodeChunk, _dedupe_chunks


def _chunk(chunk_id: str, *, text: str, tier: str = "unspecified", section: str = "1.1") -> CodeChunk:
    return CodeChunk(
        chunk_id=chunk_id,
        code_name="X",
        code_short="X",
        version="1",
        section=section,
        category="building_safety",
        jurisdictions=["*"],
        text=text,
        source_tier=tier,
    )


def test_official_gov_supersedes_seed_regardless_of_order():
    """ADA case: the official_gov copy must win over an unspecified-tier seed
    even when the seed is loaded first AND happens to be longer."""
    seed = _chunk("ada-404.2.3", text="seed text that is intentionally quite long " * 5,
                  tier="unspecified")
    gov = _chunk("ada-404.2.3", text="official short text", tier="official_gov")
    result = _dedupe_chunks([seed, gov])
    assert len(result) == 1
    assert result[0].source_tier == "official_gov"


def test_same_tier_collision_keeps_longer_text():
    """CRC case: a junk fragment ('5') and the real provision share a chunk_id
    and source_tier ('licensed'); the fuller text must survive."""
    junk = _chunk("crc-r101.2.1", text="5", tier="licensed")
    real = _chunk("crc-r101.2.1", text="Provisions in the appendices shall not apply "
                                        "unless specifically adopted.", tier="licensed")
    # junk first (as it is on disk, lines 1-7) — order must not matter.
    result = _dedupe_chunks([junk, real])
    assert len(result) == 1
    assert result[0].text.startswith("Provisions in the appendices")


def test_distinct_chunk_ids_are_untouched():
    """A long section split into many chunks keeps distinct chunk_ids and must
    pass through unchanged — dedupe is by chunk_id, never by citation/section."""
    chunks = [_chunk(f"t24-100.1#{i}", text=f"part {i} of section 100.1", section="100.1")
              for i in range(5)]
    result = _dedupe_chunks(chunks)
    assert len(result) == 5
    assert [c.chunk_id for c in result] == [c.chunk_id for c in chunks]


def test_first_seen_wins_on_full_tie_and_order_is_stable():
    a = _chunk("x-1", text="same length text", tier="licensed")
    b = _chunk("x-1", text="same length text", tier="licensed")
    c = _chunk("x-2", text="other", tier="licensed")
    result = _dedupe_chunks([a, c, b])
    assert [r.chunk_id for r in result] == ["x-1", "x-2"]
    assert result[0] is a  # first-seen kept on an exact tie


def test_chunk_id_match_is_case_insensitive():
    upper = _chunk("ADA-206.2.1", text="x", tier="unspecified")
    lower = _chunk("ada-206.2.1", text="fuller official text", tier="official_gov")
    result = _dedupe_chunks([upper, lower])
    assert len(result) == 1
    assert result[0].source_tier == "official_gov"
