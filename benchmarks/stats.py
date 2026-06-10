"""Aggregate metrics with bootstrap confidence intervals (BENCHMARK_DESIGN §6).

A point estimate from a handful of plans is a lie of precision. This pools
per-case scores into overall rates AND attaches a 95% CI by **resampling
plans** (not findings — findings within one plan are correlated, so resampling
findings would understate the interval). The output is the honest sentence:
"critical recall 0.96 (CI 0.92–0.98, n=42)".
"""
from __future__ import annotations

import random
from typing import Callable, Dict, List, Sequence, Tuple

# A "case score" here is any object exposing tp/fp/fn/critical_tp/critical_fn/
# forbidden_hits/cited_in_corpus/total_findings (i.e. scorer.CaseScore).

# Below these, the confidence intervals are too wide to support ANY claim — the
# harness must refuse to render a ship verdict (BENCHMARK_DESIGN §3/§6).
MIN_CASES = 20
MIN_CRITICAL_FINDINGS = 30


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def pooled_precision(cases: Sequence) -> float:
    tp = sum(c.tp for c in cases); fp = sum(c.fp for c in cases)
    return _ratio(tp, tp + fp)


def pooled_recall(cases: Sequence) -> float:
    tp = sum(c.tp for c in cases); fn = sum(c.fn for c in cases)
    return _ratio(tp, tp + fn)


def pooled_critical_recall(cases: Sequence) -> float:
    tp = sum(c.critical_tp for c in cases); fn = sum(c.critical_fn for c in cases)
    return _ratio(tp, tp + fn)


def pooled_citation_validity(cases: Sequence) -> float:
    ok = sum(c.cited_in_corpus for c in cases)
    n = sum(c.total_findings for c in cases)
    return _ratio(ok, n)


def bootstrap_ci(
    cases: Sequence,
    rate_fn: Callable[[Sequence], float],
    *,
    n: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> Tuple[float, float, float]:
    """(point, lo, hi) for a pooled rate, resampling cases with replacement.
    Deterministic given `seed` so CI is reproducible across runs."""
    cases = list(cases)
    point = rate_fn(cases)
    k = len(cases)
    if k <= 1:
        return (point, point, point)   # one case → no interval to estimate
    rng = random.Random(seed)
    samples = sorted(
        rate_fn([cases[rng.randrange(k)] for _ in range(k)]) for _ in range(n)
    )
    lo = samples[max(0, int((alpha / 2) * n))]
    hi = samples[min(n - 1, int((1 - alpha / 2) * n))]
    return (point, lo, hi)


def aggregate(cases: Sequence, *, seed: int = 0) -> Dict[str, object]:
    """Pooled metrics with 95% CIs + the raw totals that justify them."""
    metrics = {
        "precision": bootstrap_ci(cases, pooled_precision, seed=seed),
        "recall": bootstrap_ci(cases, pooled_recall, seed=seed),
        "critical_recall": bootstrap_ci(cases, pooled_critical_recall, seed=seed),
        "citation_validity": bootstrap_ci(cases, pooled_citation_validity, seed=seed),
    }
    crit_n = sum(c.critical_tp for c in cases) + sum(c.critical_fn for c in cases)
    totals = {
        "cases": len(cases),
        "tp": sum(c.tp for c in cases),
        "fp": sum(c.fp for c in cases),
        "fn": sum(c.fn for c in cases),
        "critical_tp": sum(c.critical_tp for c in cases),
        "critical_fn": sum(c.critical_fn for c in cases),
        "forbidden_hits": sum(c.forbidden_hits for c in cases),
        "findings": sum(c.total_findings for c in cases),
    }
    # Is there enough data to quote a number at all?
    sufficient = len(cases) >= MIN_CASES and crit_n >= MIN_CRITICAL_FINDINGS
    return {"metrics": {k: {"point": p, "lo": lo, "hi": hi}
                        for k, (p, lo, hi) in metrics.items()},
            "totals": totals,
            "sufficient": sufficient}


def format_aggregate(agg: Dict[str, object]) -> str:
    """One-line-per-metric human summary: 'critical_recall 0.96 (0.92–0.98)'."""
    out: List[str] = []
    t = agg["totals"]
    crit_n = t["critical_tp"] + t["critical_fn"]
    if not agg.get("sufficient", False):
        out.append(
            f"!! INSUFFICIENT DATA — {t['cases']} cases / {crit_n} critical findings "
            f"(need >= {MIN_CASES} / {MIN_CRITICAL_FINDINGS}). The CIs below are NOT "
            f"meaningful; do NOT quote these numbers or make a ship decision."
        )
        out.append("")
    m = agg["metrics"]
    for key in ("critical_recall", "recall", "precision", "citation_validity"):
        v = m[key]
        out.append(f"{key:18} {v['point']:.2f}  (95% CI {v['lo']:.2f}-{v['hi']:.2f})")
    out.append(f"n = {t['cases']} cases, {t['findings']} findings, "
               f"{t['fn']} misses ({t['critical_fn']} critical), "
               f"{t['forbidden_hits']} forbidden")
    return "\n".join(out)
