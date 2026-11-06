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
from .code_visuals import (
    CodeExcerpt,
    CodeExtractor,
    CodeHighlighter,
    CodeWalkthroughGenerator,
    CodeWalkthroughLine,
    code_extractor,
    code_highlighter,
    code_walkthrough_generator,
)
from .scene_cards import (
    SummaryCardGenerator,
    TitleCardGenerator,
    summary_card_generator,
    title_card_generator,
)

__all__ = [
    "ArchitectureDiagramGenerator",
    "BaseDiagramGenerator",
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "CodeExcerpt",
    "CodeExtractor",
    "CodeHighlighter",
    "CodeWalkthroughGenerator",
    "CodeWalkthroughLine",
    "ComponentDiagramGenerator",
    "DataFlowDiagramGenerator",
    "DiagramGenerationResult",
    "DiagramRenderer",
    "DiagramType",
    "MediaFormat",
    "PathTraversalError",
    "SceneVisualAssets",
    "SummaryCardGenerator",
    "TitleCardGenerator",
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
    "code_extractor",
    "code_highlighter",
    "code_walkthrough_generator",
    "diagram_renderer",
    "sanitize_filename",
    "sanitize_text",
    "summary_card_generator",
    "title_card_generator",
    "visual_storage_manager",
    "visual_generation_service",
    "VISUAL_ASSET_SCHEMA_VERSION",
]
