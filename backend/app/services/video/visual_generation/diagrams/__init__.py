"""
Diagram generation package for Milestone 5, Phase 5.2.
"""

from .base import (
    BaseDiagramGenerator,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    DiagramGenerationResult,
    DiagramType,
    extract_component_identifiers,
    extract_workflow_step_identifiers,
    sanitize_filename,
    sanitize_text,
)
from .renderer import DiagramRenderer, diagram_renderer
from .architecture import ArchitectureDiagramGenerator
from .component import ComponentDiagramGenerator
from .workflow import WorkflowDiagramGenerator
from .data_flow import DataFlowDiagramGenerator

__all__ = [
    "BaseDiagramGenerator",
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "DiagramGenerationResult",
    "DiagramType",
    "DiagramRenderer",
    "diagram_renderer",
    "ArchitectureDiagramGenerator",
    "ComponentDiagramGenerator",
    "WorkflowDiagramGenerator",
    "DataFlowDiagramGenerator",
    "extract_component_identifiers",
    "extract_workflow_step_identifiers",
    "sanitize_filename",
    "sanitize_text",
]
