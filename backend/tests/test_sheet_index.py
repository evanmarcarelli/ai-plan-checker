"""Tests for app.services.sheet_index — deterministic sheet identification."""
import pytest

from app.services.sheet_index import (
    DISCIPLINE_TO_CATEGORY,
    build_sheet_index,
    detect_page_sheet_number,
    discipline_for_sheet_number,
    parse_cover_sheet_index,
    summarize_sheet_index,
)


# ── discipline mapping ────────────────────────────────────────────────


@pytest.mark.parametrize("sheet,expected", [
    ("A-1.0", "architectural"),
    ("A101", "architectural"),
    ("S-2", "structural"),
    ("S2.1", "structural"),
    ("M-1", "mechanical"),
    ("E-101", "electrical"),
    ("P-1", "plumbing"),
    ("FP-1", "fire_protection"),
    ("LS-1", "life_safety"),
    ("T-1.0", "general"),
    ("CS-1", "general"),
    ("C1.1", "civil"),
    ("L-1", "landscape"),
    ("EN-1", "energy"),
    ("ID-2", "interiors"),
])
def test_discipline_prefixes(sheet, expected):
    assert discipline_for_sheet_number(sheet) == expected


def test_discipline_unknown_prefix():
    assert discipline_for_sheet_number("ZZZ-1") is None
    assert discipline_for_sheet_number("") is None


def test_every_discipline_has_category():
    for disc in set(d for _, d in [
        ("A", "architectural"), ("S", "structural")
    ]) | set(DISCIPLINE_TO_CATEGORY):
        assert disc in DISCIPLINE_TO_CATEGORY


# ── cover-sheet index parsing ─────────────────────────────────────────


COVER_TEXT = """PROJECT: TEST BUILDING
SHEET INDEX
T-1.0  TITLE SHEET
A-1.0  SITE PLAN
A-2.0 - FLOOR PLAN
S-1   FOUNDATION PLAN
M-1   MECHANICAL PLAN
E-1   ELECTRICAL PLAN

GENERAL NOTES
ALL WORK SHALL CONFORM TO THE 2022 CBC.
"""


def test_parse_cover_sheet_index():
    idx = parse_cover_sheet_index({1: COVER_TEXT})
    assert idx["T-1.0"] == "TITLE SHEET"
    assert idx["A-1.0"] == "SITE PLAN"
    assert idx["A-2.0"] == "FLOOR PLAN"
    assert idx["S-1"] == "FOUNDATION PLAN"
    assert len(idx) == 6


def test_index_rejects_occupancy_lookalikes():
    text = """SHEET INDEX
A-1  FIRST FLOOR PLAN
R-3  OCCUPANCY GROUP
"""
    idx = parse_cover_sheet_index({1: text})
    assert "A-1" in idx          # corroborated by drawing-ish title
    assert "R-3" not in idx      # occupancy declaration, not a sheet


def test_no_index_returns_empty():
    assert parse_cover_sheet_index({1: "GENERAL NOTES\nNO TABLE HERE"}) == {}


# ── per-page detection ───────────────────────────────────────────────


def test_labeled_sheet_number_wins():
    hit = detect_page_sheet_number("blah blah SHEET NO: A-2.0 blah", None, {})
    assert hit["sheet_number"] == "A-2.0"
    assert hit["confidence"] >= 0.9
    assert hit["discipline"] == "architectural"


def test_corner_text_detection():
    hit = detect_page_sheet_number(
        "FLOOR PLAN GENERAL NOTES...", "PROJECT X\nDATE 01/02\nA-3.1", {}
    )
    assert hit["sheet_number"] == "A-3.1"
    assert hit["source"] == "title_block"


def test_ambiguous_token_requires_index():
    # "R-3" alone (occupancy group) must NOT be claimed as a sheet number...
    assert detect_page_sheet_number("OCCUPANCY: R-3", "R-3", {}) is None
    # ...unless the cover index lists it as a real sheet.
    hit = detect_page_sheet_number("...", "R-3", {"R-3": "ROOF PLAN"})
    assert hit is not None and hit["sheet_number"] == "R-3"


def test_body_token_needs_index_confirmation():
    assert detect_page_sheet_number("see detail on A-5.0", None, {}) is None
    hit = detect_page_sheet_number(
        "see detail on A-5.0", None, {"A-5.0": "DETAILS"}
    )
    assert hit is not None and hit["source"] == "index_match"


def test_construction_type_not_matched():
    # V-B / I-A have no digits — must never match.
    assert detect_page_sheet_number("CONSTRUCTION TYPE: V-B", "TYPE I-A", {}) is None


# ── full build ───────────────────────────────────────────────────────


def test_build_sheet_index_end_to_end():
    pages = {
        1: COVER_TEXT,
        2: "SITE PLAN CONTENT",
        3: "FLOOR PLAN CONTENT",
        4: "RANDOM PAGE",
    }
    corners = {
        1: "T-1.0",
        2: "A-1.0",
        3: "SHEET NO: A-2.0",
    }
    recs = build_sheet_index(pages, corners)
    by_page = {r["page_number"]: r for r in recs if r["page_number"]}
    assert by_page[1]["sheet_number"] == "T-1.0"
    assert by_page[1]["sheet_title"] == "TITLE SHEET"
    assert by_page[2]["sheet_number"] == "A-1.0"
    assert by_page[2]["category"] == "building_safety"
    assert by_page[3]["sheet_number"] == "A-2.0"
    assert by_page[4]["sheet_number"] is None
    # Sheets listed in the index but never matched to a page survive as
    # index_only records (proof the sheet exists in the set).
    index_only = {r["sheet_number"] for r in recs if r["source"] == "index_only"}
    assert {"S-1", "M-1", "E-1"} <= index_only

    stats = summarize_sheet_index(recs)
    assert stats["pages"] == 4
    assert stats["pages_with_sheet_number"] == 3
    assert stats["disciplines"]["architectural"] == 2
    assert stats["index_only_sheets"] == 3
