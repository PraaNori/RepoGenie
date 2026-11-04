from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from ...models.schemas import (
    JobCreateRequest,
    JobResponse,
    StatusEnum,
    VideoResult,
)
from ...services.storage.job_store import PIPELINE_STAGES, job_store
from ...utils.validation import parse_github_url

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreateRequest):
    """
    Validate GitHub repository URL and initialize a video generation pipeline job.
    """
    parsed = parse_github_url(payload.github_url)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid GitHub repository URL. Must match format https://github.com/owner/repository",
        )
    owner, repo_name = parsed
    full_name = f"{owner}/{repo_name}"

    job = job_store.create_job(repo_url=payload.github_url.strip(), repo_name=full_name)
    return job

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

@router.post("/{job_id}/simulate-step", response_model=JobResponse)
def simulate_job_step(job_id: str):
    """
    Milestone 1 helper endpoint:
    Advances the pipeline by one stage to test stage transitions, UI updates,
    and completion behavior on the frontend before AI pipelines are plugged in.
    """
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )

    if job.status == StatusEnum.COMPLETED:
        return job

    # Find first non-completed stage
    now = datetime.now(timezone.utc)
    target_idx = None
    for idx, stage in enumerate(job.stages):
        if stage.status != StatusEnum.COMPLETED:
            target_idx = idx
            break

    if target_idx is not None:
        # Mark previous stages completed
        for i in range(target_idx):
            job.stages[i].status = StatusEnum.COMPLETED

        current_stage = job.stages[target_idx]
        if current_stage.status == StatusEnum.PENDING:
            current_stage.status = StatusEnum.IN_PROGRESS
            current_stage.started_at = now
            current_stage.detail = f"Processing {current_stage.name}..."
            job.status = StatusEnum.IN_PROGRESS
            job.current_stage = current_stage.name
            job.progress_percentage = int(((target_idx + 0.5) / len(job.stages)) * 100)
        elif current_stage.status == StatusEnum.IN_PROGRESS:
            current_stage.status = StatusEnum.COMPLETED
            current_stage.completed_at = now
            current_stage.detail = f"Completed {current_stage.name} successfully."
            job.progress_percentage = int(((target_idx + 1) / len(job.stages)) * 100)

            # Check if there is a next stage
            if target_idx + 1 < len(job.stages):
                next_stage = job.stages[target_idx + 1]
                next_stage.status = StatusEnum.IN_PROGRESS
                next_stage.started_at = now
                next_stage.detail = f"Starting {next_stage.name}..."
                job.current_stage = next_stage.name
            else:
                job.status = StatusEnum.COMPLETED
                job.current_stage = "All stages completed"
                job.progress_percentage = 100
                job.result = VideoResult(
                    repo_name=job.repo_name,
                    repo_url=job.repo_url,
                    description=f"Automated educational walkthrough for {job.repo_name}.",
                    tech_stack=["React", "FastAPI", "Python", "Tailwind CSS"],
                    summary=f"This video breaks down the architecture, modules, and data flow of {job.repo_name}.",
                    video_url="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
                    duration_seconds=180,
                )

    job_store.update_job(job)
    return job
