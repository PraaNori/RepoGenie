"""
Video Output Storage Manager (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from ....core.config import settings
from .exceptions import VideoStorageError
from .schemas import SAFE_ID_REGEX

logger = logging.getLogger(__name__)


class VideoStorageManager:
    """Manages isolated video file storage per job with atomic finalization and traversal defense."""

    def __init__(self, base_storage_dir: Optional[Path] = None):
        self._custom_base = base_storage_dir

    @property
    def base_dir(self) -> Path:
        if self._custom_base:
            return Path(self._custom_base).resolve()
        return settings.storage_path.resolve()

    def assert_safe_job_id(self, job_id: str) -> str:
        """Validates job ID syntax against directory traversal attempts."""
        if not job_id or not SAFE_ID_REGEX.match(job_id):
            raise VideoStorageError(f"Security: Invalid or prohibited job ID '{job_id}'")
        return job_id

    def assert_safe_path(self, path: Path) -> Path:
        """Ensures that target path is safely contained within base storage directory."""
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.base_dir)):
            raise VideoStorageError(f"Security: Path traversal attempt outside storage root: {resolved}")
        return resolved

    def get_job_video_dir(self, job_id: str) -> Path:
        """Returns the isolated video storage directory for a specific job: storage/jobs/{job_id}/video/"""
        clean_id = self.assert_safe_job_id(job_id)
        video_dir = self.base_dir / "jobs" / clean_id / "video"
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

    def finalize_render_output(
        self,
        job_id: str,
        temp_render_path: Path,
        target_filename: str = "final_video.mp4",
        overwrite: bool = False,
    ) -> Path:
        """
        Atomically renames temp_render_path to target_filename after validating
        that the temp file exists and has non-zero size.
        """
        safe_temp = self.assert_safe_path(temp_render_path)
        if not safe_temp.exists() or not safe_temp.is_file():
            raise VideoStorageError(f"Rendered temporary file does not exist: {safe_temp}")

        size = safe_temp.stat().st_size
        if size == 0:
            self.cleanup_file(safe_temp)
            raise VideoStorageError(f"Rendered video output is empty (0 bytes): {safe_temp}")

        target_path = self.get_final_output_path(job_id, target_filename)
        if target_path.exists() and not overwrite:
            raise VideoStorageError(f"Target video output already exists: {target_path}. Pass overwrite=True to replace.")

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
        video_dir = self.base_dir / "jobs" / clean_id / "video"
        if video_dir.exists():
            shutil.rmtree(video_dir, ignore_errors=True)


video_storage_manager = VideoStorageManager()
