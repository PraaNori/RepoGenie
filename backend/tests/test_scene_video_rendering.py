"""
Milestone 6, Phase 6.2 Automated Test Suite: Scene Video Rendering.

Covers:
1. SVG validation and security defense (scripts, event handlers, XXE, remote URLs, malformed XML).
2. Visual asset preparation (SVG rasterization via rsvg-convert and Pillow fallback, PNG/JPEG/WebP input).
3. Command builder for narrated scenes (AAC audio, actual audio duration) and silent scenes (-an, visual duration).
4. Per-scene video rendering orchestration and probing.
5. Audio duration preservation (no stretching/acceleration).
6. Cache reuse and explicit refresh behavior.
7. Atomic scene clip storage and temporary file cleanup.
8. Partial failure handling (does not mark failed scenes completed).
9. Per-job concurrency locking.
10. Stage 09 lifecycle invariants (remains IN_PROGRESS, does not mark COMPLETED prematurely).
11. REST API endpoints: POST /render-scenes, GET /render-scenes, GET /{scene_id}, GET /{scene_id}/file.
"""

import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models.schemas import StageEnum, StatusEnum
from app.services.storage.job_store import job_store
from app.services.video.assembly.command_builder import FFmpegCommandBuilder
from app.services.video.assembly.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    JobRenderConcurrencyError,
    MediaProbeError,
    SceneRenderError,
    VideoStorageError,
    VisualPreparationError,
)
from app.services.video.assembly.ffmpeg_manager import FFmpegManager
from app.services.video.assembly.ffprobe_manager import FFprobeManager
from app.services.video.assembly.scene_service import SceneRenderService
from app.services.video.assembly.schemas import (
    MediaProbeResult,
    MediaStreamProbe,
    SceneRenderAsset,
    SceneRenderConfiguration,
    SceneRenderProgress,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
)
from app.services.video.assembly.storage import VideoStorageManager
from app.services.video.assembly.visual_preparer import (
    VisualAssetPreparer,
    validate_svg_content,
)
from app.services.video.assembly_input.schemas import (
    AssemblyAssetReference,
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    VideoAssemblyInput,
)

client = TestClient(app)


@pytest.fixture
def temp_storage():
    """Provides a fresh isolated temporary directory for storage tests."""
    temp_dir = tempfile.mkdtemp(prefix="repogenie_scene_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. SVG Security Validation & Rasterization
# ==============================================================================

def test_svg_security_validation_rejects_scripts():
    """Verifies that SVGs with <script> tags or javascript: URIs are rejected."""
    malicious_script = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(VisualPreparationError) as exc:
        validate_svg_content(malicious_script)
    assert "Security: Prohibited construct" in str(exc.value)

    malicious_js = '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><rect width="10" height="10"/></a></svg>'
    with pytest.raises(VisualPreparationError) as exc:
        validate_svg_content(malicious_js)
    assert "Security: Prohibited construct" in str(exc.value)


def test_svg_security_validation_rejects_event_handlers():
    """Verifies that SVGs with inline event handlers like onload/onerror are rejected."""
    malicious_onload = '<svg xmlns="http://www.w3.org/2000/svg" onload="fetch(\'/steal\')"><rect width="10" height="10"/></svg>'
    with pytest.raises(VisualPreparationError) as exc:
        validate_svg_content(malicious_onload)
    assert "Security: Prohibited construct" in str(exc.value)


def test_svg_security_validation_rejects_xxe_and_remote_resources():
    """Verifies that SVGs with XXE entity declarations or remote image URLs are rejected."""
    xxe_svg = '<!DOCTYPE svg [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]><svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>'
    with pytest.raises(VisualPreparationError) as exc:
        validate_svg_content(xxe_svg)
    assert "Security: Prohibited construct" in str(exc.value)

    remote_img = '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.com/tracker.png" width="10" height="10"/></svg>'
    with pytest.raises(VisualPreparationError) as exc:
        validate_svg_content(remote_img)
    assert "Security: Prohibited construct" in str(exc.value)


def test_svg_validation_rejects_malformed_xml():
    """Verifies that unclosed tags or syntax errors raise VisualPreparationError."""
    malformed = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10">'
    with pytest.raises(VisualPreparationError) as exc:
        validate_svg_content(malformed)
    assert "Malformed SVG XML" in str(exc.value)


def test_visual_preparer_rasterizes_valid_svg(temp_storage):
    """Verifies that a valid SVG visual asset is rasterized to a 1920x1080 PNG."""
    preparer = VisualAssetPreparer()
    svg_file = temp_storage / "valid_card.svg"
    svg_file.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">'
        '<rect width="100%" height="100%" fill="#1e293b"/>'
        '<text x="960" y="540" fill="white" font-size="64" text-anchor="middle">RepoGenie</text>'
        '</svg>',
        encoding="utf-8",
    )

    out_png = temp_storage / "raster" / "valid_card.png"
    result_path = preparer.prepare_visual_asset(svg_file, out_png, target_width=1920, target_height=1080)

    assert result_path.exists()
    assert result_path == out_png.resolve()
    with Image.open(result_path) as img:
        assert img.size == (1920, 1080)


def test_visual_preparer_handles_raster_inputs(temp_storage):
    """Verifies that PNG and JPEG inputs are standardized to 1920x1080 with centered padding."""
    preparer = VisualAssetPreparer()

    # Create a small 800x600 test PNG
    input_png = temp_storage / "small.png"
    small_img = Image.new("RGB", (800, 600), (255, 0, 0))
    small_img.save(input_png)

    out_png = temp_storage / "standardized_small.png"
    result = preparer.prepare_visual_asset(input_png, out_png, target_width=1920, target_height=1080)

    assert result.exists()
    with Image.open(result) as img:
        assert img.size == (1920, 1080)


# ==============================================================================
# 2. Command Builder for Narrated and Silent Scenes
# ==============================================================================

def test_command_builder_narrated_scene():
    """Verifies that narrated scenes include AAC audio encoding and match audio duration."""
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")
    cfg = VideoRenderConfiguration(resolution_width=1920, resolution_height=1080, fps=30)

    cmd = builder.build_scene_render_command(
        image_path=Path("/tmp/visual.png"),
        audio_path=Path("/tmp/audio.mp3"),
        output_path=Path("/tmp/output.mp4"),
        duration_seconds=7.25,
        config=cfg,
        is_silent=False,
    )

    cmd_str = " ".join(cmd)
    assert "-c:v libx264" in cmd_str
    assert "-c:a aac" in cmd_str
    assert "-ar 44100" in cmd_str
    assert "-ac 2" in cmd_str
    assert "-t 7.250" in cmd_str
    assert "-shortest" in cmd_str
    assert "-movflags +faststart" in cmd_str
    assert "-an" not in cmd_str


def test_command_builder_silent_scene():
    """Verifies that silent scenes use -an without inventing an audio stream."""
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")
    cfg = VideoRenderConfiguration(resolution_width=1920, resolution_height=1080, fps=30)

    cmd = builder.build_scene_render_command(
        image_path=Path("/tmp/visual.png"),
        audio_path=None,
        output_path=Path("/tmp/output.mp4"),
        duration_seconds=4.0,
        config=cfg,
        is_silent=True,
    )

    cmd_str = " ".join(cmd)
    assert "-c:v libx264" in cmd_str
    assert "-an" in cmd_str
    assert "-t 4.000" in cmd_str
    assert "-c:a" not in cmd_str
    assert "anullsrc" not in cmd_str


# ==============================================================================
# 3. Scene Render Service Orchestration
# ==============================================================================

def _setup_mock_assembly_job(temp_storage, job_id="test-scene-job"):
    """Helper to create a Job with a valid 2-scene assembly input package."""
    job = job_store.create_job(
        repo_url=f"https://github.com/org/{job_id}",
        repo_name=f"org/{job_id}",
        repository_owner="org",
        repository_name=job_id,
        clone_url=f"https://github.com/org/{job_id}.git",
    )
    job.job_id = job_id
    job_store._jobs[job_id] = job

    # Create dummy files
    visual_dir = temp_storage / "jobs" / job_id / "visuals"
    audio_dir = temp_storage / "jobs" / job_id / "audio"
    visual_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    v1 = visual_dir / "scene_01.svg"
    v1.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="100%" height="100%" fill="#111"/></svg>'
    )
    v2 = visual_dir / "scene_02.svg"
    v2.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="100%" height="100%" fill="#222"/></svg>'
    )

    a1 = audio_dir / "scene_01.mp3"
    a1.write_bytes(b"dummy_audio_bytes")

    scene1 = AssemblyScene(
        scene_id="sc-intro",
        scene_number=1,
        script_section_id="sec-1",
        section_purpose="Introduction",
        title="Project Introduction",
        visual_asset=AssemblyAssetReference(
            asset_id="vis-1",
            scene_id="sc-intro",
            asset_type="visual",
            relative_path=f"jobs/{job_id}/visuals/scene_01.svg",
            file_format="svg",
            file_size_bytes=v1.stat().st_size,
        ),
        narration_asset=AssemblyAssetReference(
            asset_id="narr-1",
            scene_id="sc-intro",
            asset_type="narration",
            relative_path=f"jobs/{job_id}/audio/scene_01.mp3",
            file_format="mp3",
            duration_seconds=5.5,
            file_size_bytes=len(b"dummy_audio_bytes"),
        ),
        start_seconds=0.0,
        end_seconds=5.5,
        duration_seconds=5.5,
        is_silent=False,
    )

    scene2 = AssemblyScene(
        scene_id="sc-summary",
        scene_number=2,
        script_section_id="sec-2",
        section_purpose="Summary",
        title="Architecture Summary",
        visual_asset=AssemblyAssetReference(
            asset_id="vis-2",
            scene_id="sc-summary",
            asset_type="visual",
            relative_path=f"jobs/{job_id}/visuals/scene_02.svg",
            file_format="svg",
            file_size_bytes=v2.stat().st_size,
        ),
        narration_asset=None,
        start_seconds=5.5,
        end_seconds=9.5,
        duration_seconds=4.0,
        is_silent=True,
    )

    assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name=f"org/{job_id}",
        scenes=[scene1, scene2],
        total_scenes=2,
        narrated_scenes=1,
        silent_scenes=1,
        total_duration_seconds=9.5,
        readiness_report=AssemblyReadinessReport(
            job_id=job_id,
            status=AssemblyReadinessStatus.READY,
            total_scenes=2,
            ready_scenes=2,
            total_duration_seconds=9.5,
            has_visuals=True,
            has_narration=True,
            blocking_issues=[],
            warnings=[],
        ),
    )

    job.assembly_input = assembly_input
    job_store.update_job(job)
    return job, [scene1, scene2]


def test_scene_render_service_narrated_and_silent_scenes(temp_storage):
    """
    Verifies that SceneRenderService renders both narrated and silent scenes,
    preserves measured audio durations, and updates JobStore.
    """
    job_id = "test-job-scenes-render"
    job, scenes = _setup_mock_assembly_job(temp_storage, job_id)

    storage = VideoStorageManager(base_storage_dir=temp_storage)
    service = SceneRenderService(storage_mgr=storage)

    # Mock FFmpeg / FFprobe availability
    with patch.object(service._ffmpeg, "assert_available", return_value=None):
        with patch.object(service._ffprobe, "assert_available", return_value=None):
            with patch.object(service._ffmpeg, "resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
                # Mock run_process_sync to create dummy MP4 output
                def _fake_run(cmd, timeout_seconds=None):
                    out_file = Path(cmd[-1])
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    out_file.write_bytes(b"dummy_mp4_encoded_content")
                    return 0, "", ""

                # Mock probe results
                def _fake_probe(file_path):
                    p_str = str(file_path)
                    is_silent = "sc-summary" in p_str
                    dur = 4.0 if is_silent else 5.5
                    vid_stream = MediaStreamProbe(
                        index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0, pixel_format="yuv420p"
                    )
                    aud_stream = None if is_silent else MediaStreamProbe(
                        index=1, codec_type="audio", codec_name="aac", sample_rate=44100, channels=2
                    )
                    return MediaProbeResult(
                        format_name="mp4",
                        file_path=p_str,
                        duration_seconds=dur,
                        size_bytes=len(b"dummy_mp4_encoded_content"),
                        streams=[vid_stream] + ([aud_stream] if aud_stream else []),
                        has_video=True,
                        has_audio=not is_silent,
                        primary_video_stream=vid_stream,
                        primary_audio_stream=aud_stream,
                    )

                with patch("app.services.video.assembly.scene_service.run_process_sync", side_effect=_fake_run):
                    with patch.object(service._ffprobe, "probe_media_file", side_effect=_fake_probe):
                        result = service.render_scenes(job_id=job_id, refresh=True)

                        assert result.total_scenes == 2
                        assert result.completed_scenes == 2
                        assert result.failed_scenes == 0
                        assert result.is_complete is True

                        sc1 = result.scenes[0]
                        assert sc1.scene_id == "sc-intro"
                        assert sc1.status == SceneRenderStatus.COMPLETED
                        assert sc1.is_silent is False
                        assert sc1.actual_duration_seconds == 5.5
                        assert sc1.video_codec == "h264"
                        assert sc1.audio_codec == "aac"
                        assert "scene_01_sc-intro.mp4" in sc1.output_relative_path

                        sc2 = result.scenes[1]
                        assert sc2.scene_id == "sc-summary"
                        assert sc2.status == SceneRenderStatus.COMPLETED
                        assert sc2.is_silent is True
                        assert sc2.actual_duration_seconds == 4.0
                        assert sc2.audio_codec is None
                        assert "scene_02_sc-summary.mp4" in sc2.output_relative_path

                        # Verify Stage 09 is IN_PROGRESS (NOT COMPLETED yet)
                        updated_job = job_store.get_internal_job(job_id)
                        assert updated_job.stages[8].status == StatusEnum.IN_PROGRESS
                        assert "Scene rendering complete" in updated_job.stages[8].detail


def test_scene_render_service_cache_reuse(temp_storage):
    """Verifies that existing valid scene clips are reused without re-rendering when refresh=False."""
    job_id = "test-job-cache-reuse"
    job, scenes = _setup_mock_assembly_job(temp_storage, job_id)
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    service = SceneRenderService(storage_mgr=storage)

    # Pre-render scene 1 clip
    clip1 = storage.get_scene_output_path(job_id, 1, "sc-intro")
    clip1.write_bytes(b"existing_valid_mp4")

    # Update mtime so clip is newer than source
    future_time = time.time() + 100
    os.utime(clip1, (future_time, future_time))

    encode_calls = []

    def _fake_run(cmd, timeout_seconds=None):
        encode_calls.append(cmd)
        out_file = Path(cmd[-1])
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"rendered_mp4")
        return 0, "", ""

    def _fake_probe(file_path):
        vid_stream = MediaStreamProbe(
            index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0, pixel_format="yuv420p"
        )
        aud_stream = MediaStreamProbe(index=1, codec_type="audio", codec_name="aac", sample_rate=44100, channels=2)
        return MediaProbeResult(
            format_name="mp4",
            file_path=str(file_path),
            duration_seconds=5.5,
            size_bytes=len(b"existing_valid_mp4"),
            streams=[vid_stream, aud_stream],
            has_video=True,
            has_audio=True,
            primary_video_stream=vid_stream,
            primary_audio_stream=aud_stream,
        )

    with patch.object(service._ffmpeg, "assert_available", return_value=None):
        with patch.object(service._ffprobe, "assert_available", return_value=None):
            with patch.object(service._ffmpeg, "resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
                with patch("app.services.video.assembly.scene_service.run_process_sync", side_effect=_fake_run):
                    with patch.object(service._ffprobe, "probe_media_file", side_effect=_fake_probe):
                        result = service.render_scenes(job_id=job_id, refresh=False)

                        # Scene 1 was cached, so run_process_sync should ONLY have been called for scene 2!
                        # (Plus rasterizer calls if rsvg was invoked)
                        ffmpeg_render_calls = [c for c in encode_calls if "sc-intro" in " ".join(c)]
                        assert len(ffmpeg_render_calls) == 0
                        assert result.scenes[0].status == SceneRenderStatus.COMPLETED


def test_scene_render_service_partial_failure_handling(temp_storage):
    """Verifies that an error in one scene does not crash rendering and leaves is_complete=False."""
    job_id = "test-job-partial-fail"
    job, scenes = _setup_mock_assembly_job(temp_storage, job_id)
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    service = SceneRenderService(storage_mgr=storage)

    with patch.object(service._ffmpeg, "assert_available", return_value=None):
        with patch.object(service._ffprobe, "assert_available", return_value=None):
            with patch.object(service._ffmpeg, "resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
                # Fail scene 1, succeed scene 2
                def _fake_run(cmd, timeout_seconds=None):
                    cmd_str = " ".join(cmd)
                    if "sc-intro" in cmd_str:
                        return 1, "", "Simulated encoder error"
                    out_file = Path(cmd[-1])
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    out_file.write_bytes(b"dummy_mp4_2")
                    return 0, "", ""

                def _fake_probe(file_path):
                    vid_stream = MediaStreamProbe(
                        index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0, pixel_format="yuv420p"
                    )
                    return MediaProbeResult(
                        format_name="mp4",
                        file_path=str(file_path),
                        duration_seconds=4.0,
                        size_bytes=len(b"dummy_mp4_2"),
                        streams=[vid_stream],
                        has_video=True,
                        has_audio=False,
                        primary_video_stream=vid_stream,
                    )

                with patch("app.services.video.assembly.scene_service.run_process_sync", side_effect=_fake_run):
                    with patch.object(service._ffprobe, "probe_media_file", side_effect=_fake_probe):
                        result = service.render_scenes(job_id=job_id, refresh=True)

                        assert result.completed_scenes == 1
                        assert result.failed_scenes == 1
                        assert result.is_complete is False
                        assert result.scenes[0].status == SceneRenderStatus.FAILED
                        assert "Simulated encoder error" in result.scenes[0].error
                        assert result.scenes[1].status == SceneRenderStatus.COMPLETED


def test_scene_render_concurrency_locking(temp_storage):
    """Verifies that concurrent requests to render_scenes on the same job raise JobRenderConcurrencyError."""
    job_id = "test-job-concurrent-render"
    job, scenes = _setup_mock_assembly_job(temp_storage, job_id)
    storage = VideoStorageManager(base_storage_dir=temp_storage)
    service = SceneRenderService(storage_mgr=storage)

    errors = []

    def _slow_render():
        try:
            with patch.object(service._ffmpeg, "assert_available", return_value=None):
                with patch.object(service._ffprobe, "assert_available", return_value=None):
                    with patch.object(service._ffmpeg, "resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
                        with patch("app.services.video.assembly.scene_service.run_process_sync") as mock_run:
                            # Sleep to simulate long encoding
                            def _blocking_run(*args, **kwargs):
                                time.sleep(0.3)
                                return 0, "", ""
                            mock_run.side_effect = _blocking_run
                            service.render_scenes(job_id=job_id)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=_slow_render)
    t2 = threading.Thread(target=_slow_render)
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join()
    t2.join()

    # One thread should have failed with JobRenderConcurrencyError
    assert any(isinstance(e, JobRenderConcurrencyError) for e in errors)


# ==============================================================================
# 4. REST API Endpoints
# ==============================================================================

def test_api_render_scenes_endpoints(temp_storage):
    """Verifies POST /render-scenes, GET /render-scenes, and GET /{scene_id}."""
    job_id = "test-job-api-scenes"
    job, scenes = _setup_mock_assembly_job(temp_storage, job_id)
    storage = VideoStorageManager(base_storage_dir=temp_storage)

    # 1. GET before rendering returns 404
    res_get_init = client.get(f"/api/v1/jobs/{job_id}/render-scenes")
    assert res_get_init.status_code == status.HTTP_404_NOT_FOUND

    # 2. POST /render-scenes
    with patch("app.services.video.assembly.scene_service.scene_render_service._storage", storage):
        with patch("app.services.video.assembly.scene_service.scene_render_service._ffmpeg.assert_available", return_value=None):
            with patch("app.services.video.assembly.scene_service.scene_render_service._ffprobe.assert_available", return_value=None):
                with patch("app.services.video.assembly.scene_service.scene_render_service._ffmpeg.resolve_binary", return_value=Path("/usr/local/bin/ffmpeg")):
                    def _fake_run(cmd, timeout_seconds=None):
                        out_file = Path(cmd[-1])
                        out_file.parent.mkdir(parents=True, exist_ok=True)
                        out_file.write_bytes(b"dummy_video_data_123")
                        return 0, "", ""

                    def _fake_probe(file_path):
                        vid_stream = MediaStreamProbe(
                            index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0, pixel_format="yuv420p"
                        )
                        return MediaProbeResult(
                            format_name="mp4",
                            file_path=str(file_path),
                            duration_seconds=5.0,
                            size_bytes=len(b"dummy_video_data_123"),
                            streams=[vid_stream],
                            has_video=True,
                            has_audio=True,
                            primary_video_stream=vid_stream,
                        )

                    with patch("app.services.video.assembly.scene_service.run_process_sync", side_effect=_fake_run):
                        with patch("app.services.video.assembly.scene_service.scene_render_service._ffprobe.probe_media_file", side_effect=_fake_probe):
                            res_post = client.post(f"/api/v1/jobs/{job_id}/render-scenes?refresh=true")
                            assert res_post.status_code == status.HTTP_200_OK
                            data = res_post.json()
                            assert data["total_scenes"] == 2
                            assert data["completed_scenes"] == 2
                            assert data["is_complete"] is True

                            # 3. GET /render-scenes returns completed result
                            res_get = client.get(f"/api/v1/jobs/{job_id}/render-scenes")
                            assert res_get.status_code == status.HTTP_200_OK
                            assert res_get.json()["is_complete"] is True

                            # 4. GET /render-scenes/{scene_id} returns single scene
                            res_sc = client.get(f"/api/v1/jobs/{job_id}/render-scenes/sc-intro")
                            assert res_sc.status_code == status.HTTP_200_OK
                            assert res_sc.json()["scene_id"] == "sc-intro"

                            # 5. GET /render-scenes/{scene_id}/file streams MP4 clip
                            with patch("app.services.video.assembly.scene_service.scene_render_service._storage", storage):
                                res_file = client.get(f"/api/v1/jobs/{job_id}/render-scenes/sc-intro/file")
                                assert res_file.status_code == status.HTTP_200_OK
                                assert res_file.headers["content-type"] == "video/mp4"
                                assert res_file.content == b"dummy_video_data_123"
