"""Turn the applicable correction checklist into per-department requirements.

The department reviewers already loop over a `requirements` list, review the
plan against each, and run a citation gate. So the cleanest way to give them
real-plan-check coverage is to feed the standard-correction-list items in as
extra requirements — they ride the existing prompt + gate + provenance with no
new review path. Each item keeps its code citation and source URL.
"""
from __future__ import annotations

from typing import Dict, List

from app.code_library.checklists.loader import select_checklist
from app.models.schemas import CodeRequirement, ExtractedPlanData
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _to_requirement(checklist_id: str, src_url: str, authority: str, item) -> CodeRequirement:
    cite = item.code_citation
    return CodeRequirement(
        # Unique, citable id. The reviewer prompt shows "[<code_id>] <text>" and
        # asks the model to echo the bracketed id, so the gate matches cleanly.
        code_id=f"{checklist_id}:{item.item_id}",
        code_name=f"{authority} Standard Correction List",
        section=cite or item.item_id,
        description=item.text,
        category=item.department_code or "building_safety",
        requirement_type="completeness",
        jurisdiction_specific=True,
        full_text=(f"[{cite}] " if cite else "") + item.text,
        source=src_url,
    )


def checklist_requirements(
    plan_data: ExtractedPlanData,
    max_per_department: int = 40,
) -> Dict[str, List[CodeRequirement]]:
    """Applicable correction-list items as requirements, keyed by department_code.

    Returns {} when no checklist matches the plan's occupancy (e.g. commercial
    until we ingest a commercial list) — the pipeline then behaves as before.
    """
    occ = getattr(plan_data, "occupancy_type", None)
    checklist = select_checklist(occ)
    if not checklist:
        return {}

    out: Dict[str, List[CodeRequirement]] = {}
    for item in checklist.items:
        dept = item.department_code or "building_safety"
        bucket = out.setdefault(dept, [])
        if len(bucket) >= max_per_department:
            continue
        bucket.append(_to_requirement(
            checklist.id, checklist.source.url, checklist.source.authority, item
        ))

    total = sum(len(v) for v in out.values())
    logger.info(
        f"[checklists] {checklist.id} -> {total} correction items across "
        f"{len(out)} departments for occupancy {occ!r}"
    )
    return out
