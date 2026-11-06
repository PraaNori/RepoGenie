"""
Milestone 6, Phase 6.1 Automated Test Suite: FFmpeg Video Assembly Foundation.

Tests cover:
1. Executable discovery and version parsing (FFmpeg and FFprobe).
2. Missing executable error handling and clear messaging.
3. Safe argument construction and injection defense.
4. Process execution timeouts and non-zero exit handling.
5. Path traversal defense and isolated storage management.
6. Media probe JSON parsing and structured stream extraction.
7. Render configuration validation (dimensions, codecs, aspect ratios).
8. JobStore rendering lifecycle and Stage 09 invariants.
9. FastAPI endpoints: GET /api/v1/video/status, GET/PUT render-config, GET render.
10. Concurrency protection.
"""

import json
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
from app.services.storage.job_store import job_store
from app.services.video.assembly.command_builder import FFmpegCommandBuilder, command_builder
from app.services.video.assembly.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FFprobeNotFoundError,
    FFmpegTimeoutError,
    InvalidRenderConfigurationError,
    JobRenderConcurrencyError,
    MediaProbeError,
    VideoStorageError,
)
from app.services.video.assembly.ffmpeg_manager import FFmpegManager
from app.services.video.assembly.ffprobe_manager import FFprobeManager
from app.services.video.assembly.process_runner import run_process_async, run_process_sync, validate_arg_tokens
from app.services.video.assembly.schemas import (
    MediaProbeResult,
    MediaStreamProbe,
    VideoAssemblySystemStatus,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderProgress,
    VideoRenderResult,
    VideoRenderStatus,
)
from app.services.video.assembly.service import VideoAssemblyService
from app.services.video.assembly.storage import VideoStorageManager

client = TestClient(app)


@pytest.fixture
def temp_storage():
    """Provides a fresh isolated temporary directory for storage tests."""
    temp_dir = tempfile.mkdtemp(prefix="repogenie_assembly_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. Executable Discovery, Missing Binaries & Version Parsing
# ==============================================================================

def test_ffmpeg_missing_executable_handling():
    """Verifies clear error reporting when ffmpeg binary is not found."""
    mgr = FFmpegManager(binary_path="non_existent_ffmpeg_bin_xyz")
    status = mgr.get_status(refresh=True)

    assert status.is_available is False
    assert status.executable_path is None
    assert status.version is None
    assert "was not found in system PATH" in status.error

    with pytest.raises(FFmpegNotFoundError) as excinfo:
        mgr.assert_available()
    assert "was not found in system PATH" in str(excinfo.value) or "not available" in str(excinfo.value)


def test_ffprobe_missing_executable_handling():
    """Verifies clear error reporting when ffprobe binary is not found."""
    mgr = FFprobeManager(binary_path="non_existent_ffprobe_bin_xyz")
    status = mgr.get_status(refresh=True)

    assert status.is_available is False
    assert status.executable_path is None
    assert "was not found in system PATH" in status.error

    with pytest.raises(FFprobeNotFoundError) as excinfo:
        mgr.assert_available()
    assert "was not found in system PATH" in str(excinfo.value) or "not available" in str(excinfo.value)


def test_ffmpeg_version_and_codecs_parsing():
    """Verifies parsing of simulated ffmpeg -version and -encoders outputs."""
    mgr = FFmpegManager(binary_path="ffmpeg")

    mock_version_stdout = (
        "ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers\n"
        "built with Apple clang version 15.0.0\n"
        "configuration: --enable-libx264\n"
    )
    mock_encoders_stdout = (
        "Encoders:\n"
        " V..... = Video\n"
        " A..... = Audio\n"
        " V..... libx264              H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)\n"
        " A..... aac                  AAC (Advanced Audio Coding)\n"
    )

    with patch.object(mgr, "resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
        with patch("app.services.video.assembly.ffmpeg_manager.run_process_sync") as mock_run:
            mock_run.side_effect = [
                (0, mock_version_stdout, ""),
                (0, mock_encoders_stdout, ""),
            ]

            status = mgr.get_status(refresh=True)
            assert status.is_available is True
            assert status.version == "6.1.1"
            assert "libx264" in status.codecs_supported
            assert "aac" in status.codecs_supported
            assert status.error is None


def test_ffprobe_version_parsing():
    """Verifies parsing of simulated ffprobe -version output."""
    mgr = FFprobeManager(binary_path="ffprobe")
    mock_version_stdout = "ffprobe version 6.1.1 Copyright (c) 2007-2023 the FFmpeg developers\n"

    with patch.object(mgr, "resolve_binary", return_value=Path("/usr/local/bin/ffprobe")):
        with patch("app.services.video.assembly.ffprobe_manager.run_process_sync", return_value=(0, mock_version_stdout, "")):
            status = mgr.get_status(refresh=True)
            assert status.is_available is True
            assert status.version == "6.1.1"


# ==============================================================================
# 2. Process Runner Safety, Timeouts, and Injection Prevention
# ==============================================================================

def test_argument_validation_rejects_null_bytes_and_newlines():
    """Verifies rejection of argument tokens containing null bytes or line breaks."""
    with pytest.raises(ValueError) as exc:
        validate_arg_tokens(["ffmpeg", "input\x00.mp4"])
    assert "prohibited control character" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate_arg_tokens(["ffmpeg", "input\n.mp4"])
    assert "prohibited control character" in str(exc.value)


def test_process_runner_handles_non_zero_exit():
    """Verifies that non-zero return codes are cleanly returned with stdout and stderr."""
    # Using 'false' system binary or python exit(1)
    ret, out, err = run_process_sync(["python3", "-c", "import sys; sys.stderr.write('Test error message\\n'); sys.exit(2)"])
    assert ret == 2
    assert "Test error message" in err


def test_process_runner_timeout_raises_exception():
    """Verifies that exceeding the execution timeout raises FFmpegTimeoutError."""
    with pytest.raises(FFmpegTimeoutError) as excinfo:
        run_process_sync(["python3", "-c", "import time; time.sleep(5)"], timeout_seconds=0.2)
    assert excinfo.value.timeout_seconds == 0.2


# ==============================================================================
# 3. Path Traversal Defense & Isolated Video Storage
# ==============================================================================

def test_storage_rejects_unsafe_job_ids(temp_storage):
    """Verifies that job IDs with path traversal patterns are rejected."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)

    with pytest.raises(VideoStorageError):
        storage.assert_safe_job_id("../escaped_job")

    with pytest.raises(VideoStorageError):
        storage.assert_safe_job_id("job/with/slashes")

    with pytest.raises(VideoStorageError):
        storage.assert_safe_job_id("job with spaces")


def test_storage_isolated_output_and_atomic_finalization(temp_storage):
    """Verifies isolated directory creation, relative path formatting, and atomic rename."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job_id = "test-job-storage-123"

    job_dir = storage.get_job_video_dir(job_id)
    assert job_dir.exists()
    assert str(job_dir).startswith(str(temp_storage.resolve()))

    rel_path = storage.get_relative_video_path(job_id, "final_video.mp4")
    assert rel_path == f"jobs/{job_id}/video/final_video.mp4"

    # Create temporary file
    temp_render = storage.create_temp_render_path(job_id, extension="mp4")
    assert temp_render.parent == job_dir
    assert "render_" in temp_render.name

    # Write dummy non-empty data
    temp_render.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 20)

    # Finalize
    final_output = storage.finalize_render_output(job_id, temp_render, "final_video.mp4")
    assert final_output.exists()
    assert not temp_render.exists()
    assert final_output.stat().st_size > 0

    # Overwrite protection: attempting to finalize again without overwrite=True raises error
    temp_render2 = storage.create_temp_render_path(job_id, extension="mp4")
    temp_render2.write_bytes(b"dummy")
    with pytest.raises(VideoStorageError) as exc:
        storage.finalize_render_output(job_id, temp_render2, "final_video.mp4", overwrite=False)
    assert "already exists" in str(exc.value)


def test_storage_rejects_empty_file_finalization(temp_storage):
    """Verifies that empty 0-byte temporary render files are rejected during finalization."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job_id = "test-empty-job"

    temp_render = storage.create_temp_render_path(job_id)
    temp_render.write_bytes(b"")  # 0 bytes

    with pytest.raises(VideoStorageError) as exc:
        storage.finalize_render_output(job_id, temp_render, "empty.mp4")
    assert "is empty (0 bytes)" in str(exc.value)
    assert not temp_render.exists()  # Cleaned up


# ==============================================================================
# 4. Media Probing (FFprobe)
# ==============================================================================

def test_ffprobe_json_output_parsing(temp_storage):
    """Verifies parsing of structured ffprobe JSON output into MediaProbeResult."""
    mgr = FFprobeManager(binary_path="ffprobe")
    dummy_media = temp_storage / "sample.mp4"
    dummy_media.write_bytes(b"dummy_mp4_bytes")

    mock_probe_data = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "12.500000",
            "size": "2048500",
            "bit_rate": "1311040",
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "pix_fmt": "yuv420p",
                "duration": "12.500000",
                "bit_rate": "1118000",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 2,
                "channel_layout": "stereo",
                "duration": "12.500000",
                "bit_rate": "192000",
            },
        ],
    }

    with patch.object(mgr, "assert_available", return_value=Path("/usr/local/bin/ffprobe")):
        with patch("app.services.video.assembly.ffprobe_manager.run_process_sync", return_value=(0, json.dumps(mock_probe_data), "")):
            probe = mgr.probe_media_file(dummy_media)

            assert probe.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
            assert probe.duration_seconds == 12.5
            assert probe.size_bytes == 2048500
            assert probe.has_video is True
            assert probe.has_audio is True
            assert probe.primary_video_stream.codec_name == "h264"
            assert probe.primary_video_stream.width == 1920
            assert probe.primary_video_stream.height == 1080
            assert probe.primary_video_stream.fps == 30.0
            assert probe.primary_audio_stream.codec_name == "aac"
            assert probe.primary_audio_stream.sample_rate == 44100


def test_ffprobe_handles_corrupt_json(temp_storage):
    """Verifies that malformed probe JSON output raises MediaProbeError."""
    mgr = FFprobeManager(binary_path="ffprobe")
    dummy_media = temp_storage / "sample_bad.mp4"
    dummy_media.write_bytes(b"dummy")

    with patch.object(mgr, "assert_available", return_value=Path("/usr/local/bin/ffprobe")):
        with patch("app.services.video.assembly.ffprobe_manager.run_process_sync", return_value=(0, "NOT_JSON_OUTPUT", "")):
            with pytest.raises(MediaProbeError) as exc:
                mgr.probe_media_file(dummy_media)
            assert "Failed to parse ffprobe JSON output" in str(exc.value)


# ==============================================================================
# 5. Render Configuration Validation
# ==============================================================================

def test_render_configuration_validation_rules():
    """Verifies default values and strict validation on dimensions and aspect ratios."""
    # Default valid config
    cfg = VideoRenderConfiguration()
    assert cfg.resolution_width == 1920
    assert cfg.resolution_height == 1080
    assert cfg.fps == 30
    assert cfg.video_codec == "libx264"
    assert cfg.pixel_format == "yuv420p"
    assert cfg.faststart is True

    # Odd width rejected (libx264 requirement)
    with pytest.raises(ValueError) as exc:
        VideoRenderConfiguration(resolution_width=1921, resolution_height=1080)
    assert "must be an even number" in str(exc.value)

    # Odd height rejected
    with pytest.raises(ValueError) as exc:
        VideoRenderConfiguration(resolution_width=1920, resolution_height=1081)
    assert "must be an even number" in str(exc.value)

    # Aspect ratio mismatch rejected
    with pytest.raises(ValueError) as exc:
        VideoRenderConfiguration(resolution_width=1000, resolution_height=1000, aspect_ratio="16:9")
    assert "does not match 16:9 aspect ratio" in str(exc.value)

    # Unsupported video codec rejected
    with pytest.raises(ValueError) as exc:
        VideoRenderConfiguration(video_codec="unsupported_codec_xyz")
    assert "Unsupported video codec" in str(exc.value)


# ==============================================================================
# 6. Command Builder Argument Construction
# ==============================================================================

def test_command_builder_scene_render_arguments(temp_storage):
    """Verifies that command builder constructs safe, correctly typed argument arrays."""
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")
    img_path = temp_storage / "scene.svg"
    img_path.write_text("<svg/>")
    audio_path = temp_storage / "scene.mp3"
    audio_path.write_bytes(b"mp3")
    output_path = temp_storage / "output.mp4"

    cfg = VideoRenderConfiguration(resolution_width=1280, resolution_height=720, fps=24, crf=20)
    cmd = builder.build_scene_render_command(
        image_path=img_path,
        audio_path=audio_path,
        output_path=output_path,
        duration_seconds=6.5,
        config=cfg,
    )

    assert isinstance(cmd, list)
    assert cmd[0] == "ffmpeg"
    assert "-loop" in cmd
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "-pix_fmt" in cmd
    assert "yuv420p" in cmd
    assert "-crf" in cmd
    assert "20" in cmd
    assert "-r" in cmd
    assert "24" in cmd
    assert "-c:a" in cmd
    assert "aac" in cmd
    assert "-movflags" in cmd
    assert "+faststart" in cmd
    assert cmd[-1] == str(output_path.resolve())


# ==============================================================================
# 7. JobStore Lifecycle & Stage 09 Invariants
# ==============================================================================

def test_jobstore_render_lifecycle_and_stage9_invariants():
    """Verifies rendering lifecycle in JobStore: Stage 09 remains PENDING until rendering starts."""
    job = job_store.create_job(
        repo_url="https://github.com/org/repo-render",
        repo_name="org/repo-render",
        repository_owner="org",
        repository_name="repo-render",
        clone_url="https://github.com/org/repo-render.git",
    )
    job_id = job.job_id

    # Stage 09 initial invariant
    assert job.stages[8].name == StageEnum.VIDEO_ASSEMBLY.value
    assert job.stages[8].status == StatusEnum.PENDING
    assert job_store.get_job_render(job_id) is None

    # Update render config -> Stage 09 MUST remain PENDING
    cfg = VideoRenderConfiguration(resolution_width=1280, resolution_height=720, fps=25)
    job_store.update_job_render_config(job_id, cfg)
    job_updated = job_store.get_internal_job(job_id)
    assert job_updated.stages[8].status == StatusEnum.PENDING

    # Start render job
    render_job = VideoRenderJob(
        job_id=job_id,
        status=VideoRenderStatus.RENDERING,
        configuration=cfg,
        progress=VideoRenderProgress(job_id=job_id, status=VideoRenderStatus.RENDERING, progress_percentage=10),
    )
    job_store.update_job_render_started(job_id, render_job)
    job_rendering = job_store.get_internal_job(job_id)
    assert job_rendering.stages[8].status == StatusEnum.IN_PROGRESS
    assert job_rendering.current_stage == StageEnum.VIDEO_ASSEMBLY.value

    # Update progress
    progress = VideoRenderProgress(job_id=job_id, status=VideoRenderStatus.RENDERING, progress_percentage=50, stage_detail="Encoding scene 2/4")
    job_store.update_job_render_progress(job_id, progress)
    job_progress = job_store.get_internal_job(job_id)
    assert job_progress.stages[8].detail == "Encoding scene 2/4"

    # Invalidation resets Stage 09 to PENDING
    job_store.invalidate_job_render(job_id)
    job_invalidated = job_store.get_internal_job(job_id)
    assert job_invalidated.render_job is None
    assert job_invalidated.stages[8].status == StatusEnum.PENDING


# ==============================================================================
# 8. FastAPI Endpoints
# ==============================================================================

def test_api_video_status_endpoint():
    """Verifies GET /api/v1/video/status returns valid system availability status."""
    res = client.get("/api/v1/video/status")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "ffmpeg" in data
    assert "ffprobe" in data
    assert "is_ready" in data
    assert "default_configuration" in data


def test_api_render_config_endpoints():
    """Verifies GET and PUT /api/v1/jobs/{job_id}/render-config."""
    job = job_store.create_job(
        repo_url="https://github.com/org/repo-api-render",
        repo_name="org/repo-api-render",
        repository_owner="org",
        repository_name="repo-api-render",
        clone_url="https://github.com/org/repo-api-render.git",
    )
    job_id = job.job_id

    # 1. GET initial default config
    res = client.get(f"/api/v1/jobs/{job_id}/render-config")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["resolution_width"] == 1920
    assert data["resolution_height"] == 1080
    assert data["fps"] == 30

    # 2. PUT custom valid configuration
    update_payload = {
        "resolution_width": 1280,
        "resolution_height": 720,
        "aspect_ratio": "16:9",
        "fps": 24,
        "video_codec": "libx264",
        "pixel_format": "yuv420p",
        "audio_codec": "aac",
        "audio_sample_rate": 48000,
        "audio_channels": 2,
        "audio_bitrate": "192k",
        "faststart": True,
        "container_format": "mp4",
    }
    res_put = client.put(f"/api/v1/jobs/{job_id}/render-config", json=update_payload)
    assert res_put.status_code == status.HTTP_200_OK
    assert res_put.json()["resolution_width"] == 1280
    assert res_put.json()["fps"] == 24

    # 3. PUT invalid configuration (e.g. odd width) -> HTTP 422
    invalid_payload = dict(update_payload)
    invalid_payload["resolution_width"] = 1281
    res_err = client.put(f"/api/v1/jobs/{job_id}/render-config", json=invalid_payload)
    assert res_err.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY or res_err.status_code == status.HTTP_400_BAD_REQUEST

    # 4. GET /api/v1/jobs/{job_id}/render initially returns null
    res_render = client.get(f"/api/v1/jobs/{job_id}/render")
    assert res_render.status_code == status.HTTP_200_OK
    assert res_render.json() is None
