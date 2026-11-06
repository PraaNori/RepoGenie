"""
Milestone 5, Phase 5.6 Automated Test Suite: Video Assembly Input Package & Preflight Validation.

Tests cover:
1. Schema model instantiation, validation, and serialization.
2. Physical disk asset inspection (valid/invalid SVGs, MP3s, SRTs, VTTs, zero-byte and non-existent files).
3. Path traversal defense and isolation enforcement.
4. Sequential monotonic timeline ordering and continuity (detecting gaps and overlaps).
5. Cross-asset synchronization and duration consistency (matching narration audio, silent scene handling).
6. Overall package classification (READY, READY_WITH_WARNINGS, NOT_READY).
7. JobStore lifecycle methods and invalidation cascade.
8. FastAPI endpoints: POST/GET assembly-input, GET assembly-readiness, error handling and locking.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import StageEnum, StatusEnum
from app.services.ai.script_generation.schemas import EducationalScript, ScriptSection, SectionPurpose
from app.services.ai.storyboard_generation.schemas import (
    EducationalStoryboard,
    StoryboardScene,
    VisualType,
)
from app.services.storage.job_store import job_store
from app.services.video.assembly_input.schemas import (
    AssemblyAssetReference,
    AssemblyIssueSeverity,
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    AssemblyValidationIssue,
    VideoAssemblyInput,
)
from app.services.video.assembly_input.service import AssemblyInputService, assembly_input_service
from app.services.video.assembly_input.validator import AssemblyPreflightValidator, preflight_validator
from app.services.video.captions.schemas import CaptionGenerationResult, CaptionStatus, SceneCaptionAsset
from app.services.video.narration.schemas import NarrationAsset, NarrationAssetStatus, NarrationGenerationResult
from app.services.video.visual_generation.schemas import VisualAsset, VisualAssetStatus, VisualGenerationResult

client = TestClient(app)

SAMPLE_VALID_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" width="1920" height="1080">
  <rect width="1920" height="1080" fill="#1e293b"/>
  <text x="960" y="540" fill="#ffffff" font-size="48" text-anchor="middle">Test Scene Visual</text>
</svg>"""

SAMPLE_INVALID_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500">
  <rect width="500" height="500" fill="#ff0000"/>
</svg>"""

SAMPLE_CORRUPT_XML = """<svg><rect></svg>"""

SAMPLE_VALID_SRT = """1
00:00:00,000 --> 00:00:04,500
This is a test subtitle.

2
00:00:04,500 --> 00:00:08,000
Second subtitle cue.
"""

SAMPLE_VALID_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:04.500
This is a test subtitle.

2
00:00:04.500 --> 00:00:08.000
Second subtitle cue.
"""

SAMPLE_MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x20" + b"\xff\xfb\x90\x64" + b"\x00" * 2000


@pytest.fixture
def temp_storage():
    """Isolated temporary storage directory for physical asset tests."""
    temp_dir = tempfile.mkdtemp(prefix="repogenie_assembly_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_storyboard():
    """Generates a standard 2-scene educational storyboard fixture."""
    return EducationalStoryboard(
        storyboard_id="storyboard-test-1",
        script_id="script-test-1",
        title="Test Storyboard",
        total_estimated_duration_seconds=12.0,
        scenes=[
            StoryboardScene(
                scene_id="scene-1",
                scene_number=1,
                script_section_id="sec-1",
                title="Introduction Scene",
                purpose="hook_introduction",
                estimated_duration_seconds=5.0,
                visual_type=VisualType.TITLE_CARD,
                visual_description="Title card for introduction.",
                transition_to_next="Fade to architecture.",
            ),
            StoryboardScene(
                scene_id="scene-2",
                scene_number=2,
                script_section_id="sec-2",
                title="Architecture Scene",
                purpose="architecture_overview",
                estimated_duration_seconds=7.0,
                visual_type=VisualType.ARCHITECTURE_DIAGRAM,
                visual_description="High-level architecture diagram.",
                transition_to_next=None,
            ),
        ],
    )


# ==============================================================================
# 1. Schema Validation Tests
# ==============================================================================

def test_assembly_validation_issue_schema():
    issue = AssemblyValidationIssue(
        code="MISSING_VISUAL",
        severity=AssemblyIssueSeverity.BLOCKING,
        message="Visual asset is missing.",
        scene_id="scene-1",
        scene_number=1,
    )
    assert issue.code == "MISSING_VISUAL"
    assert issue.severity == AssemblyIssueSeverity.BLOCKING
    assert issue.scene_number == 1


def test_assembly_asset_reference_schema():
    ref = AssemblyAssetReference(
        asset_id="vis_asset_1",
        scene_id="scene-1",
        asset_type="visual",
        relative_path="jobs/job-1/visuals/vis_asset_1.svg",
        file_format="svg",
        file_size_bytes=1024,
        is_valid=True,
    )
    assert ref.asset_id == "vis_asset_1"
    assert ref.file_format == "svg"
    assert ref.is_valid is True


def test_assembly_scene_timing_validation():
    scene = AssemblyScene(
        scene_id="scene-1",
        scene_number=1,
        script_section_id="sec-1",
        section_purpose="hook_introduction",
        title="Scene 1",
        start_seconds=0.0,
        end_seconds=5.0,
        duration_seconds=5.0,
    )
    assert scene.duration_seconds == 5.0

    # Inverted timeline boundaries must raise ValueError
    with pytest.raises(ValueError):
        AssemblyScene(
            scene_id="scene-invalid",
            scene_number=1,
            script_section_id="sec-1",
            section_purpose="hook_introduction",
            title="Invalid",
            start_seconds=10.0,
            end_seconds=5.0,
            duration_seconds=5.0,
        )


# ==============================================================================
# 2. Physical Disk Inspection & Format Verification
# ==============================================================================

def test_validate_visual_file_valid_svg(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    svg_file = temp_storage / "test_scene.svg"
    svg_file.write_text(SAMPLE_VALID_SVG, encoding="utf-8")

    is_valid, err, size = validator.validate_visual_file(svg_file)
    assert is_valid is True
    assert err is None
    assert size == len(SAMPLE_VALID_SVG)


def test_validate_visual_file_invalid_aspect_ratio(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    svg_file = temp_storage / "square_scene.svg"
    svg_file.write_text(SAMPLE_INVALID_SVG, encoding="utf-8")

    is_valid, err, size = validator.validate_visual_file(svg_file)
    assert is_valid is False
    assert "aspect ratio" in err.lower()


def test_validate_visual_file_corrupt_xml(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    svg_file = temp_storage / "corrupt.svg"
    svg_file.write_text(SAMPLE_CORRUPT_XML, encoding="utf-8")

    is_valid, err, size = validator.validate_visual_file(svg_file)
    assert is_valid is False
    assert "malformed" in err.lower()


def test_validate_visual_file_empty_and_nonexistent(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    empty_file = temp_storage / "empty.svg"
    empty_file.write_text("", encoding="utf-8")

    is_valid, err, size = validator.validate_visual_file(empty_file)
    assert is_valid is False
    assert "empty" in err.lower()

    non_existent = temp_storage / "non_existent.svg"
    is_valid, err, size = validator.validate_visual_file(non_existent)
    assert is_valid is False
    assert "does not exist" in err.lower()


def test_validate_audio_file_valid_mp3(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    audio_file = temp_storage / "test_audio.mp3"
    audio_file.write_bytes(SAMPLE_MP3_BYTES)

    with patch("app.services.video.narration.audio_storage.audio_storage_manager.measure_audio_duration", return_value=4.5):
        is_valid, err, size, dur = validator.validate_audio_file(audio_file)
        assert is_valid is True
        assert err is None
        assert dur == 4.5
        assert size == len(SAMPLE_MP3_BYTES)


def test_validate_audio_file_corrupt_header(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    audio_file = temp_storage / "corrupt_audio.mp3"
    audio_file.write_bytes(b"CORRUPT_HEADER_BYTES_NOT_AN_MP3")

    is_valid, err, size, dur = validator.validate_audio_file(audio_file)
    assert is_valid is False
    assert "lacks valid mp3 header" in err.lower()


def test_validate_caption_file_srt_and_vtt(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)

    srt_file = temp_storage / "test.srt"
    srt_file.write_text(SAMPLE_VALID_SRT, encoding="utf-8")
    is_valid, err, size = validator.validate_caption_file(srt_file, format="srt")
    assert is_valid is True
    assert err is None

    vtt_file = temp_storage / "test.vtt"
    vtt_file.write_text(SAMPLE_VALID_VTT, encoding="utf-8")
    is_valid, err, size = validator.validate_caption_file(vtt_file, format="vtt")
    assert is_valid is True
    assert err is None


def test_validate_caption_file_malformed(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    malformed_vtt = temp_storage / "bad.vtt"
    malformed_vtt.write_text("NOT_A_WEBVTT_HEADER\n\n1\n00:00:00.000 --> 00:00:01.000\nHello", encoding="utf-8")

    is_valid, err, size = validator.validate_caption_file(malformed_vtt, format="vtt")
    assert is_valid is False
    assert "malformed" in err.lower()


# ==============================================================================
# 3. Path Traversal & Isolation Defense
# ==============================================================================

def test_path_traversal_rejection(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)
    escaped_path = temp_storage / ".." / ".." / "etc" / "passwd"

    with pytest.raises(ValueError) as excinfo:
        validator.assert_safe_path(escaped_path)
    assert "Path traversal attempt" in str(excinfo.value)


# ==============================================================================
# 4. Timeline Continuity & Cross-Asset Synchronization
# ==============================================================================

def test_evaluate_package_ready(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)

    vis1 = temp_storage / "scene1.svg"
    vis1.write_text(SAMPLE_VALID_SVG, encoding="utf-8")
    vis2 = temp_storage / "scene2.svg"
    vis2.write_text(SAMPLE_VALID_SVG, encoding="utf-8")

    scene1 = AssemblyScene(
        scene_id="scene-1",
        scene_number=1,
        script_section_id="sec-1",
        section_purpose="hook",
        title="Scene 1",
        start_seconds=0.0,
        end_seconds=5.0,
        duration_seconds=5.0,
        visual_asset=AssemblyAssetReference(
            asset_id="v1", scene_id="scene-1", asset_type="visual", relative_path="scene1.svg", file_format="svg", is_valid=True
        ),
        narration_asset=AssemblyAssetReference(
            asset_id="a1", scene_id="scene-1", asset_type="narration", relative_path="scene1.mp3", file_format="mp3", duration_seconds=5.0, is_valid=True
        ),
        caption_srt_asset=AssemblyAssetReference(
            asset_id="c1", scene_id="scene-1", asset_type="caption_srt", relative_path="scene1.srt", file_format="srt", is_valid=True
        ),
        caption_vtt_asset=AssemblyAssetReference(
            asset_id="c1", scene_id="scene-1", asset_type="caption_vtt", relative_path="scene1.vtt", file_format="vtt", is_valid=True
        ),
    )

    scene2 = AssemblyScene(
        scene_id="scene-2",
        scene_number=2,
        script_section_id="sec-2",
        section_purpose="architecture",
        title="Scene 2",
        start_seconds=5.0,
        end_seconds=11.0,
        duration_seconds=6.0,
        visual_asset=AssemblyAssetReference(
            asset_id="v2", scene_id="scene-2", asset_type="visual", relative_path="scene2.svg", file_format="svg", is_valid=True
        ),
        narration_asset=AssemblyAssetReference(
            asset_id="a2", scene_id="scene-2", asset_type="narration", relative_path="scene2.mp3", file_format="mp3", duration_seconds=6.0, is_valid=True
        ),
        caption_srt_asset=AssemblyAssetReference(
            asset_id="c2", scene_id="scene-2", asset_type="caption_srt", relative_path="scene2.srt", file_format="srt", is_valid=True
        ),
        caption_vtt_asset=AssemblyAssetReference(
            asset_id="c2", scene_id="scene-2", asset_type="caption_vtt", relative_path="scene2.vtt", file_format="vtt", is_valid=True
        ),
    )

    full_srt = AssemblyAssetReference(asset_id="full", asset_type="full_video_srt", relative_path="full.srt", file_format="srt", is_valid=True)
    full_vtt = AssemblyAssetReference(asset_id="full", asset_type="full_video_vtt", relative_path="full.vtt", file_format="vtt", is_valid=True)

    report = validator.evaluate_package("job-test", [scene1, scene2], full_srt, full_vtt)
    assert report.status == AssemblyReadinessStatus.READY
    assert report.total_scenes == 2
    assert report.ready_scenes == 2
    assert report.total_duration_seconds == 11.0
    assert len(report.blocking_issues) == 0
    assert len(report.warnings) == 0


def test_evaluate_package_timeline_gap_warning(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)

    # Scene 2 starts at 5.2s instead of 5.0s -> gap of 0.2s
    scene1 = AssemblyScene(
        scene_id="scene-1", scene_number=1, script_section_id="sec-1", section_purpose="hook", title="Scene 1",
        start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0,
        visual_asset=AssemblyAssetReference(asset_id="v1", asset_type="visual", relative_path="s1.svg", file_format="svg", is_valid=True),
        narration_asset=AssemblyAssetReference(asset_id="a1", asset_type="narration", relative_path="s1.mp3", file_format="mp3", duration_seconds=5.0, is_valid=True),
        caption_srt_asset=AssemblyAssetReference(asset_id="c1", asset_type="caption_srt", relative_path="s1.srt", file_format="srt", is_valid=True),
        caption_vtt_asset=AssemblyAssetReference(asset_id="c1", asset_type="caption_vtt", relative_path="s1.vtt", file_format="vtt", is_valid=True),
    )
    scene2 = AssemblyScene(
        scene_id="scene-2", scene_number=2, script_section_id="sec-2", section_purpose="architecture", title="Scene 2",
        start_seconds=5.2, end_seconds=10.0, duration_seconds=4.8,
        visual_asset=AssemblyAssetReference(asset_id="v2", asset_type="visual", relative_path="s2.svg", file_format="svg", is_valid=True),
        narration_asset=AssemblyAssetReference(asset_id="a2", asset_type="narration", relative_path="s2.mp3", file_format="mp3", duration_seconds=4.8, is_valid=True),
        caption_srt_asset=AssemblyAssetReference(asset_id="c2", asset_type="caption_srt", relative_path="s2.srt", file_format="srt", is_valid=True),
        caption_vtt_asset=AssemblyAssetReference(asset_id="c2", asset_type="caption_vtt", relative_path="s2.vtt", file_format="vtt", is_valid=True),
    )

    full_srt = AssemblyAssetReference(asset_id="full", asset_type="full_video_srt", relative_path="full.srt", file_format="srt", is_valid=True)
    full_vtt = AssemblyAssetReference(asset_id="full", asset_type="full_video_vtt", relative_path="full.vtt", file_format="vtt", is_valid=True)

    report = validator.evaluate_package("job-test", [scene1, scene2], full_srt, full_vtt)
    assert report.status == AssemblyReadinessStatus.READY_WITH_WARNINGS
    assert any(w.code == "TIMELINE_GAP" for w in report.warnings)


def test_evaluate_package_missing_assets_blocking(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)

    # Scene 1 is missing visual asset and scene 2 is missing audio
    scene1 = AssemblyScene(
        scene_id="scene-1", scene_number=1, script_section_id="sec-1", section_purpose="hook", title="Scene 1",
        start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0,
        visual_asset=None,  # Missing visual
        narration_asset=AssemblyAssetReference(asset_id="a1", asset_type="narration", relative_path="s1.mp3", file_format="mp3", duration_seconds=5.0, is_valid=True),
        caption_srt_asset=AssemblyAssetReference(asset_id="c1", asset_type="caption_srt", relative_path="s1.srt", file_format="srt", is_valid=True),
        caption_vtt_asset=AssemblyAssetReference(asset_id="c1", asset_type="caption_vtt", relative_path="s1.vtt", file_format="vtt", is_valid=True),
    )
    scene2 = AssemblyScene(
        scene_id="scene-2", scene_number=2, script_section_id="sec-2", section_purpose="architecture", title="Scene 2",
        start_seconds=5.0, end_seconds=10.0, duration_seconds=5.0,
        visual_asset=AssemblyAssetReference(asset_id="v2", asset_type="visual", relative_path="s2.svg", file_format="svg", is_valid=True),
        narration_asset=None,  # Missing audio
        caption_srt_asset=None,
        caption_vtt_asset=None,
    )

    report = validator.evaluate_package("job-test", [scene1, scene2])
    assert report.status == AssemblyReadinessStatus.NOT_READY
    assert any(iss.code == "MISSING_VISUAL_ASSET" for iss in report.blocking_issues)
    assert any(iss.code == "MISSING_NARRATION_ASSET" for iss in report.blocking_issues)


def test_silent_scene_handled_gracefully(temp_storage):
    validator = AssemblyPreflightValidator(base_storage_dir=temp_storage)

    # Intentionally silent scene (no narration required)
    silent_scene = AssemblyScene(
        scene_id="scene-silent",
        scene_number=1,
        script_section_id="sec-1",
        section_purpose="code_transition",
        title="Silent Transition",
        start_seconds=0.0,
        end_seconds=4.0,
        duration_seconds=4.0,
        is_silent=True,
        narration_text=None,
        visual_asset=AssemblyAssetReference(asset_id="v1", asset_type="visual", relative_path="s1.svg", file_format="svg", is_valid=True),
        narration_asset=None,
        caption_srt_asset=None,
        caption_vtt_asset=None,
    )

    report = validator.evaluate_package(
        "job-test",
        [silent_scene],
        full_video_srt=AssemblyAssetReference(asset_id="f", asset_type="full_srt", relative_path="f.srt", file_format="srt", is_valid=True),
        full_video_vtt=AssemblyAssetReference(asset_id="f", asset_type="full_vtt", relative_path="f.vtt", file_format="vtt", is_valid=True),
    )
    # Since it is silent, missing narration and captions are not blocking issues
    assert report.status == AssemblyReadinessStatus.READY
    assert len(report.blocking_issues) == 0


# ==============================================================================
# 5. JobStore Lifecycle & Invalidation Cascade
# ==============================================================================

def test_job_store_assembly_lifecycle_and_invalidation():
    job = job_store.create_job(
        repo_url="https://github.com/org/repo",
        repo_name="org/repo",
        repository_owner="org",
        repository_name="repo",
        clone_url="https://github.com/org/repo.git",
    )
    job_id = job.job_id

    # Create dummy assembly input
    report = AssemblyReadinessReport(
        job_id=job_id,
        status=AssemblyReadinessStatus.READY,
        total_scenes=1,
        ready_scenes=1,
        total_duration_seconds=5.0,
        has_visuals=True,
        has_narration=True,
        has_captions=True,
        has_full_video_captions=True,
    )
    assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name="org/repo",
        scenes=[],
        total_scenes=1,
        total_duration_seconds=5.0,
        readiness_report=report,
    )

    # 1. Update success
    updated = job_store.update_job_assembly_input_success(job_id, assembly_input)
    assert updated.assembly_input is not None
    assert updated.stages[8].status == StatusEnum.PENDING  # Stage 9 remains pending for Milestone 6

    # 2. Retrieve
    retrieved = job_store.get_job_assembly_input(job_id)
    assert retrieved is not None
    assert retrieved.job_id == job_id

    # 3. Direct invalidation
    job_store.invalidate_job_assembly_input(job_id)
    assert job_store.get_job_assembly_input(job_id) is None

    # 4. Invalidation cascade via captions
    job_store.update_job_assembly_input_success(job_id, assembly_input)
    assert job_store.get_job_assembly_input(job_id) is not None
    job_store.invalidate_job_captions(job_id)
    assert job_store.get_job_assembly_input(job_id) is None

    # 5. Invalidation cascade via visuals
    job_store.update_job_assembly_input_success(job_id, assembly_input)
    assert job_store.get_job_assembly_input(job_id) is not None
    job_store.invalidate_job_visual_generation(job_id)
    assert job_store.get_job_assembly_input(job_id) is None


# ==============================================================================
# 6. FastAPI Endpoints & Error Handling
# ==============================================================================

def test_api_assembly_input_endpoints(mock_storyboard):
    job = job_store.create_job(
        repo_url="https://github.com/test/repo",
        repo_name="test/repo",
        repository_owner="test",
        repository_name="repo",
        clone_url="https://github.com/test/repo.git",
    )
    job_id = job.job_id

    # 1. POST assembly-input before storyboard -> HTTP 409
    res = client.post(f"/api/v1/jobs/{job_id}/assembly-input")
    assert res.status_code == status.HTTP_409_CONFLICT
    assert "Educational storyboard must be generated" in res.json()["detail"]

    # 2. Add storyboard to job
    job.educational_storyboard = mock_storyboard
    job_store.update_job(job)

    # 3. POST assembly-input -> HTTP 200
    res = client.post(f"/api/v1/jobs/{job_id}/assembly-input")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["job_id"] == job_id
    assert data["total_scenes"] == 2
    assert "readiness_report" in data
    # Status should be NOT_READY since files are not physically created on disk yet
    assert data["readiness_report"]["status"] == "not_ready"

    # 4. GET assembly-input -> HTTP 200
    res = client.get(f"/api/v1/jobs/{job_id}/assembly-input")
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["job_id"] == job_id

    # 5. GET assembly-readiness -> HTTP 200
    res = client.get(f"/api/v1/jobs/{job_id}/assembly-readiness")
    assert res.status_code == status.HTTP_200_OK
    report = res.json()
    assert report["job_id"] == job_id
    assert report["total_scenes"] == 2


def test_api_assembly_input_404_for_unknown_job():
    res = client.get("/api/v1/jobs/non-existent-job-xyz/assembly-input")
    assert res.status_code == status.HTTP_404_NOT_FOUND

    res = client.get("/api/v1/jobs/non-existent-job-xyz/assembly-readiness")
    assert res.status_code == status.HTTP_404_NOT_FOUND
