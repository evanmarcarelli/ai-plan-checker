"""Tests for discipline-aware page routing in DepartmentReviewer
._relevant_plan_text (sheet-index boost + sheet labels)."""
from app.agents.departments import ALL_DEPARTMENTS
from app.models.schemas import ExtractedPlanData


def _dept(code: str):
    for cls in ALL_DEPARTMENTS:
        d = cls()
        if d.category == code:
            return d
    raise AssertionError(f"no department with category {code}")


def test_discipline_sheet_outranks_keyword_pages():
    """The electrical reviewer must pull the E-sheet even when its body text
    has fewer 'electrical' keywords than a spec page."""
    dept = _dept("electrical")
    pd = ExtractedPlanData(
        raw_text_by_page={
            1: "TITLE SHEET. CODE ANALYSIS.",
            # Spec page: many keyword hits, not an E-sheet.
            2: "electrical wiring conductor receptacle circuit panel grounding",
            # The E-sheet: drawing labels, single weak keyword.
            3: "PANEL SCHEDULE PNL-A 200A",
        },
        sheet_index=[
            {"page_number": 2, "sheet_number": "A-9.0", "sheet_title": "SPECS",
             "discipline": "architectural", "category": "building_safety",
             "source": "title_block", "confidence": 0.9},
            {"page_number": 3, "sheet_number": "E-1.0", "sheet_title": "POWER PLAN",
             "discipline": "electrical", "category": "electrical",
             "source": "title_block", "confidence": 0.9},
        ],
    )
    # Tight budget: page 1 (anchor) + one more page. The E-sheet must win.
    text = dept._relevant_plan_text(pd, budget=60, per_page=50)
    assert "SHEET E-1.0 POWER PLAN" in text
    assert "PNL-A" in text


def test_sheet_labels_appear_in_page_headers():
    dept = _dept("electrical")
    pd = ExtractedPlanData(
        raw_text_by_page={1: "TITLE", 2: "electrical receptacle circuit"},
        sheet_index=[
            {"page_number": 1, "sheet_number": "T-1.0", "sheet_title": None,
             "discipline": "general", "category": "building_safety",
             "source": "title_block", "confidence": 0.9},
        ],
    )
    text = dept._relevant_plan_text(pd)
    assert "[PAGE 1 — SHEET T-1.0]" in text
    assert "[PAGE 2]" in text  # no sheet record → plain label


def test_no_sheet_index_behaves_like_before():
    dept = _dept("electrical")
    pd = ExtractedPlanData(
        raw_text_by_page={1: "TITLE", 2: "electrical receptacle circuit"},
    )
    text = dept._relevant_plan_text(pd)
    assert "[PAGE 1]" in text and "[PAGE 2]" in text
