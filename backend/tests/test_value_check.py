"""Tests for the table-value cross-check and the citation-gate
contradiction guard — the two anti-hallucination layers added on top of the
existing citation gate."""
from typing import Optional

from app.code_library.deterministic.citation_gate import apply_citation_gate
from app.code_library.deterministic.value_check import cross_check_table_claims
from app.models.schemas import (
    CodeRequirement,
    ComplianceFinding,
    ComplianceStatus,
    ExtractedPlanData,
)


def _finding(
    section: str = "506.2",
    code_name: str = "International Building Code",
    status: ComplianceStatus = ComplianceStatus.NON_COMPLIANT,
    required_value: Optional[str] = None,
    description: str = "Area exceeds allowable.",
    citation: Optional[str] = None,
) -> ComplianceFinding:
    return ComplianceFinding(
        finding_id="f1",
        code_requirement=CodeRequirement(
            code_id=f"IBC-{section}", code_name=code_name, section=section,
        ),
        status=status,
        required_value=required_value,
        description=description,
        source_citation=citation,
    )


def _plan(occ="B", ctype="V-B") -> ExtractedPlanData:
    return ExtractedPlanData(occupancy_type=occ, construction_type=ctype)


# ── Table 506.2 (allowable area) ──────────────────────────────────────
# Hardcoded fallback table: B / V-B = 9,000 sf.


def test_t506_correct_claim_passes():
    f = _finding(required_value="9,000 SF allowable")
    stats = cross_check_table_claims([f], _plan())
    assert stats.checked == 1 and stats.mismatched == 0
    assert f.status == ComplianceStatus.NON_COMPLIANT


def test_t506_below_tabular_claim_downgraded():
    # Modifications only increase the tabular base — 6,000 is an invented limit.
    f = _finding(required_value="max 6,000 sf")
    stats = cross_check_table_claims([f], _plan())
    assert stats.mismatched == 1
    assert f.status == ComplianceStatus.NEEDS_REVIEW
    assert "Table cross-check" in f.description


def test_t506_above_tabular_claim_left_alone():
    # 18,000 could be a legitimate sprinkler/frontage increase (506.3).
    f = _finding(required_value="18,000 sf with sprinkler increase")
    stats = cross_check_table_claims([f], _plan())
    assert stats.mismatched == 0
    assert f.status == ComplianceStatus.NON_COMPLIANT


def test_t506_skips_when_plan_scope_unknown():
    f = _finding(required_value="6,000 sf")
    stats = cross_check_table_claims([f], _plan(occ=None, ctype=None))
    assert stats.checked == 0
    assert f.status == ComplianceStatus.NON_COMPLIANT


def test_compliant_findings_not_checked():
    f = _finding(required_value="6,000 sf", status=ComplianceStatus.COMPLIANT)
    stats = cross_check_table_claims([f], _plan())
    assert stats.checked == 0


# ── Table 504.4 (stories) ─────────────────────────────────────────────
# Hardcoded fallback: B / V-B = 2 stories (3 sprinklered varies by table rev).


def test_t504_legitimate_range_passes():
    from app.code_library.deterministic import table_store
    tabular = table_store.t504_4()["B"]["V-B"]
    f = _finding(section="504.4", required_value=f"{tabular} stories")
    stats = cross_check_table_claims([f], _plan())
    assert stats.checked == 1 and stats.mismatched == 0
    # Non-sprinklered footnote value is also legitimate.
    f2 = _finding(section="504.4", required_value=f"{max(1, tabular - 1)} stories max")
    assert cross_check_table_claims([f2], _plan()).mismatched == 0


def test_t504_invented_value_downgraded():
    from app.code_library.deterministic import table_store
    tabular = table_store.t504_4()["B"]["V-B"]
    f = _finding(section="504.4", required_value=f"{tabular + 5} stories")
    stats = cross_check_table_claims([f], _plan())
    assert stats.mismatched == 1
    assert f.status == ComplianceStatus.NEEDS_REVIEW


# ── IBC 403 high-rise threshold ───────────────────────────────────────


def test_highrise_correct_threshold_passes():
    f = _finding(section="403", code_name="IBC", citation="IBC 403",
                 required_value="75 ft threshold")
    stats = cross_check_table_claims([f], _plan())
    assert stats.checked == 1 and stats.mismatched == 0


def test_highrise_wrong_threshold_downgraded():
    f = _finding(section="403", code_name="IBC", citation="IBC 403",
                 required_value="55 ft threshold")
    stats = cross_check_table_claims([f], _plan())
    assert stats.mismatched == 1
    assert f.status == ComplianceStatus.NEEDS_REVIEW


def test_highrise_non_threshold_number_ignored():
    # required_value without "ft" is not a threshold claim.
    f = _finding(section="403", code_name="IBC", citation="IBC 403",
                 required_value="2 exits")
    stats = cross_check_table_claims([f], _plan())
    assert stats.checked == 0


# ── citation-gate contradiction guard ─────────────────────────────────


class _FakeSource:
    """Duck-typed code source: one known citation with fixed text."""

    def __init__(self, known: dict):
        self._known = known

    def verify_citation(self, citation: str) -> bool:
        return citation in self._known

    def get_source_text(self, citation: str):
        return self._known.get(citation)


EGRESS_TEXT = (
    "Two exits or exit access doorways from any space shall be provided "
    "where the occupant load exceeds the values in Table 1006.2.1."
)


def test_guard_supported_claim_untouched():
    f = _finding(
        section="1006.2.1", citation="IBC 1006.2.1",
        description="Two exits are required because the occupant load exceeds the table values.",
    )
    src = _FakeSource({"IBC 1006.2.1": EGRESS_TEXT})
    stats = apply_citation_gate([f], src, enforce=False, contradiction_guard=True)
    assert stats.verified == 1 and stats.contradicted == 0
    assert f.status == ComplianceStatus.NON_COMPLIANT
    assert f.verified is True and f.source_text


def test_guard_unrelated_claim_downgraded():
    # Real section, but the claim is about something the text never says.
    f = _finding(
        section="1006.2.1", citation="IBC 1006.2.1",
        description="Roofing membrane must achieve Class A fire classification rating.",
    )
    src = _FakeSource({"IBC 1006.2.1": EGRESS_TEXT})
    stats = apply_citation_gate([f], src, enforce=False, contradiction_guard=True)
    assert stats.contradicted == 1
    assert f.status == ComplianceStatus.NEEDS_REVIEW
    assert "does not support this claim" in f.description


def test_guard_missing_section_still_left_alone_in_enrich_mode():
    f = _finding(section="9999.9", citation="IBC 9999.9",
                 description="Anything at all.")
    src = _FakeSource({})
    stats = apply_citation_gate([f], src, enforce=False, contradiction_guard=True)
    assert stats.contradicted == 0 and stats.downgraded == 0
    assert f.status == ComplianceStatus.NON_COMPLIANT


def test_guard_off_by_default():
    f = _finding(
        section="1006.2.1", citation="IBC 1006.2.1",
        description="Roofing membrane must achieve Class A fire classification rating.",
    )
    src = _FakeSource({"IBC 1006.2.1": EGRESS_TEXT})
    stats = apply_citation_gate([f], src, enforce=False)
    assert stats.contradicted == 0
    assert f.status == ComplianceStatus.NON_COMPLIANT


def test_guard_does_not_touch_non_violations():
    f = _finding(
        section="1006.2.1", citation="IBC 1006.2.1",
        status=ComplianceStatus.NEEDS_REVIEW,
        description="Unrelated claim about roofing membranes.",
    )
    src = _FakeSource({"IBC 1006.2.1": EGRESS_TEXT})
    stats = apply_citation_gate([f], src, enforce=False, contradiction_guard=True)
    assert stats.contradicted == 0
    assert f.status == ComplianceStatus.NEEDS_REVIEW
