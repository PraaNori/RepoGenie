"""
Per-Scene Video Rendering Service (Milestone 6, Phase 6.2).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ....core.config import settings
from ...storage.job_store import job_store
from .command_builder import FFmpegCommandBuilder, command_builder
from .exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    JobRenderConcurrencyError,
    MediaProbeError,
    SceneRenderError,
    VideoStorageError,
    VisualPreparationError,
)
from .ffmpeg_manager import FFmpegManager, ffmpeg_manager
from .ffprobe_manager import FFprobeManager, ffprobe_manager
from .process_runner import run_process_sync
from .schemas import (
    SceneRenderAsset,
    SceneRenderProgress,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
)
from .storage import VideoStorageManager, video_storage_manager
from .visual_preparer import VisualAssetPreparer, visual_asset_preparer

logger = logging.getLogger(__name__)

# Concurrency locks per job to prevent duplicate render executions
_active_scene_renders: set[str] = set()
_scene_render_mutex = threading.Lock()


class SceneRenderService:
    """
    Orchestrates the conversion of validated storyboard scenes into individual
    standardized MP4 video segments with visual rasterization, audio synchronization,
    probing, and atomic storage.
    """

    def __init__(
        self,
        ffmpeg_mgr: Optional[FFmpegManager] = None,
        ffprobe_mgr: Optional[FFprobeManager] = None,
        storage_mgr: Optional[VideoStorageManager] = None,
        cmd_builder: Optional[FFmpegCommandBuilder] = None,
        preparer: Optional[VisualAssetPreparer] = None,
    ):
        self._ffmpeg = ffmpeg_mgr or ffmpeg_manager
        self._ffprobe = ffprobe_mgr or ffprobe_manager
        self._storage = storage_mgr or video_storage_manager
        self._builder = cmd_builder or command_builder
        self._preparer = preparer or visual_asset_preparer

    def get_scene_renders(self, job_id: str) -> Optional[SceneRenderResult]:
        """Retrieves cached scene render result for a job."""
        self._storage.assert_safe_job_id(job_id)
        return job_store.get_job_scene_renders(job_id)

    def get_single_scene_render(self, job_id: str, scene_id: str) -> Optional[SceneRenderAsset]:
        """Retrieves render asset metadata for a single scene."""
        self._storage.assert_safe_job_id(job_id)
        self._storage.assert_safe_scene_id(scene_id)
        result = self.get_scene_renders(job_id)
        if not result:
            return None
        for scene in result.scenes:
            if scene.scene_id == scene_id:
                return scene
        return None

    def get_scene_render_file_path(self, job_id: str, scene_id: str) -> Path:
        """
        Returns the verified absolute path to a rendered scene MP4.
        Raises VideoStorageError if not found or outside storage root.
        """
        asset = self.get_single_scene_render(job_id, scene_id)
        if not asset or not asset.output_relative_path:
            raise VideoStorageError(f"Scene render asset '{scene_id}' not found for job '{job_id}'")

        target = self._storage.get_scene_output_path(job_id, asset.scene_number, asset.scene_id)
        if not target.exists() or target.stat().st_size == 0:
            raise VideoStorageError(f"Rendered scene MP4 file does not exist on disk: {target}")

        return self._storage.assert_safe_path(target)

    def render_scenes(self, job_id: str, refresh: bool = False) -> SceneRenderResult:
        """
        Executes rendering for all scenes in the job's storyboard.
        Reuses cached MP4 clips when valid and refresh=False.
        """
        self._storage.assert_safe_job_id(job_id)

        # 1. Concurrency control
        with _scene_render_mutex:
            if job_id in _active_scene_renders:
                raise JobRenderConcurrencyError(f"Scene rendering is already in progress for job '{job_id}'")
            _active_scene_renders.add(job_id)

        start_time = time.time()
        try:
            return self._execute_scene_renders(job_id, refresh=refresh, start_time=start_time)
        finally:
            with _scene_render_mutex:
                _active_scene_renders.discard(job_id)

    def _execute_scene_renders(self, job_id: str, refresh: bool, start_time: float) -> SceneRenderResult:
        # 2. Check binary availability
        self._ffmpeg.assert_available()
        self._ffprobe.assert_available()

        # 3. Retrieve internal job & assembly input
        job = job_store.get_internal_job(job_id)
        if not job:
            raise VideoStorageError(f"Job with ID '{job_id}' not found")

        assembly_input = job.assembly_input
        if not assembly_input:
            raise SceneRenderError(
                f"Video assembly input package not found for job '{job_id}'. Run assembly preflight first.",
                scene_id="",
            )

        report = assembly_input.readiness_report
        is_ready = getattr(report, "status", None) != "not_ready" and len(getattr(report, "blocking_issues", [])) == 0
        if not is_ready:
            blocking_issues = [
                i.message for i in getattr(report, "blocking_issues", [])
            ]
            raise SceneRenderError(
                f"Video assembly package is NOT ready: {'; '.join(blocking_issues[:3])}",
                scene_id="",
            )

        scenes = assembly_input.scenes
        if not scenes:
            raise SceneRenderError(f"Storyboard contains no scenes for job '{job_id}'", scene_id="")

        config = job.render_config or VideoRenderConfiguration()
        total_scenes = len(scenes)

        # Notify JobStore: Stage 09 is IN_PROGRESS
        job_store.update_job_scene_renders_started(job_id, total_scenes=total_scenes)

        rendered_assets: List[SceneRenderAsset] = []
        completed_count = 0
        failed_count = 0

        # Sort explicitly by monotonic scene_number
        sorted_scenes = sorted(scenes, key=lambda s: s.scene_number)

        for idx, scene in enumerate(sorted_scenes):
            scene_num = scene.scene_number
            scene_id = scene.scene_id
            title = scene.title or f"Scene {scene_num}"

            # Update progress
            progress = SceneRenderProgress(
                job_id=job_id,
                status=SceneRenderStatus.RENDERING,
                progress_percentage=int((idx / total_scenes) * 100),
                current_scene_index=idx + 1,
                total_scenes=total_scenes,
                completed_scenes=completed_count,
                failed_scenes=failed_count,
                current_scene_id=scene_id,
                stage_detail=f"Rendering scene {idx + 1}/{total_scenes}: {title}",
            )
            job_store.update_job_scene_render_progress(job_id, progress)

            asset = self._render_individual_scene(
                job_id=job_id,
                scene=scene,
                config=config,
                refresh=refresh,
            )
            rendered_assets.append(asset)
            if asset.status == SceneRenderStatus.COMPLETED:
                completed_count += 1
            else:
                failed_count += 1

        elapsed = time.time() - start_time
        is_complete = completed_count == total_scenes and total_scenes > 0

        result = SceneRenderResult(
            job_id=job_id,
            total_scenes=total_scenes,
            completed_scenes=completed_count,
            failed_scenes=failed_count,
            is_complete=is_complete,
            render_duration_seconds=round(elapsed, 2),
            scenes=rendered_assets,
            completed_at=datetime.now(timezone.utc) if is_complete else None,
        )

        job_store.update_job_scene_renders_completed(job_id, result)
        return result

    def _render_individual_scene(
        self,
        job_id: str,
        scene,
        config: VideoRenderConfiguration,
        refresh: bool,
    ) -> SceneRenderAsset:
        scene_num = scene.scene_number
        scene_id = scene.scene_id
        title = scene.title or f"Scene {scene_num}"

        visual_ref = scene.visual_asset
        narration_ref = scene.narration_asset
        is_silent = scene.is_silent or narration_ref is None

        # Verify visual reference
        if not visual_ref:
            return SceneRenderAsset(
                scene_id=scene_id,
                scene_number=scene_num,
                title=title,
                status=SceneRenderStatus.FAILED,
                error="Missing required visual asset reference for scene",
                is_silent=is_silent,
            )

        source_visual_path = self._storage.base_dir / visual_ref.relative_path
        if not source_visual_path.exists():
            source_visual_path = settings.storage_path / visual_ref.relative_path
        if not source_visual_path.exists():
            source_visual_path = Path(settings.STORAGE_DIR) / visual_ref.relative_path
        if not source_visual_path.exists():
            return SceneRenderAsset(
                scene_id=scene_id,
                scene_number=scene_num,
                title=title,
                status=SceneRenderStatus.FAILED,
                error=f"Visual asset file not found on disk: {visual_ref.relative_path}",
                is_silent=is_silent,
            )

        # Determine narration path and target duration
        source_narration_path: Optional[Path] = None
        target_duration = scene.duration_seconds

        if not is_silent and narration_ref:
            p = self._storage.base_dir / narration_ref.relative_path
            if not p.exists():
                p = settings.storage_path / narration_ref.relative_path
            if not p.exists():
                p = Path(settings.STORAGE_DIR) / narration_ref.relative_path
            if not p.exists():
                return SceneRenderAsset(
                    scene_id=scene_id,
                    scene_number=scene_num,
                    title=title,
                    status=SceneRenderStatus.FAILED,
                    error=f"Narration audio file not found on disk: {narration_ref.relative_path}",
                    is_silent=False,
                )
            source_narration_path = p
            # Use actual measured narration duration (do NOT stretch audio)
            target_duration = narration_ref.duration_seconds or scene.duration_seconds

        target_duration = max(0.5, round(target_duration, 3))

        # Destination paths
        raster_path = self._storage.get_raster_output_path(job_id, scene_num, scene_id)
        final_mp4_path = self._storage.get_scene_output_path(job_id, scene_num, scene_id)
        rel_scene_path = self._storage.get_relative_scene_path(job_id, scene_num, scene_id)
        rel_raster_path = self._storage.get_relative_raster_path(job_id, scene_num, scene_id)

        # 1. Visual asset preparation (SVG -> 1920x1080 PNG)
        try:
            self._preparer.prepare_visual_asset(
                source_path=source_visual_path,
                output_png_path=raster_path,
                target_width=config.resolution_width,
                target_height=config.resolution_height,
                refresh=refresh,
            )
        except Exception as exc:
            logger.error("Visual preparation failed for job %s scene %s: %s", job_id, scene_id, exc)
            return SceneRenderAsset(
                scene_id=scene_id,
                scene_number=scene_num,
                title=title,
                source_visual_path=visual_ref.relative_path,
                source_narration_path=narration_ref.relative_path if narration_ref else None,
                status=SceneRenderStatus.FAILED,
                error=f"Visual asset preparation failed: {exc}",
                is_silent=is_silent,
            )

        # 2. Cache reuse check
        if not refresh and final_mp4_path.exists() and final_mp4_path.stat().st_size > 0:
            mp4_mtime = final_mp4_path.stat().st_mtime
            visual_mtime = source_visual_path.stat().st_mtime
            audio_mtime = source_narration_path.stat().st_mtime if source_narration_path else 0.0

            if mp4_mtime >= visual_mtime and mp4_mtime >= audio_mtime:
                try:
                    probe = self._ffprobe.probe_media_file(final_mp4_path)
                    if probe.has_video and (is_silent or probe.has_audio):
                        logger.debug("Reusing valid existing scene clip: %s", final_mp4_path)
                        return SceneRenderAsset(
                            scene_id=scene_id,
                            scene_number=scene_num,
                            title=title,
                            source_visual_path=visual_ref.relative_path,
                            source_narration_path=narration_ref.relative_path if narration_ref else None,
                            prepared_visual_path=rel_raster_path,
                            expected_duration_seconds=target_duration,
                            actual_duration_seconds=probe.duration_seconds,
                            output_relative_path=rel_scene_path,
                            file_size_bytes=probe.size_bytes,
                            status=SceneRenderStatus.COMPLETED,
                            is_silent=is_silent,
                            width=probe.primary_video_stream.width or config.resolution_width if probe.primary_video_stream else config.resolution_width,
                            height=probe.primary_video_stream.height or config.resolution_height if probe.primary_video_stream else config.resolution_height,
                            fps=int(probe.primary_video_stream.fps or config.fps) if probe.primary_video_stream else config.fps,
                            video_codec=probe.primary_video_stream.codec_name if probe.primary_video_stream else config.video_codec,
                            audio_codec=probe.primary_audio_stream.codec_name if probe.primary_audio_stream else None,
                            completed_at=datetime.fromtimestamp(mp4_mtime, timezone.utc),
                        )
                except Exception as probe_err:
                    logger.warning("Existing scene clip failed probe, re-rendering: %s", probe_err)

        # 3. Render scene MP4
        temp_render_path = self._storage.create_temp_scene_render_path(job_id, scene_id)

        builder = FFmpegCommandBuilder(ffmpeg_executable=str(self._ffmpeg.resolve_binary()))
        cmd = builder.build_scene_render_command(
            image_path=raster_path,
            audio_path=source_narration_path,
            output_path=temp_render_path,
            duration_seconds=target_duration,
            config=config,
            is_silent=is_silent,
        )

        try:
            code, stdout, stderr = run_process_sync(
                cmd,
                timeout_seconds=float(settings.VIDEO_RENDER_TIMEOUT),
            )
            if code != 0:
                self._storage.cleanup_file(temp_render_path)
                return SceneRenderAsset(
                    scene_id=scene_id,
                    scene_number=scene_num,
                    title=title,
                    source_visual_path=visual_ref.relative_path,
                    source_narration_path=narration_ref.relative_path if narration_ref else None,
                    prepared_visual_path=rel_raster_path,
                    expected_duration_seconds=target_duration,
                    status=SceneRenderStatus.FAILED,
                    error=f"FFmpeg encoding failed with code {code}: {stderr[:300]}",
                    is_silent=is_silent,
                )

            # 4. Probe the rendered temp file
            probe = self._ffprobe.probe_media_file(temp_render_path)
            if not probe.has_video:
                self._storage.cleanup_file(temp_render_path)
                return SceneRenderAsset(
                    scene_id=scene_id,
                    scene_number=scene_num,
                    title=title,
                    source_visual_path=visual_ref.relative_path,
                    source_narration_path=narration_ref.relative_path if narration_ref else None,
                    status=SceneRenderStatus.FAILED,
                    error="FFprobe validation failed: rendered file lacks a video stream",
                    is_silent=is_silent,
                )

            if not is_silent and not probe.has_audio:
                self._storage.cleanup_file(temp_render_path)
                return SceneRenderAsset(
                    scene_id=scene_id,
                    scene_number=scene_num,
                    title=title,
                    source_visual_path=visual_ref.relative_path,
                    source_narration_path=narration_ref.relative_path if narration_ref else None,
                    status=SceneRenderStatus.FAILED,
                    error="FFprobe validation failed: narrated scene lacks an audio stream",
                    is_silent=False,
                )

            # 5. Atomic promotion
            final_path = self._storage.finalize_scene_render_output(
                job_id=job_id,
                temp_render_path=temp_render_path,
                scene_number=scene_num,
                scene_id=scene_id,
                overwrite=True,
            )

            vid_stream = probe.primary_video_stream
            aud_stream = probe.primary_audio_stream

            return SceneRenderAsset(
                scene_id=scene_id,
                scene_number=scene_num,
                title=title,
                source_visual_path=visual_ref.relative_path,
                source_narration_path=narration_ref.relative_path if narration_ref else None,
                prepared_visual_path=rel_raster_path,
                expected_duration_seconds=target_duration,
                actual_duration_seconds=probe.duration_seconds,
                output_relative_path=rel_scene_path,
                file_size_bytes=probe.size_bytes,
                status=SceneRenderStatus.COMPLETED,
                is_silent=is_silent,
                width=vid_stream.width if vid_stream and vid_stream.width else config.resolution_width,
                height=vid_stream.height if vid_stream and vid_stream.height else config.resolution_height,
                fps=int(vid_stream.fps) if vid_stream and vid_stream.fps else config.fps,
                video_codec=vid_stream.codec_name if vid_stream else config.video_codec,
                audio_codec=aud_stream.codec_name if aud_stream else None,
                completed_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            self._storage.cleanup_file(temp_render_path)
            logger.error("Scene rendering exception for job %s scene %s: %s", job_id, scene_id, exc)
            return SceneRenderAsset(
                scene_id=scene_id,
                scene_number=scene_num,
                title=title,
                source_visual_path=visual_ref.relative_path,
                source_narration_path=narration_ref.relative_path if narration_ref else None,
                status=SceneRenderStatus.FAILED,
                error=f"Unexpected scene rendering error: {exc}",
                is_silent=is_silent,
            )


scene_render_service = SceneRenderService()
