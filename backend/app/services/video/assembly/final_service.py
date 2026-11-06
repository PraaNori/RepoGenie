"""
Final Video Assembly Service (Milestone 6, Phase 6.3).

Assembles rendered scene videos in storyboard order into one standardized,
high-quality MP4 file using the FFmpeg concat demuxer, preserves narration audio
synchronization, handles silent scenes, validates outputs with FFprobe, and
atomically updates Stage 09 pipeline progress upon verified success.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ....core.config import settings
from ...storage.job_store import job_store
from .command_builder import FFmpegCommandBuilder, command_builder
from .exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FinalVideoAssemblyError,
    JobRenderConcurrencyError,
    MediaProbeError,
    VideoStorageError,
)
from .ffmpeg_manager import FFmpegManager, ffmpeg_manager
from .ffprobe_manager import FFprobeManager, ffprobe_manager
from .process_runner import run_process_sync
from .scene_service import SceneRenderService, scene_render_service
from .schemas import (
    MediaProbeResult,
    VideoRenderConfiguration,
    VideoRenderJob,
    VideoRenderProgress,
    VideoRenderResult,
    VideoRenderStatus,
)
from .storage import VideoStorageManager, video_storage_manager

logger = logging.getLogger(__name__)

# Concurrency locks per job to serialize final assembly execution
_active_final_renders: set[str] = set()
_final_render_mutex = threading.Lock()


class FinalVideoAssemblyService:
    """
    Coordinates concatenation of verified scene video clips into the canonical
    full-length educational walkthrough video (MP4) for a job.
    """

    def __init__(
        self,
        ffmpeg_mgr: Optional[FFmpegManager] = None,
        ffprobe_mgr: Optional[FFprobeManager] = None,
        storage_mgr: Optional[VideoStorageManager] = None,
        cmd_builder: Optional[FFmpegCommandBuilder] = None,
        scene_svc: Optional[SceneRenderService] = None,
    ):
        self._ffmpeg = ffmpeg_mgr or ffmpeg_manager
        self._ffprobe = ffprobe_mgr or ffprobe_manager
        self._storage = storage_mgr or video_storage_manager
        self._builder = cmd_builder or command_builder
        self._scene_service = scene_svc or scene_render_service

    def get_final_video_file_path(self, job_id: str) -> Path:
        """
        Returns verified path to the completed final video MP4.
        Raises VideoStorageError if file does not exist or is empty.
        """
        self._storage.assert_safe_job_id(job_id)
        final_path = self._storage.get_final_output_path(job_id, "final_video.mp4")
        if not final_path.exists() or final_path.stat().st_size == 0:
            raise VideoStorageError(f"Final video file does not exist for job '{job_id}'")
        return self._storage.assert_safe_path(final_path)

    def get_final_video_result(self, job_id: str) -> Optional[VideoRenderResult]:
        """
        Returns cached VideoRenderResult for a completed job, or None if not yet assembled.
        """
        self._storage.assert_safe_job_id(job_id)
        job = job_store.get_internal_job(job_id)
        if not job or not job.render_job or job.render_job.status != VideoRenderStatus.COMPLETED:
            return None

        # Build VideoRenderResult from render_job metadata if final video is on disk
        try:
            final_path = self.get_final_video_file_path(job_id)
            probe = self._ffprobe.probe_media_file(final_path)
            return self._build_result_from_probe(
                job_id=job_id,
                file_path=final_path,
                probe=probe,
                config=job.render_config or VideoRenderConfiguration(),
                completed_at=job.render_job.completed_at,
            )
        except Exception as exc:
            logger.warning("Could not probe existing final video for job %s: %s", job_id, exc)
            return None

    def assemble_video(self, job_id: str, refresh: bool = False) -> VideoRenderResult:
        """
        Executes complete final video assembly for a job:
        1. Validates preconditions and acquires exclusive per-job lock.
        2. Ensures all storyboard scenes are rendered to MP4 (rendering if needed).
        3. Verifies each scene clip on disk and probes stream properties.
        4. Normalizes silent scenes if mixed with audio scenes so concat demuxer preserves all streams.
        5. Formats concat manifest and invokes FFmpeg concat demuxer with stream copy (-c copy).
        6. Atomically moves output to canonical final_video.mp4.
        7. Performs deep FFprobe verification of streams, duration, and codecs.
        8. Updates JobStore Stage 09 to COMPLETED and sets job status to COMPLETED.
        """
        self._storage.assert_safe_job_id(job_id)

        # 1. Concurrency control
        with _final_render_mutex:
            if job_id in _active_final_renders:
                raise JobRenderConcurrencyError(f"Final video assembly is already in progress for job '{job_id}'")
            _active_final_renders.add(job_id)

        start_time = time.time()
        try:
            return self._execute_assembly(job_id=job_id, refresh=refresh, start_time=start_time)
        finally:
            with _final_render_mutex:
                _active_final_renders.discard(job_id)

    def _execute_assembly(self, job_id: str, refresh: bool, start_time: float) -> VideoRenderResult:
        # Check host executable availability
        self._ffmpeg.assert_available()
        self._ffprobe.assert_available()

        job = job_store.get_internal_job(job_id)
        if not job:
            raise VideoStorageError(f"Job with ID '{job_id}' not found")

        assembly_input = job.assembly_input
        if not assembly_input:
            raise FinalVideoAssemblyError(
                f"Video assembly input package not found for job '{job_id}'. Run assembly preflight first."
            )

        report = assembly_input.readiness_report
        is_ready = getattr(report, "status", None) != "not_ready" and len(getattr(report, "blocking_issues", [])) == 0
        if not is_ready:
            blocking_issues = [i.message for i in getattr(report, "blocking_issues", [])]
            raise FinalVideoAssemblyError(
                f"Video assembly package is NOT ready: {'; '.join(blocking_issues[:3])}"
            )

        scenes = sorted(assembly_input.scenes, key=lambda s: s.scene_number)
        if not scenes:
            raise FinalVideoAssemblyError(f"Storyboard contains no scenes for job '{job_id}'")

        config = job.render_config or VideoRenderConfiguration()
        total_scenes = len(scenes)

        # 2. Check scene renders status
        scene_result = job_store.get_job_scene_renders(job_id)
        if not scene_result or not scene_result.is_complete:
            logger.info("Scene renders not complete for job %s; running scene render service", job_id)
            scene_result = self._scene_service.render_scenes(job_id=job_id, refresh=False)

        if not scene_result.is_complete:
            err_msg = f"Cannot assemble video: {scene_result.failed_scenes} of {total_scenes} scenes failed rendering."
            job_store.update_job_render_failed(job_id, err_msg)
            raise FinalVideoAssemblyError(err_msg)

        final_output_path = self._storage.get_final_output_path(job_id, "final_video.mp4")

        # 3. Cache reuse check
        if not refresh and final_output_path.exists() and final_output_path.stat().st_size > 0:
            final_mtime = final_output_path.stat().st_mtime
            scenes_older = True
            for sc in scenes:
                sc_path = self._storage.get_scene_output_path(job_id, sc.scene_number, sc.scene_id)
                if not sc_path.exists() or sc_path.stat().st_mtime > final_mtime:
                    scenes_older = False
                    break

            if scenes_older:
                try:
                    probe = self._ffprobe.probe_media_file(final_output_path)
                    if probe.has_video and probe.duration_seconds > 0:
                        logger.info("Reusing cached final video for job %s: %s", job_id, final_output_path)
                        result = self._build_result_from_probe(
                            job_id=job_id,
                            file_path=final_output_path,
                            probe=probe,
                            config=config,
                            completed_at=datetime.fromtimestamp(final_mtime, timezone.utc),
                        )
                        job_store.update_job_render_success(job_id, result)
                        return result
                except Exception as probe_err:
                    logger.warning("Existing final video failed validation probe, re-assembling: %s", probe_err)

        # 4. Verify all scene files on disk and probe streams
        scene_probes: List[MediaProbeResult] = []
        has_any_audio = False
        has_any_silent = False

        for sc in scenes:
            sc_path = self._storage.get_scene_output_path(job_id, sc.scene_number, sc.scene_id)
            if not sc_path.exists() or sc_path.stat().st_size == 0:
                err_msg = f"Rendered clip for scene {sc.scene_number} ('{sc.scene_id}') is missing or empty on disk: {sc_path}"
                job_store.update_job_render_failed(job_id, err_msg)
                raise FinalVideoAssemblyError(err_msg)

            try:
                probe = self._ffprobe.probe_media_file(sc_path)
            except MediaProbeError as mpe:
                err_msg = f"Failed to probe scene {sc.scene_number} clip: {mpe}"
                job_store.update_job_render_failed(job_id, err_msg)
                raise FinalVideoAssemblyError(err_msg) from mpe

            if not probe.has_video:
                err_msg = f"Scene {sc.scene_number} clip has no valid video stream: {sc_path}"
                job_store.update_job_render_failed(job_id, err_msg)
                raise FinalVideoAssemblyError(err_msg)

            if probe.has_audio:
                has_any_audio = True
            else:
                has_any_silent = True

            scene_probes.append(probe)

        # 5. Initialize render progress in JobStore
        init_progress = VideoRenderProgress(
            job_id=job_id,
            status=VideoRenderStatus.RENDERING,
            progress_percentage=95,
            current_scene=total_scenes,
            total_scenes=total_scenes,
            elapsed_seconds=round(time.time() - start_time, 2),
            stage_detail=f"Preparing {total_scenes} scenes for final concatenation...",
        )
        job_store.update_job_render_progress(job_id, init_progress)

        temp_normalized_files: List[Path] = []
        concat_scene_files: List[Path] = []
        manifest_path: Optional[Path] = None
        temp_final_path: Optional[Path] = None

        try:
            # 6. Stream layout normalization:
            # If the storyboard is mixed (some scenes narrated with audio, some silent without audio),
            # concat demuxer requires uniform streams across all segments.
            # We normalize silent scenes by adding a silent AAC audio track via fast stream copy (-c:v copy).
            for idx, (sc, probe) in enumerate(zip(scenes, scene_probes)):
                orig_path = self._storage.get_scene_output_path(job_id, sc.scene_number, sc.scene_id)
                if has_any_audio and not probe.has_audio:
                    norm_temp = self._storage.create_temp_render_path(job_id, extension="mp4")
                    temp_normalized_files.append(norm_temp)
                    norm_cmd = self._builder.build_silent_audio_normalization_command(
                        scene_path=orig_path,
                        output_path=norm_temp,
                        duration_seconds=probe.duration_seconds,
                        config=config,
                    )
                    ret, _, stderr = run_process_sync(norm_cmd, timeout_seconds=float(settings.VIDEO_RENDER_TIMEOUT))
                    if ret != 0:
                        raise FFmpegExecutionError(
                            f"Failed to normalize silent scene {sc.scene_number} audio: {stderr[:250]}",
                            return_code=ret,
                            stderr=stderr,
                            command=" ".join(norm_cmd),
                        )
                    concat_scene_files.append(norm_temp)
                else:
                    concat_scene_files.append(orig_path)

            # 7. Create concat manifest
            manifest_path = self._storage.create_concat_manifest(job_id, concat_scene_files)

            # 8. Execute concat command
            temp_final_path = self._storage.create_temp_render_path(job_id, extension="mp4")
            concat_cmd = self._builder.build_concat_command(
                concat_list_file=manifest_path,
                output_path=temp_final_path,
                config=config,
            )

            job_store.update_job_render_progress(
                job_id,
                VideoRenderProgress(
                    job_id=job_id,
                    status=VideoRenderStatus.RENDERING,
                    progress_percentage=98,
                    current_scene=total_scenes,
                    total_scenes=total_scenes,
                    elapsed_seconds=round(time.time() - start_time, 2),
                    stage_detail="Concatenating scenes into final MP4 video...",
                ),
            )

            code, stdout, stderr = run_process_sync(
                concat_cmd,
                timeout_seconds=float(settings.VIDEO_RENDER_TIMEOUT),
            )

            if code != 0:
                raise FFmpegExecutionError(
                    f"FFmpeg concat failed with exit code {code}: {stderr[:300]}",
                    return_code=code,
                    stderr=stderr,
                    command=" ".join(concat_cmd),
                )

            # 9. Atomically promote temp output to canonical final_video.mp4
            promoted_path = self._storage.finalize_render_output(
                job_id=job_id,
                temp_render_path=temp_final_path,
                target_filename="final_video.mp4",
                overwrite=True,
            )
            temp_final_path = None  # moved successfully

            # 10. Deep FFprobe post-render validation
            final_probe = self._ffprobe.probe_media_file(promoted_path)
            if not final_probe.has_video:
                raise FinalVideoAssemblyError("Assembled final video has no video stream.")

            if final_probe.duration_seconds <= 0:
                raise FinalVideoAssemblyError(
                    f"Assembled final video has non-positive duration: {final_probe.duration_seconds:.2f}s"
                )

            if has_any_audio and not final_probe.has_audio:
                raise FinalVideoAssemblyError("Assembled final video is missing audio stream despite narrated scenes.")

            # Calculate total expected duration
            total_expected_duration = sum(sc.duration_seconds for sc in scenes)
            if abs(final_probe.duration_seconds - total_expected_duration) > max(1.5, total_scenes * 0.5):
                logger.warning(
                    "Final video duration (%.2fs) differs from expected sum of scenes (%.2fs)",
                    final_probe.duration_seconds,
                    total_expected_duration,
                )

            # 11. Build result and update JobStore
            result = self._build_result_from_probe(
                job_id=job_id,
                file_path=promoted_path,
                probe=final_probe,
                config=config,
            )

            job_store.update_job_render_success(job_id, result)
            logger.info("Successfully assembled final video for job %s: %s (%.2fs)", job_id, promoted_path, result.duration_seconds)
            return result

        except Exception as exc:
            if temp_final_path:
                self._storage.cleanup_file(temp_final_path)
            error_message = str(exc)
            job_store.update_job_render_failed(job_id, error_message)
            if not isinstance(exc, FinalVideoAssemblyError):
                raise FinalVideoAssemblyError(f"Final video assembly failed: {exc}") from exc
            raise
        finally:
            # Always clean up concat manifest and temporary normalized clips
            if manifest_path:
                self._storage.cleanup_file(manifest_path)
            for norm_file in temp_normalized_files:
                self._storage.cleanup_file(norm_file)

    def _build_result_from_probe(
        self,
        job_id: str,
        file_path: Path,
        probe: MediaProbeResult,
        config: VideoRenderConfiguration,
        completed_at: Optional[datetime] = None,
    ) -> VideoRenderResult:
        rel_path = self._storage.get_relative_video_path(job_id, file_path.name)
        v_stream = probe.primary_video_stream
        a_stream = probe.primary_audio_stream

        width = (v_stream and v_stream.width) or config.resolution_width
        height = (v_stream and v_stream.height) or config.resolution_height
        fps = int((v_stream and v_stream.fps) or config.fps)
        v_codec = (v_stream and v_stream.codec_name) or config.video_codec
        a_codec = (a_stream and a_stream.codec_name) if a_stream else None

        return VideoRenderResult(
            job_id=job_id,
            status=VideoRenderStatus.COMPLETED,
            output_relative_path=rel_path,
            file_size_bytes=probe.size_bytes or file_path.stat().st_size,
            duration_seconds=round(probe.duration_seconds, 3),
            resolution=f"{width}x{height}",
            fps=fps,
            video_codec=v_codec,
            audio_codec=a_codec,
            completed_at=completed_at or datetime.now(timezone.utc),
        )


# Global singleton instance
final_video_assembly_service = FinalVideoAssemblyService()
