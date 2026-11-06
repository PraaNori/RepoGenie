"""
Video Assembly Service Foundation (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ....core.config import settings
from ...storage.job_store import job_store
from .command_builder import FFmpegCommandBuilder, command_builder
from .exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    InvalidRenderConfigurationError,
    JobRenderConcurrencyError,
    VideoStorageError,
)
from .ffmpeg_manager import FFmpegManager, ffmpeg_manager
from .ffprobe_manager import FFprobeManager, ffprobe_manager
from .process_runner import run_process_sync
from .schemas import (
    MediaProbeResult,
    VideoAssemblySystemStatus,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderProgress,
    VideoRenderResult,
    VideoRenderStatus,
)
from .storage import VideoStorageManager, video_storage_manager

logger = logging.getLogger(__name__)


class VideoAssemblyService:
    """Core service establishing the secure FFmpeg foundation for video compilation."""

    def __init__(
        self,
        ffmpeg_mgr: Optional[FFmpegManager] = None,
        ffprobe_mgr: Optional[FFprobeManager] = None,
        storage_mgr: Optional[VideoStorageManager] = None,
        cmd_builder: Optional[FFmpegCommandBuilder] = None,
    ):
        self._ffmpeg = ffmpeg_mgr or ffmpeg_manager
        self._ffprobe = ffprobe_mgr or ffprobe_manager
        self._storage = storage_mgr or video_storage_manager
        self._builder = cmd_builder or command_builder

    def get_system_status(self, refresh: bool = False) -> VideoAssemblySystemStatus:
        """Returns the readiness status of host FFmpeg and FFprobe binaries."""
        ff_status = self._ffmpeg.get_status(refresh=refresh)
        fp_status = self._ffprobe.get_status(refresh=refresh)
        is_ready = ff_status.is_available and fp_status.is_available

        return VideoAssemblySystemStatus(
            ffmpeg=ff_status,
            ffprobe=fp_status,
            is_ready=is_ready,
            default_configuration=VideoRenderConfiguration(),
        )

    def get_job_render_config(self, job_id: str) -> VideoRenderConfiguration:
        """Retrieves or initializes the render configuration for a job."""
        self._storage.assert_safe_job_id(job_id)
        internal = job_store.get_internal_job(job_id)
        if not internal:
            raise VideoStorageError(f"Job '{job_id}' not found.")

        config = job_store.get_job_render_config(job_id)
        if not config:
            config = VideoRenderConfiguration()
            job_store.update_job_render_config(job_id, config)
        return config

    def update_job_render_config(
        self,
        job_id: str,
        config: VideoRenderConfiguration,
    ) -> VideoRenderConfiguration:
        """Validates and updates custom render configuration for a job."""
        self._storage.assert_safe_job_id(job_id)
        internal = job_store.get_internal_job(job_id)
        if not internal:
            raise VideoStorageError(f"Job '{job_id}' not found.")

        # Ensure job is not currently rendering
        current_render = job_store.get_job_render(job_id)
        if current_render and current_render.status == VideoRenderStatus.RENDERING:
            raise JobRenderConcurrencyError(f"Cannot update configuration while job '{job_id}' is actively rendering.")

        job_store.update_job_render_config(job_id, config)
        return config

    def get_job_render(self, job_id: str) -> Optional[VideoRenderJob]:
        """Returns the current rendering job record for a repository job."""
        self._storage.assert_safe_job_id(job_id)
        return job_store.get_job_render(job_id)

    def probe_media_file(self, file_path: Path) -> MediaProbeResult:
        """Executes ffprobe to inspect streams, duration, and codecs of a media file."""
        return self._ffprobe.probe_media_file(file_path)

    def execute_synthetic_smoke_test(
        self,
        job_id: str,
        duration_seconds: float = 2.0,
        cleanup_output: bool = True,
    ) -> MediaProbeResult:
        """
        Executes a self-contained synthetic video generation and probing smoke test
        using lavfi test sources. Does NOT invoke any external APIs.
        Cleans up temporary smoke test assets when cleanup_output is True.
        """
        self._ffmpeg.assert_available()
        self._ffprobe.assert_available()

        config = self.get_job_render_config(job_id)
        temp_path = self._storage.create_temp_render_path(job_id, extension="mp4")

        builder = FFmpegCommandBuilder(ffmpeg_executable=str(self._ffmpeg.resolve_binary()))
        cmd = builder.build_synthetic_color_video_command(
            output_path=temp_path,
            duration_seconds=duration_seconds,
            config=config,
        )

        try:
            ret, stdout, stderr = run_process_sync(cmd, timeout_seconds=30.0)
            if ret != 0:
                raise FFmpegExecutionError(
                    f"Synthetic smoke test rendering failed with code {ret}: {stderr[:300]}",
                    return_code=ret,
                    stderr=stderr,
                    command=" ".join(cmd),
                )

            final_path = self._storage.finalize_render_output(
                job_id=job_id,
                temp_render_path=temp_path,
                target_filename="synthetic_smoke_test.mp4",
                overwrite=True,
            )

            # Probe the synthesized test media
            probe = self.probe_media_file(final_path)
            if cleanup_output:
                self._storage.cleanup_file(final_path)
            return probe
        finally:
            self._storage.cleanup_file(temp_path)


video_assembly_service = VideoAssemblyService()
