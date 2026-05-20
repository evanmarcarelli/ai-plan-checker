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
    # ---- RAG provenance (new) ----
    # verified=True means the cited section was retrieved from the real code corpus,
    # not invented by the LLM. source_text is the verbatim code language.
    verified: bool = False
    source_text: Optional[str] = None
    source_citation: Optional[str] = None  # canonical e.g. "ADA 404.2.3"


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
