import asyncio
import re
import uuid
from datetime import datetime
from typing import Dict, Any, Callable, List, Optional
from app.agents.surveyor import SurveyorAgent
from app.agents.librarian import LibrarianAgent
from app.agents.departments import ALL_DEPARTMENTS, DepartmentReviewer
from app.agents.archetype import (
    CoastalZoneInfo, ParcelInfo, PropertyProfile, WuiInfo,
    classify_archetype, render_archetype_banner,
)
from app.agents.critic import critique_finding, apply_critique
from app.config.pilot import PIPELINE_GATES, ARCHETYPE_UNCLASSIFIED
from app.code_library.checklists.checker import checklist_requirements
from app.config import settings
from app.models.schemas import (
    ProcessingJob, AgentLog, ComplianceReport, ComplianceFinding,
    ComplianceSummary, ComplianceStatus, DepartmentReview, CodeRequirement,
)
from app.code_library.adapter import CorpusCodeSource
from app.code_library.adoption.resolver import get_resolver
from app.code_library.deterministic.engine import evaluate_plan
from app.code_library.deterministic.citation_gate import apply_citation_gate
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Cap how many department reviewers run concurrently. The full set is 10.
# Render Free has tight CPU/RAM/network limits that kill background tasks
# stone-dead when several outbound HTTPS calls overlap. Empirically 3 in
# flight is still too many on Free — the dyno hangs after a couple
# completions. 2 is the safe ceiling for Free; bump to 5–10 the moment
# the founder upgrades to a Starter ($7/mo) or larger dyno.
DEPARTMENT_CONCURRENCY = 2


def _address_mismatch_reason(
    user_address: Optional[str],
    plan_address: Optional[str],
    extracted_city: Optional[str],
    site_city: Optional[str],
) -> Optional[str]:
    """Why the address entered at upload and the plan set disagree, or None.

    Deliberately conservative: only a different leading street number or a
    clearly different city counts. Fuzzier comparison (street-name spelling,
    abbreviations, missing zips, suite numbers) produces noise, and a false
    mismatch finding erodes trust faster than a missed one."""
    if user_address and plan_address:
        u = re.match(r"\s*(\d+)", user_address)
        p = re.match(r"\s*(\d+)", plan_address)
        if u and p and u.group(1) != p.group(1):
            return (
                f"the plan set reads '{plan_address.strip()}' but the application "
                f"address entered at upload is '{user_address.strip()}' "
                f"(different street numbers)"
            )
    if extracted_city and site_city:
        a, b = extracted_city.strip().lower(), site_city.strip().lower()
        if a and b and a not in b and b not in a:
            return (
                f"the plans appear to reference {extracted_city}, but the address "
                f"entered at upload geocodes to {site_city}"
            )
    return None


def _overlay_summary(overlays: Dict[str, Any]) -> str:
    """One log line for the agent timeline: each overlay as yes/no/its detail,
    'unknown' when that layer's lookup failed (unknown must never read as no)."""
    errors = overlays.get("errors") or {}

    def describe(key: str, detail_key: str = None) -> str:
        verdict = overlays.get(key)
        if verdict is None:
            return "unknown" if key in errors else "n/a"
        if key == "flood":
            zone = verdict.get("zone") or "none"
            return f"{zone}{' (SFHA)' if verdict.get('in_sfha') else ''}"
        if not verdict.get("in_zone"):
            return "no"
        detail = detail_key and verdict.get(detail_key)
        return str(detail) if detail else "yes"

    return (
        f"fire: {describe('fire_hazard', 'severity')} | flood: {describe('flood')} | "
        f"coastal: {describe('coastal')} | hillside: {describe('hillside')} | "
        f"HPOZ: {describe('hpoz', 'name')} | methane: {describe('methane', 'kind')} | "
        f"liquefaction: {describe('liquefaction')}"
    )


def _maybe_add_coastal_layer(resolved_stack, site_context) -> bool:
    """Add the Coastal Act corpus layer ("CA:Coastal") to the resolved stack
    when the GIS overlay sweep put the project site inside the Coastal Zone.

    Static adoption records carry the key for jurisdictions wholly inside the
    zone (Malibu); this handles coastal parcels inside ordinary jurisdictions
    (Venice, San Pedro) whose records don't. Returns True when the key was
    added, so the caller can log it.
    """
    if resolved_stack is None:
        return False
    overlays = (site_context or {}).get("overlays") or {}
    if not (overlays.get("coastal") or {}).get("in_zone"):
        return False
    keys = list(resolved_stack.corpus_layer_keys or [])
    if "CA:Coastal" in keys:
        return False
    resolved_stack.corpus_layer_keys = keys + ["CA:Coastal"]
    return True


def _property_profile_from_overlays(site_context, jurisdiction) -> Optional[PropertyProfile]:
    """Build the archetype gate's PropertyProfile from the GIS overlay sweep
    in site_context. None when no sweep ran (no address / geocode failed) —
    the gate then falls back to plan-text cues as before. Per-overlay: a key
    absent from the sweep (layer errored or out of geographic scope) maps to
    None/absent, never to False, so 'unknown' can't suppress a text-cue reject.
    """
    overlays = (site_context or {}).get("overlays") or {}
    if not overlays.get("checked"):
        return None
    fire = overlays.get("fire_hazard") or {}
    # CBC Ch. 7A applies in all SRA classes and Very High LRA — that's the
    # wildfire-review trigger the gate's WUI reject keys on.
    in_wui = bool(fire.get("in_zone")) and (
        fire.get("severity") == "Very High" or fire.get("responsibility") == "SRA"
    )
    haz = (fire.get("severity") or "").lower().replace(" ", "_") or None
    # City AND county: the gate's Ventura detection regexes this string for
    # county names, so "Ojai, CA" without the county would silently disarm
    # the Ventura VHFHSZ reject.
    place = ", ".join(
        p for p in [jurisdiction.city, jurisdiction.county, jurisdiction.state_code] if p
    )
    return PropertyProfile(
        parcel=ParcelInfo(jurisdiction=place or None),
        coastal_zone=(
            CoastalZoneInfo(in_coastal_zone=bool(overlays["coastal"].get("in_zone")))
            if overlays.get("coastal") is not None else None
        ),
        wui_zone=(
            WuiInfo(in_wui=in_wui, haz_class=haz)
            if overlays.get("fire_hazard") is not None else None
        ),
        in_hpoz=(overlays["hpoz"].get("in_zone") if overlays.get("hpoz") is not None else None),
        in_hillside=(
            overlays["hillside"].get("in_zone") if overlays.get("hillside") is not None else None
        ),
    )


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
        site_context: Optional[Dict[str, Any]] = None,
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

            # Vision pass status — surfaces in the Agent Logs tab so the user
            # can see whether the title-sheet read succeeded. Without this, a
            # silent vision failure (bad key, rate limit) would look identical
            # to a successful run that simply didn't find the title sheet.
            vision_data = state.get("vision_data") or {}
            vision_error = state.get("vision_error")
            if vision_error:
                await emit(
                    "Surveyor",
                    f"Title-sheet vision pass failed: {vision_error} "
                    f"(falling back to text-layer regex extraction only)",
                    level="warning",
                    data={"vision_error": vision_error},
                )
            elif vision_data:
                filled = [k for k, v in vision_data.items() if v not in (None, "", []) and k != "is_title_sheet"]
                await emit(
                    "Surveyor",
                    f"Title-sheet vision pass read {len(filled)} field(s): {', '.join(filled) or '(none)'}",
                    data={"vision_fields": filled, "is_title_sheet": vision_data.get("is_title_sheet")},
                )
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

        # ----- USER-PROVIDED SITE CONTEXT -----
        # When the customer entered a project address at upload, the worker
        # already geocoded it and resolved the adoption stack (site_resolver).
        # That jurisdiction is authoritative — a typed, geocoded address beats
        # an LLM reading a title block — so it overrides the Surveyor's guess
        # before the adoption resolver and reviewers consume it. The
        # Surveyor's own extraction is NOT discarded: it becomes a cross-check,
        # and a disagreement is surfaced as a finding below (real plan checkers
        # flag application/plan address mismatches too).
        if site_context:
            state["site_context"] = site_context
            extracted_city, extracted_state_code = j.city, j.state_code
            site_jur = site_context.get("jurisdiction") or {}
            if site_jur.get("state_code") or site_jur.get("county") or site_jur.get("city"):
                j.city = site_jur.get("city") or j.city
                j.county = site_jur.get("county") or j.county
                j.state = site_jur.get("state") or j.state
                j.state_code = site_jur.get("state_code") or j.state_code
                adoption_info = site_context.get("adoption") or {}
                if adoption_info.get("authority"):
                    j.governing_authority = adoption_info["authority"]
                j.confidence = max(j.confidence, 0.95)
                replaced = (
                    f" (plan-text guess was '{extracted_city or '?'}, {extracted_state_code or '?'}')"
                    if (extracted_city or extracted_state_code)
                    and (extracted_city != j.city or extracted_state_code != j.state_code)
                    else ""
                )
                await emit(
                    "Surveyor",
                    f"Jurisdiction pinned from the project address provided at upload: "
                    f"{j.city or j.county or 'Unknown'}, {j.state_code or '??'}{replaced}",
                    data={"source": "user_address", "city": j.city,
                          "county": j.county, "state": j.state_code},
                )
            mismatch = _address_mismatch_reason(
                (site_context.get("address") or {}).get("input"),
                pd.project_address,
                extracted_city,
                site_jur.get("city"),
            )
            if mismatch:
                state["address_mismatch"] = mismatch
                await emit("Surveyor", f"Address cross-check: {mismatch}", level="warning")

        # ----- ARCHETYPE GATE -----
        # Decide whether this submittal falls inside the current pilot's
        # broad-scope 90% target. Out-of-pilot archetypes (Hillside, HPOZ,
        # Coastal Zone, high-rise, Ventura VHFHSZ, ag buildings, multi-
        # family new construction, mixed-use new) get a prominent CRITICAL
        # finding prepended to the report so reviewers see "manual review
        # required" before they read any AI output. The downstream pipeline
        # still runs — we don't yet hard short-circuit because the dashboard
        # doesn't have a graceful "out-of-scope" view. The CRITICAL finding
        # is sufficient signal for now. See docs/PILOT_BRIEF.md.
        plan_text_for_gate = "\n".join(pd.raw_text_by_page.values()) if pd.raw_text_by_page else ""
        # GIS overlays (resolved from the upload address) make the gate's
        # overlay rejects authoritative instead of plan-text-cue guesses.
        property_profile = _property_profile_from_overlays(state.get("site_context"), j)
        if property_profile is not None:
            overlays = state["site_context"].get("overlays") or {}
            await emit(
                "Archetype",
                f"GIS overlays from project address — {_overlay_summary(overlays)}",
                data={"overlays": overlays},
            )
        archetype_result = classify_archetype(pd, plan_text_for_gate, property_profile=property_profile)
        state["archetype"] = archetype_result
        await emit(
            "Archetype",
            render_archetype_banner(archetype_result),
            level="info" if archetype_result.in_pilot_scope else "warning",
            data={
                "archetype": archetype_result.archetype,
                "in_pilot_scope": archetype_result.in_pilot_scope,
                "excluded_overlays": archetype_result.excluded_overlays,
                "reasoning": archetype_result.reasoning,
            },
        )

        # ----- ADOPTION RESOLVER -----
        # Resolve which code editions + local amendments + overlays apply for
        # the jurisdiction the Surveyor found. This is the "which code stack"
        # layer; downstream agents filter the corpus to resolved_stack's
        # layer keys and cite the resolved edition.
        try:
            resolved_stack = get_resolver().resolve(j.state_code, j.county, j.city)
            if _maybe_add_coastal_layer(resolved_stack, state.get("site_context")):
                await emit(
                    "Adoption",
                    "Site is inside the CA Coastal Zone (GIS) — Coastal Act layer "
                    "added to the corpus scope for retrieval and citations.",
                )
            state["resolved_stack"] = resolved_stack
            await emit(
                "Adoption",
                f"Adopted code: {resolved_stack.headline_code_version()} "
                f"({resolved_stack.authority or 'baseline AHJ'}) — "
                f"corpus layers {resolved_stack.corpus_layer_keys}",
                data={
                    "matched": resolved_stack.matched_id,
                    "edition": resolved_stack.effective_edition,
                    "layers": resolved_stack.corpus_layer_keys,
                    "overlays": resolved_stack.overlays,
                    "buy_license_layers": resolved_stack.buy_license_layers,
                },
            )
            if resolved_stack.permit_date_note:
                await emit("Adoption", resolved_stack.permit_date_note)
        except Exception as e:
            # Non-fatal: fall back to corpus-only behavior if the map can't load.
            resolved_stack = None
            state["resolved_stack"] = None
            await emit("Adoption", f"Adoption resolve skipped: {e}", level="warning")

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
            county=j.county,
            # The workflow's stack may carry dynamically-added layers (e.g.
            # CA:Coastal from the GIS sweep) that a fresh resolve would drop.
            layer_keys=(list(resolved_stack.corpus_layer_keys) if resolved_stack else None),
        )
        codes_by_category: Dict[str, List] = {}
        for c in full_codes:
            codes_by_category.setdefault(c.category, []).append(c)

        # ----- STANDARD CORRECTION CHECKLIST -----
        # Feed published plan-check correction-list items to each department as
        # extra requirements, so coverage matches a real plan check (a real
        # residential set runs many pages of corrections). They ride the same
        # reviewer prompt + citation gate as code requirements. Toggle via
        # settings.checklist_review_enabled (default on).
        checklist_reqs: Dict[str, List] = {}
        if getattr(settings, "checklist_review_enabled", True):
            checklist_reqs = checklist_requirements(
                pd,
                max_per_department=int(getattr(settings, "checklist_max_per_department", 40)),
                city=j.city,
                state=j.state_code,
            )
            if checklist_reqs:
                await emit(
                    "Librarian",
                    f"Loaded standard correction-list coverage: "
                    f"{sum(len(v) for v in checklist_reqs.values())} items across "
                    f"{len(checklist_reqs)} departments.",
                )

        # ----- DETERMINISTIC ENGINE (runs BEFORE the LLM reviewers) -----
        # Compute the high-trust code-math up front so each department reviewer
        # is handed its verified findings as authoritative context — the LLM
        # never recomputes area/story/completeness math (where it silently
        # errs). The gated findings also surface as their own department below.
        det_overlays = resolved_stack.overlays if resolved_stack else None
        is_residential = (pd.plan_type and pd.plan_type.value in ("residential", "mixed_use"))
        det_ladbs_sfd = bool(
            resolved_stack and resolved_stack.matched_id == "ca_los_angeles_city" and is_residential
        )
        det_findings = evaluate_plan(pd, overlays=det_overlays, ladbs_sfd=det_ladbs_sfd)
        det_gate = apply_citation_gate(det_findings, self.code_db, enforce=True)
        await emit(
            "Deterministic Code Check",
            f"Computed {len(det_findings)} code-math finding(s) up front; citation gate "
            f"verified {det_gate.verified}, downgraded {det_gate.downgraded}. "
            f"Sharing verified facts with the department reviewers.",
            data={"findings": len(det_findings), "verified": det_gate.verified,
                  "downgraded": det_gate.downgraded},
        )

        # Bounded concurrency: limit the parallel reviewers so Render Free
        # is not asked to juggle 10 simultaneous outbound HTTPS calls.
        sem = asyncio.Semaphore(DEPARTMENT_CONCURRENCY)

        async def run_one(dept: DepartmentReviewer) -> DepartmentReview:
            dept_codes = (
                codes_by_category.get(dept.category, [])
                + checklist_reqs.get(dept.department_code, [])
            )
            await emit(dept.department_name, f"Starting review ({len(dept_codes)} codes)...")
            async with sem:
                return await _do_review(dept, dept_codes)

        async def _do_review(dept: DepartmentReviewer, dept_codes: list) -> DepartmentReview:
            try:
                review = await dept.review(
                    pd, dept_codes, amendments, code_version,
                    deterministic_findings=det_findings,
                )
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

        # ----- CITATION GATE (enrich the LLM findings) + DET DEPARTMENT -----
        # The deterministic findings were computed up front (above) and shared
        # with the reviewers. Here we (a) enrich the LLM department findings
        # with verbatim corpus text where groundable (never downgrading for a
        # MISSING section — the corpus is too thin to be authoritative
        # against dept retrieval — but downgrading CONTRADICTED claims, where
        # the section IS in the corpus and its text doesn't support the
        # claim), and (b) surface the deterministic findings as their own
        # department.
        contradiction_guard = bool(getattr(settings, "citation_contradiction_guard", True))
        llm_gate_contradicted = 0
        for r in reviews:
            g = apply_citation_gate(
                r.findings, self.code_db,
                enforce=False, contradiction_guard=contradiction_guard,
            )
            llm_gate_contradicted += g.contradicted
        if llm_gate_contradicted:
            await emit(
                "Citation Gate",
                f"Contradiction guard: {llm_gate_contradicted} non-compliant finding(s) "
                f"cited a section whose text does not support the claim — "
                f"downgraded to needs-review with the cited text attached.",
                level="warning",
                data={"contradicted": llm_gate_contradicted},
            )

        # ----- TABLE-VALUE CROSS-CHECK on LLM findings -----
        # A reviewer citing a real table with an invented number (e.g. "Table
        # 506.2 allows 6,000 sf" when it says 9,000) survives the citation
        # gate. Reproduce the claimed limit from the deterministic table
        # store; downgrade what can't be reproduced.
        if bool(getattr(settings, "table_value_cross_check", True)):
            from app.code_library.deterministic.value_check import cross_check_table_claims
            mismatched = checked = 0
            for r in reviews:
                vs = cross_check_table_claims(r.findings, pd)
                mismatched += vs.mismatched
                checked += vs.checked
            if checked:
                await emit(
                    "Table Cross-Check",
                    f"Reproduced {checked} claimed table value(s) from the deterministic "
                    f"table store; {mismatched} could not be reproduced and were "
                    f"downgraded to needs-review.",
                    level="warning" if mismatched else "info",
                    data={"checked": checked, "mismatched": mismatched},
                )

        if det_findings:
            det_summary = self._summarize(det_findings)
            det_status = (
                "rejected" if det_summary.non_compliant and det_summary.critical_issues
                else "conditional" if (det_summary.non_compliant or det_summary.needs_review)
                else "cleared"
            )
            reviews.append(DepartmentReview(
                department="Deterministic Code Check",
                department_code="deterministic",
                icon="📐",
                summary=det_summary,
                findings=det_findings,
                review_status=det_status,
                notes=(
                    f"Deterministic engine: {len(det_findings)} finding(s). "
                    f"Citation gate verified {det_gate.verified}, "
                    f"downgraded {det_gate.downgraded} unverifiable assertion(s) to needs-review."
                ),
            ))

        # ----- SYNTHESIZE FINAL REPORT -----
        await emit("Coordinator", "Aggregating findings across all departments...")
        all_findings: List[ComplianceFinding] = []
        for r in reviews:
            all_findings.extend(r.findings)

        # ----- OUT-OF-PILOT INJECTION -----
        # If the archetype gate flagged this submittal as out-of-scope, prepend
        # a CRITICAL finding so reviewers see "manual review required" above
        # any AI-generated findings. The downstream pipeline already ran;
        # this is the loudest defensible signal we can attach short of a
        # full short-circuit (which the dashboard doesn't yet support).
        archetype_result = state.get("archetype")
        if archetype_result is not None and not archetype_result.in_pilot_scope:
            why = (
                "; ".join(archetype_result.excluded_overlays)
                if archetype_result.excluded_overlays
                else (archetype_result.reasoning[-1] if archetype_result.reasoning else "out of pilot scope")
            )
            # Two different verdicts, two different findings:
            #  - "unclassified" means we couldn't auto-determine the archetype
            #    (e.g. the title sheet never stated occupancy/construction). The
            #    plan may well be in scope — flag it for manual review, don't
            #    stamp it "out of scope" with a critical finding.
            #  - any other out-of-pilot archetype (hillside, coastal, high-rise,
            #    multifamily, …) is a positive identification that it's outside
            #    pilot scope — keep the loud critical signal.
            undetermined = archetype_result.archetype == ARCHETYPE_UNCLASSIFIED
            if undetermined:
                gate_desc = (
                    f"ARCHETYPE UNDETERMINED. {why}. The plan's occupancy/"
                    f"construction couldn't be read automatically, so it could "
                    f"not be auto-classified — a reviewer should confirm scope. "
                    f"AI findings below still ran and are advisory."
                )
                gate_reco = "Manual review recommended — confirm building archetype/scope."
                gate_sev = "medium"
                gate_code_desc = "Submittal archetype could not be auto-determined."
            else:
                gate_desc = (
                    f"OUT OF PILOT SCOPE ({archetype_result.archetype}). "
                    f"Reason: {why}. AI findings below are advisory only — "
                    f"this submittal needs manual reviewer attention."
                )
                gate_reco = "Send to manual review — outside current AI pilot scope."
                gate_sev = "critical"
                gate_code_desc = "Submittal archetype is outside the current AI pilot scope."
            all_findings.insert(0, ComplianceFinding(
                finding_id=str(uuid.uuid4()),
                code_requirement=CodeRequirement(
                    code_id=f"PILOT-SCOPE-{archetype_result.archetype}",
                    code_name="Pilot scope gate",
                    section=archetype_result.archetype,
                    description=gate_code_desc,
                    category="intake",
                    source="archetype_gate",
                ),
                status=ComplianceStatus.NEEDS_REVIEW,
                plan_value=archetype_result.archetype,
                required_value="in-pilot archetype",
                description=gate_desc,
                recommendation=gate_reco,
                severity=gate_sev,
                confidence=1.0,
                verified=True,
                source_text="docs/PILOT_BRIEF.md — out-of-pilot archetypes",
                source_citation=f"Pilot scope ({archetype_result.archetype})",
            ))

        # ----- ADDRESS CROSS-CHECK INJECTION -----
        # The user-entered address and the plan set disagreed (detected right
        # after the Surveyor ran). Surface it at the top: every jurisdiction-
        # dependent check below used the upload address, so if the plans are
        # for a different site the whole report's code stack may be wrong.
        mismatch_reason = state.get("address_mismatch")
        if mismatch_reason:
            user_addr = ((state.get("site_context") or {}).get("address") or {}).get("input")
            all_findings.insert(0, ComplianceFinding(
                finding_id=str(uuid.uuid4()),
                code_requirement=CodeRequirement(
                    code_id="SITE-ADDRESS-MISMATCH",
                    code_name="Application / plan address cross-check",
                    section="intake",
                    description="The project address on the application must match the plan set.",
                    category="intake",
                    source="site_resolver",
                ),
                status=ComplianceStatus.NEEDS_REVIEW,
                plan_value=pd.project_address or "address not found on plans",
                required_value=user_addr,
                description=(
                    f"ADDRESS MISMATCH: {mismatch_reason}. The jurisdiction and code "
                    f"editions for this review were taken from the address entered at "
                    f"upload — if the plans are for a different site, re-run the check "
                    f"with the correct address."
                ),
                recommendation=(
                    "Confirm the project address: correct the title block on the plans "
                    "or re-submit with the right application address."
                ),
                severity="high",
                confidence=1.0,
                verified=True,
                source_text="Upload-time address pre-check (site resolver)",
                source_citation="Site address cross-check",
            ))

        # ----- ADVERSARIAL CRITIC LOOP -----
        # Run a cross-model critique on the top-N non_compliant findings to
        # suppress false positives. Different model from the proposer
        # (Sonnet → Opus). Disagreements with high confidence downgrade the
        # finding to needs_review with the rebuttal attached.
        sev_order_for_critic = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        critic_candidates = sorted(
            [f for f in all_findings if f.status == ComplianceStatus.NON_COMPLIANT],
            key=lambda f: sev_order_for_critic.get(f.severity, 4),
        )[: PIPELINE_GATES.critic_max_findings_per_run]
        if critic_candidates:
            await emit(
                "Critic",
                f"Cross-model adversarial review on {len(critic_candidates)} top non_compliant finding(s)...",
                data={"count": len(critic_candidates), "max": PIPELINE_GATES.critic_max_findings_per_run},
            )
            plan_text_excerpt = "\n".join(pd.raw_text_by_page.values())[:4000] if pd.raw_text_by_page else None
            downgraded = 0
            disputed = 0
            for f in critic_candidates:
                try:
                    verdict = await critique_finding(
                        finding=f,
                        scope=pd,
                        plan_text_excerpt=plan_text_excerpt,
                    )
                    pre_status = f.status
                    apply_critique(f, verdict)
                    if not verdict.agrees:
                        disputed += 1
                        if f.status != pre_status:
                            downgraded += 1
                except Exception as critic_err:
                    await emit(
                        "Critic",
                        f"Critique failed for {f.finding_id}: {critic_err}",
                        level="warning",
                    )
            await emit(
                "Critic",
                f"Critic run complete. {disputed} disputed, {downgraded} downgraded to needs_review.",
                data={"disputed": disputed, "downgraded": downgraded},
            )

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
            sources_used=["code_library/bm25", "deterministic_engine", "citation_gate"],
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
