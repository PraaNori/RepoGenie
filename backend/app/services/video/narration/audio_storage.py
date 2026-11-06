"""
Audio Asset Storage Manager (Milestone 5, Phase 5.4).

Manages storage, validation, atomic writes, duration measurement, and retrieval
of narration audio files isolated per job under storage/jobs/{job_id}/audio/.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class AudioAssetStorageManager:
    """Manages audio file storage, atomic writes, and duration extraction per job."""

    def __init__(self, base_storage_dir: Optional[str] = None):
        self._custom_base = base_storage_dir

    @property
    def base_dir(self) -> Path:
        """Base storage directory resolved safely."""
        if self._custom_base:
            p = Path(self._custom_base).resolve()
        else:
            p = settings.storage_path
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_job_audio_dir(self, job_id: str) -> Path:
        """
        Returns the resolved job-specific audio directory under storage/jobs/{job_id}/audio/.
        Enforces strict path isolation and traversal defense.
        """
        if not job_id or ".." in job_id or "/" in job_id or "\\" in job_id:
            raise ValueError(f"Unsafe job_id: '{job_id}'")

        audio_dir = (self.base_dir / "jobs" / job_id / "audio").resolve()
        # Verify the resolved path is strictly within the base storage directory
        if not str(audio_dir).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected: {audio_dir} is outside {self.base_dir}")

        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir

    def get_audio_path(self, job_id: str, asset_id: str, format: str = "mp3") -> Path:
        """Returns the canonical file path for an audio asset."""
        if not asset_id or not SAFE_FILENAME_RE.match(asset_id):
            raise ValueError(f"Unsafe or invalid asset_id: '{asset_id}'")
        clean_ext = format.lower().strip(".")
        filename = f"{asset_id}.{clean_ext}"
        return self.get_job_audio_dir(job_id) / filename

    def get_relative_audio_path(self, job_id: str, asset_id: str, format: str = "mp3") -> str:
        """Returns the internal relative path safe for serialization in API schemas."""
        clean_ext = format.lower().strip(".")
        return f"jobs/{job_id}/audio/{asset_id}.{clean_ext}"

    def audio_file_exists(self, job_id: str, asset_id: str, format: str = "mp3") -> bool:
        """Checks whether the audio file exists and is non-empty."""
        try:
            path = self.get_audio_path(job_id, asset_id, format)
            return path.is_file() and path.stat().st_size > 0
        except ValueError:
            return False

    def validate_audio_bytes(self, data: bytes, format: str = "mp3") -> bool:
        """
        Validates that binary data represents genuine audio.
        For MP3: verifies ID3 tag or MPEG audio frame sync word (0xFF + high 3 bits).
        """
        if not data or len(data) < 16:
            return False

        fmt = format.lower().strip(".")
        if fmt == "mp3":
            # Check ID3v2 header
            if data[:3] == b"ID3":
                return True
            # Scan first 4096 bytes for an MPEG frame sync word (11 bits set: 0xFF followed by 0xE0-0xFF)
            search_len = min(len(data), 4096)
            for i in range(search_len - 1):
                if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                    return True
            return False

        # Fallback check for non-empty bytes
        return len(data) > 0

    def save_audio(
        self,
        job_id: str,
        asset_id: str,
        audio_bytes: bytes,
        format: str = "mp3",
    ) -> Path:
        """
        Atomically writes audio bytes to disk after validating audio content.
        Uses a temporary file in the destination folder and renames it.
        """
        if not self.validate_audio_bytes(audio_bytes, format=format):
            raise ValueError(f"Invalid or corrupt audio content for asset '{asset_id}' ({len(audio_bytes)} bytes)")

        target_path = self.get_audio_path(job_id, asset_id, format)
        parent_dir = target_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file then rename
        temp_filename = f".tmp_{uuid.uuid4().hex}_{target_path.name}"
        temp_path = parent_dir / temp_filename

        try:
            with open(temp_path, "wb") as f:
                f.write(audio_bytes)
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

    def read_audio(self, job_id: str, asset_id: str, format: str = "mp3") -> bytes:
        """Reads audio bytes from disk."""
        path = self.get_audio_path(job_id, asset_id, format)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Audio asset '{asset_id}' not found for job '{job_id}'.")
        return path.read_bytes()

    def delete_job_audio(self, job_id: str) -> None:
        """Safely removes all stored audio assets for a job."""
        try:
            audio_dir = self.get_job_audio_dir(job_id)
            if audio_dir.exists() and audio_dir.is_dir():
                shutil.rmtree(audio_dir)
        except Exception as e:
            logger.warning("Error cleaning up audio directory for job %s: %s", job_id, e)

    def save_audio_metadata(self, job_id: str, asset_id: str, metadata: Dict[str, Any]) -> None:
        """Stores a JSON sidecar file alongside the audio asset for cache validation."""
        if not asset_id or not SAFE_FILENAME_RE.match(asset_id):
            raise ValueError(f"Unsafe or invalid asset_id: '{asset_id}'")
        meta_path = self.get_job_audio_dir(job_id) / f"{asset_id}.meta.json"
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f)
        except Exception as e:
            logger.warning("Failed to write audio metadata for %s: %s", asset_id, e)

    def get_audio_metadata(self, job_id: str, asset_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the JSON sidecar metadata for an audio asset if it exists."""
        if not asset_id or not SAFE_FILENAME_RE.match(asset_id):
            return None
        try:
            meta_path = self.get_job_audio_dir(job_id) / f"{asset_id}.meta.json"
            if meta_path.is_file():
                with open(meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return None
        return None

    def measure_audio_duration(self, file_path: Path) -> float:
        """
        Measures actual audio duration in seconds.
        Attempts ffprobe first if installed; otherwise uses a robust pure-Python MP3 parser.
        """
        if not file_path.is_file() or file_path.stat().st_size == 0:
            return 0.0

        # 1. Try ffprobe if available
        ffprobe_bin = shutil.which("ffprobe")
        if ffprobe_bin:
            try:
                cmd = [
                    ffprobe_bin,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ]
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                if proc.returncode == 0 and proc.stdout.strip():
                    dur = float(proc.stdout.strip())
                    if dur > 0.0:
                        return round(dur, 2)
            except Exception as e:
                logger.debug("ffprobe execution failed, falling back to pure-Python parser: %s", e)

        # 2. Pure-Python MP3 duration parser
        try:
            data = file_path.read_bytes()
            dur = self.parse_mp3_duration_from_bytes(data)
            if dur > 0.0:
                return round(dur, 2)
        except Exception as e:
            logger.warning("Pure-Python MP3 parser failed on %s: %s", file_path, e)

        # Fallback estimation for 128kbps MP3 if structure is obscure
        size = file_path.stat().st_size
        return round(size / 16000.0, 2) if size > 0 else 0.0

    @staticmethod
    def parse_mp3_duration_from_bytes(data: bytes) -> float:
        """
        Parses MPEG Audio frames from raw bytes to calculate exact playback duration.
        Accounts for ID3v2 headers, MPEG-1/2/2.5 Layer III bitrates, samplerates, and padding.
        """
        size = len(data)
        if size < 10:
            return 0.0

        pos = 0
        # Skip ID3v2 tag if present
        if data[:3] == b"ID3" and size >= 10:
            tag_size = (
                ((data[6] & 0x7F) << 21)
                | ((data[7] & 0x7F) << 14)
                | ((data[8] & 0x7F) << 7)
                | (data[9] & 0x7F)
            )
            pos = min(10 + tag_size, size)

        # MPEG Bitrate and Samplerate lookup tables
        BITRATES_MPEG1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        BITRATES_MPEG2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
        SAMPLERATES_MPEG1 = [44100, 48000, 32000, 0]
        SAMPLERATES_MPEG2 = [22050, 24000, 16000, 0]
        SAMPLERATES_MPEG25 = [11025, 12000, 8000, 0]

        total_samples = 0
        current_samplerate = 44100
        frames_parsed = 0

        while pos + 4 <= size:
            b0, b1 = data[pos], data[pos + 1]
            # MPEG Sync Word: 11 bits set (0xFF followed by 0xE0..0xFF)
            if b0 == 0xFF and (b1 & 0xE0) == 0xE0:
                ver_bits = (b1 >> 3) & 0x03
                layer_bits = (b1 >> 1) & 0x03

                # Layer III is bits == 1 (01)
                if layer_bits == 1:
                    b2 = data[pos + 2]
                    br_idx = (b2 >> 4) & 0x0F
                    sr_idx = (b2 >> 2) & 0x03
                    padding = (b2 >> 1) & 0x01

                    if ver_bits == 3:  # MPEG 1
                        br = BITRATES_MPEG1_L3[br_idx] * 1000
                        sr = SAMPLERATES_MPEG1[sr_idx]
                        samples_per_frame = 1152
                        frame_len = (144 * br // sr) + padding if (br > 0 and sr > 0) else 0
                    elif ver_bits in (0, 2):  # MPEG 2 (2) or MPEG 2.5 (0)
                        br = BITRATES_MPEG2_L3[br_idx] * 1000
                        sr = SAMPLERATES_MPEG2[sr_idx] if ver_bits == 2 else SAMPLERATES_MPEG25[sr_idx]
                        samples_per_frame = 576
                        frame_len = (72 * br // sr) + padding if (br > 0 and sr > 0) else 0
                    else:
                        frame_len = 0

                    if frame_len > 4 and sr > 0:
                        # Check for Xing / Info VBR header in first frame
                        if frames_parsed == 0:
                            # Xing header can appear at offset 36 (stereo) or 21 (mono) after 4-byte frame header
                            for xing_off in (pos + 4 + 32, pos + 4 + 17):
                                if xing_off + 8 <= size:
                                    tag = data[xing_off : xing_off + 4]
                                    if tag in (b"Xing", b"Info"):
                                        flags = int.from_bytes(data[xing_off + 4 : xing_off + 8], "big")
                                        if flags & 0x01 and xing_off + 12 <= size:
                                            total_vbr_frames = int.from_bytes(data[xing_off + 8 : xing_off + 12], "big")
                                            if total_vbr_frames > 0:
                                                return (total_vbr_frames * samples_per_frame) / sr

                        total_samples += samples_per_frame
                        current_samplerate = sr
                        frames_parsed += 1
                        pos += frame_len
                        continue

            pos += 1

        if current_samplerate > 0 and total_samples > 0:
            return total_samples / current_samplerate

        return 0.0


# Default global instance
audio_storage_manager = AudioAssetStorageManager()
