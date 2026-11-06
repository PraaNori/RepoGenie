"""
Visual generation foundation module (Milestone 5, Phase 5.1).
"""

from .schemas import (
    MediaFormat,
    SceneVisualAssets,
    VideoOrientation,
    VisualAsset,
    VisualAssetStatus,
    VisualAssetType,
    VisualGenerationMetadata,
    VisualGenerationResult,
    VisualGenerationStatus,
    VISUAL_ASSET_SCHEMA_VERSION,
)
from .storage import (
    PathTraversalError,
    VisualAssetStorageManager,
    visual_storage_manager,
)
from .service import (
    VisualGenerationService,
    visual_generation_service,
)

__all__ = [
    "MediaFormat",
    "PathTraversalError",
    "SceneVisualAssets",
    "VideoOrientation",
    "VisualAsset",
    "VisualAssetStatus",
    "VisualAssetType",
    "VisualGenerationMetadata",
    "VisualGenerationResult",
    "VisualGenerationStatus",
    "VisualAssetStorageManager",
    "VisualGenerationService",
    "visual_storage_manager",
    "visual_generation_service",
    "VISUAL_ASSET_SCHEMA_VERSION",
]
