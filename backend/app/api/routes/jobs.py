import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import FileResponse
from ...models.schemas import (
    ArchitectureAnalysisResult,
    JobCreateRequest,
    JobResponse,
    ParsedRepository,
    RepoAnalysisResult,
    RepositoryKnowledge,
    StageEnum,
    StatusEnum,
    VideoResult,
)
from ...services.ai.exceptions import AIError
from ...services.ai.project_understanding import (
    ProjectUnderstanding,
    project_understanding_analyzer,
)
from ...services.ai.code_understanding import (
    RepositoryCodeUnderstanding,
    code_understanding_analyzer,
)
from ...services.ai.workflow_understanding import (
    RepositoryWorkflowUnderstanding,
    workflow_understanding_analyzer,
)
from ...services.ai.script_generation import (
    EducationalScript,
    educational_script_analyzer,
)
from ...services.ai.storyboard_generation import (
    EducationalStoryboard,
    educational_storyboard_analyzer,
)
from ...services.video.visual_generation import (
    PathTraversalError,
    VisualAsset,
    VisualGenerationResult,
    visual_generation_service,
    visual_storage_manager,
)
from ...services.repo.analyzer import repo_analyzer_service
from ...services.repo.architecture_analyzer import architecture_analyzer_service
from ...services.repo.code_parser import code_parser_service
from ...services.repo.knowledge_builder import knowledge_builder_service
from ...services.repo.ingest import (
    CloneExecutionError,
    CloneTimeoutError,
    DestinationExistsError,
    RepoIngestionError,
    RepositorySizeExceededError,
    repo_ingestion_service,
)
from ...services.storage.job_store import PIPELINE_STAGES, job_store
from ...core.config import settings
from ...utils.github_url import (
    GitHubURLValidationError,
    RepositoryAccessibilityError,
    RepositoryNotFoundError,
    parse_and_validate_github_url,
    verify_repository_accessible,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _sanitize_error_message(msg: str, local_path: Optional[str] = None) -> str:
    """Removes sensitive keys and absolute local repository paths from user-facing error details."""
    if not msg:
        return ""
    if local_path and local_path in msg:
        msg = msg.replace(local_path, "<REPO_ROOT>")
    if getattr(settings, "GROQ_API_KEY", None) and settings.GROQ_API_KEY in msg:
        msg = msg.replace(settings.GROQ_API_KEY, "[REDACTED]")
    if getattr(settings, "GEMINI_API_KEY", None) and settings.GEMINI_API_KEY in msg:
        msg = msg.replace(settings.GEMINI_API_KEY, "[REDACTED]")
    return msg

def run_ingestion_and_analysis_task(job_id: str, clone_url: str):
    """
    Background worker task to clone the repository and automatically perform structure & file analysis.
    """
    job_store.update_job_ingestion_started(job_id)
    try:
        # Step 1: Clone repository
        result = repo_ingestion_service.ingest_repository(job_id, clone_url)
        job_store.update_job_ingestion_success(
            job_id=job_id,
            local_path=result.local_path,
            file_count=result.file_count,
            size_mb=result.size_mb,
        )
        logger.info(
            "Successfully ingested repository for job %s: %d files, %.2f MB",
            job_id,
            result.file_count,
            result.size_mb,
        )

        # Step 2: Milestone 2.3 Repository Structure and File Analysis
        internal_job = job_store.get_internal_job(job_id)
        analysis_result = None
        if internal_job and internal_job.local_path:
            job_store.update_job_analysis_started(job_id)
            try:
                analysis = repo_analyzer_service.analyze_repository(
                    job_id=job_id,
                    repo_name=internal_job.repo_name,
                    local_path=internal_job.local_path,
                )
                job_store.update_job_analysis_success(job_id, analysis)
                analysis_result = analysis
                logger.info(
                    "Successfully analyzed repository for job %s: %d source files, %d languages",
                    job_id,
                    analysis.statistics.source_files,
                    analysis.statistics.recognized_languages_count,
                )
            except Exception as exc:
                job_store.update_job_analysis_failed(job_id, str(exc))
                logger.exception("Repository analysis failed for job %s: %s", job_id, exc)

            # Step 3: Milestone 2.4 Code Parsing and Structural Extraction
            job_store.update_job_code_parsing_started(job_id)
            try:
                code_analysis = code_parser_service.parse_repository(
                    job_id=job_id,
                    repo_name=internal_job.repo_name,
                    local_path=internal_job.local_path,
                    analysis=analysis_result,
                )
                logger.info(
                    "Successfully parsed code for job %s: %d files, %d functions, %d classes",
                    job_id,
                    code_analysis.total_parsed_files,
                    code_analysis.total_functions,
                    code_analysis.total_classes,
                )

                # Step 4: Milestone 2.5 Architecture and Dependency Relationship Analysis
                architecture = architecture_analyzer_service.analyze_architecture(
                    job_id=job_id,
                    repo_name=internal_job.repo_name,
                    parsed_repo=code_analysis,
                    analysis=analysis_result,
                    local_path=internal_job.local_path,
                )
                logger.info(
                    "Successfully analyzed architecture for job %s: %d internal dependencies, %d resolved calls, %d entry points, %d components",
                    job_id,
                    architecture.dependency_graph.total_internal_dependencies,
                    architecture.call_graph.total_resolved_calls,
                    len(architecture.entry_points),
                    len(architecture.components),
                )

                # Step 5: Milestone 2.6 Unified Repository Knowledge Representation
                knowledge = knowledge_builder_service.build_knowledge(
                    job_id=job_id,
                    repo_name=internal_job.repo_name,
                    repo_owner=internal_job.repository_owner,
                    repo_url=internal_job.repo_url,
                    local_path=internal_job.local_path,
                    size_mb=result.size_mb,
                    file_count=result.file_count,
                    analysis=analysis_result,
                    parsed_repo=code_analysis,
                    architecture=architecture,
                )
                job_store.update_job_knowledge_success(
                    job_id=job_id,
                    code_analysis=code_analysis,
                    architecture=architecture,
                    knowledge=knowledge,
                )
                logger.info(
                    "Successfully built repository knowledge for job %s: %d important files, %d frameworks, %d source evidence records",
                    job_id,
                    len(knowledge.important_files),
                    len(knowledge.technology_stack.frameworks),
                    len(knowledge.source_evidence),
                )
            except Exception as exc:
                job_store.update_job_code_parsing_failed(job_id, str(exc))
                logger.exception("Code understanding or knowledge consolidation failed for job %s: %s", job_id, exc)

    except DestinationExistsError as exc:
        job_store.update_job_ingestion_failed(job_id, str(exc))
        logger.error("Destination exists for job %s: %s", job_id, exc)
    except CloneTimeoutError as exc:
        job_store.update_job_ingestion_failed(job_id, str(exc))
        logger.error("Clone timeout for job %s: %s", job_id, exc)
    except RepositorySizeExceededError as exc:
        job_store.update_job_ingestion_failed(job_id, str(exc))
        logger.error("Size exceeded for job %s: %s", job_id, exc)
    except CloneExecutionError as exc:
        job_store.update_job_ingestion_failed(job_id, str(exc))
        logger.error("Clone execution failed for job %s: %s", job_id, exc)
    except Exception as exc:
        job_store.update_job_ingestion_failed(job_id, f"Unexpected ingestion error: {exc}")
        logger.exception("Unexpected error ingesting repository for job %s", job_id)

@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    wait: bool = Query(
        False,
        description="If True, performs cloning and analysis synchronously before returning response.",
    ),
):
    """
    Validate GitHub repository URL, verify accessibility, and initialize repository ingestion and analysis.
    """
    # 1. Validate GitHub URL format
    try:
        parsed = parse_and_validate_github_url(payload.github_url)
    except GitHubURLValidationError as exc:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY),
            detail=str(exc),
        ) from exc

    # 2. Verify repository existence and public accessibility on GitHub
    try:
        verify_repository_accessible(parsed.canonical_url)
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RepositoryAccessibilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    # 3. Create job record in job store
    full_name = f"{parsed.owner}/{parsed.repo}"
    internal_job = job_store.create_job(
        repo_url=parsed.canonical_url,
        repo_name=full_name,
        repository_owner=parsed.owner,
        repository_name=parsed.repo,
        clone_url=parsed.clone_url,
    )

    # 4. Ingest repository (synchronously if wait=True, or via background task)
    if wait:
        try:
            run_ingestion_and_analysis_task(internal_job.job_id, parsed.clone_url)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ingestion and analysis failed: {exc}",
            ) from exc
        return job_store.get_job(internal_job.job_id)

    # Initiate background cloning and subsequent analysis
    job_store.update_job_ingestion_started(internal_job.job_id)
    background_tasks.add_task(run_ingestion_and_analysis_task, internal_job.job_id, parsed.clone_url)
    return internal_job.to_response()

@router.get("", response_model=list[JobResponse])
def list_jobs():
    """List recent video generation jobs."""
    return job_store.list_jobs()

@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    """Get the current status and stage details of a video generation job."""
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )
    return job

@router.get("/{job_id}/analysis", response_model=RepoAnalysisResult)
def get_job_analysis(job_id: str):
    """
    Get the detailed repository structure, languages, dependency manifests, and statistics.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )
    if internal.ingestion_status == StatusEnum.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository ingestion failed for job '{job_id}': {internal.error}",
        )
    if internal.ingestion_status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion is still in progress for job '{job_id}'.",
        )
    if not internal.analysis:
        if internal.stages[1].status == StatusEnum.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Repository analysis failed: {internal.stages[1].detail}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository analysis is still in progress for job '{job_id}'.",
        )
    return internal.analysis

@router.get("/{job_id}/code-analysis", response_model=ParsedRepository)
def get_job_code_analysis(job_id: str):
    """
    Get the detailed AST-parsed code structure metadata (functions, classes, methods, imports, calls).
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )
    if internal.ingestion_status == StatusEnum.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository ingestion failed for job '{job_id}': {internal.error}",
        )
    if internal.ingestion_status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion is still in progress for job '{job_id}'.",
        )
    if internal.stages[1].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis is still in progress for job '{job_id}'.",
        )
    if internal.stages[2].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Code parsing is still in progress for job '{job_id}'.",
        )
    if not internal.code_analysis:
        if internal.stages[2].status == StatusEnum.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Code parsing failed: {internal.stages[2].detail}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Code parsing metadata is not ready for job '{job_id}'.",
        )
    return internal.code_analysis

@router.get("/{job_id}/architecture", response_model=ArchitectureAnalysisResult)
def get_job_architecture(job_id: str):
    """
    Get the detailed architecture and dependency relationship analysis (dependency graph, call graph, inheritance, entry points, components).
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )
    if internal.ingestion_status == StatusEnum.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository ingestion failed for job '{job_id}': {internal.error}",
        )
    if internal.ingestion_status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion is still in progress for job '{job_id}'.",
        )
    if internal.stages[1].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis is still in progress for job '{job_id}'.",
        )
    if internal.stages[2].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Architecture and code analysis is still in progress for job '{job_id}'.",
        )
    if not internal.architecture:
        if internal.stages[2].status == StatusEnum.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Architecture analysis failed: {internal.stages[2].detail}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Architecture analysis metadata is not ready for job '{job_id}'.",
        )
    return internal.architecture

@router.get("/{job_id}/knowledge", response_model=RepositoryKnowledge)
def get_job_knowledge(job_id: str):
    """
    Get the unified repository knowledge representation consolidating structure, code parsing, and architecture.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )
    if internal.ingestion_status == StatusEnum.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository ingestion failed for job '{job_id}': {internal.error}",
        )
    if internal.ingestion_status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion is still in progress for job '{job_id}'.",
        )
    if internal.stages[1].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis is still in progress for job '{job_id}'.",
        )
    if internal.stages[2].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Code understanding and knowledge consolidation are still in progress for job '{job_id}'.",
        )
    if not internal.knowledge:
        if internal.stages[2].status == StatusEnum.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Knowledge consolidation failed: {internal.stages[2].detail}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge representation is not ready for job '{job_id}'.",
        )
    return internal.knowledge

@router.get("/{job_id}/project-understanding", response_model=ProjectUnderstanding)
def get_job_project_understanding(job_id: str):
    """
    Returns the cached AI-generated project understanding for a job.
    Returns 404 if job not found or understanding not yet generated.
    Returns 409 if prerequisite stages are still in progress.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Check prerequisite stages
    if internal.stages[0].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository fetching is still in progress for job '{job_id}'.",
        )
    if internal.stages[1].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository analysis is still in progress for job '{job_id}'.",
        )
    if internal.stages[2].status in (StatusEnum.PENDING, StatusEnum.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Code understanding is still in progress for job '{job_id}'.",
        )

    if not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge must be completed before project understanding can be viewed.",
        )

    if not internal.project_understanding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project understanding has not yet been generated for job '{job_id}'. Call POST /jobs/{job_id}/project-understanding to generate it.",
        )

    return internal.project_understanding


@router.post("/{job_id}/project-understanding", response_model=ProjectUnderstanding)
async def generate_job_project_understanding(
    job_id: str,
    provider: Optional[str] = Query(None, description="Optional override provider (e.g. gemini, groq)"),
    refresh: bool = Query(False, description="Whether to re-generate if already cached"),
):
    """
    Generates or retrieves cached AI project-level understanding for a job using the configured LLM.
    Advances Stage 4 (AI Summary Generation) to COMPLETED upon success.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Check prerequisite stages
    if internal.stages[0].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion must be completed first (current status: {internal.stages[0].status.value}).",
        )
    if internal.stages[1].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis must be completed first (current status: {internal.stages[1].status.value}).",
        )
    if internal.stages[2].status != StatusEnum.COMPLETED or not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge consolidation must be completed first (current status: {internal.stages[2].status.value}).",
        )

    # Acquire dedicated per-job lock to serialize concurrent requests for the same job atomically
    job_lock = await job_store.get_job_lock(job_id)
    async with job_lock:
        # Re-fetch latest internal job state inside the lock
        internal = job_store.get_internal_job(job_id)
        if not internal or not internal.knowledge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )

        # Return cached if already available and refresh not requested
        if internal.project_understanding and not refresh:
            return internal.project_understanding

        # Prevent duplicate execution if another process or thread marked Stage 4 IN_PROGRESS
        if internal.stages[3].status == StatusEnum.IN_PROGRESS and not refresh:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Project understanding generation is already in progress for job '{job_id}'.",
            )

        # Update job stage to IN_PROGRESS atomically
        job_store.update_job_ai_summary_started(job_id)

        try:
            understanding = await project_understanding_analyzer.analyze_project(
                job_id=job_id,
                knowledge=internal.knowledge,
                provider_name=provider,
                local_path=internal.local_path,
            )
            job_store.update_job_ai_summary_success(job_id, understanding)
            return understanding
        except AIError as ai_err:
            job_store.update_job_ai_summary_failed(job_id, str(ai_err))
            raise HTTPException(
                status_code=ai_err.status_code if ai_err.status_code and ai_err.status_code >= 400 else 500,
                detail=f"AI project understanding failed: {ai_err.message}",
            )
        except Exception as exc:
            job_store.update_job_ai_summary_failed(job_id, str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during project understanding: {exc}",
            )

@router.post("/{job_id}/code-understanding", response_model=RepositoryCodeUnderstanding)
async def generate_job_code_understanding(
    job_id: str,
    provider: Optional[str] = Query(None, description="AI provider to use (gemini or groq)"),
    refresh: bool = Query(False, description="Force re-generation even if code understanding already exists"),
):
    """
    Generates or retrieves cached component-level and code-level understanding for a job.
    Does not reset Stage 4 completion status or alter Stage 5.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Check prerequisite stages: ingestion, structure analysis, and code parsing / knowledge consolidation
    if internal.stages[0].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion must be completed first (current status: {internal.stages[0].status.value}).",
        )
    if internal.stages[1].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis must be completed first (current status: {internal.stages[1].status.value}).",
        )
    if internal.stages[2].status != StatusEnum.COMPLETED or not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge consolidation must be completed first (current status: {internal.stages[2].status.value}).",
        )

    # Acquire dedicated per-job lock to serialize concurrent requests for the same job atomically
    job_lock = await job_store.get_job_lock(job_id)
    async with job_lock:
        internal = job_store.get_internal_job(job_id)
        if not internal or not internal.knowledge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )

        # Return cached if already available and refresh not requested
        if internal.code_understanding and not refresh:
            return internal.code_understanding

        try:
            understanding = await code_understanding_analyzer.analyze_codebase(
                job_id=job_id,
                knowledge=internal.knowledge,
                project_understanding=internal.project_understanding,
                provider_name=provider,
                local_path=internal.local_path,
            )
            job_store.update_job_code_understanding_success(job_id, understanding)
            return understanding
        except AIError as ai_err:
            raise HTTPException(
                status_code=ai_err.status_code if ai_err.status_code and ai_err.status_code >= 400 else 500,
                detail=f"AI code understanding failed: {ai_err.message}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during code understanding: {exc}",
            )

@router.get("/{job_id}/code-understanding", response_model=RepositoryCodeUnderstanding)
def get_job_code_understanding(job_id: str):
    """
    Retrieves cached component-level and code-level understanding for a job.
    Returns 404 if not yet generated.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not internal.code_understanding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Code understanding has not yet been generated for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/code-understanding to generate.",
        )

    return internal.code_understanding


@router.post("/{job_id}/workflow-understanding", response_model=RepositoryWorkflowUnderstanding)
async def generate_job_workflow_understanding(
    job_id: str,
    provider: Optional[str] = Query(None, description="AI provider to use (gemini or groq)"),
    refresh: bool = Query(False, description="Force re-generation even if workflow understanding already exists"),
):
    """
    Generates or retrieves cached application workflow and data-flow understanding for a job.
    Requires completed repository analysis, parsed code structure, CallGraph, and knowledge.
    Does not reset Stage 4 completion status or alter Stage 5 pending status.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # 1. Prerequisite verification
    if internal.stages[0].status != StatusEnum.COMPLETED or not internal.local_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository ingestion must be completed first (source directory unavailable).",
        )
    if internal.stages[1].status != StatusEnum.COMPLETED or not internal.analysis:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis must be completed first (current status: {internal.stages[1].status.value}).",
        )
    if not internal.code_analysis:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parsed code structure is required before workflow understanding can be generated.",
        )
    if not internal.architecture or not getattr(internal.architecture, "call_graph", None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Architecture analysis and directional CallGraph are required before workflow understanding can be generated.",
        )
    if internal.stages[2].status != StatusEnum.COMPLETED or not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge consolidation must be completed first (current status: {internal.stages[2].status.value}).",
        )

    # Acquire dedicated per-job lock to serialize concurrent requests for the same job atomically
    job_lock = await job_store.get_job_lock(job_id)
    async with job_lock:
        internal = job_store.get_internal_job(job_id)
        if not internal or not internal.knowledge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )

        # Return cached if already available and refresh not requested
        if internal.workflow_understanding and not refresh:
            return internal.workflow_understanding

        try:
            understanding = await workflow_understanding_analyzer.analyze_workflows(
                job_id=job_id,
                knowledge=internal.knowledge,
                project_understanding=internal.project_understanding,
                code_understanding=internal.code_understanding,
                provider_name=provider,
                local_path=internal.local_path,
            )
            job_store.update_job_workflow_understanding_success(job_id, understanding)
            return understanding
        except AIError as ai_err:
            logger.error("AI error during workflow understanding for job %s: %s", job_id, ai_err)
            err_msg = ai_err.message
            if internal.local_path and internal.local_path in err_msg:
                err_msg = err_msg.replace(internal.local_path, "<REPO_ROOT>")
            raise HTTPException(
                status_code=ai_err.status_code if ai_err.status_code and ai_err.status_code >= 400 else 500,
                detail=f"AI workflow understanding failed: {err_msg}",
            )
        except Exception as exc:
            logger.exception("Unexpected error during workflow understanding for job %s: %s", job_id, exc)
            exc_msg = str(exc)
            if internal.local_path and internal.local_path in exc_msg:
                exc_msg = exc_msg.replace(internal.local_path, "<REPO_ROOT>")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during workflow understanding: {exc_msg}",
            )


@router.get("/{job_id}/workflow-understanding", response_model=RepositoryWorkflowUnderstanding)
def get_job_workflow_understanding(job_id: str):
    """
    Retrieves cached application workflow and data-flow understanding for a job.
    Returns 404 if not yet generated.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not internal.workflow_understanding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow understanding has not yet been generated for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/workflow-understanding to generate.",
        )

    return internal.workflow_understanding


@router.post("/{job_id}/educational-script", response_model=EducationalScript)
async def generate_job_educational_script(
    job_id: str,
    provider: Optional[str] = Query(None, description="Optional override AI provider (e.g. groq, gemini)"),
    refresh: bool = Query(False, description="Whether to re-generate if already cached"),
):
    """
    Generates or retrieves cached educational narration script for a job.
    Advances Stage 5 (Script Generation) to COMPLETED upon success.
    If refresh=True, invalidates any previously generated educational storyboard.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Check prerequisite stages: ingestion, structure analysis, and code parsing / knowledge consolidation
    if internal.stages[0].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion must be completed first (current status: {internal.stages[0].status.value}).",
        )
    if internal.stages[1].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis must be completed first (current status: {internal.stages[1].status.value}).",
        )
    if internal.stages[2].status != StatusEnum.COMPLETED or not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge consolidation must be completed first (current status: {internal.stages[2].status.value}).",
        )

    # Acquire dedicated per-job lock to serialize concurrent requests for the same job atomically
    job_lock = await job_store.get_job_lock(job_id)
    async with job_lock:
        internal = job_store.get_internal_job(job_id)
        if not internal or not internal.knowledge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )

        # Return cached if already available and refresh not requested
        if internal.educational_script and not refresh:
            return internal.educational_script

        # Prevent duplicate execution if another process or thread marked Stage 5 IN_PROGRESS
        if internal.stages[4].status == StatusEnum.IN_PROGRESS and not refresh:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Educational script generation is already in progress for job '{job_id}'.",
            )

        # Update job stage to IN_PROGRESS atomically
        job_store.update_job_educational_script_started(job_id)

        try:
            script = await educational_script_analyzer.generate_script(
                job_id=job_id,
                knowledge=internal.knowledge,
                project_understanding=internal.project_understanding,
                code_understanding=internal.code_understanding,
                workflow_understanding=internal.workflow_understanding,
                provider_name=provider,
                local_path=internal.local_path,
            )
            job_store.update_job_educational_script_success(job_id, script)
            return script
        except AIError as ai_err:
            logger.error("AI error during educational script generation for job %s: %s", job_id, ai_err)
            job_store.update_job_educational_script_failed(job_id, str(ai_err))
            err_msg = _sanitize_error_message(ai_err.message, internal.local_path)
            raise HTTPException(
                status_code=ai_err.status_code if ai_err.status_code and ai_err.status_code >= 400 else 502,
                detail=f"AI educational script generation failed: {err_msg}",
            )
        except Exception as exc:
            logger.exception("Unexpected error during educational script generation for job %s: %s", job_id, exc)
            job_store.update_job_educational_script_failed(job_id, str(exc))
            exc_msg = _sanitize_error_message(str(exc), internal.local_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during educational script generation: {exc_msg}",
            )


@router.get("/{job_id}/educational-script", response_model=EducationalScript)
def get_job_educational_script(job_id: str):
    """
    Retrieves cached educational narration script for a job.
    Returns 404 if not yet generated.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not internal.educational_script:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Educational script has not yet been generated for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/educational-script to generate.",
        )

    return internal.educational_script


@router.post("/{job_id}/educational-storyboard", response_model=EducationalStoryboard)
async def generate_job_educational_storyboard(
    job_id: str,
    provider: Optional[str] = Query(None, description="Optional override AI provider (e.g. groq, gemini)"),
    refresh: bool = Query(False, description="Whether to re-generate if already cached"),
):
    """
    Generates or retrieves cached educational storyboard for a job.
    Requires an existing generated EducationalScript.
    Advances Stage 6 (Storyboard Generation) to COMPLETED upon success.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Storyboard requires existing EducationalScript
    if not internal.educational_script:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Educational script must be generated before storyboard generation for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/educational-script first.",
        )

    if not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository knowledge is required for educational storyboard generation.",
        )

    # Acquire dedicated per-job lock to serialize concurrent requests for the same job atomically
    job_lock = await job_store.get_job_lock(job_id)
    async with job_lock:
        internal = job_store.get_internal_job(job_id)
        if not internal or not internal.knowledge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )
        if not internal.educational_script:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Educational script must be generated before storyboard generation for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/educational-script first.",
            )

        # Return cached if already available and refresh not requested
        if internal.educational_storyboard and not refresh:
            return internal.educational_storyboard

        # Prevent duplicate execution if another process or thread marked Stage 6 IN_PROGRESS
        if internal.stages[5].status == StatusEnum.IN_PROGRESS and not refresh:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Educational storyboard generation is already in progress for job '{job_id}'.",
            )

        # Update job stage to IN_PROGRESS atomically
        job_store.update_job_educational_storyboard_started(job_id)

        try:
            storyboard = await educational_storyboard_analyzer.generate_storyboard(
                job_id=job_id,
                script=internal.educational_script,
                knowledge=internal.knowledge,
                project_understanding=internal.project_understanding,
                code_understanding=internal.code_understanding,
                workflow_understanding=internal.workflow_understanding,
                provider_name=provider,
                local_path=internal.local_path,
            )
            job_store.update_job_educational_storyboard_success(job_id, storyboard)
            return storyboard
        except AIError as ai_err:
            logger.error("AI error during educational storyboard generation for job %s: %s", job_id, ai_err)
            job_store.update_job_educational_storyboard_failed(job_id, str(ai_err))
            err_msg = _sanitize_error_message(ai_err.message, internal.local_path)
            raise HTTPException(
                status_code=ai_err.status_code if ai_err.status_code and ai_err.status_code >= 400 else 502,
                detail=f"AI educational storyboard generation failed: {err_msg}",
            )
        except Exception as exc:
            logger.exception("Unexpected error during educational storyboard generation for job %s: %s", job_id, exc)
            job_store.update_job_educational_storyboard_failed(job_id, str(exc))
            exc_msg = _sanitize_error_message(str(exc), internal.local_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during educational storyboard generation: {exc_msg}",
            )


@router.get("/{job_id}/educational-storyboard", response_model=EducationalStoryboard)
def get_job_educational_storyboard(job_id: str):
    """
    Retrieves cached educational storyboard for a job.
    Returns 404 if not yet generated.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not internal.educational_storyboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Educational storyboard has not yet been generated for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/educational-storyboard to generate.",
        )

    return internal.educational_storyboard


@router.post("/{job_id}/visual-assets", response_model=VisualGenerationResult)
async def generate_job_visual_assets(
    job_id: str,
    refresh: bool = Query(False, description="Whether to re-initialize and purge previously planned visual assets"),
):
    """
    Initializes or retrieves the visual generation foundation for a job's educational storyboard.
    Requires an existing generated EducationalStoryboard.
    Advances Stage 7 (Visual Generation) to COMPLETED upon planning success.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    # Ingestion & Analysis prerequisites
    if internal.stages[0].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository ingestion must be completed first (current status: {internal.stages[0].status.value}).",
        )
    if internal.stages[1].status != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository structure analysis must be completed first (current status: {internal.stages[1].status.value}).",
        )
    if internal.stages[2].status != StatusEnum.COMPLETED or not internal.knowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Repository knowledge consolidation must be completed first (current status: {internal.stages[2].status.value}).",
        )

    # Visual generation requires an existing EducationalStoryboard
    if not internal.educational_storyboard:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Educational storyboard must be generated before visual asset generation for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/educational-storyboard first.",
        )

    # Acquire dedicated per-job lock to serialize concurrent requests for the same job atomically
    job_lock = await job_store.get_job_lock(job_id)
    async with job_lock:
        internal = job_store.get_internal_job(job_id)
        if not internal or not internal.knowledge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )
        if not internal.educational_storyboard:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Educational storyboard must be generated before visual asset generation for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/educational-storyboard first.",
            )

        # Return cached plan if already available and refresh not requested
        if internal.visual_generation and not refresh:
            return internal.visual_generation

        # Update job stage to IN_PROGRESS atomically for planning
        job_store.update_job_visual_planning_started(job_id)

        try:
            result = visual_generation_service.initialize_visual_assets(
                job_id=job_id,
                storyboard=internal.educational_storyboard,
                script=internal.educational_script,
                knowledge=internal.knowledge,
                refresh=refresh,
            )
            job_store.update_job_visual_planning_success(job_id, result)
            return result
        except Exception as exc:
            logger.exception("Unexpected error during visual asset planning for job %s: %s", job_id, exc)
            job_store.update_job_visual_generation_failed(job_id, str(exc))
            exc_msg = _sanitize_error_message(str(exc), internal.local_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during visual asset planning: {exc_msg}",
            )


@router.get("/{job_id}/visual-assets", response_model=VisualGenerationResult)
def get_job_visual_assets(job_id: str):
    """
    Retrieves visual asset generation blueprint and asset status for a job.
    Returns 404 if not yet initialized.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not internal.visual_generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Visual assets have not yet been initialized for job '{job_id}'. Call POST /api/v1/jobs/{job_id}/visual-assets to generate.",
        )

    return internal.visual_generation


@router.get("/{job_id}/visual-assets/{asset_id}", response_model=VisualAsset)
def get_job_visual_asset_by_id(job_id: str, asset_id: str):
    """
    Retrieves metadata for a specific visual asset in a job.
    Returns 404 if not found.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if not internal.visual_generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Visual assets have not yet been initialized for job '{job_id}'.",
        )

    asset = internal.visual_generation.get_asset_by_id(asset_id)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Visual asset '{asset_id}' not found in job '{job_id}'.",
        )

    return asset


@router.get("/{job_id}/visual-assets/{asset_id}/file")
def get_job_visual_asset_file(job_id: str, asset_id: str):
    """
    Retrieves rendered media file content for a visual asset if available on disk.
    Enforces safe path handling and returns 404 if not yet rendered to disk.
    """
    internal = job_store.get_internal_job(job_id)
    if not internal or not internal.visual_generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' or its visual assets not found.",
        )

    asset = internal.visual_generation.get_asset_by_id(asset_id)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Visual asset '{asset_id}' not found in job '{job_id}'.",
        )

    filename = Path(asset.storage_path).name
    try:
        if not visual_storage_manager.asset_file_exists(job_id, filename):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Visual asset file '{asset_id}' has not yet been rendered to disk (Phase 5.2).",
            )
        abs_path = visual_storage_manager.get_asset_file_path(job_id, filename, must_exist=True)
        media_type = "image/svg+xml" if asset.media_format.value == "svg" else "application/octet-stream"
        return FileResponse(path=str(abs_path), media_type=media_type, filename=filename)
    except PathTraversalError as pte:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid asset path: {pte}",
        )

@router.post("/{job_id}/simulate-step", response_model=JobResponse)
def simulate_job_step(job_id: str):
    """
    Simulation helper endpoint:
    Advances the pipeline by one stage for stages after Repository Fetching and Analysis.
    """
    internal_job = job_store.get_internal_job(job_id)
    if not internal_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if internal_job.status == StatusEnum.COMPLETED:
        return internal_job.to_response()

    # Find first non-completed stage
    now = datetime.now(timezone.utc)
    target_idx = None
    for idx, stage in enumerate(internal_job.stages):
        if stage.status != StatusEnum.COMPLETED:
            target_idx = idx
            break

    if target_idx is not None:
        # Mark previous stages completed
        for i in range(target_idx):
            internal_job.stages[i].status = StatusEnum.COMPLETED

        current_stage = internal_job.stages[target_idx]
        if current_stage.status == StatusEnum.PENDING:
            current_stage.status = StatusEnum.IN_PROGRESS
            current_stage.started_at = now
            current_stage.detail = f"Processing {current_stage.name}..."
            internal_job.status = StatusEnum.IN_PROGRESS
            internal_job.current_stage = current_stage.name
            internal_job.progress_percentage = int(((target_idx + 0.5) / len(internal_job.stages)) * 100)
        elif current_stage.status == StatusEnum.IN_PROGRESS:
            current_stage.status = StatusEnum.COMPLETED
            current_stage.completed_at = now
            current_stage.detail = f"Completed {current_stage.name} successfully."
            internal_job.progress_percentage = int(((target_idx + 1) / len(internal_job.stages)) * 100)

            if current_stage.name == StageEnum.AI_SUMMARY.value and internal_job.knowledge:
                if not internal_job.project_understanding:
                    internal_job.project_understanding = project_understanding_analyzer.create_rule_based_fallback(
                        internal_job.knowledge, local_path=internal_job.local_path
                    )
                if not internal_job.code_understanding:
                    internal_job.code_understanding = code_understanding_analyzer.create_rule_based_fallback(
                        internal_job.knowledge,
                        project_understanding=internal_job.project_understanding,
                        local_path=internal_job.local_path,
                    )
                if not internal_job.workflow_understanding:
                    internal_job.workflow_understanding = workflow_understanding_analyzer.create_deterministic_fallback(
                        knowledge=internal_job.knowledge,
                    )

            # Check if there is a next stage
            if target_idx + 1 < len(internal_job.stages):
                next_stage = internal_job.stages[target_idx + 1]
                next_stage.status = StatusEnum.IN_PROGRESS
                next_stage.started_at = now
                next_stage.detail = f"Starting {next_stage.name}..."
                internal_job.current_stage = next_stage.name
            else:
                internal_job.status = StatusEnum.COMPLETED
                internal_job.current_stage = "All stages completed"
                internal_job.progress_percentage = 100
                internal_job.result = VideoResult(
                    repo_name=internal_job.repo_name,
                    repo_url=internal_job.repo_url,
                    description=f"Automated educational walkthrough for {internal_job.repo_name}.",
                    tech_stack=["React", "FastAPI", "Python", "Tailwind CSS"],
                    summary=f"This video breaks down the architecture, modules, and data flow of {internal_job.repo_name}.",
                    video_url="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
                    duration_seconds=180,
                )

    job_store.update_job(internal_job)
    return internal_job.to_response()
