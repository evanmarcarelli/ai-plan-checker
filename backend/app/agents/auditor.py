import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.agents.base import BaseAgent
from app.models.schemas import (
    CodeRequirement, ComplianceFinding, ComplianceReport,
    ComplianceStatus, ComplianceSummary, Jurisdiction, ExtractedPlanData
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AuditorAgent(BaseAgent):
    """
    Agent 3: The Auditor
    Cross-references plan data against code requirements.
    Generates compliance findings with pass/fail/needs-review status.
    """

    def __init__(self):
        super().__init__(name="Auditor")

    def _get_system_prompt(self) -> str:
        return """You are an expert building code compliance auditor. Your job is to:

1. Cross-reference PLAN DATA (actual measurements, elements) against CODE REQUIREMENTS
2. For DIMENSIONAL requirements: compare actual values vs minimum/maximum required
3. For PROCEDURAL requirements: assess if elements/notes indicate compliance
4. Assign compliance status: compliant | non_compliant | needs_review | not_applicable
5. Assign severity: critical | high | medium | low

VERIFICATION RULES:
- If plan shows a hallway at 32" and code requires 44" minimum → NON_COMPLIANT (critical)
- If plan explicitly shows sprinkler system and code requires it → COMPLIANT
- If element exists in plan but exact measurement not found → NEEDS_REVIEW
- If plan type is residential and commercial-only code applies → NOT_APPLICABLE

OUTPUT FORMAT — return a JSON array of findings ONLY:
[
  {
    "finding_id": "unique-id",
    "code_id": "code reference",
    "status": "compliant|non_compliant|needs_review|not_applicable",
    "plan_value": "what the plan shows (string or null)",
    "required_value": "what the code requires (string or null)",
    "description": "clear explanation of finding",
    "recommendation": "what action to take (for non_compliant/needs_review)",
    "severity": "critical|high|medium|low",
    "category": "fire_safety|structural|electrical|plumbing|accessibility|energy|general"
  }
]"""

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        jurisdiction: Jurisdiction = state.get("jurisdiction")
        plan_data: ExtractedPlanData = state.get("plan_data")
        code_requirements: List[CodeRequirement] = state.get("code_requirements", [])
        code_version: str = state.get("code_version", "2021 IBC")
        sources_used: List[str] = state.get("sources_used", [])

        logger.info(f"[Auditor] Auditing against {len(code_requirements)} code requirements")

        # First, run rule-based checks (fast, deterministic)
        rule_findings = self._run_rule_based_checks(plan_data, code_requirements)
        logger.info(f"[Auditor] Rule-based checks produced {len(rule_findings)} findings")

        # Then use LLM for nuanced analysis
        llm_findings = await self._run_llm_audit(plan_data, code_requirements, rule_findings)

        # Merge findings (LLM overrides rule-based for same code_id)
        all_findings = self._merge_findings(rule_findings, llm_findings)

        # Build report
        report = self._build_report(
            all_findings, jurisdiction, plan_data, code_requirements,
            code_version, sources_used
        )

        logger.info(
            f"[Auditor] Compliance score: {report.summary.compliance_score:.0%} "
            f"({report.summary.compliant}/{report.summary.total_checks} compliant)"
        )

        return {"report": report}

    def _run_rule_based_checks(
        self,
        plan_data: Optional[ExtractedPlanData],
        requirements: List[CodeRequirement]
    ) -> List[ComplianceFinding]:
        """Deterministic rule-based compliance checks."""
        findings = []
        if not plan_data:
            return findings

        dims = plan_data.dimensions if plan_data.dimensions else {}
        elements = [e.element_type for e in plan_data.elements] if plan_data.elements else []

        for req in requirements:
            finding = None

            # CORRIDOR WIDTH
            if req.code_id in ("IBC-1005.1",) and "corridor_widths" in dims:
                min_width = min(dims["corridor_widths"])
                if req.min_value:
                    status = ComplianceStatus.COMPLIANT if min_width >= req.min_value else ComplianceStatus.NON_COMPLIANT
                    finding = self._make_finding(req, status,
                        plan_value=f"{min_width} inches",
                        required_value=f"Minimum {req.min_value} {req.unit}",
                        description=f"Narrowest corridor is {min_width}\". Code requires minimum {req.min_value}\".",
                        severity="critical" if status == ComplianceStatus.NON_COMPLIANT else "low",
                        recommendation=None if status == ComplianceStatus.COMPLIANT else
                            f"Widen corridor to at least {req.min_value} inches."
                    )

            # DOOR WIDTHS
            elif req.code_id in ("IBC-1010.1.1", "ADA-4.13.5") and "door_widths" in dims:
                min_door = min(dims["door_widths"])
                if req.min_value:
                    status = ComplianceStatus.COMPLIANT if min_door >= req.min_value else ComplianceStatus.NON_COMPLIANT
                    finding = self._make_finding(req, status,
                        plan_value=f"{min_door} inches",
                        required_value=f"Minimum {req.min_value} {req.unit}",
                        description=f"Narrowest door opening is {min_door}\". Required minimum: {req.min_value}\".",
                        severity="high" if status == ComplianceStatus.NON_COMPLIANT else "low",
                        recommendation=None if status == ComplianceStatus.COMPLIANT else
                            f"Increase door clear width to at least {req.min_value} inches."
                    )

            # STAIR WIDTH
            elif req.code_id == "IBC-1011.5.2" and "stair_width" in dims:
                if req.min_value:
                    stair_w = dims["stair_width"]
                    status = ComplianceStatus.COMPLIANT if stair_w >= req.min_value else ComplianceStatus.NON_COMPLIANT
                    finding = self._make_finding(req, status,
                        plan_value=f"{stair_w} inches",
                        required_value=f"Minimum {req.min_value} {req.unit}",
                        description=f"Stairway width is {stair_w}\". Required minimum: {req.min_value}\".",
                        severity="high" if status == ComplianceStatus.NON_COMPLIANT else "low",
                        recommendation=None if status == ComplianceStatus.COMPLIANT else
                            f"Increase stairway width to at least {req.min_value} inches."
                    )

            # CEILING HEIGHT
            elif req.code_id == "IBC-1208.2" and "ceiling_height" in dims:
                if req.min_value:
                    ceil_h = dims["ceiling_height"]
                    status = ComplianceStatus.COMPLIANT if ceil_h >= req.min_value else ComplianceStatus.NON_COMPLIANT
                    finding = self._make_finding(req, status,
                        plan_value=f"{ceil_h} ft",
                        required_value=f"Minimum {req.min_value} {req.unit}",
                        description=f"Ceiling height is {ceil_h}'. Required minimum: {req.min_value}'.",
                        severity="medium" if status == ComplianceStatus.NON_COMPLIANT else "low",
                        recommendation=None if status == ComplianceStatus.COMPLIANT else
                            "Raise ceiling height to minimum 7.5 feet."
                    )

            # SPRINKLER SYSTEM
            elif req.code_id == "IFC-903.2":
                has_sprinkler = "fire_suppression" in elements
                if has_sprinkler:
                    finding = self._make_finding(req, ComplianceStatus.COMPLIANT,
                        plan_value="Sprinkler system shown",
                        description="Automatic fire sprinkler system is indicated on the plans.",
                        severity="low"
                    )
                else:
                    finding = self._make_finding(req, ComplianceStatus.NEEDS_REVIEW,
                        plan_value="Not explicitly shown",
                        description="Fire sprinkler system not clearly indicated on plans.",
                        severity="high",
                        recommendation="Confirm sprinkler system requirements with AHJ. Provide fire suppression plans."
                    )

            # ADA ACCESSIBLE ROUTE
            elif req.code_id == "ADA-4.3.3" and "corridor_widths" in dims:
                min_width = min(dims["corridor_widths"])
                if req.min_value:
                    status = ComplianceStatus.COMPLIANT if min_width >= req.min_value else ComplianceStatus.NON_COMPLIANT
                    finding = self._make_finding(req, status,
                        plan_value=f"{min_width} inches",
                        required_value=f"Minimum {req.min_value} {req.unit}",
                        description=f"ADA accessible route minimum width check: {min_width}\" shown.",
                        severity="high" if status == ComplianceStatus.NON_COMPLIANT else "low",
                        recommendation=None if status == ComplianceStatus.COMPLIANT else
                            "Provide accessible route of minimum 36 inches clear width."
                    )

            # EGRESS ELEMENTS
            elif req.code_id == "IBC-1006.3.3":
                has_egress = "egress" in elements
                if has_egress:
                    finding = self._make_finding(req, ComplianceStatus.COMPLIANT,
                        plan_value="Exit elements shown",
                        description="Exit/egress elements are present on plans.",
                        severity="low"
                    )
                else:
                    finding = self._make_finding(req, ComplianceStatus.NEEDS_REVIEW,
                        plan_value="Not explicitly verified",
                        description="Minimum exit count not verified from plans.",
                        severity="critical",
                        recommendation="Verify minimum two exits per floor per IBC 1006.3.3."
                    )

            # GFCI
            elif req.code_id == "NEC-210.8":
                has_electrical = "electrical" in elements
                finding = self._make_finding(req,
                    ComplianceStatus.NEEDS_REVIEW if has_electrical else ComplianceStatus.NEEDS_REVIEW,
                    plan_value="Electrical plans required",
                    description="GFCI protection verification requires electrical plan review.",
                    severity="medium",
                    recommendation="Provide electrical plans showing GFCI locations per NEC 210.8."
                )

            # ADA RAMP SLOPE
            elif req.code_id == "ADA-4.8.2":
                has_accessibility = "accessibility" in elements
                finding = self._make_finding(req,
                    ComplianceStatus.COMPLIANT if has_accessibility else ComplianceStatus.NEEDS_REVIEW,
                    plan_value="ADA elements noted" if has_accessibility else "Not indicated",
                    description="ADA ramp slope compliance" + (" noted on plans." if has_accessibility else " not verified."),
                    severity="medium",
                    recommendation=None if has_accessibility else "Provide ramp details showing maximum 1:12 slope."
                )

            # Default: needs_review for unmatched
            if finding is None:
                finding = self._make_finding(req, ComplianceStatus.NEEDS_REVIEW,
                    plan_value=None,
                    description=f"Could not auto-verify: {req.description}",
                    severity="medium",
                    recommendation=f"Manual review required for {req.section} - {req.description}"
                )

            findings.append(finding)

        return findings

    async def _run_llm_audit(
        self,
        plan_data: Optional[ExtractedPlanData],
        requirements: List[CodeRequirement],
        existing_findings: List[ComplianceFinding]
    ) -> List[ComplianceFinding]:
        """Use LLM for nuanced cross-referencing."""
        if not plan_data:
            return []

        # Prepare plan summary
        plan_summary = {
            "plan_type": plan_data.plan_type.value if plan_data.plan_type else "unknown",
            "project_name": plan_data.project_name,
            "occupancy_type": plan_data.occupancy_type,
            "construction_type": plan_data.construction_type,
            "building_height_ft": plan_data.building_height,
            "building_area_sf": plan_data.building_area,
            "dimensions": plan_data.dimensions,
            "elements_present": [e.element_type for e in plan_data.elements],
            "materials": plan_data.materials,
        }

        context = f"""EXTRACTED PLAN DATA:
{json.dumps(plan_summary, indent=2)}

PLAN TEXT SAMPLE (first 2000 chars):
{list(plan_data.raw_text_by_page.values())[0][:2000] if plan_data.raw_text_by_page else "No text extracted"}

CODE REQUIREMENTS TO AUDIT (first 15):
{json.dumps([r.model_dump() for r in requirements[:15]], indent=2)}

EXISTING RULE-BASED FINDINGS (for context):
{json.dumps([{
    "code_id": f.code_requirement.code_id,
    "status": f.status.value,
    "description": f.description
} for f in existing_findings[:10]], indent=2)}

Review the plan data against ALL code requirements and generate a comprehensive compliance report.
Focus on requirements not already covered by rule-based checks.
Be specific about values when available.
Return JSON array of findings."""

        try:
            response = await self._call_llm(context, max_tokens=4000)
            parsed = self._parse_json_response(response)

            if parsed and isinstance(parsed, list):
                llm_findings = []
                req_map = {r.code_id: r for r in requirements}

                for item in parsed:
                    code_id = item.get("code_id", "")
                    req = req_map.get(code_id)
                    if not req:
                        # Find by partial match
                        for r in requirements:
                            if code_id in r.code_id or r.code_id in code_id:
                                req = r
                                break

                    if req:
                        try:
                            status = ComplianceStatus(item.get("status", "needs_review"))
                        except Exception:
                            status = ComplianceStatus.NEEDS_REVIEW

                        finding = self._make_finding(
                            req, status,
                            plan_value=item.get("plan_value"),
                            required_value=item.get("required_value"),
                            description=item.get("description", ""),
                            severity=item.get("severity", "medium"),
                            recommendation=item.get("recommendation"),
                        )
                        llm_findings.append(finding)

                logger.info(f"[Auditor] LLM generated {len(llm_findings)} findings")
                return llm_findings
        except Exception as e:
            logger.warning(f"[Auditor] LLM audit failed: {e}")

        return []

    def _merge_findings(
        self,
        rule_findings: List[ComplianceFinding],
        llm_findings: List[ComplianceFinding]
    ) -> List[ComplianceFinding]:
        """Merge rule and LLM findings, LLM takes precedence."""
        merged = {f.code_requirement.code_id: f for f in rule_findings}
        for f in llm_findings:
            merged[f.code_requirement.code_id] = f
        return list(merged.values())

    def _make_finding(
        self,
        req: CodeRequirement,
        status: ComplianceStatus,
        plan_value: Optional[str] = None,
        required_value: Optional[str] = None,
        description: str = "",
        severity: str = "medium",
        recommendation: Optional[str] = None,
    ) -> ComplianceFinding:
        return ComplianceFinding(
            finding_id=str(uuid.uuid4())[:8],
            code_requirement=req,
            status=status,
            plan_value=plan_value,
            required_value=required_value,
            description=description or req.description,
            recommendation=recommendation,
            severity=severity,
            category=req.category,
        )

    def _build_report(
        self,
        findings: List[ComplianceFinding],
        jurisdiction: Optional[Jurisdiction],
        plan_data: Optional[ExtractedPlanData],
        requirements: List[CodeRequirement],
        code_version: str,
        sources_used: List[str],
    ) -> ComplianceReport:
        # Tally counts
        total = len(findings)
        compliant = sum(1 for f in findings if f.status == ComplianceStatus.COMPLIANT)
        non_compliant = sum(1 for f in findings if f.status == ComplianceStatus.NON_COMPLIANT)
        needs_review = sum(1 for f in findings if f.status == ComplianceStatus.NEEDS_REVIEW)
        not_applicable = sum(1 for f in findings if f.status == ComplianceStatus.NOT_APPLICABLE)

        critical = sum(1 for f in findings if f.severity == "critical")
        high = sum(1 for f in findings if f.severity == "high")
        medium = sum(1 for f in findings if f.severity == "medium")
        low = sum(1 for f in findings if f.severity == "low")

        # Score = compliant / (total - not_applicable)
        checkable = total - not_applicable
        score = (compliant / checkable) if checkable > 0 else 0.0

        # Generate recommendations
        recommendations = []
        for f in findings:
            if f.status == ComplianceStatus.NON_COMPLIANT and f.recommendation:
                prefix = f"[{f.severity.upper()}] {f.code_requirement.section}: "
                recommendations.append(prefix + f.recommendation)

        for f in findings:
            if f.status == ComplianceStatus.NEEDS_REVIEW and f.recommendation:
                prefix = f"[REVIEW] {f.code_requirement.section}: "
                recommendations.append(prefix + f.recommendation)

        # Sort by severity
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        findings.sort(key=lambda f: (sev_order.get(f.severity, 4),
                                      0 if f.status == ComplianceStatus.NON_COMPLIANT else 1))

        return ComplianceReport(
            report_id=str(uuid.uuid4()),
            job_id="",  # filled in by workflow
            generated_at=datetime.utcnow(),
            jurisdiction=jurisdiction,
            plan_data=plan_data,
            findings=findings,
            summary=ComplianceSummary(
                total_checks=total,
                compliant=compliant,
                non_compliant=non_compliant,
                needs_review=needs_review,
                not_applicable=not_applicable,
                compliance_score=round(score, 3),
                critical_issues=critical,
                high_issues=high,
                medium_issues=medium,
                low_issues=low,
            ),
            recommendations=recommendations[:20],
            code_versions={"primary": code_version},
            sources_used=sources_used,
            auditor_notes=f"Automated audit completed. {non_compliant} non-compliant items and "
                          f"{needs_review} items requiring manual review.",
        )
