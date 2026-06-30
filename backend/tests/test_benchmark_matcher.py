"""Tests for the Week-2 benchmark core: fair matcher, bootstrap CIs, extraction.

These guard the *measurement* itself — a benchmark that scores unfairly points
you at the wrong fixes, so the matcher's fairness is as important as any feature.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.matcher import match_findings, norm, family_match     # noqa: E402
from benchmarks import stats as S                                     # noqa: E402
from benchmarks.extraction import score_extraction                    # noqa: E402


@dataclass
class _Exp:
    section: str = ""
    severity: str = "medium"
    status: str = "non_compliant"
    acceptable_sections: List[str] = field(default_factory=list)


def _f(cite, status="non_compliant", severity="medium"):
    return {"code_id": cite, "source_citation": cite, "status": status, "severity": severity}


# ── normalization / family ───────────────────────────────────

def test_norm_strips_code_prefix():
    assert norm("IBC 1011.5.2") == "1011.5.2"
    assert norm("CBC-7A 504.5") == "504.5"


def test_family_match_ancestor():
    assert family_match("1011.5.2", "1011.5") is True
    assert family_match("1011.5", "1011.6") is False


# ── the fairness win: acceptable_sections set ────────────────

def test_acceptable_sections_lets_a_different_valid_citation_match():
    # GT accepts EITHER the CBC-7A or the CRC citation for the same WUI issue.
    exp = [_Exp(severity="critical",
                acceptable_sections=["CBC-7A 504.5", "CRC R337.7"])]
    # Model cited the OTHER acceptable one — must count as a hit, not a miss.
    res = match_findings(exp, [_f("CRC R337.7", severity="critical")])
    assert len(res.tp) == 1 and not res.fn


def test_family_citation_counts_as_match():
    exp = [_Exp(acceptable_sections=["IBC 1011.5"])]
    res = match_findings(exp, [_f("IBC 1011.5.2")])     # subsection of the accepted section
    assert len(res.tp) == 1


# ── misses / false positives / forbidden ─────────────────────

def test_unmatched_expected_is_a_miss():
    exp = [_Exp(severity="critical", acceptable_sections=["IBC 1004.1"])]
    res = match_findings(exp, [])
    assert len(res.fn) == 1 and not res.tp


def test_unmatched_produced_is_fp_and_queued_for_adjudication():
    res = match_findings([], [_f("IBC 705.8")])
    assert len(res.fp_confirmed) == 1
    assert res.adjudication_queue == res.fp_confirmed


def test_forbidden_flag_is_hard_fp():
    res = match_findings([], [_f("ADA 208.2")], must_not_flag=["ADA 208.2"])
    assert len(res.forbidden) == 1 and not res.fp_confirmed


def test_non_flag_findings_are_ignored():
    # compliant / not_applicable findings aren't scored against expected.
    res = match_findings([_Exp(acceptable_sections=["IBC 1004.1"])],
                         [_f("IBC 1004.1", status="compliant")])
    assert not res.tp and len(res.fn) == 1 and len(res.ignored) == 1


# ── severity / status error tracking ─────────────────────────

def test_matched_issue_with_wrong_severity_is_tp_with_severity_error():
    exp = [_Exp(severity="critical", status="non_compliant",
                acceptable_sections=["IBC 1004.1"])]
    res = match_findings(exp, [_f("IBC 1004.1", status="needs_review", severity="low")])
    assert len(res.tp) == 1                     # found the issue
    assert res.severity_errors == 1             # but mis-rated severity
    assert res.status_errors == 1               # and abstained vs asserted


# ── tier-3 judge hook ────────────────────────────────────────

def test_judge_rescues_a_semantic_match_tier1_missed():
    exp = [_Exp(acceptable_sections=["IBC 1004.1"])]
    produced = [_f("CBC 1004.5")]               # different section, tier-1 miss
    # Without a judge: miss. With a judge that says "same issue": match.
    assert len(match_findings(exp, produced).fn) == 1
    res = match_findings(exp, produced, judge=lambda e, f: True)
    assert len(res.tp) == 1 and not res.fn


# ── stats: bootstrap CIs ─────────────────────────────────────

@dataclass
class _Score:
    tp: int = 0; fp: int = 0; fn: int = 0
    critical_tp: int = 0; critical_fn: int = 0
    forbidden_hits: int = 0; cited_in_corpus: int = 0; total_findings: int = 0


def test_bootstrap_ci_brackets_the_point_and_is_deterministic():
    cases = [_Score(tp=9, fn=1, critical_tp=4, critical_fn=0, cited_in_corpus=9, total_findings=9),
             _Score(tp=7, fn=3, critical_tp=3, critical_fn=1, cited_in_corpus=10, total_findings=10),
             _Score(tp=8, fn=2, critical_tp=5, critical_fn=0, cited_in_corpus=8, total_findings=8),
             _Score(tp=6, fn=4, critical_tp=2, critical_fn=2, cited_in_corpus=6, total_findings=6)]
    agg = S.aggregate(cases, seed=0)
    rec = agg["metrics"]["recall"]
    assert rec["lo"] <= rec["point"] <= rec["hi"]      # CI brackets the point
    assert 0.0 <= rec["lo"] and rec["hi"] <= 1.0
    # Deterministic given the seed.
    assert S.aggregate(cases, seed=0)["metrics"]["recall"] == rec


def test_single_case_has_degenerate_ci():
    agg = S.aggregate([_Score(tp=5, fn=0)], seed=0)
    r = agg["metrics"]["recall"]
    assert r["lo"] == r["point"] == r["hi"] == 1.0


# ── extraction stage metric ──────────────────────────────────

def test_extraction_exact_and_tolerance():
    expected = {"occupancy_type": "R-3", "construction_type": "V-B",
                "building_area": 2400, "stories": 2}
    captured = {"occupancy_type": "r-3", "construction_type": "V-B",
                "building_area": 2450, "stories": 2}     # area within ±5%
    res = score_extraction(expected, captured)
    assert res["accuracy"] == 1.0
    assert res["fields"]["occupancy_type"] and res["fields"]["building_area"]


def test_extraction_flags_wrong_occupancy_and_far_area():
    expected = {"occupancy_type": "R-3", "building_area": 2400}
    captured = {"occupancy_type": "B", "building_area": 5000}   # both wrong
    res = score_extraction(expected, captured)
    assert res["fields"]["occupancy_type"] is False
    assert res["fields"]["building_area"] is False
    assert res["accuracy"] == 0.0


def test_extraction_only_scores_specified_fields():
    res = score_extraction({"occupancy_type": "R-3"}, {"occupancy_type": "R-3", "stories": 9})
    assert res["total"] == 1 and res["accuracy"] == 1.0       # stories not in expected → not scored
