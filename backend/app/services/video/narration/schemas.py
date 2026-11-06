"""
Narration Generation Schemas (Milestone 5, Phase 5.4).

Defines structured audio asset models, generation results, and synchronization
analysis between actual spoken audio duration and storyboard scene duration.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class NarrationAssetStatus(str, Enum):
    """Lifecycle status of a scene narration audio asset."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class NarrationAsset(BaseModel):
    """Metadata and status for a single scene's narration audio asset."""
    asset_id: str = Field(..., description="Unique alphanumeric identifier for the audio asset")
    job_id: str = Field(..., description="Job identifier associated with this narration asset")
    scene_id: str = Field(..., description="Storyboard scene identifier")
    scene_number: int = Field(..., ge=1, description="1-indexed sequence number of the scene")
    script_section_id: str = Field(..., description="Educational script section identifier")

    status: NarrationAssetStatus = NarrationAssetStatus.PENDING
    file_path: Optional[str] = Field(None, description="Relative internal path to stored audio file")
    format: str = Field(default="mp3", description="Audio format/container, e.g. mp3")
    file_size_bytes: int = Field(default=0, ge=0, description="Size of generated audio file in bytes")

    duration_seconds: float = Field(default=0.0, ge=0.0, description="Measured actual audio duration")
    expected_scene_duration_seconds: float = Field(default=0.0, ge=0.0, description="Planned scene duration from storyboard")
    duration_difference_seconds: float = Field(default=0.0, description="actual - expected duration difference")
    is_synchronized: bool = Field(default=True, description="Whether duration difference is within acceptable threshold")
    sync_warning: Optional[str] = Field(None, description="Warning if actual audio substantially diverges from planned scene")

    voice_id: Optional[str] = Field(None, description="ElevenLabs voice identifier used")
    model_id: Optional[str] = Field(None, description="ElevenLabs TTS model used")
    narration_text: str = Field(default="", description="Exact spoken text passed to TTS engine")

    generation_timestamp: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_id", "job_id", "scene_id")
    @classmethod
    def _validate_safe_id(cls, v: str) -> str:
        if not v or not SAFE_ID_REGEX.match(v):
            raise ValueError(f"Identifier '{v}' contains invalid characters; must be alphanumeric, hyphen, or underscore.")
        return v

    @field_validator("file_path")
    @classmethod
    def _validate_safe_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if ".." in v or v.startswith("/") or "\\" in v:
                raise ValueError(f"Unsafe relative storage path: '{v}'")
        return v


class SceneSyncReport(BaseModel):
    """Detailed timing comparison for a single scene."""
    scene_id: str
    scene_number: int
    expected_seconds: float
    actual_seconds: float
    difference_seconds: float
    ratio: float
    status: str
    warning: Optional[str] = None


class NarrationSyncSummary(BaseModel):
    """Overall timing and synchronization analysis across all scenes."""
    total_expected_duration_seconds: float = 0.0
    total_actual_duration_seconds: float = 0.0
    total_difference_seconds: float = 0.0
    scenes_synchronized: int = 0
    scenes_with_divergence: int = 0
    scene_reports: List[SceneSyncReport] = Field(default_factory=list)
    synchronization_warnings: List[str] = Field(default_factory=list)


class NarrationGenerationResult(BaseModel):
    """Complete narration generation plan and progress for a repository job."""
    schema_version: str = "1.0"
    job_id: str = Field(..., description="Job identifier")
    status: NarrationAssetStatus = NarrationAssetStatus.PENDING

    total_scenes: int = 0
    scenes_completed: int = 0
    scenes_failed: int = 0
    scenes_skipped: int = 0
    scenes_pending: int = 0
    scenes_generating: int = 0

    total_assets: int = 0
    assets_completed: int = 0
    assets_failed: int = 0
    assets_skipped: int = 0
    assets_pending: int = 0
    assets_generating: int = 0

    assets: List[NarrationAsset] = Field(default_factory=list)
    sync_summary: Optional[NarrationSyncSummary] = None

    voice_id: Optional[str] = None
    model_id: Optional[str] = None
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_fully_generated(self) -> bool:
        """True only if every required asset across all scenes is completed or skipped."""
        if not self.assets or self.total_assets == 0:
            return False
        return (self.assets_completed + self.assets_skipped) == self.total_assets and self.assets_failed == 0

    def get_asset_by_id(self, asset_id: str) -> Optional[NarrationAsset]:
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        return None

    def get_asset_by_scene_id(self, scene_id: str) -> Optional[NarrationAsset]:
        for a in self.assets:
            if a.scene_id == scene_id:
                return a
        return None
