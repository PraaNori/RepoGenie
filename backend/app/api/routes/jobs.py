import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from ...models.schemas import (
    JobCreateRequest,
    JobResponse,
    RepoAnalysisResult,
    StatusEnum,
    VideoResult,
)
from ...services.repo.analyzer import repo_analyzer_service
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
        if internal_job and internal_job.local_path:
            job_store.update_job_analysis_started(job_id)
            try:
                analysis = repo_analyzer_service.analyze_repository(
                    job_id=job_id,
                    repo_name=internal_job.repo_name,
                    local_path=internal_job.local_path,
                )
                job_store.update_job_analysis_success(job_id, analysis)
                logger.info(
                    "Successfully analyzed repository for job %s: %d source files, %d languages",
                    job_id,
                    analysis.statistics.source_files,
                    analysis.statistics.recognized_languages_count,
                )
            except Exception as exc:
                job_store.update_job_analysis_failed(job_id, str(exc))
                logger.exception("Repository analysis failed for job %s: %s", job_id, exc)

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
