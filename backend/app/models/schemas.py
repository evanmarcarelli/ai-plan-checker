from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ==================== Enums ====================

class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"
    NOT_APPLICABLE = "not_applicable"


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanType(str, Enum):
    COMMERCIAL = "commercial"
    RESIDENTIAL = "residential"
    INDUSTRIAL = "industrial"
    MIXED_USE = "mixed_use"
    UNKNOWN = "unknown"


# ==================== Auth Schemas ====================

class UserCreate(BaseModel):
    email: str
    password: str
    name: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    is_admin: bool
    created_at: Optional[str] = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class TokenRefresh(BaseModel):
    refresh_token: str


# ==================== Jurisdiction ====================

class Jurisdiction(BaseModel):
    city: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    country: str = "USA"
    governing_authority: Optional[str] = None
    seismic_zone: Optional[str] = None
    wind_zone: Optional[str] = None
    flood_zone: Optional[str] = None
    snow_load_zone: Optional[str] = None
    confidence: float = 0.0


# ==================== Plan Data ====================

class PlanElement(BaseModel):
    element_type: str
    description: str
    value: Optional[float] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    page_number: Optional[int] = None
    raw_text: Optional[str] = None


# ---- Geometry extraction (feature-flagged; populated by geometry_extractor) ----
# Net-new geometry pulled from the drawing vector layer, distinct from the
# text-label dimensions the surveyor has always parsed. Whole tree auto-persists
# into jobs.plan_data JSONB via model_dump() — no migration needed.

class SheetScale(BaseModel):
    """Calibrated drawing scale for one sheet. points_per_foot converts a drawn
    length in PDF points to real-world feet (PDF point = 1/72 inch)."""
    page: int
    scale_text: Optional[str] = None        # e.g. "1/4\"=1'-0\""
    points_per_foot: Optional[float] = None
    source: Optional[str] = None            # "note" | "bar" | "empirical" | "reconciled"
    confidence: float = 0.0


class PageGeometry(BaseModel):
    page: int
    # Router verdict: how this page should be (was) measured.
    path: str = "vector_layered"            # vector_layered | vector_unlayered | raster
    vector_coverage: float = 0.0            # rough 0..1 share of drawn vs scanned content
    primitive_counts: Dict[str, int] = {}   # by primitive type and/or layer role
    scale: Optional[SheetScale] = None
    # Measured outputs that CAN drive checks; each value carries a confidence flag
    # consumed by the Hybrid gate (see geometry_extractor / engine).
    measured_features: Dict[str, Any] = {}  # corridor_widths, door_widths, ...
    advisory: Dict[str, Any] = {}           # research-grade outputs, never a hard finding


class GeometryData(BaseModel):
    enabled: bool = True
    pages: List[PageGeometry] = []
    dominant_scale: Optional[SheetScale] = None
    layers: List[str] = []                   # OCG layer names found in the document
    stats: Dict[str, Any] = {}               # coverage, timings, self-consistency score


class ExtractedPlanData(BaseModel):
    project_name: Optional[str] = None
    project_address: Optional[str] = None
    plan_type: PlanType = PlanType.UNKNOWN
    architect: Optional[str] = None
    engineer: Optional[str] = None
    date: Optional[str] = None
    scale: Optional[str] = None
    elements: List[PlanElement] = []
    dimensions: Dict[str, Any] = {}
    materials: List[str] = []
    occupancy_type: Optional[str] = None
    construction_type: Optional[str] = None
    building_height: Optional[float] = None
    building_area: Optional[float] = None
    stories: Optional[int] = None
    raw_text_by_page: Dict[int, str] = {}
    title_block_text: Optional[str] = None
    # ---- Optional scalars consumed by the deterministic rule engine ----
    # The Surveyor may or may not populate these yet; checkers degrade to
    # "needs review / not applicable" when they are None, exactly like the
    # plan-room engine. Present so the deterministic numeric checks
    # (exits, capacity, fixtures, story sprinkler-adjust) can activate as
    # extraction improves.
    occupant_load: Optional[int] = None
    sprinklered: Optional[bool] = None
    per_story_area: Optional[float] = None
    declared_exits: Optional[int] = None
    declared_door_width_in: Optional[float] = None
    declared_stair_width_in: Optional[float] = None
    # Stair configuration ("standard" for a straight-run stair; otherwise
    # "spiral" / "winder" / "alternating_tread"). Disambiguates the
    # deterministic stair-geometry rules: a declared "standard" stair closes
    # the spiral/winder/alternating-tread exception, so a sub-limit tread /
    # riser / guard / handrail asserts a HARD fail instead of needs_review
    # (engine._hard_trigger_met). None falls SOFT, never silently hardens.
    stair_type: Optional[str] = None
    actual_wc: Optional[int] = None
    actual_lav: Optional[int] = None
    state_code: Optional[str] = None
    # CalFire FHSZ overlay tier ("high" / "very_high"), address-derived.
    wui_zone: Optional[str] = None
    # ---- Plan-library provenance (migration 010) ----
    # SHA256 of the uploaded PDF. Persisted with the job so duplicate uploads
    # and revisions of the same plan set are detectable across jobs.
    file_hash: Optional[str] = None
    # Total pages in the PDF (raw_text_by_page is capped, this is not).
    page_count: Optional[int] = None
    # Per-page sheet identification (sheet_number, discipline, sheet_title,
    # source, confidence) built by app.services.sheet_index. Empty when no
    # sheets could be identified.
    sheet_index: List[Dict[str, Any]] = []
    # Extraction audit trail: textract stats, vision status, sheet-index
    # coverage. Persisted in plan_data JSONB so "why was this check hollow?"
    # is answerable after the fact.
    extraction_stats: Dict[str, Any] = {}
    # Net-new geometry pulled from the drawing vector layer (feature-flagged).
    # None when geometry extraction is disabled or the document yielded nothing.
    geometry: Optional[GeometryData] = None


# ==================== Code Requirements ====================

class CodeRequirement(BaseModel):
    code_id: str = ""
    code_name: str = ""
    section: str = ""
    description: str = ""
    category: str = "general"
    requirement_type: str = "general"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: Optional[str] = None
    jurisdiction_specific: bool = False
    full_text: Optional[str] = None
    source: str = "mock_database"
    # Most-specific corpus jurisdiction tag this requirement came from
    # ("*" = base, "CA" = state, "CA:Los Angeles" = city). Set by the adapter
    # from the chunk's jurisdictions; read by the precedence resolver to decide
    # which layer governs. None until populated.
    layer_key: Optional[str] = None


# ==================== Compliance Finding ====================

class ComplianceFinding(BaseModel):
    finding_id: str = ""
    code_requirement: CodeRequirement
    status: ComplianceStatus
    plan_value: Optional[str] = None
    required_value: Optional[str] = None
    description: str = ""
    recommendation: Optional[str] = None
    severity: str = "medium"  # low, medium, high, critical
    page_references: List[int] = []
    category: str = "general"
    # Reviewer's self-reported certainty 0..1. Low-confidence NON_COMPLIANT
    # assertions are downgraded to NEEDS_REVIEW by the confidence gate so an
    # uncertain reviewer never hard-blocks a permit. Default 1.0 = no gating
    # when a reviewer (or the deterministic engine) doesn't report confidence.
    confidence: float = 1.0
    # ---- RAG provenance (new) ----
    # verified=True means the cited section was retrieved from the real code corpus,
    # not invented by the LLM. source_text is the verbatim code language.
    verified: bool = False
    source_text: Optional[str] = None
    source_citation: Optional[str] = None  # canonical e.g. "ADA 404.2.3"
    # ---- precedence provenance (which law governs + why) ----
    # Stamped by the precedence resolver: the jurisdiction layer that governs
    # this requirement's topic ("CA:Los Angeles"), the basis for that call
    # ("more_restrictive" | "local_replaces" | "state_preempts_local" |
    # "overlay_stacks" | "ada_independent" | "single_layer"), a human rationale,
    # and the layers that were superseded. All optional so legacy callers and
    # serialization are unaffected.
    governing_layer: Optional[str] = None
    governing_basis: Optional[str] = None
    governing_rationale: Optional[str] = None
    superseded_layers: List[str] = []


# ==================== Compliance Report ====================

class ComplianceSummary(BaseModel):
    total_checks: int = 0
    compliant: int = 0
    non_compliant: int = 0
    needs_review: int = 0
    not_applicable: int = 0
    compliance_score: float = 0.0
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0


class DepartmentReview(BaseModel):
    department: str
    department_code: str  # short id e.g. "building_safety", "fire"
    icon: str = ""
    summary: ComplianceSummary = ComplianceSummary()
    findings: List[ComplianceFinding] = []
    notes: Optional[str] = None
    submittal_required: bool = True
    review_status: str = "pending"  # pending|cleared|conditional|rejected


class ComplianceReport(BaseModel):
    report_id: str = ""
    job_id: str = ""
    generated_at: Optional[datetime] = None
    jurisdiction: Optional[Jurisdiction] = None
    plan_data: Optional[ExtractedPlanData] = None
    findings: List[ComplianceFinding] = []
    department_reviews: List[DepartmentReview] = []
    summary: ComplianceSummary = ComplianceSummary()
    recommendations: List[str] = []
    code_versions: Dict[str, str] = {}
    sources_used: List[str] = []
    auditor_notes: Optional[str] = None


# ==================== Agent Log ====================

class AgentLog(BaseModel):
    timestamp: datetime
    agent: str
    level: str = "info"
    message: str
    data: Optional[Dict[str, Any]] = None


# ==================== Job ====================

class ProcessingJob(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    filename: str
    file_size: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    progress: int = 0
    current_agent: Optional[str] = None
    agents_completed: List[str] = []
    report: Optional[ComplianceReport] = None
    logs: List[AgentLog] = []


# ==================== WebSocket Messages ====================

class WSMessage(BaseModel):
    type: str
    job_id: str
    data: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ==================== API Request/Response ====================

class UploadResponse(BaseModel):
    job_id: str
    message: str
    filename: str
    file_size: int


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    current_agent: Optional[str]
    agents_completed: List[str]
    error: Optional[str]
    report: Optional[ComplianceReport]
    logs: List[AgentLog]
