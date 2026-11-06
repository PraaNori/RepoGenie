"""
Video Assembly Package (Milestone 6, Phase 6.1: FFmpeg Video Assembly Foundation).
"""

from .exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FFprobeNotFoundError,
    FFmpegTimeoutError,
    InvalidRenderConfigurationError,
    JobRenderConcurrencyError,
    MediaProbeError,
    VideoAssemblyError,
    VideoStorageError,
)
from .schemas import (
    FFmpegExecutableStatus,
    MediaProbeResult,
    MediaStreamProbe,
    VideoAssemblySystemStatus,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderProgress,
    VideoRenderResult,
    VideoRenderStatus,
)
from .process_runner import run_process_async, run_process_sync
from .ffmpeg_manager import FFmpegManager, ffmpeg_manager
from .ffprobe_manager import FFprobeManager, ffprobe_manager
from .storage import VideoStorageManager, video_storage_manager
from .command_builder import FFmpegCommandBuilder, command_builder
from .service import VideoAssemblyService, video_assembly_service

__all__ = [
    "FFmpegExecutionError",
    "FFmpegNotFoundError",
    "FFprobeNotFoundError",
    "FFmpegTimeoutError",
    "InvalidRenderConfigurationError",
    "JobRenderConcurrencyError",
    "MediaProbeError",
    "VideoAssemblyError",
    "VideoStorageError",
    "FFmpegExecutableStatus",
    "MediaProbeResult",
    "MediaStreamProbe",
    "VideoAssemblySystemStatus",
    "VideoRenderConfiguration",
    "VideoRenderJob",
    "VideoRenderProgress",
    "VideoRenderResult",
    "VideoRenderStatus",
    "run_process_async",
    "run_process_sync",
    "FFmpegManager",
    "ffmpeg_manager",
    "FFprobeManager",
    "ffprobe_manager",
    "VideoStorageManager",
    "video_storage_manager",
    "FFmpegCommandBuilder",
    "command_builder",
    "VideoAssemblyService",
    "video_assembly_service",
]
