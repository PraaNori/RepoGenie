"""
Repository processing services (Milestone 2).
"""
from .analyzer import (
    EXCLUDED_DIRECTORIES,
    EXCLUDED_EXTENSIONS,
    LANGUAGE_EXTENSION_MAP,
    RepoAnalyzerService,
    repo_analyzer_service,
)
from .architecture_analyzer import (
    ArchitectureAnalyzerService,
    architecture_analyzer_service,
)
from .call_graph_builder import (
    CallGraphBuilder,
    call_graph_builder,
)
from .code_parser import (
    CodeParserService,
    code_parser_service,
)
from .component_classifier import (
    ComponentClassifier,
    component_classifier,
)
from .dependency_resolver import (
    DependencyResolver,
    dependency_resolver,
)
from .entry_point_detector import (
    EntryPointDetector,
    entry_point_detector,
)
from .ingest import (
    CloneExecutionError,
    CloneTimeoutError,
    DestinationExistsError,
    IngestionResult,
    RepoIngestionError,
    RepoIngestionService,
    RepositorySizeExceededError,
    repo_ingestion_service,
)

__all__ = [
    "ArchitectureAnalyzerService",
    "CallGraphBuilder",
    "CloneExecutionError",
    "CloneTimeoutError",
    "CodeParserService",
    "ComponentClassifier",
    "DependencyResolver",
    "DestinationExistsError",
    "EXCLUDED_DIRECTORIES",
    "EXCLUDED_EXTENSIONS",
    "EntryPointDetector",
    "IngestionResult",
    "LANGUAGE_EXTENSION_MAP",
    "RepoAnalyzerService",
    "RepoIngestionError",
    "RepoIngestionService",
    "RepositorySizeExceededError",
    "architecture_analyzer_service",
    "call_graph_builder",
    "code_parser_service",
    "component_classifier",
    "dependency_resolver",
    "entry_point_detector",
    "repo_analyzer_service",
    "repo_ingestion_service",
]
