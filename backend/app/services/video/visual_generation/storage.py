"""
Storage manager for Milestone 5, Phase 5.1: Visual Generation Foundation.

Enforces:
- Isolated job-specific directory structure: storage/jobs/{job_id}/visuals/
- Strict path traversal prevention (rejecting '..', absolute paths, backslashes, control characters)
- Safe relative path resolution for public API responses (never leaking local machine absolute paths)
- Atomic deletion of old visual assets when an educational storyboard is invalidated
"""

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Union

from ....core.config import settings

logger = logging.getLogger(__name__)

_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+$")


class PathTraversalError(ValueError):
    """Raised when an operation attempts to access files outside the isolated storage boundary."""


class VisualAssetStorageManager:
    """Manages the isolated file storage and path resolution for job visual assets."""

    def __init__(self, base_storage_dir: Optional[Path] = None):
        self._base_storage_dir = base_storage_dir

    @property
    def base_dir(self) -> Path:
        """Resolves root storage directory from settings."""
        if self._base_storage_dir:
            return self._base_storage_dir.resolve()
        return settings.storage_path.resolve()

    @property
    def jobs_dir(self) -> Path:
        """Root directory for isolated job storage."""
        d = self.base_dir / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def validate_job_id(self, job_id: str) -> str:
        """Validates job_id to prevent directory traversal."""
        if not job_id or not isinstance(job_id, str):
            raise PathTraversalError("job_id must be a non-empty string.")
        job_id = job_id.strip()
        if not _ID_PATTERN.match(job_id):
            raise PathTraversalError(
                f"Invalid job_id '{job_id}': only alphanumeric characters, dashes, and underscores are allowed."
            )
        return job_id

    def validate_filename(self, filename: str) -> str:
        """Validates filename to prevent directory traversal and invalid extensions."""
        if not filename or not isinstance(filename, str):
            raise PathTraversalError("filename must be a non-empty string.")
        filename = filename.strip()
        if "/" in filename or "\\" in filename or ".." in filename:
            raise PathTraversalError(f"Prohibited path traversal character in filename '{filename}'.")
        if not _FILENAME_PATTERN.match(filename):
            raise PathTraversalError(
                f"Invalid filename '{filename}': must match standard name.ext pattern without path separators."
            )
        return filename

    def get_job_visuals_dir(self, job_id: str, create: bool = True) -> Path:
        """
        Returns the absolute Path to the isolated visuals directory for job_id:
        <storage_path>/jobs/<job_id>/visuals/
        """
        safe_job_id = self.validate_job_id(job_id)
        visuals_dir = (self.jobs_dir / safe_job_id / "visuals").resolve()

        # Enforce that visuals_dir is strictly inside jobs_dir
        try:
            visuals_dir.relative_to(self.jobs_dir)
        except ValueError as exc:
            raise PathTraversalError(
                f"Resolved visuals directory '{visuals_dir}' escapes jobs boundary '{self.jobs_dir}'."
            ) from exc

        if create:
            visuals_dir.mkdir(parents=True, exist_ok=True)
        return visuals_dir

    def get_relative_storage_dir(self, job_id: str) -> str:
        """Returns relative storage directory string: 'jobs/{job_id}/visuals'."""
        safe_job_id = self.validate_job_id(job_id)
        return f"jobs/{safe_job_id}/visuals"

    def get_relative_asset_path(self, job_id: str, filename: str) -> str:
        """Returns clean relative storage path: 'jobs/{job_id}/visuals/{filename}'."""
        safe_job_id = self.validate_job_id(job_id)
        safe_filename = self.validate_filename(filename)
        return f"jobs/{safe_job_id}/visuals/{safe_filename}"

    def get_asset_file_path(self, job_id: str, filename: str, must_exist: bool = False) -> Path:
        """
        Resolves the absolute path to an asset file and verifies boundary isolation.
        """
        visuals_dir = self.get_job_visuals_dir(job_id, create=False)
        safe_filename = self.validate_filename(filename)
        file_path = (visuals_dir / safe_filename).resolve()

        try:
            file_path.relative_to(visuals_dir)
        except ValueError as exc:
            raise PathTraversalError(
                f"Resolved asset path '{file_path}' escapes isolated visuals directory '{visuals_dir}'."
            ) from exc

        if must_exist and not file_path.is_file():
            raise FileNotFoundError(f"Visual asset file '{safe_filename}' not found for job '{job_id}'.")

        return file_path

    def asset_file_exists(self, job_id: str, filename: str) -> bool:
        """Checks if an asset file currently exists on disk."""
        try:
            path = self.get_asset_file_path(job_id, filename, must_exist=False)
            return path.is_file()
        except (PathTraversalError, ValueError):
            return False

    def save_asset_content(
        self,
        job_id: str,
        filename: str,
        content: Union[str, bytes],
    ) -> Path:
        """
        Safely writes asset content (SVG, PNG bytes, or JSON markup) to disk.
        """
        visuals_dir = self.get_job_visuals_dir(job_id, create=True)
        safe_filename = self.validate_filename(filename)
        target_path = (visuals_dir / safe_filename).resolve()

        try:
            target_path.relative_to(visuals_dir)
        except ValueError as exc:
            raise PathTraversalError(
                f"Target write path '{target_path}' escapes isolated visuals directory."
            ) from exc

        if isinstance(content, str):
            target_path.write_text(content, encoding="utf-8")
        else:
            target_path.write_bytes(content)

        logger.debug("Saved visual asset to %s (%d bytes)", target_path, len(content))
        return target_path

    def read_asset_content(self, job_id: str, filename: str) -> bytes:
        """Reads raw binary content of a visual asset file."""
        file_path = self.get_asset_file_path(job_id, filename, must_exist=True)
        return file_path.read_bytes()

    def delete_job_visuals(self, job_id: str) -> bool:
        """
        Deletes the entire visuals directory for job_id.
        Called on storyboard invalidation to ensure stale assets are never served.
        """
        safe_job_id = self.validate_job_id(job_id)
        visuals_dir = (self.jobs_dir / safe_job_id / "visuals").resolve()
        try:
            visuals_dir.relative_to(self.jobs_dir)
        except ValueError as exc:
            raise PathTraversalError("Invalid directory deletion path.") from exc

        if visuals_dir.is_dir():
            shutil.rmtree(visuals_dir)
            logger.info("Successfully deleted stale visual assets for job %s", job_id)
            return True
        return False


# Singleton instance
visual_storage_manager = VisualAssetStorageManager()
