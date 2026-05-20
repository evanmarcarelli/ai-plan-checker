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

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.code_library.corpus_loader import get_corpus


@dataclass
class ExpectedFinding:
    section: str                       # canonical e.g. "ADA 404.2.3" or just "404.2.3"
    severity: str = "medium"
    status: str = "non_compliant"      # what we expect the system to call it
    notes: str = ""                    # human description, not used for matching


@dataclass
class CaseGroundTruth:
    case_id: str
    description: str = ""
    jurisdiction: Dict[str, str] = field(default_factory=dict)  # {"state": "CA", "city": "Altadena"}
    plan_type: str = "residential"
    expected_findings: List[ExpectedFinding] = field(default_factory=list)
    must_not_flag: List[str] = field(default_factory=list)        # sections we should NOT flag
    plan_features: Dict[str, object] = field(default_factory=dict) # for live runs without a PDF


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


# ---- normalization helpers ----

_NORM_RE = re.compile(r"[^a-z0-9.]")

def _norm(s: str) -> str:
    """Normalize a citation for matching: drop the code-prefix word (which
    may itself contain digits like 'T24' or 'CBC-7A'), keep the actual section
    number. Returns e.g. '404.2.3', '210.8a', '4.106.4'."""
    if not s:
        return ""
    s = s.lower().strip()
    # Split off the prefix. Code prefixes are space- or dash-separated and
    # always come BEFORE the section number; the section number is the last
    # whitespace-separated token.
    tokens = re.split(r"\s+", s)
    tail = tokens[-1]
    # If still hyphenated like 'ibc-1011.5.2', take the part after the dash
    if "-" in tail and re.search(r"[a-z]", tail.split("-", 1)[0] or ""):
        tail = tail.split("-", 1)[1]
    return _NORM_RE.sub("", tail)


def _matches(produced_citation: str, expected_section: str) -> bool:
    a = _norm(produced_citation)
    b = _norm(expected_section)
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


# ---- main scoring ----

def score_case(gt: CaseGroundTruth, findings: Sequence[Dict[str, object]]) -> CaseScore:
    """Score one case.

    `findings` is a list of dicts each with keys:
        code_id / source_citation : str
        severity                  : str
        status                    : str   (optional; defaults to non_compliant)
        verified                  : bool  (optional, only used for citation_validity)
    """
    corpus = get_corpus()
    score = CaseScore(case_id=gt.case_id, total_findings=len(findings))

    # Pre-compute expected-section set & critical set
    expected_norm = {_norm(e.section): e for e in gt.expected_findings}
    critical_norm = {_norm(e.section) for e in gt.expected_findings if e.severity == "critical"}
    forbidden_norm = {_norm(s) for s in gt.must_not_flag}

    matched_expected: set = set()
    for f in findings:
        cite = str(f.get("source_citation") or f.get("code_id") or "")
        # citation validity (does this section exist in the real corpus?)
        if corpus.has_section(cite):
            score.cited_in_corpus += 1
        else:
            score.cited_outside_corpus += 1

        # status: only count "non_compliant" or "needs_review" as a real flag
        status = str(f.get("status", "")).lower()
        if status not in ("non_compliant", "needs_review"):
            # not a flag; not scored against expected
            continue

        norm = _norm(cite)
        if norm in forbidden_norm:
            score.forbidden_hits += 1
            continue

        # Match to an expected finding?
        if norm in expected_norm and norm not in matched_expected:
            matched_expected.add(norm)
            score.tp += 1
            if norm in critical_norm:
                score.critical_tp += 1
        else:
            # Don't count "not in expected" against precision unless we're being
            # strict. Be strict: this is a quality bar — only count as TP what
            # the architect explicitly cared about.
            score.fp += 1

    # Anything in expected we didn't match is a false negative
    for norm in expected_norm:
        if norm not in matched_expected:
            score.fn += 1
            if norm in critical_norm:
                score.critical_fn += 1

    return score
