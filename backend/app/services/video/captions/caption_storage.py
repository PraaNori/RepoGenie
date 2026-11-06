"""
Caption Asset Storage Manager (Milestone 5, Phase 5.5).

Provides isolated, path-safe, atomic storage for scene and full-video
subtitle files (.srt and .vtt) under storage/jobs/{job_id}/captions/.
Guarantees directory containment, validates file syntax before writing,
and provides cleanup primitives.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import shutil
import uuid
from typing import Optional

from app.core.config import settings
from .formatter import validate_srt_content, validate_vtt_content

logger = logging.getLogger(__name__)

SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class CaptionAssetStorageManager:
    """Manages disk persistence and retrieval of caption files (.srt and .vtt)."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = (base_dir or settings.storage_path).resolve()

    def get_job_captions_dir(self, job_id: str) -> Path:
        """Returns the canonical directory for a job's caption assets."""
        if not job_id or not SAFE_FILENAME_RE.match(job_id):
            raise ValueError(f"Invalid or unsafe job_id: '{job_id}'")

        captions_dir = (self.base_dir / "jobs" / job_id / "captions").resolve()
        if not str(captions_dir).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected: {captions_dir} is outside {self.base_dir}")

        captions_dir.mkdir(parents=True, exist_ok=True)
        return captions_dir

    def get_caption_path(self, job_id: str, asset_id: str, format: str = "srt") -> Path:
        """Returns the absolute file path for a caption asset."""
        if not asset_id or not SAFE_FILENAME_RE.match(asset_id):
            raise ValueError(f"Unsafe or invalid asset_id: '{asset_id}'")

        clean_ext = format.lower().strip(".")
        if clean_ext not in ("srt", "vtt"):
            raise ValueError(f"Unsupported caption format: '{format}'. Must be 'srt' or 'vtt'.")

        filename = f"{asset_id}.{clean_ext}"
        return self.get_job_captions_dir(job_id) / filename

    def get_relative_caption_path(self, job_id: str, asset_id: str, format: str = "srt") -> str:
        """Returns a safe relative internal path for schema responses."""
        clean_ext = format.lower().strip(".")
        return f"jobs/{job_id}/captions/{asset_id}.{clean_ext}"

    def caption_file_exists(self, job_id: str, asset_id: str, format: str = "srt") -> bool:
        """Checks if the caption file exists and is non-empty."""
        try:
            path = self.get_caption_path(job_id, asset_id, format)
            return path.is_file() and path.stat().st_size > 0
        except ValueError:
            return False

    def save_caption_file(
        self,
        job_id: str,
        asset_id: str,
        content: str,
        format: str = "srt",
    ) -> Path:
        """
        Atomically writes subtitle content (UTF-8) to disk after syntactic validation.
        """
        clean_ext = format.lower().strip(".")
        if clean_ext == "srt":
            if not validate_srt_content(content):
                raise ValueError(f"Invalid SubRip (.srt) syntax for asset '{asset_id}'")
        elif clean_ext == "vtt":
            if not validate_vtt_content(content):
                raise ValueError(f"Invalid WebVTT (.vtt) syntax for asset '{asset_id}'")
        else:
            raise ValueError(f"Unsupported caption format '{format}'")

        target_path = self.get_caption_path(job_id, asset_id, format)
        parent_dir = target_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        temp_filename = f".tmp_{uuid.uuid4().hex}_{target_path.name}"
        temp_path = parent_dir / temp_filename

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        return target_path

    def read_caption_file(self, job_id: str, asset_id: str, format: str = "srt") -> str:
        """Reads subtitle text from disk as UTF-8 string."""
        path = self.get_caption_path(job_id, asset_id, format)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Caption file '{asset_id}.{format}' not found for job '{job_id}'.")
        return path.read_text(encoding="utf-8")

    def delete_job_captions(self, job_id: str) -> None:
        """Removes all stored caption files for a job."""
        try:
            captions_dir = self.get_job_captions_dir(job_id)
            if captions_dir.exists() and captions_dir.is_dir():
                shutil.rmtree(captions_dir)
        except Exception as e:
            logger.warning("Error cleaning up caption directory for job %s: %s", job_id, e)


# Global singleton instance
caption_storage_manager = CaptionAssetStorageManager()
