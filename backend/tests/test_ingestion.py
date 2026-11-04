"""
Unit tests for the repository ingestion service.
"""
import concurrent.futures
from pathlib import Path
from unittest.mock import MagicMock, patch
import git
import pytest
from app.services.repo.ingest import (
    CloneExecutionError,
    CloneTimeoutError,
    DestinationExistsError,
    IngestionResult,
    RepoIngestionService,
    RepositorySizeExceededError,
)

@pytest.fixture
def temp_service(tmp_path):
    """Provides a RepoIngestionService pointing to a test-isolated temporary directory."""
    return RepoIngestionService(repos_base_path=tmp_path)

def test_successful_clone(temp_service, tmp_path):
    job_id = "test-job-success"

    def fake_clone(url, to_path, **kwargs):
        dest = Path(to_path)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.py").write_text("print('hello world')")
        (dest / "README.md").write_text("# Test Repo")
        return MagicMock()

    with patch("git.Repo.clone_from", side_effect=fake_clone):
        result = temp_service.ingest_repository(
            job_id=job_id,
            clone_url="https://github.com/fastapi/fastapi.git",
        )

        assert isinstance(result, IngestionResult)
        assert result.job_id == job_id
        assert result.file_count == 2
        assert result.size_bytes > 0
        assert Path(result.local_path).exists()
        assert (Path(result.local_path) / "main.py").exists()

def test_clone_failure_cleans_up(temp_service, tmp_path):
    job_id = "test-job-failure"
    dest_path = temp_service.get_job_repo_path(job_id)

    def failing_clone(url, to_path, **kwargs):
        dest = Path(to_path)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "partial.tmp").write_text("incomplete data")
        raise git.exc.GitCommandError(
            command=["git", "clone"],
            status=128,
            stderr="fatal: remote error: repository not found",
        )

    with patch("git.Repo.clone_from", side_effect=failing_clone):
        with pytest.raises(CloneExecutionError) as exc:
            temp_service.ingest_repository(
                job_id=job_id,
                clone_url="https://github.com/owner/missing.git",
            )

        assert "not found" in str(exc.value).lower()
        # Ensure cleanup removed partial directory
        assert not dest_path.exists()

def test_inaccessible_repository(temp_service):
    job_id = "test-job-auth-fail"

    def auth_failed_clone(url, to_path, **kwargs):
        raise git.exc.GitCommandError(
            command=["git", "clone"],
            status=128,
            stderr="fatal: Authentication failed for 'https://github.com/private/repo.git'",
        )

    with patch("git.Repo.clone_from", side_effect=auth_failed_clone):
        with pytest.raises(CloneExecutionError) as exc:
            temp_service.ingest_repository(
                job_id=job_id,
                clone_url="https://github.com/private/repo.git",
            )
        assert "not found, is private, or requires authentication" in str(exc.value)

def test_existing_destination_directory_rejected(temp_service):
    job_id = "test-job-existing"
    dest_path = temp_service.get_job_repo_path(job_id)
    dest_path.mkdir(parents=True, exist_ok=True)
    (dest_path / "existing.file").write_text("already here")

    with pytest.raises(DestinationExistsError) as exc:
        temp_service.ingest_repository(
            job_id=job_id,
            clone_url="https://github.com/fastapi/fastapi.git",
        )
    assert "already exists" in str(exc.value)

def test_clone_timeout_handling(temp_service):
    job_id = "test-job-timeout"
    dest_path = temp_service.get_job_repo_path(job_id)

    with patch("concurrent.futures.Future.result", side_effect=concurrent.futures.TimeoutError):
        with pytest.raises(CloneTimeoutError) as exc:
            temp_service.ingest_repository(
                job_id=job_id,
                clone_url="https://github.com/fastapi/fastapi.git",
            )
        assert "timed out" in str(exc.value)
        assert not dest_path.exists()

def test_repository_size_limit_exceeded(temp_service):
    job_id = "test-job-large"
    dest_path = temp_service.get_job_repo_path(job_id)

    def oversized_clone(url, to_path, **kwargs):
        dest = Path(to_path)
        dest.mkdir(parents=True, exist_ok=True)
        # Create a dummy file that claims to be very large via mocking stat
        (dest / "bigfile.dat").write_bytes(b"x" * 1024)
        return MagicMock()

    with patch("git.Repo.clone_from", side_effect=oversized_clone):
        # Temporarily mock MAX_REPO_SIZE_MB to 0 MB (so any byte exceeds limit)
        with patch("app.services.repo.ingest.settings.MAX_REPO_SIZE_MB", 0.0001):
            with pytest.raises(RepositorySizeExceededError) as exc:
                temp_service.ingest_repository(
                    job_id=job_id,
                    clone_url="https://github.com/fastapi/fastapi.git",
                )
            assert "exceeds maximum allowed limit" in str(exc.value)
            # Ensure cleanup removed the directory
            assert not dest_path.exists()
