"""
Tests for Milestone 4, Phase 4.1: Backend API and JobStore Integration for Educational Script and Storyboard.

Covers:
1. Educational Script API (POST generation, GET retrieval, 404, 409 prerequisites, caching, refresh, error handling).
2. Educational Storyboard API (POST generation from stored script, GET retrieval, 404, 409 prerequisites, caching, refresh, error handling).
3. Storyboard invalidation on script refresh/regeneration.
4. Concurrency handling and locking (preventing duplicate LLM generations).
5. Pipeline stage progression (Stage 05 & 06 transitions, no false completion on failure, preserving 9-stage pipeline).
6. Error message sanitization (no path leakage, no secret leakage).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitectureAnalysisResult,
    CallGraph,
    DependencyGraph,
    DirectoryTreeNode,
    ParsedRepository,
    RepoAnalysisResult,
    RepoStatistics,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    ProjectOverviewInfo,
    TechnologyStack,
    RepositoryStructureOverview,
    UnifiedStatistics,
    CodeStructureSummary,
    ArchitectureSummary,
    KnowledgeAnalysisMetadata,
    StageEnum,
    StatusEnum,
)
from app.services.ai.exceptions import AIError, AIProviderUnavailableError
from app.services.ai.project_understanding import (
    EvidenceReference,
    ProjectUnderstanding,
)
from app.services.ai.script_generation import educational_script_analyzer
from app.services.ai.script_generation.schemas import (
    EducationalScript,
    GroundedClaim,
    GroundingStatus,
    ScriptSection,
    SectionPurpose,
    VideoFormatSpec,
)
from app.services.ai.storyboard_generation import educational_storyboard_analyzer
from app.services.ai.storyboard_generation.schemas import (
    EducationalStoryboard,
    NarrationReference,
    StoryboardScene,
    VisualType,
)
from app.services.storage.job_store import PIPELINE_STAGES, job_store
from app.api.routes.jobs import (
    generate_job_educational_script,
    generate_job_educational_storyboard,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

def _create_mock_knowledge(repo_name: str = "pallets/click") -> RepositoryKnowledge:
    """Builds a minimal valid RepositoryKnowledge for testing."""
    now = datetime.now(timezone.utc)
    return RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="click",
            owner="pallets",
            repository_url=f"https://github.com/{repo_name}",
            clone_status=StatusEnum.COMPLETED,
            file_count=20,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="Composable command-line interface toolkit",
        ),
        technology_stack=TechnologyStack(),
        repository_structure=RepositoryStructureOverview(
            total_directories=4,
            total_files=20,
            important_directories=["src/click"],
        ),
        statistics=UnifiedStatistics(total_files=20, source_files=15),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(),
            call_graph=CallGraph(),
        ),
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=["repo_structure", "code_parsing", "architecture_analysis"],
        ),
    )


def _create_mock_script(script_id: str = "script-test-1", repo_name: str = "pallets/click") -> EducationalScript:
    """Builds a verified sample EducationalScript."""
    core_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=10,
        line_end=50,
        evidence_type="code",
        is_valid=True,
        path_verified=True,
    )
    sections = [
        ScriptSection(
            section_id="sec-1-hook",
            order=1,
            title="Introduction to Click",
            purpose=SectionPurpose.HOOK,
            narration_text="Click is a Python package for creating composable command line interfaces.",
            estimated_duration_seconds=15.0,
            evidence=[core_ev],
            claims=[
                GroundedClaim(
                    statement="Click builds command line tools using Python decorators.",
                    grounding_status=GroundingStatus.CONFIRMED,
                    evidence=[core_ev],
                )
            ],
            transition_to_next="Let's look at the overall architecture.",
        ),
        ScriptSection(
            section_id="sec-2-arch",
            order=2,
            title="Layered Architecture",
            purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
            narration_text="Click separates decorators, context creation, and callback invocation.",
            estimated_duration_seconds=15.0,
            evidence=[core_ev],
            transition_to_next="Now let's examine the core components.",
        ),
        ScriptSection(
            section_id="sec-3-comp",
            order=3,
            title="Command Engine & Decorators",
            purpose=SectionPurpose.COMPONENT_DEEP_DIVE,
            narration_text="The Command Execution Engine manages context while decorators wrap user functions.",
            estimated_duration_seconds=18.0,
            evidence=[core_ev],
            transition_to_next="Next, let's trace command execution.",
        ),
        ScriptSection(
            section_id="sec-4-wf",
            order=4,
            title="Execution Workflow",
            purpose=SectionPurpose.WORKFLOW,
            narration_text="When a command executes, arguments are parsed, converted, and forwarded to the callback.",
            estimated_duration_seconds=15.0,
            evidence=[core_ev],
            transition_to_next="Finally, let's review what we learned.",
        ),
        ScriptSection(
            section_id="sec-5-outro",
            order=5,
            title="Summary and Conclusion",
            purpose=SectionPurpose.CONCLUSION,
            narration_text="Click makes building complex command line interfaces modular and testable.",
            estimated_duration_seconds=12.0,
            evidence=[core_ev],
            transition_to_next=None,
        ),
    ]
    return EducationalScript(
        script_id=script_id,
        repository_name=repo_name,
        title="Inside Click CLI",
        introduction="Click is a Python package for composable command-line tools.",
        learning_objectives=["Understand Click decorators", "Trace command execution flow"],
        total_estimated_duration_seconds=75.0,
        sections=sections,
        conclusion="Click provides an extensible architecture for CLIs.",
        evidence=[core_ev],
    )


def _create_mock_storyboard(script: EducationalScript, storyboard_id: str = "sb-test-1") -> EducationalStoryboard:
    """Builds a verified sample EducationalStoryboard matching `script`."""
    scenes = [
        StoryboardScene(
            scene_id="scene-1",
            scene_number=1,
            script_section_id="sec-1-hook",
            title="Title & Hook",
            purpose="Introduce Click and display title card",
            estimated_duration_seconds=15.0,
            visual_type=VisualType.TITLE_CARD,
            visual_description="Clean title card with Click logo and subtitle 'Composable CLIs in Python'.",
            on_screen_text=["Inside Click CLI", "Composable Python CLIs"],
            narration=NarrationReference(
                script_section_id="sec-1-hook",
                excerpt="Click is a Python package for creating composable command line interfaces.",
            ),
            related_files=["src/click/core.py"],
            transition_to_next="Crossfade to architecture diagram",
        ),
        StoryboardScene(
            scene_id="scene-2",
            scene_number=2,
            script_section_id="sec-2-arch",
            title="Layered CLI Architecture",
            purpose="Show high-level architectural layers",
            estimated_duration_seconds=15.0,
            visual_type=VisualType.ARCHITECTURE_DIAGRAM,
            visual_description="Three horizontal layers: Decorator API -> Core Execution Engine -> Parameter Parsers.",
            on_screen_text=["Decorator API", "Command Engine", "Option Parsers"],
            narration=NarrationReference(script_section_id="sec-2-arch"),
            related_files=["src/click/core.py"],
            transition_to_next="Zoom into Command Engine",
        ),
        StoryboardScene(
            scene_id="scene-3",
            scene_number=3,
            script_section_id="sec-3-comp",
            title="Command Engine Deep Dive",
            purpose="Walk through Command and Context classes",
            estimated_duration_seconds=18.0,
            visual_type=VisualType.CODE_WALKTHROUGH,
            visual_description="Code view of Command.main() invoking Context.invoke()",
            on_screen_text=["class Command", "class Context"],
            narration=NarrationReference(script_section_id="sec-3-comp"),
            related_files=["src/click/core.py"],
            transition_to_next="Slide right to workflow diagram",
        ),
        StoryboardScene(
            scene_id="scene-4",
            scene_number=4,
            script_section_id="sec-4-wf",
            title="Command Execution Flow",
            purpose="Trace argument parsing to callback execution",
            estimated_duration_seconds=15.0,
            visual_type=VisualType.DATA_FLOW_VISUALIZATION,
            visual_description="Step-by-step token parsing flowchart",
            on_screen_text=["1. Parse argv", "2. Resolve context", "3. Invoke callback"],
            narration=NarrationReference(script_section_id="sec-4-wf"),
            related_files=["src/click/core.py"],
            transition_to_next="Fade to summary card",
        ),
        StoryboardScene(
            scene_id="scene-5",
            scene_number=5,
            script_section_id="sec-5-outro",
            title="Summary & Conclusion",
            purpose="Wrap up architectural takeaways",
            estimated_duration_seconds=12.0,
            visual_type=VisualType.SUMMARY_CARD,
            visual_description="Key takeaway bullet points with Pallets documentation link",
            on_screen_text=["Modular", "Composable", "Testable CLIs"],
            narration=NarrationReference(script_section_id="sec-5-outro"),
            related_files=["src/click/core.py"],
            transition_to_next=None,
        ),
    ]
    return EducationalStoryboard(
        storyboard_id=storyboard_id,
        script_id=script.script_id,
        title=f"{script.title} Storyboard",
        total_estimated_duration_seconds=75.0,
        video_format=VideoFormatSpec(),
        scenes=scenes,
    )


def setup_job_ready_for_script(job_id_prefix: str = "test-job-script") -> str:
    """Creates a job in JobStore with prerequisites ready for Stage 5 script generation."""
    internal = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job_id = internal.job_id
    internal.local_path = f"/tmp/repos/{job_id}"

    # Complete Stage 1 (Ingestion)
    job_store.update_job_ingestion_success(
        job_id=job_id,
        local_path=internal.local_path,
        file_count=20,
        size_mb=1.5,
    )

    # Complete Stage 2 (Analysis)
    stats = RepoStatistics(
        total_files=20,
        total_directories=4,
        source_files=15,
        filtered_files=5,
        total_size_bytes=1024 * 1024,
        configuration_files=2,
        dependency_manifests=1,
        recognized_languages_count=1,
    )
    analysis = RepoAnalysisResult(
        repository_name="click",
        directory_tree=DirectoryTreeNode(name="click", path="", type="directory"),
        statistics=stats,
        languages=[],
        dependency_files=[],
        configuration_files=[],
    )
    job_store.update_job_analysis_success(job_id, analysis)

    # Complete Stage 3 (Code Parsing & Knowledge Consolidation)
    parsed_repo = ParsedRepository(
        job_id=job_id,
        repository_name="click",
        total_parsed_files=15,
        total_functions=30,
        total_classes=10,
        total_methods=40,
        total_imports=50,
        total_function_calls=60,
        supported_languages=["python"],
    )
    arch = ArchitectureAnalysisResult(
        job_id=job_id,
        repository_name="click",
        dependency_graph=DependencyGraph(),
        call_graph=CallGraph(),
    )
    knowledge = _create_mock_knowledge()
    job_store.update_job_knowledge_success(
        job_id=job_id,
        code_analysis=parsed_repo,
        architecture=arch,
        knowledge=knowledge,
    )

    return job_id


# ---------------------------------------------------------------------------
# Educational Script API Tests
# ---------------------------------------------------------------------------

def test_generate_script_success():
    """POST /educational-script generates script, updates Stage 5 to COMPLETED, and advances to Stage 6."""
    job_id = setup_job_ready_for_script("script-gen-success")
    mock_script = _create_mock_script(script_id=f"script-{job_id}")

    with patch.object(
        educational_script_analyzer,
        "generate_script",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = mock_script
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-script")
        assert resp.status_code == 200
        data = resp.json()
        assert data["script_id"] == mock_script.script_id
        assert len(data["sections"]) == 5
        assert data["total_estimated_duration_seconds"] == 75.0
        mock_gen.assert_called_once()

    # Verify JobStore state
    stored_script = job_store.get_job_educational_script(job_id)
    assert stored_script is not None
    assert stored_script.script_id == mock_script.script_id

    # Verify Stage progression
    job_resp = job_store.get_job(job_id)
    assert job_resp is not None
    assert job_resp.has_educational_script is True
    assert job_resp.has_educational_storyboard is False
    assert job_resp.stages[4].status == StatusEnum.COMPLETED
    assert job_resp.stages[4].name == StageEnum.SCRIPT_GENERATION.value
    assert job_resp.current_stage == StageEnum.STORYBOARD_GENERATION.value
    assert job_resp.progress_percentage == 55


def test_get_educational_script_success():
    """GET /educational-script retrieves previously generated script."""
    job_id = setup_job_ready_for_script("script-get-success")
    mock_script = _create_mock_script(script_id=f"script-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)

    resp = client.get(f"/api/v1/jobs/{job_id}/educational-script")
    assert resp.status_code == 200
    data = resp.json()
    assert data["script_id"] == mock_script.script_id
    assert data["title"] == "Inside Click CLI"


def test_get_educational_script_not_generated_returns_404():
    """GET /educational-script returns 404 when script has not been generated yet."""
    job_id = setup_job_ready_for_script("script-get-not-gen")
    resp = client.get(f"/api/v1/jobs/{job_id}/educational-script")
    assert resp.status_code == 404
    assert "has not yet been generated" in resp.json()["detail"]


def test_get_educational_script_unknown_job_returns_404():
    """GET /educational-script returns 404 for nonexistent job ID."""
    resp = client.get("/api/v1/jobs/unknown-job-id-9999/educational-script")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_post_educational_script_unknown_job_returns_404():
    """POST /educational-script returns 404 for nonexistent job ID."""
    resp = client.post("/api/v1/jobs/unknown-job-id-9999/educational-script")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_post_script_caching_avoids_llm_call():
    """POST /educational-script returns cached script without invoking LLM when already generated."""
    job_id = setup_job_ready_for_script("script-caching")
    mock_script = _create_mock_script(script_id=f"script-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)

    with patch.object(
        educational_script_analyzer,
        "generate_script",
        new_callable=AsyncMock,
    ) as mock_gen:
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-script")
        assert resp.status_code == 200
        assert resp.json()["script_id"] == mock_script.script_id
        mock_gen.assert_not_called()


def test_post_script_explicit_refresh_regenerates():
    """POST /educational-script with refresh=true forces LLM generation even if cached."""
    job_id = setup_job_ready_for_script("script-refresh")
    old_script = _create_mock_script(script_id=f"script-old-{job_id}")
    job_store.update_job_educational_script_success(job_id, old_script)

    new_script = _create_mock_script(script_id=f"script-new-{job_id}")
    new_script.title = "Updated Click Explainer"

    with patch.object(
        educational_script_analyzer,
        "generate_script",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = new_script
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-script?refresh=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["script_id"] == new_script.script_id
        assert data["title"] == "Updated Click Explainer"
        mock_gen.assert_called_once()


def test_post_script_refresh_invalidates_previous_storyboard():
    """Regenerating a script invalidates any previous storyboard generated from the older script."""
    job_id = setup_job_ready_for_script("script-invalidation")
    initial_script = _create_mock_script(script_id=f"script-initial-{job_id}")
    job_store.update_job_educational_script_success(job_id, initial_script)

    initial_storyboard = _create_mock_storyboard(initial_script, storyboard_id=f"sb-{job_id}")
    job_store.update_job_educational_storyboard_success(job_id, initial_storyboard)

    # Confirm initial storyboard is active and Stage 6 is COMPLETED
    job = job_store.get_job(job_id)
    assert job.has_educational_storyboard is True
    assert job.stages[5].status == StatusEnum.COMPLETED

    # Regenerate script with refresh=true
    new_script = _create_mock_script(script_id=f"script-v2-{job_id}")
    with patch.object(
        educational_script_analyzer,
        "generate_script",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = new_script
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-script?refresh=true")
        assert resp.status_code == 200

    # Storyboard must now be invalidated
    job_after = job_store.get_job(job_id)
    assert job_after.has_educational_script is True
    assert job_after.has_educational_storyboard is False
    assert job_after.educational_storyboard is None
    assert job_after.stages[5].status == StatusEnum.PENDING
    assert "regenerated" in job_after.stages[5].detail

    # GET educational-storyboard must return 404
    get_sb_resp = client.get(f"/api/v1/jobs/{job_id}/educational-storyboard")
    assert get_sb_resp.status_code == 404


def test_post_script_missing_prerequisites_returns_409():
    """POST /educational-script returns 409 Conflict when repository analysis/knowledge is incomplete."""
    internal = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    # Stage 0 is still PENDING
    resp = client.post(f"/api/v1/jobs/{internal.job_id}/educational-script")
    assert resp.status_code == 409
    assert "ingestion must be completed first" in resp.json()["detail"]


def test_post_script_provider_failure_does_not_store_fabricated_script():
    """Provider failure returns HTTP 502/503 and does not store any fabricated script."""
    job_id = setup_job_ready_for_script("script-failure")

    with patch.object(
        educational_script_analyzer,
        "generate_script",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.side_effect = AIProviderUnavailableError("Groq service unavailable", provider="groq")
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-script")
        assert resp.status_code == 503
        assert "Groq service unavailable" in resp.json()["detail"]

    # Verify no script stored and Stage 5 marked FAILED
    job = job_store.get_job(job_id)
    assert job.has_educational_script is False
    assert job.educational_script is None
    assert job.stages[4].status == StatusEnum.FAILED
    assert "failed" in job.stages[4].detail.lower()


@pytest.mark.anyio
async def test_post_script_concurrent_requests_prevent_duplicate_generation():
    """Concurrent requests for the same job serialize and trigger only one LLM generation."""
    job_id = setup_job_ready_for_script("script-concurrency")
    mock_script = _create_mock_script(script_id=f"script-conc-{job_id}")
    call_count = 0

    async def _mock_slow_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return mock_script

    with patch.object(
        educational_script_analyzer,
        "generate_script",
        side_effect=_mock_slow_generate,
    ):
        task1 = generate_job_educational_script(job_id=job_id, provider=None, refresh=False)
        task2 = generate_job_educational_script(job_id=job_id, provider=None, refresh=False)
        res1, res2 = await asyncio.gather(task1, task2)

        assert res1.script_id == mock_script.script_id
        assert res2.script_id == mock_script.script_id
        # Crucial check: analyzer must only have been invoked ONCE
        assert call_count == 1


# ---------------------------------------------------------------------------
# Educational Storyboard API Tests
# ---------------------------------------------------------------------------

def test_generate_storyboard_success_from_stored_script():
    """POST /educational-storyboard generates storyboard using the stored script and advances to Stage 7."""
    job_id = setup_job_ready_for_script("sb-gen-success")
    mock_script = _create_mock_script(script_id=f"script-for-sb-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)

    mock_storyboard = _create_mock_storyboard(mock_script, storyboard_id=f"sb-{job_id}")

    with patch.object(
        educational_storyboard_analyzer,
        "generate_storyboard",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = mock_storyboard
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-storyboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["storyboard_id"] == mock_storyboard.storyboard_id
        assert data["script_id"] == mock_script.script_id
        assert len(data["scenes"]) == 5
        assert data["total_estimated_duration_seconds"] == 75.0

        # Verify analyzer was invoked with the exact stored script
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["script"].script_id == mock_script.script_id

    # Verify JobStore state
    stored_sb = job_store.get_job_educational_storyboard(job_id)
    assert stored_sb is not None
    assert stored_sb.storyboard_id == mock_storyboard.storyboard_id

    # Verify Stage progression
    job_resp = job_store.get_job(job_id)
    assert job_resp.has_educational_storyboard is True
    assert job_resp.stages[5].status == StatusEnum.COMPLETED
    assert job_resp.stages[5].name == StageEnum.STORYBOARD_GENERATION.value
    assert job_resp.current_stage == StageEnum.VISUAL_GENERATION.value
    assert job_resp.progress_percentage == 66


def test_get_educational_storyboard_success():
    """GET /educational-storyboard retrieves previously generated storyboard."""
    job_id = setup_job_ready_for_script("sb-get-success")
    mock_script = _create_mock_script(script_id=f"script-sb-get-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)
    mock_storyboard = _create_mock_storyboard(mock_script, storyboard_id=f"sb-{job_id}")
    job_store.update_job_educational_storyboard_success(job_id, mock_storyboard)

    resp = client.get(f"/api/v1/jobs/{job_id}/educational-storyboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["storyboard_id"] == mock_storyboard.storyboard_id
    assert data["script_id"] == mock_script.script_id


def test_get_educational_storyboard_not_generated_returns_404():
    """GET /educational-storyboard returns 404 when storyboard has not been generated."""
    job_id = setup_job_ready_for_script("sb-get-not-gen")
    resp = client.get(f"/api/v1/jobs/{job_id}/educational-storyboard")
    assert resp.status_code == 404
    assert "has not yet been generated" in resp.json()["detail"]


def test_get_educational_storyboard_unknown_job_returns_404():
    """GET /educational-storyboard returns 404 for unknown job ID."""
    resp = client.get("/api/v1/jobs/unknown-job-id-9999/educational-storyboard")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_post_educational_storyboard_unknown_job_returns_404():
    """POST /educational-storyboard returns 404 for unknown job ID."""
    resp = client.post("/api/v1/jobs/unknown-job-id-9999/educational-storyboard")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_post_storyboard_missing_script_prerequisite_returns_409():
    """POST /educational-storyboard returns 409 Conflict when EducationalScript is missing."""
    job_id = setup_job_ready_for_script("sb-missing-script")
    resp = client.post(f"/api/v1/jobs/{job_id}/educational-storyboard")
    assert resp.status_code == 409
    assert "Educational script must be generated before storyboard generation" in resp.json()["detail"]


def test_post_storyboard_caching_avoids_llm_call():
    """POST /educational-storyboard returns cached storyboard without invoking LLM."""
    job_id = setup_job_ready_for_script("sb-caching")
    mock_script = _create_mock_script(script_id=f"script-sb-cache-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)
    mock_storyboard = _create_mock_storyboard(mock_script, storyboard_id=f"sb-{job_id}")
    job_store.update_job_educational_storyboard_success(job_id, mock_storyboard)

    with patch.object(
        educational_storyboard_analyzer,
        "generate_storyboard",
        new_callable=AsyncMock,
    ) as mock_gen:
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-storyboard")
        assert resp.status_code == 200
        assert resp.json()["storyboard_id"] == mock_storyboard.storyboard_id
        mock_gen.assert_not_called()


def test_post_storyboard_explicit_refresh_regenerates():
    """POST /educational-storyboard with refresh=true re-runs LLM generation."""
    job_id = setup_job_ready_for_script("sb-refresh")
    mock_script = _create_mock_script(script_id=f"script-sb-ref-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)
    old_storyboard = _create_mock_storyboard(mock_script, storyboard_id=f"sb-old-{job_id}")
    job_store.update_job_educational_storyboard_success(job_id, old_storyboard)

    new_storyboard = _create_mock_storyboard(mock_script, storyboard_id=f"sb-new-{job_id}")
    new_storyboard.title = "Updated Storyboard Title"

    with patch.object(
        educational_storyboard_analyzer,
        "generate_storyboard",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = new_storyboard
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-storyboard?refresh=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["storyboard_id"] == new_storyboard.storyboard_id
        assert data["title"] == "Updated Storyboard Title"
        mock_gen.assert_called_once()


def test_post_storyboard_provider_failure_does_not_store_fabricated_storyboard():
    """Storyboard generation failure returns HTTP 503 and marks Stage 6 FAILED without storing bogus data."""
    job_id = setup_job_ready_for_script("sb-failure")
    mock_script = _create_mock_script(script_id=f"script-sb-fail-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)

    with patch.object(
        educational_storyboard_analyzer,
        "generate_storyboard",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.side_effect = AIProviderUnavailableError("Groq quota exceeded", provider="groq")
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-storyboard")
        assert resp.status_code == 503
        assert "Groq quota exceeded" in resp.json()["detail"]

    # Verify no storyboard stored and Stage 6 marked FAILED
    job = job_store.get_job(job_id)
    assert job.has_educational_storyboard is False
    assert job.educational_storyboard is None
    assert job.stages[5].status == StatusEnum.FAILED
    assert "failed" in job.stages[5].detail.lower()


@pytest.mark.anyio
async def test_post_storyboard_concurrent_requests_prevent_duplicate_generation():
    """Concurrent requests for storyboard serialize and run only one LLM generation."""
    job_id = setup_job_ready_for_script("sb-concurrency")
    mock_script = _create_mock_script(script_id=f"script-sb-conc-{job_id}")
    job_store.update_job_educational_script_success(job_id, mock_script)
    mock_storyboard = _create_mock_storyboard(mock_script, storyboard_id=f"sb-conc-{job_id}")

    call_count = 0

    async def _mock_slow_storyboard(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return mock_storyboard

    with patch.object(
        educational_storyboard_analyzer,
        "generate_storyboard",
        side_effect=_mock_slow_storyboard,
    ):
        task1 = generate_job_educational_storyboard(job_id=job_id, provider=None, refresh=False)
        task2 = generate_job_educational_storyboard(job_id=job_id, provider=None, refresh=False)
        r1, r2 = await asyncio.gather(task1, task2)

        assert r1.storyboard_id == mock_storyboard.storyboard_id
        assert r2.storyboard_id == mock_storyboard.storyboard_id
        assert call_count == 1


# ---------------------------------------------------------------------------
# Pipeline Integrity & Error Sanitization Tests
# ---------------------------------------------------------------------------

def test_pipeline_stages_preserved_and_nine_stage_integrity():
    """Verifies that standard 9-stage pipeline ordering and names are intact."""
    assert len(PIPELINE_STAGES) == 9
    assert PIPELINE_STAGES[4] == StageEnum.SCRIPT_GENERATION.value
    assert PIPELINE_STAGES[5] == StageEnum.STORYBOARD_GENERATION.value

    job_id = setup_job_ready_for_script("pipeline-integrity")
    job = job_store.get_job(job_id)
    assert len(job.stages) == 9
    assert job.stages[4].id == 5
    assert job.stages[4].name == StageEnum.SCRIPT_GENERATION.value
    assert job.stages[5].id == 6
    assert job.stages[5].name == StageEnum.STORYBOARD_GENERATION.value


def test_error_message_sanitization_masks_paths_and_keys():
    """Errors containing internal local paths or sensitive API keys are sanitized in API responses."""
    job_id = setup_job_ready_for_script("error-sanitization")
    internal = job_store.get_internal_job(job_id)
    raw_error_msg = f"Failed in {internal.local_path}/sensitive/file: API key gsk_test1234567890 invalid"

    with patch.object(
        educational_script_analyzer,
        "generate_script",
        new_callable=AsyncMock,
    ) as mock_gen, patch("app.api.routes.jobs.settings.GROQ_API_KEY", "gsk_test1234567890"):
        mock_gen.side_effect = AIError(raw_error_msg, status_code=502)
        resp = client.post(f"/api/v1/jobs/{job_id}/educational-script")
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert internal.local_path not in detail
        assert "<REPO_ROOT>" in detail
        assert "gsk_test1234567890" not in detail
        assert "[REDACTED]" in detail
