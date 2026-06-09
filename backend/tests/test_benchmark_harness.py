"""Tests for the Week-1 benchmark plumbing (manifest, extended schema, capture).

The benchmark package lives at the repo root (it drives the backend as a black
box), so we add the repo root to sys.path to import it.
"""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks import manifest as M           # noqa: E402
from benchmarks import capture as C            # noqa: E402
from benchmarks.runner import parse_ground_truth, load_case, CASES_DIR  # noqa: E402


# ── manifest ─────────────────────────────────────────────────

def test_manifest_has_reproducibility_fields():
    man = M.build_manifest("dry", now=datetime(2026, 6, 9, 12, 0, 0))
    assert man["run_id"] == "20260609T120000Z"
    assert man["mode"] == "dry"
    # git_sha/corpus_sha resolve to a value or a safe sentinel — never crash.
    assert man["git_sha"] and man["corpus_sha"]
    assert "models" in man and "python" in man


# ── extended schema parsing (back-compatible) ────────────────

def test_parse_legacy_section_schema():
    gt = parse_ground_truth({
        "expected_findings": [{"section": "IBC 1011.5", "severity": "critical"}],
    }, "legacy_case")
    e = gt.expected_findings[0]
    assert e.section == "IBC 1011.5"
    assert e.acceptable_sections == ["IBC 1011.5"]   # derived
    assert e.issue_id == "IBC 1011.5"                # derived
    assert e.objectivity == "hard"                   # default
    assert gt.tier == "A" and gt.split == "dev"


def test_parse_extended_schema_preserved():
    gt = parse_ground_truth({
        "tier": "B", "split": "holdout", "source": "LA County letter",
        "input_quality": "vector", "labelers": ["jc_pe", "ms_arch"],
        "expected_findings": [{
            "issue_id": "wui-siding-5ft",
            "acceptable_sections": ["CBC-7A 704A.1", "CRC R337.7"],
            "objectivity": "soft", "severity": "critical", "status": "non_compliant",
            "acceptance_criteria": "flags combustible siding within 5 ft in a VHFHSZ",
        }],
    }, "ext_case")
    e = gt.expected_findings[0]
    assert e.issue_id == "wui-siding-5ft"
    assert e.acceptable_sections == ["CBC-7A 704A.1", "CRC R337.7"]
    assert e.section == "CBC-7A 704A.1"              # primary = first acceptable
    assert e.objectivity == "soft"
    assert gt.tier == "B" and gt.split == "holdout"
    assert gt.labelers == ["jc_pe", "ms_arch"]


# ── the clean negative control case loads correctly ──────────

def test_clean_control_case_is_a_zero_finding_control():
    gt = load_case(CASES_DIR / "la_sfr_clean_control")
    assert gt.expected_findings == []                # a compliant plan
    assert gt.must_not_flag                          # but with forbidden-flag guards
    assert gt.jurisdiction.get("city") == "Los Angeles"


# ── capture: report -> scorer-shaped findings/extraction (pure) ──

def test_findings_from_report_shape():
    report = SimpleNamespace(findings=[
        SimpleNamespace(
            code_requirement=SimpleNamespace(code_id="IBC 1004.1.1"),
            source_citation="IBC 1004.1.1",
            severity="critical",
            status=SimpleNamespace(value="non_compliant"),
            verified=True,
        ),
    ])
    out = C.findings_from_report(report)
    assert out == [{
        "code_id": "IBC 1004.1.1", "source_citation": "IBC 1004.1.1",
        "severity": "critical", "status": "non_compliant", "verified": True,
    }]


def test_findings_from_report_empty_when_no_findings():
    assert C.findings_from_report(SimpleNamespace(findings=[])) == []
    assert C.findings_from_report(SimpleNamespace()) == []


def test_extraction_from_report_unwraps_enums():
    report = SimpleNamespace(plan_data=SimpleNamespace(
        plan_type=SimpleNamespace(value="residential"),
        occupancy_type="R-3", construction_type="V-B",
        building_area=2500.0, stories=1, building_height=18.0,
    ))
    ex = C.extraction_from_report(report)
    assert ex["plan_type"] == "residential"
    assert ex["occupancy_type"] == "R-3" and ex["construction_type"] == "V-B"
    assert ex["building_area"] == 2500.0 and ex["stories"] == 1
