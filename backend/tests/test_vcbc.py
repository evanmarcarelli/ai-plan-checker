"""Tests for the VCBC (Ventura County Building Code) compiled-ordinance
ingester: article splitting, per-article chunk namespacing, the relaxed
numbering fallback, and adoption-statement capture."""
import json

import pytest

from app.code_library.ingest.vcbc import (
    _article_attribution,
    ingest_vcbc,
    parse_vcbc_articles,
)


# A miniature compiled ordinance: TOC + four body articles exercising every
# parse path — strict ICC numbering with a colliding "101.1" across two
# articles, an appendix header, a relaxed-numbering CalGreen article, and a
# pure adoption-statement article with no numbered sections at all.
SAMPLE = """TABLE OF CONTENTS

ARTICLE 1 -- ADOPTION OF THE VENTURA COUNTY BUILDING CODE
ARTICLE 2 – AMENDMENTS TO THE CALIFORNIA BUILDING CODE
ARTICLE 3 – AMENDMENTS TO THE CALIFORNIA ENERGY CODE
ARTICLE 4 – AMENDMENTS TO THE CALIFORNIA GREEN BUILDING STANDARDS CODE

ARTICLE 1
ADOPTION OF THE
VENTURA COUNTY BUILDING CODE

CHAPTER 1 ADOPTION OF STATE CODES

SECTION 101 VENTURA COUNTY BUILDING CODE DEFINED

101.1 Elements. The Ventura County Building Code contained herein is
comprised of the California codes, appendices, model codes, and amendments
described below.

ARTICLE 2
AMENDMENTS TO THE
CALIFORNIA BUILDING CODE

CHAPTER 1 AMENDMENTS TO CBC CHAPTER 1

SECTION 101 GENERAL

101.1 Title. These regulations shall be known as the Building Code of the
County of Ventura.

CBC APPENDIX J
GRADING

J101.1 General. Grading, erosion control and sediment control shall comply
with this appendix and county standards.

ARTICLE 3
AMENDMENTS TO THE
CALIFORNIA ENERGY CODE

CHAPTER 1
GENERAL PROVISIONS

In order to carry out the necessary civil, administrative, and criminal
procedures for enforcing the standards and provisions contained in the
California Energy Code, the Scope and Administration provisions of the
Building Code shall be used, as adopted, and as amended in Article 2.

ARTICLE 4
AMENDMENTS TO THE
CALIFORNIA GREEN BUILDING STANDARDS CODE

CGBC APPENDIX A4
RESIDENTIAL VOLUNTARY MEASURES

A4.8 All-electric appliances and equipment. In order to reduce greenhouse
gases, new residential buildings may be designed and constructed to have no
appliances or equipment that use natural gas.
"""


def _articles_by_number(text=SAMPLE):
    return {n: (title, secs) for n, title, secs in parse_vcbc_articles(text)}


def test_articles_split_with_titles():
    arts = _articles_by_number()
    assert set(arts) == {1, 2, 3, 4}
    assert arts[1][0] == "ADOPTION OF THE VENTURA COUNTY BUILDING CODE"
    assert arts[2][0] == "AMENDMENTS TO THE CALIFORNIA BUILDING CODE"


def test_colliding_section_numbers_stay_in_their_articles():
    arts = _articles_by_number()
    a1 = {s.section_number: s for _, s in [(None, s) for s in arts[1][1]]}
    a2 = {s.section_number: s for s in arts[2][1]}
    assert "Ventura County Building Code contained herein" in a1["101.1"].text
    assert "Building Code of the" in a2["101.1"].text
    # The article crumb leads every breadcrumb.
    assert a2["101.1"].breadcrumb[0].startswith("VCBC Article 2")


def test_appendix_header_becomes_breadcrumb():
    arts = _articles_by_number()
    j = next(s for s in arts[2][1] if s.section_number == "J101.1")
    assert any(c.startswith("Appendix J") for c in j.breadcrumb)


def test_adoption_statement_captured_for_stub_article():
    arts = _articles_by_number()
    title, secs = arts[3]
    assert [s.section_number for s in secs] == ["adoption"]
    assert "Scope and Administration" in secs[0].text
    # Header echo must not survive in the adoption text.
    assert "GENERAL PROVISIONS" not in secs[0].text


def test_relaxed_numbering_fallback_parses_calgreen_style():
    arts = _articles_by_number()
    nums = {s.section_number for s in arts[4][1]}
    assert "A4.8" in nums
    a48 = next(s for s in arts[4][1] if s.section_number == "A4.8")
    assert a48.title == "All-electric appliances and equipment"


def test_article_attribution_mapping():
    assert _article_attribution("ADOPTION OF THE VENTURA COUNTY BUILDING CODE") == (None, None, False)
    assert _article_attribution("AMENDMENTS TO THE CALIFORNIA BUILDING CODE (CBC)")[0] == "CBC"
    assert _article_attribution("AMENDMENTS TO THE CALIFORNIA HISTORICAL BUILDING CODE")[0] == "CHBC"
    assert _article_attribution("AMENDMENTS TO THE CALIFORNIA WILDLAND-URBAN INTERFACE CODE")[0] == "CWUIC"
    assert _article_attribution("MOBILE HOMES AND COMMERCIAL COACHES") == (
        "MH", "Mobile Homes and Commercial Coaches", False)


def test_article_attribution_survives_body_header_drift():
    """The ordinance's body headers drift from its TOC: one-word
    'MOBILEHOMES', unhyphenated 'LIMITED DENSITY', and the county's own
    'SWIMMIING' typo. Attribution must still namespace these articles —
    a miss collides them with Article 1's 101.x numbering."""
    assert _article_attribution("MOBILEHOMES AND COMMERCIAL COACHES")[0] == "MH"
    assert _article_attribution("LIMITED DENSITY OWNER-BUILT RURAL DWELLINGS")[0] == "LD"
    assert _article_attribution(
        "AMENDMENTS TO THE INTERNATIONAL SWIMMIING POOL AND SPA CODE")[0] == "ISPSC"
    assert _article_attribution("POST-DISASTER RECOVERY AND RECONSTRUCTION")[0] == "PDR"


def test_end_to_end_pdf_ingest(tmp_path, monkeypatch):
    """Synthesize a PDF with fitz, ingest it, verify namespaced chunk ids."""
    import fitz
    import app.code_library.ingest.writer as writer_mod

    pdf_path = tmp_path / "vcbc_excerpt.pdf"
    doc = fitz.open()
    # Split across pages the way the real ordinance is; textbox wraps within
    # the rect and silently drops overflow, so keep each page's text short.
    half = SAMPLE.find("ARTICLE 3\n")
    for part in (SAMPLE[:half], SAMPLE[half:]):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(36, 36, 560, 800), part, fontsize=9)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(writer_mod, "CORPUS_DIR", tmp_path)

    written = ingest_vcbc(str(pdf_path))
    assert written >= 4

    out = tmp_path / "vcbc_2025_ord4655.jsonl"
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    ids = {r["chunk_id"] for r in rows}

    # Same section number, different articles → distinct namespaced ids.
    assert "vcbc-101.1" in ids
    assert "vcbc-cbc-101.1" in ids
    assert "vcbc-cbc-j101.1" in ids
    assert "vcbc-cenc-adoption" in ids
    assert "vcbc-cgbc-a4.8" in ids
    assert len(ids) == len(rows), "chunk ids must be unique"

    assert all(r["license_status"] == "edict" for r in rows)
    assert all(r["source_tier"] == "official_gov" for r in rows)
    assert all(r["jurisdictions"] == ["CA:Ventura County"] for r in rows)


def test_missing_pdf_raises():
    with pytest.raises(FileNotFoundError):
        ingest_vcbc("Z:/does/not/exist.pdf")
