"""
Tests for the agent workflow.
Run with: pytest tests/ -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.surveyor import SurveyorAgent
from app.agents.librarian import LibrarianAgent
from app.agents.auditor import AuditorAgent
from app.models.schemas import (
    Jurisdiction, ExtractedPlanData, PlanType, CodeRequirement,
    ComplianceStatus
)
from app.services.code_database import CodeDatabase


# ─── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def sample_jurisdiction():
    return Jurisdiction(
        city="Los Angeles",
        state="California",
        state_code="CA",
        country="USA",
        seismic_zone="D",
        confidence=0.9,
    )


@pytest.fixture
def sample_plan_data():
    return ExtractedPlanData(
        project_name="Test Commercial Building",
        plan_type=PlanType.COMMERCIAL,
        occupancy_type="B",
        construction_type="Type V-B",
        building_height=24.0,
        building_area=5000.0,
        dimensions={
            "corridor_widths": [48.0, 36.0],  # One compliant, one narrow
            "door_widths": [36.0],
            "stair_width": 48.0,
            "ceiling_height": 9.0,
            "occupant_load": 50,
        },
        elements=[
            MagicMock(element_type="fire_suppression"),
            MagicMock(element_type="egress"),
            MagicMock(element_type="accessibility"),
        ],
        materials=["concrete", "steel"],
        raw_text_by_page={1: "Sample plan text"},
        title_block_text="PROJECT: Test Building\nADDRESS: 123 Main St, Los Angeles, CA 90001",
    )


@pytest.fixture
def code_database():
    return CodeDatabase()


# ─── Code Database Tests ─────────────────────────────────────────────

class TestCodeDatabase:

    def test_get_applicable_codes_generic(self, code_database):
        codes = code_database.get_applicable_codes(None, None)
        assert len(codes) > 0
        categories = {c.category for c in codes}
        assert "fire_safety" in categories
        assert "accessibility" in categories

    def test_get_applicable_codes_california(self, code_database):
        codes = code_database.get_applicable_codes("CA", "Los Angeles")
        assert len(codes) > 0
        ca_codes = [c for c in codes if c.jurisdiction_specific]
        assert len(ca_codes) > 0
        # Should have seismic codes
        seismic = [c for c in ca_codes if "seismic" in c.description.lower() or "CBC" in c.code_name]
        assert len(seismic) > 0

    def test_get_applicable_codes_florida(self, code_database):
        codes = code_database.get_applicable_codes("FL", "Miami")
        fl_codes = [c for c in codes if c.jurisdiction_specific]
        assert len(fl_codes) > 0
        wind_codes = [c for c in fl_codes if "wind" in c.description.lower() or "hurricane" in c.full_text.lower()]
        assert len(wind_codes) > 0

    def test_get_code_version(self, code_database):
        assert "California" in code_database.get_code_version("CA")
        assert "Florida" in code_database.get_code_version("FL")
        assert "IBC" in code_database.get_code_version("DEFAULT")

    def test_get_jurisdiction_amendments(self, code_database):
        amendments = code_database.get_jurisdiction_amendments("CA", "Los Angeles")
        assert len(amendments) > 0
        assert any("CALGreen" in a or "Title 24" in a or "LADBS" in a for a in amendments)


# ─── Auditor Tests ───────────────────────────────────────────────────

class TestAuditorAgent:

    @pytest.fixture
    def auditor(self):
        return AuditorAgent()

    @pytest.fixture
    def sample_requirements(self, code_database):
        return code_database.get_applicable_codes("CA", "Los Angeles")

    def test_rule_based_corridor_compliant(self, auditor, sample_plan_data, sample_requirements):
        """Corridor at 48" should be compliant against 44" min."""
        # Force corridor to be compliant
        sample_plan_data.dimensions["corridor_widths"] = [48.0]
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)

        corridor_findings = [
            f for f in findings
            if f.code_requirement.code_id == "IBC-1005.1"
        ]
        assert len(corridor_findings) > 0
        assert corridor_findings[0].status == ComplianceStatus.COMPLIANT

    def test_rule_based_corridor_non_compliant(self, auditor, sample_plan_data, sample_requirements):
        """Corridor at 32" should be non-compliant against 44" min."""
        sample_plan_data.dimensions["corridor_widths"] = [32.0]
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)

        corridor_findings = [
            f for f in findings
            if f.code_requirement.code_id == "IBC-1005.1"
        ]
        assert len(corridor_findings) > 0
        assert corridor_findings[0].status == ComplianceStatus.NON_COMPLIANT
        assert corridor_findings[0].severity == "critical"
        assert "32" in corridor_findings[0].plan_value

    def test_rule_based_door_compliant(self, auditor, sample_plan_data, sample_requirements):
        """Door at 36" should be compliant against 32" min."""
        sample_plan_data.dimensions["door_widths"] = [36.0]
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)

        door_findings = [
            f for f in findings
            if f.code_requirement.code_id in ("IBC-1010.1.1",)
        ]
        if door_findings:
            assert door_findings[0].status == ComplianceStatus.COMPLIANT

    def test_rule_based_sprinkler_present(self, auditor, sample_plan_data, sample_requirements):
        """Sprinkler system present should be compliant."""
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)
        sprinkler = [f for f in findings if f.code_requirement.code_id == "IFC-903.2"]
        assert len(sprinkler) > 0
        assert sprinkler[0].status == ComplianceStatus.COMPLIANT

    def test_rule_based_sprinkler_missing(self, auditor, sample_plan_data, sample_requirements):
        """Missing sprinkler should need review."""
        sample_plan_data.elements = []  # Remove all elements
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)
        sprinkler = [f for f in findings if f.code_requirement.code_id == "IFC-903.2"]
        assert len(sprinkler) > 0
        assert sprinkler[0].status == ComplianceStatus.NEEDS_REVIEW

    def test_build_report_summary(self, auditor, sample_plan_data, sample_requirements, sample_jurisdiction):
        """Report summary counts should be consistent."""
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)
        report = auditor._build_report(
            findings, sample_jurisdiction, sample_plan_data,
            sample_requirements, "2022 CBC", ["mock_database"]
        )

        s = report.summary
        assert s.total_checks == len(findings)
        assert s.compliant + s.non_compliant + s.needs_review + s.not_applicable == s.total_checks
        assert 0.0 <= s.compliance_score <= 1.0

    def test_findings_sorted_by_severity(self, auditor, sample_plan_data, sample_requirements, sample_jurisdiction):
        """Critical findings should appear first."""
        # Make corridor non-compliant (critical)
        sample_plan_data.dimensions["corridor_widths"] = [28.0]
        findings = auditor._run_rule_based_checks(sample_plan_data, sample_requirements)
        report = auditor._build_report(
            findings, sample_jurisdiction, sample_plan_data,
            sample_requirements, "2022 CBC", ["mock_database"]
        )
        # First finding should be critical or high severity
        if len(report.findings) > 0:
            assert report.findings[0].severity in ("critical", "high")


# ─── Librarian Tests ─────────────────────────────────────────────────

class TestLibrarianAgent:

    @pytest.fixture
    def librarian(self):
        agent = LibrarianAgent()
        # Mock LLM to avoid real API calls
        agent._call_llm = AsyncMock(return_value="[]")
        return agent

    @pytest.mark.asyncio
    async def test_execute_with_jurisdiction(self, librarian, sample_jurisdiction, sample_plan_data):
        """Should return codes for CA jurisdiction."""
        state = {
            "jurisdiction": sample_jurisdiction,
            "plan_data": sample_plan_data,
        }
        result = await librarian.execute(state)

        assert "code_requirements" in result
        assert len(result["code_requirements"]) > 0
        assert "code_version" in result
        assert "California" in result["code_version"] or "IBC" in result["code_version"]

    @pytest.mark.asyncio
    async def test_execute_without_jurisdiction(self, librarian, sample_plan_data):
        """Should still return generic codes without jurisdiction."""
        state = {
            "jurisdiction": Jurisdiction(),
            "plan_data": sample_plan_data,
        }
        result = await librarian.execute(state)
        assert len(result["code_requirements"]) > 0


# ─── Integration Test ────────────────────────────────────────────────

class TestWorkflowIntegration:

    @pytest.mark.asyncio
    async def test_full_audit_pipeline(self, sample_jurisdiction, sample_plan_data):
        """Test the full Librarian → Auditor pipeline without LLM."""
        librarian = LibrarianAgent()
        librarian._call_llm = AsyncMock(return_value="[]")

        auditor = AuditorAgent()
        auditor._call_llm = AsyncMock(return_value="[]")

        state = {
            "jurisdiction": sample_jurisdiction,
            "plan_data": sample_plan_data,
        }

        # Run librarian
        lib_result = await librarian.execute(state)
        state.update(lib_result)

        assert len(state["code_requirements"]) > 0

        # Run auditor
        aud_result = await auditor.execute(state)
        report = aud_result["report"]

        assert report is not None
        assert len(report.findings) > 0
        assert report.summary.total_checks > 0
        assert 0.0 <= report.summary.compliance_score <= 1.0
        print(f"\nIntegration test: {report.summary.total_checks} checks, "
              f"score={report.summary.compliance_score:.0%}, "
              f"non_compliant={report.summary.non_compliant}")
