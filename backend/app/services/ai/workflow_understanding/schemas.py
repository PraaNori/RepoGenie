from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from ..project_understanding.schemas import EvidenceReference
from ..schemas import TokenUsageRecord


class WorkflowComponentReference(BaseModel):
    """References a participating component using canonical repository paths."""
    component_id: str                      # Canonical file path, e.g. "src/click/core.py"
    name: str                              # Descriptive component name, e.g. "Command Execution Engine"
    role_in_workflow: str                  # e.g. "Command dispatcher and option coordinator"


class CallSiteEvidence(BaseModel):
    """
    Unambiguous caller/callee identities separating directional graph edges
    from physical call-site expressions at specific source locations.
    """
    caller_file: str                       # e.g. "src/click/core.py"
    caller_symbol: str                     # e.g. "Command.invoke"
    callee_file: str                       # e.g. "src/click/types.py"
    callee_symbol: str                     # e.g. "ParamType.convert"
    call_name: str                         # Exact call token, e.g. "convert"
    call_site_line: int                    # 1-indexed source line number of call expression
    call_site_column: Optional[int] = None # 1-indexed column offset of call expression

    call_graph_edge_id: str                # "{caller_file}:{caller_symbol}->{callee_file}:{callee_symbol}"
    call_site_id: str                      # "{caller_file}:{caller_symbol}->{callee_file}:{callee_symbol}@{line}:{col}"

    is_edge_verified: bool = False         # True ONLY if verified against CallGraph.edges
    is_site_location_verified: bool = False# True ONLY if verified against ParsedFile.function_calls at line
    evidence_reference: Optional[EvidenceReference] = None

    @classmethod
    def format_edge_id(
        cls,
        caller_file: str,
        caller_symbol: str,
        callee_file: str,
        callee_symbol: str,
    ) -> str:
        """Constructs a deterministic edge ID connecting caller and callee symbols."""
        c_file = caller_file.replace("\\", "/").strip().lstrip("/")
        ce_file = callee_file.replace("\\", "/").strip().lstrip("/")
        return f"{c_file}:{caller_symbol}->{ce_file}:{callee_symbol}"

    @classmethod
    def format_site_id(
        cls,
        caller_file: str,
        caller_symbol: str,
        callee_file: str,
        callee_symbol: str,
        line: int,
        col: Optional[int] = None,
    ) -> str:
        """Constructs a deterministic call-site ID capturing source location."""
        edge_id = cls.format_edge_id(caller_file, caller_symbol, callee_file, callee_symbol)
        col_str = str(col) if col is not None else "0"
        return f"{edge_id}@{line}:{col_str}"


class WorkflowStep(BaseModel):
    """An ordered step in an application execution path."""
    step_number: int = Field(..., ge=1)
    title: str = Field(..., max_length=80)
    component_id: str
    symbol_name: Optional[str] = None
    action_type: str = "call"              # "entry", "call", "transformation", "storage_io", "external_api", "response"
    description: str = Field(..., max_length=300)
    data_received: Optional[str] = Field(None, max_length=150)
    data_produced: Optional[str] = Field(None, max_length=150)
    next_step: Optional[int] = None

    # Multi-dimensional verification (transition to next step)
    call_relationship_verified: bool = False   # True ONLY if call_graph_edge_id is verified
    source_order_verified: bool = False        # True ONLY if calls share the same caller and Line(A) < Line(B)
    same_execution_path_verified: bool = False # True if at least one statically valid path contains both calls
    execution_guaranteed: bool = False         # True ONLY if B is guaranteed to execute whenever A executes
    runtime_execution_verified: bool = False   # ALWAYS False (RepoGenie does not execute code)

    call_evidence: Optional[CallSiteEvidence] = None
    unresolved_aspects: List[str] = Field(default_factory=list, max_length=5)
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list, max_length=2)
    confidence: str = "high"                   # "high", "medium", "low"
    is_deterministic: bool = False

    @field_validator("runtime_execution_verified")
    @classmethod
    def validate_runtime_execution_verified(cls, v: bool) -> bool:
        if v is True:
            raise ValueError(
                "runtime_execution_verified must always be False because RepoGenie does not execute or profile repository code."
            )
        return False


class DataTransformation(BaseModel):
    """Explains a concrete transformation performed on application data."""
    transformation_name: str = Field(..., max_length=80)
    performed_by_component: str
    performed_by_symbol: Optional[str] = None

    transformation_verified: bool = False      # True ONLY if verified by AST expression, assignment, or coercion
    data_relationship_status: str = "inferred" # "observed", "inferred", "unknown_or_unresolved"
    observed_operation: Optional[str] = Field(None, max_length=150)

    input_format_or_type: str = Field(..., max_length=100)
    output_format_or_type: str = Field(..., max_length=100)
    transformation_logic: str = Field(..., max_length=250)
    supporting_evidence: List[EvidenceReference] = Field(default_factory=list, max_length=2)
    confidence: str = "high"


class DataFlow(BaseModel):
    """Traces data origin, transformations, storage, and destination."""
    flow_id: str
    workflow_id: str
    data_item_name: str = Field(..., max_length=80)
    origin: WorkflowComponentReference
    destination: WorkflowComponentReference
    data_relationship_status: str = "inferred" # "observed", "inferred", "unknown_or_unresolved"
    lifecycle_stages: List[str] = Field(default_factory=list, max_length=5)
    transformations: List[DataTransformation] = Field(default_factory=list, max_length=2)

    # Operation-based storage verification
    storage_library_detected: bool = False
    storage_operation_verified: bool = False   # True only if AST evidence confirms actual write/read
    storage_operation_type: str = "none"       # "read", "write", "delete", "none"
    persistence_status: str = "no_storage_operation_detected"
    persistence_detail: Optional[str] = Field(None, max_length=200)

    # Operation-based external API verification
    external_api_library_detected: bool = False
    external_api_operation_verified: bool = False
    external_api_operation_type: str = "none"  # "http_request", "none"
    external_api_status: str = "no_external_api_operation_detected"
    external_api_detail: Optional[str] = Field(None, max_length=200)

    confidence: str = "high"


class ApplicationWorkflow(BaseModel):
    """An end-to-end application workflow."""
    workflow_id: str
    name: str = Field(..., max_length=100)
    category: str = "user_request"             # "user_request", "api_handling", "initialization", "business_logic", "data_storage", "background_job", "auth"
    description: str = Field(..., max_length=400)
    trigger: str = Field(..., max_length=150)
    entry_point: WorkflowComponentReference
    participating_components: List[WorkflowComponentReference] = Field(default_factory=list, max_length=5)
    steps: List[WorkflowStep] = Field(default_factory=list, max_length=5)
    data_flows: List[DataFlow] = Field(default_factory=list, max_length=2)
    final_outcome: str = Field(..., max_length=200)

    # Summary verification (derived from constituent steps)
    call_relationships_fully_verified: bool = False
    source_order_verified: bool = False        # True only if all intra-caller transitions have source_order_verified
    same_execution_path_verified: bool = False # True only if all step transitions have same_execution_path_verified
    execution_guaranteed: bool = False         # True only if all step transitions have execution_guaranteed
    runtime_execution_verified: bool = False   # ALWAYS False

    unresolved_aspects: List[str] = Field(default_factory=list, max_length=5)
    alternative_paths_detected: List[str] = Field(default_factory=list, max_length=3)

    confidence: str = "high"
    is_deterministic: bool = False

    @field_validator("runtime_execution_verified")
    @classmethod
    def validate_workflow_runtime_execution(cls, v: bool) -> bool:
        if v is True:
            raise ValueError(
                "runtime_execution_verified must always be False because RepoGenie does not execute or profile repository code."
            )
        return False


class StructuralCallChain(BaseModel):
    """Deterministic static call chain generated when fallback is active or candidates are omitted."""
    chain_id: str
    entry_symbol: str
    entry_file: str
    steps: List[WorkflowStep] = Field(default_factory=list, max_length=5)
    unresolved_reason: str = "Static call chain generated from CallGraph; semantic AI workflow was omitted or unavailable."


class RepositoryWorkflowUnderstanding(BaseModel):
    """Top-level container for discovered workflows and data flows."""
    schema_version: str = "1.0"
    repository_name: str
    system_architecture_type: str
    workflow_summary: str = Field(..., max_length=500)
    workflows: List[ApplicationWorkflow] = Field(default_factory=list, max_length=2)

    # Separated deterministic structural chains & omitted candidates
    structural_call_chains: List[StructuralCallChain] = Field(default_factory=list, max_length=2)
    omitted_candidate_workflows: List[str] = Field(default_factory=list)
    is_incomplete: bool = False

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""
    is_fallback: bool = False
    latency_ms: float = 0.0
    token_usage: Optional[TokenUsageRecord] = None
    validation_warnings: List[str] = Field(default_factory=list)
