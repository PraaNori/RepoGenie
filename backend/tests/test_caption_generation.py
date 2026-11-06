"""
Comprehensive Caption Generation Unit Tests (Milestone 5, Phase 5.5).

Verifies deterministic caption segmentation, punctuation-aware proportional timing,
SRT and WebVTT formatting, standards validation, Unicode safety, audio-to-scene matching,
file storage, path traversal protection, cache reuse, lifecycle isolation, and API routes.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import StageEnum, StatusEnum
from app.services.ai.script_generation.schemas import (
    EducationalScript,
    ScriptSection,
    SectionPurpose,
)
from app.services.ai.storyboard_generation.schemas import (
    EducationalStoryboard,
    NarrationReference,
    StoryboardScene,
    VisualType,
)
from app.services.storage.job_store import JobInternal, job_store
from app.services.video.captions import (
    Caption,
    CaptionAssetStorageManager,
    CaptionGenerationResult,
    CaptionService,
    CaptionStatus,
    SceneCaptionAsset,
    TimingProvenance,
    caption_service,
    caption_storage_manager,
    format_srt_cues,
    format_vtt_cues,
    generate_scene_captions,
    seconds_to_srt_timestamp,
    seconds_to_vtt_timestamp,
    split_text_into_cues,
    validate_srt_content,
    validate_vtt_content,
)
from app.services.video.narration.schemas import (
    NarrationAsset,
    NarrationAssetStatus,
    NarrationGenerationResult,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_storyboard() -> EducationalStoryboard:
    scenes = [
        StoryboardScene(
            scene_id="scene-intro-1",
            scene_number=1,
            script_section_id="sec-intro",
            title="Introduction to Repository",
            purpose="Welcome viewers to the codebase",
            estimated_duration_seconds=5.0,
            visual_type=VisualType.TITLE_CARD,
            visual_description="Title banner",
            narration=NarrationReference(
                script_section_id="sec-intro",
                excerpt="Welcome to RepoGenie. This video explains the architecture of the project.",
            ),
        ),
        StoryboardScene(
            scene_id="scene-arch-2",
            scene_number=2,
            script_section_id="sec-arch",
            title="Layered Architecture",
            purpose="Deep dive into system components",
            estimated_duration_seconds=6.0,
            visual_type=VisualType.ARCHITECTURE_DIAGRAM,
            visual_description="Architecture diagram",
            narration=NarrationReference(
                script_section_id="sec-arch",
                excerpt="The architecture is modular; it separates API dispatch, storage abstraction, and processing.",
            ),
        ),
        StoryboardScene(
            scene_id="scene-silent-3",
            scene_number=3,
            script_section_id="sec-silent",
            title="Visual Pause",
            purpose="Brief visual interlude",
            estimated_duration_seconds=3.0,
            visual_type=VisualType.OTHER,
            visual_description="Silent transition",
            narration=NarrationReference(
                script_section_id="sec-silent",
                excerpt="",
            ),
        ),
    ]
    return EducationalStoryboard(
        storyboard_id="sb-test-captions",
        script_id="script-test-captions",
        title="Test Storyboard",
        scenes=scenes,
        total_estimated_duration_seconds=14.0,
    )


@pytest.fixture
def sample_narration_result() -> NarrationGenerationResult:
    return NarrationGenerationResult(
        job_id="job-test-captions",
        status=NarrationAssetStatus.COMPLETED,
        total_scenes=3,
        scenes_completed=2,
        scenes_failed=0,
        scenes_skipped=1,
        total_assets=3,
        assets_completed=2,
        assets_failed=0,
        assets_skipped=1,
        assets=[
            NarrationAsset(
                asset_id="audio_scene_intro_1",
                job_id="job-test-captions",
                scene_id="scene-intro-1",
                scene_number=1,
                script_section_id="sec-intro",
                status=NarrationAssetStatus.COMPLETED,
                duration_seconds=4.5,
                narration_text="Welcome to RepoGenie. This video explains the architecture of the project.",
            ),
            NarrationAsset(
                asset_id="audio_scene_arch_2",
                job_id="job-test-captions",
                scene_id="scene-arch-2",
                scene_number=2,
                script_section_id="sec-arch",
                status=NarrationAssetStatus.COMPLETED,
                duration_seconds=5.8,
                narration_text="The architecture is modular; it separates API dispatch, storage abstraction, and processing.",
            ),
            NarrationAsset(
                asset_id="audio_scene_silent_3",
                job_id="job-test-captions",
                scene_id="scene-silent-3",
                scene_number=3,
                script_section_id="sec-silent",
                status=NarrationAssetStatus.SKIPPED,
                duration_seconds=0.0,
                narration_text="",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Formatting and Validation Unit Tests
# ---------------------------------------------------------------------------

def test_seconds_to_srt_timestamp():
    """Verify conversion of seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    assert seconds_to_srt_timestamp(0.0) == "00:00:00,000"
    assert seconds_to_srt_timestamp(1.25) == "00:00:01,250"
    assert seconds_to_srt_timestamp(74.321) == "00:01:14,321"
    assert seconds_to_srt_timestamp(3661.05) == "01:01:01,050"


def test_seconds_to_vtt_timestamp():
    """Verify conversion of seconds to WebVTT timestamp format (HH:MM:SS.mmm)."""
    assert seconds_to_vtt_timestamp(0.0) == "00:00:00.000"
    assert seconds_to_vtt_timestamp(1.25) == "00:00:01.250"
    assert seconds_to_vtt_timestamp(74.321) == "00:01:14.321"
    assert seconds_to_vtt_timestamp(3661.05) == "01:01:01.050"


def test_format_srt_cues_validity():
    """Verify generated SRT adheres strictly to SubRip syntax."""
    cues = [
        (0.05, 2.15, "Welcome to RepoGenie."),
        (2.19, 4.45, "This is an architectural walkthrough."),
    ]
    srt = format_srt_cues(cues, start_index=1)
    assert validate_srt_content(srt) is True
    assert "1\n00:00:00,050 --> 00:00:02,150\nWelcome to RepoGenie." in srt
    assert "2\n00:00:02,190 --> 00:00:04,450\nThis is an architectural walkthrough." in srt


def test_format_vtt_cues_validity():
    """Verify generated WebVTT adheres to standards with WEBVTT signature."""
    cues = [
        (0.05, 2.15, "Welcome to RepoGenie."),
        (2.19, 4.45, "This is an architectural walkthrough."),
    ]
    vtt = format_vtt_cues(cues, header_title="Scene 1")
    assert validate_vtt_content(vtt) is True
    assert vtt.startswith("WEBVTT - Scene 1")
    assert "00:00:00.050 --> 00:00:02.150\nWelcome to RepoGenie." in vtt


def test_unicode_and_special_character_formatting():
    """Verify special characters, Unicode, quotes, and punctuation are preserved."""
    cues = [
        (0.1, 2.5, "RepoGenie supports Python 3.12+, TypeScript & Go!"),
        (2.6, 5.0, "«Intelligent» static analysis — 100% verified."),
    ]
    srt = format_srt_cues(cues)
    vtt = format_vtt_cues(cues)
    assert validate_srt_content(srt) is True
    assert validate_vtt_content(vtt) is True
    assert "Python 3.12+, TypeScript & Go!" in srt
    assert "«Intelligent» static analysis — 100% verified." in vtt


def test_invalid_srt_syntax_rejected():
    """Verify validator rejects malformed SRT strings."""
    assert validate_srt_content("") is False
    assert validate_srt_content("Just plain text") is False
    # Missing sequence number
    assert validate_srt_content("00:00:00,000 --> 00:00:01,000\nText") is False
    # Non-consecutive sequence
    bad_seq = "1\n00:00:00,000 --> 00:00:01,000\nText\n\n3\n00:00:01,000 --> 00:00:02,000\nText"
    assert validate_srt_content(bad_seq) is False


def test_invalid_vtt_syntax_rejected():
    """Verify validator rejects invalid WebVTT content lacking signature."""
    assert validate_vtt_content("") is False
    assert validate_vtt_content("NO_WEBVTT_HEADER\n\n00:00:00.000 --> 00:00:01.000\nText") is False


# ---------------------------------------------------------------------------
# Segmentation & Proportional Timing Tests
# ---------------------------------------------------------------------------

def test_split_text_into_cues_sentence_boundaries():
    """Verify natural phrase and sentence boundary splitting."""
    text = "First sentence. Second sentence with extra details! And a third question?"
    cues = split_text_into_cues(text)
    assert len(cues) == 3
    assert cues[0] == "First sentence."
    assert cues[1] == "Second sentence with extra details!"
    assert cues[2] == "And a third question?"


def test_split_text_into_cues_clause_boundaries():
    """Verify long sentences split cleanly at clauses rather than arbitrary words."""
    text = "The application architecture is modular, isolating execution dispatch, data storage, and external API requests."
    cues = split_text_into_cues(text)
    assert len(cues) >= 2
    # Ensure words are not chopped mid-word and commas do not start a line
    for cue in cues:
        assert not cue.startswith(",")
        assert len(cue.split()) >= 2
    assert "modular," in cues[0]


def test_generate_scene_captions_proportional_timing():
    """Verify timing allocation respects measured audio duration and keeps boundaries."""
    text = "Welcome to RepoGenie. Here is the architecture overview."
    duration = 5.0
    captions = generate_scene_captions(
        scene_id="scene-1",
        narration_text=text,
        audio_duration_seconds=duration,
    )
    assert len(captions) == 2
    assert captions[0].sequence_number == 1
    assert captions[1].sequence_number == 2
    assert captions[0].start_seconds >= 0.0
    assert captions[0].end_seconds <= captions[1].start_seconds + 0.001
    assert captions[1].end_seconds <= duration + 0.05
    assert captions[0].text == "Welcome to RepoGenie."
    assert captions[1].text == "Here is the architecture overview."
    assert captions[0].timing_provenance == TimingProvenance.ESTIMATED


def test_empty_narration_produces_empty_captions():
    """Verify empty or whitespace narration produces 0 captions."""
    assert generate_scene_captions("s1", "", 5.0) == []
    assert generate_scene_captions("s1", "   ", 5.0) == []


# ---------------------------------------------------------------------------
# Storage Manager Tests
# ---------------------------------------------------------------------------

def test_storage_manager_atomic_save_and_read(tmp_path: Path):
    """Verify atomic write and retrieval of SRT and VTT files."""
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    job_id = "test-atomic-captions"
    asset_id = "caption_scene_1"

    srt_content = "1\n00:00:00,100 --> 00:00:02,000\nHello World\n"
    vtt_content = "WEBVTT - Test\n\n00:00:00.100 --> 00:00:02.000\nHello World\n"

    path_srt = storage.save_caption_file(job_id, asset_id, srt_content, format="srt")
    path_vtt = storage.save_caption_file(job_id, asset_id, vtt_content, format="vtt")

    assert path_srt.is_file() and path_srt.stat().st_size > 0
    assert path_vtt.is_file() and path_vtt.stat().st_size > 0

    assert storage.caption_file_exists(job_id, asset_id, format="srt") is True
    assert storage.caption_file_exists(job_id, asset_id, format="vtt") is True

    assert storage.read_caption_file(job_id, asset_id, format="srt") == srt_content
    assert storage.read_caption_file(job_id, asset_id, format="vtt") == vtt_content

    # Clean up
    storage.delete_job_captions(job_id)
    assert storage.caption_file_exists(job_id, asset_id, format="srt") is False


def test_storage_manager_path_traversal_prevention(tmp_path: Path):
    """Verify path traversal attempts are rejected."""
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    with pytest.raises(ValueError, match="Invalid or unsafe job_id"):
        storage.get_job_captions_dir("../evil_job")

    with pytest.raises(ValueError, match="Unsafe or invalid asset_id"):
        storage.get_caption_path("job123", "../../etc/passwd")


def test_storage_manager_corrupt_data_rejected(tmp_path: Path):
    """Verify invalid subtitle content fails validation before write."""
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    with pytest.raises(ValueError, match="Invalid SubRip"):
        storage.save_caption_file("job1", "asset1", "Corrupt non-srt text", format="srt")


# ---------------------------------------------------------------------------
# Caption Service Full Lifecycle Tests
# ---------------------------------------------------------------------------

def test_service_generates_scene_and_composite_captions(
    sample_storyboard: EducationalStoryboard,
    sample_narration_result: NarrationGenerationResult,
    tmp_path: Path,
):
    """Verify full end-to-end generation across scenes and full-video composite track."""
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    svc = CaptionService(storage=storage)

    job_id = "job-test-captions"
    result = svc.generate_captions_for_job(
        job_id=job_id,
        storyboard=sample_storyboard,
        narration=sample_narration_result,
        refresh=True,
    )

    assert result.status == CaptionStatus.COMPLETED
    assert result.total_scenes == 3
    assert result.scenes_completed == 2
    assert result.scenes_skipped == 1
    assert result.scenes_failed == 0
    assert result.total_captions > 2

    # Check individual scene assets
    scene1_asset = result.get_asset_by_scene_id("scene-intro-1")
    assert scene1_asset is not None
    assert scene1_asset.status == CaptionStatus.COMPLETED
    assert len(scene1_asset.captions) >= 1
    assert scene1_asset.srt_file_path is not None
    assert scene1_asset.vtt_file_path is not None

    scene3_asset = result.get_asset_by_scene_id("scene-silent-3")
    assert scene3_asset is not None
    assert scene3_asset.status == CaptionStatus.SKIPPED
    assert len(scene3_asset.captions) == 0

    # Check composite full-video tracks
    assert result.full_srt_file_path is not None
    assert result.full_vtt_file_path is not None
    assert storage.caption_file_exists(job_id, "full", format="srt") is True
    assert storage.caption_file_exists(job_id, "full", format="vtt") is True

    full_srt_content = storage.read_caption_file(job_id, "full", format="srt")
    assert validate_srt_content(full_srt_content) is True
    assert "Welcome to RepoGenie" in full_srt_content
    assert "The architecture is modular" in full_srt_content


def test_service_failed_narration_marks_caption_failed(
    sample_storyboard: EducationalStoryboard,
    tmp_path: Path,
):
    """Verify scenes whose narration failed are marked as FAILED in captions."""
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    svc = CaptionService(storage=storage)

    failed_narration = NarrationGenerationResult(
        job_id="job-failed-narration",
        status=NarrationAssetStatus.FAILED,
        total_scenes=1,
        scenes_completed=0,
        scenes_failed=1,
        total_assets=1,
        assets_failed=1,
        assets=[
            NarrationAsset(
                asset_id="audio_failed_1",
                job_id="job-failed-narration",
                scene_id="scene-intro-1",
                scene_number=1,
                script_section_id="sec-intro",
                status=NarrationAssetStatus.FAILED,
                error_message="ElevenLabs 401 Unauthorized",
            )
        ],
    )

    result = svc.generate_captions_for_job(
        job_id="job-failed-narration",
        storyboard=sample_storyboard,
        narration=failed_narration,
        refresh=True,
    )
    assert result.status == CaptionStatus.FAILED
    assert result.scenes_failed >= 1
    asset = result.get_asset_by_scene_id("scene-intro-1")
    assert asset.status == CaptionStatus.FAILED
    assert "ElevenLabs 401 Unauthorized" in asset.error_message


def test_service_missing_storyboard_or_narration_raises(sample_storyboard: EducationalStoryboard):
    """Verify validation errors when prerequisites are missing."""
    with pytest.raises(ValueError, match="storyboard with at least one scene"):
        caption_service.generate_captions_for_job("job1", storyboard=None, narration=None)

    with pytest.raises(ValueError, match="Narration audio assets must be generated"):
        caption_service.generate_captions_for_job("job1", storyboard=sample_storyboard, narration=None)


# ---------------------------------------------------------------------------
# JobStore Lifecycle and Invalidation Cascade Tests
# ---------------------------------------------------------------------------

def test_job_store_caption_lifecycle_and_invalidation():
    """Verify caption lifecycle methods and cascading invalidation upon storyboard/narration reset."""
    job = job_store.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        repo_name="octocat/Hello-World",
        repository_owner="octocat",
        repository_name="Hello-World",
        clone_url="https://github.com/octocat/Hello-World.git",
    )
    job_id = job.job_id

    # Initialize captions
    res = CaptionGenerationResult(
        job_id=job_id,
        status=CaptionStatus.COMPLETED,
        total_scenes=1,
        scenes_completed=1,
        total_captions=2,
    )
    job_store.update_job_captions_success(job_id, res)
    assert job_store.get_job_captions(job_id) is not None
    assert job.to_response().has_captions is True

    # Invalidate narration -> must cascade and invalidate captions
    job_store.invalidate_job_narration(job_id)
    assert job_store.get_job_captions(job_id) is None
    assert job.to_response().has_captions is False

    # Clean up
    job_store._jobs.pop(job_id, None)


# ---------------------------------------------------------------------------
# API Route Tests
# ---------------------------------------------------------------------------

def test_api_missing_job_returns_404():
    """Verify 404 on unknown job."""
    resp = client.post("/api/v1/jobs/non-existent-job-xyz/captions")
    assert resp.status_code == 404


def test_api_missing_prerequisites_returns_409():
    """Verify 409 when storyboard or narration is not yet available."""
    job = job_store.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        repo_name="octocat/Hello-World",
        repository_owner="octocat",
        repository_name="Hello-World",
        clone_url="https://github.com/octocat/Hello-World.git",
    )
    job_id = job.job_id
    try:
        resp = client.post(f"/api/v1/jobs/{job_id}/captions")
        assert resp.status_code == 409
        assert "Educational storyboard is required" in resp.json()["detail"]
    finally:
        job_store._jobs.pop(job_id, None)


def test_api_full_caption_generation_and_file_streaming(
    sample_storyboard: EducationalStoryboard,
    sample_narration_result: NarrationGenerationResult,
):
    """Verify POST generation, GET metadata, and GET file streaming for SRT and VTT."""
    job = job_store.create_job(
        repo_url="https://github.com/octocat/Hello-World",
        repo_name="octocat/Hello-World",
        repository_owner="octocat",
        repository_name="Hello-World",
        clone_url="https://github.com/octocat/Hello-World.git",
    )
    job_id = job.job_id
    job.educational_storyboard = sample_storyboard
    job.narration = sample_narration_result
    job.stages[7].status = StatusEnum.COMPLETED  # Voice generation completed

    try:
        # 1. POST /captions
        post_resp = client.post(f"/api/v1/jobs/{job_id}/captions?refresh=true")
        assert post_resp.status_code == 200
        post_data = post_resp.json()
        assert post_data["status"] == "completed"
        assert post_data["total_scenes"] == 3
        assert post_data["scenes_completed"] == 2
        assert post_data["full_srt_file_path"] is not None

        # 2. GET /captions
        get_resp = client.get(f"/api/v1/jobs/{job_id}/captions")
        assert get_resp.status_code == 200
        assert get_resp.json()["total_captions"] == post_data["total_captions"]

        # 3. GET /captions/{asset_id}
        asset_id = post_data["scene_assets"][0]["asset_id"]
        asset_resp = client.get(f"/api/v1/jobs/{job_id}/captions/{asset_id}")
        assert asset_resp.status_code == 200
        assert asset_resp.json()["asset_id"] == asset_id

        # 4. GET /captions/{asset_id}/file?format=srt
        file_srt_resp = client.get(f"/api/v1/jobs/{job_id}/captions/{asset_id}/file?format=srt")
        assert file_srt_resp.status_code == 200
        assert "00:00:" in file_srt_resp.text
        assert "Welcome to RepoGenie" in file_srt_resp.text

        # 5. GET /captions/{asset_id}/file?format=vtt
        file_vtt_resp = client.get(f"/api/v1/jobs/{job_id}/captions/{asset_id}/file?format=vtt")
        assert file_vtt_resp.status_code == 200
        assert file_vtt_resp.text.startswith("WEBVTT")

        # 6. GET /captions/full/file?format=srt (full-video composite track)
        full_srt_resp = client.get(f"/api/v1/jobs/{job_id}/captions/full/file?format=srt")
        assert full_srt_resp.status_code == 200
        assert "Welcome to RepoGenie" in full_srt_resp.text

    finally:
        caption_storage_manager.delete_job_captions(job_id)
        job_store._jobs.pop(job_id, None)


# ---------------------------------------------------------------------------
# Phase 5.5 Audit: Multi-Scene Timeline and Edge Case Verification
# ---------------------------------------------------------------------------

def test_three_scene_timeline_cumulative_offsets_with_skipped_scene(tmp_path: Path):
    """
    Verify full-video cumulative offsets across three scenes with different durations,
    including a silent/skipped scene in the middle.
    Guarantees later scenes never restart at 0.0s and account for preceding scene durations.
    """
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    svc = CaptionService(storage=storage)
    job_id = "job-audit-three-scenes"

    # Storyboard: Scene 1 (4.0s), Scene 2 (silent, 3.0s), Scene 3 (5.0s)
    scenes = [
        StoryboardScene(
            scene_id="scene-intro-1",
            scene_number=1,
            script_section_id="sec-1",
            title="Introduction",
            purpose="Welcome",
            estimated_duration_seconds=4.0,
            visual_type=VisualType.TITLE_CARD,
            visual_description="Intro Card",
            narration=NarrationReference(
                script_section_id="sec-1",
                excerpt="Welcome to RepoGenie.",
            ),
        ),
        StoryboardScene(
            scene_id="scene-pause-2",
            scene_number=2,
            script_section_id="sec-2",
            title="Visual Pause",
            purpose="Pause",
            estimated_duration_seconds=3.0,
            visual_type=VisualType.OTHER,
            visual_description="Pause without spoken narration",
            narration=NarrationReference(
                script_section_id="sec-2",
                excerpt="",
            ),
        ),
        StoryboardScene(
            scene_id="scene-arch-3",
            scene_number=3,
            script_section_id="sec-3",
            title="Architecture",
            purpose="Architecture overview",
            estimated_duration_seconds=5.0,
            visual_type=VisualType.ARCHITECTURE_DIAGRAM,
            visual_description="Architecture diagram",
            narration=NarrationReference(
                script_section_id="sec-3",
                excerpt="This is the architecture diagram. It demonstrates modular components.",
            ),
        ),
    ]
    storyboard = EducationalStoryboard(
        storyboard_id="sb-three-scenes",
        script_id="sc-three-scenes",
        title="Three Scene Test",
        scenes=scenes,
        total_estimated_duration_seconds=12.0,
    )

    narration_result = NarrationGenerationResult(
        job_id=job_id,
        status=NarrationAssetStatus.COMPLETED,
        total_scenes=3,
        scenes_completed=2,
        scenes_skipped=1,
        total_assets=3,
        assets_completed=2,
        assets_skipped=1,
        assets=[
            NarrationAsset(
                asset_id="audio_1",
                job_id=job_id,
                scene_id="scene-intro-1",
                scene_number=1,
                script_section_id="sec-1",
                status=NarrationAssetStatus.COMPLETED,
                duration_seconds=4.0,
                narration_text="Welcome to RepoGenie.",
            ),
            NarrationAsset(
                asset_id="audio_2",
                job_id=job_id,
                scene_id="scene-pause-2",
                scene_number=2,
                script_section_id="sec-2",
                status=NarrationAssetStatus.SKIPPED,
                duration_seconds=0.0,
                narration_text="",
            ),
            NarrationAsset(
                asset_id="audio_3",
                job_id=job_id,
                scene_id="scene-arch-3",
                scene_number=3,
                script_section_id="sec-3",
                status=NarrationAssetStatus.COMPLETED,
                duration_seconds=5.0,
                narration_text="This is the architecture diagram. It demonstrates modular components.",
            ),
        ],
    )

    result = svc.generate_captions_for_job(job_id=job_id, storyboard=storyboard, narration=narration_result)

    assert result.status == CaptionStatus.COMPLETED
    assert result.total_scenes == 3
    assert len(result.scene_assets) == 3

    asset1 = result.scene_assets[0]
    asset2 = result.scene_assets[1]
    asset3 = result.scene_assets[2]

    # Verify Scene 1: [0.0, 4.0]
    assert asset1.cumulative_start_seconds == 0.0
    assert asset1.cumulative_end_seconds == 4.0
    assert asset1.captions[0].start_seconds >= 0.0
    assert asset1.captions[0].end_seconds <= 4.0

    # Verify Scene 2 (Silent): [4.0, 7.0]
    assert asset2.status == CaptionStatus.SKIPPED
    assert asset2.cumulative_start_seconds == 4.0
    assert asset2.cumulative_end_seconds == 7.0
    assert len(asset2.captions) == 0

    # Verify Scene 3 (Narrated): [7.0, 12.0]
    assert asset3.status == CaptionStatus.COMPLETED
    assert asset3.cumulative_start_seconds == 7.0
    assert asset3.cumulative_end_seconds == 12.0

    # Read composite full-video SRT and verify exact cumulative timestamps
    full_srt = storage.read_caption_file(job_id, "full", format="srt")
    assert validate_srt_content(full_srt) is True

    # Scene 1 cue: starts near 00:00:00,050
    assert "00:00:00,050 -->" in full_srt
    assert "Welcome to RepoGenie." in full_srt

    # Scene 3 cue: MUST start after 7.0s (00:00:07,050), NEVER restarting at 0 or 4
    assert "00:00:07,050 -->" in full_srt
    assert "This is the architecture diagram." in full_srt

    # WebVTT full track has equivalent timing
    full_vtt = storage.read_caption_file(job_id, "full", format="vtt")
    assert validate_vtt_content(full_vtt) is True
    assert "00:00:07.050 -->" in full_vtt


def test_three_scene_timeline_cumulative_offsets_with_failed_scene(tmp_path: Path):
    """
    Verify that a failed narration scene does not cause subsequent scenes to shift left
    or overwrite timestamps.
    """
    storage = CaptionAssetStorageManager(base_dir=tmp_path)
    svc = CaptionService(storage=storage)
    job_id = "job-audit-failed-scene"

    scenes = [
        StoryboardScene(
            scene_id="scene-intro-1",
            scene_number=1,
            script_section_id="sec-1",
            title="Scene 1",
            purpose="Welcome",
            estimated_duration_seconds=4.0,
            visual_type=VisualType.TITLE_CARD,
            visual_description="Intro",
            narration=NarrationReference(script_section_id="sec-1", excerpt="First scene narration."),
        ),
        StoryboardScene(
            scene_id="scene-failed-2",
            scene_number=2,
            script_section_id="sec-2",
            title="Scene 2 Failed",
            purpose="Failed",
            estimated_duration_seconds=3.5,
            visual_type=VisualType.OTHER,
            visual_description="Failed narration",
            narration=NarrationReference(script_section_id="sec-2", excerpt="Broken audio."),
        ),
        StoryboardScene(
            scene_id="scene-third-3",
            scene_number=3,
            script_section_id="sec-3",
            title="Scene 3",
            purpose="Resume",
            estimated_duration_seconds=5.0,
            visual_type=VisualType.SUMMARY_CARD,
            visual_description="Summary",
            narration=NarrationReference(script_section_id="sec-3", excerpt="Third scene narration resumes."),
        ),
    ]
    storyboard = EducationalStoryboard(
        storyboard_id="sb-failed-scene",
        script_id="sc-failed-scene",
        title="Failed Scene Test",
        scenes=scenes,
        total_estimated_duration_seconds=12.5,
    )

    narration_result = NarrationGenerationResult(
        job_id=job_id,
        status=NarrationAssetStatus.FAILED,
        total_scenes=3,
        scenes_completed=2,
        scenes_failed=1,
        total_assets=3,
        assets_completed=2,
        assets_failed=1,
        assets=[
            NarrationAsset(
                asset_id="a1",
                job_id=job_id,
                scene_id="scene-intro-1",
                scene_number=1,
                script_section_id="sec-1",
                status=NarrationAssetStatus.COMPLETED,
                duration_seconds=4.0,
                narration_text="First scene narration.",
            ),
            NarrationAsset(
                asset_id="a2",
                job_id=job_id,
                scene_id="scene-failed-2",
                scene_number=2,
                script_section_id="sec-2",
                status=NarrationAssetStatus.FAILED,
                error_message="TTS Network Timeout",
            ),
            NarrationAsset(
                asset_id="a3",
                job_id=job_id,
                scene_id="scene-third-3",
                scene_number=3,
                script_section_id="sec-3",
                status=NarrationAssetStatus.COMPLETED,
                duration_seconds=5.0,
                narration_text="Third scene narration resumes.",
            ),
        ],
    )

    result = svc.generate_captions_for_job(job_id=job_id, storyboard=storyboard, narration=narration_result)

    assert result.status == CaptionStatus.FAILED
    assert result.scenes_failed == 1

    asset2 = result.get_asset_by_scene_id("scene-failed-2")
    asset3 = result.get_asset_by_scene_id("scene-third-3")

    # Scene 2 failed: occupied planned 3.5s [4.0, 7.5]
    assert asset2.status == CaptionStatus.FAILED
    assert asset2.cumulative_start_seconds == 4.0
    assert asset2.cumulative_end_seconds == 7.5

    # Scene 3: starts at 7.5s, not 4.0s!
    assert asset3.status == CaptionStatus.COMPLETED
    assert asset3.cumulative_start_seconds == 7.5
    assert asset3.cumulative_end_seconds == 12.5

    full_srt = storage.read_caption_file(job_id, "full", format="srt")
    assert "00:00:07,550 -->" in full_srt
    assert "Third scene narration resumes." in full_srt


def test_timing_and_segmentation_edge_cases():
    """
    Verify segmentation and timing across edge cases:
    - Very short text
    - Long sentence with clauses
    - Abbreviations and decimal numbers
    - Multiple punctuation marks
    - Text without terminal punctuation
    - Extremely tight / rushed audio duration
    """
    # 1. Very short narration
    c1 = generate_scene_captions("s1", "Hello.", 2.0)
    assert len(c1) == 1
    assert c1[0].text == "Hello."
    assert c1[0].start_seconds >= 0.0
    assert c1[0].end_seconds <= 2.0
    assert c1[0].end_seconds > c1[0].start_seconds

    # 2. Narration with no terminal punctuation
    c2 = generate_scene_captions("s2", "Command line interface walkthrough", 3.0)
    assert len(c2) == 1
    assert c2[0].text == "Command line interface walkthrough"
    assert c2[0].end_seconds <= 3.0

    # 3. Abbreviations, decimals, and special characters
    c3 = generate_scene_captions("s3", "RepoGenie v1.2 runs on Python 3.12, e.g. FastAPI & Starlette.", 6.0)
    assert len(c3) >= 1
    full_text = " ".join(c.text for c in c3)
    assert "3.12" in full_text
    assert "v1.2" in full_text
    assert "&" in full_text

    # 4. Long sentence (> 30 words) split into readable cues
    long_text = (
        "The architecture decomposes repository structures into deterministic AST parse trees, "
        "enabling static dependency analysis, technology detection, and educational script generation "
        "without requiring live execution of untrusted codebase instructions."
    )
    c4 = generate_scene_captions("s4", long_text, 14.0)
    assert len(c4) >= 3
    # Check bounds and monotonicity
    last_end = 0.0
    for cue in c4:
        assert cue.start_seconds >= last_end - 1e-4
        assert cue.end_seconds > cue.start_seconds
        assert cue.end_seconds <= 14.05
        last_end = cue.end_seconds
    assert "untrusted codebase instructions." in c4[-1].text

    # 5. Rushed duration (0.4s for 12 words) surfaces warning and maintains strict boundaries
    rushed_text = "This is a hurried sentence with many words packed into a short time."
    c5 = generate_scene_captions("s5", rushed_text, 0.4)
    assert len(c5) >= 1
    assert c5[0].end_seconds <= 0.45
    assert c5[0].end_seconds > c5[0].start_seconds
    assert any("hurried" in w or "short" in w for w in c5[0].warnings)

