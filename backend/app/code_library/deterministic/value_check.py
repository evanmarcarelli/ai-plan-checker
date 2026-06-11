"""Table-value cross-check: verify LLM-claimed table limits against the
deterministic table store.

The citation gate proves a cited SECTION exists; this module proves a cited
NUMBER is right. The failure mode it closes: a department reviewer cites
"IBC Table 506.2" (real) but claims the allowable area is 6,000 sf when the
table says 9,000 sf — the finding *looks* grounded (real table, real-sounding
number) and sails through the citation gate, yet hard-blocks a compliant
building on an invented limit.

Rules (deliberately one-sided to avoid punishing legitimate findings):

  * Table 506.2 (allowable area): a claimed allowable BELOW the tabular value
    is impossible — area modifications (frontage, sprinklers, IBC 506.3) only
    INCREASE the tabular base. Claimed < tabular ⇒ mismatch. Claimed above
    tabular is plausible (increases) and left alone.
  * Table 504.4 (allowable stories): the legitimate range is
    [tabular - 1 (non-sprinklered footnote), tabular]. A claim outside that
    range ⇒ mismatch.
  * IBC 403 (high-rise threshold): the threshold is a single scalar (75 ft
    base). A claimed threshold that differs ⇒ mismatch.

A mismatched NON_COMPLIANT is downgraded to NEEDS_REVIEW with both numbers in
the note — never deleted, so a human still sees and adjudicates it.

Pure deterministic text/number work; no LLM, no network. Unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from app.code_library.deterministic import table_store
from app.code_library.deterministic.engine import (
    normalize_construction_type,
    normalize_occupancy,
)
from app.models.schemas import ComplianceFinding, ComplianceStatus, ExtractedPlanData
from app.utils.logger import get_logger

logger = get_logger(__name__)

_NUM_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")

_T506_RE = re.compile(r"\b506\.2\b")
_T504_RE = re.compile(r"\b504\.4\b")
_HIGHRISE_RE = re.compile(r"\bIBC\s*403\b|\bhigh[- ]rise\b", re.IGNORECASE)


@dataclass
class ValueCheckStats:
    checked: int = 0
    mismatched: int = 0


def _first_number(*texts: Optional[str]) -> Optional[float]:
    for t in texts:
        if not t:
            continue
        m = _NUM_RE.search(t)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _note(table: str, claimed: float, expected: str) -> str:
    return (
        f" [Table cross-check: the claimed {table} value ({claimed:,.0f}) does "
        f"not match the adopted table value ({expected}). The cited number "
        f"could not be reproduced from the table — confirm before issuing. "
        f"Downgraded from non-compliant to needs-review.]"
    )


def _downgrade(f: ComplianceFinding, table: str, claimed: float, expected: str) -> None:
    f.status = ComplianceStatus.NEEDS_REVIEW
    marker = "[Table cross-check:"
    if marker not in (f.description or ""):
        f.description = (f.description or "") + _note(table, claimed, expected)


def _finding_cites(f: ComplianceFinding, pattern: re.Pattern) -> bool:
    hay = " ".join(filter(None, (
        f.source_citation,
        f.code_requirement.section,
        f.code_requirement.code_id,
        f.code_requirement.code_name,
    )))
    return bool(pattern.search(hay))


def cross_check_table_claims(
    findings: List[ComplianceFinding],
    plan_data: Optional[ExtractedPlanData],
    *,
    adoption_id: Optional[str] = None,
) -> ValueCheckStats:
    """Cross-check every NON_COMPLIANT finding that cites a known table.

    Mutates findings in place (downgrade + note on mismatch). Safe no-op when
    the plan's occupancy/construction can't be normalized (nothing to look
    up) or the finding carries no parseable number.
    """
    stats = ValueCheckStats()
    if not findings:
        return stats

    occ = normalize_occupancy(plan_data.occupancy_type) if plan_data else None
    ctype = normalize_construction_type(plan_data.construction_type) if plan_data else None

    for f in findings:
        if f.status != ComplianceStatus.NON_COMPLIANT:
            continue

        # ── Table 506.2: allowable area ─────────────────────────────
        if _finding_cites(f, _T506_RE) and occ and ctype:
            tabular = (table_store.t506_2(adoption_id).get(occ) or {}).get(ctype)
            claimed = _first_number(f.required_value)
            if isinstance(tabular, int) and claimed is not None:
                stats.checked += 1
                # Modifications only increase the base; below-tabular is impossible.
                if claimed < tabular * 0.99:
                    _downgrade(f, "IBC Table 506.2 allowable area", claimed, f"{tabular:,}")
                    stats.mismatched += 1
            continue

        # ── Table 504.4: allowable stories ──────────────────────────
        if _finding_cites(f, _T504_RE) and occ and ctype:
            tabular = (table_store.t504_4(adoption_id).get(occ) or {}).get(ctype)
            claimed = _first_number(f.required_value)
            if isinstance(tabular, int) and claimed is not None:
                stats.checked += 1
                legitimate = {tabular, max(1, tabular - 1)}  # non-sprinklered footnote
                if int(claimed) not in legitimate:
                    _downgrade(
                        f, "IBC Table 504.4 story limit", claimed,
                        f"{tabular} (or {max(1, tabular - 1)} non-sprinklered)",
                    )
                    stats.mismatched += 1
            continue

        # ── IBC 403: high-rise threshold ────────────────────────────
        if _finding_cites(f, _HIGHRISE_RE):
            threshold = table_store.high_rise_ft(adoption_id)
            claimed = _first_number(f.required_value)
            # Only judge claims that are unambiguously about the threshold
            # ("75 ft"): a required_value carrying some other number (an
            # occupant count, a story count) is not a threshold claim.
            if claimed is not None and "ft" in (f.required_value or "").lower():
                stats.checked += 1
                if abs(claimed - threshold) > 0.5:
                    _downgrade(f, "IBC 403 high-rise threshold (ft)", claimed, str(threshold))
                    stats.mismatched += 1

    if stats.mismatched:
        logger.info(
            f"[value_check] cross-checked {stats.checked} table claim(s); "
            f"downgraded {stats.mismatched} mismatch(es)"
        )
    return stats
