from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class StageEnum(str, Enum):
    REPO_FETCHING = "Repository Fetching"
    REPO_ANALYSIS = "Repository Analysis"
    CODE_UNDERSTANDING = "Code Understanding"
    AI_SUMMARY = "AI Summary Generation"
    SCRIPT_GENERATION = "Script Generation"
    STORYBOARD_GENERATION = "Storyboard Generation"
    VISUAL_GENERATION = "Visual Generation"
    VOICE_GENERATION = "Voice Generation"
    VIDEO_ASSEMBLY = "Video Assembly"

class StatusEnum(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class StageInfo(BaseModel):
    id: int
    name: str
    status: StatusEnum = StatusEnum.PENDING
    detail: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str
    version: str
    environment: str
    timestamp: datetime

class JobCreateRequest(BaseModel):
    github_url: str = Field(..., description="Public GitHub repository URL (e.g. https://github.com/owner/repo)")

class VideoResult(BaseModel):
    repo_name: str
    repo_url: str
    description: str
    tech_stack: List[str]
    summary: str
    video_url: Optional[str] = None
    duration_seconds: Optional[int] = None

class JobResponse(BaseModel):
    job_id: str
    repo_url: str
    repo_name: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    clone_url: Optional[str] = None
    ingestion_status: StatusEnum = StatusEnum.PENDING
    status: StatusEnum
    current_stage: str
    progress_percentage: int
    stages: List[StageInfo]
    created_at: datetime
    updated_at: datetime
    result: Optional[VideoResult] = None
    error: Optional[str] = None
