"""
Tests for Milestone 5, Phase 5.1: Visual Generation Foundation.

Covers:
1. Strongly typed Pydantic schemas (VisualAsset, SceneVisualAssets, VisualGenerationResult, metadata, enums).
2. Isolated storage manager (directory isolation, path traversal prevention, safe relative paths, deletion).
3. VisualGenerationService (scene-to-asset blueprint mapping, PLANNED status, PENDING asset lifecycle state, evidence preservation).
4. JobStore integration & Lifecycle Correctness:
   - Visual planning initializes the plan without marking Stage 07 as COMPLETED.
   - Visual planning does NOT advance the pipeline to Stage 08 (Voice Generation).
   - All planned assets remain in PENDING status before rendering.
   - Stage 07 is marked COMPLETED only when every required asset has successfully rendered.
   - A failed asset prevents premature completion.
   - Invalidation cascade: Storyboard invalidation clears visual plan and purges disk assets.
   - Invalidation cascade: Script invalidation clears storyboard, visual plan, and purges disk assets.
5. FastAPI endpoints (POST /visual-assets, GET /visual-assets, GET /visual-assets/{asset_id},
   GET /visual-assets/{asset_id}/file, 404, 409, refresh).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitectureAnalysisResult,
    ArchitectureSummary,
    CallGraph,
    CodeStructureSummary,
    DependencyGraph,
    DirectoryTreeNode,
    KnowledgeAnalysisMetadata,
    ParsedRepository,
    ProjectOverviewInfo,
    RepoAnalysisResult,
    RepoStatistics,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    StageEnum,
    StatusEnum,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.project_understanding import EvidenceReference
from app.services.ai.script_generation.schemas import (
    EducationalScript,
    GroundedClaim,
    GroundingStatus,
    ScriptSection,
    SectionPurpose,
)
from app.services.ai.storyboard_generation.schemas import (
    EducationalStoryboard,
    NarrationReference,
    StoryboardScene,
    VisualType,
)
from app.services.storage.job_store import PIPELINE_STAGES, job_store
from app.services.video.visual_generation import (
    MediaFormat,
    PathTraversalError,
    SceneVisualAssets,
    VideoOrientation,
    VisualAsset,
    VisualAssetStatus,
    VisualAssetStorageManager,
    VisualAssetType,
    VisualGenerationMetadata,
    VisualGenerationResult,
    VisualGenerationService,
    VisualGenerationStatus,
    visual_generation_service,
    visual_storage_manager,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def _create_mock_knowledge(repo_name: str = "pallets/click") -> RepositoryKnowledge:
    now = datetime.now(timezone.utc)
    return RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="click",
            owner="pallets",
            repository_url=f"https://github.com/{repo_name}",
            clone_status=StatusEnum.COMPLETED,
            file_count=10,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="CLI toolkit",
        ),
        technology_stack=TechnologyStack(),
        repository_structure=RepositoryStructureOverview(
            total_directories=2,
            total_files=10,
            important_directories=["src/click"],
        ),
        statistics=UnifiedStatistics(total_files=10, source_files=8),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(),
            call_graph=CallGraph(),
        ),
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=["repo_structure"],
        ),
    )


def _create_mock_script(script_id: str = "script-test-vg") -> EducationalScript:
    ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=1,
        line_end=20,
        evidence_type="code",
        is_valid=True,
        path_verified=True,
    )
    sections = [
        ScriptSection(
            section_id="sec-1",
            order=1,
            title="Hook",
            purpose=SectionPurpose.HOOK,
            narration_text="Welcome to Click CLI.",
            estimated_duration_seconds=15.0,
            evidence=[ev],
            claims=[
                GroundedClaim(
                    statement="Click is a Python CLI framework.",
                    grounding_status=GroundingStatus.CONFIRMED,
                    evidence=[ev],
                )
            ],
            transition_to_next="Next is architecture.",
        ),
        ScriptSection(
            section_id="sec-2",
            order=2,
            title="Architecture",
            purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
            narration_text="Click architecture is modular.",
            estimated_duration_seconds=20.0,
            evidence=[ev],
            transition_to_next=None,
        ),
    ]
    return EducationalScript(
        script_id=script_id,
        repository_name="pallets/click",
        title="Inside Click CLI",
        introduction="Intro text",
        learning_objectives=["Understand Click"],
        total_estimated_duration_seconds=35.0,
        sections=sections,
        conclusion="Conclusion text",
        evidence=[ev],
    )


def _create_mock_storyboard(script: EducationalScript, storyboard_id: str = "sb-test-vg") -> EducationalStoryboard:
    ev = script.evidence[0]
    scenes = [
        StoryboardScene(
            scene_id="scene-1",
            scene_number=1,
            script_section_id="sec-1",
            title="Title Card Scene",
            purpose="Introduce Click",
            estimated_duration_seconds=15.0,
            visual_type=VisualType.OTHER,
            visual_description="Title card with Click logo",
            on_screen_text=["Click CLI", "Python CLI Framework"],
            narration=NarrationReference(
                script_section_id="sec-1",
                excerpt="Welcome to Click CLI.",
            ),
            evidence=[ev],
            related_files=["src/click/core.py"],
            transition_to_next="Fade to architecture",
        ),
        StoryboardScene(
            scene_id="scene-2",
            scene_number=2,
            script_section_id="sec-2",
            title="Architecture Scene",
            purpose="Show Click architecture",
            estimated_duration_seconds=20.0,
            visual_type=VisualType.ARCHITECTURE_DIAGRAM,
            visual_description="Mermaid diagram of Click modules",
            on_screen_text=["Architecture Overview"],
            narration=NarrationReference(
                script_section_id="sec-2",
                excerpt="Click architecture is modular.",
            ),
            evidence=[ev],
            related_files=["src/click/core.py"],
            transition_to_next="Fade out",
        ),
    ]
    return EducationalStoryboard(
        storyboard_id=storyboard_id,
        script_id=script.script_id,
        repository_name="pallets/click",
        title="Inside Click CLI Storyboard",
        total_estimated_duration_seconds=35.0,
        scenes=scenes,
        evidence=[ev],
    )


def _setup_job_with_storyboard(job_id_prefix: str = "test-job-vg") -> tuple[str, EducationalScript, EducationalStoryboard]:
    """Sets up a complete job in JobStore up to Stage 6 (Storyboard) with prerequisites met."""
    internal = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job_id = internal.job_id
    internal.local_path = f"/tmp/repos/{job_id}"

    # Stage 1: Ingestion
    job_store.update_job_ingestion_success(
        job_id=job_id,
        local_path=internal.local_path,
        file_count=10,
        size_mb=1.0,
    )

    # Stage 2: Analysis
    analysis = RepoAnalysisResult(
        repository_name="click",
        directory_tree=DirectoryTreeNode(name="click", path="", type="directory"),
        statistics=RepoStatistics(
            total_files=10,
            total_directories=2,
            source_files=8,
            filtered_files=2,
            total_size_bytes=1024,
            configuration_files=1,
            dependency_manifests=1,
            recognized_languages_count=1,
        ),
        languages=[],
        dependency_files=[],
        configuration_files=[],
    )
    job_store.update_job_analysis_success(job_id, analysis)

    # Stage 3: Code Parsing and Knowledge Consolidation
    parsed_repo = ParsedRepository(
        job_id=job_id,
        repository_name="click",
        total_parsed_files=8,
        total_functions=10,
        total_classes=5,
        total_methods=10,
        total_imports=10,
        total_function_calls=10,
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

    # Stages 5 & 6: Script & Storyboard
    script = _create_mock_script(script_id=f"script-{job_id}")
    storyboard = _create_mock_storyboard(script, storyboard_id=f"sb-{job_id}")
    job_store.update_job_educational_script_success(job_id, script)
    job_store.update_job_educational_storyboard_success(job_id, storyboard)

    return job_id, script, storyboard


# ---------------------------------------------------------------------------
# 1. Schema Tests
# ---------------------------------------------------------------------------

def test_visual_asset_schema_valid():
    """Verifies that a valid VisualAsset passes validation with correct defaults."""
    ev = EvidenceReference(file_path="src/click/core.py", line_start=1, line_end=10, is_valid=True)
    asset = VisualAsset(
        asset_id="va_testjob1_s01_01",
        job_id="testjob1",
        scene_id="scene-1",
        scene_number=1,
        asset_type=VisualAssetType.TITLE_CARD,
        visual_type=VisualType.TITLE_CARD,
        storage_path="jobs/testjob1/visuals/va_testjob1_s01_01.svg",
        media_format=MediaFormat.SVG,
        source_evidence=[ev],
        related_files=["src/click/core.py"],
    )
    assert asset.status == VisualAssetStatus.PENDING
    assert asset.width == 1920
    assert asset.height == 1080
    assert asset.aspect_ratio == "16:9"
    assert asset.metadata.generator_name == "VisualGenerationFoundation"


def test_visual_asset_schema_rejects_unsafe_identifiers():
    """Verifies that path traversal or illegal characters in IDs are rejected."""
    with pytest.raises(ValueError, match="Invalid identifier"):
        VisualAsset(
            asset_id="../dangerous",
            job_id="testjob1",
            scene_id="scene-1",
            scene_number=1,
            visual_type=VisualType.TITLE_CARD,
            storage_path="jobs/testjob1/visuals/va_01.svg",
        )

    with pytest.raises(ValueError, match="Invalid identifier"):
        VisualAsset(
            asset_id="va_01",
            job_id="bad/job/id",
            scene_id="scene-1",
            scene_number=1,
            visual_type=VisualType.TITLE_CARD,
            storage_path="jobs/testjob1/visuals/va_01.svg",
        )


def test_visual_asset_schema_rejects_unsafe_storage_paths():
    """Verifies that non-relative or escaping paths are strictly rejected in schemas."""
    with pytest.raises(ValueError, match="prohibited path traversal"):
        VisualAsset(
            asset_id="va_01",
            job_id="job1",
            scene_id="scene-1",
            scene_number=1,
            visual_type=VisualType.TITLE_CARD,
            storage_path="/etc/passwd",
        )

    with pytest.raises(ValueError, match="prohibited path traversal"):
        VisualAsset(
            asset_id="va_01",
            job_id="job1",
            scene_id="scene-1",
            scene_number=1,
            visual_type=VisualType.TITLE_CARD,
            storage_path="jobs/job1/../../secret.svg",
        )


def test_scene_visual_assets_validation():
    """Verifies SceneVisualAssets validation rules."""
    asset = VisualAsset(
        asset_id="va_job1_s01_01",
        job_id="job1",
        scene_id="scene-1",
        scene_number=1,
        asset_type=VisualAssetType.TITLE_CARD,
        visual_type=VisualType.TITLE_CARD,
        storage_path="jobs/job1/visuals/va_job1_s01_01.svg",
    )
    scene_assets = SceneVisualAssets(
        scene_id="scene-1",
        scene_number=1,
        scene_title="Title Card",
        visual_type=VisualType.TITLE_CARD,
        visual_description="Description",
        primary_asset=asset,
    )
    assert scene_assets.total_assets_count == 1
    assert scene_assets.status == VisualGenerationStatus.PLANNED

    # Mismatched scene_id between SceneVisualAssets and primary_asset
    mismatched_asset = asset.model_copy(update={"scene_id": "different-scene"})
    with pytest.raises(ValueError, match="does not match SceneVisualAssets scene_id"):
        SceneVisualAssets(
            scene_id="scene-1",
            scene_number=1,
            scene_title="Title Card",
            visual_type=VisualType.TITLE_CARD,
            visual_description="Description",
            primary_asset=mismatched_asset,
        )


def test_visual_generation_result_validation():
    """Verifies VisualGenerationResult validation rules and constraints."""
    asset = VisualAsset(
        asset_id="va_job1_s01_01",
        job_id="job1",
        scene_id="scene-1",
        scene_number=1,
        visual_type=VisualType.TITLE_CARD,
        storage_path="jobs/job1/visuals/va_job1_s01_01.svg",
    )
    scene_assets = SceneVisualAssets(
        scene_id="scene-1",
        scene_number=1,
        scene_title="Title",
        visual_type=VisualType.TITLE_CARD,
        visual_description="Desc",
        primary_asset=asset,
    )
    result = VisualGenerationResult(
        job_id="job1",
        storyboard_id="sb-1",
        script_id="script-1",
        status=VisualGenerationStatus.PLANNED,
        total_scenes=1,
        scenes_completed=0,
        scenes_failed=0,
        total_assets=1,
        assets_pending=1,
        assets_completed=0,
        scene_assets=[scene_assets],
        storage_directory="jobs/job1/visuals",
    )
    assert result.status == VisualGenerationStatus.PLANNED
    assert result.video_orientation == VideoOrientation.LANDSCAPE
    assert not result.is_fully_rendered

    # Completed scenes cannot exceed total scenes
    with pytest.raises(ValueError, match="scenes_completed .* cannot exceed total_scenes"):
        VisualGenerationResult(
            job_id="job1",
            storyboard_id="sb-1",
            script_id="script-1",
            total_scenes=1,
            scenes_completed=5,
            scenes_failed=0,
            total_assets=1,
            scene_assets=[scene_assets],
            storage_directory="jobs/job1/visuals",
        )

    # Completed assets cannot exceed total assets
    with pytest.raises(ValueError, match="assets_completed .* cannot exceed total_assets"):
        VisualGenerationResult(
            job_id="job1",
            storyboard_id="sb-1",
            script_id="script-1",
            total_scenes=1,
            scenes_completed=0,
            scenes_failed=0,
            total_assets=1,
            assets_completed=5,
            scene_assets=[scene_assets],
            storage_directory="jobs/job1/visuals",
        )


# ---------------------------------------------------------------------------
# 2. Storage Manager Tests
# ---------------------------------------------------------------------------

def test_storage_manager_validation_and_path_resolution(tmp_path: Path):
    """Verifies strict boundary resolution and job_id/filename validation."""
    mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)

    # Valid job_id & filename
    assert mgr.validate_job_id("job-123_abc") == "job-123_abc"
    assert mgr.validate_filename("va_test.svg") == "va_test.svg"

    # Traversal attempts in job_id
    with pytest.raises(PathTraversalError):
        mgr.validate_job_id("../escaped")
    with pytest.raises(PathTraversalError):
        mgr.validate_job_id("/absolute")
    with pytest.raises(PathTraversalError):
        mgr.validate_job_id("job with spaces")

    # Traversal attempts in filename
    with pytest.raises(PathTraversalError):
        mgr.validate_filename("../secret.png")
    with pytest.raises(PathTraversalError):
        mgr.validate_filename("dir/file.svg")
    with pytest.raises(PathTraversalError):
        mgr.validate_filename("no_extension")

    # Relative paths
    rel_dir = mgr.get_relative_storage_dir("job-123")
    assert rel_dir == "jobs/job-123/visuals"
    rel_path = mgr.get_relative_asset_path("job-123", "scene_01.svg")
    assert rel_path == "jobs/job-123/visuals/scene_01.svg"


def test_storage_manager_file_operations(tmp_path: Path):
    """Verifies safe save, read, exists check, and atomic deletion."""
    mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)
    job_id = "job-safe-ops"

    # Initially file does not exist
    assert not mgr.asset_file_exists(job_id, "test.svg")

    # Save SVG string content
    svg_content = "<svg><circle cx='50' cy='50' r='40'/></svg>"
    saved_path = mgr.save_asset_content(job_id, "test.svg", svg_content)
    assert saved_path.is_file()
    assert mgr.asset_file_exists(job_id, "test.svg")

    # Read content
    read_bytes = mgr.read_asset_content(job_id, "test.svg")
    assert read_bytes == svg_content.encode("utf-8")

    # Delete job visuals directory
    assert mgr.delete_job_visuals(job_id) is True
    assert not mgr.asset_file_exists(job_id, "test.svg")
    assert mgr.delete_job_visuals(job_id) is False


# ---------------------------------------------------------------------------
# 3. VisualGenerationService Tests
# ---------------------------------------------------------------------------

def test_service_plan_visual_asset_for_scene():
    """Verifies mapping of StoryboardScene into PENDING VisualAsset blueprint."""
    script = _create_mock_script()
    storyboard = _create_mock_storyboard(script)
    scene = storyboard.scenes[1]  # Architecture scene

    service = VisualGenerationService()
    asset = service.plan_visual_asset_for_scene("job-plan-1", scene)

    assert asset.job_id == "job-plan-1"
    assert asset.scene_id == scene.scene_id
    assert asset.scene_number == 2
    assert asset.visual_type == VisualType.ARCHITECTURE_DIAGRAM
    assert asset.asset_type == VisualAssetType.ARCHITECTURE_DIAGRAM
    assert asset.media_format == MediaFormat.SVG
    assert asset.status == VisualAssetStatus.PENDING
    assert asset.storage_path == "jobs/job-plan-1/visuals/va_job-plan_s02_01.svg"
    assert asset.source_evidence == list(scene.evidence)
    assert asset.related_files == ["src/click/core.py"]


def test_service_initialize_visual_assets(tmp_path: Path):
    """Verifies that initialize_visual_assets produces a complete PLANNED blueprint."""
    mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)
    service = VisualGenerationService(storage_manager=mgr)

    script = _create_mock_script()
    storyboard = _create_mock_storyboard(script)

    result = service.initialize_visual_assets("job-init-1", storyboard, script=script)

    assert result.job_id == "job-init-1"
    assert result.storyboard_id == storyboard.storyboard_id
    assert result.script_id == script.script_id
    assert result.status == VisualGenerationStatus.PLANNED
    assert result.total_scenes == 2
    assert result.scenes_completed == 0
    assert result.scenes_failed == 0
    assert result.total_assets == 2
    assert result.assets_pending == 2
    assert result.assets_completed == 0
    assert result.assets_generating == 0
    assert result.assets_failed == 0
    assert len(result.scene_assets) == 2
    assert result.storage_directory == "jobs/job-init-1/visuals"

    # All scenes and assets are planned/pending
    for sa in result.scene_assets:
        assert sa.status == VisualGenerationStatus.PLANNED
        assert sa.primary_asset.status == VisualAssetStatus.PENDING

    # Directory was created on disk
    vis_dir = mgr.get_job_visuals_dir("job-init-1", create=False)
    assert vis_dir.is_dir()


def test_service_initialize_visual_assets_validation():
    """Verifies ValueError when storyboard is missing or has no scenes."""
    service = VisualGenerationService()
    with pytest.raises(ValueError, match="EducationalStoryboard is required"):
        service.initialize_visual_assets("job-1", None)

    empty_sb = EducationalStoryboard.model_construct(
        storyboard_id="sb-empty",
        script_id="sc-1",
        repository_name="test/repo",
        title="Empty",
        total_estimated_duration_seconds=10.0,
        scenes=[],
    )
    with pytest.raises(ValueError, match="at least one scene"):
        service.initialize_visual_assets("job-1", empty_sb)


# ---------------------------------------------------------------------------
# 4. JobStore Integration & Correct Lifecycle Tests
# ---------------------------------------------------------------------------

def test_visual_planning_does_not_mark_stage_completed_or_advance():
    """
    REGRESSION TEST:
    Verifies that initializing a visual asset plan:
    1. Keeps Stage 07 (Visual Generation) IN_PROGRESS (not COMPLETED).
    2. Does NOT set completed_at timestamp on Stage 07.
    3. Does NOT advance current_stage to Stage 08 (Voice Generation).
    4. Keeps all assets in PENDING status.
    """
    job_id, script, storyboard = _setup_job_with_storyboard("vg-plan-lifecycle")

    # Start planning
    job_store.update_job_visual_planning_started(job_id)
    j = job_store.get_job(job_id)
    assert j.stages[6].name == StageEnum.VISUAL_GENERATION.value
    assert j.stages[6].status == StatusEnum.IN_PROGRESS
    assert j.current_stage == StageEnum.VISUAL_GENERATION.value

    # Plan initialized
    blueprint = visual_generation_service.initialize_visual_assets(job_id, storyboard)
    job_store.update_job_visual_planning_success(job_id, blueprint)

    j_after = job_store.get_job(job_id)
    # Stage 07 MUST NOT be marked COMPLETED
    assert j_after.stages[6].status == StatusEnum.IN_PROGRESS
    assert j_after.stages[6].status != StatusEnum.COMPLETED
    assert j_after.stages[6].completed_at is None
    assert "pending rendering" in j_after.stages[6].detail

    # MUST NOT advance to Stage 08
    assert j_after.current_stage == StageEnum.VISUAL_GENERATION.value
    assert j_after.current_stage != StageEnum.VOICE_GENERATION.value
    assert j_after.stages[7].status == StatusEnum.PENDING

    # Visual assets remain pending
    assert j_after.visual_generation is not None
    assert j_after.visual_generation.status == VisualGenerationStatus.PLANNED
    assert j_after.visual_generation.assets_pending == 2
    assert j_after.visual_generation.assets_completed == 0
    assert j_after.visual_generation.scenes_completed == 0
    for sa in j_after.visual_generation.scene_assets:
        assert sa.primary_asset.status == VisualAssetStatus.PENDING


def test_stage_07_completed_only_when_all_assets_rendered():
    """
    REGRESSION TEST:
    Verifies that Stage 07 is only marked COMPLETED when all required visual assets
    have genuinely been rendered and completed.
    Attempting to mark visual generation complete while assets are pending raises ValueError.
    """
    job_id, script, storyboard = _setup_job_with_storyboard("vg-render-complete")
    blueprint = visual_generation_service.initialize_visual_assets(job_id, storyboard)
    job_store.update_job_visual_planning_success(job_id, blueprint)

    # Attempting to call visual generation success with pending assets MUST FAIL
    with pytest.raises(ValueError, match="Cannot mark visual generation as completed"):
        job_store.update_job_visual_generation_success(job_id, blueprint)

    # Simulate completed rendering of all scenes and assets
    completed_scene_assets = []
    for sa in blueprint.scene_assets:
        rendered_primary = sa.primary_asset.model_copy(
            update={"status": VisualAssetStatus.COMPLETED}
        )
        completed_sa = sa.model_copy(
            update={
                "status": VisualGenerationStatus.COMPLETED,
                "primary_asset": rendered_primary,
            }
        )
        completed_scene_assets.append(completed_sa)

    completed_result = blueprint.model_copy(
        update={
            "status": VisualGenerationStatus.COMPLETED,
            "scenes_completed": blueprint.total_scenes,
            "scenes_failed": 0,
            "assets_completed": blueprint.total_assets,
            "assets_pending": 0,
            "assets_generating": 0,
            "assets_failed": 0,
            "scene_assets": completed_scene_assets,
        }
    )
    assert completed_result.is_fully_rendered is True

    # Now update_job_visual_generation_success succeeds
    job_store.update_job_visual_generation_success(job_id, completed_result)
    j = job_store.get_job(job_id)

    # Stage 07 is legitimately COMPLETED
    assert j.stages[6].status == StatusEnum.COMPLETED
    assert j.stages[6].completed_at is not None
    assert "Rendered all visual assets" in j.stages[6].detail

    # Advances to Stage 08 (Voice Generation)
    assert j.current_stage == StageEnum.VOICE_GENERATION.value
    assert j.stages[7].detail == "Ready for voice generation"


def test_failed_asset_prevents_premature_completion():
    """
    REGRESSION TEST:
    Verifies that a failure during visual rendering marks Stage 07 as FAILED
    and does NOT advance to Stage 08.
    """
    job_id, script, storyboard = _setup_job_with_storyboard("vg-fail")
    blueprint = visual_generation_service.initialize_visual_assets(job_id, storyboard)
    job_store.update_job_visual_planning_success(job_id, blueprint)

    # Calling update_job_visual_generation_failed
    job_store.update_job_visual_generation_failed(job_id, "SVG rendering timed out")
    j = job_store.get_job(job_id)

    assert j.stages[6].status == StatusEnum.FAILED
    assert "SVG rendering timed out" in j.stages[6].detail
    assert j.current_stage == StageEnum.VISUAL_GENERATION.value
    assert j.current_stage != StageEnum.VOICE_GENERATION.value
    assert j.stages[7].status == StatusEnum.PENDING


def test_invalidation_cascade_storyboard_invalidates_visuals(tmp_path: Path):
    """
    Verifies that when a storyboard is regenerated or invalidated:
    1. Previous visual assets in JobStore are wiped.
    2. Visual asset files on disk are deleted.
    3. Stage 7 is reset to PENDING.
    """
    job_id, script, storyboard = _setup_job_with_storyboard("sb-inv-vg")

    # Setup visual assets and create a file on disk
    blueprint = visual_generation_service.initialize_visual_assets(job_id, storyboard)
    job_store.update_job_visual_planning_success(job_id, blueprint)

    # Manually save a file to disk to verify it gets deleted
    visual_storage_manager.save_asset_content(job_id, "va_test.svg", "<svg></svg>")
    assert visual_storage_manager.asset_file_exists(job_id, "va_test.svg")

    # Invalidate storyboard
    job_store.invalidate_job_educational_storyboard(job_id)

    # Verify visual generation is reset
    j = job_store.get_job(job_id)
    assert j.has_visual_assets is False
    assert j.visual_generation is None
    assert j.stages[6].status == StatusEnum.PENDING

    # Verify disk files are purged
    assert not visual_storage_manager.asset_file_exists(job_id, "va_test.svg")


def test_invalidation_cascade_script_invalidates_storyboard_and_visuals():
    """
    Verifies that refreshing or invalidating an educational script cascades to:
    1. Invalidating the educational storyboard.
    2. Invalidating visual assets and wiping disk visuals.
    3. Resetting Stage 5, Stage 6, and Stage 7 to PENDING.
    """
    job_id, script, storyboard = _setup_job_with_storyboard("sc-inv-vg")

    blueprint = visual_generation_service.initialize_visual_assets(job_id, storyboard)
    job_store.update_job_visual_planning_success(job_id, blueprint)

    visual_storage_manager.save_asset_content(job_id, "va_test2.svg", "<svg></svg>")
    assert visual_storage_manager.asset_file_exists(job_id, "va_test2.svg")

    # Invalidate script
    job_store.invalidate_job_educational_script(job_id)

    j = job_store.get_job(job_id)
    assert j.has_educational_script is False
    assert j.educational_script is None
    assert j.has_educational_storyboard is False
    assert j.educational_storyboard is None
    assert j.has_visual_assets is False
    assert j.visual_generation is None
    assert j.stages[4].status == StatusEnum.PENDING  # Stage 5: Educational Script
    assert j.stages[5].status == StatusEnum.PENDING  # Stage 6: Educational Storyboard
    assert j.stages[6].status == StatusEnum.PENDING  # Stage 7: Visual Generation

    # Disk visuals deleted
    assert not visual_storage_manager.asset_file_exists(job_id, "va_test2.svg")


# ---------------------------------------------------------------------------
# 5. FastAPI Endpoints Tests
# ---------------------------------------------------------------------------

def test_post_visual_assets_missing_job():
    """POST /visual-assets returns 404 for non-existent job."""
    resp = client.post("/api/v1/jobs/nonexistent-job-id/visual-assets")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_post_visual_assets_missing_storyboard_prerequisite():
    """POST /visual-assets returns 409 Conflict if storyboard has not been generated."""
    job_id, script, _ = _setup_job_with_storyboard("no-sb")
    job_store.invalidate_job_educational_storyboard(job_id)
    resp = client.post(f"/api/v1/jobs/{job_id}/visual-assets")
    assert resp.status_code == 409
    assert "educational storyboard must be generated" in resp.json()["detail"].lower()


def test_post_and_get_visual_assets_success():
    """
    POST /visual-assets generates plan, GET retrieves it.
    Verifies that:
    - Status is 'planned' (not completed).
    - Assets are reported as pending rendering.
    - Stage 07 is IN_PROGRESS (not COMPLETED).
    - Pipeline remains at Stage 07 (does NOT advance to Stage 08).
    - Unrendered files return 404 and are not claimed to exist.
    """
    job_id, script, storyboard = _setup_job_with_storyboard("post-get-vg")

    # 1. POST generation (Planning and Technical Diagram Rendering)
    resp = client.post(f"/api/v1/jobs/{job_id}/visual-assets")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] in ("generating", "planned")
    assert data["total_scenes"] == 2
    assert data["total_assets"] == 2
    assert data["assets_pending"] == 1
    assert data["assets_completed"] == 1
    assert data["scenes_completed"] == 1
    assert len(data["scene_assets"]) == 2

    # Verify JobStore state: Stage 07 must remain IN_PROGRESS, pipeline remains at Stage 07
    j = job_store.get_job(job_id)
    assert j.stages[6].status == StatusEnum.IN_PROGRESS
    assert j.stages[6].status != StatusEnum.COMPLETED
    assert j.stages[6].completed_at is None
    assert j.current_stage == StageEnum.VISUAL_GENERATION.value
    assert j.current_stage != StageEnum.VOICE_GENERATION.value

    # 2. GET retrieval
    get_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["job_id"] == job_id
    assert get_data["total_assets"] == 2
    assert get_data["assets_pending"] == 1
    assert get_data["assets_completed"] == 1

    # 3. Scene 1 is TITLE_CARD (pending rendering in later phase)
    scene1_asset_id = data["scene_assets"][0]["primary_asset"]["asset_id"]
    asset1_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets/{scene1_asset_id}")
    assert asset1_resp.status_code == 200
    assert asset1_resp.json()["status"] == "pending"

    # GET asset 1 file before rendering returns 404 (does not pretend file exists)
    file1_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets/{scene1_asset_id}/file")
    assert file1_resp.status_code == 404
    assert "has not yet been rendered to disk" in file1_resp.json()["detail"]

    # 4. Scene 2 is ARCHITECTURE_DIAGRAM (rendered in Phase 5.2!)
    scene2_asset_id = data["scene_assets"][1]["primary_asset"]["asset_id"]
    asset2_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets/{scene2_asset_id}")
    assert asset2_resp.status_code == 200
    assert asset2_resp.json()["status"] == "completed"

    # GET asset 2 file returns HTTP 200 with real SVG content on disk
    file2_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets/{scene2_asset_id}/file")
    assert file2_resp.status_code == 200
    assert "image/svg+xml" in file2_resp.headers["content-type"]
    assert b"<svg" in file2_resp.content

    # 5. GET non-existent asset metadata returns 404
    non_asset_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets/va_unknown")
    assert non_asset_resp.status_code == 404


def test_get_visual_assets_not_generated():
    """GET /visual-assets returns 404 when not yet generated."""
    job_id, _, _ = _setup_job_with_storyboard("not-yet-gen")
    resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets")
    assert resp.status_code == 404
    assert "not yet been initialized" in resp.json()["detail"]


def test_refresh_query_param_on_post():
    """POST /visual-assets with refresh=true cleans previous assets."""
    job_id, script, storyboard = _setup_job_with_storyboard("refresh-vg")

    # Initial POST
    resp1 = client.post(f"/api/v1/jobs/{job_id}/visual-assets")
    assert resp1.status_code == 200

    # Save a temporary file
    visual_storage_manager.save_asset_content(job_id, "temp.svg", "<svg/>")
    assert visual_storage_manager.asset_file_exists(job_id, "temp.svg")

    # POST with refresh=true
    resp2 = client.post(f"/api/v1/jobs/{job_id}/visual-assets?refresh=true")
    assert resp2.status_code == 200
    # temp.svg was purged by refresh
    assert not visual_storage_manager.asset_file_exists(job_id, "temp.svg")
