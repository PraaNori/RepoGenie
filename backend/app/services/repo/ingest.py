"""
Repository Ingestion Service for cloning and managing local repository workspaces.
"""
import concurrent.futures
import os
import shutil
import time
from pathlib import Path
from typing import Optional
import git
from pydantic import BaseModel
from ...core.config import settings

class RepoIngestionError(Exception):
    """Base exception for repository ingestion failures."""
    pass

class DestinationExistsError(RepoIngestionError):
    """Raised when the target destination directory already exists."""
    pass

class CloneTimeoutError(RepoIngestionError):
    """Raised when repository cloning exceeds the configured timeout."""
    pass

class RepositorySizeExceededError(RepoIngestionError):
    """Raised when the cloned repository exceeds the maximum allowed size."""
    pass

class CloneExecutionError(RepoIngestionError):
    """Raised when a Git command execution or network connection fails."""
    pass

class IngestionResult(BaseModel):
    job_id: str
    local_path: str
    file_count: int
    size_bytes: int
    size_mb: float
    clone_duration_seconds: float

class RepoIngestionService:
    def __init__(self, repos_base_path: Optional[Path] = None):
        self._repos_base = repos_base_path or settings.repos_path

    def get_job_repo_path(self, job_id: str) -> Path:
        """Returns the isolated destination path for a given job ID."""
        return self._repos_base / job_id

    def ingest_repository(self, job_id: str, clone_url: str) -> IngestionResult:
        """
        Clones a public repository into an isolated local directory for the job.

        Enforces:
        - Unique, non-overlapping destination directory per job ID.
        - Configured clone timeout duration.
        - Configured maximum repository size limit.
        - Automatic cleanup of incomplete files on failure.
        - Safe shallow cloning (--depth=1) without code execution.

        Returns:
            IngestionResult with path, file count, and size metrics.

        Raises:
            DestinationExistsError
            CloneTimeoutError
            RepositorySizeExceededError
            CloneExecutionError
            RepoIngestionError
        """
        dest_dir = self.get_job_repo_path(job_id)

        # 1. Check if destination already exists
        if dest_dir.exists():
            raise DestinationExistsError(
                f"Destination directory for job '{job_id}' already exists: {dest_dir}"
            )

        start_time = time.time()
        timeout = settings.CLONE_TIMEOUT_SECONDS

        # 2. Execute Git clone with timeout enforcement
        def _execute_clone():
            # Safe Git clone: shallow depth, unsafe protocols/options disabled
            return git.Repo.clone_from(
                clone_url,
                str(dest_dir),
                depth=settings.CLONE_DEPTH,
                allow_unsafe_protocols=False,
                allow_unsafe_options=False,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_execute_clone)
            try:
                future.result(timeout=timeout)
            except concurrent.futures.TimeoutError as exc:
                self.cleanup_directory(dest_dir)
                raise CloneTimeoutError(
                    f"Cloning '{clone_url}' timed out after {timeout} seconds."
                ) from exc
            except git.exc.GitCommandError as exc:
                self.cleanup_directory(dest_dir)
                stderr = exc.stderr if hasattr(exc, "stderr") and exc.stderr else str(exc)
                if "Repository not found" in stderr or "Authentication failed" in stderr or "terminal prompts disabled" in stderr:
                    raise CloneExecutionError(
                        f"Repository '{clone_url}' not found, is private, or requires authentication."
                    ) from exc
                raise CloneExecutionError(
                    f"Git error while cloning repository '{clone_url}': {stderr.strip()}"
                ) from exc
            except Exception as exc:
                self.cleanup_directory(dest_dir)
                raise RepoIngestionError(
                    f"Unexpected error while ingesting repository '{clone_url}': {exc}"
                ) from exc

        duration = time.time() - start_time

        # 3. Enforce repository size limit & file metrics
        try:
            total_bytes = 0
            file_count = 0
            for item in dest_dir.rglob("*"):
                if item.is_file() and not item.is_symlink():
                    file_count += 1
                    total_bytes += item.stat().st_size

            size_mb = total_bytes / (1024 * 1024)

            if size_mb > settings.MAX_REPO_SIZE_MB:
                self.cleanup_directory(dest_dir)
                raise RepositorySizeExceededError(
                    f"Repository size ({size_mb:.2f} MB) exceeds maximum allowed limit of {settings.MAX_REPO_SIZE_MB} MB."
                )

            return IngestionResult(
                job_id=job_id,
                local_path=str(dest_dir.resolve()),
                file_count=file_count,
                size_bytes=total_bytes,
                size_mb=round(size_mb, 2),
                clone_duration_seconds=round(duration, 2),
            )
        except Exception:
            # Re-raise if it was RepositorySizeExceededError
            if not dest_dir.exists():
                raise
            self.cleanup_directory(dest_dir)
            raise

    def cleanup_directory(self, path: Path) -> None:
        """Safely cleans up an incomplete or failed repository directory."""
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

repo_ingestion_service = RepoIngestionService()
