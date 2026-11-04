"""Job storage service."""
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel
from ...models.schemas import (
    ArchitectureAnalysisResult,
    JobResponse,
    ParsedRepository,
    RepoAnalysisResult,
    StageEnum,
    StageInfo,
    StatusEnum,
    VideoResult,
)

# Standard 9 pipeline stages
PIPELINE_STAGES = [
    StageEnum.REPO_FETCHING.value,
    StageEnum.REPO_ANALYSIS.value,
    StageEnum.CODE_UNDERSTANDING.value,
    StageEnum.AI_SUMMARY.value,
    StageEnum.SCRIPT_GENERATION.value,
    StageEnum.STORYBOARD_GENERATION.value,
    StageEnum.VISUAL_GENERATION.value,
    StageEnum.VOICE_GENERATION.value,
    StageEnum.VIDEO_ASSEMBLY.value,
]

class JobInternal(BaseModel):
    job_id: str
    repo_url: str
    repo_name: str
    repository_owner: str
    repository_name: str
    clone_url: str
    local_path: Optional[str] = None
    ingestion_status: StatusEnum = StatusEnum.PENDING
    status: StatusEnum = StatusEnum.PENDING
    current_stage: str
    progress_percentage: int
    stages: List[StageInfo]
    created_at: datetime
    updated_at: datetime
    analysis: Optional[RepoAnalysisResult] = None
    code_analysis: Optional[ParsedRepository] = None
    architecture: Optional[ArchitectureAnalysisResult] = None
    result: Optional[VideoResult] = None
    error: Optional[str] = None

    def to_response(self) -> JobResponse:
        """Converts internal job record to public JobResponse without leaking internal filesystem paths."""
        return JobResponse(
            job_id=self.job_id,
            repo_url=self.repo_url,
            repo_name=self.repo_name,
            repository_owner=self.repository_owner,
            repository_name=self.repository_name,
            clone_url=self.clone_url,
            ingestion_status=self.ingestion_status,
            status=self.status,
            current_stage=self.current_stage,
            progress_percentage=self.progress_percentage,
            stages=self.stages,
            created_at=self.created_at,
            updated_at=self.updated_at,
            analysis=self.analysis,
            code_analysis=self.code_analysis,
            architecture=self.architecture,
            result=self.result,
            error=self.error,
        )

class JobStore:
    def __init__(self):
        self._jobs: Dict[str, JobInternal] = {}

    def create_job(
        self,
        repo_url: str,
        repo_name: str,
        repository_owner: str,
        repository_name: str,
        clone_url: str,
    ) -> JobInternal:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        stages = [
            StageInfo(
                id=idx + 1,
                name=stage_name,
                status=StatusEnum.PENDING,
                detail=f"Queued for {stage_name}",
            )
            for idx, stage_name in enumerate(PIPELINE_STAGES)
        ]
        job = JobInternal(
            job_id=job_id,
            repo_url=repo_url,
            repo_name=repo_name,
            repository_owner=repository_owner,
            repository_name=repository_name,
            clone_url=clone_url,
            local_path=None,
            ingestion_status=StatusEnum.PENDING,
            status=StatusEnum.PENDING,
            current_stage=PIPELINE_STAGES[0],
            progress_percentage=0,
            stages=stages,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[JobResponse]:
        internal = self._jobs.get(job_id)
        if not internal:
            return None
        return internal.to_response()

    def get_internal_job(self, job_id: str) -> Optional[JobInternal]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[JobResponse]:
        sorted_internal = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_response() for j in sorted_internal]

    def update_job_ingestion_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.ingestion_status = StatusEnum.IN_PROGRESS
        job.status = StatusEnum.IN_PROGRESS
        job.current_stage = PIPELINE_STAGES[0]
        job.stages[0].status = StatusEnum.IN_PROGRESS
        job.stages[0].started_at = now
        job.stages[0].detail = "Cloning repository from GitHub..."
        job.updated_at = now
        return job

    def update_job_ingestion_success(
        self, job_id: str, local_path: str, file_count: int, size_mb: float
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.local_path = local_path
        job.ingestion_status = StatusEnum.COMPLETED
        job.stages[0].status = StatusEnum.COMPLETED
        job.stages[0].completed_at = now
        job.stages[0].detail = f"Cloned successfully ({file_count} files, {size_mb:.2f} MB)"
        job.progress_percentage = 11
        # Set next stage ready
        job.current_stage = PIPELINE_STAGES[1]
        job.stages[1].status = StatusEnum.PENDING
        job.stages[1].detail = "Ready for repository analysis"
        job.updated_at = now
        return job

    def update_job_ingestion_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.ingestion_status = StatusEnum.FAILED
        job.status = StatusEnum.FAILED
        job.stages[0].status = StatusEnum.FAILED
        job.stages[0].completed_at = now
        job.stages[0].detail = f"Cloning failed: {error_message}"
        job.error = error_message
        job.updated_at = now
        return job

    def update_job_analysis_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.current_stage = PIPELINE_STAGES[1]
        job.stages[1].status = StatusEnum.IN_PROGRESS
        job.stages[1].started_at = now
        job.stages[1].detail = "Analyzing repository structure, languages, and dependencies..."
        job.updated_at = now
        return job

    def update_job_analysis_success(
        self, job_id: str, analysis: RepoAnalysisResult
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.analysis = analysis
        job.stages[1].status = StatusEnum.COMPLETED
        job.stages[1].completed_at = now
        job.stages[1].detail = (
            f"Analyzed {analysis.statistics.source_files} source files across "
            f"{analysis.statistics.recognized_languages_count} languages"
        )
        job.progress_percentage = 22
        # Set next stage ready (Stage 3: Code Understanding)
        job.current_stage = PIPELINE_STAGES[2]
        job.stages[2].status = StatusEnum.PENDING
        job.stages[2].detail = "Ready for code understanding"
        job.updated_at = now
        return job

    def update_job_analysis_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[1].status = StatusEnum.FAILED
        job.stages[1].completed_at = now
        job.stages[1].detail = f"Analysis failed: {error_message}"
        # Keep cloned repo intact, mark error in warnings/detail
        job.updated_at = now
        return job

    def update_job_code_parsing_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.current_stage = PIPELINE_STAGES[2]
        job.stages[2].status = StatusEnum.IN_PROGRESS
        job.stages[2].started_at = now
        job.stages[2].detail = "Parsing source code with Tree-sitter AST..."
        job.updated_at = now
        return job

    def update_job_code_parsing_success(
        self, job_id: str, code_analysis: ParsedRepository
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.code_analysis = code_analysis
        job.stages[2].status = StatusEnum.COMPLETED
        job.stages[2].completed_at = now
        job.stages[2].detail = (
            f"Parsed {code_analysis.total_parsed_files} files "
            f"({code_analysis.total_functions} functions, "
            f"{code_analysis.total_classes} classes, "
            f"{code_analysis.total_methods} methods, "
            f"{code_analysis.total_imports} imports)"
        )
        job.progress_percentage = 33
        # Set next stage ready (Stage 4: AI Summary Generation)
        job.current_stage = PIPELINE_STAGES[3]
        job.stages[3].status = StatusEnum.PENDING
        job.stages[3].detail = "Ready for AI summary generation"
        job.updated_at = now
        return job

    def update_job_code_and_architecture_success(
        self,
        job_id: str,
        code_analysis: ParsedRepository,
        architecture: ArchitectureAnalysisResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.code_analysis = code_analysis
        job.architecture = architecture
        job.stages[2].status = StatusEnum.COMPLETED
        job.stages[2].completed_at = now
        job.stages[2].detail = (
            f"Parsed {code_analysis.total_parsed_files} files "
            f"({architecture.dependency_graph.total_internal_dependencies} internal dependencies, "
            f"{architecture.call_graph.total_resolved_calls} resolved calls, "
            f"{len(architecture.entry_points)} entry points)"
        )
        job.progress_percentage = 33
        # Set next stage ready (Stage 4: AI Summary Generation)
        job.current_stage = PIPELINE_STAGES[3]
        job.stages[3].status = StatusEnum.PENDING
        job.stages[3].detail = "Ready for AI summary generation"
        job.updated_at = now
        return job

    def update_job_code_parsing_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[2].status = StatusEnum.FAILED
        job.stages[2].completed_at = now
        job.stages[2].detail = f"Code parsing failed: {error_message}"
        job.updated_at = now
        return job

    def update_job(self, job: JobInternal) -> JobInternal:
        job.updated_at = datetime.now(timezone.utc)
        self._jobs[job.job_id] = job
        return job

job_store = JobStore()
