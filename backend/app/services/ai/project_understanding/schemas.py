from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..schemas import TokenUsageRecord


class EvidenceReference(BaseModel):
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    evidence_type: str = "code"  # "code", "readme", "manifest", "config", "import", "comment"
    confidence: str = "high"  # "high", "medium", "low"
    status: str = "confirmed"  # "confirmed", "inferred", "unknown", "unverified"
    detail: Optional[str] = None
    is_valid: bool = True
    path_verified: bool = False
    line_range_verified: bool = False


class ProjectIdentity(BaseModel):
    name: str
    short_description: str
    category: str
    project_type: str
    primary_purpose: str


class ProblemStatement(BaseModel):
    problem_addressed: str
    why_it_matters: str
    how_project_solves_it: str


class CoreFeatureItem(BaseModel):
    name: str
    description: str
    user_benefit: str
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)
    confidence: str = "high"


class TargetAudience(BaseModel):
    intended_users: List[str] = Field(default_factory=list)
    likely_needs: List[str] = Field(default_factory=list)
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)
    is_established: bool = True


class UseCaseItem(BaseModel):
    name: str
    description: str
    how_used: str
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)


class TechnologyExplanationItem(BaseModel):
    technology_name: str
    category: str
    role_in_project: str
    why_used: str
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)
    status: str = "confirmed"  # "confirmed", "inferred"


class ApplicationExplanation(BaseModel):
    concise_overview: str
    detailed_explanation: str
    beginner_friendly: str
    interesting_aspects: str
    video_demonstration_highlights: List[str] = Field(default_factory=list)


class ProjectUnderstanding(BaseModel):
    schema_version: str = "1.0"
    identity: ProjectIdentity
    problem_statement: ProblemStatement
    core_features: List[CoreFeatureItem] = Field(default_factory=list)
    target_audience: TargetAudience
    use_cases: List[UseCaseItem] = Field(default_factory=list)
    technology_stack: List[TechnologyExplanationItem] = Field(default_factory=list)
    overall_explanation: ApplicationExplanation
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""
    is_fallback: bool = False
    latency_ms: float = 0.0
    token_usage: Optional[TokenUsageRecord] = None
    validation_warnings: List[str] = Field(default_factory=list)
