"""
Caption Generation Schemas (Milestone 5, Phase 5.5).

Defines structured models for caption segments, per-scene caption assets,
full-video subtitle tracks, timing provenance, and generation results.
Includes strict Pydantic validation for timestamps, sequence ordering,
scene associations, and duration limits.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")
TIMESTAMP_ROUNDING_TOLERANCE_SECONDS = 0.05  # Tolerance for floating-point duration boundaries


class CaptionStatus(str, Enum):
    """Lifecycle status for caption generation operations."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TimingProvenance(str, Enum):
    """Provenance indicator for subtitle timestamps."""
    ESTIMATED = "estimated"   # Proportional allocation based on punctuation, syllables, and word weights
    ALIGNED = "aligned"       # Measured character- or word-level alignment (e.g. from speech recognizer)


class Caption(BaseModel):
    """
    A single subtitle cue / caption segment within a scene.
    """
    caption_id: str = Field(..., description="Unique identifier for this caption cue")
    scene_id: str = Field(..., description="Associated storyboard scene identifier")
    sequence_number: int = Field(..., ge=1, description="1-indexed sequence order within the scene or video")
    
    start_seconds: float = Field(..., ge=0.0, description="Start time in seconds relative to scene or track")
    end_seconds: float = Field(..., ge=0.0, description="End time in seconds relative to scene or track")
    
    start_timestamp_srt: str = Field(..., description="SRT formatted timestamp HH:MM:SS,mmm")
    end_timestamp_srt: str = Field(..., description="SRT formatted timestamp HH:MM:SS,mmm")
    start_timestamp_vtt: str = Field(..., description="WebVTT formatted timestamp HH:MM:SS.mmm")
    end_timestamp_vtt: str = Field(..., description="WebVTT formatted timestamp HH:MM:SS.mmm")
    
    text: str = Field(..., description="Clean, readable spoken text for this caption cue")
    timing_provenance: TimingProvenance = Field(
        default=TimingProvenance.ESTIMATED,
        description="Indicates whether timing was proportionally estimated or externally aligned",
    )
    warnings: List[str] = Field(default_factory=list, description="Validation warnings, if any")

    @field_validator("caption_id", "scene_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Identifier '{v}' contains invalid characters; must be alphanumeric, hyphen, or underscore.")
        return v

    @field_validator("text")
    @classmethod
    def _validate_non_empty_text(cls, v: str) -> str:
        clean = v.strip() if v else ""
        if not clean:
            raise ValueError("Caption text must not be empty or whitespace.")
        return clean

    @model_validator(mode="after")
    def _validate_timing_consistency(self) -> Caption:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"End timestamp ({self.end_seconds:.3f}s) must be strictly greater than start timestamp ({self.start_seconds:.3f}s)."
            )
        return self


class SceneCaptionAsset(BaseModel):
    """
    Collection of caption segments and subtitle files for an individual storyboard scene.
    """
    asset_id: str = Field(..., description="Unique alphanumeric identifier for the scene caption asset")
    job_id: str = Field(..., description="Job identifier")
    scene_id: str = Field(..., description="Storyboard scene identifier")
    scene_number: int = Field(..., ge=1, description="1-indexed sequence number of the scene")
    script_section_id: str = Field(..., description="Associated educational script section ID")

    status: CaptionStatus = Field(default=CaptionStatus.PENDING, description="Status of scene caption generation")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Actual measured audio duration for this scene")
    
    cumulative_start_seconds: float = Field(default=0.0, ge=0.0, description="Offset in seconds from start of full video")
    cumulative_end_seconds: float = Field(default=0.0, ge=0.0, description="End offset in seconds from start of full video")

    captions: List[Caption] = Field(default_factory=list, description="Ordered caption cues for this scene")

    srt_file_path: Optional[str] = Field(None, description="Relative path to scene SRT file")
    vtt_file_path: Optional[str] = Field(None, description="Relative path to scene WebVTT file")
    srt_file_size_bytes: int = Field(default=0, ge=0)
    vtt_file_size_bytes: int = Field(default=0, ge=0)

    timing_provenance: TimingProvenance = Field(default=TimingProvenance.ESTIMATED)
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)

    @field_validator("asset_id", "job_id", "scene_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Identifier '{v}' contains invalid characters; must be alphanumeric, hyphen, or underscore.")
        return v

    @field_validator("srt_file_path", "vtt_file_path")
    @classmethod
    def _validate_safe_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if ".." in v or v.startswith("/") or "\\" in v:
                raise ValueError(f"Unsafe storage path: '{v}'")
        return v

    @model_validator(mode="after")
    def _validate_captions_sequence_and_bounds(self) -> SceneCaptionAsset:
        if self.status == CaptionStatus.COMPLETED and self.captions:
            # Check sequential ordering and non-overlapping within scene
            last_end = 0.0
            for idx, c in enumerate(self.captions):
                expected_seq = idx + 1
                if c.sequence_number != expected_seq:
                    raise ValueError(
                        f"Caption sequence mismatch at index {idx}: expected {expected_seq}, got {c.sequence_number}"
                    )
                if c.start_seconds < last_end - 1e-4:
                    raise ValueError(
                        f"Overlapping captions detected: caption {c.caption_id} starts at {c.start_seconds:.3f}s before previous ended at {last_end:.3f}s"
                    )
                last_end = c.end_seconds

            # Check that captions do not exceed scene audio duration beyond tolerance
            if self.duration_seconds > 0:
                max_end = self.captions[-1].end_seconds
                if max_end > self.duration_seconds + TIMESTAMP_ROUNDING_TOLERANCE_SECONDS:
                    raise ValueError(
                        f"Caption end timestamp ({max_end:.3f}s) exceeds scene audio duration ({self.duration_seconds:.3f}s) by more than {TIMESTAMP_ROUNDING_TOLERANCE_SECONDS}s tolerance."
                    )
        return self


class CaptionGenerationResult(BaseModel):
    """
    Complete aggregate caption generation result for a job, containing per-scene assets
    as well as full-video composite subtitle tracks (.srt and .vtt).
    """
    schema_version: str = "1.0"
    job_id: str = Field(..., description="Job identifier")
    status: CaptionStatus = Field(default=CaptionStatus.PENDING)

    total_scenes: int = 0
    scenes_completed: int = 0
    scenes_failed: int = 0
    scenes_skipped: int = 0
    total_captions: int = 0

    scene_assets: List[SceneCaptionAsset] = Field(default_factory=list)

    full_srt_file_path: Optional[str] = Field(None, description="Relative path to concatenated full-video SRT file")
    full_vtt_file_path: Optional[str] = Field(None, description="Relative path to concatenated full-video WebVTT file")
    full_srt_file_size_bytes: int = Field(default=0, ge=0)
    full_vtt_file_size_bytes: int = Field(default=0, ge=0)

    timing_provenance: TimingProvenance = Field(default=TimingProvenance.ESTIMATED)
    total_duration_seconds: float = Field(default=0.0, ge=0.0, description="Total duration of all video scenes combined")
    
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_fully_generated(self) -> bool:
        """Returns True if every required scene has completed or skipped captions without errors."""
        if not self.scene_assets or self.total_scenes == 0:
            return False
        return (self.scenes_completed + self.scenes_skipped) == self.total_scenes and self.scenes_failed == 0

    def get_asset_by_id(self, asset_id: str) -> Optional[SceneCaptionAsset]:
        for a in self.scene_assets:
            if a.asset_id == asset_id:
                return a
        return None

    def get_asset_by_scene_id(self, scene_id: str) -> Optional[SceneCaptionAsset]:
        for a in self.scene_assets:
            if a.scene_id == scene_id:
                return a
        return None
