"""Pure text->dict tests for PDFProcessor._extract_dimensions.

The extractor is the Surveyor: it pulls labeled scalars off the CODE ANALYSIS /
PROJECT DATA text. These tests pin the newly-extracted egress-detail dimensions
(guard/handrail height, stair riser/tread) and confirm the fail-safe contract:
an unlabeled or junk value yields an ABSENT key, never a crash.
"""
from app.services.pdf_processor import PDFProcessor

P = PDFProcessor()


def test_guard_and_handrail_heights_extracted():
    text = 'GUARD HEIGHT: 42"\nHANDRAIL HEIGHT: 36"'
    dims = P._extract_dimensions(text)
    assert dims["guard_height"] == 42.0
    assert dims["handrail_height"] == 36.0


def test_riser_and_tread_extracted():
    text = "MAX RISER: 7\"\nMIN TREAD: 11\""
    dims = P._extract_dimensions(text)
    assert dims["riser_height"] == 7.0
    assert dims["tread_depth"] == 11.0


def test_alternate_labels_and_units():
    # guardrail/handrail variants, fractional riser, inch-word units
    text = "GUARDRAIL HT: 42 IN\nHANDRAIL: 34\"\nRISER HEIGHT: 7.75\"\nTREAD DEPTH: 10\""
    dims = P._extract_dimensions(text)
    assert dims["guard_height"] == 42.0
    assert dims["handrail_height"] == 34.0
    assert dims["riser_height"] == 7.75
    assert dims["tread_depth"] == 10.0


def test_missing_fields_are_absent_not_none():
    # None-safe contract: unlabeled -> key simply not present (no crash, no None).
    dims = P._extract_dimensions("OCCUPANCY: R-3\nCEILING HEIGHT: 8 FT")
    assert "guard_height" not in dims
    assert "handrail_height" not in dims
    assert "riser_height" not in dims
    assert "tread_depth" not in dims


def test_junk_values_dropped():
    # Empty/garbage captures are rejected by _safe_float -> absent key.
    dims = P._extract_dimensions("GUARD HEIGHT: .\nRISER: ")
    assert "guard_height" not in dims
    assert "riser_height" not in dims
