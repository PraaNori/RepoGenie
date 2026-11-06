"""
Video Assembly Input Package Schemas (Milestone 5, Phase 5.6).

Defines structured models for pre-assembly packaging, cross-asset synchronization,
physical asset validation, and assembly readiness reporting.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class AssemblyReadinessStatus(str, Enum):
    """Overall preflight readiness status for video assembly."""
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    NOT_READY = "not_ready"


class AssemblyIssueSeverity(str, Enum):
    """Severity level of an assembly validation issue."""
    BLOCKING = "blocking"
    WARNING = "warning"


class AssemblyValidationIssue(BaseModel):
    """A validation defect or advisory warning discovered during assembly preflight."""
    code: str = Field(..., description="Machine-readable error/warning code")
    severity: AssemblyIssueSeverity = Field(..., description="Severity classification (blocking or warning)")
    message: str = Field(..., description="Human-readable explanation of the defect or warning")
    scene_id: Optional[str] = Field(default=None, description="Affected scene identifier, if applicable")
    scene_number: Optional[int] = Field(default=None, description="Affected scene number, if applicable")
    asset_id: Optional[str] = Field(default=None, description="Affected asset identifier, if applicable")
    asset_type: Optional[str] = Field(default=None, description="Asset type (visual, narration, caption, etc.)")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Diagnostic data or measurements")


class AssemblyAssetReference(BaseModel):
    """
    Validated reference to a physical asset file on disk prepared for video assembly.
    """
    asset_id: str = Field(..., description="Unique asset identifier")
    scene_id: Optional[str] = Field(default=None, description="Associated scene identifier")
    asset_type: str = Field(..., description="Asset kind: visual, narration, caption_srt, caption_vtt, full_video_srt, full_video_vtt")
    relative_path: str = Field(..., description="Safe relative path from repository root (e.g. storage/jobs/...)")
    file_format: str = Field(..., description="File extension format: svg, mp3, srt, vtt")
    file_size_bytes: int = Field(default=0, ge=0, description="Size of file on disk in bytes")
    duration_seconds: Optional[float] = Field(default=None, ge=0.0, description="Measured asset duration in seconds, if applicable")
    is_valid: bool = Field(default=True, description="Whether the asset passed format and integrity preflight validation")
    validation_error: Optional[str] = Field(default=None, description="Detailed validation error message if invalid")

    @field_validator("asset_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Asset ID '{v}' contains invalid characters.")
        return v


class AssemblyScene(BaseModel):
    """
    A single scene in the video assembly timeline with its synchronized visual, audio, and subtitle assets.
    """
    scene_id: str = Field(..., description="Unique scene identifier")
    scene_number: int = Field(..., ge=1, description="1-indexed monotonic scene order in the video")
    script_section_id: str = Field(..., description="Associated script section ID")
    section_purpose: str = Field(..., description="Educational section purpose")
    title: str = Field(..., description="Scene title or header")

    visual_asset: Optional[AssemblyAssetReference] = Field(default=None, description="Visual SVG asset reference")
    narration_asset: Optional[AssemblyAssetReference] = Field(default=None, description="Narration MP3 audio asset reference")
    caption_srt_asset: Optional[AssemblyAssetReference] = Field(default=None, description="Per-scene SRT subtitle asset reference")
    caption_vtt_asset: Optional[AssemblyAssetReference] = Field(default=None, description="Per-scene WebVTT subtitle asset reference")

    start_seconds: float = Field(..., ge=0.0, description="Timeline start offset in seconds")
    end_seconds: float = Field(..., ge=0.0, description="Timeline end offset in seconds")
    duration_seconds: float = Field(..., ge=0.0, description="Effective duration of the scene in seconds")

    is_silent: bool = Field(default=False, description="Whether this scene is intentionally silent (no narration required)")
    narration_text: Optional[str] = Field(default=None, description="Spoken narration text")

    is_ready: bool = Field(default=True, description="Whether all required assets for this scene are present and valid")
    issues: List[AssemblyValidationIssue] = Field(default_factory=list, description="Validation issues specific to this scene")

    @model_validator(mode="after")
    def _validate_scene_duration(self) -> AssemblyScene:
        if self.end_seconds < self.start_seconds:
            raise ValueError(
                f"Scene {self.scene_number} end_seconds ({self.end_seconds}) cannot be less than start_seconds ({self.start_seconds})"
            )
        return self


class AssemblyReadinessReport(BaseModel):
    """
    Comprehensive preflight audit report evaluating whether a job's assets are ready for video assembly.
    """
    job_id: str = Field(..., description="Job identifier")
    status: AssemblyReadinessStatus = Field(..., description="Overall readiness status")
    total_scenes: int = Field(default=0, ge=0, description="Total number of storyboard scenes")
    ready_scenes: int = Field(default=0, ge=0, description="Number of fully ready scenes")
    total_duration_seconds: float = Field(default=0.0, ge=0.0, description="Total timeline duration in seconds")

    has_visuals: bool = Field(default=False, description="Whether all scenes have valid visual assets")
    has_narration: bool = Field(default=False, description="Whether all non-silent scenes have valid narration audio")
    has_captions: bool = Field(default=False, description="Whether all non-silent scenes have valid captions")
    has_full_video_captions: bool = Field(default=False, description="Whether full-video composite captions exist and are valid")

    blocking_issues: List[AssemblyValidationIssue] = Field(default_factory=list, description="Issues preventing assembly")
    warnings: List[AssemblyValidationIssue] = Field(default_factory=list, description="Non-blocking warnings")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of report generation")


class VideoAssemblyInput(BaseModel):
    """
    Complete, self-contained, validated input package for the video assembly engine (Milestone 6).
    """
    job_id: str = Field(..., description="Job identifier")
    repo_name: str = Field(..., description="Target repository name")
    scenes: List[AssemblyScene] = Field(default_factory=list, description="Ordered scenes with synchronized assets")
    total_scenes: int = Field(default=0, ge=0, description="Total scenes in timeline")
    total_duration_seconds: float = Field(default=0.0, ge=0.0, description="Total duration of complete video in seconds")

    full_video_srt: Optional[AssemblyAssetReference] = Field(default=None, description="Full-video composite SRT subtitle asset")
    full_video_vtt: Optional[AssemblyAssetReference] = Field(default=None, description="Full-video composite WebVTT subtitle asset")

    readiness_report: AssemblyReadinessReport = Field(..., description="Preflight readiness evaluation")
    video_metadata: Dict[str, Any] = Field(
        default_factory=lambda: {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "aspect_ratio": "16:9",
            "audio_codec": "aac",
            "audio_sample_rate": 44100,
            "video_codec": "libx264",
        },
        description="Target video rendering parameters",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Package creation timestamp")
