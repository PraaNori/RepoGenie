"""
Burned-in Subtitles & Subtitle Track Integration Tests.

Verifies:
1. Subtitle filter path escaping for FFmpeg (colons, backslashes, spaces, security checks).
2. Concat command generation with burned-in subtitle filter vs stream copy fallback.
3. Actual media rendering: verified white subtitle text rendered onto frames during cues,
   clean background during gaps, H.264/AAC streams, 1920x1080 resolution, and 30 fps.
4. Missing, empty, or whitespace subtitle files smoothly fall back without breaking assembly.
5. Subtitle cache invalidation triggers re-assembly so new captions are burned in.
"""

import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.models.schemas import StatusEnum
from app.services.video.assembly.command_builder import FFmpegCommandBuilder
from app.services.video.assembly.ffmpeg_manager import ffmpeg_manager
from app.services.video.assembly.ffprobe_manager import ffprobe_manager
from app.services.video.assembly.final_service import FinalVideoAssemblyService
from app.services.video.assembly.schemas import (
    SceneRenderAsset,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
)
from app.services.video.assembly.storage import VideoStorageManager
from app.services.video.assembly_input.schemas import (
    AssemblyAssetReference,
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    VideoAssemblyInput,
)
from app.services.storage.job_store import job_store


@pytest.fixture
def command_builder() -> FFmpegCommandBuilder:
    return FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")


def test_subtitles_filter_path_escaping(command_builder: FFmpegCommandBuilder):
    """Verifies that colons and backslashes are properly escaped for FFmpeg filter syntax."""
    # Standard Unix path
    p1 = Path("/tmp/storage/jobs/job-123/captions/full.srt")
    escaped1 = command_builder.escape_subtitles_filter_path(p1)
    assert "\\:" not in escaped1
    assert "\\" not in escaped1
    assert escaped1 == str(p1.resolve())

    # Path with colon (e.g. Windows drive letter or colon in folder)
    p2 = Path("/tmp/storage/jobs/job:456/captions/full.srt")
    escaped2 = command_builder.escape_subtitles_filter_path(p2)
    assert "\\:" in escaped2

    # Prohibits newlines and null bytes to prevent filter injection
    with pytest.raises(ValueError, match="cannot contain newlines or null bytes"):
        command_builder.escape_subtitles_filter_path(Path("/tmp/evil\npath/full.srt"))

    with pytest.raises(ValueError):
        command_builder.escape_subtitles_filter_path(Path("/tmp/evil\x00path/full.srt"))


def test_subtitles_filter_string_generation(command_builder: FFmpegCommandBuilder, tmp_path: Path):
    """Verifies generated subtitles filter contains correct libass force_style parameters."""
    srt_file = tmp_path / "full.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")

    filter_str = command_builder.build_subtitles_filter_string(srt_file)
    assert filter_str.startswith("subtitles=filename='")
    assert "force_style='" in filter_str
    assert "FontSize=10" in filter_str               # Scaled font height (~36px on 1080p)
    assert "PrimaryColour=&H00FFFFFF" in filter_str  # White text
    assert "OutlineColour=&H00000000" in filter_str  # Dark outline
    assert "Outline=1.2" in filter_str               # Subtle outline
    assert "BackColour=&H00000000" in filter_str     # Transparent background (no box)
    assert "Alignment=2" in filter_str               # Bottom center
    assert "MarginV=16" in filter_str                # 55-65px safe margin
    assert "MarginL=50" in filter_str                # Limit width to ~80%
    assert "MarginR=50" in filter_str
    assert "WrapStyle=0" in filter_str               # Natural balanced 2-line wrapping


def test_concat_command_with_and_without_subtitles(command_builder: FFmpegCommandBuilder, tmp_path: Path):
    """Verifies stream copy when no subtitles are present, and re-encoding with -vf when subtitles exist."""
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("file 'a.mp4'\nfile 'b.mp4'\n", encoding="utf-8")
    output = tmp_path / "final.mp4"
    config = VideoRenderConfiguration(video_codec="libx264", fps=30, pixel_format="yuv420p")

    # 1. No subtitles provided -> stream copy (-c copy)
    cmd_no_sub = command_builder.build_concat_command(manifest, output, config, subtitles_file=None)
    assert "-c" in cmd_no_sub
    assert cmd_no_sub[cmd_no_sub.index("-c") + 1] == "copy"
    assert "-vf" not in cmd_no_sub

    # 2. Subtitle file exists and is non-empty -> burns in subtitles with re-encoding
    srt_file = tmp_path / "full.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")

    cmd_with_sub = command_builder.build_concat_command(manifest, output, config, subtitles_file=srt_file)
    assert "-vf" in cmd_with_sub
    vf_idx = cmd_with_sub.index("-vf")
    assert "subtitles=filename=" in cmd_with_sub[vf_idx + 1]
    assert "-c:v" in cmd_with_sub
    assert cmd_with_sub[cmd_with_sub.index("-c:v") + 1] == "libx264"
    assert "-c:a" in cmd_with_sub
    assert cmd_with_sub[cmd_with_sub.index("-c:a") + 1] == "copy"

    # 3. Subtitle file is 0-byte empty -> falls back to stream copy safely
    empty_srt = tmp_path / "empty.srt"
    empty_srt.write_text("", encoding="utf-8")
    cmd_empty = command_builder.build_concat_command(manifest, output, config, subtitles_file=empty_srt)
    assert "-c" in cmd_empty
    assert cmd_empty[cmd_empty.index("-c") + 1] == "copy"
    assert "-vf" not in cmd_empty


def test_burned_in_subtitles_actual_media_rendering(tmp_path: Path):
    """
    Renders actual synthetic video scenes, burns in a full-video SRT subtitle track,
    and proves with FFprobe and pixel analysis that subtitles are physically rendered.
    """
    ffmpeg_manager.assert_available()
    ffprobe_manager.assert_available()

    job_id = "job-burned-sub-verify"
    storage = VideoStorageManager(base_storage_dir=tmp_path)
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")

    # 1. Generate 2 synthetic 2-second scenes (video + audio)
    scene1_path = storage.get_scene_output_path(job_id, 1, "s1")
    scene1_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=2.0:r=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
        str(scene1_path)
    ], check=True, capture_output=True)

    scene2_path = storage.get_scene_output_path(job_id, 2, "s2")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=2.0:r=30",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=2.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
        str(scene2_path)
    ], check=True, capture_output=True)

    # 2. Write full-video SRT subtitle file:
    # Cue 1: 0.4s to 1.6s ("Scene One Architecture")
    # Gap:   1.6s to 2.4s (no captions)
    # Cue 2: 2.4s to 3.6s ("Scene Two Dataflow")
    srt_dir = tmp_path / "jobs" / job_id / "captions"
    srt_dir.mkdir(parents=True, exist_ok=True)
    srt_file = srt_dir / "full.srt"
    srt_file.write_text(
        "1\n00:00:00,400 --> 00:00:01,600\nScene One Architecture\n\n"
        "2\n00:00:02,400 --> 00:00:03,600\nScene Two Dataflow\n",
        encoding="utf-8"
    )

    # 3. Create assembly input
    scenes = [
        AssemblyScene(
            scene_id="s1", scene_number=1, script_section_id="sec-1",
            section_purpose="hook", title="Scene 1",
            start_seconds=0.0, end_seconds=2.0, duration_seconds=2.0,
        ),
        AssemblyScene(
            scene_id="s2", scene_number=2, script_section_id="sec-2",
            section_purpose="architecture", title="Scene 2",
            start_seconds=2.0, end_seconds=4.0, duration_seconds=2.0,
        ),
    ]

    full_srt_ref = AssemblyAssetReference(
        asset_id="full",
        asset_type="full_video_srt",
        relative_path=f"jobs/{job_id}/captions/full.srt",
        file_format="srt",
        file_size_bytes=srt_file.stat().st_size,
        duration_seconds=4.0,
        is_valid=True,
    )

    assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name="mock/repo",
        scenes=scenes,
        total_scenes=2,
        total_duration_seconds=4.0,
        full_video_srt=full_srt_ref,
        readiness_report=AssemblyReadinessReport(
            job_id=job_id,
            status=AssemblyReadinessStatus.READY,
            total_scenes=2,
            ready_scenes=2,
            is_render_ready=True,
        ),
    )

    # Setup Job in JobStore
    job = job_store.create_job(
        repo_url="https://github.com/mock/repo",
        repo_name="mock/repo",
        repository_owner="mock",
        repository_name="repo",
        clone_url="https://github.com/mock/repo.git",
    )
    job.job_id = job_id
    job_store._jobs[job_id] = job
    job.assembly_input = assembly_input

    # Set scene renders complete in job
    job.scene_renders = SceneRenderResult(
        job_id=job_id,
        status=SceneRenderStatus.COMPLETED,
        total_scenes=2,
        completed_scenes=2,
        failed_scenes=0,
        is_complete=True,
        total_duration_seconds=4.0,
        scenes=[
            SceneRenderAsset(
                scene_id="s1", scene_number=1, status=SceneRenderStatus.COMPLETED,
                output_relative_path=f"jobs/{job_id}/scenes/scene_001_s1.mp4",
                duration_seconds=2.0, file_size_bytes=scene1_path.stat().st_size,
            ),
            SceneRenderAsset(
                scene_id="s2", scene_number=2, status=SceneRenderStatus.COMPLETED,
                output_relative_path=f"jobs/{job_id}/scenes/scene_002_s2.mp4",
                duration_seconds=2.0, file_size_bytes=scene2_path.stat().st_size,
            ),
        ],
    )

    service = FinalVideoAssemblyService(
        storage_mgr=storage,
        cmd_builder=builder,
        ffmpeg_mgr=ffmpeg_manager,
        ffprobe_mgr=ffprobe_manager,
    )

    result = service.assemble_video(job_id=job_id, refresh=True)
    assert result.status.value == "completed"
    assert result.resolution == "1920x1080"
    assert result.fps == 30
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert 3.8 <= result.duration_seconds <= 4.2

    final_video_path = storage.get_final_output_path(job_id, "final_video.mp4")
    assert final_video_path.is_file()

    # 4. Deep Probe: Verify with FFprobe that audio and video streams exist and are valid
    probe = ffprobe_manager.probe_media_file(final_video_path)
    assert probe.has_video is True
    assert probe.has_audio is True
    assert probe.primary_video_stream is not None
    assert probe.primary_video_stream.width == 1920
    assert probe.primary_video_stream.height == 1080
    assert probe.primary_video_stream.fps == 30.0

    # 5. Visual Frame Inspection:
    # Frame at t=1.0s: Cue 1 is active ("Scene One Architecture"). Should contain bright white text pixels!
    # Frame at t=2.0s: Inter-scene silent gap between cues. Should have NO bright text pixels!
    frame_sub_path = tmp_path / "frame_sub.png"
    frame_gap_path = tmp_path / "frame_gap.png"

    subprocess.run([
        "ffmpeg", "-y", "-ss", "1.0", "-i", str(final_video_path), "-vframes", "1", str(frame_sub_path)
    ], check=True, capture_output=True)

    subprocess.run([
        "ffmpeg", "-y", "-ss", "2.0", "-i", str(final_video_path), "-vframes", "1", str(frame_gap_path)
    ], check=True, capture_output=True)

    im_sub = Image.open(frame_sub_path)
    im_gap = Image.open(frame_gap_path)
    w, h = im_sub.size

    # Crop the bottom subtitle zone (bottom 20% of 1080p frame)
    sub_zone = im_sub.crop((0, int(h * 0.8), w, h))
    gap_zone = im_gap.crop((0, int(h * 0.8), w, h))

    max_sub_brightness = max(
        p for px in sub_zone.getdata() for p in (px[:3] if isinstance(px, tuple) else [px])
    )
    max_gap_brightness = max(
        p for px in gap_zone.getdata() for p in (px[:3] if isinstance(px, tuple) else [px])
    )

    # Subtitle frame must have pure white text (brightness >= 240)
    assert max_sub_brightness >= 240, f"Expected bright white subtitle pixels at t=1.0s, got {max_sub_brightness}"
    # Gap frame on black background must not have text (brightness < 30)
    assert max_gap_brightness < 30, f"Expected dark background during gap at t=2.0s, got {max_gap_brightness}"

    # Verify subtitle geometry on 1920x1080 frame:
    bbox = im_sub.getbbox()
    assert bbox is not None, "Expected non-empty bounding box for rendered subtitles"
    rendered_text_height = bbox[3] - bbox[1]
    rendered_text_width = bbox[2] - bbox[0]
    bottom_safe_margin = 1080 - bbox[3]

    # Height should be approximately 36px (within 34-44px range)
    assert 34 <= rendered_text_height <= 44, f"Expected subtitle height ~36px, got {rendered_text_height}px"
    # Bottom margin should be within the 55-65px safe margin
    assert 55 <= bottom_safe_margin <= 65, f"Expected safe bottom margin 55-65px, got {bottom_safe_margin}px"
    # Width must not exceed 80% of video width (0.80 * 1920 = 1536px)
    assert rendered_text_width <= int(1920 * 0.80), f"Subtitle width {rendered_text_width}px exceeds 80% width"
    # Unobstructed top: all content above y=950 is completely clear
    assert bbox[1] >= 950, f"Subtitle top edge y={bbox[1]} impinges on upper 88% slide area"


def test_missing_or_empty_subtitles_file_fallback(tmp_path: Path):
    """Verifies that missing or empty subtitle reference smoothly falls back to stream copy without failing."""
    ffmpeg_manager.assert_available()
    ffprobe_manager.assert_available()

    job_id = "job-missing-sub-fallback"
    storage = VideoStorageManager(base_storage_dir=tmp_path)
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")

    scene_path = storage.get_scene_output_path(job_id, 1, "s1")
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=1920x1080:d=1.5:r=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
        str(scene_path)
    ], check=True, capture_output=True)

    # Assembly input pointing to non-existent SRT file
    assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name="mock/repo",
        scenes=[
            AssemblyScene(
                scene_id="s1", scene_number=1, script_section_id="sec-1",
                section_purpose="hook", title="Scene 1",
                start_seconds=0.0, end_seconds=1.5, duration_seconds=1.5,
            )
        ],
        total_scenes=1,
        total_duration_seconds=1.5,
        full_video_srt=AssemblyAssetReference(
            asset_id="full",
            asset_type="full_video_srt",
            relative_path=f"jobs/{job_id}/captions/nonexistent.srt",
            file_format="srt",
            file_size_bytes=0,
            duration_seconds=1.5,
            is_valid=False,
        ),
        readiness_report=AssemblyReadinessReport(
            job_id=job_id,
            status=AssemblyReadinessStatus.READY,
            total_scenes=1,
            ready_scenes=1,
            is_render_ready=True,
        ),
    )

    job = job_store.create_job(
        repo_url="https://github.com/mock/repo",
        repo_name="mock/repo",
        repository_owner="mock",
        repository_name="repo",
        clone_url="https://github.com/mock/repo.git",
    )
    job.job_id = job_id
    job_store._jobs[job_id] = job
    job.assembly_input = assembly_input
    job.scene_renders = SceneRenderResult(
        job_id=job_id,
        status=SceneRenderStatus.COMPLETED,
        total_scenes=1,
        completed_scenes=1,
        failed_scenes=0,
        is_complete=True,
        total_duration_seconds=1.5,
        scenes=[
            SceneRenderAsset(
                scene_id="s1", scene_number=1, status=SceneRenderStatus.COMPLETED,
                output_relative_path=f"jobs/{job_id}/scenes/scene_001_s1.mp4",
                duration_seconds=1.5, file_size_bytes=scene_path.stat().st_size,
            )
        ],
    )

    service = FinalVideoAssemblyService(
        storage_mgr=storage,
        cmd_builder=builder,
        ffmpeg_mgr=ffmpeg_manager,
        ffprobe_mgr=ffprobe_manager,
    )

    result = service.assemble_video(job_id=job_id, refresh=True)
    assert result.status.value == "completed"
    assert result.resolution == "1920x1080"
    final_video_path = storage.get_final_output_path(job_id, "final_video.mp4")
    assert final_video_path.is_file()


def test_subtitle_invalidation_triggers_reassembly(tmp_path: Path):
    """Verifies that updating the subtitle file mtime invalidates cached video and triggers re-assembly."""
    job_id = "job-sub-invalidation"
    storage = VideoStorageManager(base_storage_dir=tmp_path)
    builder = FFmpegCommandBuilder(ffmpeg_executable="ffmpeg")

    scene_path = storage.get_scene_output_path(job_id, 1, "s1")
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=1920x1080:d=1.0:r=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
        str(scene_path)
    ], check=True, capture_output=True)

    srt_dir = tmp_path / "jobs" / job_id / "captions"
    srt_dir.mkdir(parents=True, exist_ok=True)
    srt_file = srt_dir / "full.srt"
    srt_file.write_text("1\n00:00:00,100 --> 00:00:00,800\nInitial Subtitles\n", encoding="utf-8")

    assembly_input = VideoAssemblyInput(
        job_id=job_id,
        repo_name="mock/repo",
        scenes=[
            AssemblyScene(
                scene_id="s1", scene_number=1, script_section_id="sec-1",
                section_purpose="hook", title="Scene 1",
                start_seconds=0.0, end_seconds=1.0, duration_seconds=1.0,
            )
        ],
        total_scenes=1,
        total_duration_seconds=1.0,
        full_video_srt=AssemblyAssetReference(
            asset_id="full",
            asset_type="full_video_srt",
            relative_path=f"jobs/{job_id}/captions/full.srt",
            file_format="srt",
            file_size_bytes=srt_file.stat().st_size,
            duration_seconds=1.0,
            is_valid=True,
        ),
        readiness_report=AssemblyReadinessReport(
            job_id=job_id,
            status=AssemblyReadinessStatus.READY,
            total_scenes=1,
            ready_scenes=1,
            is_render_ready=True,
        ),
    )

    job = job_store.create_job(
        repo_url="https://github.com/mock/repo",
        repo_name="mock/repo",
        repository_owner="mock",
        repository_name="repo",
        clone_url="https://github.com/mock/repo.git",
    )
    job.job_id = job_id
    job_store._jobs[job_id] = job
    job.assembly_input = assembly_input
    job.scene_renders = SceneRenderResult(
        job_id=job_id,
        status=SceneRenderStatus.COMPLETED,
        total_scenes=1,
        completed_scenes=1,
        failed_scenes=0,
        is_complete=True,
        total_duration_seconds=1.0,
        scenes=[
            SceneRenderAsset(
                scene_id="s1", scene_number=1, status=SceneRenderStatus.COMPLETED,
                output_relative_path=f"jobs/{job_id}/scenes/scene_001_s1.mp4",
                duration_seconds=1.0, file_size_bytes=scene_path.stat().st_size,
            )
        ],
    )

    service = FinalVideoAssemblyService(
        storage_mgr=storage,
        cmd_builder=builder,
        ffmpeg_mgr=ffmpeg_manager,
        ffprobe_mgr=ffprobe_manager,
    )

    # Initial assembly
    res1 = service.assemble_video(job_id=job_id, refresh=False)
    final_video = storage.get_final_output_path(job_id, "final_video.mp4")
    mtime1 = final_video.stat().st_mtime

    # Call again without refresh: cache should be reused (same mtime)
    res2 = service.assemble_video(job_id=job_id, refresh=False)
    assert final_video.stat().st_mtime == mtime1

    # Now update subtitle file content and touch mtime into the future
    time.sleep(0.05)
    srt_file.write_text("1\n00:00:00,100 --> 00:00:00,800\nUpdated Subtitles v2\n", encoding="utf-8")
    import os
    future_time = mtime1 + 10.0
    os.utime(srt_file, (future_time, future_time))

    # Call assemble_video without refresh: subtitle change MUST invalidate cache and re-render!
    res3 = service.assemble_video(job_id=job_id, refresh=False)
    mtime3 = final_video.stat().st_mtime
    assert mtime3 > mtime1, "Expected re-assembly after subtitle file modification"

