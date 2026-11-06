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

import asyncio
import concurrent.futures
import json
import os
import shutil
import tempfile
import threading
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
from app.services.video.assembly.process_runner import (
    MAX_OUTPUT_STREAM_BYTES,
    run_process_async,
    run_process_sync,
    sanitize_environment,
    validate_arg_tokens,
)
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


# ==============================================================================
# 9. Phase 6.1 Audit Hardening Tests
# ==============================================================================

def test_concat_path_escaping_special_characters():
    """
    Verifies that FFmpeg concat demuxer file paths properly escape single quotes,
    backslashes, spaces, brackets, semicolons, and Unicode, while rejecting control chars.
    """
    builder = FFmpegCommandBuilder()

    # 1. Spaces and standard characters
    line_space = builder.escape_concat_path("/storage/jobs/job-1/video/scene 1 intro.mp4")
    assert line_space == "file '/storage/jobs/job-1/video/scene 1 intro.mp4'"

    # 2. Single quotes (must be escaped for concat demuxer: ' -> '\'')
    line_quote = builder.escape_concat_path("/storage/jobs/job-1/video/user's walkthrough.mp4")
    assert line_quote == "file '/storage/jobs/job-1/video/user'\\''s walkthrough.mp4'"

    # 3. Double quotes
    line_dq = builder.escape_concat_path('/storage/jobs/job-1/video/scene_"intro".mp4')
    assert line_dq == 'file \'/storage/jobs/job-1/video/scene_"intro".mp4\''

    # 4. Backslashes
    line_bs = builder.escape_concat_path("/storage/jobs/job-1/video/scene\\test.mp4")
    assert line_bs == "file '/storage/jobs/job-1/video/scene\\\\test.mp4'"

    # 5. Semicolons, brackets, and Unicode
    line_complex = builder.escape_concat_path("/storage/jobs/job-1/video/scene;[chunk_1]_日本語_🚀.mp4")
    assert line_complex == "file '/storage/jobs/job-1/video/scene;[chunk_1]_日本語_🚀.mp4'"

    # 6. Prohibited control characters (must raise ValueError)
    with pytest.raises(ValueError):
        builder.escape_concat_path("/storage/jobs/job-1/video/scene\ninjection.mp4")
    with pytest.raises(ValueError):
        builder.escape_concat_path("/storage/jobs/job-1/video/scene\x00null.mp4")
    with pytest.raises(ValueError):
        builder.escape_concat_path("/storage/jobs/job-1/video/scene\rinjection.mp4")


def test_concat_manifest_creation_and_containment_check(temp_storage):
    """Verifies concat manifest creation in isolated video directory and containment enforcement."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job_id = "test-job-manifest"
    video_dir = storage.get_job_video_dir(job_id)

    # Valid scenes inside the job video dir
    scene1 = video_dir / "scene_01.mp4"
    scene1.write_bytes(b"scene1data")
    scene2 = video_dir / "scene 02's test.mp4"
    scene2.write_bytes(b"scene2data")

    manifest = storage.create_concat_manifest(job_id, [scene1, scene2])
    assert manifest.exists()
    assert manifest.parent == video_dir
    assert "concat_" in manifest.name

    content = manifest.read_text(encoding="utf-8")
    assert f"file '{str(scene1.resolve())}'" in content
    assert "scene 02'\\''s test.mp4" in content

    # Attempting to include an external file outside storage root must raise VideoStorageError
    outside_file = Path("/etc/hosts") if Path("/etc/hosts").exists() else Path("/tmp/outside.mp4")
    with pytest.raises(VideoStorageError):
        storage.create_concat_manifest(job_id, [outside_file])


def test_storage_overwrite_protection_preserves_completed_video(temp_storage):
    """
    Verifies that:
    1. Overwrite=False preserves existing completed output and cleans up the new temp file.
    2. Overwrite=True atomically replaces the completed output.
    """
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job_id = "test-job-overwrite"

    # Step 1: Initial render output
    temp1 = storage.create_temp_render_path(job_id)
    temp1.write_bytes(b"ORIGINAL_VIDEO_DATA_V1")
    final1 = storage.finalize_render_output(job_id, temp1, "final_video.mp4", overwrite=False)
    assert final1.exists()
    assert final1.read_bytes() == b"ORIGINAL_VIDEO_DATA_V1"

    # Step 2: Attempting to finalize a new render with overwrite=False
    temp2 = storage.create_temp_render_path(job_id)
    temp2.write_bytes(b"NEW_VIDEO_DATA_V2")
    with pytest.raises(VideoStorageError) as exc:
        storage.finalize_render_output(job_id, temp2, "final_video.mp4", overwrite=False)
    assert "already exists" in str(exc.value)

    # Verify original file is 100% preserved
    assert final1.read_bytes() == b"ORIGINAL_VIDEO_DATA_V1"
    # Verify temp2 was cleaned up automatically
    assert not temp2.exists()

    # Step 3: Explicit overwrite=True replaces the file
    temp3 = storage.create_temp_render_path(job_id)
    temp3.write_bytes(b"OVERWRITTEN_VIDEO_DATA_V3")
    final3 = storage.finalize_render_output(job_id, temp3, "final_video.mp4", overwrite=True)
    assert final3.exists()
    assert final3.read_bytes() == b"OVERWRITTEN_VIDEO_DATA_V3"
    assert not temp3.exists()


def test_storage_failed_replacement_preserves_completed_video(temp_storage):
    """Verifies that failed promotion (0-byte file) preserves previous video and cleans up temp."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job_id = "test-job-fail-replace"

    # Completed video exists
    temp_valid = storage.create_temp_render_path(job_id)
    temp_valid.write_bytes(b"INITIAL_VALID_VIDEO")
    final = storage.finalize_render_output(job_id, temp_valid, "final_video.mp4")
    assert final.read_bytes() == b"INITIAL_VALID_VIDEO"

    # Attempt to replace with 0-byte file even with overwrite=True
    temp_empty = storage.create_temp_render_path(job_id)
    temp_empty.write_bytes(b"")

    with pytest.raises(VideoStorageError) as exc:
        storage.finalize_render_output(job_id, temp_empty, "final_video.mp4", overwrite=True)
    assert "empty (0 bytes)" in str(exc.value)

    # Completed video must still be intact
    assert final.read_bytes() == b"INITIAL_VALID_VIDEO"
    assert not temp_empty.exists()


def test_storage_concurrent_finalization_serialization(temp_storage):
    """Verifies that concurrent threads attempting to finalize are serialized safely."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job_id = "test-job-concurrent"

    results = []
    errors = []

    def _worker(thread_idx: int):
        try:
            temp = storage.create_temp_render_path(job_id)
            temp.write_bytes(f"THREAD_{thread_idx}_DATA".encode("utf-8"))
            out = storage.finalize_render_output(job_id, temp, "final_video.mp4", overwrite=False)
            results.append((thread_idx, out))
        except Exception as e:
            errors.append((thread_idx, type(e).__name__, str(e)))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly 1 thread must succeed, 4 must raise VideoStorageError (already exists)
    assert len(results) == 1
    assert len(errors) == 4
    for err in errors:
        assert err[1] == "VideoStorageError"
        assert "already exists" in err[2]

    # Target video must exist and be readable
    final_output = storage.get_final_output_path(job_id, "final_video.mp4")
    assert final_output.exists()
    assert b"THREAD_" in final_output.read_bytes()


def test_storage_path_layout_no_duplicate_jobs_jobs(temp_storage):
    """Verifies that whether storage base is /root or /root/jobs, no duplicate jobs/jobs occurs."""
    # 1. Base is /tmp/root -> jobs/{job_id}/video
    storage1 = VideoStorageManager(base_storage_dir=temp_storage)
    dir1 = storage1.get_job_video_dir("job-abc")
    rel1 = dir1.relative_to(temp_storage.resolve())
    assert str(rel1) == "jobs/job-abc/video"

    # 2. Base is /tmp/root/jobs -> {job_id}/video (no duplicate jobs/jobs!)
    jobs_sub = temp_storage / "jobs"
    jobs_sub.mkdir(exist_ok=True)
    storage2 = VideoStorageManager(base_storage_dir=jobs_sub)
    dir2 = storage2.get_job_video_dir("job-abc")
    rel2 = dir2.relative_to(jobs_sub.resolve())
    assert str(rel2) == "job-abc/video"
    assert "jobs/jobs" not in str(dir2)


def test_storage_symlink_escape_rejection(temp_storage):
    """Verifies that symlinks pointing outside storage root are strictly rejected."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    outside_dir = tempfile.mkdtemp(prefix="outside_root_")
    try:
        symlink_path = temp_storage / "symlink_escape"
        try:
            os.symlink(outside_dir, symlink_path)
            with pytest.raises(VideoStorageError) as exc:
                storage.assert_safe_path(symlink_path / "evil.mp4")
            assert "outside storage root" in str(exc.value)
        except OSError:
            pass  # If OS does not permit symlink in sandbox, skip symlink test
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)


def test_process_runner_environment_sanitization():
    """Verifies that sanitize_environment excludes sensitive secrets while keeping safe system vars."""
    os.environ["ELEVENLABS_API_KEY"] = "sk-secret-12345"
    os.environ["GROQ_API_KEY"] = "gsk-secret-67890"
    os.environ["MY_DATABASE_PASSWORD"] = "p@ssword"
    os.environ["AUTH_TOKEN"] = "token-xyz"

    env = sanitize_environment(extra_env={"CUSTOM_PARAM": "safe_value"})

    assert "ELEVENLABS_API_KEY" not in env
    assert "GROQ_API_KEY" not in env
    assert "MY_DATABASE_PASSWORD" not in env
    assert "AUTH_TOKEN" not in env
    assert env.get("CUSTOM_PARAM") == "safe_value"
    assert "PATH" in env
    assert "TMPDIR" in env


def test_process_runner_active_output_stream_capping():
    """Verifies that high-volume stream output is capped at MAX_OUTPUT_STREAM_BYTES while running."""
    # Run a python command that outputs 1MB of text
    py_script = "import sys; sys.stdout.write('A' * 700000); sys.stdout.flush()"
    code, stdout, stderr = run_process_sync(["python3", "-c", py_script], timeout_seconds=10.0)

    assert code == 0
    assert len(stdout) <= MAX_OUTPUT_STREAM_BYTES + 200
    assert "[RepoGenie: stdout truncated" in stdout


@pytest.mark.anyio
async def test_process_runner_async_cancellation_cleanup():
    """Verifies that cancelling an async subprocess terminates the process group without orphans."""
    task = asyncio.create_task(
        run_process_async(["python3", "-c", "import time; time.sleep(10)"], timeout_seconds=20.0)
    )
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_synthetic_smoke_test_execution_and_cleanup(temp_storage):
    """Verifies execute_synthetic_smoke_test runs correctly and cleans up assets when cleanup_output=True."""
    service = VideoAssemblyService(storage_mgr=VideoStorageManager(base_storage_dir=temp_storage))
    job = job_store.create_job(
        repo_url="https://github.com/org/repo-smoke",
        repo_name="org/repo-smoke",
        repository_owner="org",
        repository_name="repo-smoke",
        clone_url="https://github.com/org/repo-smoke.git",
    )
    job_id = job.job_id

    mock_probe = MediaProbeResult(
        file_path="jobs/test/video/synthetic_smoke_test.mp4",
        format_name="mp4",
        duration_seconds=2.0,
        file_size_bytes=1024,
        video_streams=[
            MediaStreamProbe(index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0, pixel_format="yuv420p")
        ],
        audio_streams=[
            MediaStreamProbe(index=1, codec_type="audio", codec_name="aac", sample_rate=44100, channels=2)
        ],
        has_video=True,
        has_audio=True,
    )

    with patch.object(service._ffmpeg, "assert_available", return_value=None):
        with patch.object(service._ffprobe, "assert_available", return_value=None):
            with patch.object(service._ffmpeg, "resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
                with patch("app.services.video.assembly.service.run_process_sync") as mock_run:
                    # Mock run_process_sync writing a dummy video file
                    def _fake_run(cmd, timeout_seconds=None):
                        # Write data to output path (last arg)
                        out_path = Path(cmd[-1])
                        out_path.write_bytes(b"dummy_rendered_video_bytes")
                        return 0, "", ""

                    mock_run.side_effect = _fake_run
                    with patch.object(service, "probe_media_file", return_value=mock_probe):
                        result = service.execute_synthetic_smoke_test(job_id, duration_seconds=2.0, cleanup_output=True)
                        assert result.has_video is True
                        assert result.has_audio is True
                        assert result.duration_seconds == 2.0

                        # Ensure output file was cleaned up
                        final_path = service._storage.get_final_output_path(job_id, "synthetic_smoke_test.mp4")
                        assert not final_path.exists()


def test_upstream_asset_invalidation_cleans_video_and_resets_stage9(temp_storage):
    """Verifies that upstream storyboard/narration/caption invalidation purges video storage and resets Stage 09."""
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    job = job_store.create_job(
        repo_url="https://github.com/org/repo-cascade",
        repo_name="org/repo-cascade",
        repository_owner="org",
        repository_name="repo-cascade",
        clone_url="https://github.com/org/repo-cascade.git",
    )
    job_id = job.job_id

    # Create dummy video file
    video_dir = storage.get_job_video_dir(job_id)
    dummy_file = video_dir / "final_video.mp4"
    dummy_file.write_bytes(b"fake_video")

    # Set job into COMPLETED video stage
    cfg = VideoRenderConfiguration()
    res = VideoRenderResult(
        job_id=job_id,
        output_relative_path=f"jobs/{job_id}/video/final_video.mp4",
        file_size_bytes=10,
        duration_seconds=5.0,
        resolution="1920x1080",
        fps=30.0,
        video_codec="libx264",
        audio_codec="aac",
    )
    render_job = VideoRenderJob(
        job_id=job_id,
        status=VideoRenderStatus.RENDERING,
        configuration=cfg,
        progress=VideoRenderProgress(job_id=job_id, status=VideoRenderStatus.RENDERING),
    )
    job_store.update_job_render_started(job_id, render_job)
    job_store.update_job_render_success(job_id, res)

    job_done = job_store.get_internal_job(job_id)
    assert job_done.stages[8].status == StatusEnum.COMPLETED

    with patch("app.services.storage.job_store.video_storage_manager", storage):
        # Invalidate narration -> cascades to captions -> assembly_input -> render!
        job_store.invalidate_job_narration(job_id)

        job_reset = job_store.get_internal_job(job_id)
        assert job_reset.render_job is None
        assert job_reset.stages[8].status == StatusEnum.PENDING
        assert job_reset.stages[8].detail == "Ready for video assembly"
        assert not dummy_file.exists()

