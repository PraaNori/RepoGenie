from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..services.ai.project_understanding.schemas import ProjectUnderstanding

class StageEnum(str, Enum):
    REPO_FETCHING = "Repository Fetching"
    REPO_ANALYSIS = "Repository Analysis"
    CODE_UNDERSTANDING = "Code Understanding"
    AI_SUMMARY = "AI Summary Generation"
    SCRIPT_GENERATION = "Script Generation"
    STORYBOARD_GENERATION = "Storyboard Generation"
    VISUAL_GENERATION = "Visual Generation"
    VOICE_GENERATION = "Voice Generation"
    VIDEO_ASSEMBLY = "Video Assembly"

class StatusEnum(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class StageInfo(BaseModel):
    id: int
    name: str
    status: StatusEnum = StatusEnum.PENDING
    detail: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str
    version: str
    environment: str
    timestamp: datetime

class JobCreateRequest(BaseModel):
    github_url: str = Field(..., description="Public GitHub repository URL (e.g. https://github.com/owner/repo)")

class VideoResult(BaseModel):
    repo_name: str
    repo_url: str
    description: str
    tech_stack: List[str]
    summary: str
    video_url: Optional[str] = None
    duration_seconds: Optional[int] = None

# --- Milestone 2.3: Repository Structure & File Analysis Models ---

class LanguageStat(BaseModel):
    name: str
    file_count: int
    percentage: float  # e.g., 68.5

class DependencyItem(BaseModel):
    name: str
    version_spec: Optional[str] = None
    source_file: str

class ManifestInfo(BaseModel):
    file_path: str
    ecosystem: str
    dependencies_count: int
    dependencies: List[DependencyItem] = []

class ConfigurationFileInfo(BaseModel):
    file_path: str
    config_type: str  # e.g. "docker", "ci_cd", "environment_template", "build_tool", "lint_format"

class DirectoryTreeNode(BaseModel):
    name: str
    path: str  # relative to repository root
    type: str  # "file" or "directory"
    size_bytes: Optional[int] = None
    extension: Optional[str] = None
    children: Optional[List["DirectoryTreeNode"]] = None

DirectoryTreeNode.model_rebuild()

class RepoStatistics(BaseModel):
    total_files: int
    total_directories: int
    source_files: int
    filtered_files: int
    total_size_bytes: int
    configuration_files: int
    dependency_manifests: int
    recognized_languages_count: int

class RepoAnalysisResult(BaseModel):
    repository_name: str
    directory_tree: DirectoryTreeNode
    statistics: RepoStatistics
    languages: List[LanguageStat]
    dependency_files: List[ManifestInfo]
    configuration_files: List[ConfigurationFileInfo]
    analysis_status: StatusEnum = StatusEnum.COMPLETED
    warnings: List[str] = []

# --- Milestone 2.4: Code Parsing & Structural Extraction Models ---

class SourceLocation(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    start_column: int
    end_column: int

class ParsingWarning(BaseModel):
    file_path: str
    line_number: Optional[int] = None
    message: str
    warning_type: str

class FunctionInfo(BaseModel):
    name: str
    file_path: str
    location: SourceLocation
    parameters: List[str] = []
    is_async: bool = False
    visibility: Optional[str] = None
    return_type: Optional[str] = None
    enclosing_scope: Optional[str] = None
    snippet: Optional[str] = None

class MethodInfo(BaseModel):
    name: str
    parent_class: str
    file_path: str
    location: SourceLocation
    parameters: List[str] = []
    is_async: bool = False
    visibility: Optional[str] = None
    return_type: Optional[str] = None
    snippet: Optional[str] = None

class ClassInfo(BaseModel):
    name: str
    file_path: str
    location: SourceLocation
    base_classes: List[str] = []
    methods: List[str] = []
    nested_classes: List[str] = []
    snippet: Optional[str] = None

class ImportInfo(BaseModel):
    module: str
    symbols: List[str] = []
    alias: Optional[str] = None
    file_path: str
    line_number: int

class FunctionCallInfo(BaseModel):
    call_name: str
    enclosing_scope: Optional[str] = None
    file_path: str
    line_number: int
    column_number: Optional[int] = None

class ParsedFile(BaseModel):
    file_path: str
    language: str
    status: str  # "success", "syntax_error", "skipped", "error"
    functions: List[FunctionInfo] = []
    classes: List[ClassInfo] = []
    methods: List[MethodInfo] = []
    imports: List[ImportInfo] = []
    function_calls: List[FunctionCallInfo] = []
    warnings: List[ParsingWarning] = []
    total_lines: int = 0

class ParsedRepository(BaseModel):
    job_id: str
    repository_name: str
    total_parsed_files: int
    total_functions: int
    total_classes: int
    total_methods: int
    total_imports: int
    total_function_calls: int
    supported_languages: List[str]
    files: List[ParsedFile] = []
    parsing_status: StatusEnum = StatusEnum.COMPLETED
    warnings: List[str] = []

# --- Milestone 2.5: Architecture & Dependency Relationship Analysis Models ---

class RelationshipEvidence(BaseModel):
    evidence_type: str  # "import_statement", "function_call", "class_inheritance", "instantiation", "type_annotation", "main_guard", "configuration"
    statement: Optional[str] = None
    file_path: str
    line_number: Optional[int] = None
    confidence: str = "high"  # "high", "medium", "low"

class DependencyNode(BaseModel):
    id: str  # repository-relative file path or external package name
    label: str
    node_type: str  # "internal_file", "external_package", "unresolved"
    language: Optional[str] = None

class DependencyEdge(BaseModel):
    source: str
    target: str
    relationship_type: str = "imports"  # "imports", "re_exports"
    is_internal: bool
    resolution_status: str  # "resolved_internal", "external_package", "unresolved"
    evidence: RelationshipEvidence

class DependencyGraph(BaseModel):
    nodes: List[DependencyNode] = []
    edges: List[DependencyEdge] = []
    total_internal_dependencies: int = 0
    total_external_dependencies: int = 0
    total_unresolved_dependencies: int = 0
    circular_dependencies: List[List[str]] = []

class CallGraphNode(BaseModel):
    id: str  # "path/to/file.py:scope.function"
    name: str
    file_path: str
    enclosing_class: Optional[str] = None

class CallGraphEdge(BaseModel):
    caller: str
    callee: str
    call_name: str
    resolution_status: str  # "resolved_internal", "external_or_unresolved"
    evidence: RelationshipEvidence

class CallGraph(BaseModel):
    nodes: List[CallGraphNode] = []
    edges: List[CallGraphEdge] = []
    total_resolved_calls: int = 0
    total_unresolved_calls: int = 0

class InheritanceRelationship(BaseModel):
    child_class: str
    child_file: str
    parent_class: str
    parent_file: Optional[str] = None
    relationship_type: str = "inherits"  # "inherits", "implements", "extends"
    resolution_status: str = "resolved_internal"  # "resolved_internal", "external_or_unresolved"
    evidence: RelationshipEvidence

class ClassReference(BaseModel):
    source_class: Optional[str] = None
    source_file: str
    referenced_class: str
    referenced_file: Optional[str] = None
    reference_type: str  # "instantiation", "type_annotation", "usage"
    evidence: RelationshipEvidence

class EntryPointCandidate(BaseModel):
    file_path: str
    entry_type: str  # "python_main_guard", "application_entry_file", "framework_app_instance", "java_main_method", "go_main", "rust_main", "c_cpp_main", "package_script", "docker_entrypoint"
    symbol_or_command: Optional[str] = None
    confidence: str  # "high", "medium", "low"
    evidence: List[RelationshipEvidence] = []

class ArchitecturalComponent(BaseModel):
    file_path: str
    category: str  # "entry_point", "api_route", "service", "repository_or_dao", "model", "database", "frontend", "utility", "test", "configuration", "external_integration", "unknown"
    confidence: str  # "high", "medium", "low"
    evidence: List[str] = []

class ArchitectureAnalysisResult(BaseModel):
    job_id: str
    repository_name: str
    dependency_graph: DependencyGraph
    call_graph: CallGraph
    inheritance_relationships: List[InheritanceRelationship] = []
    class_references: List[ClassReference] = []
    entry_points: List[EntryPointCandidate] = []
    components: List[ArchitecturalComponent] = []
    component_counts: Dict[str, int] = {}
    analysis_status: StatusEnum = StatusEnum.COMPLETED
    warnings: List[str] = []

# --- Milestone 2.6: Unified Repository Knowledge Representation Models ---

class TechnologyItem(BaseModel):
    name: str
    category: str  # "language", "framework", "library", "database", "tool", "deployment"
    version: Optional[str] = None
    confidence: str = "high"  # "high", "medium", "low"
    detection_source: str  # "manifest", "configuration", "language_detection", "code_import", "framework_instance"
    is_confirmed: bool = True  # True for observed/active signals, False for inferred declarations

class TechnologyStack(BaseModel):
    languages: List[TechnologyItem] = []
    frameworks: List[TechnologyItem] = []
    libraries: List[TechnologyItem] = []
    databases: List[TechnologyItem] = []
    tools: List[TechnologyItem] = []
    deployment_technologies: List[TechnologyItem] = []

class RepositoryMetadataInfo(BaseModel):
    name: str
    owner: str
    repository_url: str
    clone_url: Optional[str] = None
    clone_status: StatusEnum = StatusEnum.COMPLETED
    size_mb: float = 0.0
    file_count: int = 0
    description: Optional[str] = None

class ProjectOverviewInfo(BaseModel):
    readme_available: bool = False
    readme_path: Optional[str] = None
    description: Optional[str] = None
    features: List[str] = []
    limitations: List[str] = []
    documentation_warnings: List[str] = []

class ImportantFileInfo(BaseModel):
    relative_path: str
    category: str  # "readme", "entry_point", "manifest", "configuration", "api_route", "service", "model", "database", "test"
    score: float  # Numerical priority rank (higher = more central)
    reason: str
    evidence: str
    confidence: str = "high"  # "high", "medium", "low"

class SourceEvidenceRecord(BaseModel):
    file_path: str
    start_line: int
    end_line: Optional[int] = None
    evidence_type: str  # "import_statement", "function_call", "class_inheritance", "instantiation", "type_annotation", "main_guard", "configuration", "manifest_dependency", "documentation"
    symbol_or_statement: str
    confidence: str = "high"  # "high", "medium", "low"
    analysis_stage: str  # "repo_structure", "code_parsing", "architecture_analysis", "documentation"
    status: str = "statically_resolved"  # "observed", "statically_resolved", "inferred", "unresolved"

class RepositoryStructureOverview(BaseModel):
    total_directories: int = 0
    total_files: int = 0
    important_directories: List[str] = []
    directory_tree: Optional[DirectoryTreeNode] = None

class UnifiedStatistics(BaseModel):
    total_files: int = 0
    source_files: int = 0
    filtered_files: int = 0
    total_lines_of_code: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_methods: int = 0
    total_imports: int = 0
    total_function_calls: int = 0
    total_internal_dependencies: int = 0
    total_external_dependencies: int = 0
    circular_dependencies_count: int = 0

class CodeStructureSummary(BaseModel):
    parsed_files_count: int = 0
    supported_languages: List[str] = []
    files: List[ParsedFile] = []

class ArchitectureSummary(BaseModel):
    dependency_graph: DependencyGraph
    call_graph: CallGraph
    inheritance_relationships: List[InheritanceRelationship] = []
    class_references: List[ClassReference] = []
    components: List[ArchitecturalComponent] = []
    component_counts: Dict[str, int] = {}

class KnowledgeAnalysisMetadata(BaseModel):
    analysis_status: StatusEnum = StatusEnum.COMPLETED
    created_at: datetime
    stages_completed: List[str] = []

class RepositoryKnowledge(BaseModel):
    schema_version: str = "1.0"
    repository: RepositoryMetadataInfo
    project_overview: ProjectOverviewInfo
    technology_stack: TechnologyStack
    repository_structure: RepositoryStructureOverview
    statistics: UnifiedStatistics
    dependency_information: DependencyGraph
    code_structure: CodeStructureSummary
    architecture: ArchitectureSummary
    entry_points: List[EntryPointCandidate] = []
    important_files: List[ImportantFileInfo] = []
    source_evidence: List[SourceEvidenceRecord] = []
    warnings: List[str] = []
    analysis_metadata: KnowledgeAnalysisMetadata

# --- Main Job Models ---

class JobResponse(BaseModel):
    job_id: str
    repo_url: str
    repo_name: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    clone_url: Optional[str] = None
    ingestion_status: StatusEnum = StatusEnum.PENDING
    status: StatusEnum
    current_stage: str
    progress_percentage: int
    stages: List[StageInfo]
    created_at: datetime
    updated_at: datetime
    analysis: Optional[RepoAnalysisResult] = None
    code_analysis: Optional[ParsedRepository] = None
    architecture: Optional[ArchitectureAnalysisResult] = None
    knowledge: Optional[RepositoryKnowledge] = None
    project_understanding: Optional[ProjectUnderstanding] = None
    has_code_understanding: bool = False
    result: Optional[VideoResult] = None
    error: Optional[str] = None
