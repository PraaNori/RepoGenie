"""Tests for job submission, validation, and repository analysis integration."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import (
    DirectoryTreeNode,
    RepoAnalysisResult,
    RepoStatistics,
    StatusEnum,
)
from app.services.repo.ingest import IngestionResult

client = TestClient(app)

def test_create_job_invalid_url():
    response = client.post("/api/v1/jobs", json={"github_url": "not-a-valid-url"})
    assert response.status_code == 422
    assert "Unsupported URL protocol" in response.json()["detail"] or "Not a GitHub" in response.json()["detail"]

def test_create_job_non_github_url():
    response = client.post("/api/v1/jobs", json={"github_url": "https://gitlab.com/owner/repo"})
    assert response.status_code == 422
    assert "Not a GitHub repository URL" in response.json()["detail"]

def test_create_job_profile_url():
    response = client.post("/api/v1/jobs", json={"github_url": "https://github.com/torvalds"})
    assert response.status_code == 422
    assert "profile or organization without a repository" in response.json()["detail"]

def test_create_job_nonexistent_repo():
    with patch("app.api.routes.jobs.verify_repository_accessible") as mock_verify:
        from app.utils.github_url import RepositoryNotFoundError
        mock_verify.side_effect = RepositoryNotFoundError("Repository not found")

        response = client.post(
            "/api/v1/jobs",
            json={"github_url": "https://github.com/nonexistent/repo"}
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

def test_create_job_valid_url_and_analysis_pipeline():
    dummy_analysis = RepoAnalysisResult(
        repository_name="facebook/react",
        directory_tree=DirectoryTreeNode(name="react", path="", type="directory", children=[]),
        statistics=RepoStatistics(
            total_files=50,
            total_directories=5,
            source_files=40,
            filtered_files=10,
            total_size_bytes=50000,
            configuration_files=3,
            dependency_manifests=1,
            recognized_languages_count=2,
        ),
        languages=[],
        dependency_files=[],
        configuration_files=[],
        analysis_status=StatusEnum.COMPLETED,
        warnings=[],
    )

    with patch("app.api.routes.jobs.verify_repository_accessible", return_value=True):
        with patch("app.api.routes.jobs.repo_ingestion_service.ingest_repository") as mock_ingest:
            mock_ingest.return_value = IngestionResult(
                job_id="test-id",
                local_path="/tmp/test-repo",
                file_count=10,
                size_bytes=1024,
                size_mb=0.01,
                clone_duration_seconds=1.2,
            )
            with patch("app.api.routes.jobs.repo_analyzer_service.analyze_repository", return_value=dummy_analysis):
                response = client.post(
                    "/api/v1/jobs",
                    json={"github_url": "https://github.com/facebook/react"}
                )
                assert response.status_code == 201
                data = response.json()
                assert "job_id" in data
                assert data["repo_name"] == "facebook/react"
                assert data["repository_owner"] == "facebook"
                assert data["repository_name"] == "react"
                assert data["clone_url"] == "https://github.com/facebook/react.git"
                assert len(data["stages"]) == 9
                assert data["stages"][0]["name"] == "Repository Fetching"
                assert data["stages"][1]["name"] == "Repository Analysis"

                job_id = data["job_id"]
                get_res = client.get(f"/api/v1/jobs/{job_id}")
                assert get_res.status_code == 200
                res_data = get_res.json()
                assert res_data["job_id"] == job_id
                # In TestClient, background tasks finish before post returns
                assert res_data["stages"][0]["status"] == "completed"
                assert res_data["stages"][1]["status"] == "completed"
                assert res_data["analysis"] is not None
                assert "local_path" not in res_data

                # Test analysis endpoint
                analysis_res = client.get(f"/api/v1/jobs/{job_id}/analysis")
                assert analysis_res.status_code == 200
                analysis_data = analysis_res.json()
                assert analysis_data["repository_name"] == "facebook/react"
                assert analysis_data["statistics"]["source_files"] == 40

def test_get_analysis_job_not_found():
    response = client.get("/api/v1/jobs/nonexistent-job-id/analysis")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_job_survives_backend_restart_and_store_reinitialization(tmp_path):
    """
    Verifies that jobs created in JobStore are durably persisted to disk
    and remain fully accessible after a backend restart / JobStore reinitialization.
    """
    from app.services.storage.job_store import job_store, JobStore

    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job_id = job.job_id

    # Verify initially accessible
    res = client.get(f"/api/v1/jobs/{job_id}")
    assert res.status_code == 200
    assert res.json()["job_id"] == job_id

    # Simulate backend restart: instantiate a completely new JobStore instance
    fresh_store = JobStore()
    rehydrated = fresh_store.get_internal_job(job_id)
    assert rehydrated is not None
    assert rehydrated.job_id == job_id
    assert rehydrated.repo_name == "click"

    # API endpoint also retrieves rehydrated job
    res_after = client.get(f"/api/v1/jobs/{job_id}")
    assert res_after.status_code == 200
    assert res_after.json()["job_id"] == job_id


def test_script_generation_prerequisite_validation_and_job_preservation():
    """
    Verifies that script generation endpoint locates the job in JobStore,
    validates prerequisites, and does not return 404 for existing jobs.
    """
    from app.services.storage.job_store import job_store

    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job_id = job.job_id

    # Calling script generation on an uningested job returns 409 Conflict, NOT 404 Not Found!
    res = client.post(f"/api/v1/jobs/{job_id}/educational-script")
    assert res.status_code == 409
    assert "ingestion must be completed first" in res.json()["detail"]
