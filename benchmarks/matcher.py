"""Issue-level matcher (BENCHMARK_DESIGN §5).

Bipartite-match produced findings to ground-truth findings by *issue*, not by
exact string. The old scorer matched a single `section` string; an examiner's
`CBC-7A 704A.1` vs the AI's `CRC R337.7` (same WUI siding issue) scored as a
miss. This matcher fixes that with:

  Tier 1 — exact/family match over the GT's `acceptable_sections` SET.
  Tier 3 — an optional, injectable judge(expected, produced)->bool for the
           semantic matches the labeler didn't enumerate (LLM or human; kept
           out of the core so the deterministic path stays free + testable).

Unmatched produced flags are conservatively counted as false positives AND
surfaced for adjudication (a human may later reclassify a real-but-unlabeled
flag — incomplete ground truth, BENCHMARK_DESIGN §2). The matcher itself never
calls a network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

_NORM_RE = re.compile(r"[^a-z0-9.]")
FLAG_STATUSES = ("non_compliant", "needs_review")


def norm(s: str) -> str:
    """Normalize a citation for matching: drop the code-prefix word (which may
    itself contain digits like 'T24'/'CBC-7A'), keep the section number.
    'IBC 1011.5.2' -> '1011.5.2'; 'CBC-7A 704A.1' -> '704a.1'."""
    if not s:
        return ""
    s = s.lower().strip()
    tail = re.split(r"\s+", s)[-1]
    if "-" in tail and re.search(r"[a-z]", tail.split("-", 1)[0] or ""):
        tail = tail.split("-", 1)[1]
    return _NORM_RE.sub("", tail)


def family_match(a: str, b: str) -> bool:
    """True if two normalized sections are the same or one is an ancestor of the
    other (1011.5 ~ 1011.5.2)."""
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _cite(f: Dict[str, Any]) -> str:
    return str(f.get("source_citation") or f.get("code_id") or "")


def _is_flag(f: Dict[str, Any]) -> bool:
    return str(f.get("status", "")).lower() in FLAG_STATUSES


def _acceptable_norms(e: Any) -> List[str]:
    accs = getattr(e, "acceptable_sections", None) or [getattr(e, "section", "")]
    return [norm(x) for x in accs if x]


@dataclass
class Match:
    expected: Any
    produced: Dict[str, Any]
    severity_match: bool       # did the model get the severity right?
    status_match: bool         # non_compliant vs needs_review agreement


@dataclass
class MatchResult:
    tp: List[Match] = field(default_factory=list)
    fn: List[Any] = field(default_factory=list)            # unmatched expected (misses)
    forbidden: List[Dict[str, Any]] = field(default_factory=list)  # must_not_flag hits
    fp_confirmed: List[Dict[str, Any]] = field(default_factory=list)  # unmatched produced
    fp_unlabeled: List[Dict[str, Any]] = field(default_factory=list)  # set by adjudication
    ignored: List[Dict[str, Any]] = field(default_factory=list)        # non-flag produced

    @property
    def severity_errors(self) -> int:
        return sum(1 for m in self.tp if not m.severity_match)

    @property
    def status_errors(self) -> int:
        return sum(1 for m in self.tp if not m.status_match)

    @property
    def adjudication_queue(self) -> List[Dict[str, Any]]:
        """Unmatched produced flags a human should rule on (real-but-unlabeled
        vs genuine false positive)."""
        return list(self.fp_confirmed)


def match_findings(
    expected: Sequence[Any],
    produced: Sequence[Dict[str, Any]],
    must_not_flag: Sequence[str] = (),
    *,
    judge: Optional[Callable[[Any, Dict[str, Any]], bool]] = None,
) -> MatchResult:
    """Match produced findings to expected findings. Greedy, most-confident
    tier first; each expected and each produced flag is consumed at most once."""
    res = MatchResult()

    # 1. Split flags from non-flags (only non_compliant / needs_review are scored).
    flags: List[Dict[str, Any]] = []
    for f in produced:
        (flags if _is_flag(f) else res.ignored).append(f)

    # 2. Forbidden (must_not_flag) hits are hard false positives — pull them out.
    forbidden_norms = {norm(s) for s in must_not_flag}
    pool: List[Dict[str, Any]] = []
    for f in flags:
        (res.forbidden if norm(_cite(f)) in forbidden_norms else pool).append(f)

    used = [False] * len(pool)

    def _consume(expected_list: List[Any], predicate) -> List[Any]:
        still: List[Any] = []
        for e in expected_list:
            hit = next((i for i, f in enumerate(pool)
                        if not used[i] and predicate(e, f)), None)
            if hit is None:
                still.append(e)
            else:
                used[hit] = True
                f = pool[hit]
                sev = str(getattr(e, "severity", "")).lower() == str(f.get("severity", "")).lower()
                stat = str(getattr(e, "status", "")).lower() == str(f.get("status", "")).lower()
                res.tp.append(Match(e, f, sev, stat))
        return still

    # 3. Tier 1: exact/family over acceptable_sections.
    remaining = _consume(list(expected), lambda e, f: any(
        family_match(norm(_cite(f)), en) for en in _acceptable_norms(e)))

    # 4. Tier 3: optional judge for semantic matches the labeler didn't enumerate.
    if judge is not None and remaining:
        def _judged(e, f):
            try:
                return bool(judge(e, f))
            except Exception:
                return False
        remaining = _consume(remaining, _judged)

    # 5. Leftovers.
    res.fn = remaining
    res.fp_confirmed = [pool[i] for i in range(len(pool)) if not used[i]]
    return res
