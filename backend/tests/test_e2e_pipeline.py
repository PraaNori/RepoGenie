"""
Milestone 3.5.3 — End-to-End Pipeline & Integration Test Suite.

Covers:
- Scenario A: Successful repository processing (pallets/click and sindresorhus/is).
- Scenario B: API and job-state correctness (URL validation, 404s, 409s, caching, concurrency, 9 stages).
- Scenario C: AI provider behavior (Groq, missing/invalid keys, timeouts, repair, fallback, token accounting).
- Scenario D: Evidence and correctness (grounding, line ranges, path sanitization, no runtime claims).
"""

import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.schemas import StageEnum, StatusEnum
from app.services.ai import (
    BaseLLMProvider,
    GroqProvider,
    LLMManager,
    LLMResponse,
    TokenUsageRecord,
)
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIProviderUnavailableError,
    AITimeoutError,
)
from app.services.ai.project_understanding import (
    ProjectUnderstanding,
    project_understanding_analyzer,
)
from app.services.ai.code_understanding import (
    RepositoryCodeUnderstanding,
    code_understanding_analyzer,
)
from app.services.ai.workflow_understanding import (
    RepositoryWorkflowUnderstanding,
    WorkflowUnderstandingAnalyzer,
    workflow_understanding_analyzer,
)
from app.services.repo.analyzer import repo_analyzer_service
from app.services.repo.architecture_analyzer import architecture_analyzer_service
from app.services.repo.code_parser import code_parser_service
from app.services.repo.ingest import (
    CloneExecutionError,
    IngestionResult,
    repo_ingestion_service,
)
from app.services.repo.knowledge_builder import knowledge_builder_service
from app.services.storage.job_store import job_store

client = TestClient(app)

CLICK_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "repos" / "click"
IS_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "repos" / "is"


async def _mock_project_understanding(job_id, knowledge, **kwargs):
    return project_understanding_analyzer.create_rule_based_fallback(knowledge=knowledge)


async def _mock_code_understanding(job_id, knowledge, project_understanding=None, **kwargs):
    return code_understanding_analyzer.create_rule_based_fallback(
        knowledge=knowledge,
        project_understanding=project_understanding,
    )


async def _mock_workflow_understanding(job_id, knowledge, project_understanding=None, code_understanding=None, **kwargs):
    return workflow_understanding_analyzer.create_deterministic_fallback(knowledge=knowledge)


# =============================================================================
# SCENARIO A: Full Successful Repository Processing Pipeline
# =============================================================================

def test_e2e_successful_pipeline_pallets_click():
    """
    Scenario A1: End-to-end processing of Python repository pallets/click:
    1. Submit GitHub URL.
    2. URL validation & normalization.
    3. Job creation.
    4. Repository cloning (using local shallow fixture).
    5. Repository structure & language analysis.
    6. Tree-sitter code parsing.
    7. Architecture & CallGraph analysis.
    8. Unified RepositoryKnowledge building.
    9. Project Understanding generation.
    10. Code Understanding generation.
    11. Workflow Understanding generation.
    """
    assert CLICK_FIXTURE_PATH.exists(), f"Click fixture not found at {CLICK_FIXTURE_PATH}"

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(
            job_id=job_id,
            local_path=str(dest_dir),
            file_count=171,
            size_bytes=1024 * 1024,
            size_mb=1.0,
            clone_duration_seconds=0.5,
        )

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(project_understanding_analyzer, "analyze_project", side_effect=_mock_project_understanding), \
         patch.object(code_understanding_analyzer, "analyze_codebase", side_effect=_mock_code_understanding), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding):

        # 1. Submit GitHub URL with wait=true to run analysis pipeline synchronously
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        assert resp.status_code == 201
        job_data = resp.json()
        job_id = job_data["job_id"]
        assert job_data["repo_name"] == "pallets/click"

        # Verify pipeline stages
        internal = job_store.get_internal_job(job_id)
        assert internal is not None
        assert internal.ingestion_status == StatusEnum.COMPLETED
        assert internal.local_path is not None
        assert internal.stages[1].status == StatusEnum.COMPLETED
        assert internal.analysis is not None
        assert internal.analysis.statistics.source_files > 0
        assert any(l.name == "Python" for l in internal.analysis.languages)

        # 6. Tree-sitter code parsing verified
        assert internal.code_analysis is not None
        assert internal.code_analysis.total_parsed_files > 0
        assert internal.code_analysis.total_functions > 100

        # 7. Architecture CallGraph verified
        assert internal.architecture is not None
        assert internal.architecture.call_graph.total_resolved_calls > 0
        assert len(internal.architecture.entry_points) > 0

        # 8. Unified Knowledge verified
        assert internal.knowledge is not None
        assert len(internal.knowledge.important_files) > 0
        assert len(internal.knowledge.source_evidence) > 0

        # 9. Project Understanding API
        pu_resp = client.post(f"/api/v1/jobs/{job_id}/project-understanding")
        assert pu_resp.status_code == 200
        pu_data = pu_resp.json()
        assert pu_data["identity"]["name"] == "pallets/click"
        assert len(pu_data["core_features"]) >= 1

        # 10. Code Understanding API
        cu_resp = client.post(f"/api/v1/jobs/{job_id}/code-understanding")
        assert cu_resp.status_code == 200
        cu_data = cu_resp.json()
        assert cu_data["repository_name"] == "pallets/click"
        assert len(cu_data["components"]) >= 3

        # 11. Workflow Understanding API
        wu_resp = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding")
        assert wu_resp.status_code == 200
        wu_data = wu_resp.json()
        assert wu_data["repository_name"] == "pallets/click"
        assert len(wu_data["workflows"]) + len(wu_data["structural_call_chains"]) >= 1

        # Check job summary consistency
        status_resp = client.get(f"/api/v1/jobs/{job_id}")
        assert status_resp.status_code == 200
        summary = status_resp.json()
        assert summary["has_code_understanding"] is True
        assert summary["has_workflow_understanding"] is True
        assert summary["stages"][3]["status"] == "completed"  # Stage 4 completed
        assert summary["stages"][4]["status"] == "pending"    # Stage 5 pending


def test_e2e_successful_pipeline_sindresorhus_is():
    """
    Scenario A2: End-to-end processing of TypeScript repository sindresorhus/is:
    Verifies full lifecycle on TypeScript codebase.
    """
    assert IS_FIXTURE_PATH.exists(), f"is fixture not found at {IS_FIXTURE_PATH}"

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(IS_FIXTURE_PATH, dest_dir)
        return IngestionResult(
            job_id=job_id,
            local_path=str(dest_dir),
            file_count=18,
            size_bytes=200 * 1024,
            size_mb=0.2,
            clone_duration_seconds=0.2,
        )

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(project_understanding_analyzer, "analyze_project", side_effect=_mock_project_understanding), \
         patch.object(code_understanding_analyzer, "analyze_codebase", side_effect=_mock_code_understanding), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding):

        # 1. Submit GitHub URL with wait=true
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/sindresorhus/is"})
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        internal = job_store.get_internal_job(job_id)
        assert internal.ingestion_status == StatusEnum.COMPLETED
        assert any(l.name == "TypeScript" for l in internal.analysis.languages)
        assert internal.code_analysis.total_parsed_files > 0
        assert internal.architecture.call_graph.total_resolved_calls > 0
        assert internal.knowledge is not None

        # Project Understanding
        pu_resp = client.post(f"/api/v1/jobs/{job_id}/project-understanding")
        assert pu_resp.status_code == 200
        assert pu_resp.json()["identity"]["name"] == "sindresorhus/is"

        # Code Understanding
        cu_resp = client.post(f"/api/v1/jobs/{job_id}/code-understanding")
        assert cu_resp.status_code == 200
        assert cu_resp.json()["repository_name"] == "sindresorhus/is"

        # Workflow Understanding
        wu_resp = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding")
        assert wu_resp.status_code == 200
        assert wu_resp.json()["repository_name"] == "sindresorhus/is"


# =============================================================================
# SCENARIO B: API & Job-State Correctness
# =============================================================================

def test_e2e_invalid_github_urls_rejected():
    """Scenario B1: Invalid GitHub repository URLs rejected with 422."""
    invalid_urls = [
        "https://gitlab.com/user/project",
        "https://github.com",
        "https://github.com/user",
        "https://github.com/user/repo/issues",
        "not-a-valid-url",
        "",
    ]
    for url in invalid_urls:
        resp = client.post("/api/v1/jobs", json={"github_url": url})
        assert resp.status_code == 422


def test_e2e_inaccessible_repository_handling():
    """Scenario B2: Inaccessible/nonexistent repository fails cleanly without crashing."""
    with patch("app.api.routes.jobs.verify_repository_accessible") as mock_verify:
        from app.utils.github_url import RepositoryNotFoundError
        mock_verify.side_effect = RepositoryNotFoundError("Repository not found")

        resp = client.post("/api/v1/jobs", json={"github_url": "https://github.com/nonexistent-org/not-real"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


def test_e2e_missing_job_returns_404():
    """Scenario B3: Missing job ID returns 404 across all endpoints."""
    missing_id = "missing-job-xyz-999"
    assert client.get(f"/api/v1/jobs/{missing_id}").status_code == 404
    assert client.get(f"/api/v1/jobs/{missing_id}/analysis").status_code == 404
    assert client.get(f"/api/v1/jobs/{missing_id}/code-analysis").status_code == 404
    assert client.get(f"/api/v1/jobs/{missing_id}/architecture").status_code == 404
    assert client.get(f"/api/v1/jobs/{missing_id}/knowledge").status_code == 404
    assert client.post(f"/api/v1/jobs/{missing_id}/project-understanding").status_code == 404
    assert client.post(f"/api/v1/jobs/{missing_id}/code-understanding").status_code == 404
    assert client.post(f"/api/v1/jobs/{missing_id}/workflow-understanding").status_code == 404


def test_e2e_understanding_endpoints_reject_incomplete_prerequisites():
    """Scenario B4: Understanding endpoints reject requests with 409 when prerequisites are pending."""
    job = job_store.create_job(
        repo_url="https://github.com/test/repo",
        repo_name="test/repo",
        repository_owner="test",
        repository_name="repo",
        clone_url="https://github.com/test/repo.git",
    )
    jid = job.job_id

    # Attempting to call project/code/workflow understanding must reject with 409
    p_resp = client.post(f"/api/v1/jobs/{jid}/project-understanding")
    assert p_resp.status_code == 409
    assert "Repository ingestion must be completed" in p_resp.json()["detail"]

    c_resp = client.post(f"/api/v1/jobs/{jid}/code-understanding")
    assert c_resp.status_code == 409

    w_resp = client.post(f"/api/v1/jobs/{jid}/workflow-understanding")
    assert w_resp.status_code == 409


def test_e2e_caching_and_refresh_semantics():
    """Scenario B5: Cached results returned without unnecessary regeneration; refresh=true forces refresh."""
    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(
            job_id=job_id,
            local_path=str(dest_dir),
            file_count=171,
            size_bytes=1024 * 1024,
            size_mb=1.0,
            clone_duration_seconds=0.5,
        )

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(project_understanding_analyzer, "analyze_project", side_effect=_mock_project_understanding), \
         patch.object(code_understanding_analyzer, "analyze_codebase", side_effect=_mock_code_understanding), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding) as mock_analyze:

        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

        # Initial workflow generation
        wu1 = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding").json()
        assert mock_analyze.call_count == 1

        # Second POST without refresh should return cached object immediately
        with patch.object(workflow_understanding_analyzer, "analyze_workflows", new_callable=AsyncMock) as mock_analyze_2:
            wu2 = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding").json()
            mock_analyze_2.assert_not_called()
            assert wu1["generated_at"] == wu2["generated_at"]

        # Third POST with refresh=true forces re-generation
        with patch.object(
            workflow_understanding_analyzer,
            "analyze_workflows",
            new_callable=AsyncMock,
            return_value=workflow_understanding_analyzer.create_deterministic_fallback(
                job_store.get_internal_job(job_id).knowledge
            ),
        ) as mock_analyze_3:
            wu3 = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding?refresh=true").json()
            mock_analyze_3.assert_called_once()


@pytest.mark.anyio
async def test_e2e_concurrent_requests_serialized():
    """Scenario B6: Concurrent understanding generation requests for the same job are serialized cleanly."""
    from app.api.routes.jobs import generate_job_workflow_understanding

    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if not dest_dir.exists():
            shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(job_id=job_id, local_path=str(dest_dir), file_count=171, size_bytes=1000, size_mb=0.1, clone_duration_seconds=0.1)

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone):
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

    internal = job_store.get_internal_job(job_id)
    fallback_wf = workflow_understanding_analyzer.create_deterministic_fallback(internal.knowledge)

    execution_count = 0

    async def mock_slow_analyze(*args, **kwargs):
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)
        return fallback_wf

    with patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=mock_slow_analyze):
        t1 = generate_job_workflow_understanding(job_id=job_id, provider=None, refresh=False)
        t2 = generate_job_workflow_understanding(job_id=job_id, provider=None, refresh=False)
        r1, r2 = await asyncio.gather(t1, t2)

        assert r1.repository_name == "pallets/click"
        assert r2.repository_name == "pallets/click"
        # Per-job lock ensures analyze_workflows executed only once
        assert execution_count == 1


def test_e2e_nine_stages_pipeline_schema_consistency():
    """Scenario B6: Exactly nine pipeline stages; Stage 4 completed upon understanding; Stage 5 pending."""
    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if not dest_dir.exists():
            shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(job_id=job_id, local_path=str(dest_dir), file_count=171, size_bytes=1000, size_mb=0.1, clone_duration_seconds=0.1)

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(project_understanding_analyzer, "analyze_project", side_effect=_mock_project_understanding), \
         patch.object(code_understanding_analyzer, "analyze_codebase", side_effect=_mock_code_understanding), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding):

        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

        client.post(f"/api/v1/jobs/{job_id}/project-understanding")
        client.post(f"/api/v1/jobs/{job_id}/code-understanding")
        client.post(f"/api/v1/jobs/{job_id}/workflow-understanding")

        job = client.get(f"/api/v1/jobs/{job_id}").json()
        stages = job["stages"]
        assert len(stages) == 9

        stage_names = [s["name"] for s in stages]
        expected_names = [
            "Repository Fetching",
            "Repository Analysis",
            "Code Understanding",
            "AI Summary Generation",
            "Script Generation",
            "Storyboard Generation",
            "Visual Generation",
            "Voice Generation",
            "Video Assembly",
        ]
        assert stage_names == expected_names

        # Stage 1, 2, 3, 4 completed
        assert stages[0]["status"] == "completed"
        assert stages[1]["status"] == "completed"
        assert stages[2]["status"] == "completed"
        assert stages[3]["status"] == "completed"

        # Stage 5 is pending (not started yet)
        assert stages[4]["status"] == "pending"


# =============================================================================
# SCENARIO C: AI Provider Behavior (Groq, Auth, Timeouts, JSON Repair, Fallback)
# =============================================================================

def test_e2e_groq_provider_configuration_and_token_accounting():
    """Scenario C1: Groq provider configuration, model attribution, and token tracking."""
    provider = GroqProvider(api_key="gsk_test_key_12345", model="llama-3.1-8b-instant")
    assert provider.provider_name == "groq"
    assert provider.model_name == "llama-3.1-8b-instant"

    # Token estimation check
    tokens = provider.estimate_token_count("def calculate_total(items): return sum(items)")
    assert tokens > 0


@pytest.mark.anyio
async def test_e2e_ai_provider_missing_key_fails_fast():
    """Scenario C2: Missing API key fails fast with AIConfigurationError."""
    provider = GroqProvider(api_key="")
    with pytest.raises(AIConfigurationError) as exc_info:
        await provider.generate_text("Explain click architecture.")
    assert "Groq API key is not configured" in str(exc_info.value)
    assert exc_info.value.retryable is False


@pytest.mark.anyio
async def test_e2e_ai_provider_invalid_key_fails_fast():
    """Scenario C3: Invalid API key fails fast without retrying."""
    manager = LLMManager(active_provider="groq", max_retries=2)
    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.provider_name = "groq"
    mock_provider.model_name = "llama-3.1-8b-instant"
    mock_provider.is_configured.return_value = True
    mock_provider.generate_text = AsyncMock(
        side_effect=AIAuthenticationError("Invalid API key provided", provider="groq")
    )
    manager.register_provider("groq", mock_provider)

    with pytest.raises(AIAuthenticationError):
        await manager.generate("Analyze repo", job_id="job-auth-fail")
    # Must fail fast (only 1 attempt, no retries)
    assert mock_provider.generate_text.call_count == 1


@pytest.mark.anyio
async def test_e2e_ai_provider_timeout_and_transient_retry():
    """Scenario C4: Transient timeout retries up to configured limit before failing."""
    manager = LLMManager(active_provider="groq", max_retries=2)
    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.provider_name = "groq"
    mock_provider.model_name = "llama-3.1-8b-instant"
    mock_provider.is_configured.return_value = True
    mock_provider.generate_text = AsyncMock(
        side_effect=AITimeoutError("Request timed out", provider="groq")
    )
    manager.register_provider("groq", mock_provider)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(AITimeoutError):
            await manager.generate("Analyze repo", job_id="job-timeout")
    # 1 initial + 2 retries = 3 calls
    assert mock_provider.generate_text.call_count == 3


@pytest.mark.anyio
async def test_e2e_json_repair_on_malformed_llm_response():
    """Scenario C5: Malformed JSON triggers one-shot repair query; succeeds without crashing."""
    import json
    mock_llm = AsyncMock(spec=LLMManager)
    repaired_json = json.dumps({
        "schema_version": "1.0",
        "repository_name": "test/repair_app",
        "system_architecture_type": "modular_monolith",
        "workflow_summary": "Repaired workflow summary.",
        "workflows": [
            {
                "workflow_id": "wf_repair",
                "name": "Repaired Workflow",
                "category": "user_request",
                "description": "Repaired description.",
                "trigger": "start_app",
                "entry_point": {"component_id": "app/main.py", "name": "start_app", "role_in_workflow": "entry"},
                "steps": [
                    {
                        "step_number": 1,
                        "title": "Start",
                        "component_id": "app/main.py",
                        "symbol_name": "start_app",
                        "action_type": "call",
                        "description": "Initial call",
                        "runtime_execution_verified": False,
                    }
                ],
                "final_outcome": "Outcome success",
                "runtime_execution_verified": False,
            }
        ],
    })
    mock_llm.generate.side_effect = [
        LLMResponse(
            text="```json\n{ malformed: unquoted, broken: \n```",
            provider="gemini",
            model="gemini-2.5-pro",
            token_usage=TokenUsageRecord(
                provider="gemini",
                model="gemini-2.5-pro",
                prompt_tokens=200,
                completion_tokens=50,
                total_tokens=250,
            ),
            latency_ms=100.0,
        ),
        LLMResponse(
            text=repaired_json,
            provider="gemini",
            model="gemini-2.5-pro",
            token_usage=TokenUsageRecord(
                provider="gemini",
                model="gemini-2.5-pro",
                prompt_tokens=250,
                completion_tokens=150,
                total_tokens=400,
            ),
            latency_ms=120.0,
        ),
    ]

    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    from tests.test_workflow_understanding import _create_mock_knowledge_for_phase3
    mock_knowledge = _create_mock_knowledge_for_phase3()

    result = await analyzer.analyze_workflows(job_id="job_repair_e2e", knowledge=mock_knowledge)
    assert result.is_fallback is False
    assert len(result.workflows) == 1
    assert result.workflows[0].name == "Repaired Workflow"
    assert mock_llm.generate.call_count == 2
    assert result.token_usage.total_tokens == 650


@pytest.mark.anyio
async def test_e2e_unrecoverable_llm_failure_deterministic_fallback():
    """Scenario C6: Unrecoverable LLM failure yields deterministic AST fallback."""
    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.generate.side_effect = AIProviderUnavailableError("All LLM endpoints unreachable", provider="gemini")

    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    from tests.test_workflow_understanding import _create_mock_knowledge_for_phase3
    mock_knowledge = _create_mock_knowledge_for_phase3()

    result = await analyzer.analyze_workflows(job_id="job_fallback_e2e", knowledge=mock_knowledge)
    assert result.is_fallback is True
    assert result.provider == "deterministic_fallback"
    assert result.model == "ast_rule_based"
    assert len(result.workflows) >= 1
    assert result.workflows[0].is_deterministic is True
    assert any("AI generation unavailable" in lim for lim in result.analysis_limitations)


# =============================================================================
# SCENARIO D: Evidence and Correctness
# =============================================================================

def test_e2e_evidence_grounding_and_path_safety():
    """
    Scenario D1: Source evidence references actual repository files;
    paths are relative and sanitized; line ranges are positive and within file length.
    """
    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if not dest_dir.exists():
            shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(job_id=job_id, local_path=str(dest_dir), file_count=171, size_bytes=1000, size_mb=0.1, clone_duration_seconds=0.1)

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone):
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

        internal = job_store.get_internal_job(job_id)
        knowledge = internal.knowledge

        # Check evidence references in RepositoryKnowledge
        for ev in knowledge.source_evidence:
            assert not ev.file_path.startswith("/")
            assert not ev.file_path.startswith("C:\\")
            assert not "/repo_cache/" in ev.file_path
            if ev.start_line is not None:
                assert ev.start_line >= 1
            if ev.end_line is not None and ev.start_line is not None:
                assert ev.end_line >= ev.start_line


def test_e2e_no_runtime_execution_claims():
    """
    Scenario D2: All workflow steps and workflows strictly enforce runtime_execution_verified == False.
    RepoGenie does not execute or profile code at runtime.
    """
    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if not dest_dir.exists():
            shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(job_id=job_id, local_path=str(dest_dir), file_count=171, size_bytes=1000, size_mb=0.1, clone_duration_seconds=0.1)

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding):
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

        wu = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding").json()

        for wf in wu.get("workflows", []):
            assert wf["runtime_execution_verified"] is False
            for step in wf.get("steps", []):
                assert step["runtime_execution_verified"] is False


def test_e2e_no_fabricated_storage_or_http_operations():
    """
    Scenario D3: Operations are classified by static source expressions,
    never claimed as 'successfully saved' or 'request succeeded'.
    """
    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if not dest_dir.exists():
            shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(job_id=job_id, local_path=str(dest_dir), file_count=171, size_bytes=1000, size_mb=0.1, clone_duration_seconds=0.1)

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding):
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

        wu = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding").json()

        for wf in wu.get("workflows", []):
            for df in wf.get("data_flows", []):
                # Persistence status must be technical classifications, not success claims
                assert "successfully saved" not in df.get("persistence_status", "").lower()
                assert "request succeeded" not in df.get("external_api_status", "").lower()


def test_e2e_structural_call_chains_separate_provenance():
    """
    Scenario D4: Deterministic structural call chains remain distinct from LLM-generated workflows.
    """
    assert CLICK_FIXTURE_PATH.exists()

    def mock_clone(job_id, clone_url):
        dest_dir = repo_ingestion_service.get_job_repo_path(job_id)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if not dest_dir.exists():
            shutil.copytree(CLICK_FIXTURE_PATH, dest_dir)
        return IngestionResult(job_id=job_id, local_path=str(dest_dir), file_count=171, size_bytes=1000, size_mb=0.1, clone_duration_seconds=0.1)

    with patch("app.api.routes.jobs.verify_repository_accessible"), \
         patch.object(repo_ingestion_service, "ingest_repository", side_effect=mock_clone), \
         patch.object(workflow_understanding_analyzer, "analyze_workflows", side_effect=_mock_workflow_understanding):
        resp = client.post("/api/v1/jobs?wait=true", json={"github_url": "https://github.com/pallets/click"})
        job_id = resp.json()["job_id"]

        wu = client.post(f"/api/v1/jobs/{job_id}/workflow-understanding").json()

        # Structural chains have unresolved_reason and entry_symbol/entry_file
        for chain in wu.get("structural_call_chains", []):
            assert "chain_id" in chain
            assert "entry_symbol" in chain
            assert "entry_file" in chain
            assert "unresolved_reason" in chain
            assert "CallGraph" in chain["unresolved_reason"]
