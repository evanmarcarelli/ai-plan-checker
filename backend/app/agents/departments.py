"""Department-specific compliance reviewer agents.

Each department agent represents a real city/county permit reviewer:
Building & Safety, Fire, Electrical, Plumbing, Mechanical, Accessibility,
Energy, Planning/Zoning, Public Works, Environmental.

All agents inherit from DepartmentReviewer and run in parallel via the workflow.
"""
import json
import uuid
from typing import Dict, Any, List, Optional
from app.agents.base import BaseAgent
from app.code_library.corpus_loader import get_corpus
from app.models.schemas import (
    CodeRequirement, ComplianceFinding, ComplianceStatus, ComplianceSummary,
    DepartmentReview, ExtractedPlanData,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# #5 — Confidence gate threshold. A NON_COMPLIANT finding whose reviewer
# confidence is below this is downgraded to NEEDS_REVIEW so an uncertain
# reviewer never hard-blocks a permit (the trust-preserving default).
LOW_CONFIDENCE_THRESHOLD = 0.55

_UNCERTAIN_NOTE = (
    " [Reviewer confidence below threshold — downgraded from non-compliant to "
    "needs-review; a human should confirm.]"
)


def _coerce_confidence(raw) -> float:
    """Parse an LLM-supplied confidence into 0..1. Missing/garbage -> 1.0 so a
    reviewer that doesn't report confidence is not auto-downgraded."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if v != v:  # NaN
        return 1.0
    return max(0.0, min(1.0, v))


def gate_low_confidence(
    findings: List[ComplianceFinding], threshold: float = LOW_CONFIDENCE_THRESHOLD
) -> int:
    """Downgrade low-confidence NON_COMPLIANT findings to NEEDS_REVIEW in place.
    Returns the number downgraded. Pure post-processing — no LLM/network."""
    downgraded = 0
    for f in findings:
        if f.status == ComplianceStatus.NON_COMPLIANT and f.confidence < threshold:
            f.status = ComplianceStatus.NEEDS_REVIEW
            if _UNCERTAIN_NOTE.strip() not in (f.description or ""):
                f.description = (f.description or "") + _UNCERTAIN_NOTE
            downgraded += 1
    return downgraded


class DepartmentReviewer(BaseAgent):
    """Base class for all department-level plan reviewers.

    Runs on Sonnet (cheap model) for ~5x cost savings over Opus. The 10
    department reviewers are the volume driver of LLM cost — Surveyor and
    Anthropic Sonnet handles structured cross-referencing very well.
    """

    @property
    def model_override(self):  # type: ignore[override]
        # #6 — Per-department model tier. Default: Sonnet (cheap) for every
        # reviewer. A category listed in settings.strong_review_categories
        # (env STRONG_REVIEW_CATEGORIES) uses the premium model instead, so the
        # operator can upgrade judgment-heavy reviewers (structural, life-safety)
        # without touching code. No category is upgraded by default — keeps cost
        # flat unless the operator opts in.
        from app.config import settings as _s
        strong = {
            c.strip() for c in (_s.strong_review_categories or "").split(",") if c.strip()
        }
        if self.category in strong:
            return _s.anthropic_model
        return _s.anthropic_model_cheap

    # Subclasses override these
    department_name: str = "Department"
    department_code: str = "generic"
    department_icon: str = ""
    category: str = "general"  # CodeRequirement category to filter on
    domain_expertise: str = ""  # Short blurb appended to the system prompt
    review_focus: str = ""  # What the reviewer specifically looks for

    def __init__(self):
        super().__init__(name=self.department_name)

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # DepartmentReviewer uses .review() instead of .execute()
        raise NotImplementedError("Use review() for department agents")

    def _get_system_prompt(self) -> str:
        from app.agents.few_shot_corrections import few_shot_block
        examples = few_shot_block(self.category)
        examples_section = f"\n\n{examples}\n" if examples else ""
        return f"""You are a senior {self.department_name} plan reviewer for a city/county building department.
You have 15+ years of experience and are responsible for ensuring the submitted plans comply with applicable codes.

YOUR DOMAIN: {self.domain_expertise}

YOUR REVIEW FOCUS: {self.review_focus}{examples_section}

YOUR TASK:
1. Cross-reference the EXTRACTED PLAN DATA against the CODE REQUIREMENTS provided.
2. For each code requirement, decide: compliant | non_compliant | needs_review | not_applicable
3. Be specific. Cite the plan's actual values vs. what the code requires.
4. Be conservative — if the plan does not clearly demonstrate compliance, mark needs_review (not compliant).
5. Assign severity: critical | high | medium | low.
6. Provide a concrete, actionable recommendation for any non_compliant or needs_review finding.

SEVERITY GUIDE:
- critical: life-safety failure (no egress, missing exits, no sprinklers where required, structural inadequacy)
- high: significant code violation that will block permit (wrong fire rating, undersized service, missing ADA path)
- medium: code issue requiring correction but not blocking (insufficient ventilation, missing GFCI)
- low: best-practice or minor (label discrepancy, missing detail callout)

OUTPUT — return ONLY a JSON array, no prose:
[
  {{
    "code_id": "string (matches a provided requirement)",
    "status": "compliant|non_compliant|needs_review|not_applicable",
    "plan_value": "what the plan shows, or null",
    "required_value": "what the code requires, or null",
    "description": "1-3 sentence explanation specific to THIS plan",
    "recommendation": "concrete next step for the applicant, or null if compliant",
    "severity": "critical|high|medium|low",
    "confidence": 0.0 to 1.0 (your certainty THIS finding is correct; use <0.55 when the plan is ambiguous or you are guessing),
    "page_references": [page numbers if known, else []]
  }}
]

CONFIDENCE: be honest. A non_compliant finding you are unsure about is more
harmful than a needs_review — if you cannot clearly demonstrate the violation
from the plan text + code provided, lower your confidence rather than asserting."""

    async def review(
        self,
        plan_data: Optional[ExtractedPlanData],
        requirements: List[CodeRequirement],
        jurisdiction_amendments: List[str],
        code_version: str,
        deterministic_findings: Optional[List[ComplianceFinding]] = None,
    ) -> DepartmentReview:
        """Run this department's review and return a DepartmentReview.

        `deterministic_findings` are the high-trust results from the rule
        engine (allowable area, story limits, LADBS completeness, ...). The
        reviewer is shown the ones in its own category as authoritative facts
        so it does NOT recompute the code-math (where LLMs silently err) and
        builds its judgment review on top of them.
        """

        if not requirements:
            return DepartmentReview(
                department=self.department_name,
                department_code=self.department_code,
                icon=self.department_icon,
                summary=ComplianceSummary(),
                findings=[],
                notes=f"No {self.department_name} codes applicable to this submittal.",
                submittal_required=False,
                review_status="cleared",
            )

        findings = await self._call_reviewer(
            plan_data, requirements, jurisdiction_amendments, deterministic_findings
        )
        # #5 — Confidence gate: an uncertain reviewer must not hard-block a
        # permit. Low-confidence NON_COMPLIANT findings become NEEDS_REVIEW.
        gate_low_confidence(findings)
        summary = self._summarize(findings)
        status = self._derive_status(summary)

        return DepartmentReview(
            department=self.department_name,
            department_code=self.department_code,
            icon=self.department_icon,
            summary=summary,
            findings=findings,
            notes=self._notes(summary, jurisdiction_amendments, code_version),
            submittal_required=True,
            review_status=status,
        )

    def _deterministic_context(
        self, deterministic_findings: Optional[List[ComplianceFinding]]
    ) -> str:
        """Format this department's verified deterministic findings for the
        prompt. Filters to findings in this department's category so each
        reviewer only sees what's relevant to it."""
        if not deterministic_findings:
            return ""
        mine = [f for f in deterministic_findings if f.category == self.category]
        if not mine:
            return ""
        lines = []
        for f in mine:
            cid = f.code_requirement.code_id
            status = f.status.value if hasattr(f.status, "value") else str(f.status)
            lines.append(f"- [{cid}] {status.upper()} ({f.severity}): {f.description}")
        return (
            "VERIFIED DETERMINISTIC FINDINGS (computed by a deterministic rule engine — "
            "these are authoritative facts. Do NOT recompute this math; factor them into "
            "your review and do not contradict them):\n" + "\n".join(lines)
        )

    def _relevant_plan_text(
        self, plan_data: Optional[ExtractedPlanData], budget: int = 6000, per_page: int = 2000
    ) -> str:
        """#3 — Per-department plan-text retrieval.

        The reviewer used to see only the first page (~2,500 chars). On a
        multi-hundred-page set that's almost nothing and the domain sheets
        (electrical schedules, plumbing fixture schedules, ...) are never seen.
        Here we score every page by this department's domain keywords and feed
        the reviewer the title/code sheet (always) plus the highest-scoring
        domain pages, up to a char budget.

        The sheet index (when extraction identified sheet numbers) adds a
        strong routing signal on top of the keyword score: a page whose sheet
        DISCIPLINE maps to this department's category (E-sheets → electrical,
        P-sheets → plumbing, FP/LS-sheets → fire ...) is what a human reviewer
        would open first, even if its body text is drawing labels with few
        domain keywords.

        Degrades safely: no plan text -> ""; no domain match anywhere -> just
        the first page (the previous behaviour, so no regression).
        """
        pages = (plan_data.raw_text_by_page if plan_data else None) or {}
        if not pages:
            return ""
        from app.code_library.ingest.chunker import compiled_patterns_for_category
        patterns = compiled_patterns_for_category(self.category)

        # Sheet-index lookup: page -> sheet record (discipline routing + the
        # sheet-number label that makes the excerpt traceable).
        sheets_by_page = {
            rec.get("page_number"): rec
            for rec in (plan_data.sheet_index if plan_data else None) or []
            if rec.get("page_number") is not None
        }

        # A discipline match outranks any realistic keyword count: it is the
        # "open the E-sheets first" instinct, not a tie-breaker.
        DISCIPLINE_BOOST = 100

        first_pageno = min(pages.keys())
        selected: List[tuple] = []
        used: set = set()
        total = 0

        def add(pageno: int) -> None:
            nonlocal total
            if pageno in used:
                return
            text = (pages.get(pageno) or "")[:per_page]
            if not text.strip():
                return
            selected.append((pageno, text))
            used.add(pageno)
            total += len(text)

        # Anchor: the first page almost always carries the title block + code
        # analysis, which every department needs.
        add(first_pageno)

        # Score the rest: domain-keyword hits + sheet-discipline routing.
        scored = []
        for pageno, text in pages.items():
            if pageno in used or not text:
                continue
            score = sum(1 for p in patterns if p.search(text))
            rec = sheets_by_page.get(pageno)
            if rec and rec.get("category") == self.category:
                score += DISCIPLINE_BOOST
            if score > 0:
                scored.append((score, pageno))
        scored.sort(key=lambda t: (-t[0], t[1]))
        for _score, pageno in scored:
            if total >= budget:
                break
            add(pageno)

        selected.sort(key=lambda t: t[0])

        def _label(pn: int) -> str:
            rec = sheets_by_page.get(pn) or {}
            num, title = rec.get("sheet_number"), rec.get("sheet_title")
            if num and title:
                return f"[PAGE {pn} — SHEET {num} {title}]"
            if num:
                return f"[PAGE {pn} — SHEET {num}]"
            return f"[PAGE {pn}]"

        return "\n\n".join(f"{_label(pn)}\n{tx}" for pn, tx in selected)

    async def _call_reviewer(
        self,
        plan_data: Optional[ExtractedPlanData],
        requirements: List[CodeRequirement],
        jurisdiction_amendments: List[str],
        deterministic_findings: Optional[List[ComplianceFinding]] = None,
    ) -> List[ComplianceFinding]:
        # Build plan summary
        plan_summary = "No plan data extracted."
        relevant_text = ""
        if plan_data:
            plan_summary = json.dumps({
                "plan_type": plan_data.plan_type.value if plan_data.plan_type else "unknown",
                "project_name": plan_data.project_name,
                "project_address": plan_data.project_address,
                "occupancy_type": plan_data.occupancy_type,
                "construction_type": plan_data.construction_type,
                "building_height_ft": plan_data.building_height,
                "building_area_sf": plan_data.building_area,
                "stories": plan_data.stories,
                "dimensions": plan_data.dimensions,
                "elements_present": [e.element_type for e in plan_data.elements] if plan_data.elements else [],
                "materials": plan_data.materials,
            }, indent=2, default=str)
            relevant_text = self._relevant_plan_text(plan_data)

        # Build a code-requirements block that puts the VERBATIM code text
        # front and centre so the model is forced to ground in it rather than
        # invent values. The corpus category can be far larger than the prompt
        # budget, so requirements are RANKED against this plan before the cut:
        # curated checklist items first (they are the examiner's actual list),
        # then corpus chunks by lexical overlap with the plan text. Untreated,
        # JSONL filename sort order decided which codes the model saw — and
        # ~98% of a large category (e.g. accessibility) was silently dropped
        # while the header still claimed every item was under review.
        REQ_BUDGET_CHARS = 18000
        ranked = self._rank_requirements(requirements, f"{plan_summary}\n{relevant_text}")
        req_block_parts: List[str] = []
        included: List[CodeRequirement] = []
        total_chars = 0
        for r in ranked:
            part = f"[{r.code_id}] {r.description}\n{r.full_text or '(no text available)'}"
            if included and total_chars + len(part) > REQ_BUDGET_CHARS:
                break
            req_block_parts.append(part)
            included.append(r)
            total_chars += len(part) + 2
        req_block = "\n\n".join(req_block_parts)
        excluded_count = len(requirements) - len(included)

        # ---- STABLE prefix (cached) ----
        # The verbatim code requirements for this department + jurisdiction do
        # not change between runs. We send them as `cache_prefix` so Anthropic
        # prompt caching bills them at ~10% of the input rate on warm runs.
        # This is the bulk of the input tokens, so it is the bulk of the saving.
        code_block = (
            f"CODE REQUIREMENTS TO REVIEW ({len(included)} items) — each shown "
            f"with its CITATION and verbatim code text:\n\n{req_block}"
        )

        # Standard-correction-list items are completeness checks ("Provide X",
        # "Show Y on plans", "Add note Z"). They are easy to over-flag: the
        # reviewer only sees plan-text EXCERPTS, so absence of text is not proof
        # the item is missing from the full set. Steer those items toward high
        # precision — a clear miss fails, silence/ambiguity is needs_review, not
        # a hard violation. This protects the 90% precision target as the
        # injected corrections deepen coverage.
        has_completeness = any(
            getattr(r, "requirement_type", None) == "completeness" for r in included
        )
        completeness_guidance = (
            "\n\nSTANDARD CORRECTION-LIST (COMPLETENESS) ITEMS: some requirements "
            "above are plan-completeness corrections (\"Provide…\", \"Show…\", "
            "\"Add note…\", \"Dimension…\"). For these, flag ONLY what the plan "
            "does not show or does not satisfy:\n"
            "- If the provided plan text clearly shows the item is addressed → "
            "status=\"compliant\".\n"
            "- If it clearly shows the item is missing or wrong → "
            "status=\"non_compliant\".\n"
            "- If the plan text is silent or ambiguous (the relevant sheet may "
            "simply not be in the excerpt) → status=\"needs_review\" with "
            "confidence < 0.55. Do NOT assert non_compliant from absence of text "
            "alone.\n"
            "- If the item cannot apply to this project → status=\"not_applicable\"."
            if has_completeness else ""
        )

        # ---- FRESH content (not cached) ----
        # The actual plan under review changes every run, so it stays uncached.
        det_block = self._deterministic_context(deterministic_findings)
        fresh = f"""EXTRACTED PLAN DATA:
{plan_summary}

RELEVANT PLAN TEXT (the title/code sheet plus pages matched to YOUR domain — schedules, notes, callouts):
{relevant_text}

LOCAL JURISDICTION AMENDMENTS:
{chr(10).join(f'- {a}' for a in jurisdiction_amendments) if jurisdiction_amendments else 'None'}
{(chr(10) + det_block + chr(10)) if det_block else ''}
Using the CODE REQUIREMENTS shown above, review every requirement against this
plan. For each, return a finding whose code_id is EXACTLY the bracketed citation
(e.g. "IBC 1011.5.2"). Do NOT invent new section numbers. If a code is not
applicable to this plan, use status="not_applicable". Return JSON findings array.{completeness_guidance}"""

        try:
            response = await self._call_llm(fresh, max_tokens=4000, cache_prefix=code_block)
            parsed = self._parse_json_response(response)
        except Exception as e:
            logger.error(f"[{self.department_name}] LLM call failed: {e}")
            parsed = None

        findings: List[ComplianceFinding] = []
        req_map = {r.code_id: r for r in included}

        corpus = get_corpus()
        if parsed and isinstance(parsed, list):
            for item in parsed:
                code_id = item.get("code_id", "")
                req = req_map.get(code_id)
                if not req:
                    # try partial match
                    for r in included:
                        if code_id and (code_id in r.code_id or r.code_id in code_id):
                            req = r
                            break
                if not req:
                    # The LLM cited a section we never gave it. Two possibilities:
                    # (a) the section exists in the corpus and the model is right
                    #     to surface it -> verify and accept with the corpus's
                    #     authoritative text;
                    # (b) it's a hallucinated section -> drop the finding silently.
                    chunk = corpus.get(code_id) if code_id else None
                    if not chunk:
                        logger.warning(
                            f"[{self.department_name}] dropped finding citing unverified section {code_id!r}"
                        )
                        continue
                    from app.code_library.adapter import chunk_to_requirement
                    req = chunk_to_requirement(chunk)

                try:
                    status = ComplianceStatus(item.get("status", "needs_review"))
                except Exception:
                    status = ComplianceStatus.NEEDS_REVIEW

                # Verify against corpus: if code_id is a real chunk, use its
                # verbatim text as the source quote. Findings without a real
                # corpus hit are marked verified=False so the UI can flag them.
                source_chunk = corpus.get(req.code_id)
                verified = source_chunk is not None
                source_text = source_chunk.text if source_chunk else req.full_text
                source_citation = source_chunk.citation if source_chunk else req.code_id

                findings.append(ComplianceFinding(
                    finding_id=str(uuid.uuid4())[:8],
                    code_requirement=req,
                    status=status,
                    plan_value=item.get("plan_value"),
                    required_value=item.get("required_value"),
                    description=item.get("description", "") or req.description,
                    recommendation=item.get("recommendation"),
                    severity=item.get("severity", "medium"),
                    category=req.category,
                    confidence=_coerce_confidence(item.get("confidence")),
                    page_references=item.get("page_references") or [],
                    verified=verified,
                    source_text=source_text,
                    source_citation=source_citation,
                ))

        # Fill in any requirement the LLM skipped with a needs_review finding —
        # but ONLY requirements that were actually in the prompt. Backfilling
        # requirements the model never saw used to spawn ~1,300 filler
        # "Manual review required" findings per run, burying real violations
        # and dragging every department to "conditional".
        covered = {f.code_requirement.code_id for f in findings}
        for req in included:
            if req.code_id not in covered:
                findings.append(ComplianceFinding(
                    finding_id=str(uuid.uuid4())[:8],
                    code_requirement=req,
                    status=ComplianceStatus.NEEDS_REVIEW,
                    description=f"Manual review required: {req.description}",
                    recommendation=f"Reviewer to verify {req.section} - {req.description}",
                    severity="medium",
                    category=req.category,
                ))

        # Requirements that didn't fit the prompt budget collapse into ONE
        # informational line (NOT_APPLICABLE keeps it out of the compliance
        # score) instead of a finding apiece — honest about coverage without
        # drowning the report.
        if excluded_count > 0:
            findings.append(ComplianceFinding(
                finding_id=str(uuid.uuid4())[:8],
                code_requirement=CodeRequirement(
                    code_id=f"COVERAGE-{self.department_code.upper()}",
                    code_name="Review coverage note",
                    section="coverage",
                    description="Corpus requirements outside this run's prompt budget.",
                    category=self.category,
                    requirement_type="general",
                    jurisdiction_specific=False,
                ),
                status=ComplianceStatus.NOT_APPLICABLE,
                description=(
                    f"{excluded_count} lower-relevance {self.department_name} corpus "
                    f"requirement(s) were not individually evaluated this run "
                    f"(ranked below the prompt budget for this plan)."
                ),
                severity="low",
                category=self.category,
            ))

        return findings

    @staticmethod
    def _rank_requirements(
        requirements: List[CodeRequirement], plan_context: str
    ) -> List[CodeRequirement]:
        """Order requirements by relevance to THIS plan before the prompt cut.

        Curated checklist/completeness items come first unconditionally — they
        are the examiner's actual correction list, injected per department on
        purpose. Corpus chunks follow, scored by token overlap between the
        requirement text and the plan excerpt (length-normalized so a long
        chunk can't win on bulk). Ties keep load order, so behavior is stable
        when there is no plan text at all.
        """
        from app.code_library.corpus_loader import tokenize
        plan_tokens = set(tokenize(plan_context or ""))

        def overlap(r: CodeRequirement) -> float:
            toks = set(tokenize(f"{r.description} {(r.full_text or '')[:1500]}"))
            if not toks or not plan_tokens:
                return 0.0
            return len(toks & plan_tokens) / (len(toks) ** 0.5)

        curated: List[CodeRequirement] = []
        scored: List[tuple] = []
        for i, r in enumerate(requirements):
            if getattr(r, "requirement_type", None) == "completeness":
                curated.append(r)
            else:
                scored.append((-overlap(r), i, r))
        scored.sort(key=lambda t: (t[0], t[1]))
        return curated + [r for _, _, r in scored]

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

    def _derive_status(self, summary: ComplianceSummary) -> str:
        if summary.non_compliant > 0 and summary.critical_issues > 0:
            return "rejected"
        if summary.non_compliant > 0 or summary.high_issues > 0:
            return "conditional"
        if summary.needs_review > 0:
            return "conditional"
        return "cleared"

    def _notes(self, s: ComplianceSummary, amendments: List[str], code_version: str) -> str:
        parts = [f"{self.department_name} review against {code_version}."]
        if amendments:
            parts.append(f"Local amendments: {', '.join(amendments)}.")
        if s.critical_issues:
            parts.append(f"{s.critical_issues} CRITICAL life-safety issue(s) flagged.")
        if s.non_compliant:
            parts.append(f"{s.non_compliant} non-compliant items must be corrected.")
        if s.needs_review:
            parts.append(f"{s.needs_review} items require additional information from applicant.")
        return " ".join(parts)


# ============================================================
# 10 DEPARTMENT AGENTS
# ============================================================

class BuildingSafetyAgent(DepartmentReviewer):
    department_name = "Building & Safety"
    department_code = "building_safety"
    department_icon = ""
    category = "building_safety"
    domain_expertise = (
        "IBC structural design (Chapter 16), occupancy classification (Chapter 3), "
        "construction types and fire-resistance (Chapter 6-7), means of egress (Chapter 10), "
        "interior finishes (Chapter 8), ceiling heights, allowable height and area (Tables 504/506), "
        "seismic (Chapter 16), gravity loads (Chapter 16), foundations (Chapter 18). "
        "Local amendments: CBC for California, FBC for Florida, NYC BC for NYC."
    )
    review_focus = (
        "Verify occupancy group, construction type, allowable height/area, fire-resistance ratings, "
        "egress geometry (corridor/door/stair widths), exit count and travel distance, ceiling heights, "
        "structural lateral and gravity systems, foundation type, and applicable seismic/wind requirements."
    )


class FireAgent(DepartmentReviewer):
    department_name = "Fire Department"
    department_code = "fire"
    department_icon = ""
    category = "fire"
    domain_expertise = (
        "International Fire Code (IFC), NFPA 13/13R/13D sprinklers, NFPA 72 alarms, "
        "fire apparatus access (Section 503), water supply for fire protection (Section 507/Appendix B,C), "
        "Knox boxes, standpipes (NFPA 14), emergency power, smoke control, "
        "rated assemblies, fire department connections (FDC), occupancy-based requirements. "
        "Wildfire/WUI (CBC 7A) where applicable."
    )
    review_focus = (
        "Verify sprinkler requirement by occupancy and confirm NFPA standard, fire alarm thresholds, "
        "fire apparatus access roads (20 ft width, 13'-6\" vertical, within 150 ft), hydrant flow/spacing, "
        "FDC location, knox box, common path/exit access travel distances, EERO for sleeping rooms, "
        "extinguisher placement (75 ft travel)."
    )


class ElectricalAgent(DepartmentReviewer):
    department_name = "Electrical Inspector"
    department_code = "electrical"
    department_icon = ""
    category = "electrical"
    domain_expertise = (
        "National Electrical Code (NEC 2023), service sizing and disconnect (Article 230), "
        "branch circuit design (Article 210), grounding and bonding (Article 250), "
        "GFCI (210.8) and AFCI (210.12) protection zones, receptacle spacing in dwellings (210.52), "
        "conductor ampacity (Table 310.16), motor circuits (Article 430), feeders (Article 215), "
        "panel installation, working clearances (110.26). California Title 24 Part 6 lighting controls."
    )
    review_focus = (
        "Verify service size, disconnect location and accessibility, grounding electrode system, "
        "GFCI/AFCI coverage in all required locations, receptacle counts and spacing, "
        "panel schedules, working clearances (3 ft front, 30\" wide), feeder/branch circuit sizing, "
        "EV charging readiness where required."
    )


class PlumbingAgent(DepartmentReviewer):
    department_name = "Plumbing Inspector"
    department_code = "plumbing"
    department_icon = ""
    category = "plumbing"
    domain_expertise = (
        "International Plumbing Code (IPC) / Uniform Plumbing Code (UPC where adopted), "
        "minimum fixture counts (Table 403.1), fixture clearances, water supply sizing (Appendix E), "
        "DWV sizing by fixture units, venting (Chapter 9), backflow protection (Section 608), "
        "water heaters (Chapter 5), gas piping (IFGC). CalGreen low-flow fixture requirements."
    )
    review_focus = (
        "Verify fixture count meets occupancy minimums, fixture clearances (WC 15\" CL, 21\" front), "
        "water service size and pressure, DWV sizing and venting completeness, "
        "backflow preventers on irrigation/boiler/fire/dental, water heater T&P discharge, "
        "gas line sizing, low-flow fixtures where required."
    )


class MechanicalAgent(DepartmentReviewer):
    department_name = "Mechanical Inspector"
    department_code = "mechanical"
    department_icon = ""
    category = "mechanical"
    domain_expertise = (
        "International Mechanical Code (IMC), ventilation rates (Table 403.3.1.1), "
        "exhaust requirements (Section 501-505), duct construction and insulation (Chapter 6), "
        "combustion air (Chapter 8 / IFGC), refrigeration safety (Chapter 11), "
        "boilers (Chapter 10), commercial kitchen hoods (Section 507). Title 24 mechanical compliance."
    )
    review_focus = (
        "Verify ventilation rates for each space type, bathroom/kitchen exhaust, "
        "combustion air for fuel-fired equipment, duct insulation in unconditioned spaces, "
        "condensate disposal, equipment access clearances, MERV filtration where required, "
        "commercial kitchen hood sizing and fire suppression."
    )


class AccessibilityAgent(DepartmentReviewer):
    department_name = "Accessibility (ADA / CBC 11B)"
    department_code = "accessibility"
    department_icon = ""
    category = "accessibility"
    domain_expertise = (
        "2010 ADA Standards, CBC Chapter 11A (multi-family) and 11B (public accommodations), "
        "accessible route (Section 402), parking (Section 208), entrances (206.4), "
        "doors and gates (404), ramps (405), elevators (407), toilet rooms (603-604), "
        "reach ranges, signage (703), path-of-travel upgrades triggered by alterations."
    )
    review_focus = (
        "Verify continuous accessible route from arrival → parking → entrance → all public spaces, "
        "accessible parking count and van-accessible space, door clear widths (32\") and maneuvering clearances, "
        "ramp slopes (1:12), restroom turning radius and grab bars, reach ranges, "
        "signage with raised characters and braille, path-of-travel upgrades for alterations."
    )


class EnergyAgent(DepartmentReviewer):
    department_name = "Energy & Green Building"
    department_code = "energy"
    department_icon = ""
    category = "energy"
    domain_expertise = (
        "IECC 2021 / California Title 24 Part 6 (energy), CALGreen Part 11 (green building), "
        "envelope U-values and R-values by climate zone, fenestration SHGC/U, "
        "lighting power density (Table C405.3.2), occupancy/daylight controls, "
        "HVAC efficiency, water heating, PV solar (CA new SFD requirement), "
        "EV charging infrastructure (CALGreen 4.106.4), low-flow fixtures (5.303)."
    )
    review_focus = (
        "Verify envelope assemblies meet climate-zone U/R values, fenestration U/SHGC, "
        "lighting power and controls (occ sensors, daylight harvesting), "
        "duct location and insulation, mandatory PV (CA), EV-ready infrastructure, "
        "CalGreen low-flow fixtures, cool roof in applicable zones."
    )


class ZoningAgent(DepartmentReviewer):
    department_name = "Planning & Zoning"
    department_code = "zoning"
    department_icon = ""
    category = "zoning"
    domain_expertise = (
        "Local zoning ordinances, use districts and permitted uses, dimensional standards "
        "(setbacks, height limits, FAR, lot coverage), density limits, parking requirements, "
        "design review, CUP/variance triggers, historic and overlay districts, "
        "Hillside, Coastal, WUI overlays, ADU regulations (CA SB 9/10)."
    )
    review_focus = (
        "Verify proposed use is permitted by-right (or note CUP needed), front/side/rear setbacks "
        "meet district minimums, building height under limit, FAR and lot coverage within max, "
        "parking count meets ratio, identify any overlay districts (hillside, coastal, historic, WUI), "
        "ADU compliance if applicable."
    )


class PublicWorksAgent(DepartmentReviewer):
    department_name = "Public Works"
    department_code = "public_works"
    department_icon = ""
    category = "public_works"
    domain_expertise = (
        "Right-of-way improvements, driveway approaches and curb cuts, sidewalk replacement (ADA cross-slope), "
        "grading and drainage (cut/fill thresholds, retaining walls), stormwater LID/SWQMP (MS4 permits), "
        "utility connections (sewer lateral, water service), encroachment permits and bonds, "
        "traffic control plans for construction in ROW."
    )
    review_focus = (
        "Verify driveway width/location/sight triangle, sidewalk repair scope and ADA cross-slope, "
        "grading quantities and any required retaining walls or geotech, stormwater BMPs / LID for "
        "sites > 2,500 sf impervious, sewer lateral and water service tie-in points, "
        "encroachment permit scope, construction traffic control."
    )


class EnvironmentalAgent(DepartmentReviewer):
    department_name = "Environmental"
    department_code = "environmental"
    department_icon = ""
    category = "environmental"
    domain_expertise = (
        "NPDES Construction General Permit / SWPPP, CBC Chapter 7A Wildland-Urban Interface, "
        "CAL FIRE defensible space (PRC 4291), EPA RRP lead-safe work practices (pre-1978), "
        "NESHAP asbestos pre-demo survey, AQMD demolition notification, "
        "CEQA categorical exemptions vs. ND/MND, hazardous materials and Phase I ESA where applicable."
    )
    review_focus = (
        "Verify SWPPP/NOI for sites disturbing ≥ 1 acre, WUI ignition-resistant construction in fire zones, "
        "defensible space plan (0-5/5-30/30-100 ft), lead survey for pre-1978 renovations, "
        "asbestos survey + 10-day AQMD notice for demolition, identify any hazmat or contaminated soils, "
        "tree protection / heritage tree permits if applicable."
    )


# Registry — used by workflow.py to instantiate all departments
ALL_DEPARTMENTS = [
    BuildingSafetyAgent,
    FireAgent,
    ElectricalAgent,
    PlumbingAgent,
    MechanicalAgent,
    AccessibilityAgent,
    EnergyAgent,
    ZoningAgent,
    PublicWorksAgent,
    EnvironmentalAgent,
]
