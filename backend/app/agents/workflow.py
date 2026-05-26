import asyncio
import uuid
from datetime import datetime
from typing import Dict, Any, Callable, List, Optional
from app.agents.surveyor import SurveyorAgent
from app.agents.librarian import LibrarianAgent
from app.agents.departments import ALL_DEPARTMENTS, DepartmentReviewer
from app.models.schemas import (
    ProcessingJob, AgentLog, ComplianceReport, ComplianceFinding,
    ComplianceSummary, ComplianceStatus, DepartmentReview,
)
from app.code_library.adapter import CorpusCodeSource
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Cap how many department reviewers run concurrently. The full set is 10.
# Render Free has tight CPU/RAM/network limits that kill background tasks
# stone-dead when several outbound HTTPS calls overlap. Empirically 3 in
# flight is still too many on Free — the dyno hangs after a couple
# completions. 2 is the safe ceiling for Free; bump to 5–10 the moment
# the founder upgrades to a Starter ($7/mo) or larger dyno.
DEPARTMENT_CONCURRENCY = 2


class PlanCheckerWorkflow:
    """Orchestrates Surveyor → Librarian → parallel Department reviewers → Synthesis."""

    def __init__(self):
        self.surveyor = SurveyorAgent()
        self.librarian = LibrarianAgent()
        self.departments: List[DepartmentReviewer] = [cls() for cls in ALL_DEPARTMENTS]
        # Real BM25 retrieval over the JSONL corpus — replaces the hardcoded
        # BUILDING_CODES_DB. Findings emitted by the agents are now grounded
        # in verbatim code text and the cited section numbers are verified
        # against this corpus before being returned to the user.
        self.code_db = CorpusCodeSource()

    async def run(
        self,
        job: ProcessingJob,
        file_path: str,
        log_callback: Optional[Callable] = None,
    ) -> ComplianceReport:

        async def emit(agent: str, message: str, level: str = "info", data: dict = None):
            log = AgentLog(
                timestamp=datetime.utcnow(),
                agent=agent,
                level=level,
                message=message,
                data=data or {},
            )
            if log_callback:
                await log_callback(log)
            else:
                job.logs.append(log)
            logger.info(f"[{agent}] {message}")

        state: Dict[str, Any] = {"file_path": file_path}

        # ----- SURVEYOR -----
        job.current_agent = "Surveyor"
        job.progress = 5
        await emit("Surveyor", "Starting PDF extraction and jurisdiction identification...")
        try:
            surveyor_result = await self.surveyor.execute(state)
            state.update(surveyor_result)
            j = state["jurisdiction"]
            pd = state["plan_data"]
            await emit("Surveyor", f"PDF extracted: {len(pd.raw_text_by_page)} pages processed")
            await emit(
                "Surveyor",
                f"Jurisdiction: {j.city or 'Unknown'}, {j.state or 'Unknown'} (confidence {j.confidence:.0%})",
                data={"city": j.city, "state": j.state_code, "confidence": j.confidence},
            )
            if j.seismic_zone:
                await emit("Surveyor", f"Seismic Zone: {j.seismic_zone}")
            if j.wind_zone:
                await emit("Surveyor", f"Wind Zone: {j.wind_zone}")
            await emit(
                "Surveyor",
                f"Plan type: {pd.plan_type.value} | Occupancy: {pd.occupancy_type or 'TBD'} | Construction: {pd.construction_type or 'TBD'}",
            )
            job.agents_completed.append("Surveyor")
            job.progress = 15
        except Exception as e:
            await emit("Surveyor", f"Surveyor failed: {e}", level="error")
            raise

        # ----- LIBRARIAN -----
        job.current_agent = "Librarian"
        await emit("Librarian", "Retrieving applicable codes for jurisdiction...")
        try:
            librarian_result = await self.librarian.execute(state)
            state.update(librarian_result)
            all_codes = state["code_requirements"]
            amendments = state.get("jurisdiction_amendments", [])
            code_version = state.get("code_version", "2021 IBC")
            await emit(
                "Librarian",
                f"Retrieved {len(all_codes)} applicable code requirements",
                data={"code_count": len(all_codes), "version": code_version},
            )
            await emit("Librarian", f"Applicable code: {code_version}")
            for a in amendments:
                await emit("Librarian", f"Local amendment: {a}")
            job.agents_completed.append("Librarian")
            job.progress = 25
        except Exception as e:
            await emit("Librarian", f"Librarian failed: {e}", level="error")
            raise

        # ----- PARALLEL DEPARTMENT REVIEWS -----
        # Reset current_agent so the UI doesn't keep saying "Librarian
        # working..." for the full parallel phase. The 10 reviewers fire
        # together; there is no single current agent.
        job.current_agent = None
        await emit(
            "Coordinator",
            f"Dispatching to {len(self.departments)} department reviewers in parallel...",
        )

        # Pull codes per department from the FULL applicable code set
        # (the Librarian's refined subset is fine for context, but each dept
        # filters from the canonical CodeDatabase to ensure category coverage)
        full_codes = self.code_db.get_applicable_codes(
            state=j.state_code,
            city=j.city,
            plan_type=pd.plan_type.value if pd.plan_type else "commercial",
        )
        codes_by_category: Dict[str, List] = {}
        for c in full_codes:
            codes_by_category.setdefault(c.category, []).append(c)

        # Bounded concurrency: limit the parallel reviewers so Render Free
        # is not asked to juggle 10 simultaneous outbound HTTPS calls.
        sem = asyncio.Semaphore(DEPARTMENT_CONCURRENCY)

        async def run_one(dept: DepartmentReviewer) -> DepartmentReview:
            dept_codes = codes_by_category.get(dept.category, [])
            await emit(dept.department_name, f"Starting review ({len(dept_codes)} codes)...")
            async with sem:
                return await _do_review(dept, dept_codes)

        async def _do_review(dept: DepartmentReviewer, dept_codes: list) -> DepartmentReview:
            try:
                review = await dept.review(pd, dept_codes, amendments, code_version)
                s = review.summary
                # If the LLM call failed silently and we fell back to the
                # mock response, every requirement comes back as needs_review.
                # Surface the underlying error so the user can see what went
                # wrong in the Agent Logs tab.
                if dept.last_llm_error:
                    await emit(
                        dept.department_name,
                        f"LLM call failed; findings fell back to needs_review. "
                        f"Underlying error: {dept.last_llm_error}",
                        level="error",
                        data={"llm_error": dept.last_llm_error},
                    )
                # Mark this department as done IN REAL TIME and bump progress.
                # Without this the UI stays at 25% / "Librarian working..." for
                # the entire 1–2 minute parallel phase and looks frozen.
                # 10 departments cover the 25→95 range (7 percentage points
                # each); the final 5 is reserved for synthesis after gather.
                job.agents_completed.append(dept.department_name)
                done_count = sum(
                    1 for d in self.departments if d.department_name in job.agents_completed
                )
                job.progress = 25 + int(done_count / len(self.departments) * 70)
                await emit(
                    dept.department_name,
                    f"Review complete. status: {review.review_status.upper()} | "
                    f"{s.compliant} compliant / {s.non_compliant} non-compliant / {s.needs_review} needs review "
                    f"| score {s.compliance_score:.0%}",
                    data={
                        "review_status": review.review_status,
                        "compliant": s.compliant,
                        "non_compliant": s.non_compliant,
                        "needs_review": s.needs_review,
                        "critical": s.critical_issues,
                        "progress": job.progress,
                    },
                )
                return review
            except Exception as e:
                # Even on failure, mark the dept done so progress moves and the
                # pipeline doesn't hang waiting for one dept to "finish".
                if dept.department_name not in job.agents_completed:
                    job.agents_completed.append(dept.department_name)
                done_count = sum(
                    1 for d in self.departments if d.department_name in job.agents_completed
                )
                job.progress = 25 + int(done_count / len(self.departments) * 70)
                await emit(dept.department_name, f"Review failed: {e}", level="error")
                return DepartmentReview(
                    department=dept.department_name,
                    department_code=dept.department_code,
                    icon="",
                    notes=f"Review failed: {e}",
                    review_status="rejected",
                )

        reviews: List[DepartmentReview] = await asyncio.gather(*(run_one(d) for d in self.departments))

        # ----- SYNTHESIZE FINAL REPORT -----
        await emit("Coordinator", "Aggregating findings across all departments...")
        all_findings: List[ComplianceFinding] = []
        for r in reviews:
            all_findings.extend(r.findings)

        # Overall summary
        overall_summary = self._summarize(all_findings)

        # Recommendations (severity-sorted)
        recommendations: List[str] = []
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_for_recs = sorted(
            [f for f in all_findings if f.status in (ComplianceStatus.NON_COMPLIANT, ComplianceStatus.NEEDS_REVIEW)],
            key=lambda f: sev_order.get(f.severity, 4),
        )
        for f in sorted_for_recs[:30]:
            if f.recommendation:
                dept = next((r for r in reviews if any(ff.finding_id == f.finding_id for ff in r.findings)), None)
                dept_label = f"[{dept.department}]" if dept else ""
                recommendations.append(
                    f"[{f.severity.upper()}] {dept_label} {f.code_requirement.section}: {f.recommendation}"
                )

        report = ComplianceReport(
            report_id=str(uuid.uuid4()),
            job_id=job.job_id,
            generated_at=datetime.utcnow(),
            jurisdiction=j,
            plan_data=pd,
            findings=all_findings,
            department_reviews=reviews,
            summary=overall_summary,
            recommendations=recommendations,
            code_versions={"primary": code_version},
            sources_used=["code_library/bm25"],
            auditor_notes=self._overall_notes(reviews, overall_summary),
        )

        cleared = sum(1 for r in reviews if r.review_status == "cleared")
        conditional = sum(1 for r in reviews if r.review_status == "conditional")
        rejected = sum(1 for r in reviews if r.review_status == "rejected")
        await emit(
            "Coordinator",
            f"Final: {cleared} cleared | {conditional} conditional | {rejected} rejected — "
            f"overall score {overall_summary.compliance_score:.0%}",
            data={"cleared": cleared, "conditional": conditional, "rejected": rejected,
                  "score": overall_summary.compliance_score},
        )

        # Department names were appended in real time by _do_review, so we
        # only need to finalize progress and clear current_agent here.
        job.progress = 100
        job.current_agent = None
        return report

    def _summarize(self, findings: List[ComplianceFinding]) -> ComplianceSummary:
        total = len(findings)
        compliant = sum(1 for f in findings if f.status == ComplianceStatus.COMPLIANT)
        non_compliant = sum(1 for f in findings if f.status == ComplianceStatus.NON_COMPLIANT)
        needs_review = sum(1 for f in findings if f.status == ComplianceStatus.NEEDS_REVIEW)
        not_applicable = sum(1 for f in findings if f.status == ComplianceStatus.NOT_APPLICABLE)
        checkable = total - not_applicable
        score = (compliant / checkable) if checkable > 0 else 0.0
        return ComplianceSummary(
            total_checks=total,
            compliant=compliant,
            non_compliant=non_compliant,
            needs_review=needs_review,
            not_applicable=not_applicable,
            compliance_score=round(score, 3),
            critical_issues=sum(1 for f in findings if f.severity == "critical"),
            high_issues=sum(1 for f in findings if f.severity == "high"),
            medium_issues=sum(1 for f in findings if f.severity == "medium"),
            low_issues=sum(1 for f in findings if f.severity == "low"),
        )

    def _overall_notes(self, reviews: List[DepartmentReview], s: ComplianceSummary) -> str:
        rejected = [r.department for r in reviews if r.review_status == "rejected"]
        conditional = [r.department for r in reviews if r.review_status == "conditional"]
        parts = [f"Multi-department review across {len(reviews)} departments completed."]
        if rejected:
            parts.append(f"Rejected by: {', '.join(rejected)}.")
        if conditional:
            parts.append(f"Conditional approval from: {', '.join(conditional)}.")
        if not rejected and not conditional:
            parts.append("Cleared by all departments.")
        if s.critical_issues:
            parts.append(f"{s.critical_issues} CRITICAL life-safety issues require immediate attention.")
        return " ".join(parts)
