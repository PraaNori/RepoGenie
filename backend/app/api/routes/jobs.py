import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from ...models.schemas import (
    ArchitectureAnalysisResult,
    JobCreateRequest,
    JobResponse,
    ParsedRepository,
    RepoAnalysisResult,
    RepositoryKnowledge,
    StatusEnum,
    VideoResult,
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
from ...utils.github_url import (
    GitHubURLValidationError,
    RepositoryAccessibilityError,
    RepositoryNotFoundError,
    parse_and_validate_github_url,
    verify_repository_accessible,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

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
