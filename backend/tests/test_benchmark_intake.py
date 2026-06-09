"""Tests for the correction-letter intake helper (benchmarks/intake.py).

The load-bearing guarantee: whatever the parser emits must be a VALID,
loadable ground_truth.yaml — otherwise the "10-minute review" turns into
debugging YAML.
"""
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks import intake as I                          # noqa: E402
from benchmarks.runner import parse_ground_truth            # noqa: E402


SAMPLE = """\
CITY OF LOS ANGELES - DEPARTMENT OF BUILDING AND SAFETY
PLAN CHECK CORRECTION SHEET

1. CBC 1011.5.2 - Provide handrails on both sides of the interior stair.
   Handrail height shall be 34" to 38" above the nosing.

2. Per CRC R337.7, exterior wall covering within 5 feet of grade shall be
   noncombustible. The plans show wood siding - revise.

3. ADA 404.2.3 - The new interior door is shown at 30". Provide 32" minimum
   clear width on the accessible route.

4. Plan check fee of $1,250 has not been paid. Submit payment before approval.

5. Provide structural calculations signed and wet-stamped by a CA licensed engineer.

6. Show the occupant load on the floor plan per CBC 1004.5.
"""


# ── citation detection ───────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("CBC 1011.5.2 handrails", ["CBC 1011.5.2"]),
    ("Per CRC R337.7 exterior", ["CRC R337.7"]),
    ("IBC Table 506.2 area", ["IBC 506.2"]),
    ("ADA 404.2.3 door", ["ADA 404.2.3"]),
    ("see CBC-7A 704A.1 vents", ["CBC-7A 704A.1"]),
])
def test_find_sections(text, expected):
    assert I.find_sections(text) == expected


def test_find_sections_dedupes_bare_r_inside_prefixed():
    # 'CRC R337.7' must not also yield a bare 'R337.7'.
    assert I.find_sections("CRC R337.7 and again CRC R337.7") == ["CRC R337.7"]


# ── guesses ──────────────────────────────────────────────────

def test_severity_guess():
    assert I.guess_severity("provide guardrail at the open stair") == "critical"
    assert I.guess_severity("accessible route door width") == "high"
    assert I.guess_severity("note the address on the cover") == "medium"


def test_administrative_detection():
    assert I.is_administrative("Plan check fee not paid", []) is True
    assert I.is_administrative("wet-stamped calculations", []) is True
    assert I.is_administrative("handrail height shall be 34 inches", ["CBC 1011.5.2"]) is False
    assert I.is_administrative("no section cited here", []) is True   # no code → admin


def test_objectivity_guess():
    assert I.guess_objectivity('door shown at 30" provide 32"') == "hard"
    assert I.guess_objectivity("clarify the design intent") == "soft"


# ── full parse ───────────────────────────────────────────────

def test_parse_splits_items_and_classifies():
    items = I.parse_correction_text(SAMPLE)
    assert len(items) == 6
    code = [i for i in items if not i.is_administrative]
    admin = [i for i in items if i.is_administrative]
    assert len(code) == 4 and len(admin) == 2          # 4,5 are admin (fee / wet-stamp)

    by_num = {i.number: i for i in items}
    assert by_num[1].sections == ["CBC 1011.5.2"]
    assert by_num[1].severity == "high" and by_num[1].objectivity == "hard"
    assert "CRC R337.7" in by_num[2].sections
    assert by_num[4].is_administrative is True          # the fee
    assert by_num[6].sections == ["CBC 1004.5"]


# ── the scaffold must be a valid, loadable ground_truth.yaml ──

def test_scaffold_is_valid_loadable_ground_truth():
    items = I.parse_correction_text(SAMPLE)
    text = I.render_ground_truth_yaml(items, {
        "source": "corrections.pdf", "state": "CA", "city": "Los Angeles",
        "county": "Los Angeles", "plan_type": "residential",
    })
    raw = yaml.safe_load(text)                           # 1) parses as YAML
    assert raw is not None

    gt = parse_ground_truth(raw, "intake_case")          # 2) loads as a case
    assert gt.tier == "C"
    assert gt.jurisdiction["city"] == "Los Angeles"
    # only the 4 code items become expected_findings; admin items stay commented out
    assert len(gt.expected_findings) == 4
    e0 = gt.expected_findings[0]
    assert e0.acceptable_sections == ["CBC 1011.5.2"]
    assert e0.issue_id and e0.severity in ("critical", "high", "medium", "low")
    assert gt.must_not_flag == []


def test_scaffold_handles_zero_code_items():
    # A letter that's all administrative must still emit valid YAML.
    items = I.parse_correction_text("1. Pay the plan check fee.\n2. Wet-stamp the cover sheet.")
    text = I.render_ground_truth_yaml(items, {"source": "x.txt"})
    raw = yaml.safe_load(text)
    gt = parse_ground_truth(raw, "empty_case")
    assert gt.expected_findings == []
