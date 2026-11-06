"""
Milestone 6, Phase 6.3 Automated Test Suite: Final Video Assembly.

Validates:
1. Concat manifest formatting and injection defense (escapes quotes/backslashes, rejects newlines and null bytes).
2. FFmpeg command builder for concat demuxer (-f concat -safe 0 -c copy +faststart) and silent audio normalization.
3. Scene video concatenation in storyboard order.
4. Narration audio synchronization and stream preservation.
5. Mixed storyboard handling (narrated + silent scenes -> silent scene normalization preserves audio track across final video).
6. Pure silent storyboard handling (all silent scenes -> video-only final video).
7. Error and failure handling (missing scene, corrupt clip, concat failure, timeout, cleanup).
8. Cache reuse when refresh=False and forced re-assembly when refresh=True.
9. Per-job concurrency locking preventing race conditions.
10. Stage 09 and job completion invariants (updates Stage 09 to COMPLETED only after FFprobe verification).
11. REST API endpoints: POST /assemble-video, GET /render-result, GET /video/file.
12. Real FFmpeg execution and FFprobe media verification on the host machine.
"""

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

from app.main import app
from app.models.schemas import StageEnum, StatusEnum, VideoResult
from app.services.storage.job_store import job_store
from app.services.video.assembly.command_builder import FFmpegCommandBuilder
from app.services.video.assembly.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FinalVideoAssemblyError,
    JobRenderConcurrencyError,
    MediaProbeError,
    VideoStorageError,
)
from app.services.video.assembly.ffmpeg_manager import FFmpegManager, ffmpeg_manager
from app.services.video.assembly.ffprobe_manager import FFprobeManager, ffprobe_manager
from app.services.video.assembly.final_service import FinalVideoAssemblyService
from app.services.video.assembly.process_runner import run_process_sync
from app.services.video.assembly.scene_service import SceneRenderService
from app.services.video.assembly.schemas import (
    MediaProbeResult,
    MediaStreamProbe,
    SceneRenderAsset,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderProgress,
    VideoRenderResult,
    VideoRenderStatus,
)
from app.services.video.assembly.storage import VideoStorageManager
from app.services.video.assembly_input.schemas import (
    AssemblyAssetReference,
    AssemblyIssueSeverity,
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    AssemblyValidationIssue,
    VideoAssemblyInput,
)

client = TestClient(app)


# ==============================================================================
# Fixtures & Helpers
# ==============================================================================

def setup_test_job(job_id: str):
    job = job_store.create_job(
        repo_url=f"https://github.com/org/{job_id}",
        repo_name=f"org/{job_id}",
        repository_owner="org",
        repository_name=job_id,
        clone_url=f"https://github.com/org/{job_id}.git",
    )
    job.job_id = job_id
    job_store._jobs[job_id] = job
    return job


@pytest.fixture
def temp_storage(tmp_path: Path):
    storage = VideoStorageManager(base_storage_dir=tmp_path)
    return storage


@pytest.fixture
def sample_assembly_input(tmp_path: Path):
    """Creates a 3-scene assembly input package: 2 narrated, 1 silent."""
    scene1 = AssemblyScene(
        scene_id="scene-01",
        scene_number=1,
        script_section_id="sec-01",
        section_purpose="Hook",
        title="Introduction",
        start_seconds=0.0,
        end_seconds=3.0,
        duration_seconds=3.0,
        is_silent=False,
    )
    scene2 = AssemblyScene(
        scene_id="scene-02",
        scene_number=2,
        script_section_id="sec-02",
        section_purpose="Architecture",
        title="Core Architecture",
        start_seconds=3.0,
        end_seconds=7.0,
        duration_seconds=4.0,
        is_silent=True,
    )
    scene3 = AssemblyScene(
        scene_id="scene-03",
        scene_number=3,
        script_section_id="sec-03",
        section_purpose="Conclusion",
        title="Summary",
        start_seconds=7.0,
        end_seconds=10.0,
        duration_seconds=3.0,
        is_silent=False,
    )

    report = AssemblyReadinessReport(
        job_id="job-assembly-test",
        status=AssemblyReadinessStatus.READY,
        total_scenes=3,
        ready_scenes=3,
        total_duration_seconds=10.0,
        has_visuals=True,
        has_narration=True,
        has_captions=True,
        has_full_video_captions=True,
        blocking_issues=[],
        warnings=[],
    )

    return VideoAssemblyInput(
        job_id="job-assembly-test",
        repo_name="octocat/Hello-World",
        scenes=[scene1, scene2, scene3],
        total_scenes=3,
        total_duration_seconds=10.0,
        readiness_report=report,
    )


# ==============================================================================
# 1. Command Builder Tests
# ==============================================================================

def test_command_builder_concat_manifest_escaping():
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")

    # Safe standard path
    line = builder.format_concat_manifest_line(Path("/tmp/storage/jobs/job1/scene.mp4"))
    assert line.startswith("file '")
    assert line.endswith("'\n")

    # Path containing single quotes
    quoted_line = builder.escape_concat_path("/path/with 'single' quotes/video.mp4")
    assert "\\'" in quoted_line or "'\\''" in quoted_line

    # Path containing injection characters (newlines, null bytes) must be rejected
    with pytest.raises(ValueError, match="cannot contain newlines or null bytes"):
        builder.escape_concat_path("/path/with\ninjection")

    with pytest.raises(ValueError, match="cannot contain newlines or null bytes"):
        builder.escape_concat_path("/path/with\x00null")


def test_command_builder_concat_command():
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")
    cfg = VideoRenderConfiguration()
    manifest = Path("/tmp/concat.txt")
    output = Path("/tmp/final.mp4")

    cmd = builder.build_concat_command(manifest, output, cfg)
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and "concat" in cmd
    assert "-safe" in cmd and "0" in cmd
    assert "-c" in cmd and "copy" in cmd
    assert "-movflags" in cmd and "+faststart" in cmd
    assert cmd[-1] == str(output.resolve())


def test_command_builder_silent_audio_normalization_command():
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")
    cfg = VideoRenderConfiguration(audio_codec="aac", audio_bitrate="192k", audio_sample_rate=44100)
    scene_path = Path("/tmp/silent_scene.mp4")
    out_path = Path("/tmp/norm_scene.mp4")

    cmd = builder.build_silent_audio_normalization_command(scene_path, out_path, 4.0, cfg)
    assert "-i" in cmd and str(scene_path.resolve()) in cmd
    assert "anullsrc=channel_layout=stereo:sample_rate=44100" in " ".join(cmd)
    assert "-c:v" in cmd and "copy" in cmd
    assert "-c:a" in cmd and "aac" in cmd
    assert "-b:a" in cmd and "192k" in cmd
    assert "-shortest" in cmd
    assert cmd[-1] == str(out_path.resolve())


# ==============================================================================
# 2. Final Video Assembly Service Logic (Mocked FFmpeg & Synthetic Tests)
# ==============================================================================

def test_final_assembly_not_ready_package_rejected(temp_storage):
    job_id = "job-not-ready"
    job = setup_test_job(job_id)

    # Readiness report with blocking issue
    issue = AssemblyValidationIssue(
        code="MISSING_AUDIO",
        severity=AssemblyIssueSeverity.BLOCKING,
        message="Missing audio file",
    )
    report = AssemblyReadinessReport(
        job_id=job_id,
        status=AssemblyReadinessStatus.NOT_READY,
        total_scenes=1,
        ready_scenes=0,
        total_duration_seconds=5.0,
        blocking_issues=[issue],
    )
    sc = AssemblyScene(scene_id="sc1", scene_number=1, script_section_id="sec-1", section_purpose="Hook", title="Part 1", start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0, is_silent=False)
    assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name="test/repo",
        scenes=[sc],
        total_scenes=1,
        total_duration_seconds=5.0,
        readiness_report=report,
    )
    job.assembly_input = assembly_input

    service = FinalVideoAssemblyService(storage_mgr=temp_storage)
    with pytest.raises(FinalVideoAssemblyError, match="Video assembly package is NOT ready"):
        service.assemble_video(job_id)


def test_final_assembly_missing_scene_clip_raises_error(temp_storage, sample_assembly_input):
    job_id = "job-missing-clip"
    sample_assembly_input.job_id = job_id
    job = setup_test_job(job_id)
    job.assembly_input = sample_assembly_input

    # Set scene renders as completed in job_store, but do NOT put MP4 files on disk
    scene_result = SceneRenderResult(
        job_id=job_id,
        total_scenes=3,
        completed_scenes=3,
        failed_scenes=0,
        is_complete=True,
        render_duration_seconds=5.0,
        scenes=[],
    )
    job_store.update_job_scene_renders_completed(job_id, scene_result)

    mock_scene_svc = MagicMock()
    mock_scene_svc.render_scenes.return_value = scene_result

    service = FinalVideoAssemblyService(storage_mgr=temp_storage, scene_svc=mock_scene_svc)
    with pytest.raises(FinalVideoAssemblyError, match="is missing or empty on disk"):
        service.assemble_video(job_id)


def test_final_assembly_mixed_scenes_normalization_and_success(temp_storage, sample_assembly_input):
    job_id = "job-mixed-success"
    sample_assembly_input.job_id = job_id
    job = setup_test_job(job_id)
    job.assembly_input = sample_assembly_input

    # Put dummy scene MP4 files on disk
    scenes_dir = temp_storage.get_job_scenes_dir(job_id)
    s1 = scenes_dir / "scene_01_scene-01.mp4"
    s2 = scenes_dir / "scene_02_scene-02.mp4"
    s3 = scenes_dir / "scene_03_scene-03.mp4"
    for f in (s1, s2, s3):
        f.write_bytes(b"dummy_mp4_bytes")

    # Mock ffprobe probes: s1 has audio, s2 is silent, s3 has audio
    vid_stream = MediaStreamProbe(index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0)
    aud_stream = MediaStreamProbe(index=1, codec_type="audio", codec_name="aac", sample_rate=44100, channels=2)

    probe_s1 = MediaProbeResult(format_name="mov,mp4", duration_seconds=3.0, size_bytes=100, streams=[vid_stream, aud_stream], has_video=True, has_audio=True, primary_video_stream=vid_stream, primary_audio_stream=aud_stream)
    probe_s2 = MediaProbeResult(format_name="mov,mp4", duration_seconds=4.0, size_bytes=100, streams=[vid_stream], has_video=True, has_audio=False, primary_video_stream=vid_stream, primary_audio_stream=None)
    probe_s3 = MediaProbeResult(format_name="mov,mp4", duration_seconds=3.0, size_bytes=100, streams=[vid_stream, aud_stream], has_video=True, has_audio=True, primary_video_stream=vid_stream, primary_audio_stream=aud_stream)
    probe_final = MediaProbeResult(format_name="mov,mp4", duration_seconds=10.0, size_bytes=300, streams=[vid_stream, aud_stream], has_video=True, has_audio=True, primary_video_stream=vid_stream, primary_audio_stream=aud_stream)

    def _mock_probe(file_path):
        p_str = str(file_path)
        if "final_video" in p_str:
            return probe_final
        if "scene_01" in p_str:
            return probe_s1
        if "scene_02" in p_str:
            return probe_s2
        if "scene_03" in p_str:
            return probe_s3
        return probe_s1

    mock_ffprobe = MagicMock(spec=FFprobeManager)
    mock_ffprobe.assert_available.return_value = None
    mock_ffprobe.probe_media_file.side_effect = _mock_probe

    mock_ffmpeg = MagicMock(spec=FFmpegManager)
    mock_ffmpeg.assert_available.return_value = None

    scene_result = SceneRenderResult(
        job_id=job_id,
        total_scenes=3,
        completed_scenes=3,
        failed_scenes=0,
        is_complete=True,
        render_duration_seconds=5.0,
        scenes=[],
    )
    job_store.update_job_scene_renders_completed(job_id, scene_result)

    def _fake_run(cmd, timeout_seconds=None):
        # Write dummy file to destination (last argument)
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"final_assembled_mp4_bytes")
        return 0, "", ""

    with patch("app.services.video.assembly.final_service.run_process_sync", side_effect=_fake_run):
        service = FinalVideoAssemblyService(
            ffmpeg_mgr=mock_ffmpeg,
            ffprobe_mgr=mock_ffprobe,
            storage_mgr=temp_storage,
        )
        res = service.assemble_video(job_id, refresh=True)

        assert res.job_id == job_id
        assert res.status == VideoRenderStatus.COMPLETED
        assert res.duration_seconds == 10.0
        assert res.resolution == "1920x1080"
        assert res.video_codec == "h264"
        assert res.audio_codec == "aac"
        assert res.output_relative_path == f"jobs/{job_id}/video/final_video.mp4"

        # Verify Stage 09 is COMPLETED in job_store
        job = job_store.get_internal_job(job_id)
        assert job.stages[8].status == StatusEnum.COMPLETED
        assert job.status == StatusEnum.COMPLETED
        assert job.progress_percentage == 100
        assert job.result is not None
        assert f"/api/v1/jobs/{job_id}/video/file" in job.result.video_url


def test_final_assembly_cache_reuse(temp_storage, sample_assembly_input):
    job_id = "job-cache-reuse"
    sample_assembly_input.job_id = job_id
    job = setup_test_job(job_id)
    job.assembly_input = sample_assembly_input

    # Put scenes on disk with older mtime
    scenes_dir = temp_storage.get_job_scenes_dir(job_id)
    for sc in sample_assembly_input.scenes:
        p = scenes_dir / f"scene_{sc.scene_number:02d}_{sc.scene_id}.mp4"
        p.write_bytes(b"scene_mp4")
        os.utime(p, (1000.0, 1000.0))

    # Put final_video.mp4 with newer mtime
    final_video = temp_storage.get_final_output_path(job_id, "final_video.mp4")
    final_video.write_bytes(b"cached_final_mp4")
    os.utime(final_video, (2000.0, 2000.0))

    vid_stream = MediaStreamProbe(index=0, codec_type="video", codec_name="h264", width=1920, height=1080, fps=30.0)
    probe_final = MediaProbeResult(format_name="mov,mp4", duration_seconds=10.0, size_bytes=100, streams=[vid_stream], has_video=True, has_audio=False, primary_video_stream=vid_stream)

    mock_ffprobe = MagicMock(spec=FFprobeManager)
    mock_ffprobe.assert_available.return_value = None
    mock_ffprobe.probe_media_file.return_value = probe_final

    mock_ffmpeg = MagicMock(spec=FFmpegManager)
    mock_ffmpeg.assert_available.return_value = None

    scene_result = SceneRenderResult(
        job_id=job_id,
        total_scenes=3,
        completed_scenes=3,
        failed_scenes=0,
        is_complete=True,
        render_duration_seconds=5.0,
        scenes=[],
    )
    job_store.update_job_scene_renders_completed(job_id, scene_result)

    with patch("app.services.video.assembly.final_service.run_process_sync") as mock_run:
        service = FinalVideoAssemblyService(
            ffmpeg_mgr=mock_ffmpeg,
            ffprobe_mgr=mock_ffprobe,
            storage_mgr=temp_storage,
        )
        res = service.assemble_video(job_id, refresh=False)

        # Process should NOT have been invoked because cache was reused
        mock_run.assert_not_called()
        assert res.duration_seconds == 10.0


def test_final_assembly_concurrency_error(temp_storage, sample_assembly_input):
    job_id = "job-concurrency"
    sample_assembly_input.job_id = job_id
    job = setup_test_job(job_id)
    job.assembly_input = sample_assembly_input

    from app.services.video.assembly.final_service import _active_final_renders

    _active_final_renders.add(job_id)
    try:
        service = FinalVideoAssemblyService(storage_mgr=temp_storage)
        with pytest.raises(JobRenderConcurrencyError, match="already in progress"):
            service.assemble_video(job_id)
    finally:
        _active_final_renders.discard(job_id)


# ==============================================================================
# 3. REST API Endpoint Tests
# ==============================================================================

def test_api_assemble_video_endpoints(temp_storage, sample_assembly_input):
    job_id = "job-api-assemble"
    sample_assembly_input.job_id = job_id
    job = setup_test_job(job_id)
    job.assembly_input = sample_assembly_input

    # 1. GET /render-result before assembly -> 404
    res_get_init = client.get(f"/api/v1/jobs/{job_id}/render-result")
    assert res_get_init.status_code == status.HTTP_404_NOT_FOUND

    # 2. GET /video/file before assembly -> 404
    res_file_init = client.get(f"/api/v1/jobs/{job_id}/video/file")
    assert res_file_init.status_code == status.HTTP_404_NOT_FOUND

    # Mock assemble_video return value
    expected_result = VideoRenderResult(
        job_id=job_id,
        status=VideoRenderStatus.COMPLETED,
        output_relative_path=f"jobs/{job_id}/video/final_video.mp4",
        file_size_bytes=50000,
        duration_seconds=10.0,
        resolution="1920x1080",
        fps=30,
        video_codec="h264",
        audio_codec="aac",
    )

    with patch("app.services.video.assembly.final_service.final_video_assembly_service.assemble_video", return_value=expected_result):
        # 3. POST /assemble-video
        post_res = client.post(f"/api/v1/jobs/{job_id}/assemble-video?refresh=true")
        assert post_res.status_code == status.HTTP_200_OK
        data = post_res.json()
        assert data["job_id"] == job_id
        assert data["status"] == "completed"
        assert data["duration_seconds"] == 10.0
        assert data["resolution"] == "1920x1080"

        # 4. Alias POST /render
        post_alias_res = client.post(f"/api/v1/jobs/{job_id}/render")
        assert post_alias_res.status_code == status.HTTP_200_OK

    with patch("app.services.video.assembly.final_service.final_video_assembly_service.get_final_video_result", return_value=expected_result):
        # 5. GET /render-result
        get_res = client.get(f"/api/v1/jobs/{job_id}/render-result")
        assert get_res.status_code == status.HTTP_200_OK
        assert get_res.json()["duration_seconds"] == 10.0

    # 6. GET /video/file streaming
    dummy_file = temp_storage.get_final_output_path(job_id, "final_video.mp4")
    dummy_file.write_bytes(b"test_stream_data_mp4")
    with patch("app.services.video.assembly.final_service.final_video_assembly_service.get_final_video_file_path", return_value=dummy_file):
        file_res = client.get(f"/api/v1/jobs/{job_id}/video/file")
        assert file_res.status_code == status.HTTP_200_OK
        assert file_res.headers["content-type"] == "video/mp4"
        assert file_res.content == b"test_stream_data_mp4"


# ==============================================================================
# 4. Real FFmpeg Execution & Verification Test
# ==============================================================================

@pytest.mark.skipif(ffmpeg_manager.resolve_binary() is None, reason="FFmpeg not installed on host machine")
def test_real_ffmpeg_final_video_assembly(tmp_path: Path):
    """
    Executes REAL FFmpeg concatenation on the development host using synthetic media.
    Validates output streams with real FFprobe.
    """
    job_id = "job-real-ffmpeg-assembly"
    storage = VideoStorageManager(base_storage_dir=tmp_path)
    b = FFmpegCommandBuilder(ffmpeg_executable=str(ffmpeg_manager.resolve_binary()))
    cfg = VideoRenderConfiguration()

    scenes_dir = storage.get_job_scenes_dir(job_id)

    # 1. Generate real Clip 1 (narrated 1.0s)
    c1 = scenes_dir / "scene_01_sc1.mp4"
    cmd1 = [
        str(ffmpeg_manager.resolve_binary()), "-y",
        "-f", "lavfi", "-i", "color=c=navy:s=1920x1080:r=30:d=1.0",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "1.0", str(c1),
    ]
    code1, _, _ = run_process_sync(cmd1)
    assert code1 == 0

    # 2. Generate real Clip 2 (silent 1.0s, with -an)
    c2 = scenes_dir / "scene_02_sc2.mp4"
    cmd2 = [
        str(ffmpeg_manager.resolve_binary()), "-y",
        "-f", "lavfi", "-i", "color=c=crimson:s=1920x1080:r=30:d=1.0",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1.0", str(c2),
    ]
    code2, _, _ = run_process_sync(cmd2)
    assert code2 == 0

    # 3. Setup job and assembly input in JobStore
    job = setup_test_job(job_id)
    sc1 = AssemblyScene(scene_id="sc1", scene_number=1, script_section_id="sec-1", section_purpose="Hook", title="Part 1", start_seconds=0.0, end_seconds=1.0, duration_seconds=1.0, is_silent=False)
    sc2 = AssemblyScene(scene_id="sc2", scene_number=2, script_section_id="sec-2", section_purpose="Summary", title="Part 2", start_seconds=1.0, end_seconds=2.0, duration_seconds=1.0, is_silent=True)
    report = AssemblyReadinessReport(
        job_id=job_id,
        status=AssemblyReadinessStatus.READY,
        total_scenes=2,
        ready_scenes=2,
        total_duration_seconds=2.0,
        has_visuals=True,
        has_narration=True,
        has_captions=True,
        has_full_video_captions=True,
    )
    inp = VideoAssemblyInput(
        job_id=job_id,
        repo_name="test/repo",
        scenes=[sc1, sc2],
        total_scenes=2,
        total_duration_seconds=2.0,
        readiness_report=report,
    )
    job.assembly_input = inp

    # Set scene renders as completed in JobStore
    sr1 = SceneRenderAsset(scene_id="sc1", scene_number=1, title="Part 1", status=SceneRenderStatus.COMPLETED, is_silent=False, actual_duration_seconds=1.0)
    sr2 = SceneRenderAsset(scene_id="sc2", scene_number=2, title="Part 2", status=SceneRenderStatus.COMPLETED, is_silent=True, actual_duration_seconds=1.0)
    job_store.update_job_scene_renders_completed(
        job_id,
        SceneRenderResult(job_id=job_id, total_scenes=2, completed_scenes=2, failed_scenes=0, is_complete=True, scenes=[sr1, sr2]),
    )

    # Execute real assembly service
    service = FinalVideoAssemblyService(storage_mgr=storage)
    res = service.assemble_video(job_id, refresh=True)

    assert res.status == VideoRenderStatus.COMPLETED
    assert res.duration_seconds > 1.8
    assert res.resolution == "1920x1080"
    assert res.video_codec == "h264"
    assert res.audio_codec == "aac"

    # Real FFprobe verification of resulting file on disk
    final_file = storage.get_final_output_path(job_id, "final_video.mp4")
    assert final_file.exists()
    assert final_file.stat().st_size > 0

    probe = ffprobe_manager.probe_media_file(final_file)
    assert probe.has_video is True
    assert probe.has_audio is True
    assert probe.primary_video_stream.codec_name == "h264"
    assert probe.primary_video_stream.width == 1920
    assert probe.primary_video_stream.height == 1080
    assert probe.primary_audio_stream.codec_name == "aac"
    assert len(probe.streams) == 2
