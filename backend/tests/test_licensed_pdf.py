"""Tests for the licensed-PDF code ingester (parser + end-to-end on a
synthetic PDF)."""
from pathlib import Path

import pytest

from app.code_library.ingest.base import IngestTarget
from app.code_library.ingest.chunker import chunk_many
from app.code_library.ingest.licensed_pdf import (
    extract_pdf_text,
    ingest_licensed_pdf,
    parse_code_text,
)


SAMPLE = """CHAPTER 10 MEANS OF EGRESS

SECTION 1004 OCCUPANT LOAD

1004.1 Design occupant load. In determining means of egress requirements,
the number of occupants for whom means of egress facilities are provided
shall be determined in accordance with this section.

1004.1.1 Cumulative occupant loads. Where the path of egress travel includes
intervening rooms, areas or spaces, cumulative occupant loads shall be
determined in accordance with this section.

SECTION 1005 MEANS OF EGRESS SIZING

1005.3 Required capacity based on occupant load. The required capacity of
the means of egress shall be determined in accordance with Sections 1005.3.1
and 1005.3.2.
Exception: Where stairways serve fewer occupants.

CHAPTER 7A MATERIALS AND CONSTRUCTION METHODS FOR EXTERIOR WILDFIRE EXPOSURE

SECTION 709A DECKING

709A.3 Where required. Decking shall comply with this section.
123
2021 INTERNATIONAL BUILDING CODE
"""


def test_parser_extracts_numbered_sections_with_breadcrumbs():
    sections = parse_code_text(SAMPLE)
    by_num = {s.section_number: s for s in sections}

    assert set(by_num) == {"1004.1", "1004.1.1", "1005.3", "709A.3"}

    s = by_num["1004.1.1"]
    assert s.title == "Cumulative occupant loads"
    assert s.breadcrumb == ["Chapter 10 MEANS OF EGRESS", "Section 1004 OCCUPANT LOAD"]
    assert "intervening rooms" in s.text

    # Chapter change resets the breadcrumb.
    deck = by_num["709A.3"]
    assert deck.breadcrumb[0].startswith("Chapter 7A")
    assert deck.breadcrumb[1].startswith("Section 709A")


def test_parser_marks_exceptions_and_strips_furniture():
    sections = parse_code_text(SAMPLE)
    by_num = {s.section_number: s for s in sections}
    assert by_num["1005.3"].extra_tags == ["exception"]
    # Page number + edition footer must not leak into section text.
    assert "INTERNATIONAL BUILDING CODE" not in by_num["709A.3"].text
    assert "123" not in by_num["709A.3"].text.split()


def test_parser_max_sections_cap():
    assert len(parse_code_text(SAMPLE, max_sections=2)) == 2


# Regression: the CEBC 319.7.x failure. A subsection whose number runs straight
# into a long descriptive sentence (no short "Title.") used to be invisible to
# the parser and got glued into its parent's body.
UNTITLED = """SECTION 319 SEISMIC EVALUATION

319.7 Prescriptive selection of the design method. The requirements of Method A
per Section 320 are permitted to be used except if the building has one or more
characteristics described in Sections 319.7.1 through 319.7.7.

319.7.1 A building with prestressed or post-tensioned structural components
(beams, columns, walls or slabs) or precast structural components (beams,
columns, walls or flooring systems).

319.7.2 A building assigned to Risk Category IV per Section 319.4.
"""


def test_parser_recognizes_untitled_list_subsections():
    by_num = {s.section_number: s for s in parse_code_text(UNTITLED)}
    # All three are seen as distinct sections (the bug dropped .1 and .2).
    assert {"319.7", "319.7.1", "319.7.2"} <= set(by_num)
    # The titled parent keeps its title and is NOT polluted with the child text.
    assert by_num["319.7"].title == "Prescriptive selection of the design method"
    assert "prestressed" not in by_num["319.7"].text
    # The untitled list items carry their full text and no spurious title.
    assert by_num["319.7.1"].title == ""
    assert "flooring systems" in by_num["319.7.1"].text
    # A trailing section cross-reference ("Section 319.4.") must not be split
    # off as a bogus title or truncate the body to "4.".
    assert by_num["319.7.2"].title == ""
    assert by_num["319.7.2"].text == "A building assigned to Risk Category IV per Section 319.4."


def test_parser_skips_toc_rows():
    """Dot-leader / page-folio rows are table-of-contents entries, not sections.
    Loosening the heading match must not re-admit them (the relocations-table
    over-match)."""
    toc = (
        "TABLE OF CONTENTS\n"
        "319.7 Prescriptive selection of the design method ............ 3-19\n"
        "319.8 Strength requirements ............ 3-20\n"
        "\n"
        "SECTION 320 METHOD A\n"
        "320.1 Scope. This method applies to buildings of light-frame construction.\n"
    )
    nums = {s.section_number for s in parse_code_text(toc)}
    assert "320.1" in nums                       # real heading still parses
    assert "319.7" not in nums and "319.8" not in nums   # TOC rows dropped


def test_chunks_carry_section_citations():
    target = IngestTarget(
        code_short="IBC", code_name="International Building Code",
        version="2021", jurisdictions=["*"], output_filename="x.jsonl",
    )
    chunks = list(chunk_many(parse_code_text(SAMPLE), target))
    ids = {c["chunk_id"] for c in chunks}
    assert "ibc-1004.1.1" in ids
    assert "ibc-709a.3" in ids
    c = next(c for c in chunks if c["chunk_id"] == "ibc-1004.1.1")
    assert c["section"] == "1004.1.1"
    assert c["jurisdictions"] == ["*"]


def test_end_to_end_pdf_ingest(tmp_path, monkeypatch):
    """Synthesize a PDF with fitz, ingest it, verify the corpus JSONL."""
    import json
    import fitz
    import app.code_library.ingest.writer as writer_mod

    pdf_path = tmp_path / "ibc_excerpt.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # insert_textbox wraps long text within the page rect.
    page.insert_textbox(fitz.Rect(36, 36, 560, 800), SAMPLE, fontsize=9)
    doc.save(str(pdf_path))
    doc.close()

    # Redirect corpus output away from the real corpus dir.
    monkeypatch.setattr(writer_mod, "CORPUS_DIR", tmp_path)

    target = IngestTarget(
        code_short="IBC", code_name="International Building Code",
        version="2021", jurisdictions=["*"],
        output_filename="licensed_ibc_2021.jsonl",
    )
    written = ingest_licensed_pdf(str(pdf_path), target)
    assert written >= 3

    out = tmp_path / "licensed_ibc_2021.jsonl"
    assert out.exists()
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert all(r["license_status"] == "licensed" for r in rows)
    assert all(r["source_tier"] == "licensed" for r in rows)
    secs = {r["section"] for r in rows}
    assert "1004.1" in secs


def test_missing_pdf_raises():
    target = IngestTarget(
        code_short="IBC", code_name="IBC", version="2021",
        jurisdictions=["*"], output_filename="x.jsonl",
    )
    with pytest.raises(FileNotFoundError):
        ingest_licensed_pdf("Z:/does/not/exist.pdf", target)
