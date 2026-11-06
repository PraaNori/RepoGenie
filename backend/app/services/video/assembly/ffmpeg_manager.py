"""
FFmpeg Executable & Capability Manager (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import List, Optional

from ....core.config import settings
from .exceptions import FFmpegNotFoundError
from .process_runner import run_process_sync
from .schemas import FFmpegExecutableStatus

logger = logging.getLogger(__name__)

_VERSION_REGEX = re.compile(r"ffmpeg version (\S+)", re.IGNORECASE)
_ENCODER_LINE_REGEX = re.compile(r"^\s*[VAD][F.][S.][X.][B.][D.]\s+(\S+)\s+(.+)$")


class FFmpegManager:
    """Manages FFmpeg binary detection, version discovery, and codec inspection."""

    def __init__(self, binary_path: Optional[str] = None):
        self._binary_name = binary_path or getattr(settings, "FFMPEG_BINARY", "ffmpeg")
        self._cached_status: Optional[FFmpegExecutableStatus] = None

    def resolve_binary(self) -> Optional[Path]:
        """Resolves the executable path of the configured FFmpeg binary."""
        # 1. Direct path check
        direct = Path(self._binary_name)
        if direct.is_file() and direct.exists():
            return direct.resolve()

        # 2. PATH resolution via shutil.which
        resolved = shutil.which(self._binary_name)
        if resolved:
            return Path(resolved).resolve()

        return None

    def get_status(self, refresh: bool = False) -> FFmpegExecutableStatus:
        """Inspects FFmpeg availability, version, and codecs."""
        if self._cached_status and not refresh:
            return self._cached_status

        bin_path = self.resolve_binary()
        if not bin_path:
            status = FFmpegExecutableStatus(
                name="ffmpeg",
                is_available=False,
                executable_path=None,
                version=None,
                codecs_supported=[],
                error=f"FFmpeg binary '{self._binary_name}' was not found in system PATH. Install ffmpeg to enable video assembly.",
            )
            self._cached_status = status
            return status

        # Discover version
        try:
            ret, stdout, stderr = run_process_sync([str(bin_path), "-version"], timeout_seconds=10.0)
            output = stdout or stderr
            version_match = _VERSION_REGEX.search(output)
            version_str = version_match.group(1) if version_match else "unknown"
        except Exception as exc:
            status = FFmpegExecutableStatus(
                name="ffmpeg",
                is_available=False,
                executable_path=str(bin_path),
                version=None,
                codecs_supported=[],
                error=f"Failed to query FFmpeg version: {exc}",
            )
            self._cached_status = status
            return status

        # Discover supported encoders/codecs
        codecs: List[str] = []
        try:
            ret, stdout, stderr = run_process_sync([str(bin_path), "-encoders"], timeout_seconds=10.0)
            for line in stdout.splitlines():
                m = _ENCODER_LINE_REGEX.match(line)
                if m:
                    codecs.append(m.group(1))
        except Exception as exc:
            logger.warning("Could not query FFmpeg encoders: %s", exc)

        status = FFmpegExecutableStatus(
            name="ffmpeg",
            is_available=True,
            executable_path=str(bin_path),
            version=version_str,
            codecs_supported=sorted(set(codecs)),
            error=None,
        )
        self._cached_status = status
        return status

    def assert_available(self) -> Path:
        """Asserts FFmpeg is available on the system; raises FFmpegNotFoundError if missing."""
        status = self.get_status()
        if not status.is_available or not status.executable_path:
            raise FFmpegNotFoundError(status.error or "FFmpeg executable is not available on this system.")
        return Path(status.executable_path)


ffmpeg_manager = FFmpegManager()
