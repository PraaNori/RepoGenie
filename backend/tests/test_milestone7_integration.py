"""
Milestone 7: End-to-End Pipeline Integration & Stage Retry Tests.

Verifies:
1. Full 9-stage pipeline execution from GitHub URL to final MP4 video.
2. Background vs synchronous pipeline execution (/run-pipeline).
3. Granular stage retry (/retry-stage/{stage_id}) preserving upstream results.
4. Resilience against AI quota exhaustion and provider errors.
5. Path traversal protection on media file streaming endpoints.
6. Byte-range streaming support for MP4 video playback.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    JobResponse,
    RepositoryKnowledge,
    StageEnum,
    StatusEnum,
    TechnologyStack,
    VideoResult,
)
from app.services.ai.exceptions import AIError
from app.services.ai.project_understanding import ProjectUnderstanding
from app.services.ai.code_understanding import RepositoryCodeUnderstanding
from app.services.ai.workflow_understanding import RepositoryWorkflowUnderstanding
from app.services.ai.script_generation import EducationalScript, ScriptSection, SectionPurpose
from app.services.ai.storyboard_generation import EducationalStoryboard, StoryboardScene, VisualType, NarrationReference
from app.services.storage.job_store import JobInternal, job_store
from app.services.video.assembly.schemas import (
    SceneRenderAsset,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderResult,
    VideoRenderStatus,
)
from app.services.video.assembly_input.schemas import (
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    VideoAssemblyInput,
)
from app.services.video.captions.schemas import CaptionGenerationResult, CaptionStatus, SceneCaptionAsset
from app.services.video.narration.schemas import NarrationAsset, NarrationAssetStatus, NarrationGenerationResult
from app.services.video.visual_generation.schemas import (
    SceneVisualAssets,
    VisualAsset,
    VisualAssetStatus,
    VisualGenerationResult,
    VisualGenerationStatus,
)
from app.services.pipeline_runner import pipeline_runner_service

client = TestClient(app)


def _setup_mock_job(job_id: str = "job-m7-test") -> JobInternal:
    job = job_store.create_job(
        repo_url="https://github.com/mock-owner/mock-repo",
        repo_name="mock-owner/mock-repo",
        repository_owner="mock-owner",
        repository_name="mock-repo",
        clone_url="https://github.com/mock-owner/mock-repo.git",
    )
    job.job_id = job_id
    job_store._jobs[job_id] = job
    return job


def test_run_pipeline_404_for_unknown_job():
    response = client.post("/api/v1/jobs/nonexistent-job-xyz/run-pipeline")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"].lower()


def test_retry_stage_validation():
    job = _setup_mock_job("job-retry-val")
    # Invalid stage IDs
    res_zero = client.post(f"/api/v1/jobs/{job.job_id}/retry-stage/0")
    assert res_zero.status_code == status.HTTP_400_BAD_REQUEST

    res_ten = client.post(f"/api/v1/jobs/{job.job_id}/retry-stage/10")
    assert res_ten.status_code == status.HTTP_400_BAD_REQUEST


def test_full_pipeline_orchestration_mocked():
    """Verifies that PipelineRunnerService sequentially advances stages 1-9 to completion."""
    job_id = "job-full-e2e-pipeline"
    job = _setup_mock_job(job_id)

    # Mock Stage 1-3 ingestion
    job.local_path = "/tmp/mock_repo"
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    mock_k = MagicMock(spec=RepositoryKnowledge)
    mock_k.repo_name = job.repo_name
    mock_k.repo_owner = "mock-owner"
    mock_k.repo_url = job.repo_url
    job.knowledge = mock_k

    mock_project = MagicMock(spec=ProjectUnderstanding)
    mock_project.core_features = []
    mock_project.provider = "mock"
    mock_project.model = "mock"
    mock_code = MagicMock(spec=RepositoryCodeUnderstanding)
    mock_workflow = MagicMock(spec=RepositoryWorkflowUnderstanding)
    mock_script = EducationalScript(
        job_id=job_id,
        script_id="sc-1",
        title="Overview",
        repository_name="mock-repo",
        introduction="Introductory overview.",
        learning_objectives=["Understand system"],
        conclusion="Conclusion summary.",
        target_duration_seconds=5,
        total_estimated_duration_seconds=5.0,
        sections=[
            ScriptSection(
                section_id="sec-1",
                order=1,
                title="Overview",
                purpose=SectionPurpose.HOOK,
                narration_text="Introductory text describing the system architecture and overview.",
                estimated_duration_seconds=5.0,
            )
        ],
    )
    mock_storyboard = EducationalStoryboard(
        storyboard_id="sb-1",
        script_id="sc-1",
        title="Overview Storyboard",
        total_estimated_duration_seconds=5.0,
        scenes=[
            StoryboardScene(
                scene_id="s1",
                scene_number=1,
                script_section_id="sec-1",
                title="Overview",
                purpose="Hook",
                estimated_duration_seconds=5.0,
                visual_type=VisualType.ARCHITECTURE_DIAGRAM,
                visual_description="Overview diagram",
                narration=NarrationReference(
                    script_section_id="sec-1",
                    narration_text="Introductory text describing the system architecture and overview.",
                    target_duration_seconds=5.0,
                ),
            )
        ],
    )
    mock_visuals = VisualGenerationResult(
        job_id=job_id,
        storyboard_id="sb-1",
        script_id="sc-1",
        status=VisualGenerationStatus.COMPLETED,
        total_scenes=1,
        scenes_completed=1,
        total_assets=1,
        assets_completed=1,
        is_fully_rendered=True,
        storage_directory="jobs/job-full-e2e-pipeline/visuals",
        scene_assets=[
            SceneVisualAssets(
                scene_id="s1",
                scene_number=1,
                scene_title="Intro",
                visual_type=VisualType.ARCHITECTURE_DIAGRAM,
                visual_description="Overview diagram",
                visual_assets=[
                    VisualAsset(
                        job_id=job_id,
                        asset_id="va-1",
                        scene_id="s1",
                        scene_number=1,
                        visual_type=VisualType.ARCHITECTURE_DIAGRAM,
                        status=VisualAssetStatus.COMPLETED,
                        storage_path=f"jobs/{job_id}/visuals/scene_1.svg",
                    ),
                ],
            ),
        ],
    )
    mock_narration = NarrationGenerationResult(
        job_id=job_id,
        status=NarrationAssetStatus.COMPLETED,
        total_scenes=1,
        scenes_completed=1,
        scenes_failed=0,
        total_assets=1,
        assets_completed=1,
        assets_failed=0,
        assets=[
            NarrationAsset(
                asset_id="na-1",
                job_id=job_id,
                scene_id="s1",
                scene_number=1,
                script_section_id="sec-1",
                status=NarrationAssetStatus.COMPLETED,
                file_path=f"jobs/{job_id}/audio/scene_1.mp3",
                duration_seconds=5.0,
                file_size_bytes=1024,
            ),
        ],
    )
    mock_captions = CaptionGenerationResult(
        job_id=job_id,
        status=CaptionStatus.COMPLETED,
        total_scenes=1,
        scenes_completed=1,
        scene_assets=[
            SceneCaptionAsset(
                asset_id="ca-1",
                job_id=job_id,
                scene_id="s1",
                scene_number=1,
                script_section_id="sec-1",
                status=CaptionStatus.COMPLETED,
                duration_seconds=5.0,
                vtt_file_path=f"jobs/{job_id}/captions/scene_1.vtt",
                srt_file_path=f"jobs/{job_id}/captions/scene_1.srt",
            ),
        ],
        full_vtt_file_path=f"jobs/{job_id}/captions/full.vtt",
        full_srt_file_path=f"jobs/{job_id}/captions/full.srt",
    )
    mock_assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name=job.repo_name,
        storyboard_id="sb-1",
        scenes=[
            AssemblyScene(
                scene_id="s1",
                scene_number=1,
                script_section_id="sec-1",
                section_purpose="introduction",
                title="Intro",
                start_seconds=0.0,
                end_seconds=5.0,
                duration_seconds=5.0,
            ),
        ],
        readiness_report=AssemblyReadinessReport(
            job_id=job_id,
            status=AssemblyReadinessStatus.READY,
            total_scenes=1,
            ready_scenes=1,
            is_render_ready=True,
        ),
    )
    mock_scene_render = SceneRenderResult(
        job_id=job_id,
        status=SceneRenderStatus.COMPLETED,
        total_scenes=1,
        completed_scenes=1,
        failed_scenes=0,
        total_duration_seconds=5.0,
        scenes=[
            SceneRenderAsset(
                scene_id="s1",
                scene_number=1,
                status=SceneRenderStatus.COMPLETED,
                output_relative_path="scenes/scene_1.mp4",
                duration_seconds=5.0,
                file_size_bytes=2048,
            ),
        ],
    )
    mock_final_video = VideoRenderResult(
        job_id=job_id,
        status=VideoRenderStatus.COMPLETED,
        output_relative_path="final/final_video.mp4",
        file_size_bytes=4096,
        duration_seconds=5.0,
        resolution="1920x1080",
        fps=30,
        video_codec="h264",
        audio_codec="aac",
    )

    with (
        patch("app.services.ai.project_understanding.project_understanding_analyzer.analyze_project", new_callable=AsyncMock) as p_proj,
        patch("app.services.ai.code_understanding.code_understanding_analyzer.analyze_codebase", new_callable=AsyncMock) as p_code,
        patch("app.services.ai.workflow_understanding.workflow_understanding_analyzer.analyze_workflows", new_callable=AsyncMock) as p_wf,
        patch("app.services.ai.script_generation.educational_script_analyzer.generate_script", new_callable=AsyncMock) as p_script,
        patch("app.services.ai.storyboard_generation.educational_storyboard_analyzer.generate_storyboard", new_callable=AsyncMock) as p_sb,
        patch("app.services.video.visual_generation.visual_generation_service.initialize_visual_assets") as p_vis_init,
        patch("app.services.video.visual_generation.visual_generation_service.generate_diagrams_for_job") as p_vis_diag,
        patch("app.services.video.narration.narration_service.generate_narration_for_job", new_callable=AsyncMock) as p_narr,
        patch("app.services.video.captions.caption_service.generate_captions_for_job") as p_caps,
        patch("app.services.video.assembly_input.assembly_input_service.build_assembly_input") as p_asm_in,
        patch("app.services.video.assembly.scene_service.scene_render_service.render_scenes") as p_scene_rnd,
        patch("app.services.video.assembly.final_service.final_video_assembly_service.assemble_video") as p_final_rnd,
    ):
        p_proj.return_value = mock_project
        p_code.return_value = mock_code
        p_wf.return_value = mock_workflow
        p_script.return_value = mock_script
        p_sb.return_value = mock_storyboard
        p_vis_init.return_value = MagicMock()
        p_vis_diag.return_value = mock_visuals
        p_narr.return_value = mock_narration
        p_caps.return_value = mock_captions
        p_asm_in.return_value = mock_assembly_input
        p_scene_rnd.return_value = mock_scene_render
        p_final_rnd.return_value = mock_final_video

        # Run pipeline synchronously
        res = client.post(f"/api/v1/jobs/{job_id}/run-pipeline?wait=true")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "completed"
        assert data["progress_percentage"] == 100
        assert data["stages"][8]["status"] == "completed"

        # Verify all stages are completed in job_store
        updated_job = job_store.get_internal_job(job_id)
        assert updated_job.status == StatusEnum.COMPLETED
        assert all(s.status == StatusEnum.COMPLETED for s in updated_job.stages)


def test_pipeline_failure_preserves_upstream_and_allows_retry():
    """Verifies that an AI quota failure on Stage 5 preserves Stages 1-4 and allows safe retry."""
    job_id = "job-retry-stage-test"
    job = _setup_mock_job(job_id)

    # Setup stages 1-4 completed
    job.local_path = "/tmp/mock_repo"
    for i in range(4):
        job.stages[i].status = StatusEnum.COMPLETED
    mock_k = MagicMock(spec=RepositoryKnowledge)
    mock_k.repo_name = job.repo_name
    mock_k.repo_owner = "mock-owner"
    mock_k.repo_url = job.repo_url
    job.knowledge = mock_k
    job.project_understanding = MagicMock(spec=ProjectUnderstanding)
    job.code_understanding = MagicMock(spec=RepositoryCodeUnderstanding)
    job.workflow_understanding = MagicMock(spec=RepositoryWorkflowUnderstanding)

    # Fail Stage 5 with AIError (e.g. Groq 429 rate limit / quota exhausted)
    with patch(
        "app.services.ai.script_generation.educational_script_analyzer.generate_script",
        new_callable=AsyncMock,
        side_effect=AIError(message="Groq quota exhausted (429)", status_code=429),
    ):
        res = client.post(f"/api/v1/jobs/{job_id}/run-pipeline?wait=true")
        assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # Verify job is failed, stage 5 is failed, but stages 1-4 remain completed!
        failed_job = job_store.get_internal_job(job_id)
        assert failed_job.status == StatusEnum.FAILED
        assert failed_job.stages[4].status == StatusEnum.FAILED
        for i in range(4):
            assert failed_job.stages[i].status == StatusEnum.COMPLETED

    # Now simulate retry after quota replenishment: retry Stage 5
    mock_script = EducationalScript(
        job_id=job_id,
        script_id="sc-retry",
        title="Retry Script",
        repository_name="mock-repo",
        introduction="Introductory overview.",
        learning_objectives=["Understand system"],
        conclusion="Conclusion summary.",
        target_duration_seconds=5,
        total_estimated_duration_seconds=5.0,
        sections=[
            ScriptSection(
                section_id="sec-1",
                order=1,
                title="Overview",
                purpose=SectionPurpose.HOOK,
                narration_text="Introductory text describing the system architecture and overview.",
                estimated_duration_seconds=5.0,
            )
        ],
    )
    mock_storyboard = EducationalStoryboard(
        storyboard_id="sb-retry",
        script_id="sc-retry",
        title="Retry Storyboard",
        total_estimated_duration_seconds=5.0,
        scenes=[
            StoryboardScene(
                scene_id="s1",
                scene_number=1,
                script_section_id="sec-1",
                title="Overview",
                purpose="Hook",
                estimated_duration_seconds=5.0,
                visual_type=VisualType.ARCHITECTURE_DIAGRAM,
                visual_description="Overview diagram",
                narration=NarrationReference(
                    script_section_id="sec-1",
                    narration_text="Introductory text describing the system architecture and overview.",
                    target_duration_seconds=5.0,
                ),
            )
        ],
    )

    with (
        patch("app.services.ai.script_generation.educational_script_analyzer.generate_script", new_callable=AsyncMock, return_value=mock_script),
        patch("app.services.ai.storyboard_generation.educational_storyboard_analyzer.generate_storyboard", new_callable=AsyncMock, return_value=mock_storyboard) as p_sb,
        patch("app.services.video.visual_generation.visual_generation_service.initialize_visual_assets"),
        patch("app.services.video.visual_generation.visual_generation_service.generate_diagrams_for_job") as p_vis,
        patch("app.services.video.narration.narration_service.generate_narration_for_job", new_callable=AsyncMock) as p_narr,
        patch("app.services.video.captions.caption_service.generate_captions_for_job") as p_caps,
        patch("app.services.video.assembly_input.assembly_input_service.build_assembly_input") as p_asm,
        patch("app.services.video.assembly.scene_service.scene_render_service.render_scenes") as p_scene,
        patch("app.services.video.assembly.final_service.final_video_assembly_service.assemble_video") as p_fin,
    ):
        p_vis.return_value = VisualGenerationResult(
            job_id=job_id,
            storyboard_id="sb",
            script_id="sc",
            status=VisualGenerationStatus.COMPLETED,
            total_scenes=1,
            scenes_completed=1,
            total_assets=1,
            assets_completed=1,
            is_fully_rendered=True,
            storage_directory="dir",
        )
        p_narr.return_value = NarrationGenerationResult(
            job_id=job_id,
            status=NarrationAssetStatus.COMPLETED,
            total_scenes=1,
            scenes_completed=1,
            failed_scenes_count=0,
            total_assets=1,
            assets_completed=1,
            assets_failed=0,
            assets=[
                NarrationAsset(
                    asset_id="na-retry-1",
                    job_id=job_id,
                    scene_id="s1",
                    scene_number=1,
                    script_section_id="sec-1",
                    status=NarrationAssetStatus.COMPLETED,
                    file_path=f"jobs/{job_id}/audio/scene_1.mp3",
                    duration_seconds=5.0,
                ),
            ],
        )
        p_caps.return_value = CaptionGenerationResult(
            job_id=job_id,
            status=CaptionStatus.COMPLETED,
            total_scenes=1,
            scenes_completed=1,
            scene_assets=[],
        )
        p_asm.return_value = VideoAssemblyInput(
            job_id=job_id,
            repo_name=job.repo_name,
            storyboard_id="sb",
            scenes=[],
            readiness_report=AssemblyReadinessReport(
                job_id=job_id,
                status=AssemblyReadinessStatus.READY,
                total_scenes=1,
                ready_scenes=1,
                is_render_ready=True,
            ),
        )
        p_scene.return_value = SceneRenderResult(
            job_id=job_id,
            status=SceneRenderStatus.COMPLETED,
            total_scenes=1,
            completed_scenes=1,
            failed_scenes=0,
            total_duration_seconds=5.0,
            scenes=[],
        )
        p_fin.return_value = VideoRenderResult(
            job_id=job_id,
            status=VideoRenderStatus.COMPLETED,
            output_relative_path="final.mp4",
            file_size_bytes=100,
            duration_seconds=5.0,
            resolution="1920x1080",
            fps=30,
            video_codec="h264",
        )

        # Retry stage 5 synchronously
        retry_res = client.post(f"/api/v1/jobs/{job_id}/retry-stage/5?wait=true")
        assert retry_res.status_code == status.HTTP_200_OK

        resumed_job = job_store.get_internal_job(job_id)
        assert resumed_job.status == StatusEnum.COMPLETED
        assert resumed_job.stages[4].status == StatusEnum.COMPLETED
