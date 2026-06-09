"""Extraction-accuracy stage metric (BENCHMARK_DESIGN §6).

A wrong occupancy or construction type poisons every downstream department, so
a single end-to-end recall number hides whether a miss was the Surveyor or the
reviewer. This compares the Surveyor's extracted facts (from --live-pdf's
`capture.extraction`) against the labeled truth (`expected_extraction`), so you
can tell "the model misread the plan" apart from "the model reasoned wrong".

Pure + DB-free.
"""
from __future__ import annotations

from typing import Any, Dict


def _norm_str(x: Any):
    return str(x).strip().lower() if x is not None else None


def _num_within(exp: Any, act: Any, tol: float) -> bool:
    if exp is None or act is None:
        return False
    try:
        exp_f, act_f = float(exp), float(act)
    except (TypeError, ValueError):
        return False
    if exp_f == 0:
        return act_f == 0
    return abs(act_f - exp_f) / abs(exp_f) <= tol


def _int_eq(exp: Any, act: Any) -> bool:
    try:
        return act is not None and int(exp) == int(act)
    except (TypeError, ValueError):
        return False


def score_extraction(expected: Dict[str, Any], captured: Dict[str, Any]) -> Dict[str, Any]:
    """Per-field correctness of the Surveyor's extraction. Only fields the
    labeler specified in `expected` are scored — we don't penalize for facts the
    ground truth didn't pin down. Areas/heights match within ±5%; stories and
    the categorical fields match exactly (case-insensitive)."""
    fields: Dict[str, bool] = {}

    for f in ("plan_type", "occupancy_type", "construction_type"):
        if expected.get(f) is not None:
            fields[f] = _norm_str(expected[f]) == _norm_str(captured.get(f))

    for f, tol in (("building_area", 0.05), ("building_height", 0.05)):
        if expected.get(f) is not None:
            fields[f] = _num_within(expected[f], captured.get(f), tol)

    if expected.get("stories") is not None:
        fields["stories"] = _int_eq(expected["stories"], captured.get("stories"))

    correct = int(sum(fields.values()))
    return {
        "fields": fields,
        "correct": correct,
        "total": len(fields),
        "accuracy": correct / len(fields) if fields else 0.0,
    }
