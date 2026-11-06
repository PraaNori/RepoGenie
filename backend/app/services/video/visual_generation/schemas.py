"""
Strongly typed Pydantic schemas for Milestone 5, Phase 5.1: Visual Generation Foundation.

Defines schemas and explicit enums for:
- VisualAsset: Individual scene visual assets (title cards, diagrams, code visuals, overlays)
- SceneVisualAssets: Scene-level grouping of visual assets
- VisualGenerationResult: Complete visual generation state for an educational storyboard
- VisualGenerationMetadata: Metadata about rendering engine, parameters, and timings
- VisualGenerationStatus & VisualAssetStatus: Explicit lifecycle status enums
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from ...ai.project_understanding.schemas import EvidenceReference
from ...ai.storyboard_generation.schemas import VisualType


VISUAL_ASSET_SCHEMA_VERSION = "1.0"
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
_SAFE_PATH_PATTERN = re.compile(r"^jobs/[a-zA-Z0-9_\-]+/visuals/[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+$")


class VisualGenerationStatus(str, Enum):
    """Lifecycle status for storyboard-level and scene-level visual generation."""
    PENDING = "pending"
    PLANNED = "planned"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class VisualAssetStatus(str, Enum):
    """Lifecycle status for individual visual assets."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VisualAssetType(str, Enum):
    """Categories of visual assets produced for video scenes."""
    PRIMARY_VISUAL = "primary_visual"
    TITLE_CARD = "title_card"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"
    COMPONENT_DIAGRAM = "component_diagram"
    WORKFLOW_DIAGRAM = "workflow_diagram"
    DATA_FLOW_DIAGRAM = "data_flow_diagram"
    CODE_WALKTHROUGH = "code_walkthrough"
    SUMMARY_CARD = "summary_card"
    BACKGROUND = "background"
    OVERLAY = "overlay"
    OTHER = "other"


class MediaFormat(str, Enum):
    """Media file formats supported for generated visuals."""
    SVG = "svg"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    JSON = "json"


class VideoOrientation(str, Enum):
    """Visual orientation format matching downstream video specifications."""
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class VisualGenerationMetadata(BaseModel):
    """Metadata describing generation parameters, renderer info, and diagnostics."""
    generator_name: str = Field(
        default="VisualGenerationFoundation",
        description="Name of the service or renderer generating this asset",
    )
    renderer_version: str = Field(
        default="1.0",
        description="Version of the rendering service",
    )
    generation_duration_ms: Optional[float] = Field(
        default=None,
        description="Rendering latency in milliseconds",
    )
    diagram_syntax: Optional[str] = Field(
        default=None,
        description="Syntax type if generated from code/markup (e.g. 'mermaid', 'pygments', 'svg')",
    )
    source_code_hash: Optional[str] = Field(
        default=None,
        description="SHA256 hash of underlying source code or diagram input",
    )
    render_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters passed to the renderer (theme, layout, highlighted lines)",
    )


class VisualAsset(BaseModel):
    """
    Represents an individual visual asset planned or rendered for a storyboard scene.
    Stores safe relative storage paths, never local machine paths.
    """
    asset_id: str = Field(
        ...,
        description="Unique identifier for the asset (e.g. 'va_12345678_s01_01')",
    )
    job_id: str = Field(
        ...,
        description="ID of the job that owns this asset",
    )
    scene_id: str = Field(
        ...,
        description="Associated StoryboardScene ID",
    )
    scene_number: int = Field(
        ...,
        ge=1,
        description="1-based scene sequence number in the storyboard",
    )
    asset_type: VisualAssetType = Field(
        default=VisualAssetType.PRIMARY_VISUAL,
        description="Role or category of this visual asset",
    )
    visual_type: VisualType = Field(
        ...,
        description="Storyboard-designated visual treatment",
    )
    storage_path: str = Field(
        ...,
        description="Relative storage path within RepoGenie storage (e.g. 'jobs/{job_id}/visuals/{asset_id}.svg')",
    )
    media_format: MediaFormat = Field(
        default=MediaFormat.SVG,
        description="File format of the asset",
    )
    width: int = Field(
        default=1920,
        ge=1,
        description="Target pixel width (standard 1080p landscape: 1920)",
    )
    height: int = Field(
        default=1080,
        ge=1,
        description="Target pixel height (standard 1080p landscape: 1080)",
    )
    aspect_ratio: str = Field(
        default="16:9",
        description="Visual aspect ratio specification",
    )
    status: VisualAssetStatus = Field(
        default=VisualAssetStatus.PENDING,
        description="Current lifecycle status of this asset",
    )
    source_evidence: List[EvidenceReference] = Field(
        default_factory=list,
        description="Grounded repository evidence references informing this visual",
    )
    related_files: List[str] = Field(
        default_factory=list,
        description="Repository file paths highlighted or depicted in this asset",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the asset record was created",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the asset record was last modified",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error detail if asset generation failed",
    )
    validation_warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings discovered during validation",
    )
    metadata: VisualGenerationMetadata = Field(
        default_factory=VisualGenerationMetadata,
        description="Renderer and generation metadata",
    )

    @field_validator("asset_id", "job_id", "scene_id")
    @classmethod
    def validate_safe_id(cls, v: str) -> str:
        if not v or not _SAFE_ID_PATTERN.match(v):
            raise ValueError(f"Invalid identifier '{v}': must be non-empty alphanumeric with hyphens or underscores only.")
        return v

    @field_validator("storage_path")
    @classmethod
    def validate_storage_path(cls, v: str) -> str:
        if ".." in v or "\\" in v or v.startswith("/") or v.startswith("~"):
            raise ValueError(f"Storage path '{v}' contains prohibited path traversal characters.")
        if not _SAFE_PATH_PATTERN.match(v):
            raise ValueError(
                f"Storage path '{v}' does not match required format 'jobs/{{job_id}}/visuals/{{filename}}'"
            )
        return v


class SceneVisualAssets(BaseModel):
    """
    Collection of visual assets associated with a single storyboard scene.
    """
    scene_id: str = Field(
        ...,
        description="ID of the storyboard scene",
    )
    scene_number: int = Field(
        ...,
        ge=1,
        description="1-based scene sequence number",
    )
    scene_title: str = Field(
        ...,
        description="Title of the scene from the storyboard",
    )
    visual_type: VisualType = Field(
        ...,
        description="Visual treatment for this scene",
    )
    visual_description: str = Field(
        ...,
        description="Blueprint visual description from the storyboard",
    )
    primary_asset: Optional[VisualAsset] = Field(
        default=None,
        description="Primary visual asset for the scene",
    )
    supplementary_assets: List[VisualAsset] = Field(
        default_factory=list,
        description="Additional visual assets (e.g. overlays, sub-diagrams)",
    )
    status: VisualGenerationStatus = Field(
        default=VisualGenerationStatus.PLANNED,
        description="Aggregated generation status for this scene's visuals",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error detail if scene visual generation failed",
    )

    @property
    def all_assets(self) -> List[VisualAsset]:
        """Returns all assets (primary and supplementary) for this scene."""
        assets = []
        if self.primary_asset:
            assets.append(self.primary_asset)
        assets.extend(self.supplementary_assets)
        return assets

    @property
    def total_assets_count(self) -> int:
        return len(self.all_assets)

    @model_validator(mode="after")
    def validate_scene_consistency(self) -> SceneVisualAssets:
        if self.primary_asset and self.primary_asset.scene_id != self.scene_id:
            raise ValueError(
                f"primary_asset scene_id '{self.primary_asset.scene_id}' does not match SceneVisualAssets scene_id '{self.scene_id}'"
            )
        return self


class VisualGenerationResult(BaseModel):
    """
    Complete visual asset generation foundation result for an EducationalStoryboard.
    Tracks status, scene mappings, asset inventory, and lifecycle metadata.
    """
    schema_version: str = Field(
        default=VISUAL_ASSET_SCHEMA_VERSION,
        description="Schema specification version",
    )
    job_id: str = Field(
        ...,
        description="Associated job ID",
    )
    storyboard_id: str = Field(
        ...,
        description="ID of the EducationalStoryboard being visualized",
    )
    script_id: str = Field(
        ...,
        description="ID of the EducationalScript underlying the storyboard",
    )
    status: VisualGenerationStatus = Field(
        default=VisualGenerationStatus.PLANNED,
        description="Overall visual generation lifecycle status (e.g. 'planned', 'generating', 'completed', 'failed')",
    )
    video_orientation: VideoOrientation = Field(
        default=VideoOrientation.LANDSCAPE,
        description="Video aspect ratio orientation",
    )
    total_scenes: int = Field(
        default=0,
        ge=0,
        description="Total scenes in the storyboard",
    )
    scenes_completed: int = Field(
        default=0,
        ge=0,
        description="Number of scenes with completed visuals",
    )
    scenes_failed: int = Field(
        default=0,
        ge=0,
        description="Number of scenes with failed visuals",
    )
    total_assets: int = Field(
        default=0,
        ge=0,
        description="Total visual assets planned or generated",
    )
    assets_pending: int = Field(
        default=0,
        ge=0,
        description="Number of assets awaiting rendering",
    )
    assets_generating: int = Field(
        default=0,
        ge=0,
        description="Number of assets currently rendering",
    )
    assets_completed: int = Field(
        default=0,
        ge=0,
        description="Number of assets successfully rendered to disk",
    )
    assets_failed: int = Field(
        default=0,
        ge=0,
        description="Number of assets that failed rendering",
    )
    scene_assets: List[SceneVisualAssets] = Field(
        default_factory=list,
        description="Ordered visual asset collections matching storyboard scenes",
    )
    storage_directory: str = Field(
        ...,
        description="Relative storage directory for this job's visual assets (e.g. 'jobs/{job_id}/visuals')",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when visual generation was initialized",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of last status update",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if visual generation failed",
    )
    validation_warnings: List[str] = Field(
        default_factory=list,
        description="Validation notices and diagnostic warnings",
    )

    @field_validator("job_id", "storyboard_id", "script_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        if not v or not _SAFE_ID_PATTERN.match(v):
            raise ValueError(f"Invalid identifier '{v}': must be alphanumeric with hyphens or underscores.")
        return v

    @field_validator("storage_directory")
    @classmethod
    def validate_storage_directory(cls, v: str) -> str:
        if ".." in v or "\\" in v or v.startswith("/") or v.startswith("~"):
            raise ValueError(f"Storage directory '{v}' contains prohibited path traversal characters.")
        return v

    @model_validator(mode="after")
    def validate_scene_counts(self) -> VisualGenerationResult:
        if self.scenes_completed > self.total_scenes:
            raise ValueError(
                f"scenes_completed ({self.scenes_completed}) cannot exceed total_scenes ({self.total_scenes})"
            )
        if self.scenes_failed > self.total_scenes:
            raise ValueError(
                f"scenes_failed ({self.scenes_failed}) cannot exceed total_scenes ({self.total_scenes})"
            )
        if self.assets_completed > self.total_assets:
            raise ValueError(
                f"assets_completed ({self.assets_completed}) cannot exceed total_assets ({self.total_assets})"
            )
        return self

    @property
    def is_fully_rendered(self) -> bool:
        """Returns True only when all required assets are completed and rendered."""
        return (
            self.status == VisualGenerationStatus.COMPLETED
            and self.total_assets > 0
            and self.assets_completed == self.total_assets
            and self.assets_pending == 0
            and self.assets_generating == 0
            and self.assets_failed == 0
            and self.scenes_completed == self.total_scenes
            and self.scenes_failed == 0
        )

    def get_scene_assets(self, scene_id: str) -> Optional[SceneVisualAssets]:
        """Finds visual asset collection for a specific scene by scene_id."""
        for sa in self.scene_assets:
            if sa.scene_id == scene_id:
                return sa
        return None

    def get_asset_by_id(self, asset_id: str) -> Optional[VisualAsset]:
        """Finds a specific visual asset by asset_id across all scenes."""
        for sa in self.scene_assets:
            for asset in sa.all_assets:
                if asset.asset_id == asset_id:
                    return asset
        return None
