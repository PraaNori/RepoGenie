"""
Video Assembly Input Package (Milestone 5, Phase 5.6).

Exports models and services for pre-assembly packaging and physical asset validation.
"""

from .schemas import (
    AssemblyAssetReference,
    AssemblyIssueSeverity,
    AssemblyReadinessReport,
    AssemblyReadinessStatus,
    AssemblyScene,
    AssemblyValidationIssue,
    VideoAssemblyInput,
)
from .validator import AssemblyPreflightValidator, preflight_validator
from .service import AssemblyInputService, assembly_input_service

__all__ = [
    "AssemblyAssetReference",
    "AssemblyIssueSeverity",
    "AssemblyReadinessReport",
    "AssemblyReadinessStatus",
    "AssemblyScene",
    "AssemblyValidationIssue",
    "VideoAssemblyInput",
    "AssemblyPreflightValidator",
    "preflight_validator",
    "AssemblyInputService",
    "assembly_input_service",
]
