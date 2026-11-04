from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..project_understanding.schemas import EvidenceReference
from ..schemas import TokenUsageRecord


class CodeExplanationItem(BaseModel):
    """Explains a single important function, method, or class grounded in source code."""
    name: str
    symbol_type: str = "function"  # "function", "method", "class"
    file_path: str
    line_start: int
    line_end: int
    signature: Optional[str] = None
    docstring: Optional[str] = None
    summary: str
    logic_explanation: str
    parameters_and_returns: str
    internal_calls: List[str] = Field(default_factory=list)
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)
    confidence: str = "high"  # "high", "medium", "low"
    is_deterministic: bool = False  # True when generated from static AST metadata only


class ComponentInteractionItem(BaseModel):
    """Explains how two components collaborate, backed by static edges or conceptual analysis."""
    source_component: str
    target_component: str
    interaction_type: str = "calls"  # "calls", "imports", "inherits", "instantiates", "data_flow"
    description: str
    is_confirmed: bool = True  # True ONLY if backed by static DependencyEdge or CallGraphEdge
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)
    confidence: str = "high"


class ComponentUnderstandingItem(BaseModel):
    """Represents architectural and code-level comprehension of a single primary component."""
    component_id: str  # Canonical file path or module ID (e.g. "src/click/core.py")
    name: str  # Descriptive name (e.g. "Command Execution Engine")
    file_path: str
    category: str = "core"  # "entry_point", "core", "service", "parser", "model", "utility"
    importance_score: float = 0.0
    primary_responsibility: str
    why_important: str
    inputs_and_outputs: str
    key_classes_and_functions: List[str] = Field(default_factory=list)
    code_explanations: List[CodeExplanationItem] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    dependents: List[str] = Field(default_factory=list)
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list)
    confidence: str = "high"
    is_deterministic: bool = False


class RepositoryCodeUnderstanding(BaseModel):
    """Consolidated component-level and code-level understanding for the repository."""
    schema_version: str = "1.0"
    repository_name: str
    architecture_overview: str
    components: List[ComponentUnderstandingItem] = Field(default_factory=list)
    cross_component_interactions: List[ComponentInteractionItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""
    is_fallback: bool = False
    latency_ms: float = 0.0
    token_usage: Optional[TokenUsageRecord] = None
    validation_warnings: List[str] = Field(default_factory=list)
