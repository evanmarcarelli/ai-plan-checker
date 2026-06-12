"""Coastal Act + Malibu LIP corpus layers and their scoping.

Covers: the LIP PDF parser (pure function, synthetic text), the curated
Coastal Act target list, layer-key scoping of the ingested chunks (coastal
chunks must NOT leak into non-coastal retrievals), and the workflow helper
that activates the coastal layer from the GIS overlay verdict.
"""
import pytest

from app.agents.workflow import _maybe_add_coastal_layer
from app.code_library.adoption.resolver import ResolvedStack
from app.code_library.corpus_loader import get_corpus
from app.code_library.ingest.ca_leginfo import COASTAL_TARGET_SECTIONS
from app.code_library.ingest.malibu_lip import parse_lip_text


# ---------------------------------------------------------------- parser

SYNTHETIC_LIP = """
TABLE OF CONTENTS
4.5 ESHA Buffer.. 12

CHAPTER 4ENVIRONMENTALLY SENSITIVE HABITAT AREAS

4.5 Buffer Standards
City of Malibu LCP Local Implementation Plan
Page 12
A buffer shall be provided around all ESHA sufficient to prevent significant
degradation of the habitat. The buffer shall be a minimum of 100 feet from the
outer edge of the habitat area unless a site-specific analysis demonstrates
otherwise, in accordance with the standards of this chapter.

4.5.1 Purpose
This section sets forth the standards applicable to development adjacent to
environmentally sensitive habitat areas in order to prevent impacts that would
significantly degrade those areas, consistent with Section 30240 of the
Coastal Act and the certified Land Use Plan.
"""


def test_parse_lip_synthetic_text():
    sections = parse_lip_text(SYNTHETIC_LIP, source_url="test://lip")
    nums = [s.section_number for s in sections]
    assert nums == ["4.5", "4.5.1"]

    buffer_sec = sections[0]
    # Page furniture stripped from the body, real text retained.
    assert "minimum of 100 feet" in buffer_sec.text
    assert "Page 12" not in buffer_sec.text
    assert "City of Malibu LCP Local Implementation Plan" not in buffer_sec.text
    # Chapter header became the breadcrumb, not a section of its own.
    assert any("Chapter 4" in b for b in buffer_sec.breadcrumb)
    # The dot-leader TOC line did NOT produce a phantom section (only two total).
    assert len(sections) == 2


def test_parse_lip_skips_short_fragments():
    text = "3.6 Residential Development Standards\nSee Chapter 4.\n"
    assert parse_lip_text(text) == []


# ------------------------------------------------------------ target list

def test_coastal_target_sections_curation():
    laws = {law for law, *_ in COASTAL_TARGET_SECTIONS}
    assert laws == {"PRC"}
    sections = {sec for _, sec, *_ in COASTAL_TARGET_SECTIONS}
    # The two sections every coastal plan check leans on must be present.
    assert {"30600", "30253"} <= sections


# ----------------------------------------------------- ingested corpus

@pytest.fixture(scope="module")
def corpus():
    return get_corpus()


def test_coastal_act_chunks_scoped_to_coastal_layer(corpus):
    coastal = [c for c in corpus.chunks if "CA:Coastal" in c.jurisdictions]
    assert coastal, "ca_coastal_act.jsonl missing from corpus"
    sample = coastal[0]
    # Not visible to a plain CA (non-coastal) scope...
    assert not sample.in_layers(["*", "CA", "CA:Los Angeles"])
    # ...visible once the coastal layer is activated.
    assert sample.in_layers(["*", "CA", "CA:Los Angeles", "CA:Coastal"])


def test_malibu_lip_chunks_present_and_scoped(corpus):
    lip = [c for c in corpus.chunks if c.code_short == "MALIBU-LIP"]
    assert len(lip) > 50, "LIP ingest looks incomplete"
    assert all(c.jurisdictions == ["CA:Malibu"] for c in lip)
    assert all(c.license_status == "edict" for c in lip)
    # ESHA buffer standards made it in — the most-cited coastal overlay rule.
    assert any("4.5" == c.section or c.section.startswith("4.5.") for c in lip)


# --------------------------------------------- adapter layer-keys path

def test_adapter_honors_enriched_layer_keys(corpus):
    """The dynamic CA:Coastal key only exists on the workflow's enriched stack —
    get_applicable_codes must use it verbatim instead of re-resolving (which
    would silently drop it and keep coastal chunks out of reviewer prompts)."""
    from app.code_library.adapter import CorpusCodeSource
    src = CorpusCodeSource()

    base = src.get_applicable_codes(
        state="CA", city="Los Angeles", county="Los Angeles",
        layer_keys=["*", "CA", "CA:Los Angeles"],
    )
    enriched = src.get_applicable_codes(
        state="CA", city="Los Angeles", county="Los Angeles",
        layer_keys=["*", "CA", "CA:Los Angeles", "CA:Coastal"],
    )
    base_prc = {r.code_id for r in base if r.code_id.startswith("PRC 30")}
    enriched_prc = {r.code_id for r in enriched if r.code_id.startswith("PRC 30")}
    assert not base_prc, "Coastal Act leaked into a non-coastal scope"
    assert "PRC 30600" in enriched_prc and "PRC 30253" in enriched_prc


# ------------------------------------------------------ workflow helper

def _stack(keys):
    return ResolvedStack(matched_id="x", level="city", corpus_layer_keys=keys)


def test_coastal_layer_added_on_gis_hit():
    stack = _stack(["*", "CA", "CA:Los Angeles"])
    ctx = {"overlays": {"coastal": {"in_zone": True}}}
    assert _maybe_add_coastal_layer(stack, ctx) is True
    assert stack.corpus_layer_keys[-1] == "CA:Coastal"


def test_coastal_layer_not_duplicated():
    stack = _stack(["*", "CA", "CA:Malibu", "CA:Coastal"])
    ctx = {"overlays": {"coastal": {"in_zone": True}}}
    assert _maybe_add_coastal_layer(stack, ctx) is False
    assert stack.corpus_layer_keys.count("CA:Coastal") == 1


def test_coastal_layer_untouched_without_hit():
    stack = _stack(["*", "CA"])
    assert _maybe_add_coastal_layer(stack, None) is False
    assert _maybe_add_coastal_layer(stack, {"overlays": {"coastal": {"in_zone": False}}}) is False
    assert _maybe_add_coastal_layer(None, {"overlays": {"coastal": {"in_zone": True}}}) is False
    assert stack.corpus_layer_keys == ["*", "CA"]
