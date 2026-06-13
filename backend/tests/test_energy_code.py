"""Tests for the California Energy Code (Title 24, Part 6) ingester: TOC
cutting, first-occurrence/running-header handling, hardcoded subchapter
mapping, back-matter tail cut, and the renumbered-draft guard."""
import json

import pytest

from app.code_library.ingest.energy_code import (
    ingest_energy_code,
    parse_energy_code_text,
    _subchapter_for,
)


# Miniature adopted-code text: a TOC block, then a body with running headers,
# wrapped titles, a globally-unique-number layout, and a back-matter appendix.
SAMPLE = """2025 BUILDING ENERGY EFFICIENCY STANDARDS

TABLE OF CONTENTS
SECTION 100.0 – SCOPE ............................................................. 1
SECTION 150.0 – MANDATORY FEATURES AND DEVICES ...................... 386
SECTION 150.1 – PERFORMANCE AND PRESCRIPTIVE COMPLIANCE APPROACHES ... 418

SUBCHAPTER 1 ALL OCCUPANCIES—GENERAL
SECTION 100.0 – SCOPE
This part establishes energy efficiency standards for newly constructed
buildings. Buildings shall comply as specified in Section 100.0(a).
(a) Scope. These standards apply to all buildings.

SECTION 100.0 – SCOPE
Page 12
(b) The provisions are applicable to different building types.

SUBCHAPTER 7 SINGLE-FAMILY RESIDENTIAL BUILDINGS — MANDATORY
SECTION 150.0 – MANDATORY FEATURES AND DEVICES
Single-family residential buildings shall meet the following mandatory
measures for insulation, fenestration, and water heating.
(a) Ceiling insulation. Installed insulation shall meet Section 150.0(a).

SUBCHAPTER 8 SINGLE-FAMILY RESIDENTIAL BUILDINGS - PERFORMANCE AND
PRESCRIPTIVE COMPLIANCE APPROACHES
SECTION 150.1 – PERFORMANCE AND PRESCRIPTIVE COMPLIANCE APPROACHES FOR SINGLE-FAMILY
RESIDENTIAL BUILDINGS
(a) Basic Requirements. Single-family residential buildings shall meet all of
the applicable requirements of Sections 110.0 through 110.12.

APPENDIX 1-A
DOCUMENTS INCORPORATED BY REFERENCE
AHRI Standard 1230-2023 — this back-matter must not be ingested.
SECTION 999.9 – SHOULD NOT APPEAR
"""


def _by_num(text=SAMPLE):
    return {s.section_number: s for s in parse_energy_code_text(text)}


def test_extracts_unique_body_sections_only():
    secs = _by_num()
    assert set(secs) == {"100.0", "150.0", "150.1"}  # TOC + back-matter excluded


def test_running_header_repeat_is_collapsed_into_one_section():
    s = _by_num()["100.0"]
    # Both halves of 100.0 (split by a running header) land in one section.
    assert "(a) Scope" in s.text
    assert "(b) The provisions" in s.text
    # The running-header line itself is stripped.
    assert "SECTION 100.0" not in s.text
    assert "Page 12" not in s.text


def test_back_matter_after_appendix_is_dropped():
    secs = _by_num()
    assert "999.9" not in secs
    for s in secs.values():
        assert "INCORPORATED BY REFERENCE" not in s.text
        assert "back-matter must not be ingested" not in s.text


def test_subchapter_breadcrumb_hardcoded_mapping():
    secs = _by_num()
    assert secs["100.0"].breadcrumb[1].startswith("Subchapter 1")
    assert secs["150.0"].breadcrumb[1].startswith("Subchapter 7")
    assert secs["150.1"].breadcrumb[1].startswith("Subchapter 8")
    # Cross-reference in the body text survives (it is real regulatory content).
    assert "Sections 110.0 through 110.12" in secs["150.1"].text


def test_subchapter_for_ranges():
    assert _subchapter_for("110.6")[0] == 2
    assert _subchapter_for("140.3")[0] == 5
    assert _subchapter_for("150.0")[0] == 7
    assert _subchapter_for("150.1")[0] == 8
    assert _subchapter_for("150.2")[0] == 9
    assert _subchapter_for("160.1")[0] == 10
    assert _subchapter_for("180.4")[0] == 12


def test_max_sections_cap():
    assert len(parse_energy_code_text(SAMPLE, max_sections=2)) == 2


def test_end_to_end_pdf_ingest(tmp_path, monkeypatch):
    import fitz
    import app.code_library.ingest.writer as writer_mod

    pdf_path = tmp_path / "energy_excerpt.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # The default PDF font can't draw the en-dash (renders "?"); the real CEC
    # PDF has true en-dashes, which the parser also accepts. Swap to a hyphen
    # purely so this synthetic fixture round-trips.
    page.insert_textbox(fitz.Rect(36, 36, 560, 800), SAMPLE.replace("–", "-"), fontsize=8)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(writer_mod, "CORPUS_DIR", tmp_path)
    written = ingest_energy_code(str(pdf_path))
    assert written >= 3

    out = tmp_path / "ca_energy_code_2025.jsonl"
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert all(r["code_short"] == "T24-P6" for r in rows)
    assert all(r["jurisdictions"] == ["CA"] for r in rows)
    assert all(r["category"] == "energy" for r in rows)         # force_category
    assert all(r["license_status"] == "edict" for r in rows)
    assert all(r["source_tier"] == "official_gov" for r in rows)
    assert "t24-p6-150.1" in {r["chunk_id"] for r in rows}


def test_rejects_renumbered_draft(tmp_path):
    import fitz
    pdf_path = tmp_path / "restructured.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(36, 36, 560, 800),
        "RESTRUCTURED 2025 ENERGY CODE\nThis format and numbering have not been "
        "formally adopted and should not be used in place of the adopted code.",
        fontsize=10,
    )
    doc.save(str(pdf_path))
    doc.close()
    with pytest.raises(ValueError, match="Restructured|not adopted|formally adopted"):
        ingest_energy_code(str(pdf_path))


def test_missing_pdf_raises():
    with pytest.raises(FileNotFoundError):
        ingest_energy_code("Z:/does/not/exist.pdf")
