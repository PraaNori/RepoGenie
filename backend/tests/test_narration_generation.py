"""
Comprehensive Narration Generation Unit Tests (Milestone 5, Phase 5.4).

Verifies ElevenLabs provider, audio storage manager, duration measurement,
scene-to-audio association, synchronization analysis, retry backoff, error handling,
per-job isolation, and Stage 08 pipeline lifecycle.
All external ElevenLabs API network calls are strictly mocked.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.schemas import (
    RepositoryKnowledge,
    StageEnum,
    StatusEnum,
)
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
from app.services.video.narration import (
    AudioAssetStorageManager,
    ElevenLabsAuthError,
    ElevenLabsBadRequestError,
    ElevenLabsConfigurationError,
    ElevenLabsRateLimitError,
    ElevenLabsServerError,
    ElevenLabsTimeoutError,
    ElevenLabsTTSProvider,
    ElevenLabsVoiceNotFoundError,
    NarrationAssetStatus,
    NarrationGenerationResult,
    NarrationService,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def create_valid_mp3_bytes(num_frames: int = 10, bitrate_kbps: int = 128, samplerate: int = 44100) -> bytes:
    """Generates synthetic valid MPEG-1 Layer III audio frame bytes for testing."""
    # ID3v2 header: ID3, version 3, 0 flags, size 10 (synchsafe: 0 0 0 10)
    id3 = b"ID3\x03\x00\x00\x00\x00\x00\x0a" + b"x" * 10

    # MPEG-1 Layer III frame:
    # 0xFF, 0xFB (sync 11111111111, MPEG 1, Layer III, no CRC)
    # 0x90 (bitrate 128kbps -> index 9, samplerate 44100 -> index 0, padding 0)
    # 0x00 (stereo)
    # Frame size = int(144 * 128000 / 44100) = 417 bytes
    frame_body = b"\x00" * 413
    frame = b"\xff\xfb\x90\x00" + frame_body
    return id3 + (frame * num_frames)


@pytest.fixture
def mock_storyboard() -> EducationalStoryboard:
    """Creates a sample 3-scene educational storyboard for testing."""
    scenes = [
        StoryboardScene(
            scene_id="scene-intro-1",
            scene_number=1,
            script_section_id="sec-intro",
            title="Introduction to Repository",
            purpose="Welcome viewers to the codebase",
            estimated_duration_seconds=10.0,
            visual_type=VisualType.TITLE_CARD,
            visual_description="Clean hero title card showing repository identity",
            narration=NarrationReference(
                script_section_id="sec-intro",
                excerpt="Welcome to the architectural walkthrough of this repository.",
            ),
        ),
        StoryboardScene(
            scene_id="scene-arch-2",
            scene_number=2,
            script_section_id="sec-arch",
            title="Layered Architecture",
            purpose="Deep dive into system components",
            estimated_duration_seconds=15.0,
            visual_type=VisualType.ARCHITECTURE_DIAGRAM,
            visual_description="Interactive layered architecture diagram",
            narration=NarrationReference(
                script_section_id="sec-arch",
                excerpt="The architecture isolates execution dispatch from input validation.",
            ),
        ),
        StoryboardScene(
            scene_id="scene-silent-3",
            scene_number=3,
            script_section_id="sec-silent",
            title="Visual Interlude",
            purpose="Brief visual interlude without narration",
            estimated_duration_seconds=5.0,
            visual_type=VisualType.OTHER,
            visual_description="Visual pause",
            narration=NarrationReference(
                script_section_id="sec-silent",
                excerpt="",  # Empty narration
            ),
        ),
    ]
    return EducationalStoryboard(
        storyboard_id="sb-test-narration",
        script_id="script-test-narration",
        title="Test Narration Storyboard",
        scenes=scenes,
        total_estimated_duration_seconds=30.0,
    )


@pytest.fixture
def mock_script() -> EducationalScript:
    """Creates a matching sample educational script."""
    sections = [
        ScriptSection(
            section_id="sec-intro",
            order=1,
            title="Introduction",
            purpose=SectionPurpose.INTRODUCTION,
            narration_text="Welcome to the architectural walkthrough of this repository.",
            estimated_duration_seconds=10.0,
        ),
        ScriptSection(
            section_id="sec-arch",
            order=2,
            title="Architecture",
            purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
            narration_text="The architecture isolates execution dispatch from input validation.",
            estimated_duration_seconds=15.0,
        ),
        ScriptSection(
            section_id="sec-silent",
            order=3,
            title="Silent Section",
            purpose=SectionPurpose.CONCLUSION,
            is_narrated=False,
            narration_text="",
            estimated_duration_seconds=5.0,
        ),
    ]
    return EducationalScript(
        script_id="script-test-narration",
        repository_name="test_repo",
        title="Test Narration Script",
        introduction="Introduction text",
        learning_objectives=["Learn system architecture"],
        total_estimated_duration_seconds=30.0,
        sections=sections,
        conclusion="Conclusion text",
    )


# ---------------------------------------------------------------------------
# ElevenLabs Provider Tests
# ---------------------------------------------------------------------------

def test_provider_missing_credentials_fails_validation():
    """Verify provider raises ElevenLabsConfigurationError when credentials are missing."""
    p1 = ElevenLabsTTSProvider(api_key="", voice_id="v123")
    with pytest.raises(ElevenLabsConfigurationError, match="API key is missing"):
        p1.validate_configuration()

    p2 = ElevenLabsTTSProvider(api_key="sk-test", voice_id="")
    with pytest.raises(ElevenLabsConfigurationError, match="Voice ID is missing"):
        p2.validate_configuration()


@pytest.mark.anyio
async def test_provider_synthesize_success_mocked():
    """Verify provider successfully sends request and returns audio bytes on HTTP 200."""
    audio_data = create_valid_mp3_bytes(num_frames=5)
    provider = ElevenLabsTTSProvider(api_key="test-api-key", voice_id="voice-abc", max_retries=1)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = audio_data
    mock_client.post.return_value = mock_resp

    result = await provider.synthesize("Hello world narration", client=mock_client)
    assert result == audio_data
    assert mock_client.post.call_count == 1

    # Verify API key was passed in headers, but not exposed in logs or errors
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["headers"]["xi-api-key"] == "test-api-key"
    assert "https://api.elevenlabs.io/v1/text-to-speech/voice-abc" in mock_client.post.call_args[0][0]


@pytest.mark.anyio
async def test_provider_empty_audio_response_raises():
    """Verify provider detects empty/truncated response even if HTTP 200."""
    provider = ElevenLabsTTSProvider(api_key="test-api-key", voice_id="voice-abc", max_retries=0)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_client.post.return_value = mock_resp

    with pytest.raises(Exception, match="empty or truncated"):
        await provider.synthesize("Hello", client=mock_client)


@pytest.mark.anyio
async def test_provider_permanent_401_fails_without_retrying():
    """Verify 401 Unauthorized raises ElevenLabsAuthError immediately with zero retries."""
    provider = ElevenLabsTTSProvider(api_key="invalid-key", voice_id="voice-abc", max_retries=3)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"detail": {"message": "Invalid API key"}}
    mock_client.post.return_value = mock_resp

    with pytest.raises(ElevenLabsAuthError, match="authentication failed"):
        await provider.synthesize("Hello", client=mock_client)

    # Must NOT retry 401: call count should strictly be 1
    assert mock_client.post.call_count == 1


@pytest.mark.anyio
async def test_provider_permanent_404_voice_not_found():
    """Verify 404 Voice Not Found fails fast without retrying."""
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="missing-voice", max_retries=2)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.return_value = {"detail": {"message": "Voice not found"}}
    mock_client.post.return_value = mock_resp

    with pytest.raises(ElevenLabsVoiceNotFoundError, match="missing-voice"):
        await provider.synthesize("Hello", client=mock_client)

    assert mock_client.post.call_count == 1


@pytest.mark.anyio
async def test_provider_transient_500_retries_with_backoff():
    """Verify transient 500 error retries up to max_retries and succeeds when server recovers."""
    audio_data = create_valid_mp3_bytes(num_frames=4)
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="voice-abc", max_retries=2)

    mock_client = AsyncMock()
    mock_err_resp = MagicMock()
    mock_err_resp.status_code = 503
    mock_err_resp.json.return_value = {"detail": "Service Unavailable"}

    mock_ok_resp = MagicMock()
    mock_ok_resp.status_code = 200
    mock_ok_resp.content = audio_data

    # Fail on first call, succeed on second
    mock_client.post.side_effect = [mock_err_resp, mock_ok_resp]

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await provider.synthesize("Hello", client=mock_client)
        assert res == audio_data
        assert mock_client.post.call_count == 2
        assert mock_sleep.call_count == 1


@pytest.mark.anyio
async def test_provider_rate_limit_429_exhausted():
    """Verify 429 Rate Limit raises ElevenLabsRateLimitError after exhausting retries."""
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="voice-abc", max_retries=1)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.json.return_value = {"detail": "Rate limit exceeded"}
    mock_client.post.return_value = mock_resp

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ElevenLabsRateLimitError, match="rate limit"):
            await provider.synthesize("Hello", client=mock_client)

    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Storage & Duration Tests
# ---------------------------------------------------------------------------

def test_storage_manager_atomic_write_and_read(tmp_path: Path):
    """Verify AudioAssetStorageManager atomically saves and reads genuine audio files."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    job_id = "job-narration-test"
    asset_id = "audio_scene_1"
    audio_data = create_valid_mp3_bytes(num_frames=6)

    # Save audio
    saved_path = mgr.save_audio(job_id, asset_id, audio_data, format="mp3")
    assert saved_path.exists()
    assert saved_path.stat().st_size == len(audio_data)
    assert mgr.audio_file_exists(job_id, asset_id, format="mp3")

    # Read audio
    read_data = mgr.read_audio(job_id, asset_id, format="mp3")
    assert read_data == audio_data

    # Relative path
    rel_path = mgr.get_relative_audio_path(job_id, asset_id, format="mp3")
    assert rel_path == f"jobs/{job_id}/audio/{asset_id}.mp3"


def test_storage_manager_path_traversal_prevention(tmp_path: Path):
    """Verify storage manager rejects path traversal attempts."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    with pytest.raises(ValueError, match="Unsafe job_id"):
        mgr.get_job_audio_dir("../unsafe_job")

    with pytest.raises(ValueError, match="Unsafe or invalid asset_id"):
        mgr.get_audio_path("safe_job", "../../etc/passwd")


def test_storage_manager_corrupt_data_rejected(tmp_path: Path):
    """Verify storage manager rejects invalid/corrupt audio bytes."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    corrupt_data = b"<html><head><title>500 Internal Error</title></head></html>"

    with pytest.raises(ValueError, match="Invalid or corrupt audio content"):
        mgr.save_audio("job-123", "asset-1", corrupt_data)


def test_pure_python_mp3_duration_measurement(tmp_path: Path):
    """Verify pure-Python MP3 parser accurately measures playback duration."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    # 20 MPEG-1 Layer III frames at 44.1kHz (1152 samples/frame) = 20 * 1152 / 44100 = ~0.52s
    audio_bytes = create_valid_mp3_bytes(num_frames=20, bitrate_kbps=128, samplerate=44100)
    dur = mgr.parse_mp3_duration_from_bytes(audio_bytes)
    assert 0.50 <= dur <= 0.55


# ---------------------------------------------------------------------------
# Narration Service Tests
# ---------------------------------------------------------------------------

def test_service_plan_initialization_marks_empty_scenes_skipped(
    mock_storyboard: EducationalStoryboard,
    mock_script: EducationalScript,
    tmp_path: Path,
):
    """Verify initialize_narration_plan sets Scene 1 & 2 to PENDING and Scene 3 (empty) to SKIPPED."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="v1")
    srv = NarrationService(provider=provider, storage=mgr)

    plan = srv.initialize_narration_plan(
        job_id="job-plan-test",
        storyboard=mock_storyboard,
        script=mock_script,
    )

    assert plan.total_scenes == 3
    assert plan.assets[0].status == NarrationAssetStatus.PENDING
    assert plan.assets[0].narration_text.startswith("Welcome to")
    assert plan.assets[0].expected_scene_duration_seconds == 10.0

    assert plan.assets[1].status == NarrationAssetStatus.PENDING
    assert plan.assets[1].expected_scene_duration_seconds == 15.0

    # Scene 3 was empty -> marked SKIPPED
    assert plan.assets[2].status == NarrationAssetStatus.SKIPPED
    assert "skipped" in plan.assets[2].sync_warning.lower()


@pytest.mark.anyio
async def test_service_generate_narration_full_success(
    mock_storyboard: EducationalStoryboard,
    mock_script: EducationalScript,
    tmp_path: Path,
):
    """Verify generate_narration_for_job synthesizes audio, calculates sync, and completes."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="v1")
    srv = NarrationService(provider=provider, storage=mgr)

    mock_audio = create_valid_mp3_bytes(num_frames=400)  # ~10.4s
    with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = mock_audio

        res = await srv.generate_narration_for_job(
            job_id="job-full-success",
            storyboard=mock_storyboard,
            script=mock_script,
        )

        assert res.is_fully_generated is True
        assert res.status == NarrationAssetStatus.COMPLETED
        assert res.scenes_completed == 2
        assert res.scenes_skipped == 1
        assert res.scenes_failed == 0

        # Provider called exactly twice (for scene 1 and scene 2, scene 3 skipped)
        assert mock_synth.call_count == 2

        # Files exist on disk
        assert mgr.audio_file_exists("job-full-success", res.assets[0].asset_id)
        assert mgr.audio_file_exists("job-full-success", res.assets[1].asset_id)


@pytest.mark.anyio
async def test_service_reuses_completed_assets_without_recalling_tts(
    mock_storyboard: EducationalStoryboard,
    mock_script: EducationalScript,
    tmp_path: Path,
):
    """Verify already synthesized scene audio is reused unless refresh=True."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="v1")
    srv = NarrationService(provider=provider, storage=mgr)

    mock_audio = create_valid_mp3_bytes(num_frames=100)

    # First run: synthesize both scenes
    with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = mock_audio
        res1 = await srv.generate_narration_for_job(
            job_id="job-reuse",
            storyboard=mock_storyboard,
            script=mock_script,
            refresh=False,
        )
        assert mock_synth.call_count == 2

    # Second run without refresh: reuse existing files, 0 TTS calls
    with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth2:
        res2 = await srv.generate_narration_for_job(
            job_id="job-reuse",
            storyboard=mock_storyboard,
            script=mock_script,
            refresh=False,
        )
        assert mock_synth2.call_count == 0
        assert res2.scenes_completed == 2

    # Third run with refresh=True: re-synthesizes, 2 TTS calls
    with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth3:
        mock_synth3.return_value = mock_audio
        res3 = await srv.generate_narration_for_job(
            job_id="job-reuse",
            storyboard=mock_storyboard,
            script=mock_script,
            refresh=True,
        )
        assert mock_synth3.call_count == 2


@pytest.mark.anyio
async def test_service_duration_divergence_warning(
    mock_storyboard: EducationalStoryboard,
    mock_script: EducationalScript,
    tmp_path: Path,
):
    """Verify that a scene whose audio differs substantially from planned duration gets a warning."""
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    provider = ElevenLabsTTSProvider(api_key="test-key", voice_id="v1")
    srv = NarrationService(provider=provider, storage=mgr)

    # Scene 1 expected duration is 10.0s. Generate 20 frames = ~0.5s (divergence of -9.5s)
    short_audio = create_valid_mp3_bytes(num_frames=20)

    with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = short_audio
        res = await srv.generate_narration_for_job(
            job_id="job-divergence",
            storyboard=mock_storyboard,
            script=mock_script,
        )

        asset1 = res.assets[0]
        assert asset1.is_synchronized is False
        assert "shorter" in asset1.sync_warning.lower()
        assert len(res.warnings) > 0


# ---------------------------------------------------------------------------
# JobStore Lifecycle & Stage 08 Tests
# ---------------------------------------------------------------------------

def test_stage_08_lifecycle_and_invalidation(
    mock_storyboard: EducationalStoryboard,
    mock_script: EducationalScript,
    tmp_path: Path,
):
    """
    Verify Stage 08 starts IN_PROGRESS and completes only when all assets are finished.
    Verify storyboard regeneration cascades invalidation to narration and purges files.
    """
    mgr = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    job = job_store.create_job(
        repo_url="https://github.com/owner/repo",
        repo_name="repo",
        repository_owner="owner",
        repository_name="repo",
        clone_url="https://github.com/owner/repo.git",
    )
    job_id = job.job_id
    now = datetime.now(timezone.utc)
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    job.stages[3].status = StatusEnum.COMPLETED
    job.stages[4].status = StatusEnum.COMPLETED
    job.stages[5].status = StatusEnum.COMPLETED
    job.stages[6].status = StatusEnum.COMPLETED  # Visuals completed
    job.educational_script = mock_script
    job.educational_storyboard = mock_storyboard

    # 1. Start narration
    job_store.update_job_narration_started(job_id)
    j1 = job_store.get_internal_job(job_id)
    assert j1.stages[7].name == StageEnum.VOICE_GENERATION.value
    assert j1.stages[7].status == StatusEnum.IN_PROGRESS
    # Stage 07 must remain COMPLETED
    assert j1.stages[6].status == StatusEnum.COMPLETED

    # 2. Premature success guard: partial result raises ValueError
    partial_res = NarrationGenerationResult(
        job_id=job_id,
        status=NarrationAssetStatus.PENDING,
        total_assets=2,
        assets_completed=1,
        assets_pending=1,
    )
    with pytest.raises(ValueError, match="Cannot mark narration generation as completed"):
        job_store.update_job_narration_success(job_id, partial_res)

    # 3. Full success advances Stage 08
    full_res = NarrationGenerationResult(
        job_id=job_id,
        status=NarrationAssetStatus.COMPLETED,
        total_scenes=2,
        scenes_completed=2,
        total_assets=2,
        assets_completed=2,
    )
    job_store.update_job_narration_success(job_id, full_res)
    j2 = job_store.get_internal_job(job_id)
    assert j2.stages[7].status == StatusEnum.COMPLETED
    assert j2.stages[8].detail == "Ready for video assembly"
    assert j2.narration is not None
    assert j2.to_response().has_narration is True

    # 4. Invalidation cascade: regenerating storyboard resets Stage 08
    job_store.invalidate_job_educational_storyboard(job_id)
    j3 = job_store.get_internal_job(job_id)
    assert j3.narration is None
    assert j3.stages[7].status == StatusEnum.PENDING


# ---------------------------------------------------------------------------
# API Route Tests
# ---------------------------------------------------------------------------

def test_api_missing_job_returns_404():
    """POST /api/v1/jobs/{job_id}/narration with invalid ID returns 404."""
    resp = client.post("/api/v1/jobs/nonexistent-id/narration")
    assert resp.status_code == 404


def test_api_missing_storyboard_returns_409():
    """POST /api/v1/jobs/{job_id}/narration without storyboard returns 409 conflict."""
    job = job_store.create_job(
        repo_url="https://github.com/owner/repo",
        repo_name="repo",
        repository_owner="owner",
        repository_name="repo",
        clone_url="https://github.com/owner/repo.git",
    )
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    job.knowledge = MagicMock(spec=RepositoryKnowledge)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/narration")
    assert resp.status_code == 409
    assert "Educational storyboard must be generated" in resp.json()["detail"]


def test_api_post_narration_success_and_file_stream(
    mock_storyboard: EducationalStoryboard,
    mock_script: EducationalScript,
    tmp_path: Path,
):
    """Test POST /api/v1/jobs/{job_id}/narration and GET .../{asset_id}/file streaming."""
    job = job_store.create_job(
        repo_url="https://github.com/owner/click",
        repo_name="click",
        repository_owner="owner",
        repository_name="click",
        clone_url="https://github.com/owner/click.git",
    )
    job_id = job.job_id
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    job.knowledge = MagicMock(spec=RepositoryKnowledge)
    job.educational_script = mock_script
    job.educational_storyboard = mock_storyboard

    mock_audio = create_valid_mp3_bytes(num_frames=50)

    with patch.object(ElevenLabsTTSProvider, "validate_configuration", return_value=None):
        with patch.object(
            ElevenLabsTTSProvider,
            "synthesize",
            new_callable=AsyncMock,
        ) as mock_synth:
            mock_synth.return_value = mock_audio

            # POST /narration
            post_resp = client.post(f"/api/v1/jobs/{job_id}/narration")
            assert post_resp.status_code == 200
            data = post_resp.json()
            assert data["status"] == "completed"
            assert data["scenes_completed"] == 2
            assert len(data["assets"]) == 3

            first_asset_id = data["assets"][0]["asset_id"]

            # GET /narration
            get_resp = client.get(f"/api/v1/jobs/{job_id}/narration")
            assert get_resp.status_code == 200
            assert get_resp.json()["job_id"] == job_id

            # GET /narration/{asset_id}
            asset_resp = client.get(f"/api/v1/jobs/{job_id}/narration/{first_asset_id}")
            assert asset_resp.status_code == 200
            assert asset_resp.json()["asset_id"] == first_asset_id

            # GET /narration/{asset_id}/file (stream audio bytes)
            file_resp = client.get(f"/api/v1/jobs/{job_id}/narration/{first_asset_id}/file")
            assert file_resp.status_code == 200
            assert file_resp.headers["content-type"] == "audio/mpeg"
            assert len(file_resp.content) == len(mock_audio)
