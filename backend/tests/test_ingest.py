"""Tests for the code corpus ingest pipeline.

Pure-Python and HTTP-mocked. No live network. The fixture HTML below
mirrors codelibrary.amlegal.com's current layout closely enough to catch
parser regressions; when the live site drifts we update the fixture too.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.code_library.ingest.base import IngestTarget, RawSection
from app.code_library.ingest.chunker import (
    SOFT_MAX_CHARS, chunk_section, classify_category,
)


# ─────────────────────────────────────────────────────────────
# Category classifier
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title, crumb, text, expected", [
    ("Hillside Setbacks", ["Title 17 Zoning"], "see lot coverage", "zoning"),
    ("Sprinkler systems", ["Title 9 Fire"], "NFPA 13", "fire"),
    ("GFCI protection", ["Electrical"], "bathrooms, kitchens", "electrical"),
    ("Backflow prevention", ["Plumbing"], "atmospheric vacuum breaker", "plumbing"),
    ("Combustion air", ["Mechanical"], "fuel-fired appliances", "mechanical"),
    ("Accessible route", ["Chapter 11B"], "wheelchair", "accessibility"),
    ("PV system", ["Title 24"], "photovoltaic", "energy"),
    ("Wildland-Urban Interface", ["Chapter 7A"], "ember-resistant vents", "environmental"),
    ("Driveway approach", ["Public Works"], "curb cut", "public_works"),
    ("Exit width", ["Egress"], "stair", "fire"),       # 'egress' matches fire first
    ("Foundation", ["Building"], "footing", "building_safety"),
    ("Random thing", ["Misc"], "lorem ipsum", "building_safety"),  # default
])
def test_classify_category_basic(title, crumb, text, expected):
    assert classify_category(title, crumb, text) == expected


# ─────────────────────────────────────────────────────────────
# Chunker — basic + oversize
# ─────────────────────────────────────────────────────────────

def _target() -> IngestTarget:
    return IngestTarget(
        code_short="TEST-MC",
        code_name="Test Municipal Code",
        version="2024",
        jurisdictions=["CA:Testville"],
        output_filename="amlegal_testville_ca.jsonl",
    )


def test_chunk_section_basic_shape():
    s = RawSection(
        breadcrumb=["Title 17 Zoning", "Chapter 17.32 Hillside", "17.32.040 Setbacks"],
        section_number="17.32.040",
        title="Setbacks",
        text="The minimum front setback shall be 25 feet.",
        source_url="http://example.test/17.32.040",
    )
    chunks = chunk_section(s, _target())
    assert len(chunks) == 1
    c = chunks[0]
    assert c["code_short"] == "TEST-MC"
    assert c["section"] == "17.32.040"
    assert c["jurisdictions"] == ["CA:Testville"]
    assert c["category"] == "zoning"
    assert "front setback" in c["text"]
    assert c["chunk_id"] == "test-mc-17.32.040"


def test_chunk_section_splits_oversize_on_paragraphs():
    """Sections longer than SOFT_MAX_CHARS must split into multiple chunks
    on paragraph boundaries (not mid-sentence) for retrieval cleanliness."""
    paragraph = "A" * 1000
    body = "\n\n".join([paragraph] * 10)   # ~10K chars, with paragraph breaks
    s = RawSection(
        breadcrumb=["Building"],
        section_number="9.04.010",
        title="Big section",
        text=body,
    )
    chunks = chunk_section(s, _target())
    assert len(chunks) >= 2, "oversize section should produce multiple chunks"
    assert all(len(c["text"]) <= SOFT_MAX_CHARS + 1200 for c in chunks)
    # Chunk ids must be unique
    ids = [c["chunk_id"] for c in chunks]
    assert len(set(ids)) == len(ids)


def test_chunk_section_empty_text_returns_nothing():
    s = RawSection(breadcrumb=[], section_number="x", title="x", text="   ")
    assert chunk_section(s, _target()) == []


@pytest.mark.parametrize("fragment", ["5", "11", "10", "10.1", "3.1.1", "R302",
                                      "90.4.1.1", "  4  ", "4.", ">"])
def test_chunk_section_drops_page_number_fragments(fragment):
    """A page/section-number fragment must NOT be written as a provision body.

    This is the bug the licensed-PDF ingester produced on ca_crc_2025: the
    heading regex over-matched a TOC/relocations table and wrote section
    'R104.6' with body '3', 'R101.2.1' with body '5', etc. In a citation-critical
    legal corpus, dropping the chunk (citation reads UNVERIFIED) is the correct
    failure — keeping garbage text a citation could be 'verified' against is not.
    """
    s = RawSection(breadcrumb=["Chapter 1"], section_number="R104.6",
                   title="Notices and orders", text=fragment)
    assert chunk_section(s, _target()) == []


@pytest.mark.parametrize("body", [
    "Reserved.",                                   # genuinely short, but real prose
    "See Section R113.2.",                          # short cross-reference provision
    "The minimum front setback shall be 25 feet.",  # ordinary provision
])
def test_chunk_section_keeps_legit_short_and_full_bodies(body):
    """Calibration guard: the fragment filter targets number debris, not brevity.
    A real 'Reserved.' section or a short cross-reference must still produce a
    chunk, or a future tightening of the predicate could silently eat provisions."""
    s = RawSection(breadcrumb=["Chapter 1"], section_number="R104.6",
                   title="Notices", text=body)
    chunks = chunk_section(s, _target())
    assert len(chunks) == 1
    assert chunks[0]["text"] == body


# ─────────────────────────────────────────────────────────────
# Writer
# ─────────────────────────────────────────────────────────────

def test_write_jsonl_roundtrip(tmp_path, monkeypatch):
    """Writer writes one JSON object per line, overwriting any prior file."""
    from app.code_library.ingest import writer as wmod

    # Redirect the writer's CORPUS_DIR to a temp path so we don't pollute
    # the real corpus.
    monkeypatch.setattr(wmod, "CORPUS_DIR", tmp_path)

    target = _target()
    chunks = [
        {"chunk_id": "a", "code_short": "X", "section": "1", "text": "alpha"},
        {"chunk_id": "b", "code_short": "X", "section": "2", "text": "beta"},
    ]
    out = wmod.write_jsonl(target, chunks)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["chunk_id"] == "a"
    assert json.loads(lines[1])["chunk_id"] == "b"


# ─────────────────────────────────────────────────────────────
# amlegal parser — leaf extraction from fixture HTML
# ─────────────────────────────────────────────────────────────

LEAF_HTML = """\
<!doctype html>
<html><body>
  <header><h2>17.32.040 Hillside Setbacks</h2></header>
  <div class="section-content">
    <p>The minimum front yard setback in a Hillside Management Area shall
    be twenty-five (25) feet measured from the property line.</p>
    <p>Where the natural slope exceeds 25 percent, the rear setback shall
    be increased by 5 feet per additional 10 percent of slope.</p>
  </div>
</body></html>
"""

TOC_HTML = """\
<!doctype html>
<html><body>
  <nav>
    <ul>
      <li><a class="toc-item" href="/codes/x/latest/x_ca/title-17/ch-32">Chapter 17.32 Hillside</a>
        <ul>
          <li><a class="toc-item" href="/codes/x/latest/x_ca/title-17/ch-32/17-32-040">17.32.040 Hillside Setbacks</a></li>
          <li><a class="toc-item" href="/codes/x/latest/x_ca/title-17/ch-32/17-32-050">17.32.050 Height Limits</a></li>
        </ul>
      </li>
    </ul>
  </nav>
</body></html>
"""


def test_amlegal_parse_leaf_extracts_section_number_and_text():
    from app.code_library.ingest.amlegal import AmLegalIngester

    ing = AmLegalIngester(root_url="http://example.test/codes/x/latest/x_ca")
    breadcrumb = ["Title 17 Zoning", "Chapter 17.32 Hillside", "17.32.040 Hillside Setbacks"]
    sect = ing._parse_leaf(LEAF_HTML, "http://example.test/.../17-32-040", breadcrumb)
    assert sect is not None
    assert sect.section_number == "17.32.040"
    assert "Hillside Setbacks" in sect.title
    assert "minimum front yard setback" in sect.text
    assert sect.breadcrumb[-1].endswith("Hillside Setbacks")


def test_amlegal_walks_toc_and_yields_leaves():
    """Mocked HTTP — the walker should descend into the chapter page and
    yield both leaf URLs in order. We do NOT exercise the network."""
    from app.code_library.ingest.amlegal import AmLegalIngester

    pages = {
        "http://example.test/codes/x/latest/x_ca": TOC_HTML,
        # Chapter container — fixture re-uses the same TOC HTML so the
        # nested anchors are the leaves themselves (matches what the live
        # site does for chapter pages).
        "http://example.test/codes/x/latest/x_ca/title-17/ch-32": TOC_HTML,
        "http://example.test/codes/x/latest/x_ca/title-17/ch-32/17-32-040": LEAF_HTML,
        "http://example.test/codes/x/latest/x_ca/title-17/ch-32/17-32-050":
            LEAF_HTML.replace("17.32.040 Hillside Setbacks", "17.32.050 Height Limits")
                     .replace("minimum front yard setback", "maximum allowed height"),
    }

    def fake_get(self, url):
        if url not in pages:
            raise RuntimeError(f"unmocked URL: {url}")
        return pages[url]

    target = _target()
    with patch.object(AmLegalIngester, "_get", new=fake_get):
        ing = AmLegalIngester(root_url="http://example.test/codes/x/latest/x_ca", delay_sec=0)
        sects = list(ing.fetch_sections(target))

    section_numbers = [s.section_number for s in sects]
    assert "17.32.040" in section_numbers
    assert "17.32.050" in section_numbers
    # Both should classify as zoning (Hillside)
    from app.code_library.ingest.chunker import chunk_section
    chunks = []
    for s in sects:
        chunks.extend(chunk_section(s, target))
    assert all(c["category"] in {"zoning", "building_safety"} for c in chunks)
