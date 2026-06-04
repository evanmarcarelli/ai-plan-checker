#!/usr/bin/env python3
"""Deterministic-engine eval harness.

Ported from plan-room-ahj/scripts/eval/run-eval.ts. Runs the deterministic
rule engine over a set of ground-truth cases and reports precision / recall /
F1 so accuracy is a measured number, not a vibe.

Each case (cases/*.json) provides structured plan_data + a plan_text blob and
a ground_truth list of {rule_id, expected_status}. expected_status uses the
plan-room vocabulary (pass | fail | warn | info) which maps to the
ai-plan-checker ComplianceStatus enum.

Usage (from backend/, with the venv active):
    python -m scripts.eval.run_eval
    python -m scripts.eval.run_eval --case office-vb-area-violation
    python -m scripts.eval.run_eval --with-gate          # also report post-citation-gate
    python -m scripts.eval.run_eval --min-f1 0.9          # exit non-zero if F1 below

The default (no --with-gate) measures the ENGINE — is the code-math right.
--with-gate additionally measures the engine AFTER the citation gate, which
will differ when the corpus is too thin to verify a numeric citation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Make `app` importable when run as a script from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.code_library.deterministic.engine import evaluate_plan  # noqa: E402
from app.models.schemas import ComplianceStatus, ExtractedPlanData  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"

# ComplianceStatus -> plan-room status vocabulary.
_STATUS_TO_PR = {
    ComplianceStatus.COMPLIANT: "pass",
    ComplianceStatus.NON_COMPLIANT: "fail",
    ComplianceStatus.NEEDS_REVIEW: "warn",
    ComplianceStatus.NOT_APPLICABLE: "info",
}


def classify(expected: str, actual: str) -> str:
    """Confusion-matrix bucket for one (case, rule) comparison.

    Extends run-eval.ts classify() to handle warn/info expectations (the TS
    ground truth only ever used fail/pass). A "fail" we should have caught and
    did is a true positive; missing it is a false negative; flagging a clean
    or soft rule as a hard fail is a false positive. An exact match on a soft
    status (warn/info) is a correct call (counted like a true negative).
    """
    if expected == actual:
        return "tp" if expected == "fail" else "tn"
    if expected == "fail":          # we missed a real violation
        return "fn"
    if actual == "fail":            # we hard-failed something that shouldn't
        return "fp"
    return "wrong_status"           # pass<->warn<->info disagreement


def prf(tp: int, fp: int, fn: int):
    p = None if (tp + fp) == 0 else tp / (tp + fp)
    r = None if (tp + fn) == 0 else tp / (tp + fn)
    f1 = None if (p is None or r is None or (p + r) == 0) else 2 * p * r / (p + r)
    return p, r, f1


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def build_plan_data(case: dict) -> ExtractedPlanData:
    raw = dict(case.get("plan_data") or {})
    plan_text = case.get("plan_text") or ""
    raw.setdefault("raw_text_by_page", {1: plan_text} if plan_text else {})
    return ExtractedPlanData(**raw)


def run_case(case: dict, with_gate: bool) -> Dict[str, str]:
    """Return {rule_id: actual_status_in_pr_vocab} for every rule the case
    has ground truth for."""
    plan_data = build_plan_data(case)
    findings = evaluate_plan(
        plan_data,
        overlays=case.get("overlays"),
        ladbs_sfd=bool(case.get("ladbs_sfd")),
        include_passing=True,
    )

    if with_gate:
        # Lazy import so the no-gate path needs no corpus load.
        from app.code_library.adapter import CorpusCodeSource
        from app.code_library.deterministic.citation_gate import apply_citation_gate
        apply_citation_gate(findings, CorpusCodeSource(), enforce=True)

    by_rule = {f.code_requirement.code_id: _STATUS_TO_PR[f.status] for f in findings}
    return by_rule


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="run_eval")
    ap.add_argument("--case", help="run only the case with this slug")
    ap.add_argument("--with-gate", action="store_true",
                    help="apply the citation gate before scoring")
    ap.add_argument("--min-f1", type=float, default=None,
                    help="exit non-zero if overall F1 is below this")
    ap.add_argument("--verbose", action="store_true", help="print per-rule mismatches")
    args = ap.parse_args(argv)

    files = sorted(CASES_DIR.glob("*.json"))
    if args.case:
        files = [f for f in files if f.stem == args.case]
        if not files:
            print(f"No case named {args.case!r} in {CASES_DIR}", file=sys.stderr)
            return 2

    overall = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "wrong_status": 0}
    per_case_rows: List[tuple] = []
    mismatches: List[str] = []

    for fp_ in files:
        case = json.loads(fp_.read_text())
        actual_by_rule = run_case(case, args.with_gate)
        c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "wrong_status": 0}
        for gt in case.get("ground_truth", []):
            rid = gt["rule_id"]
            expected = gt["expected_status"]
            actual = actual_by_rule.get(rid, "info")  # rule didn't fire -> info
            bucket = classify(expected, actual)
            c[bucket] += 1
            overall[bucket] += 1
            if bucket in ("fp", "fn", "wrong_status"):
                mismatches.append(
                    f"  {case['slug']:34} {rid:22} expected={expected:5} actual={actual:5} ({bucket})"
                )
        p, r, f1 = prf(c["tp"], c["fp"], c["fn"])
        per_case_rows.append((case["slug"], c, p, r, f1))

    # ---- report ----
    print("=" * 78)
    print(f"Deterministic engine eval{'  (+ citation gate)' if args.with_gate else ''}")
    print("=" * 78)
    print(f"{'case':36} {'tp':>3} {'fp':>3} {'fn':>3} {'tn':>3}  {'prec':>6} {'rec':>6} {'f1':>6}")
    for slug, c, p, r, f1 in per_case_rows:
        print(f"{slug:36} {c['tp']:>3} {c['fp']:>3} {c['fn']:>3} {c['tn']:>3}  "
              f"{_fmt(p):>6} {_fmt(r):>6} {_fmt(f1):>6}")

    p, r, f1 = prf(overall["tp"], overall["fp"], overall["fn"])
    print("-" * 78)
    print(f"{'OVERALL':36} {overall['tp']:>3} {overall['fp']:>3} {overall['fn']:>3} "
          f"{overall['tn']:>3}  {_fmt(p):>6} {_fmt(r):>6} {_fmt(f1):>6}")
    if overall["wrong_status"]:
        print(f"  wrong_status (e.g. expected warn, got something else): {overall['wrong_status']}")

    if (args.verbose or args.min_f1 is not None) and mismatches:
        print("\nMismatches:")
        print("\n".join(mismatches))

    if args.min_f1 is not None:
        if f1 is None or f1 < args.min_f1:
            print(f"\nFAIL: overall F1 {_fmt(f1)} < required {args.min_f1}", file=sys.stderr)
            return 1
        print(f"\nPASS: overall F1 {_fmt(f1)} >= {args.min_f1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
