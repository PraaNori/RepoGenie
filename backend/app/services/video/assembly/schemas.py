"""
Pydantic Schemas for Milestone 6, Phase 6.1: FFmpeg Video Assembly Foundation.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")
SUPPORTED_VIDEO_CODECS = {"libx264", "h264", "libx265", "hevc", "copy"}
SUPPORTED_AUDIO_CODECS = {"aac", "libmp3lame", "mp3", "opus", "copy"}
SUPPORTED_PIXEL_FORMATS = {"yuv420p", "yuv444p", "rgb24", "rgba"}
SUPPORTED_CONTAINERS = {"mp4", "mkv", "mov", "webm"}


class VideoRenderStatus(str, Enum):
    """Lifecycle status of a video rendering job."""
    PENDING = "pending"
    CONFIGURED = "configured"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VideoRenderConfiguration(BaseModel):
    """Validated rendering parameters for video assembly."""
    resolution_width: int = Field(default=1920, ge=320, le=7680, description="Video width in pixels (even integer)")
    resolution_height: int = Field(default=1080, ge=180, le=4320, description="Video height in pixels (even integer)")
    aspect_ratio: str = Field(default="16:9", description="Standard target aspect ratio")
    fps: int = Field(default=30, ge=1, le=120, description="Frame rate per second")

    video_codec: str = Field(default="libx264", description="FFmpeg video encoder codec name")
    pixel_format: str = Field(default="yuv420p", description="Pixel format for universal web playback compatibility")
    crf: Optional[int] = Field(default=23, ge=0, le=51, description="Constant Rate Factor for x264/x265 quality")
    preset: str = Field(default="medium", description="FFmpeg x264 preset (ultrafast, superfast, veryfast, faster, fast, medium, slow)")
    video_bitrate: Optional[str] = Field(default=None, description="Optional target video bitrate (e.g. 4000k)")

    audio_codec: str = Field(default="aac", description="FFmpeg audio encoder codec name")
    audio_sample_rate: int = Field(default=44100, ge=8000, le=192000, description="Audio sample rate in Hz")
    audio_channels: int = Field(default=2, ge=1, le=8, description="Number of audio channels (1=mono, 2=stereo)")
    audio_bitrate: str = Field(default="192k", description="Audio bitrate")

    faststart: bool = Field(default=True, description="Enable movflags +faststart for progressive web playback")
    container_format: str = Field(default="mp4", description="Output container format")

    @field_validator("video_codec")
    @classmethod
    def _validate_video_codec(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_VIDEO_CODECS:
            raise ValueError(f"Unsupported video codec '{v}'. Allowed: {sorted(SUPPORTED_VIDEO_CODECS)}")
        return clean

    @field_validator("audio_codec")
    @classmethod
    def _validate_audio_codec(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_AUDIO_CODECS:
            raise ValueError(f"Unsupported audio codec '{v}'. Allowed: {sorted(SUPPORTED_AUDIO_CODECS)}")
        return clean

    @field_validator("pixel_format")
    @classmethod
    def _validate_pix_fmt(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_PIXEL_FORMATS:
            raise ValueError(f"Unsupported pixel format '{v}'. Allowed: {sorted(SUPPORTED_PIXEL_FORMATS)}")
        return clean

    @field_validator("container_format")
    @classmethod
    def _validate_container(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_CONTAINERS:
            raise ValueError(f"Unsupported container format '{v}'. Allowed: {sorted(SUPPORTED_CONTAINERS)}")
        return clean

    @model_validator(mode="after")
    def _validate_dimensions_and_aspect(self) -> VideoRenderConfiguration:
        # libx264 and yuv420p require even dimensions
        if self.resolution_width % 2 != 0:
            raise ValueError(f"Width {self.resolution_width} must be an even number for {self.pixel_format} encoding.")
        if self.resolution_height % 2 != 0:
            raise ValueError(f"Height {self.resolution_height} must be an even number for {self.pixel_format} encoding.")

        # Check 16:9 aspect ratio conformance if aspect_ratio is 16:9
        if self.aspect_ratio == "16:9":
            ratio = self.resolution_width / self.resolution_height
            if not math.isclose(ratio, 16.0 / 9.0, rel_tol=0.05):
                raise ValueError(
                    f"Resolution {self.resolution_width}x{self.resolution_height} (ratio {ratio:.2f}) does not match 16:9 aspect ratio."
                )
        return self


class VideoRenderProgress(BaseModel):
    """Detailed progress tracking for an in-flight video render operation."""
    job_id: str
    status: VideoRenderStatus = VideoRenderStatus.PENDING
    progress_percentage: int = Field(default=0, ge=0, le=100)
    current_scene: int = 0
    total_scenes: int = 0
    current_frame: int = 0
    total_frames: Optional[int] = None
    fps: Optional[float] = None
    speed: Optional[float] = None
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: Optional[float] = None
    stage_detail: str = "Ready"


class VideoRenderJob(BaseModel):
    """Represents the rendering task and execution state for a repository job."""
    job_id: str
    status: VideoRenderStatus = VideoRenderStatus.CONFIGURED
    configuration: VideoRenderConfiguration = Field(default_factory=VideoRenderConfiguration)
    expected_duration_seconds: float = 0.0
    actual_duration_seconds: Optional[float] = None
    output_relative_path: Optional[str] = None
    output_file_size_bytes: int = 0
    progress: VideoRenderProgress
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @field_validator("job_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Identifier '{v}' contains invalid characters.")
        return v


class VideoRenderResult(BaseModel):
    """Finalized render output metadata and metrics."""
    job_id: str
    status: VideoRenderStatus = VideoRenderStatus.COMPLETED
    output_relative_path: str
    file_size_bytes: int = Field(ge=0)
    duration_seconds: float = Field(ge=0.0)
    resolution: str
    fps: int
    video_codec: str
    audio_codec: str
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MediaStreamProbe(BaseModel):
    """Structured inspection of a single video, audio, or subtitle stream."""
    index: int
    codec_type: str = Field(description="Stream type: video, audio, subtitle, etc.")
    codec_name: str = Field(description="Underlying codec, e.g. h264, aac, subrip")
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    pixel_format: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    channel_layout: Optional[str] = None
    duration_seconds: Optional[float] = None
    bit_rate: Optional[int] = None


class MediaProbeResult(BaseModel):
    """Structured inspection of a media container and its streams."""
    format_name: str
    duration_seconds: float = 0.0
    size_bytes: int = 0
    bit_rate: Optional[int] = None
    streams: List[MediaStreamProbe] = Field(default_factory=list)
    has_video: bool = False
    has_audio: bool = False
    primary_video_stream: Optional[MediaStreamProbe] = None
    primary_audio_stream: Optional[MediaStreamProbe] = None


class FFmpegExecutableStatus(BaseModel):
    """Status, path, and version information for FFmpeg or FFprobe."""
    name: str = "ffmpeg"
    is_available: bool = False
    executable_path: Optional[str] = None
    version: Optional[str] = None
    codecs_supported: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class VideoAssemblySystemStatus(BaseModel):
    """Overall status of host system video assembly foundation."""
    ffmpeg: FFmpegExecutableStatus
    ffprobe: FFmpegExecutableStatus
    is_ready: bool = False
    default_configuration: VideoRenderConfiguration = Field(default_factory=VideoRenderConfiguration)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# Phase 6.2: Scene Video Rendering Schemas
# ==============================================================================

class SceneRenderStatus(str, Enum):
    """Status of an individual scene video render."""
    PENDING = "pending"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SceneRenderConfiguration(BaseModel):
    """Rendering parameters for individual scene segments."""
    resolution_width: int = Field(default=1920, ge=320, le=7680, description="Video width in pixels (even integer)")
    resolution_height: int = Field(default=1080, ge=180, le=4320, description="Video height in pixels (even integer)")
    aspect_ratio: str = Field(default="16:9", description="Standard target aspect ratio")
    fps: int = Field(default=30, ge=1, le=120, description="Frame rate per second")

    video_codec: str = Field(default="libx264", description="FFmpeg video encoder codec name")
    pixel_format: str = Field(default="yuv420p", description="Pixel format for universal web playback compatibility")
    crf: Optional[int] = Field(default=23, ge=0, le=51, description="Constant Rate Factor for x264 quality")
    preset: str = Field(default="medium", description="FFmpeg x264 preset")

    audio_codec: str = Field(default="aac", description="FFmpeg audio encoder codec name")
    audio_sample_rate: int = Field(default=44100, ge=8000, le=192000, description="Audio sample rate in Hz")
    audio_channels: int = Field(default=2, ge=1, le=8, description="Number of audio channels (1=mono, 2=stereo)")
    audio_bitrate: str = Field(default="192k", description="Audio bitrate")

    faststart: bool = Field(default=True, description="Enable movflags +faststart for progressive web playback")
    container_format: str = Field(default="mp4", description="Output container format")

    @field_validator("video_codec")
    @classmethod
    def _validate_video_codec(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_VIDEO_CODECS:
            raise ValueError(f"Unsupported video codec '{v}'. Allowed: {sorted(SUPPORTED_VIDEO_CODECS)}")
        return clean

    @field_validator("audio_codec")
    @classmethod
    def _validate_audio_codec(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_AUDIO_CODECS:
            raise ValueError(f"Unsupported audio codec '{v}'. Allowed: {sorted(SUPPORTED_AUDIO_CODECS)}")
        return clean

    @field_validator("pixel_format")
    @classmethod
    def _validate_pix_fmt(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_PIXEL_FORMATS:
            raise ValueError(f"Unsupported pixel format '{v}'. Allowed: {sorted(SUPPORTED_PIXEL_FORMATS)}")
        return clean


class SceneRenderAsset(BaseModel):
    """Rendered or in-progress MP4 segment asset for an individual scene."""
    scene_id: str = Field(..., description="Unique scene identifier")
    scene_number: int = Field(..., ge=1, description="1-indexed monotonic scene order in the storyboard")
    title: str = Field(default="", description="Scene title or header")

    source_visual_path: Optional[str] = Field(default=None, description="Relative path to source SVG/image asset")
    source_narration_path: Optional[str] = Field(default=None, description="Relative path to source narration MP3 audio")
    prepared_visual_path: Optional[str] = Field(default=None, description="Relative path to rasterized 1920x1080 PNG")

    expected_duration_seconds: float = Field(default=0.0, ge=0.0, description="Planned storyboard duration in seconds")
    actual_duration_seconds: Optional[float] = Field(default=None, ge=0.0, description="Actual probed MP4 duration in seconds")

    output_relative_path: Optional[str] = Field(default=None, description="Relative path to rendered scene MP4 file")
    file_size_bytes: int = Field(default=0, ge=0, description="Size of rendered MP4 file on disk")
    status: SceneRenderStatus = Field(default=SceneRenderStatus.PENDING, description="Current scene render status")

    is_silent: bool = Field(default=False, description="Whether this scene is silent (video-only MP4 segment)")
    width: int = Field(default=1920, ge=1)
    height: int = Field(default=1080, ge=1)
    fps: int = Field(default=30, ge=1)
    video_codec: str = Field(default="libx264")
    audio_codec: Optional[str] = Field(default=None)

    error: Optional[str] = Field(default=None, description="Detailed error message if scene rendering failed")
    warnings: List[str] = Field(default_factory=list, description="Advisory warnings encountered during rendering")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None, description="Timestamp of successful render completion")

    @field_validator("scene_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Scene ID '{v}' contains invalid characters.")
        return v


class SceneRenderProgress(BaseModel):
    """Progress tracking for overall scene rendering execution."""
    job_id: str
    status: SceneRenderStatus = SceneRenderStatus.PENDING
    progress_percentage: int = Field(default=0, ge=0, le=100)
    current_scene_index: int = 0
    total_scenes: int = 0
    completed_scenes: int = 0
    failed_scenes: int = 0
    current_scene_id: Optional[str] = None
    stage_detail: str = "Ready for scene rendering"

    @field_validator("job_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Job ID '{v}' contains invalid characters.")
        return v


class SceneRenderResult(BaseModel):
    """Aggregate result of rendering all scenes for a job."""
    job_id: str
    total_scenes: int = 0
    completed_scenes: int = 0
    failed_scenes: int = 0
    is_complete: bool = False
    render_duration_seconds: float = 0.0
    scenes: List[SceneRenderAsset] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @field_validator("job_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Job ID '{v}' contains invalid characters.")
        return v
