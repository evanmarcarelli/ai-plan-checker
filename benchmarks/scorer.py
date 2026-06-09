"""Scoring functions for a single benchmark case.

Metrics produced:

  precision        TP / (TP + FP)   on flagged findings vs expected
  recall           TP / (TP + FN)   ditto
  f1               harmonic mean
  citation_valid   fraction of findings whose code_id exists in the real corpus
                   (this is the headline anti-hallucination metric)
  critical_recall  recall restricted to expected findings of severity=critical
                   (the only metric an architect actually cares about)
  forbidden_hits   number of findings on the must_not_flag list (lower=better)

A finding "matches" an expected finding if it cites the same section number
(case-insensitive, dashes/spaces normalized) and has compatible status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.code_library.corpus_loader import get_corpus


@dataclass
class ExpectedFinding:
    section: str                       # canonical e.g. "ADA 404.2.3" or just "404.2.3"
    severity: str = "medium"
    status: str = "non_compliant"      # what we expect the system to call it
    notes: str = ""                    # human description, not used for matching
    # --- extended (BENCHMARK_DESIGN §4); optional, back-compatible ---
    issue_id: str = ""                 # stable id; match on the issue, not the string
    acceptable_sections: List[str] = field(default_factory=list)  # any of these = correct
    objectivity: str = "hard"          # hard (objective) | soft (judgment) — scored apart
    acceptance_criteria: str = ""      # what a correct AI finding must convey (for the judge)
    location: Dict[str, str] = field(default_factory=dict)        # {sheet, note}


@dataclass
class CaseGroundTruth:
    case_id: str
    description: str = ""
    jurisdiction: Dict[str, str] = field(default_factory=dict)  # {"state": "CA", "city": "Altadena"}
    plan_type: str = "residential"
    expected_findings: List[ExpectedFinding] = field(default_factory=list)
    must_not_flag: List[str] = field(default_factory=list)        # sections we should NOT flag
    plan_features: Dict[str, object] = field(default_factory=dict) # for live runs without a PDF
    # --- extended (BENCHMARK_DESIGN §3/§4); optional, back-compatible ---
    tier: str = "A"                    # A synthetic | B expert-labeled PDF | C correction letter
    split: str = "dev"                 # dev | holdout
    source: str = ""                   # provenance of the ground truth
    input_quality: str = "synthetic"   # synthetic | vector | scanned | mixed | missing_title_sheet
    labelers: List[str] = field(default_factory=list)
    # The Surveyor should extract these from the PDF — the extraction stage metric.
    expected_extraction: Dict[str, object] = field(default_factory=dict)


@dataclass
class CaseScore:
    case_id: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    critical_tp: int = 0
    critical_fn: int = 0
    forbidden_hits: int = 0
    total_findings: int = 0
    cited_in_corpus: int = 0
    cited_outside_corpus: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def citation_validity(self) -> float:
        d = self.total_findings
        return self.cited_in_corpus / d if d else 0.0

    @property
    def critical_recall(self) -> float:
        d = self.critical_tp + self.critical_fn
        return self.critical_tp / d if d else 0.0

    def as_row(self) -> List[str]:
        return [
            self.case_id,
            f"{self.precision:.2f}",
            f"{self.recall:.2f}",
            f"{self.f1:.2f}",
            f"{self.critical_recall:.2f}",
            f"{self.citation_validity:.2f}",
            str(self.forbidden_hits),
            f"{self.tp}/{self.fp}/{self.fn}",
            str(self.total_findings),
        ]


# ---- normalization helpers (kept re-exported for back-compat) ----

from benchmarks.matcher import norm as _norm, family_match, match_findings  # noqa: E402


def _matches(produced_citation: str, expected_section: str) -> bool:
    return family_match(_norm(produced_citation), _norm(expected_section))


# ---- main scoring ----

def _is_critical(e) -> bool:
    return str(getattr(e, "severity", "")).lower() == "critical"


def score_case(gt: CaseGroundTruth, findings: Sequence[Dict[str, object]]) -> CaseScore:
    """Score one case via the issue-level matcher (matcher.match_findings).

    `findings` is a list of dicts each with keys:
        code_id / source_citation : str
        severity                  : str
        status                    : str   (optional; defaults to non_compliant)
        verified                  : bool  (optional, only used for citation_validity)
    """
    corpus = get_corpus()
    score = CaseScore(case_id=gt.case_id, total_findings=len(findings))

    # Citation validity: does each cited section exist in the real corpus?
    for f in findings:
        cite = str(f.get("source_citation") or f.get("code_id") or "")
        if corpus.has_section(cite):
            score.cited_in_corpus += 1
        else:
            score.cited_outside_corpus += 1

    # Fair, issue-level matching (acceptable_sections set + family match).
    res = match_findings(gt.expected_findings, findings, gt.must_not_flag)
    score.tp = len(res.tp)
    score.fp = len(res.fp_confirmed)
    score.fn = len(res.fn)
    score.forbidden_hits = len(res.forbidden)
    score.critical_tp = sum(1 for m in res.tp if _is_critical(m.expected))
    score.critical_fn = sum(1 for e in res.fn if _is_critical(e))
    return score
