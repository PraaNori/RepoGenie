"""
Visual generation module for technical diagrams and visual assets (Milestone 5).
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
from .diagrams import (
    ArchitectureDiagramGenerator,
    BaseDiagramGenerator,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    ComponentDiagramGenerator,
    DataFlowDiagramGenerator,
    DiagramGenerationResult,
    DiagramRenderer,
    DiagramType,
    WorkflowDiagramGenerator,
    diagram_renderer,
    sanitize_filename,
    sanitize_text,
)

__all__ = [
    "ArchitectureDiagramGenerator",
    "BaseDiagramGenerator",
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "ComponentDiagramGenerator",
    "DataFlowDiagramGenerator",
    "DiagramGenerationResult",
    "DiagramRenderer",
    "DiagramType",
    "MediaFormat",
    "PathTraversalError",
    "SceneVisualAssets",
    "VideoOrientation",
    "VisualAsset",
    "VisualAssetStatus",
    "VisualAssetType",
    "VisualGenerationMetadata",
    "VisualGenerationResult",
    "VisualGenerationService",
    "VisualGenerationStatus",
    "VisualAssetStorageManager",
    "WorkflowDiagramGenerator",
    "diagram_renderer",
    "sanitize_filename",
    "sanitize_text",
    "visual_storage_manager",
    "visual_generation_service",
    "VISUAL_ASSET_SCHEMA_VERSION",
]
