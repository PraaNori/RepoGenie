"""Job storage service."""
import asyncio
import functools
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel
from ...core.config import settings
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
from ..video.assembly_input.schemas import VideoAssemblyInput
from ..video.assembly.schemas import (
    SceneRenderProgress,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderProgress,
    VideoRenderResult,
    VideoRenderStatus,
)
from ..video.assembly.storage import video_storage_manager

try:
    JobResponse.model_rebuild()
except Exception:
    pass

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
    assembly_input: Optional[VideoAssemblyInput] = None
    render_config: Optional[VideoRenderConfiguration] = None
    render_job: Optional[VideoRenderJob] = None
    scene_renders: Optional[SceneRenderResult] = None
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
            has_assembly_input=bool(self.assembly_input is not None),
            has_video_render=bool(self.render_job is not None),
            has_scene_renders=bool(self.scene_renders is not None and len(self.scene_renders.scenes) > 0),
            educational_script=self.educational_script,
            educational_storyboard=self.educational_storyboard,
            visual_generation=self.visual_generation,
            narration=self.narration,
            captions=self.captions,
            assembly_input=self.assembly_input,
            render_config=self.render_config,
            render_job=self.render_job,
            scene_renders=self.scene_renders,
            result=self.result,
            error=self.error,
        )

logger = logging.getLogger(__name__)

class JobStore:
    """
    Durable Job Storage Service for RepoGenie.

    Architecture & Concurrency Model:
    - Designed for single-process async concurrency with dedicated per-job locks
      (`get_job_lock`) that serialize operations on each job without blocking others.
    - Employs POSIX-atomic file replacement (`tmp_file.replace(state_file)`) ensuring
      readers always observe consistent, uncorrupted on-disk snapshots.
    - Uses file modification timestamps (`st_mtime`) to detect on-disk updates and
      invalidate in-memory caches.
    - Note: Distributed multi-process writers (e.g. multi-worker Uvicorn clusters)
      require external distributed locks (such as Redis/etcd) to coordinate state
      transitions across separate operating system processes.
    """

    def __init__(self):
        self._jobs: Dict[str, JobInternal] = {}
        self._job_mtimes: Dict[str, float] = {}
        self._job_locks: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()
        self._storage_jobs_dir = Path(settings.VIDEO_OUTPUT_DIR).resolve()
        self._storage_jobs_dir.mkdir(parents=True, exist_ok=True)
        self._load_all_jobs_from_disk()
        self._wrap_update_methods()

    def _persist_job(self, job: JobInternal) -> None:
        """
        Atomically persists JobInternal state to storage/jobs/<job_id>/job_state.json.
        Guarantees atomic replacement via temporary file swap and cleans up temporary files
        on any failure.
        """
        job_dir = self._storage_jobs_dir / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        state_file = job_dir / "job_state.json"
        tmp_file = job_dir / f"job_state_{uuid.uuid4().hex[:8]}.tmp"
        try:
            payload = job.model_dump_json(indent=2)
            tmp_file.write_text(payload, encoding="utf-8")
            tmp_file.replace(state_file)
            try:
                self._job_mtimes[job.job_id] = state_file.stat().st_mtime
            except OSError:
                pass
        except Exception as e:
            logger.error("Failed to persist job %s state to disk: %s", job.job_id, e, exc_info=True)
            raise RuntimeError(f"Failed to persist job '{job.job_id}' state to disk: {e}") from e
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

    def _load_job_from_disk(self, job_id: str) -> Optional[JobInternal]:
        """Loads JobInternal from storage/jobs/<job_id>/job_state.json or orphaned repo directory."""
        state_file = self._storage_jobs_dir / job_id / "job_state.json"
        if state_file.is_file():
            try:
                content = state_file.read_text(encoding="utf-8")
                job = JobInternal.model_validate_json(content)
                self._jobs[job_id] = job
                try:
                    self._job_mtimes[job_id] = state_file.stat().st_mtime
                except OSError:
                    pass
                return job
            except Exception as e:
                logger.error("Failed loading job state from disk for %s: %s", job_id, e)

        # Legacy / orphaned fallback: If cloned repository directory exists in storage/repos/<job_id>
        try:
            repo_dir = settings.repos_path / job_id
            if repo_dir.is_dir() and (repo_dir / ".git").is_dir():
                return self._recover_orphaned_repo_job(job_id, repo_dir)
        except Exception as e:
            logger.warning("Failed to recover orphaned repo for %s: %s", job_id, e)

        return None

    def _recover_orphaned_repo_job(self, job_id: str, repo_dir: Path) -> Optional[JobInternal]:
        """
        Safely reconstructs an orphaned repository into a valid JobInternal record.
        Only runs if no job state already exists for this job_id.
        Performs static AST analysis only; does NOT execute repository code.
        """
        state_file = self._storage_jobs_dir / job_id / "job_state.json"
        if state_file.is_file() or job_id in self._jobs:
            return self._jobs.get(job_id)

        try:
            import subprocess
            res = subprocess.run(
                ["git", "-C", str(repo_dir), "config", "--get", "remote.origin.url"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            remote_url = res.stdout.strip()
            clean_url = remote_url.removesuffix(".git")
            parts = clean_url.rstrip("/").split("/")
            owner = parts[-2] if len(parts) >= 2 else "unknown"
            repo_name = parts[-1] if len(parts) >= 1 else repo_dir.name

            files = [p for p in repo_dir.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.parts)]
            if not files:
                logger.warning("Orphaned repo directory %s contains no source files; skipping recovery", repo_dir)
                return None

            total_size = sum(f.stat().st_size for f in files)
            file_count = len(files)
            size_mb = total_size / (1024 * 1024)

            now = datetime.now(timezone.utc)
            stages = [
                StageInfo(id=idx + 1, name=stage_name, status=StatusEnum.PENDING, detail=f"Queued for {stage_name}")
                for idx, stage_name in enumerate(PIPELINE_STAGES)
            ]
            stages[0].status = StatusEnum.COMPLETED
            stages[0].detail = f"Cloned successfully ({file_count} files, {size_mb:.2f} MB)"

            analysis = None
            code_analysis = None
            architecture = None
            knowledge = None

            try:
                from ..repo.analyzer import repo_analyzer_service
                from ..repo.code_parser import code_parser_service
                from ..repo.knowledge_builder import knowledge_builder_service
                from ..repo.architecture_analyzer import architecture_analyzer_service

                analysis = repo_analyzer_service.analyze_repository(job_id=job_id, repo_name=repo_name, local_path=str(repo_dir))
                stages[1].status = StatusEnum.COMPLETED
                stages[1].detail = f"Analyzed {analysis.statistics.source_files} source files"

                code_analysis = code_parser_service.parse_repository(job_id=job_id, repo_name=repo_name, local_path=str(repo_dir), analysis=analysis)
                architecture = architecture_analyzer_service.analyze_architecture(job_id=job_id, repo_name=repo_name, parsed_repo=code_analysis, analysis=analysis, local_path=str(repo_dir))
                knowledge = knowledge_builder_service.build_knowledge(
                    job_id=job_id,
                    repo_name=repo_name,
                    repo_owner=owner,
                    repo_url=clean_url,
                    local_path=str(repo_dir),
                    size_mb=round(analysis.statistics.total_size_bytes / (1024 * 1024), 2) if analysis else 0.0,
                    file_count=analysis.statistics.total_files if analysis else 0,
                    analysis=analysis,
                    parsed_repo=code_analysis,
                    architecture=architecture,
                )
                stages[2].status = StatusEnum.COMPLETED
                stages[2].detail = f"Parsed {code_analysis.total_parsed_files} source files, built unified knowledge"
                stages[4].status = StatusEnum.PENDING
                stages[4].detail = "Ready for educational script generation"
            except Exception as e:
                logger.warning("Could not pre-run static analysis on recovered repo %s: %s", job_id, e)

            job = JobInternal(
                job_id=job_id,
                repo_url=clean_url or f"https://github.com/{owner}/{repo_name}",
                repo_name=repo_name,
                repository_owner=owner,
                repository_name=repo_name,
                clone_url=remote_url or clean_url,
                local_path=str(repo_dir.resolve()),
                ingestion_status=StatusEnum.COMPLETED,
                status=StatusEnum.IN_PROGRESS if knowledge else StatusEnum.PENDING,
                current_stage=PIPELINE_STAGES[4] if knowledge else PIPELINE_STAGES[1],
                progress_percentage=44 if knowledge else 11,
                stages=stages,
                created_at=now,
                updated_at=now,
                analysis=analysis,
                code_analysis=code_analysis,
                architecture=architecture,
                knowledge=knowledge,
            )
            self._jobs[job_id] = job
            self._persist_job(job)
            return job
        except Exception as e:
            logger.warning("Failed to recover orphaned repo for %s: %s", job_id, e)
            return None

    def _load_all_jobs_from_disk(self) -> None:
        """Scans storage/jobs for existing job_state.json files on startup."""
        try:
            if self._storage_jobs_dir.is_dir():
                for job_folder in self._storage_jobs_dir.iterdir():
                    if job_folder.is_dir() and job_folder.name not in self._jobs:
                        state_file = job_folder / "job_state.json"
                        if state_file.is_file():
                            try:
                                content = state_file.read_text(encoding="utf-8")
                                job = JobInternal.model_validate_json(content)
                                self._jobs[job.job_id] = job
                                try:
                                    self._job_mtimes[job.job_id] = state_file.stat().st_mtime
                                except OSError:
                                    pass
                            except Exception as err:
                                logger.debug("Skipping unparseable or legacy job state for %s: %s", job_folder.name, err)
        except Exception as e:
            logger.warning("Error scanning jobs on disk: %s", e)

    def _wrap_update_methods(self) -> None:
        """Dynamically wraps job-modifying methods to ensure disk persistence and rehydration."""
        for attr_name in list(dir(self)):
            if attr_name.startswith(("update_", "invalidate_")) or attr_name == "create_job":
                method = getattr(self, attr_name)
                if callable(method) and not getattr(method, "_is_wrapped", False):
                    setattr(self, attr_name, self._make_persisting_wrapper(method))

    def _make_persisting_wrapper(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Extract target job_id from positional or keyword arguments
            job_id = None
            if args:
                first = args[0]
                if isinstance(first, str):
                    job_id = first
                elif hasattr(first, "job_id"):
                    job_id = getattr(first, "job_id", None)
            if not job_id and "job_id" in kwargs and isinstance(kwargs["job_id"], str):
                job_id = kwargs["job_id"]

            if job_id and job_id not in self._jobs:
                self.get_internal_job(job_id)

            res = func(*args, **kwargs)
            if isinstance(res, JobInternal):
                self._persist_job(res)
            return res

        wrapper._is_wrapped = True
        return wrapper

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
        self._persist_job(job)
        return job

    def get_job(self, job_id: str) -> Optional[JobResponse]:
        internal = self.get_internal_job(job_id)
        if not internal:
            return None
        return internal.to_response()

    def get_internal_job(self, job_id: str) -> Optional[JobInternal]:
        state_file = self._storage_jobs_dir / job_id / "job_state.json"
        cached_mtime = self._job_mtimes.get(job_id)

        if job_id in self._jobs:
            if state_file.is_file() and cached_mtime is not None:
                try:
                    disk_mtime = state_file.stat().st_mtime
                    if disk_mtime > cached_mtime:
                        loaded = self._load_job_from_disk(job_id)
                        if loaded is not None:
                            return loaded
                except OSError:
                    pass
            return self._jobs[job_id]

        return self._load_job_from_disk(job_id)

    def list_jobs(self) -> List[JobResponse]:
        self._load_all_jobs_from_disk()
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
        files_count = (
            code_analysis.total_parsed_files
            if code_analysis is not None
            else (len(knowledge.code_structure.files) if (knowledge and knowledge.code_structure) else 0)
        )
        deps_count = (
            architecture.dependency_graph.total_internal_dependencies
            if (architecture is not None and architecture.dependency_graph is not None)
            else 0
        )
        imp_count = len(knowledge.important_files) if (knowledge and knowledge.important_files) else 0
        fw_count = (
            len(knowledge.technology_stack.frameworks)
            if (knowledge and knowledge.technology_stack and knowledge.technology_stack.frameworks)
            else 0
        )
        job.stages[2].detail = (
            f"Consolidated knowledge ({files_count} files, "
            f"{deps_count} internal deps, "
            f"{imp_count} important files, "
            f"{fw_count} frameworks)"
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
        self.invalidate_job_assembly_input(job_id)

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
        self.invalidate_job_assembly_input(job_id)

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

        # Invalidate downstream assembly input when visual assets are updated
        self.invalidate_job_assembly_input(job_id)

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

        # Invalidate downstream assembly input when visual assets are invalidated
        self.invalidate_job_assembly_input(job_id)

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
        self.invalidate_job_assembly_input(job_id)

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
        self.invalidate_job_assembly_input(job_id)

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

        # Invalidate downstream assembly input when captions are updated
        self.invalidate_job_assembly_input(job_id)

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

        # Invalidate downstream assembly input when captions are invalidated
        self.invalidate_job_assembly_input(job_id)

        job.updated_at = now
        return job

    def update_job_assembly_input_success(
        self,
        job_id: str,
        assembly_input: VideoAssemblyInput,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.assembly_input = assembly_input
        # Note: Stage 9 (VIDEO_ASSEMBLY) remains pending for Milestone 6
        if job.stages[8].status == StatusEnum.PENDING:
            job.stages[8].detail = (
                f"Assembly input package compiled ({assembly_input.total_scenes} scenes, "
                f"readiness: {assembly_input.readiness_report.status.value})"
            )
        job.updated_at = now
        return job

    def get_job_assembly_input(self, job_id: str) -> Optional[VideoAssemblyInput]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.assembly_input

    def invalidate_job_assembly_input(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.assembly_input = None
        if job.stages[8].status == StatusEnum.PENDING:
            job.stages[8].detail = "Ready for video assembly"
        
        # Invalidate dependent render job
        self.invalidate_job_render(job_id)

        job.updated_at = now
        return job

    def get_job_render_config(self, job_id: str) -> Optional[VideoRenderConfiguration]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.render_config

    def update_job_render_config(
        self,
        job_id: str,
        config: VideoRenderConfiguration,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.render_config = config
        job.updated_at = now
        return job

    def get_job_render(self, job_id: str) -> Optional[VideoRenderJob]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.render_job

    def update_job_render_started(
        self,
        job_id: str,
        render_job: VideoRenderJob,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.render_job = render_job
        job.stages[8].status = StatusEnum.IN_PROGRESS
        job.stages[8].started_at = now
        job.stages[8].completed_at = None
        job.stages[8].detail = "Rendering video scenes and multiplexing audio..."
        job.current_stage = PIPELINE_STAGES[8]
        job.progress_percentage = 90
        job.updated_at = now
        return job

    def update_job_render_progress(
        self,
        job_id: str,
        progress: VideoRenderProgress,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job or not job.render_job:
            return None
        now = datetime.now(timezone.utc)
        job.render_job.progress = progress
        job.stages[8].detail = progress.stage_detail
        if progress.progress_percentage > 0:
            job.progress_percentage = min(99, 90 + int(progress.progress_percentage * 0.09))
        job.updated_at = now
        return job

    def update_job_render_success(
        self,
        job_id: str,
        result: VideoRenderResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        if job.render_job:
            job.render_job.status = VideoRenderStatus.COMPLETED
            job.render_job.completed_at = now
            job.render_job.output_relative_path = result.output_relative_path
            job.render_job.output_file_size_bytes = result.file_size_bytes
            job.render_job.actual_duration_seconds = result.duration_seconds
        job.stages[8].status = StatusEnum.COMPLETED
        job.stages[8].completed_at = now
        job.stages[8].detail = f"Video assembly completed ({result.duration_seconds:.1f}s, {result.file_size_bytes} bytes)"
        job.progress_percentage = 100
        job.status = StatusEnum.COMPLETED

        # Ensure canonical video result is available for frontend consumption
        video_url = f"/api/v1/jobs/{job_id}/video/file"
        dur_int = max(1, int(round(result.duration_seconds)))
        if job.result:
            job.result.video_url = video_url
            job.result.duration_seconds = dur_int
        else:
            repo_name = job.repo_name
            repo_url = job.repo_url
            desc = (job.project_understanding and getattr(job.project_understanding, "overview", None)) or f"Automated educational walkthrough for {repo_name}."
            tech = (job.knowledge and getattr(job.knowledge, "detected_frameworks", None)) or ["Python", "FastAPI"]
            summ = (job.educational_script and getattr(job.educational_script, "introduction", None)) or f"Comprehensive architectural breakdown of {repo_name}."
            job.result = VideoResult(
                repo_name=repo_name,
                repo_url=repo_url,
                description=desc,
                tech_stack=tech,
                summary=summ,
                video_url=video_url,
                duration_seconds=dur_int,
            )

        job.updated_at = now
        return job

    def update_job_render_failed(
        self,
        job_id: str,
        error_message: str,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        if job.render_job:
            job.render_job.status = VideoRenderStatus.FAILED
            job.render_job.error = error_message
        job.stages[8].status = StatusEnum.FAILED
        job.stages[8].completed_at = now
        job.stages[8].detail = f"Video assembly failed: {error_message}"
        job.updated_at = now
        return job

    def get_job_scene_renders(self, job_id: str) -> Optional[SceneRenderResult]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return job.scene_renders

    def update_job_scene_renders_started(self, job_id: str, total_scenes: int) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[8].status = StatusEnum.IN_PROGRESS
        job.stages[8].started_at = now
        job.stages[8].completed_at = None
        job.stages[8].detail = f"Rendering scene clips (0/{total_scenes})..."
        job.current_stage = PIPELINE_STAGES[8]
        job.progress_percentage = 91
        job.updated_at = now
        return job

    def update_job_scene_render_progress(
        self,
        job_id: str,
        progress: SceneRenderProgress,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.stages[8].detail = progress.stage_detail
        if progress.total_scenes > 0:
            done_count = progress.completed_scenes + progress.failed_scenes
            job.progress_percentage = min(95, 91 + int(4 * (done_count / progress.total_scenes)))
        job.updated_at = now
        return job

    def update_job_scene_renders_completed(
        self,
        job_id: str,
        result: SceneRenderResult,
    ) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.scene_renders = result
        # Stage 09 remains IN_PROGRESS: individual scenes are rendered, but final video assembly is not completed yet
        if result.is_complete:
            job.stages[8].status = StatusEnum.IN_PROGRESS
            job.stages[8].detail = (
                f"Scene rendering complete ({result.completed_scenes}/{result.total_scenes} scenes ready for video assembly)"
            )
            job.progress_percentage = 95
        else:
            job.stages[8].status = StatusEnum.IN_PROGRESS
            job.stages[8].detail = (
                f"Scene rendering partial ({result.completed_scenes}/{result.total_scenes} completed, {result.failed_scenes} failed)"
            )
            job.progress_percentage = 92
        job.updated_at = now
        return job

    def invalidate_job_scene_renders(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.scene_renders = None
        try:
            video_storage_manager.delete_job_scenes(job_id)
        except Exception as e:
            logger.warning("Failed to clean scene storage for job %s: %s", job_id, e)
        job.updated_at = now
        return job

    def invalidate_job_render(self, job_id: str) -> Optional[JobInternal]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        now = datetime.now(timezone.utc)
        job.render_job = None
        self.invalidate_job_scene_renders(job_id)
        try:
            video_storage_manager.delete_job_video(job_id)
        except Exception as e:
            logger.warning("Failed to clean video storage for job %s: %s", job_id, e)
        if job.stages[8].status in (StatusEnum.COMPLETED, StatusEnum.IN_PROGRESS, StatusEnum.FAILED):
            job.stages[8].status = StatusEnum.PENDING
            job.stages[8].started_at = None
            job.stages[8].completed_at = None
            job.stages[8].detail = "Ready for video assembly"
        job.updated_at = now
        return job

    def update_job(self, job: JobInternal) -> JobInternal:
        job.updated_at = datetime.now(timezone.utc)
        self._jobs[job.job_id] = job
        return job

job_store = JobStore()
