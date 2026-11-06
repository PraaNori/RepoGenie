"""Job storage service."""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel
from ...models.schemas import (
    ArchitectureAnalysisResult,
    JobResponse,
    ParsedRepository,
    RepoAnalysisResult,
    RepositoryKnowledge,
    StageEnum,
    StageInfo,
    StatusEnum,
    VideoResult,
)
from ..ai.project_understanding.schemas import ProjectUnderstanding
from ..ai.code_understanding.schemas import RepositoryCodeUnderstanding
from ..ai.workflow_understanding.schemas import RepositoryWorkflowUnderstanding
from ..ai.script_generation.schemas import EducationalScript
from ..ai.storyboard_generation.schemas import EducationalStoryboard
from ..video.visual_generation.schemas import VisualGenerationResult, VisualGenerationStatus
from ..video.visual_generation.storage import visual_storage_manager
from ..video.narration.schemas import NarrationAssetStatus, NarrationGenerationResult
from ..video.narration.audio_storage import audio_storage_manager
from ..video.captions.schemas import CaptionGenerationResult, CaptionStatus
from ..video.captions.caption_storage import caption_storage_manager

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
    knowledge: Optional[RepositoryKnowledge] = None
    project_understanding: Optional[ProjectUnderstanding] = None
    code_understanding: Optional[RepositoryCodeUnderstanding] = None
    workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None
    educational_script: Optional[EducationalScript] = None
    educational_storyboard: Optional[EducationalStoryboard] = None
    visual_generation: Optional[VisualGenerationResult] = None
    narration: Optional[NarrationGenerationResult] = None
    captions: Optional[CaptionGenerationResult] = None
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
            knowledge=self.knowledge,
            project_understanding=self.project_understanding,
            has_code_understanding=bool(self.code_understanding is not None),
            has_workflow_understanding=bool(self.workflow_understanding is not None),
            has_educational_script=bool(self.educational_script is not None),
            has_educational_storyboard=bool(self.educational_storyboard is not None),
            has_visual_assets=bool(self.visual_generation is not None),
            has_narration=bool(self.narration is not None),
            has_captions=bool(self.captions is not None),
            educational_script=self.educational_script,
            educational_storyboard=self.educational_storyboard,
            visual_generation=self.visual_generation,
            narration=self.narration,
            captions=self.captions,
            result=self.result,
            error=self.error,
        )

class JobStore:
    def __init__(self):
        self._jobs: Dict[str, JobInternal] = {}
        self._job_locks: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def get_job_lock(self, job_id: str) -> asyncio.Lock:
        """
        Returns a dedicated asyncio.Lock for the specified job_id to ensure
        per-job atomicity without blocking requests for other jobs.
        """
        async with self._meta_lock:
            if job_id not in self._job_locks:
                self._job_locks[job_id] = asyncio.Lock()
            return self._job_locks[job_id]

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

    def update_job_knowledge_success(
        self,
        job_id: str,
        code_analysis: ParsedRepository,
        architecture: ArchitectureAnalysisResult,
        knowledge: RepositoryKnowledge,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.code_analysis = code_analysis
        job.architecture = architecture
        job.knowledge = knowledge
        job.stages[2].status = StatusEnum.COMPLETED
        job.stages[2].completed_at = now
        job.stages[2].detail = (
            f"Consolidated knowledge ({code_analysis.total_parsed_files} files, "
            f"{architecture.dependency_graph.total_internal_dependencies} internal deps, "
            f"{len(knowledge.important_files)} important files, "
            f"{len(knowledge.technology_stack.frameworks)} frameworks)"
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

    def update_job_ai_summary_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[3].status = StatusEnum.IN_PROGRESS
        job.stages[3].started_at = now
        job.stages[3].detail = "Generating AI-powered project understanding"
        job.current_stage = PIPELINE_STAGES[3]
        job.progress_percentage = 38
        job.updated_at = now
        return job

    def update_job_ai_summary_success(
        self,
        job_id: str,
        understanding: ProjectUnderstanding,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.project_understanding = understanding
        job.stages[3].status = StatusEnum.COMPLETED
        job.stages[3].completed_at = now
        job.stages[3].detail = (
            f"Generated project understanding ({len(understanding.core_features)} features, "
            f"{understanding.provider}/{understanding.model})"
        )
        job.progress_percentage = 44
        # Set next stage ready (Stage 5: Script Generation)
        job.current_stage = PIPELINE_STAGES[4]
        job.stages[4].status = StatusEnum.PENDING
        job.stages[4].detail = "Ready for educational script generation"
        job.updated_at = now
        return job

    def update_job_code_understanding_success(
        self,
        job_id: str,
        code_understanding: RepositoryCodeUnderstanding,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.code_understanding = code_understanding
        job.updated_at = now
        return job

    def update_job_workflow_understanding_success(
        self,
        job_id: str,
        workflow_understanding: RepositoryWorkflowUnderstanding,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.workflow_understanding = workflow_understanding
        job.updated_at = now
        return job

    def get_job_workflow_understanding(
        self,
        job_id: str,
    ) -> Optional[RepositoryWorkflowUnderstanding]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.workflow_understanding

    def update_job_ai_summary_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[3].status = StatusEnum.FAILED
        job.stages[3].completed_at = now
        job.stages[3].detail = f"AI summary generation failed: {error_message}"
        job.updated_at = now
        return job

    def update_job_educational_script_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[4].status = StatusEnum.IN_PROGRESS
        job.stages[4].started_at = now
        job.stages[4].detail = "Generating educational video narration script..."
        job.current_stage = PIPELINE_STAGES[4]
        job.progress_percentage = 48
        job.updated_at = now
        return job

    def update_job_educational_script_success(
        self,
        job_id: str,
        script: EducationalScript,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.educational_script = script
        job.stages[4].status = StatusEnum.COMPLETED
        job.stages[4].completed_at = now
        job.stages[4].detail = (
            f"Generated educational script ({len(script.sections)} sections, "
            f"{script.total_estimated_duration_seconds}s)"
        )
        job.progress_percentage = 55

        # If a previous storyboard exists, invalidate it because the script changed
        was_invalidated = False
        if job.educational_storyboard is not None:
            job.educational_storyboard = None
            if job.stages[5].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS):
                job.stages[5].status = StatusEnum.PENDING
                job.stages[5].started_at = None
                job.stages[5].completed_at = None
                job.stages[5].detail = "Ready for educational storyboard generation (script was regenerated)"
                was_invalidated = True

        # If previous visual assets exist, invalidate them because script/storyboard changed
        if job.visual_generation is not None:
            job.visual_generation = None
            try:
                visual_storage_manager.delete_job_visuals(job_id)
            except Exception as e:
                logger.warning("Failed to clean visual storage for job %s: %s", job_id, e)
            if job.stages[6].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS):
                job.stages[6].status = StatusEnum.PENDING
                job.stages[6].started_at = None
                job.stages[6].completed_at = None
                job.stages[6].detail = "Ready for visual generation (script was regenerated)"

        # Invalidate downstream narration assets as well
        if job.narration is not None:
            job.narration = None
            try:
                audio_storage_manager.delete_job_audio(job_id)
            except Exception as e:
                logger.warning("Failed to clean audio storage for job %s: %s", job_id, e)
            if job.stages[7].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS, StatusEnum.FAILED):
                job.stages[7].status = StatusEnum.PENDING
                job.stages[7].started_at = None
                job.stages[7].completed_at = None
                job.stages[7].detail = "Ready for voice generation (script was regenerated)"

        # Set next stage ready (Stage 6: Storyboard Generation)
        job.current_stage = PIPELINE_STAGES[5]
        if job.stages[5].status == StatusEnum.PENDING and not was_invalidated:
            job.stages[5].detail = "Ready for educational storyboard generation"
        job.updated_at = now
        return job

    def update_job_educational_script_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[4].status = StatusEnum.FAILED
        job.stages[4].completed_at = now
        job.stages[4].detail = f"Educational script generation failed: {error_message}"
        job.updated_at = now
        return job

    def get_job_educational_script(self, job_id: str) -> Optional[EducationalScript]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.educational_script

    def invalidate_job_educational_script(self, job_id: str) -> Optional[JobInternal]:
        """Invalidates educational script and cascades invalidation to storyboard and visual assets."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.educational_script = None
        if job.stages[4].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS):
            job.stages[4].status = StatusEnum.PENDING
            job.stages[4].started_at = None
            job.stages[4].completed_at = None
            job.stages[4].detail = "Ready for educational script generation"

        # Cascades to storyboard and visual assets
        self.invalidate_job_educational_storyboard(job_id)
        job.updated_at = now
        return job

    def update_job_educational_storyboard_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[5].status = StatusEnum.IN_PROGRESS
        job.stages[5].started_at = now
        job.stages[5].detail = "Generating educational storyboard scenes..."
        job.current_stage = PIPELINE_STAGES[5]
        job.progress_percentage = 60
        job.updated_at = now
        return job

    def update_job_educational_storyboard_success(
        self,
        job_id: str,
        storyboard: EducationalStoryboard,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.educational_storyboard = storyboard
        job.stages[5].status = StatusEnum.COMPLETED
        job.stages[5].completed_at = now
        job.stages[5].detail = (
            f"Generated educational storyboard ({len(storyboard.scenes)} scenes, "
            f"{storyboard.total_estimated_duration_seconds}s)"
        )
        job.progress_percentage = 66

        # Invalidate downstream visual assets when storyboard is newly generated or replaced
        was_visual_invalidated = False
        if job.visual_generation is not None:
            job.visual_generation = None
            try:
                visual_storage_manager.delete_job_visuals(job_id)
            except Exception as e:
                logger.warning("Failed to clean visual storage for job %s: %s", job_id, e)
            if job.stages[6].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS):
                job.stages[6].status = StatusEnum.PENDING
                job.stages[6].started_at = None
                job.stages[6].completed_at = None
                job.stages[6].detail = "Ready for visual generation (storyboard was regenerated)"
                was_visual_invalidated = True

        # Invalidate downstream narration assets as well
        if job.narration is not None:
            job.narration = None
            try:
                audio_storage_manager.delete_job_audio(job_id)
            except Exception as e:
                logger.warning("Failed to clean audio storage for job %s: %s", job_id, e)
            if job.stages[7].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS, StatusEnum.FAILED):
                job.stages[7].status = StatusEnum.PENDING
                job.stages[7].started_at = None
                job.stages[7].completed_at = None
                job.stages[7].detail = "Ready for voice generation (storyboard was regenerated)"

        # Invalidate downstream caption assets
        self.invalidate_job_captions(job_id)

        # Set next stage ready (Stage 7: Visual Generation)
        job.current_stage = PIPELINE_STAGES[6]
        if job.stages[6].status == StatusEnum.PENDING and not was_visual_invalidated:
            job.stages[6].detail = "Ready for visual generation"
        job.updated_at = now
        return job

    def update_job_educational_storyboard_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[5].status = StatusEnum.FAILED
        job.stages[5].completed_at = now
        job.stages[5].detail = f"Educational storyboard generation failed: {error_message}"
        job.updated_at = now
        return job

    def get_job_educational_storyboard(self, job_id: str) -> Optional[EducationalStoryboard]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.educational_storyboard

    def invalidate_job_educational_storyboard(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.educational_storyboard = None
        if job.stages[5].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS):
            job.stages[5].status = StatusEnum.PENDING
            job.stages[5].started_at = None
            job.stages[5].completed_at = None
            job.stages[5].detail = "Ready for educational storyboard generation (script was regenerated)"

        # Invalidate visual assets as well
        if job.visual_generation is not None:
            job.visual_generation = None
            try:
                visual_storage_manager.delete_job_visuals(job_id)
            except Exception as e:
                logger.warning("Failed to clean visual storage for job %s: %s", job_id, e)
            if job.stages[6].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS):
                job.stages[6].status = StatusEnum.PENDING
                job.stages[6].started_at = None
                job.stages[6].completed_at = None
                job.stages[6].detail = "Ready for visual generation (storyboard was invalidated)"

        # Invalidate narration assets as well
        if job.narration is not None:
            job.narration = None
            try:
                audio_storage_manager.delete_job_audio(job_id)
            except Exception as e:
                logger.warning("Failed to clean audio storage for job %s: %s", job_id, e)
            if job.stages[7].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS, StatusEnum.FAILED):
                job.stages[7].status = StatusEnum.PENDING
                job.stages[7].started_at = None
                job.stages[7].completed_at = None
                job.stages[7].detail = "Ready for voice generation (storyboard was invalidated)"

        # Invalidate downstream caption assets
        self.invalidate_job_captions(job_id)

        job.updated_at = now
        return job

    def update_job_visual_planning_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[6].status = StatusEnum.IN_PROGRESS
        job.stages[6].started_at = now
        job.stages[6].detail = "Planning visual asset specifications..."
        job.current_stage = PIPELINE_STAGES[6]
        job.progress_percentage = 68
        job.updated_at = now
        return job

    def update_job_visual_planning_success(
        self,
        job_id: str,
        plan: VisualGenerationResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.visual_generation = plan
        # Stage 07 remains IN_PROGRESS: visual planning is NOT visual rendering.
        # It must NOT be marked COMPLETED and must NOT advance to Stage 08.
        job.stages[6].status = StatusEnum.IN_PROGRESS
        job.stages[6].completed_at = None
        job.stages[6].detail = (
            f"Visual asset plan initialized ({len(plan.scene_assets)} scenes, "
            f"{plan.total_assets} assets pending rendering)"
        )
        job.current_stage = PIPELINE_STAGES[6]
        job.progress_percentage = 70
        job.updated_at = now
        return job

    def update_job_visual_generation_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[6].status = StatusEnum.IN_PROGRESS
        job.stages[6].started_at = now
        job.stages[6].detail = "Rendering visual assets..."
        job.current_stage = PIPELINE_STAGES[6]
        job.progress_percentage = 71
        job.updated_at = now
        return job

    def update_job_visual_generation_success(
        self,
        job_id: str,
        result: VisualGenerationResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None

        # Guard: Verify that all assets are genuinely rendered and completed
        if result.status != VisualGenerationStatus.COMPLETED:
            raise ValueError(
                f"Cannot mark visual generation as completed: result status is '{result.status.value}', expected 'completed'."
            )
        if result.scenes_completed != result.total_scenes or result.total_scenes == 0:
            raise ValueError(
                f"Cannot mark visual generation as completed: only {result.scenes_completed}/{result.total_scenes} scenes completed."
            )
        if result.scenes_failed > 0:
            raise ValueError(
                f"Cannot mark visual generation as completed: {result.scenes_failed} scenes failed."
            )
        if result.assets_completed != result.total_assets or result.total_assets == 0:
            raise ValueError(
                f"Cannot mark visual generation as completed: only {result.assets_completed}/{result.total_assets} assets rendered."
            )
        if result.assets_pending > 0 or result.assets_generating > 0 or result.assets_failed > 0:
            raise ValueError(
                f"Cannot mark visual generation as completed: {result.assets_pending} assets pending, {result.assets_generating} generating, {result.assets_failed} failed."
            )

        now = datetime.now(timezone.utc)
        job.visual_generation = result
        job.stages[6].status = StatusEnum.COMPLETED
        job.stages[6].completed_at = now
        job.stages[6].detail = (
            f"Rendered all visual assets ({result.scenes_completed} scenes, "
            f"{result.assets_completed} assets completed)"
        )
        job.progress_percentage = 75
        # Set next stage ready (Stage 8: Voice Generation)
        job.current_stage = PIPELINE_STAGES[7]
        if job.stages[7].status == StatusEnum.PENDING:
            job.stages[7].detail = "Ready for voice generation"
        job.updated_at = now
        return job

    def update_job_visual_generation_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[6].status = StatusEnum.FAILED
        job.stages[6].completed_at = now
        job.stages[6].detail = f"Visual generation failed: {error_message}"
        job.current_stage = PIPELINE_STAGES[6]
        if job.visual_generation:
            job.visual_generation.status = VisualGenerationStatus.FAILED
            job.visual_generation.error_message = error_message
        job.updated_at = now
        return job

    def get_job_visual_generation(self, job_id: str) -> Optional[VisualGenerationResult]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.visual_generation

    def invalidate_job_visual_generation(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.visual_generation = None
        try:
            visual_storage_manager.delete_job_visuals(job_id)
        except Exception as e:
            logger.warning("Failed to clean visual storage for job %s: %s", job_id, e)
        if job.stages[6].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS, StatusEnum.FAILED):
            job.stages[6].status = StatusEnum.PENDING
            job.stages[6].started_at = None
            job.stages[6].completed_at = None
            job.stages[6].detail = "Ready for visual generation (reset)"
        job.current_stage = PIPELINE_STAGES[6]
        job.updated_at = now
        return job

    def update_job_narration_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[7].status = StatusEnum.IN_PROGRESS
        job.stages[7].started_at = now
        job.stages[7].detail = "Synthesizing scene narration audio with ElevenLabs..."
        job.current_stage = PIPELINE_STAGES[7]
        job.progress_percentage = 78
        job.updated_at = now
        return job

    def update_job_narration_success(
        self,
        job_id: str,
        result: NarrationGenerationResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None

        # Guard: Verify that all assets are completed or explicitly skipped
        if result.status != NarrationAssetStatus.COMPLETED:
            raise ValueError(
                f"Cannot mark narration generation as completed: result status is '{result.status.value}', expected 'completed'."
            )
        if (result.assets_completed + result.assets_skipped) != result.total_assets or result.total_assets == 0:
            raise ValueError(
                f"Cannot mark narration generation as completed: only {result.assets_completed + result.assets_skipped}/{result.total_assets} assets generated or skipped."
            )
        if result.assets_failed > 0:
            raise ValueError(
                f"Cannot mark narration generation as completed: {result.assets_failed} assets failed."
            )
        if result.assets_pending > 0 or result.assets_generating > 0:
            raise ValueError(
                f"Cannot mark narration generation as completed: {result.assets_pending} assets pending, {result.assets_generating} generating."
            )

        now = datetime.now(timezone.utc)
        job.narration = result
        job.stages[7].status = StatusEnum.COMPLETED
        job.stages[7].completed_at = now
        job.stages[7].detail = (
            f"Generated narration audio ({result.scenes_completed} scenes synthesized, "
            f"{result.scenes_skipped} skipped)"
        )
        job.progress_percentage = 85
        # Set next stage ready (Stage 9: Video Assembly)
        job.current_stage = PIPELINE_STAGES[8]
        if job.stages[8].status == StatusEnum.PENDING:
            job.stages[8].detail = "Ready for video assembly"
        
        # Invalidate dependent captions when narration is newly generated or replaced
        self.invalidate_job_captions(job_id)

        job.updated_at = now
        return job

    def update_job_narration_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[7].status = StatusEnum.FAILED
        job.stages[7].completed_at = now
        job.stages[7].detail = f"Voice generation failed: {error_message}"
        job.current_stage = PIPELINE_STAGES[7]
        if job.narration:
            job.narration.status = NarrationAssetStatus.FAILED
            job.narration.error_message = error_message
        job.updated_at = now
        return job

    def get_job_narration(self, job_id: str) -> Optional[NarrationGenerationResult]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.narration

    def invalidate_job_narration(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.narration = None
        try:
            audio_storage_manager.delete_job_audio(job_id)
        except Exception as e:
            logger.warning("Failed to clean audio storage for job %s: %s", job_id, e)
        if job.stages[7].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS, StatusEnum.FAILED):
            job.stages[7].status = StatusEnum.PENDING
            job.stages[7].started_at = None
            job.stages[7].completed_at = None
            job.stages[7].detail = "Ready for voice generation (reset)"
        job.current_stage = PIPELINE_STAGES[7]

        # Invalidate dependent captions as well
        self.invalidate_job_captions(job_id)

        job.updated_at = now
        return job

    def update_job_captions_started(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        if job.captions:
            job.captions.status = CaptionStatus.GENERATING
        job.updated_at = now
        return job

    def update_job_captions_success(
        self,
        job_id: str,
        result: CaptionGenerationResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.captions = result
        job.updated_at = now
        return job

    def update_job_captions_failed(self, job_id: str, error_message: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        if job.captions:
            job.captions.status = CaptionStatus.FAILED
            job.captions.error_message = error_message
        job.updated_at = now
        return job

    def get_job_captions(self, job_id: str) -> Optional[CaptionGenerationResult]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.captions

    def invalidate_job_captions(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.captions = None
        try:
            caption_storage_manager.delete_job_captions(job_id)
        except Exception as e:
            logger.warning("Failed to clean caption storage for job %s: %s", job_id, e)
        job.updated_at = now
        return job

    def update_job(self, job: JobInternal) -> JobInternal:
        job.updated_at = datetime.now(timezone.utc)
        self._jobs[job.job_id] = job
        return job

job_store = JobStore()
