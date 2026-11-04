"""Job storage service."""
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from ...models.schemas import (
    JobResponse,
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

class JobStore:
    def __init__(self):
        self._jobs: Dict[str, JobResponse] = {}

    def create_job(self, repo_url: str, repo_name: str) -> JobResponse:
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
        job = JobResponse(
            job_id=job_id,
            repo_url=repo_url,
            repo_name=repo_name,
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
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[JobResponse]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def update_job(self, job: JobResponse) -> JobResponse:
        job.updated_at = datetime.now(timezone.utc)
        self._jobs[job.job_id] = job
        return job

job_store = JobStore()
