"""Benchmark runner — discovers cases in benchmarks/cases/, runs them, scores them,
prints a markdown scoreboard.

Cases live in:  benchmarks/cases/<case_id>/
                    ground_truth.yaml
                    plan_features.yaml   (for live runs without a PDF)
                    plan.pdf             (optional, for live runs against a real PDF)
                    findings_cache.json  (populated by --save-cache)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Make backend importable when run from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # PyYAML

from benchmarks.scorer import CaseGroundTruth, ExpectedFinding, score_case
from tabulate import tabulate

CASES_DIR = Path(__file__).parent / "cases"


# ---------- Case loading ----------

def load_case(case_dir: Path) -> CaseGroundTruth:
    gt_path = case_dir / "ground_truth.yaml"
    feats_path = case_dir / "plan_features.yaml"
    with gt_path.open() as f:
        raw = yaml.safe_load(f) or {}
    features = {}
    if feats_path.exists():
        with feats_path.open() as f:
            features = yaml.safe_load(f) or {}

    expected = [
        ExpectedFinding(
            section=e["section"],
            severity=e.get("severity", "medium"),
            status=e.get("status", "non_compliant"),
            notes=e.get("notes", ""),
        )
        for e in (raw.get("expected_findings") or [])
    ]
    return CaseGroundTruth(
        case_id=case_dir.name,
        description=raw.get("description", ""),
        jurisdiction=raw.get("jurisdiction", {}) or {},
        plan_type=raw.get("plan_type", "residential"),
        expected_findings=expected,
        must_not_flag=raw.get("must_not_flag", []) or [],
        plan_features=features,
    )


def discover_cases() -> List[CaseGroundTruth]:
    if not CASES_DIR.exists():
        return []
    return [load_case(p) for p in sorted(CASES_DIR.iterdir()) if (p / "ground_truth.yaml").exists()]


# ---------- Finding sources ----------

def dry_run_findings(gt: CaseGroundTruth) -> List[Dict]:
    """Emit one finding per expected finding (perfect oracle).
    This validates the corpus + scoring infrastructure WITHOUT calling the LLM.
    A passing dry run with citation_validity=1.0 means every expected section
    is present in our real code corpus."""
    return [
        {
            "code_id": e.section,
            "source_citation": e.section,
            "severity": e.severity,
            "status": e.status,
            "verified": True,
        }
        for e in gt.expected_findings
    ]


def cached_findings(gt: CaseGroundTruth) -> Optional[List[Dict]]:
    cache_path = CASES_DIR / gt.case_id / "findings_cache.json"
    if not cache_path.exists():
        return None
    with cache_path.open() as f:
        return json.load(f)


async def live_findings(gt: CaseGroundTruth) -> List[Dict]:
    """Run the real pipeline against synthetic plan features (no real PDF).

    This calls the dept agents with their canonical code list for the jurisdiction
    and the plan features from plan_features.yaml. Costs real money.
    """
    from app.agents.departments import ALL_DEPARTMENTS
    from app.code_library.adapter import CorpusCodeSource
    from app.models.schemas import ExtractedPlanData, PlanType

    src = CorpusCodeSource()
    state = gt.jurisdiction.get("state")
    city = gt.jurisdiction.get("city")
    amendments = src.get_jurisdiction_amendments(state, city)
    code_version = src.get_code_version(state)

    feats = gt.plan_features or {}
    plan_data = ExtractedPlanData(
        project_name=feats.get("project_name", gt.case_id),
        project_address=feats.get("project_address", f"{city or ''} {state or ''}"),
        plan_type=PlanType(feats.get("plan_type", gt.plan_type)) if feats.get("plan_type") or gt.plan_type else PlanType.UNKNOWN,
        occupancy_type=feats.get("occupancy_type"),
        construction_type=feats.get("construction_type"),
        building_height=feats.get("building_height"),
        building_area=feats.get("building_area"),
        stories=feats.get("stories"),
        dimensions=feats.get("dimensions", {}) or {},
        materials=feats.get("materials", []) or [],
        raw_text_by_page=feats.get("raw_text_by_page", {}) or {},
    )

    all_findings_out: List[Dict] = []
    for cls in ALL_DEPARTMENTS:
        dept = cls()
        codes = src.get_codes_by_category(dept.category, state=state, city=city)
        if not codes:
            continue
        review = await dept.review(plan_data, codes, amendments, code_version)
        for f in review.findings:
            all_findings_out.append({
                "code_id": f.code_requirement.code_id,
                "source_citation": f.source_citation or f.code_requirement.code_id,
                "severity": f.severity,
                "status": f.status.value if hasattr(f.status, "value") else str(f.status),
                "verified": f.verified,
            })
    return all_findings_out


# ---------- Main ----------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmarks")
    ap.add_argument("--case", help="run only this case_id", default=None)
    ap.add_argument("--live", action="store_true", help="run real pipeline (costs $)")
    ap.add_argument("--from-cache", action="store_true",
                    help="score findings_cache.json instead of running")
    ap.add_argument("--save-cache", action="store_true",
                    help="save live results to findings_cache.json")
    ap.add_argument("--json", action="store_true", help="emit raw json summary")
    args = ap.parse_args(argv)

    cases = discover_cases()
    if args.case:
        cases = [c for c in cases if c.case_id == args.case]
    if not cases:
        print("No benchmark cases found.")
        return 1

    rows = []
    json_out = {"mode": "live" if args.live else ("cache" if args.from_cache else "dry"), "cases": []}
    for gt in cases:
        # Source of findings
        findings: List[Dict]
        if args.live:
            findings = asyncio.run(live_findings(gt))
            if args.save_cache:
                (CASES_DIR / gt.case_id / "findings_cache.json").write_text(json.dumps(findings, indent=2))
        elif args.from_cache:
            cached = cached_findings(gt)
            if cached is None:
                print(f"  [skip] {gt.case_id}: no findings_cache.json")
                continue
            findings = cached
        else:
            findings = dry_run_findings(gt)

        score = score_case(gt, findings)
        rows.append(score.as_row())
        json_out["cases"].append({
            "case_id": score.case_id,
            "precision": score.precision,
            "recall": score.recall,
            "f1": score.f1,
            "critical_recall": score.critical_recall,
            "citation_validity": score.citation_validity,
            "forbidden_hits": score.forbidden_hits,
            "tp": score.tp, "fp": score.fp, "fn": score.fn,
            "total_findings": score.total_findings,
        })

    headers = ["case", "P", "R", "F1", "Crit-R", "Cite✓", "Forbid", "TP/FP/FN", "N"]
    print()
    print(tabulate(rows, headers=headers, tablefmt="github"))
    print()
    print(f"mode = {json_out['mode']}    cases scored = {len(rows)}")
    if args.json:
        print(json.dumps(json_out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
