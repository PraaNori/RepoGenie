"""
Tests for Milestone 3.5.1: Backend API, JobStore, and Workflow Understanding Integration.

Covers:
1. JobStore workflow understanding storage, retrieval, isolation, and summary response.
2. Workflow understanding API endpoints (POST / GET / 404 / 409 prerequisites / caching).
3. Concurrency serialization per job and independent execution across different jobs.
4. Pipeline compatibility (preserving Stage 4, Stage 5 pending, and 9-stage pipeline schema).
5. Sanitized error handling without path leakage.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitectureAnalysisResult,
    DirectoryTreeNode,
    ParsedRepository,
    RepoAnalysisResult,
    RepoStatistics,
    RepositoryKnowledge,
    StageEnum,
    StatusEnum,
)
from app.services.ai.exceptions import AIError, AITimeoutError
from app.services.ai.project_understanding import (
    ProjectUnderstanding,
    project_understanding_analyzer,
)
from app.services.ai.code_understanding import (
    RepositoryCodeUnderstanding,
    code_understanding_analyzer,
)
from app.services.ai.workflow_understanding import (
    ApplicationWorkflow,
    RepositoryWorkflowUnderstanding,
    WorkflowComponentReference,
    WorkflowStep,
    workflow_understanding_analyzer,
)
from app.services.repo.architecture_analyzer import (
    call_graph_builder,
    dependency_resolver,
)
from app.services.storage.job_store import PIPELINE_STAGES, job_store
from tests.test_workflow_understanding import _create_mock_knowledge_for_phase3

client = TestClient(app)


def _create_sample_workflow_understanding(repo_name: str = "test/integration_app") -> RepositoryWorkflowUnderstanding:
    step = WorkflowStep(
        step_number=1,
        title="Start Workflow",
        component_id="app/main.py",
        symbol_name="start_app",
        action_type="call",
        description="Entry call",
        runtime_execution_verified=False,
    )
    wf = ApplicationWorkflow(
        workflow_id="wf_sample",
        name="Main Workflow",
        description="Core sample workflow",
        trigger="HTTP POST",
        entry_point=WorkflowComponentReference(component_id="app/main.py", name="start_app", role_in_workflow="entry"),
        steps=[step],
        final_outcome="Processed successfully",
        runtime_execution_verified=False,
    )
    return RepositoryWorkflowUnderstanding(
        schema_version="1.0",
        repository_name=repo_name,
        system_architecture_type="modular_monolith",
        workflow_summary="Integration test summary",
        workflows=[wf],
        structural_call_chains=[],
        provider="mock_gemini",
        model="gemini-2.5-pro",
        is_fallback=False,
    )


def _setup_eligible_job(job_id: str, local_path: str = "/tmp/repos/test_repo"):
    knowledge = _create_mock_knowledge_for_phase3()
    job = job_store.create_job(
        repo_url="https://github.com/test/integration_app",
        repo_name="integration_app",
        repository_owner="test",
        repository_name="integration_app",
        clone_url="https://github.com/test/integration_app.git",
    )
    # Align job_id if specific ID requested
    if job.job_id != job_id:
        job_store._jobs.pop(job.job_id, None)
        job.job_id = job_id
        job_store._jobs[job_id] = job

    now = datetime.now(timezone.utc)
    # Stage 0: Completed with local path
    job.local_path = local_path
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[0].completed_at = now

    # Stage 1: Completed with analysis
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[1].completed_at = now
    job.analysis = RepoAnalysisResult(
        repository_name="test/integration_app",
        directory_tree=DirectoryTreeNode(name="root", path="", type="directory", children=[]),
        statistics=RepoStatistics(
            total_files=5, total_directories=1, source_files=3, filtered_files=2,
            total_size_bytes=1000, configuration_files=0, dependency_manifests=0,
            recognized_languages_count=1,
        ),
        languages=[], dependency_files=[], configuration_files=[],
        analysis_status=StatusEnum.COMPLETED, warnings=[],
    )

    # Stage 2: Completed with code analysis, architecture (with CallGraph), and knowledge
    job.stages[2].status = StatusEnum.COMPLETED
    job.stages[2].completed_at = now
    job.code_analysis = ParsedRepository(
        job_id=job_id,
        repository_name="test/integration_app",
        total_parsed_files=len(knowledge.code_structure.files),
        total_functions=1,
        total_classes=0,
        total_methods=0,
        total_imports=1,
        total_function_calls=1,
        supported_languages=["python"],
        files=knowledge.code_structure.files,
    )
    job.architecture = ArchitectureAnalysisResult(
        job_id=job_id,
        repository_name="test/integration_app",
        dependency_graph=dependency_resolver.build_dependency_graph([], set()),
        call_graph=knowledge.architecture.call_graph,
        inheritance_relationships=[],
    )
    job.knowledge = knowledge
    job_store.update_job(job)
    return job


# ===========================================================================
# 1. JobStore Integration Tests
# ===========================================================================

def test_job_store_workflow_understanding_storage_and_retrieval():
    """JobStore stores complete WorkflowUnderstanding and retrieves it accurately."""
    job_a = _setup_eligible_job("job_store_a")
    wf_sample = _create_sample_workflow_understanding("test/store_a")

    # Initial state
    assert job_store.get_job_workflow_understanding("job_store_a") is None
    assert job_a.to_response().has_workflow_understanding is False

    # Store workflow understanding
    updated_a = job_store.update_job_workflow_understanding_success("job_store_a", wf_sample)
    assert updated_a is not None
    assert updated_a.workflow_understanding is not None
    assert updated_a.workflow_understanding.repository_name == "test/store_a"

    # Retrieve via getter
    retrieved = job_store.get_job_workflow_understanding("job_store_a")
    assert retrieved is not None
    assert retrieved.repository_name == "test/store_a"
    assert len(retrieved.workflows) == 1

    # Response model exposes boolean flag
    resp = job_a.to_response()
    assert resp.has_workflow_understanding is True


def test_job_store_workflow_understanding_isolated_per_job():
    """Different jobs maintain isolated workflow understanding results."""
    job_a = _setup_eligible_job("job_iso_a")
    job_b = _setup_eligible_job("job_iso_b")

    wf_a = _create_sample_workflow_understanding("test/iso_a")
    job_store.update_job_workflow_understanding_success("job_iso_a", wf_a)

    # Job A has result; Job B remains None
    assert job_store.get_job_workflow_understanding("job_iso_a") is not None
    assert job_store.get_job_workflow_understanding("job_iso_b") is None
    assert job_a.to_response().has_workflow_understanding is True
    assert job_b.to_response().has_workflow_understanding is False


def test_job_store_preserves_existing_project_and_code_understanding():
    """Workflow understanding does not overwrite or erase project or code understanding."""
    job = _setup_eligible_job("job_preserve_all")

    # Pre-populate project understanding
    proj_und = project_understanding_analyzer.create_rule_based_fallback(job.knowledge)
    job.project_understanding = proj_und

    # Pre-populate code understanding
    code_und = code_understanding_analyzer.create_rule_based_fallback(job.knowledge, project_understanding=proj_und)
    job.code_understanding = code_und
    job_store.update_job(job)

    # Now update workflow understanding
    wf_sample = _create_sample_workflow_understanding("test/integration_app")
    job_store.update_job_workflow_understanding_success("job_preserve_all", wf_sample)

    internal = job_store.get_internal_job("job_preserve_all")
    assert internal.project_understanding is not None
    assert internal.code_understanding is not None
    assert internal.workflow_understanding is not None
    assert internal.workflow_understanding.workflow_summary == "Integration test summary"

    resp = internal.to_response()
    assert resp.has_code_understanding is True
    assert resp.has_workflow_understanding is True
    assert resp.project_understanding is not None


# ===========================================================================
# 2. API Route Tests
# ===========================================================================

def test_api_workflow_understanding_unknown_job_404():
    """GET and POST for unknown job ID return 404 Not Found."""
    get_resp = client.get("/api/v1/jobs/non-existent-job-uuid/workflow-understanding")
    assert get_resp.status_code == 404
    assert "not found" in get_resp.json()["detail"].lower()

    post_resp = client.post("/api/v1/jobs/non-existent-job-uuid/workflow-understanding")
    assert post_resp.status_code == 404
    assert "not found" in post_resp.json()["detail"].lower()


def test_api_workflow_understanding_get_404_before_generation():
    """GET returns 404 when workflow understanding has not yet been generated."""
    job = _setup_eligible_job("job_get_not_generated")
    resp = client.get(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
    assert resp.status_code == 404
    assert "has not yet been generated" in resp.json()["detail"]


def test_api_workflow_understanding_prerequisites_409_missing_ingestion():
    """POST returns 409 when repository ingestion is not completed or local_path is missing."""
    job = job_store.create_job(
        repo_url="https://github.com/test/uncloned",
        repo_name="uncloned",
        repository_owner="test",
        repository_name="uncloned",
        clone_url="https://github.com/test/uncloned.git",
    )
    job.stages[0].status = StatusEnum.PENDING
    job.local_path = None
    job_store.update_job(job)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
    assert resp.status_code == 409
    assert "Repository ingestion must be completed first" in resp.json()["detail"]


def test_api_workflow_understanding_prerequisites_409_missing_analysis():
    """POST returns 409 when repository structure analysis (Stage 1) is not completed."""
    job = _setup_eligible_job("job_missing_analysis")
    job.stages[1].status = StatusEnum.PENDING
    job.analysis = None
    job_store.update_job(job)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
    assert resp.status_code == 409
    assert "Repository structure analysis must be completed first" in resp.json()["detail"]


def test_api_workflow_understanding_prerequisites_409_missing_code_analysis():
    """POST returns 409 when parsed code structure is missing."""
    job = _setup_eligible_job("job_missing_code_analysis")
    job.code_analysis = None
    job_store.update_job(job)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
    assert resp.status_code == 409
    assert "Parsed code structure is required" in resp.json()["detail"]


def test_api_workflow_understanding_prerequisites_409_missing_architecture_or_callgraph():
    """POST returns 409 when architecture analysis or CallGraph is missing."""
    job = _setup_eligible_job("job_missing_arch")
    job.architecture = None
    job_store.update_job(job)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
    assert resp.status_code == 409
    assert "Architecture analysis and directional CallGraph are required" in resp.json()["detail"]


def test_api_workflow_understanding_prerequisites_409_missing_knowledge():
    """POST returns 409 when repository knowledge consolidation is missing."""
    job = _setup_eligible_job("job_missing_knowledge")
    job.knowledge = None
    job.stages[2].status = StatusEnum.PENDING
    job_store.update_job(job)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
    assert resp.status_code == 409
    assert "Repository knowledge consolidation must be completed first" in resp.json()["detail"]


def test_api_workflow_understanding_post_success_and_get_cached():
    """POST generates workflow understanding, caches it, and GET returns cached result."""
    job = _setup_eligible_job("job_post_success")
    wf_sample = _create_sample_workflow_understanding("test/integration_app")

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = wf_sample

        # 1. POST to generate
        post_resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert post_resp.status_code == 200
        data = post_resp.json()
        assert data["repository_name"] == "test/integration_app"
        assert len(data["workflows"]) == 1
        assert mock_analyze.call_count == 1

        # 2. Verify JobResponse flag
        job_resp = client.get(f"/api/v1/jobs/{job.job_id}")
        assert job_resp.status_code == 200
        assert job_resp.json()["has_workflow_understanding"] is True

        # 3. GET to retrieve cached
        get_resp = client.get(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert get_resp.status_code == 200
        assert get_resp.json()["repository_name"] == "test/integration_app"

        # 4. Subsequent POST without refresh returns cached without calling analyzer
        post_cached = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert post_cached.status_code == 200
        assert mock_analyze.call_count == 1  # Unchanged!

        # 5. Subsequent POST with refresh=True re-invokes analyzer
        post_refresh = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding?refresh=true")
        assert post_refresh.status_code == 200
        assert mock_analyze.call_count == 2


def test_api_workflow_understanding_optional_code_understanding_absent():
    """Workflow understanding succeeds when optional CodeUnderstanding is absent."""
    job = _setup_eligible_job("job_optional_cu_absent")
    job.code_understanding = None
    job.project_understanding = None
    job_store.update_job(job)

    wf_sample = _create_sample_workflow_understanding("test/integration_app")

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = wf_sample

        resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert resp.status_code == 200
        assert resp.json()["repository_name"] == "test/integration_app"
        # Verify kwargs passed to analyzer
        mock_analyze.assert_called_once()
        call_kwargs = mock_analyze.call_args.kwargs
        assert call_kwargs["code_understanding"] is None
        assert call_kwargs["project_understanding"] is None


def test_api_workflow_understanding_provider_error_and_no_path_leak():
    """Provider AIError returns appropriate status with sanitized message and no local path leak."""
    secret_path = "/Users/pradeepikanori/secret/disk/repo"
    job = _setup_eligible_job("job_err_path_leak", local_path=secret_path)

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = AIError(
            f"Model failed processing file at {secret_path}/app/main.py",
            provider="mock_gemini",
            status_code=503,
        )

        resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "AI workflow understanding failed" in detail
        assert secret_path not in detail
        assert "<REPO_ROOT>" in detail


def test_api_workflow_understanding_unexpected_exception_sanitized_no_path_leak():
    """Unexpected exception returns 500 with sanitized detail and no local path leak."""
    secret_path = "/private/var/folders/secret_repo"
    job = _setup_eligible_job("job_unexp_err", local_path=secret_path)

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = ValueError(f"Crash in parser at {secret_path}/file.py")

        resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "Unexpected error during workflow understanding" in detail
        assert secret_path not in detail
        assert "<REPO_ROOT>" in detail


# ===========================================================================
# 3. Concurrency Tests
# ===========================================================================

@pytest.mark.anyio
async def test_concurrent_workflow_understanding_same_job_serialized():
    """Concurrent requests for the same job are serialized; analyzer runs exactly once."""
    from app.api.routes.jobs import generate_job_workflow_understanding

    job = _setup_eligible_job("job_concurrent_same")
    wf_sample = _create_sample_workflow_understanding("test/concurrent_app")

    execution_count = 0

    async def mock_analyze_slow(*args, **kwargs):
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)
        return wf_sample

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=mock_analyze_slow):
        task1 = generate_job_workflow_understanding(job_id=job.job_id, provider=None, refresh=False)
        task2 = generate_job_workflow_understanding(job_id=job.job_id, provider=None, refresh=False)
        res1, res2 = await asyncio.gather(task1, task2)

        assert res1.repository_name == "test/concurrent_app"
        assert res2.repository_name == "test/concurrent_app"
        # Analyzer called exactly once due to atomic per-job locking
        assert execution_count == 1


@pytest.mark.anyio
async def test_concurrent_workflow_understanding_different_jobs_independent():
    """Requests for different jobs execute independently without blocking each other."""
    from app.api.routes.jobs import generate_job_workflow_understanding

    job_1 = _setup_eligible_job("job_concurrent_diff_1")
    job_2 = _setup_eligible_job("job_concurrent_diff_2")

    wf_1 = _create_sample_workflow_understanding("test/job_1")
    wf_2 = _create_sample_workflow_understanding("test/job_2")

    active_executions = 0
    max_simultaneous = 0

    async def mock_analyze(job_id, *args, **kwargs):
        nonlocal active_executions, max_simultaneous
        active_executions += 1
        if active_executions > max_simultaneous:
            max_simultaneous = active_executions
        await asyncio.sleep(0.05)
        active_executions -= 1
        return wf_1 if job_id == "job_concurrent_diff_1" else wf_2

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=mock_analyze):
        task1 = generate_job_workflow_understanding(job_id="job_concurrent_diff_1", provider=None, refresh=False)
        task2 = generate_job_workflow_understanding(job_id="job_concurrent_diff_2", provider=None, refresh=False)
        res1, res2 = await asyncio.gather(task1, task2)

        assert res1.repository_name == "test/job_1"
        assert res2.repository_name == "test/job_2"
        # Both jobs ran simultaneously because they have distinct per-job locks
        assert max_simultaneous == 2


@pytest.mark.anyio
async def test_workflow_understanding_lock_released_on_failure():
    """Per-job lock is released when an analyzer call fails, allowing subsequent retry."""
    from app.api.routes.jobs import generate_job_workflow_understanding
    from fastapi import HTTPException

    job = _setup_eligible_job("job_lock_release_retry")
    wf_sample = _create_sample_workflow_understanding("test/retry_app")

    # 1. First attempt fails
    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = AIError("Temporary timeout", provider="mock", status_code=504)
        with pytest.raises(HTTPException) as exc_info:
            await generate_job_workflow_understanding(job_id=job.job_id, provider=None, refresh=False)
        assert exc_info.value.status_code == 504

    # 2. Second attempt acquires the lock cleanly and succeeds
    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = wf_sample
        result = await generate_job_workflow_understanding(job_id=job.job_id, provider=None, refresh=False)
        assert result.repository_name == "test/retry_app"
        mock_analyze.assert_called_once()


# ===========================================================================
# 4. Pipeline Compatibility Tests
# ===========================================================================

def test_pipeline_compatibility_stage_4_completed_and_stage_5_pending():
    """Workflow understanding preserves Stage 4 completed status and keeps Stage 5 pending."""
    job = _setup_eligible_job("job_pipe_compat")
    # Simulate job at Stage 4 completed
    now = datetime.now(timezone.utc)
    job.current_stage = PIPELINE_STAGES[4]  # Stage 5 is next
    job.stages[3].status = StatusEnum.COMPLETED
    job.stages[3].completed_at = now
    job.stages[4].status = StatusEnum.PENDING
    job_store.update_job(job)

    wf_sample = _create_sample_workflow_understanding("test/pipe_compat")

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = wf_sample

        resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert resp.status_code == 200

    internal = job_store.get_internal_job("job_pipe_compat")
    assert len(internal.stages) == 9
    assert internal.stages[3].name == StageEnum.AI_SUMMARY.value
    assert internal.stages[3].status == StatusEnum.COMPLETED
    assert internal.stages[4].name == StageEnum.SCRIPT_GENERATION.value
    assert internal.stages[4].status == StatusEnum.PENDING
    assert internal.workflow_understanding is not None


def test_pipeline_compatibility_workflow_failure_does_not_erase_project_or_code_understanding():
    """Workflow understanding failure does not erase previously completed project or code understanding."""
    job = _setup_eligible_job("job_fail_preserve_prior")

    proj_und = project_understanding_analyzer.create_rule_based_fallback(job.knowledge)
    code_und = code_understanding_analyzer.create_rule_based_fallback(job.knowledge, project_understanding=proj_und)
    job.project_understanding = proj_und
    job.code_understanding = code_und
    now = datetime.now(timezone.utc)
    job.stages[3].status = StatusEnum.COMPLETED
    job.stages[3].completed_at = now
    job_store.update_job(job)

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.side_effect = AIError("Model failure", provider="mock", status_code=500)

        resp = client.post(f"/api/v1/jobs/{job.job_id}/workflow-understanding")
        assert resp.status_code == 500

    internal = job_store.get_internal_job("job_fail_preserve_prior")
    assert internal.project_understanding is not None
    assert internal.code_understanding is not None
    assert internal.workflow_understanding is None
    assert internal.stages[3].status == StatusEnum.COMPLETED
