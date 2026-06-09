"""Run the REAL pipeline on a plan.pdf and capture per-stage outputs.

This is the mode the harness was missing: the synthetic `plan_features.yaml`
path feeds the department agents pre-extracted data, so it never exercises the
Surveyor — your #1 real-world failure source. `--live-pdf` runs the actual
Surveyor (PyMuPDF + vision/OCR) end to end and records what it extracted, so
the extraction-accuracy stage metric (BENCHMARK_DESIGN §6) becomes measurable.

`findings_from_report` / `extraction_from_report` are pure so they're unit-
tested without a PDF or any API calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class StageCapture:
    case_id: str
    extraction: Dict[str, Any] = field(default_factory=dict)     # Surveyor output
    jurisdiction: Dict[str, Any] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)  # scorer-shaped
    logs: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_sec: float = 0.0
    error: Optional[str] = None


def _val(x):
    """Unwrap enums to their .value for stable JSON."""
    return x.value if hasattr(x, "value") else x


def findings_from_report(report) -> List[Dict[str, Any]]:
    """Flatten a ComplianceReport into the finding-dict shape score_case expects."""
    out: List[Dict[str, Any]] = []
    for f in (getattr(report, "findings", None) or []):
        req = getattr(f, "code_requirement", None)
        code_id = getattr(req, "code_id", "") if req else ""
        out.append({
            "code_id": code_id,
            "source_citation": getattr(f, "source_citation", None) or code_id,
            "severity": getattr(f, "severity", "medium"),
            "status": _val(getattr(f, "status", "")) or "",
            "verified": getattr(f, "verified", False),
        })
    return out


def extraction_from_report(report) -> Dict[str, Any]:
    """Pull the Surveyor's extracted plan facts for the extraction-accuracy metric."""
    pd = getattr(report, "plan_data", None)
    if not pd:
        return {}
    return {
        "plan_type": _val(getattr(pd, "plan_type", None)),
        "occupancy_type": getattr(pd, "occupancy_type", None),
        "construction_type": getattr(pd, "construction_type", None),
        "building_area": getattr(pd, "building_area", None),
        "stories": getattr(pd, "stories", None),
        "building_height": getattr(pd, "building_height", None),
    }


def jurisdiction_from_report(report) -> Dict[str, Any]:
    j = getattr(report, "jurisdiction", None)
    if not j:
        return {}
    return {
        "state": getattr(j, "state_code", None) or getattr(j, "state", None),
        "city": getattr(j, "city", None),
        "county": getattr(j, "county", None),
    }


async def run_pipeline_capture(plan_pdf: str, case_id: str) -> StageCapture:
    """Run the full pipeline on a real PDF and capture extraction + findings +
    logs + timing. Errors are captured (not raised) so one bad case can't sink
    a whole benchmark run."""
    from app.agents.workflow import PlanCheckerWorkflow
    from app.models.schemas import ProcessingJob, JobStatus, AgentLog

    cap = StageCapture(case_id=case_id)
    logs: List[Dict[str, Any]] = []

    async def on_log(log: "AgentLog"):
        logs.append({"agent": log.agent, "level": log.level, "message": log.message})

    job = ProcessingJob(
        job_id=f"bench-{case_id}",
        status=JobStatus.PROCESSING,
        filename=f"{case_id}.pdf",
        file_size=0,
        created_at=datetime.utcnow(),
    )
    start = datetime.utcnow()
    try:
        report = await PlanCheckerWorkflow().run(job, plan_pdf, log_callback=on_log)
        cap.findings = findings_from_report(report)
        cap.extraction = extraction_from_report(report)
        cap.jurisdiction = jurisdiction_from_report(report)
    except Exception as e:  # noqa: BLE001 — capture, don't crash the run
        cap.error = str(e)
    cap.logs = logs
    cap.elapsed_sec = (datetime.utcnow() - start).total_seconds()
    return cap
