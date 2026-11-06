"""
FFprobe Executable & Media Probing Manager (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....core.config import settings
from .exceptions import FFprobeNotFoundError, MediaProbeError
from .process_runner import run_process_sync
from .schemas import FFmpegExecutableStatus, MediaProbeResult, MediaStreamProbe

logger = logging.getLogger(__name__)

_VERSION_REGEX = re.compile(r"ffprobe version (\S+)", re.IGNORECASE)


class FFprobeManager:
    """Manages FFprobe binary detection, version discovery, and media container/stream probing."""

    def __init__(self, binary_path: Optional[str] = None):
        self._binary_name = binary_path or getattr(settings, "FFPROBE_BINARY", "ffprobe")
        self._cached_status: Optional[FFmpegExecutableStatus] = None

    def resolve_binary(self) -> Optional[Path]:
        """Resolves the executable path of the configured FFprobe binary."""
        direct = Path(self._binary_name)
        if direct.is_file() and direct.exists():
            return direct.resolve()

        resolved = shutil.which(self._binary_name)
        if resolved:
            return Path(resolved).resolve()

        return None

    def get_status(self, refresh: bool = False) -> FFmpegExecutableStatus:
        """Inspects FFprobe availability and version."""
        if self._cached_status and not refresh:
            return self._cached_status

        bin_path = self.resolve_binary()
        if not bin_path:
            status = FFmpegExecutableStatus(
                name="ffprobe",
                is_available=False,
                executable_path=None,
                version=None,
                codecs_supported=[],
                error=f"FFprobe binary '{self._binary_name}' was not found in system PATH. Install ffprobe for media inspection.",
            )
            self._cached_status = status
            return status

        try:
            ret, stdout, stderr = run_process_sync([str(bin_path), "-version"], timeout_seconds=10.0)
            output = stdout or stderr
            version_match = _VERSION_REGEX.search(output)
            version_str = version_match.group(1) if version_match else "unknown"

            status = FFmpegExecutableStatus(
                name="ffprobe",
                is_available=True,
                executable_path=str(bin_path),
                version=version_str,
                codecs_supported=[],
                error=None,
            )
        except Exception as exc:
            status = FFmpegExecutableStatus(
                name="ffprobe",
                is_available=False,
                executable_path=str(bin_path),
                version=None,
                codecs_supported=[],
                error=f"Failed to query FFprobe version: {exc}",
            )

        self._cached_status = status
        return status

    def assert_available(self) -> Path:
        """Asserts FFprobe is available; raises FFprobeNotFoundError if missing."""
        status = self.get_status()
        if not status.is_available or not status.executable_path:
            raise FFprobeNotFoundError(status.error or "FFprobe executable is not available on this system.")
        return Path(status.executable_path)

    def probe_media_file(self, media_path: Path) -> MediaProbeResult:
        """
        Executes ffprobe against media_path and returns a parsed MediaProbeResult.
        Inspects format metadata and all video/audio streams.
        """
        bin_path = self.assert_available()
        resolved_media = media_path.resolve()

        if not resolved_media.exists() or not resolved_media.is_file():
            raise MediaProbeError(f"Target media file does not exist: {resolved_media}")

        args = [
            str(bin_path),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(resolved_media),
        ]

        ret_code, stdout, stderr = run_process_sync(args, timeout_seconds=20.0)
        if ret_code != 0:
            raise MediaProbeError(f"ffprobe failed with exit code {ret_code}: {stderr[:300]}")

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as jde:
            raise MediaProbeError(f"Failed to parse ffprobe JSON output: {jde}") from jde

        format_info = data.get("format", {})
        streams_info = data.get("streams", [])

        format_name = format_info.get("format_name", "unknown")
        duration_seconds = 0.0
        try:
            duration_seconds = float(format_info.get("duration", 0.0))
        except (ValueError, TypeError):
            pass

        size_bytes = 0
        try:
            size_bytes = int(format_info.get("size", 0))
        except (ValueError, TypeError):
            pass

        bit_rate = None
        try:
            if format_info.get("bit_rate"):
                bit_rate = int(format_info["bit_rate"])
        except (ValueError, TypeError):
            pass

        parsed_streams: List[MediaStreamProbe] = []
        primary_video: Optional[MediaStreamProbe] = None
        primary_audio: Optional[MediaStreamProbe] = None

        for stream in streams_info:
            stream_idx = stream.get("index", 0)
            codec_type = stream.get("codec_type", "unknown").lower()
            codec_name = stream.get("codec_name", "unknown")

            width = stream.get("width")
            height = stream.get("height")
            pix_fmt = stream.get("pix_fmt")

            # Parse frame rate from fraction e.g. "30/1" or "2997/100"
            fps = None
            r_fps = stream.get("r_frame_rate", "")
            if "/" in r_fps:
                try:
                    num, den = r_fps.split("/")
                    f_num, f_den = float(num), float(den)
                    if f_den > 0:
                        fps = round(f_num / f_den, 2)
                except (ValueError, ZeroDivisionError):
                    pass

            sample_rate = None
            if stream.get("sample_rate"):
                try:
                    sample_rate = int(stream["sample_rate"])
                except ValueError:
                    pass

            channels = stream.get("channels")
            channel_layout = stream.get("channel_layout")

            stream_dur = None
            if stream.get("duration"):
                try:
                    stream_dur = float(stream["duration"])
                except ValueError:
                    pass

            stream_bit_rate = None
            if stream.get("bit_rate"):
                try:
                    stream_bit_rate = int(stream["bit_rate"])
                except ValueError:
                    pass

            parsed_stream = MediaStreamProbe(
                index=stream_idx,
                codec_type=codec_type,
                codec_name=codec_name,
                width=width,
                height=height,
                fps=fps,
                pixel_format=pix_fmt,
                sample_rate=sample_rate,
                channels=channels,
                channel_layout=channel_layout,
                duration_seconds=stream_dur,
                bit_rate=stream_bit_rate,
            )
            parsed_streams.append(parsed_stream)

            if codec_type == "video" and not primary_video:
                primary_video = parsed_stream
            elif codec_type == "audio" and not primary_audio:
                primary_audio = parsed_stream

        return MediaProbeResult(
            format_name=format_name,
            duration_seconds=round(duration_seconds, 3),
            size_bytes=size_bytes,
            bit_rate=bit_rate,
            streams=parsed_streams,
            has_video=primary_video is not None,
            has_audio=primary_audio is not None,
            primary_video_stream=primary_video,
            primary_audio_stream=primary_audio,
        )


ffprobe_manager = FFprobeManager()
