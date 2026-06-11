"""Tests for the Textract OCR fallback.

Pure-Python, no AWS. We fake the boto3 client to return canned `Blocks`
shaped like real Textract output and verify:
  - LINE-block text gets concatenated in order
  - KEY_VALUE_SET pairs are walked through the Relationships graph correctly
  - Canonical key aliases collapse label variants ("OCCUPANCY GROUP" → "occupancy")
  - Page selection respects TEXTRACT_MIN_CHARS_PER_PAGE
  - The disabled flag is a no-op (no boto3 call, original pages returned)
  - Merge logic preserves an existing text layer

The class under test is dependency-light by design, so we can build a fake
client without importing boto3 itself.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services.textract_extractor import TextractExtractor


# ─────────────────────────────────────────────────────────────────────────
# Fake Textract response factories
# ─────────────────────────────────────────────────────────────────────────


def _line(text: str, block_id: str) -> Dict[str, Any]:
    return {"BlockType": "LINE", "Id": block_id, "Text": text}


def _word(text: str, block_id: str) -> Dict[str, Any]:
    return {"BlockType": "WORD", "Id": block_id, "Text": text}


def _kv_pair(
    key_words: List[str],
    value_words: List[str],
    *,
    key_prefix: str,
) -> List[Dict[str, Any]]:
    """Build the four-block sequence Textract emits for one KV pair:
    KEY_VALUE_SET (KEY) + KEY_VALUE_SET (VALUE) + WORD children of each."""
    key_id = f"{key_prefix}-K"
    value_id = f"{key_prefix}-V"
    key_word_blocks = [_word(w, f"{key_id}-w{i}") for i, w in enumerate(key_words)]
    value_word_blocks = [_word(w, f"{value_id}-w{i}") for i, w in enumerate(value_words)]
    key_block = {
        "BlockType": "KEY_VALUE_SET",
        "EntityTypes": ["KEY"],
        "Id": key_id,
        "Relationships": [
            {"Type": "VALUE", "Ids": [value_id]},
            {"Type": "CHILD", "Ids": [b["Id"] for b in key_word_blocks]},
        ],
    }
    value_block = {
        "BlockType": "KEY_VALUE_SET",
        "EntityTypes": ["VALUE"],
        "Id": value_id,
        "Relationships": [
            {"Type": "CHILD", "Ids": [b["Id"] for b in value_word_blocks]},
        ],
    }
    return [key_block, value_block, *key_word_blocks, *value_word_blocks]


def _fake_response(lines: List[str], pairs: List) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = []
    for i, text in enumerate(lines):
        blocks.append(_line(text, f"L{i}"))
    for i, (k_words, v_words) in enumerate(pairs):
        blocks.extend(_kv_pair(k_words, v_words, key_prefix=f"P{i}"))
    return {"Blocks": blocks}


# ─────────────────────────────────────────────────────────────────────────
# Block parsing
# ─────────────────────────────────────────────────────────────────────────


def test_concat_lines_preserves_reading_order():
    blocks = [
        _line("PROJECT NAME: BEACH HOUSE", "L0"),
        _line("OCCUPANCY GROUP: R-3", "L1"),
        _line("CONSTRUCTION TYPE: V-B", "L2"),
        {"BlockType": "PAGE", "Id": "P0"},  # ignored
    ]
    out = TextractExtractor._concat_lines(blocks)
    lines = out.split("\n")
    assert lines == [
        "PROJECT NAME: BEACH HOUSE",
        "OCCUPANCY GROUP: R-3",
        "CONSTRUCTION TYPE: V-B",
    ]


def test_extract_kv_pairs_walks_relationships():
    blocks = _kv_pair(
        ["OCCUPANCY", "GROUP:"], ["B"], key_prefix="P0"
    ) + _kv_pair(
        ["CONSTRUCTION", "TYPE:"], ["II-B"], key_prefix="P1"
    )
    pairs = TextractExtractor._extract_kv_pairs(blocks)
    assert ("OCCUPANCY GROUP:", "B") in pairs
    assert ("CONSTRUCTION TYPE:", "II-B") in pairs


# ─────────────────────────────────────────────────────────────────────────
# Key alias normalization
# ─────────────────────────────────────────────────────────────────────────


def test_normalize_key_aliases_to_canonical_fields():
    ex = TextractExtractor()
    pairs = [
        ("OCCUPANCY GROUP:", "B"),
        ("Construction Type", "II-B"),
        ("Total Floor Area", "12,500 SF"),
        ("Max Building Height", "45 FT"),
        ("Number of Stories", "3"),
        ("Project Address:", "1234 Main St, Pasadena CA"),
        ("Random Label", "ignore me"),       # unknown → dropped
    ]
    out = ex._normalize_kv_pairs(pairs)
    assert out["occupancy"] == "B"
    assert out["construction_type"] == "II-B"
    assert out["building_area"] == "12,500 SF"
    assert out["building_height"] == "45 FT"
    assert out["stories"] == "3"
    assert out["project_address"] == "1234 Main St, Pasadena CA"
    assert "random label" not in out


def test_normalize_first_occurrence_wins():
    """Title-sheet box is first in reading order — its 'OCCUPANCY: B' must
    not get overwritten by a later sheet's 'OCCUPANCY: A-2'."""
    ex = TextractExtractor()
    pairs = [("OCCUPANCY:", "B"), ("OCCUPANCY:", "A-2")]
    out = ex._normalize_kv_pairs(pairs)
    assert out["occupancy"] == "B"


# ─────────────────────────────────────────────────────────────────────────
# Merge logic
# ─────────────────────────────────────────────────────────────────────────


def test_merge_text_appends_when_existing_has_content():
    merged = TextractExtractor._merge_text("existing text layer", "OCR result")
    assert "existing text layer" in merged
    assert "OCR result" in merged
    assert merged.index("existing") < merged.index("OCR")


def test_merge_text_uses_ocr_when_existing_empty():
    assert TextractExtractor._merge_text("", "OCR result") == "OCR result"
    assert TextractExtractor._merge_text("   ", "OCR result") == "OCR result"


def test_merge_text_keeps_existing_when_ocr_empty():
    assert TextractExtractor._merge_text("existing", "") == "existing"


# ─────────────────────────────────────────────────────────────────────────
# Page selection by threshold
# ─────────────────────────────────────────────────────────────────────────


def test_pages_needing_ocr_picks_thin_pages():
    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.textract_min_chars_per_page = 200
        fake_settings.textract_max_pages = 25
        targets = ex._pages_needing_ocr({
            1: "x" * 50,             # thin
            2: "x" * 500,            # fine
            3: "",                   # very thin
            4: "x" * 199,            # thin (one below threshold)
            5: "x" * 200,            # fine (exactly threshold)
        })
        assert targets == [1, 3, 4]


def test_pages_needing_ocr_caps_at_max():
    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.textract_min_chars_per_page = 200
        fake_settings.textract_max_pages = 3
        targets = ex._pages_needing_ocr({i: "" for i in range(1, 11)})
        assert targets == [1, 2, 3]


def test_pages_needing_ocr_zero_means_no_cap():
    """textract_max_pages=0 disables the cap entirely — every thin page goes
    to OCR. Important for full-plan-set scans where the user wants 100% coverage."""
    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.textract_min_chars_per_page = 200
        fake_settings.textract_max_pages = 0
        targets = ex._pages_needing_ocr({i: "" for i in range(1, 201)})
        assert targets == list(range(1, 201))


def test_pages_needing_ocr_negative_also_means_no_cap():
    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.textract_min_chars_per_page = 200
        fake_settings.textract_max_pages = -1
        targets = ex._pages_needing_ocr({i: "" for i in range(1, 51)})
        assert len(targets) == 50


# ─────────────────────────────────────────────────────────────────────────
# enhance() — end-to-end
# ─────────────────────────────────────────────────────────────────────────


def test_enhance_no_op_when_disabled():
    """When the flag is off, enhance returns the input pages dict unchanged
    and never reaches boto3."""
    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.aws_textract_enabled = False
        fake_settings.aws_access_key_id = "AKIAFAKE"
        result = ex.enhance("nonexistent.pdf", {1: "anything"})
    assert result["pages"] == {1: "anything"}
    assert result["code_data_summary"] == {}
    assert result["stats"]["pages_attempted"] == 0


def test_enhance_no_op_when_every_page_above_threshold(tmp_path):
    """If every page already has enough text, enhance skips Textract and
    returns clean."""
    import fitz
    pdf_path = tmp_path / "fat.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Lots of text " * 200)
    doc.save(str(pdf_path))
    doc.close()

    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.aws_textract_enabled = True
        fake_settings.aws_access_key_id = "AKIAFAKE"
        fake_settings.aws_secret_access_key = "secret"
        fake_settings.aws_region = "us-west-2"
        fake_settings.textract_min_chars_per_page = 50
        fake_settings.textract_max_pages = 25
        result = ex.enhance(str(pdf_path), {1: "Lots of text " * 200})
    # No boto3 call needed because the page is fat.
    assert result["stats"]["pages_attempted"] == 0
    assert result["pages"][1] == "Lots of text " * 200


def test_enhance_calls_textract_and_normalizes_kvs(tmp_path):
    """End-to-end happy path: thin page → render → fake Textract returns
    canned blocks → pages enriched + code_data_summary populated."""
    import fitz
    pdf_path = tmp_path / "thin.pdf"
    doc = fitz.open()
    doc.new_page()   # blank page → empty text layer
    doc.save(str(pdf_path))
    doc.close()

    canned = _fake_response(
        lines=["BEACH HOUSE", "OCCUPANCY GROUP: R-3"],
        pairs=[
            (["OCCUPANCY", "GROUP:"], ["R-3"]),
            (["CONSTRUCTION", "TYPE:"], ["V-B"]),
        ],
    )

    class FakeClient:
        def analyze_document(self, **kwargs):
            assert "TABLES" in kwargs["FeatureTypes"]
            assert "FORMS" in kwargs["FeatureTypes"]
            return canned

    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.aws_textract_enabled = True
        fake_settings.aws_access_key_id = "AKIAFAKE"
        fake_settings.aws_secret_access_key = "secret"
        fake_settings.aws_region = "us-west-2"
        fake_settings.textract_min_chars_per_page = 200
        fake_settings.textract_max_pages = 25
        with patch.object(ex, "_get_client", return_value=FakeClient()):
            result = ex.enhance(str(pdf_path), {1: ""})

    assert result["stats"]["pages_attempted"] == 1
    assert result["stats"]["pages_ocr_succeeded"] == 1
    assert "OCCUPANCY GROUP: R-3" in result["pages"][1]
    assert result["code_data_summary"]["occupancy"] == "R-3"
    assert result["code_data_summary"]["construction_type"] == "V-B"


def test_enhance_kv_merge_fills_gaps_and_records_conflicts(tmp_path):
    """Multi-page KV merge: first page wins per field, later pages FILL
    missing fields, and a later page that DISAGREES is recorded in
    stats.kv_conflicts instead of silently dropped."""
    import fitz
    pdf_path = tmp_path / "two-thin.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    page_responses = [
        _fake_response(
            lines=["TITLE SHEET"],
            pairs=[(["OCCUPANCY:"], ["R-3"])],
        ),
        _fake_response(
            lines=["CODE DATA"],
            pairs=[
                (["OCCUPANCY:"], ["B"]),                 # disagrees with page 1
                (["CONSTRUCTION", "TYPE:"], ["V-B"]),    # fills a gap
            ],
        ),
    ]

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def analyze_document(self, **kwargs):
            resp = page_responses[self.calls]
            self.calls += 1
            return resp

    ex = TextractExtractor()
    with patch("app.services.textract_extractor.settings") as fake_settings:
        fake_settings.aws_textract_enabled = True
        fake_settings.aws_access_key_id = "AKIAFAKE"
        fake_settings.aws_secret_access_key = "secret"
        fake_settings.aws_region = "us-west-2"
        fake_settings.textract_min_chars_per_page = 200
        fake_settings.textract_max_pages = 25
        with patch.object(ex, "_get_client", return_value=FakeClient()):
            result = ex.enhance(str(pdf_path), {1: "", 2: ""})

    # First page's value kept; second page filled the missing field.
    assert result["code_data_summary"]["occupancy"] == "R-3"
    assert result["code_data_summary"]["construction_type"] == "V-B"
    # The disagreement is auditable.
    assert result["stats"]["kv_conflicts"]["occupancy"] == ["R-3", "B"]
