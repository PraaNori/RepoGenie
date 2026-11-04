"""Tests for job submission and validation."""
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
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

def test_create_job_valid_url():
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

            job_id = data["job_id"]
            get_res = client.get(f"/api/v1/jobs/{job_id}")
            assert get_res.status_code == 200
            assert get_res.json()["job_id"] == job_id
            # Notice local_path should NOT be in public response
            assert "local_path" not in get_res.json()
