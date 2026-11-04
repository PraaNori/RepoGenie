"""Tests for job submission and validation."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_job_invalid_url():
    response = client.post("/api/v1/jobs", json={"github_url": "not-a-valid-url"})
    assert response.status_code == 422
    assert "Invalid GitHub repository URL" in response.json()["detail"]

def test_create_job_valid_url():
    response = client.post(
        "/api/v1/jobs",
        json={"github_url": "https://github.com/facebook/react"}
    )
    assert response.status_code == 201
    data = response.json()
    assert "job_id" in data
    assert data["repo_name"] == "facebook/react"
    assert data["status"] == "pending"
    assert len(data["stages"]) == 9
    assert data["stages"][0]["name"] == "Repository Fetching"

    job_id = data["job_id"]
    get_res = client.get(f"/api/v1/jobs/{job_id}")
    assert get_res.status_code == 200
    assert get_res.json()["job_id"] == job_id
