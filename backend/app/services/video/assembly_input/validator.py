"""
Assembly Preflight Validator (Milestone 5, Phase 5.6).

Performs physical disk inspection and cross-asset validation for video assembly:
1. Validates physical file existence, non-empty size, and file-format integrity
   (SVG 1920x1080 viewBox, MP3 audio header/duration, SRT/WebVTT subtitle syntax).
2. Prevents directory traversal by enforcing storage root boundaries.
3. Validates timeline continuity, monotonic scene ordering, and audio/caption synchronization.
4. Generates an AssemblyReadinessReport with BLOCKING issues and advisory WARNINGS.
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
from ..captions.formatter import validate_srt_content, validate_vtt_content
from ..narration.audio_storage import audio_storage_manager

logger = logging.getLogger(__name__)

FLOAT_TOLERANCE_SECONDS = 0.05
MP3_SYNC_PATTERNS = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


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
        Validates that an SVG file exists on disk, is non-empty, and has valid SVG markup
        with 1920x1080 canvas or 16:9 aspect ratio.
        """
        try:
            safe_path = self.assert_safe_path(file_path)
            if not safe_path.exists() or not safe_path.is_file():
                return False, f"File does not exist: {file_path}", 0

            file_size = safe_path.stat().st_size
            if file_size == 0:
                return False, f"File is empty (0 bytes): {file_path}", 0

            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                return False, "SVG content is empty", file_size

            # Basic XML parsing to verify well-formedness
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
        except Exception as exc:
            return False, f"Failed to validate visual file: {exc}", 0

    def validate_audio_file(self, file_path: Path) -> Tuple[bool, Optional[str], int, float]:
        """
        Validates that an MP3 file exists, is non-empty, contains valid MP3 headers,
        and has measurable duration > 0.
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

            if not valid:
                return False, f"Malformed {fmt.upper()} subtitle syntax: {msg}", file_size

            return True, None, file_size
        except Exception as exc:
            return False, f"Failed to validate caption file: {exc}", 0

    def evaluate_package(
        self,
        job_id: str,
        scenes: List[AssemblyScene],
        full_video_srt: Optional[AssemblyAssetReference] = None,
        full_video_vtt: Optional[AssemblyAssetReference] = None,
    ) -> AssemblyReadinessReport:
        """
        Audits the complete assembled package for timeline continuity, asset completeness,
        and cross-modal synchronization.
        """
        blocking_issues: List[AssemblyValidationIssue] = []
        warnings: List[AssemblyValidationIssue] = []

        total_scenes = len(scenes)
        ready_scenes = 0
        total_duration = 0.0

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

        for idx, scene in enumerate(scenes):
            scene_blocking: List[AssemblyValidationIssue] = []
            scene_warnings: List[AssemblyValidationIssue] = []

            # 1. Monotonic scene number check
            expected_num = idx + 1
            if scene.scene_number != expected_num:
                issue = AssemblyValidationIssue(
                    code="SCENE_SEQUENCE_MISMATCH",
                    severity=AssemblyIssueSeverity.BLOCKING,
                    message=f"Scene index {idx} has scene_number {scene.scene_number}, expected {expected_num}.",
                    scene_id=scene.scene_id,
                    scene_number=scene.scene_number,
                )
                scene_blocking.append(issue)

            # 2. Continuous timeline check
            if abs(scene.start_seconds - expected_start) > FLOAT_TOLERANCE_SECONDS:
                diff = scene.start_seconds - expected_start
                if diff > 0:
                    issue = AssemblyValidationIssue(
                        code="TIMELINE_GAP",
                        severity=AssemblyIssueSeverity.WARNING,
                        message=f"Scene {scene.scene_number} has a timeline gap of {diff:.3f}s from preceding scene.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        details={"expected_start": expected_start, "actual_start": scene.start_seconds},
                    )
                    scene_warnings.append(issue)
                else:
                    issue = AssemblyValidationIssue(
                        code="TIMELINE_OVERLAP",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Scene {scene.scene_number} overlaps preceding scene by {abs(diff):.3f}s.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        details={"expected_start": expected_start, "actual_start": scene.start_seconds},
                    )
                    scene_blocking.append(issue)

            expected_start = scene.end_seconds

            # 3. Visual asset validation
            if not scene.visual_asset:
                has_visuals = False
                issue = AssemblyValidationIssue(
                    code="MISSING_VISUAL_ASSET",
                    severity=AssemblyIssueSeverity.BLOCKING,
                    message=f"Scene {scene.scene_number} ('{scene.title}') is missing a visual asset.",
                    scene_id=scene.scene_id,
                    scene_number=scene.scene_number,
                    asset_type="visual",
                )
                scene_blocking.append(issue)
            elif not scene.visual_asset.is_valid:
                has_visuals = False
                issue = AssemblyValidationIssue(
                    code="INVALID_VISUAL_ASSET",
                    severity=AssemblyIssueSeverity.BLOCKING,
                    message=f"Visual asset for scene {scene.scene_number} is invalid: {scene.visual_asset.validation_error}",
                    scene_id=scene.scene_id,
                    scene_number=scene.scene_number,
                    asset_id=scene.visual_asset.asset_id,
                    asset_type="visual",
                )
                scene_blocking.append(issue)

            # 4. Narration asset validation
            if not scene.is_silent:
                if not scene.narration_asset:
                    has_narration = False
                    issue = AssemblyValidationIssue(
                        code="MISSING_NARRATION_ASSET",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Non-silent scene {scene.scene_number} is missing narration audio.",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_type="narration",
                    )
                    scene_blocking.append(issue)
                elif not scene.narration_asset.is_valid:
                    has_narration = False
                    issue = AssemblyValidationIssue(
                        code="INVALID_NARRATION_ASSET",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Narration asset for scene {scene.scene_number} is invalid: {scene.narration_asset.validation_error}",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_id=scene.narration_asset.asset_id,
                        asset_type="narration",
                    )
                    scene_blocking.append(issue)
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

            # 5. Caption assets validation
            if not scene.is_silent:
                if not scene.caption_srt_asset or not scene.caption_vtt_asset:
                    has_captions = False
                    issue = AssemblyValidationIssue(
                        code="MISSING_SCENE_CAPTIONS",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Non-silent scene {scene.scene_number} is missing subtitle assets (SRT/VTT).",
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_type="caption",
                    )
                    scene_blocking.append(issue)
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

            # Determine scene readiness
            scene.issues = scene_blocking + scene_warnings
            scene.is_ready = len(scene_blocking) == 0
            if scene.is_ready:
                ready_scenes += 1

            blocking_issues.extend(scene_blocking)
            warnings.extend(scene_warnings)

        total_duration = scenes[-1].end_seconds if scenes else 0.0

        # 6. Full-video subtitle track validation
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

        # 7. Compute overall status
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
