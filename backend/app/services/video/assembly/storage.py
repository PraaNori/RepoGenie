"""
Video Output Storage Manager (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from ....core.config import settings
from .command_builder import FFmpegCommandBuilder
from .exceptions import VideoStorageError
from .schemas import SAFE_ID_REGEX

logger = logging.getLogger(__name__)

# Global in-process lock dictionary per job to serialize finalization
_job_locks: dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_job_lock(job_id: str) -> threading.Lock:
    with _locks_mutex:
        if job_id not in _job_locks:
            _job_locks[job_id] = threading.Lock()
        return _job_locks[job_id]


class VideoStorageManager:
    """Manages isolated video file storage per job with atomic finalization, traversal defense, and overwrite protection."""

    def __init__(self, base_storage_dir: Optional[Path] = None):
        self._custom_base = base_storage_dir

    @property
    def base_dir(self) -> Path:
        """The base storage directory (defaults to settings.storage_path or custom override)."""
        if self._custom_base:
            return Path(self._custom_base).resolve()
        configured = getattr(settings, "VIDEO_OUTPUT_DIR", None) or settings.STORAGE_DIR
        return Path(configured).resolve()

    def assert_safe_job_id(self, job_id: str) -> str:
        """Validates job ID syntax against directory traversal attempts."""
        if not job_id or not SAFE_ID_REGEX.match(job_id):
            raise VideoStorageError(f"Security: Invalid or prohibited job ID '{job_id}'")
        return job_id

    def assert_safe_path(self, path: Path) -> Path:
        """
        Ensures that target path is safely contained within base storage directory.
        Strictly rejects directory traversal and symlink escapes.
        """
        resolved = path.resolve()
        base_resolved = self.base_dir.resolve()
        try:
            # Check relative_to; if resolved is not inside base_resolved, ValueError is raised
            resolved.relative_to(base_resolved)
        except ValueError:
            raise VideoStorageError(f"Security: Path traversal attempt outside storage root: {resolved}")
        return resolved

    def get_job_video_dir(self, job_id: str) -> Path:
        """
        Returns the isolated video storage directory for a specific job:
        storage/jobs/{job_id}/video/
        Guarantees no duplicated jobs/jobs segments regardless of whether VIDEO_OUTPUT_DIR
        ends with 'jobs' or is the root storage path.
        """
        clean_id = self.assert_safe_job_id(job_id)
        base = self.base_dir

        if base.name == "jobs":
            video_dir = base / clean_id / "video"
        else:
            video_dir = base / "jobs" / clean_id / "video"

        safe_path = self.assert_safe_path(video_dir)
        safe_path.mkdir(parents=True, exist_ok=True)
        return safe_path

    def get_relative_video_path(self, job_id: str, filename: str) -> str:
        """Returns the sanitized relative path for API responses: jobs/{job_id}/video/{filename}"""
        clean_id = self.assert_safe_job_id(job_id)
        clean_filename = Path(filename).name  # strips any directory components
        return f"jobs/{clean_id}/video/{clean_filename}"

    def get_final_output_path(self, job_id: str, filename: str = "final_video.mp4") -> Path:
        """Returns absolute path to the completed final video file for a job."""
        video_dir = self.get_job_video_dir(job_id)
        clean_name = Path(filename).name
        target = video_dir / clean_name
        return self.assert_safe_path(target)

    def create_temp_render_path(self, job_id: str, extension: str = "mp4") -> Path:
        """Creates a unique temporary render path for in-progress encoding."""
        video_dir = self.get_job_video_dir(job_id)
        token = uuid.uuid4().hex[:10]
        ext = extension.lstrip(".")
        temp_file = video_dir / f"render_{token}.tmp.{ext}"
        return self.assert_safe_path(temp_file)

    def create_concat_manifest(self, job_id: str, scene_files: List[Path]) -> Path:
        """
        Creates a temporary concat manifest file within the job's isolated video directory.
        Strictly verifies that all scene files are safely within approved storage locations,
        escapes filenames against concat-demuxer injection, and writes the manifest with UTF-8.
        """
        video_dir = self.get_job_video_dir(job_id)
        token = uuid.uuid4().hex[:10]
        manifest_path = video_dir / f"concat_{token}.tmp.txt"

        lines: List[str] = []
        for scene_file in scene_files:
            # Validate path containment
            safe_scene = self.assert_safe_path(scene_file)
            line = FFmpegCommandBuilder.escape_concat_path(str(safe_scene))
            lines.append(f"{line}\n")

        manifest_path.write_text("".join(lines), encoding="utf-8")
        return self.assert_safe_path(manifest_path)

    def finalize_render_output(
        self,
        job_id: str,
        temp_render_path: Path,
        target_filename: str = "final_video.mp4",
        overwrite: bool = False,
    ) -> Path:
        """
        Atomically promotes temp_render_path to target_filename.
        Serialized per job via locks to prevent race conditions during concurrent attempts.
        Enforces:
        - Non-empty render output validation.
        - Overwrite protection preserving previous completed video.
        - Automatic cleanup of temporary files on failure or rejected overwrites.
        """
        lock = _get_job_lock(job_id)
        with lock:
            safe_temp = self.assert_safe_path(temp_render_path)
            if not safe_temp.exists() or not safe_temp.is_file():
                raise VideoStorageError(f"Rendered temporary file does not exist: {safe_temp}")

            size = safe_temp.stat().st_size
            if size == 0:
                self.cleanup_file(safe_temp)
                raise VideoStorageError(f"Rendered video output is empty (0 bytes): {safe_temp}")

            target_path = self.get_final_output_path(job_id, target_filename)
            if target_path.exists() and not overwrite:
                # Cleanup temp file and preserve existing completed output
                self.cleanup_file(safe_temp)
                raise VideoStorageError(
                    f"Target video output already exists: {target_path}. Pass overwrite=True to replace."
                )

            # Atomic move/rename
            try:
                safe_temp.replace(target_path)
                logger.info("Finalized video output for job %s: %s (%d bytes)", job_id, target_path, size)
                return target_path
            except Exception as exc:
                self.cleanup_file(safe_temp)
                raise VideoStorageError(f"Failed to finalize render output: {exc}") from exc

    def cleanup_file(self, file_path: Path) -> None:
        """Safely removes a temporary file if it exists."""
        try:
            safe_path = self.assert_safe_path(file_path)
            if safe_path.exists():
                safe_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Failed to cleanup file %s: %s", file_path, exc)

    def delete_job_video(self, job_id: str) -> None:
        """Cleans up all video assets for a job."""
        clean_id = self.assert_safe_job_id(job_id)
        video_dir = self.get_job_video_dir(job_id)
        if video_dir.exists():
            shutil.rmtree(video_dir, ignore_errors=True)


video_storage_manager = VideoStorageManager()
