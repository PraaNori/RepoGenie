"""
Assembly Preflight Validator (Milestone 5, Phase 5.6).

Performs physical disk inspection, raster and vector image validation,
cross-asset synchronization, and deep subtitle cue timeline auditing for video assembly:
1. Validates physical file existence, non-empty size, and file-format integrity:
   - SVG: XML well-formedness, <svg> root element, 1920x1080 viewBox or 16:9 aspect ratio.
   - Raster (PNG, JPEG, WebP): genuine image decoding with PIL/Pillow, decompression bomb
     protection (MAX_IMAGE_PIXELS), positive dimensions, bounds limits, aspect ratio (16:9),
     and rejection of truncated/corrupt image data.
   - Audio (MP3): valid sync word / ID3 magic bytes, zero-byte rejection, duration measurement.
   - Captions (SRT, WebVTT): syntax validation, non-empty subtitle blocks.
2. Prevents directory traversal by enforcing storage root boundaries.
3. Subtitle Cue-Level Consistency:
   - Compares per-scene SRT/VTT cues against full-video SRT/VTT cues.
   - Verifies per-scene timestamps are relative to their own audio.
   - Verifies full-video timestamps are cumulative based on scene timeline offsets.
   - Ensures silent scenes preserve their timeline duration without generating spurious cues.
   - Verifies full-video SRT and WebVTT tracks agree with each other.
   - Detects missing, duplicated, or misaligned subtitle cues.
4. Distinguishes failed narration from legitimately silent scenes (failed scenes block readiness).
5. Generates an AssemblyReadinessReport with BLOCKING issues and advisory WARNINGS.
"""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from app.core.config import settings
from .schemas import (
    AssemblyAssetReference,
    AssemblyIssueSeverity,
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    AssemblyValidationIssue,
)
from ..captions.formatter import (
    SRT_TIME_RE,
    VTT_TIME_RE,
    validate_srt_content,
    validate_vtt_content,
)
from ..narration.audio_storage import audio_storage_manager

logger = logging.getLogger(__name__)

FLOAT_TOLERANCE_SECONDS = 0.05
MP3_SYNC_PATTERNS = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
MAX_RASTER_PIXELS = 50_000_000  # 50 Megapixels max decompression bomb threshold
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB max file size


def srt_timestamp_to_seconds(ts: str) -> float:
    """Converts SRT timestamp HH:MM:SS,mmm to floating-point seconds."""
    parts = ts.strip().split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    sec_parts = parts[2].split(",")
    seconds = int(sec_parts[0])
    millis = int(sec_parts[1])
    return hours * 3600.0 + minutes * 60.0 + seconds + millis / 1000.0


def vtt_timestamp_to_seconds(ts: str) -> float:
    """Converts WebVTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to floating-point seconds."""
    ts = ts.strip()
    parts = ts.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        sec_parts = parts[2].split(".")
        seconds = int(sec_parts[0])
        millis = int(sec_parts[1])
        return hours * 3600.0 + minutes * 60.0 + seconds + millis / 1000.0
    elif len(parts) == 2:
        minutes = int(parts[0])
        sec_parts = parts[1].split(".")
        seconds = int(sec_parts[0])
        millis = int(sec_parts[1])
        return minutes * 60.0 + seconds + millis / 1000.0
    raise ValueError(f"Invalid WebVTT timestamp format: '{ts}'")


def parse_srt_cues_from_file(file_path: Path) -> List[Tuple[float, float, str]]:
    """Extracts (start_seconds, end_seconds, text) tuples from an SRT file on disk."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []

    cues: List[Tuple[float, float, str]] = []
    blocks = content.split("\n\n")
    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            time_parts = lines[1].split("-->")
            start = srt_timestamp_to_seconds(time_parts[0].strip())
            end = srt_timestamp_to_seconds(time_parts[1].strip())
            text = " ".join(lines[2:]).strip()
            cues.append((start, end, text))
    return cues


def parse_vtt_cues_from_file(file_path: Path) -> List[Tuple[float, float, str]]:
    """Extracts (start_seconds, end_seconds, text) tuples from a WebVTT file on disk."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []

    cues: List[Tuple[float, float, str]] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            time_parts = line.split("-->")
            start_str = time_parts[0].strip()
            end_str = time_parts[1].strip().split()[0]
            start = vtt_timestamp_to_seconds(start_str)
            end = vtt_timestamp_to_seconds(end_str)
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            text = " ".join(text_lines).strip()
            cues.append((start, end, text))
        else:
            i += 1
    return cues


class AssemblyPreflightValidator:
    """Preflight validator that inspects disk assets and verifies cross-asset alignment."""

    def __init__(self, base_storage_dir: Optional[Path] = None):
        self._custom_base = base_storage_dir

    @property
    def base_dir(self) -> Path:
        if self._custom_base:
            return Path(self._custom_base).resolve()
        return settings.storage_path.resolve()

    def assert_safe_path(self, path: Path) -> Path:
        """Verifies that path is resolved within the allowed storage base directory."""
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.base_dir)):
            raise ValueError(f"Security: Path traversal attempt outside storage root: {resolved}")
        return resolved

    def validate_visual_file(self, file_path: Path) -> Tuple[bool, Optional[str], int]:
        """
        Validates that a visual asset file (SVG or raster PNG/JPEG/WEBP) exists on disk,
        is non-empty, well-formed, readable without decompression bomb risk,
        and conforms to 16:9 aspect ratio.
        """
        try:
            safe_path = self.assert_safe_path(file_path)
            if not safe_path.exists() or not safe_path.is_file():
                return False, f"File does not exist: {file_path}", 0

            file_size = safe_path.stat().st_size
            if file_size == 0:
                return False, f"File is empty (0 bytes): {file_path}", 0

            if file_size > MAX_FILE_SIZE_BYTES:
                return False, f"Visual file size ({file_size} bytes) exceeds maximum limit of 50MB", file_size

            ext = safe_path.suffix.lower()

            if ext == ".svg":
                return self._validate_svg_file(safe_path, file_size)
            elif ext in (".png", ".jpg", ".jpeg", ".webp"):
                return self._validate_raster_file(safe_path, ext, file_size)
            else:
                return False, f"Unsupported visual asset format '{ext}'. Supported formats: .svg, .png, .jpg, .jpeg, .webp", file_size
        except Exception as exc:
            return False, f"Failed to validate visual file: {exc}", 0

    def _validate_svg_file(self, safe_path: Path, file_size: int) -> Tuple[bool, Optional[str], int]:
        """Validates SVG XML markup, root element, and 16:9 viewBox/dimensions."""
        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            return False, "SVG content is empty", file_size

        try:
            root = ET.fromstring(content)
        except ET.ParseError as pe:
            return False, f"Malformed SVG XML: {pe}", file_size

        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if tag.lower() != "svg":
            return False, f"Root element is <{root.tag}> instead of <svg>", file_size

        view_box = root.attrib.get("viewBox", "").strip()
        width = root.attrib.get("width", "").strip()
        height = root.attrib.get("height", "").strip()

        if view_box:
            vb_parts = view_box.split()
            if len(vb_parts) == 4:
                try:
                    vb_w = float(vb_parts[2])
                    vb_h = float(vb_parts[3])
                    if vb_w > 0 and vb_h > 0:
                        ratio = vb_w / vb_h
                        if not math.isclose(ratio, 16.0 / 9.0, rel_tol=0.05):
                            return False, f"SVG viewBox {view_box} aspect ratio is {ratio:.2f}, expected 16:9", file_size
                except ValueError:
                    return False, f"Invalid numeric values in SVG viewBox '{view_box}'", file_size
        elif width and height:
            try:
                w = float(width.replace("px", ""))
                h = float(height.replace("px", ""))
                if w > 0 and h > 0:
                    ratio = w / h
                    if not math.isclose(ratio, 16.0 / 9.0, rel_tol=0.05):
                        return False, f"SVG dimensions {w}x{h} aspect ratio is {ratio:.2f}, expected 16:9", file_size
            except ValueError:
                return False, f"Invalid dimensions '{width}'x'{height}' in SVG", file_size
        else:
            return False, "SVG is missing both viewBox and width/height dimensions", file_size

        return True, None, file_size

    def _validate_raster_file(self, safe_path: Path, ext: str, file_size: int) -> Tuple[bool, Optional[str], int]:
        """
        Validates raster images by performing actual decompression, verifying dimensions,
        aspect ratio, and detecting decompression bombs or truncated data.
        """
        try:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = MAX_RASTER_PIXELS
        except ImportError:
            return False, "PIL/Pillow library is required for raster image validation", file_size

        try:
            import warnings
            with warnings.catch_warnings(record=True) as captured_warnings:
                warnings.simplefilter("always")

                # 1. Structural check with verify()
                with open(safe_path, "rb") as f:
                    with Image.open(f) as img:
                        detected_format = (img.format or "").upper()
                        expected_formats = {
                            ".png": "PNG",
                            ".jpg": "JPEG",
                            ".jpeg": "JPEG",
                            ".webp": "WEBP",
                        }
                        expected = expected_formats.get(ext)
                        if expected and detected_format != expected:
                            return False, f"File extension '{ext}' does not match detected image format '{detected_format}'", file_size
                        img.verify()

                # 2. Decompression and scanline check with load() (catches truncated/corrupt blocks)
                with Image.open(safe_path) as img:
                    img.load()
                    width, height = img.size

                for w in captured_warnings:
                    if issubclass(w.category, Image.DecompressionBombWarning):
                        return False, f"Decompression bomb detected: {w.message}", file_size

            if width <= 0 or height <= 0:
                return False, f"Invalid raster image dimensions: {width}x{height}", file_size

            if (width * height) > MAX_RASTER_PIXELS:
                return False, f"Decompression bomb detected: image size ({width * height} pixels) exceeds maximum limit of {MAX_RASTER_PIXELS}", file_size

            if width < 320 or height < 180:
                return False, f"Raster image dimensions {width}x{height} below minimum allowable resolution 320x180", file_size

            if width > 7680 or height > 4320:
                return False, f"Raster image dimensions {width}x{height} exceed maximum allowable 8K resolution 7680x4320", file_size

            ratio = width / height
            if not math.isclose(ratio, 16.0 / 9.0, rel_tol=0.05):
                return False, f"Raster image dimensions {width}x{height} aspect ratio is {ratio:.2f}, expected 16:9", file_size

            return True, None, file_size
        except Image.DecompressionBombError as dbe:
            return False, f"Decompression bomb detected: {dbe}", file_size
        except (OSError, SyntaxError, ValueError) as err:
            return False, f"Corrupt or truncated raster image: {err}", file_size

    def validate_audio_file(self, file_path: Path) -> Tuple[bool, Optional[str], int, float]:
        """
        Validates that an MP3 file exists, is non-empty, contains valid MP3 headers,
        and has measurable playback duration > 0.
        """
        try:
            safe_path = self.assert_safe_path(file_path)
            if not safe_path.exists() or not safe_path.is_file():
                return False, f"Audio file does not exist: {file_path}", 0, 0.0

            file_size = safe_path.stat().st_size
            if file_size == 0:
                return False, f"Audio file is empty (0 bytes): {file_path}", 0, 0.0

            # Verify MP3 sync headers / magic bytes
            with open(safe_path, "rb") as f:
                header = f.read(10)

            is_valid_mp3 = any(header.startswith(sig) for sig in MP3_SYNC_PATTERNS)
            if not is_valid_mp3:
                return False, f"File at {file_path} lacks valid MP3 header or ID3 tag", file_size, 0.0

            # Measure duration
            duration = audio_storage_manager.measure_audio_duration(safe_path)
            if duration <= 0.0:
                return False, f"Audio file duration could not be determined or is 0.0s", file_size, 0.0

            return True, None, file_size, duration
        except Exception as exc:
            return False, f"Failed to validate audio file: {exc}", 0, 0.0

    def validate_caption_file(self, file_path: Path, format: str = "srt") -> Tuple[bool, Optional[str], int]:
        """
        Validates that a subtitle file (.srt or .vtt) exists, is non-empty, and has valid syntax.
        """
        try:
            safe_path = self.assert_safe_path(file_path)
            if not safe_path.exists() or not safe_path.is_file():
                return False, f"Caption file does not exist: {file_path}", 0

            file_size = safe_path.stat().st_size
            if file_size == 0:
                return False, f"Caption file is empty (0 bytes): {file_path}", 0

            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read()

            fmt = format.lower().strip(".")
            if fmt == "srt":
                valid = validate_srt_content(content)
                if not valid:
                    return False, "Malformed SRT subtitle syntax", file_size
            elif fmt == "vtt":
                valid = validate_vtt_content(content)
                if not valid:
                    return False, "Malformed WebVTT subtitle syntax", file_size
            else:
                return False, f"Unsupported caption format '{format}'", file_size

            return True, None, file_size
        except Exception as exc:
            return False, f"Failed to validate caption file: {exc}", 0

    def evaluate_package(
        self,
        job_id: str,
        scenes: List[AssemblyScene],
        full_video_srt: Optional[AssemblyAssetReference] = None,
        full_video_vtt: Optional[AssemblyAssetReference] = None,
        additional_issues: Optional[List[AssemblyValidationIssue]] = None,
    ) -> AssemblyReadinessReport:
        """
        Audits the complete assembled package for timeline continuity, asset completeness,
        and cross-modal synchronization, including deep subtitle cue timeline comparisons.
        """
        blocking_issues: List[AssemblyValidationIssue] = []
        warnings: List[AssemblyValidationIssue] = []

        if additional_issues:
            for iss in additional_issues:
                if iss.severity == AssemblyIssueSeverity.BLOCKING:
                    blocking_issues.append(iss)
                else:
                    warnings.append(iss)

        total_scenes = len(scenes)
        ready_scenes = 0

        if total_scenes == 0:
            blocking_issues.append(
                AssemblyValidationIssue(
                    code="EMPTY_SCENE_LIST",
                    severity=AssemblyIssueSeverity.BLOCKING,
                    message="No storyboard scenes provided for assembly package.",
                )
            )
            return AssemblyReadinessReport(
                job_id=job_id,
                status=AssemblyReadinessStatus.NOT_READY,
                total_scenes=0,
                ready_scenes=0,
                total_duration_seconds=0.0,
                has_visuals=False,
                has_narration=False,
                has_captions=False,
                has_full_video_captions=False,
                blocking_issues=blocking_issues,
                warnings=warnings,
            )

        has_visuals = True
        has_narration = True
        has_captions = True

        expected_start = 0.0
        seen_scene_ids = set()
        seen_scene_numbers = set()
        all_expected_composite_cues: List[Tuple[float, float, str, int]] = []

        for idx, scene in enumerate(scenes):
            scene_blocking: List[AssemblyValidationIssue] = []
            scene_warnings: List[AssemblyValidationIssue] = []

            # 1. Unique scene ID check
            if scene.scene_id in seen_scene_ids:
                scene_blocking.append(
                    AssemblyValidationIssue(
                        code="DUPLICATE_SCENE_ID",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Duplicate scene_id detected in assembly scenes: '{scene.scene_id}'.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                    )
                )
            seen_scene_ids.add(scene.scene_id)

            # 1b. Unique scene number check
            if scene.scene_number in seen_scene_numbers:
                scene_blocking.append(
                    AssemblyValidationIssue(
                        code="DUPLICATE_SCENE_NUMBER",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Duplicate scene_number detected in assembly scenes: {scene.scene_number}.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                    )
                )
            seen_scene_numbers.add(scene.scene_number)

            # 2. Monotonic scene number check
            expected_num = idx + 1
            if scene.scene_number != expected_num:
                scene_blocking.append(
                    AssemblyValidationIssue(
                        code="SCENE_SEQUENCE_MISMATCH",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Scene index {idx} has scene_number {scene.scene_number}, expected {expected_num}.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                    )
                )

            # 3. Continuous timeline check
            if abs(scene.start_seconds - expected_start) > FLOAT_TOLERANCE_SECONDS:
                diff = scene.start_seconds - expected_start
                if diff > 0:
                    scene_warnings.append(
                        AssemblyValidationIssue(
                            code="TIMELINE_GAP",
                            severity=AssemblyIssueSeverity.WARNING,
                            message=f"Scene {scene.scene_number} has a timeline gap of {diff:.3f}s from preceding scene.",
                            scene_id=scene.scene_id,
                            scene_number=scene.scene_number,
                            details={"expected_start": expected_start, "actual_start": scene.start_seconds},
                        )
                    )
                else:
                    scene_blocking.append(
                        AssemblyValidationIssue(
                            code="TIMELINE_OVERLAP",
                            severity=AssemblyIssueSeverity.BLOCKING,
                            message=f"Scene {scene.scene_number} overlaps preceding scene by {abs(diff):.3f}s.",
                            scene_id=scene.scene_id,
                            scene_number=scene.scene_number,
                            details={"expected_start": expected_start, "actual_start": scene.start_seconds},
                        )
                    )

            expected_start = scene.end_seconds

            # 4. Visual asset validation
            if not scene.visual_asset:
                has_visuals = False
                scene_blocking.append(
                    AssemblyValidationIssue(
                        code="MISSING_VISUAL_ASSET",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Scene {scene.scene_number} ('{scene.title}') is missing a visual asset.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_type="visual",
                    )
                )
            elif not scene.visual_asset.is_valid:
                has_visuals = False
                scene_blocking.append(
                    AssemblyValidationIssue(
                        code="INVALID_VISUAL_ASSET",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Visual asset for scene {scene.scene_number} is invalid: {scene.visual_asset.validation_error}",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_id=scene.visual_asset.asset_id,
                        asset_type="visual",
                    )
                )

            # 5. Narration asset validation
            if not scene.is_silent:
                if not scene.narration_asset:
                    has_narration = False
                    scene_blocking.append(
                        AssemblyValidationIssue(
                            code="MISSING_NARRATION_ASSET",
                            severity=AssemblyIssueSeverity.BLOCKING,
                            message=f"Non-silent scene {scene.scene_number} is missing narration audio.",
                            scene_id=scene.scene_id,
                            scene_number=scene.scene_number,
                            asset_type="narration",
                        )
                    )
                elif not scene.narration_asset.is_valid:
                    has_narration = False
                    scene_blocking.append(
                        AssemblyValidationIssue(
                            code="INVALID_NARRATION_ASSET",
                            severity=AssemblyIssueSeverity.BLOCKING,
                            message=f"Narration asset for scene {scene.scene_number} is invalid: {scene.narration_asset.validation_error}",
                            scene_id=scene.scene_id,
                            scene_number=scene.scene_number,
                            asset_id=scene.narration_asset.asset_id,
                            asset_type="narration",
                        )
                    )
                else:
                    # Check audio duration vs scene duration consistency
                    if scene.narration_asset.duration_seconds is not None:
                        drift = abs(scene.duration_seconds - scene.narration_asset.duration_seconds)
                        if drift > 0.5:
                            scene_warnings.append(
                                AssemblyValidationIssue(
                                    code="DURATION_DRIFT",
                                    severity=AssemblyIssueSeverity.WARNING,
                                    message=f"Scene {scene.scene_number} duration ({scene.duration_seconds:.2f}s) differs from narration ({scene.narration_asset.duration_seconds:.2f}s) by {drift:.2f}s.",
                                    scene_id=scene.scene_id,
                                    scene_number=scene.scene_number,
                                    asset_id=scene.narration_asset.asset_id,
                                    asset_type="narration",
                                )
                            )

            # 6. Caption assets validation and cue collection
            if not scene.is_silent:
                if not scene.caption_srt_asset or not scene.caption_vtt_asset:
                    has_captions = False
                    scene_blocking.append(
                        AssemblyValidationIssue(
                            code="MISSING_SCENE_CAPTIONS",
                            severity=AssemblyIssueSeverity.BLOCKING,
                            message=f"Non-silent scene {scene.scene_number} is missing subtitle assets (SRT/VTT).",
                            scene_id=scene.scene_id,
                            scene_number=scene.scene_number,
                            asset_type="caption",
                        )
                    )
                else:
                    if not scene.caption_srt_asset.is_valid:
                        has_captions = False
                        scene_blocking.append(
                            AssemblyValidationIssue(
                                code="INVALID_SRT_CAPTION",
                                severity=AssemblyIssueSeverity.BLOCKING,
                                message=f"SRT caption for scene {scene.scene_number} is invalid: {scene.caption_srt_asset.validation_error}",
                                scene_id=scene.scene_id,
                                scene_number=scene.scene_number,
                                asset_id=scene.caption_srt_asset.asset_id,
                                asset_type="caption_srt",
                            )
                        )
                    if not scene.caption_vtt_asset.is_valid:
                        has_captions = False
                        scene_blocking.append(
                            AssemblyValidationIssue(
                                code="INVALID_VTT_CAPTION",
                                severity=AssemblyIssueSeverity.BLOCKING,
                                message=f"WebVTT caption for scene {scene.scene_number} is invalid: {scene.caption_vtt_asset.validation_error}",
                                scene_id=scene.scene_id,
                                scene_number=scene.scene_number,
                                asset_id=scene.caption_vtt_asset.asset_id,
                                asset_type="caption_vtt",
                            )
                        )

                    # When valid, parse scene cues and collect expected cumulative cues
                    if scene.caption_srt_asset.is_valid:
                        try:
                            srt_path = self.base_dir / scene.caption_srt_asset.relative_path
                            scene_srt_cues = parse_srt_cues_from_file(srt_path)
                            if not scene_srt_cues:
                                scene_blocking.append(
                                    AssemblyValidationIssue(
                                        code="EMPTY_SCENE_CAPTIONS",
                                        severity=AssemblyIssueSeverity.BLOCKING,
                                        message=f"Non-silent scene {scene.scene_number} has an empty SRT subtitle file.",
                                        scene_id=scene.scene_id,
                                        scene_number=scene.scene_number,
                                        asset_type="caption_srt",
                                    )
                                )
                            else:
                                for c_idx, (c_start, c_end, c_text) in enumerate(scene_srt_cues):
                                    if c_end > scene.duration_seconds + FLOAT_TOLERANCE_SECONDS:
                                        scene_warnings.append(
                                            AssemblyValidationIssue(
                                                code="CAPTION_DURATION_EXCEEDED",
                                                severity=AssemblyIssueSeverity.WARNING,
                                                message=f"Scene {scene.scene_number} cue {c_idx+1} end ({c_end:.2f}s) exceeds scene duration ({scene.duration_seconds:.2f}s).",
                                                scene_id=scene.scene_id,
                                                scene_number=scene.scene_number,
                                            )
                                        )
                                    # Expected timestamp on full-video timeline
                                    exp_start = round(c_start + scene.start_seconds, 3)
                                    exp_end = round(c_end + scene.start_seconds, 3)
                                    all_expected_composite_cues.append((exp_start, exp_end, c_text, scene.scene_number))
                        except Exception as e:
                            scene_blocking.append(
                                AssemblyValidationIssue(
                                    code="UNREADABLE_SCENE_SRT",
                                    severity=AssemblyIssueSeverity.BLOCKING,
                                    message=f"Could not parse SRT cues for scene {scene.scene_number}: {e}",
                                    scene_id=scene.scene_id,
                                    scene_number=scene.scene_number,
                                )
                            )

                    # Cross-check scene VTT against scene SRT
                    if scene.caption_vtt_asset.is_valid:
                        try:
                            vtt_path = self.base_dir / scene.caption_vtt_asset.relative_path
                            scene_vtt_cues = parse_vtt_cues_from_file(vtt_path)
                            if scene.caption_srt_asset.is_valid:
                                srt_path = self.base_dir / scene.caption_srt_asset.relative_path
                                scene_srt_cues = parse_srt_cues_from_file(srt_path)
                                if len(scene_vtt_cues) != len(scene_srt_cues):
                                    scene_blocking.append(
                                        AssemblyValidationIssue(
                                            code="SCENE_SUBTITLE_FORMAT_MISMATCH",
                                            severity=AssemblyIssueSeverity.BLOCKING,
                                            message=f"Scene {scene.scene_number} SRT has {len(scene_srt_cues)} cues but WebVTT has {len(scene_vtt_cues)} cues.",
                                            scene_id=scene.scene_id,
                                            scene_number=scene.scene_number,
                                        )
                                    )
                        except Exception as e:
                            scene_blocking.append(
                                AssemblyValidationIssue(
                                    code="UNREADABLE_SCENE_VTT",
                                    severity=AssemblyIssueSeverity.BLOCKING,
                                    message=f"Could not parse WebVTT cues for scene {scene.scene_number}: {e}",
                                    scene_id=scene.scene_id,
                                    scene_number=scene.scene_number,
                                )
                            )

            # Determine scene readiness
            scene.issues = scene_blocking + scene_warnings
            scene.is_ready = len(scene_blocking) == 0
            if scene.is_ready:
                ready_scenes += 1

            blocking_issues.extend(scene_blocking)
            warnings.extend(scene_warnings)

        total_duration = scenes[-1].end_seconds if scenes else 0.0

        # 7. Full-video subtitle track validation & deep composite cue consistency
        has_full_video_captions = True
        if not full_video_srt or not full_video_srt.is_valid:
            has_full_video_captions = False
            warnings.append(
                AssemblyValidationIssue(
                    code="MISSING_FULL_SRT_TRACK",
                    severity=AssemblyIssueSeverity.WARNING,
                    message="Full-video composite SRT track is missing or invalid; player will rely on per-scene cues.",
                    asset_type="full_video_srt",
                )
            )
        if not full_video_vtt or not full_video_vtt.is_valid:
            has_full_video_captions = False
            warnings.append(
                AssemblyValidationIssue(
                    code="MISSING_FULL_VTT_TRACK",
                    severity=AssemblyIssueSeverity.WARNING,
                    message="Full-video composite WebVTT track is missing or invalid; web player will lack continuous captions.",
                    asset_type="full_video_vtt",
                )
            )

        # Deep cross-check when both full-video tracks are present
        if full_video_srt and full_video_srt.is_valid and full_video_vtt and full_video_vtt.is_valid:
            try:
                full_srt_path = self.base_dir / full_video_srt.relative_path
                full_vtt_path = self.base_dir / full_video_vtt.relative_path
                full_srt_cues = parse_srt_cues_from_file(full_srt_path)
                full_vtt_cues = parse_vtt_cues_from_file(full_vtt_path)

                # 7a. Full SRT vs Full WebVTT agreement
                if len(full_srt_cues) != len(full_vtt_cues):
                    blocking_issues.append(
                        AssemblyValidationIssue(
                            code="FULL_TRACK_FORMAT_MISMATCH",
                            severity=AssemblyIssueSeverity.BLOCKING,
                            message=f"Full-video SRT has {len(full_srt_cues)} cues but full-video WebVTT has {len(full_vtt_cues)} cues.",
                            asset_type="full_video_captions",
                        )
                    )
                else:
                    for c_idx, (s_c, v_c) in enumerate(zip(full_srt_cues, full_vtt_cues)):
                        if abs(s_c[0] - v_c[0]) > FLOAT_TOLERANCE_SECONDS or abs(s_c[1] - v_c[1]) > FLOAT_TOLERANCE_SECONDS:
                            blocking_issues.append(
                                AssemblyValidationIssue(
                                    code="FULL_TRACK_TIMESTAMP_MISMATCH",
                                    severity=AssemblyIssueSeverity.BLOCKING,
                                    message=f"Full-video cue {c_idx+1} SRT timing [{s_c[0]:.2f}-{s_c[1]:.2f}] disagrees with WebVTT [{v_c[0]:.2f}-{v_c[1]:.2f}].",
                                    asset_type="full_video_captions",
                                )
                            )
                        if s_c[2].strip() != v_c[2].strip():
                            blocking_issues.append(
                                AssemblyValidationIssue(
                                    code="FULL_TRACK_TEXT_MISMATCH",
                                    severity=AssemblyIssueSeverity.BLOCKING,
                                    message=f"Full-video cue {c_idx+1} SRT text disagrees with WebVTT text.",
                                    asset_type="full_video_captions",
                                )
                            )

                # 7b. Cross-check full-video SRT cues against all expected cumulative scene cues
                if all_expected_composite_cues:
                    if len(full_srt_cues) != len(all_expected_composite_cues):
                        blocking_issues.append(
                            AssemblyValidationIssue(
                                code="COMPOSITE_CUE_COUNT_MISMATCH",
                                severity=AssemblyIssueSeverity.BLOCKING,
                                message=f"Full-video composite subtitle track has {len(full_srt_cues)} cues, expected {len(all_expected_composite_cues)} from scenes.",
                                asset_type="full_video_srt",
                            )
                        )
                    else:
                        for c_idx, (full_c, exp_c) in enumerate(zip(full_srt_cues, all_expected_composite_cues)):
                            exp_start, exp_end, exp_text, scene_num = exp_c
                            if abs(full_c[0] - exp_start) > FLOAT_TOLERANCE_SECONDS:
                                blocking_issues.append(
                                    AssemblyValidationIssue(
                                        code="COMPOSITE_CUE_TIMING_MISMATCH",
                                        severity=AssemblyIssueSeverity.BLOCKING,
                                        message=f"Full-video cue {c_idx+1} start ({full_c[0]:.3f}s) does not match expected timeline ({exp_start:.3f}s) for Scene {scene_num}.",
                                        scene_number=scene_num,
                                        asset_type="full_video_srt",
                                    )
                                )
                            if abs(full_c[1] - exp_end) > FLOAT_TOLERANCE_SECONDS:
                                blocking_issues.append(
                                    AssemblyValidationIssue(
                                        code="COMPOSITE_CUE_TIMING_MISMATCH",
                                        severity=AssemblyIssueSeverity.BLOCKING,
                                        message=f"Full-video cue {c_idx+1} end ({full_c[1]:.3f}s) does not match expected timeline ({exp_end:.3f}s) for Scene {scene_num}.",
                                        scene_number=scene_num,
                                        asset_type="full_video_srt",
                                    )
                                )
                            if full_c[2].strip() != exp_text.strip():
                                blocking_issues.append(
                                    AssemblyValidationIssue(
                                        code="COMPOSITE_CUE_TEXT_MISMATCH",
                                        severity=AssemblyIssueSeverity.BLOCKING,
                                        message=f"Full-video cue {c_idx+1} text '{full_c[2]}' does not match expected text '{exp_text}' for Scene {scene_num}.",
                                        scene_number=scene_num,
                                        asset_type="full_video_srt",
                                    )
                                )
            except Exception as e:
                blocking_issues.append(
                    AssemblyValidationIssue(
                        code="UNREADABLE_FULL_CAPTIONS",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Could not verify full-video subtitle tracks: {e}",
                        asset_type="full_video_captions",
                    )
                )

        # 8. Compute overall status
        if blocking_issues:
            overall_status = AssemblyReadinessStatus.NOT_READY
        elif warnings:
            overall_status = AssemblyReadinessStatus.READY_WITH_WARNINGS
        else:
            overall_status = AssemblyReadinessStatus.READY

        return AssemblyReadinessReport(
            job_id=job_id,
            status=overall_status,
            total_scenes=total_scenes,
            ready_scenes=ready_scenes,
            total_duration_seconds=round(total_duration, 3),
            has_visuals=has_visuals,
            has_narration=has_narration,
            has_captions=has_captions,
            has_full_video_captions=has_full_video_captions,
            blocking_issues=blocking_issues,
            warnings=warnings,
        )


preflight_validator = AssemblyPreflightValidator()
