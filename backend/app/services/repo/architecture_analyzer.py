import logging
import posixpath
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from ...core.config import settings
from ...models.schemas import (
    ArchitectureAnalysisResult,
    ClassReference,
    InheritanceRelationship,
    ParsedFile,
    ParsedRepository,
    RelationshipEvidence,
    RepoAnalysisResult,
    StatusEnum,
)
from .call_graph_builder import call_graph_builder
from .component_classifier import component_classifier
from .dependency_resolver import dependency_resolver
from .entry_point_detector import entry_point_detector

logger = logging.getLogger(__name__)


class ArchitectureAnalyzerService:
    """
    Orchestrates architectural analysis and dependency mapping across parsed repository files.
    Constructs dependency graphs, call graphs, class inheritance/composition hierarchies,
    detects entry points, and classifies components into architectural layers.
    """

    def __init__(
        self,
        max_nodes: int = settings.MAX_GRAPH_NODES,
        max_edges: int = settings.MAX_GRAPH_EDGES,
        max_relationships_per_file: int = settings.MAX_RELATIONSHIPS_PER_FILE,
    ):
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self.max_relationships_per_file = max_relationships_per_file

    def analyze_architecture(
        self,
        job_id: str,
        repo_name: str,
        parsed_repo: ParsedRepository,
        analysis: Optional[RepoAnalysisResult] = None,
        local_path: Optional[str] = None,
    ) -> ArchitectureAnalysisResult:
        """
        Executes complete architectural analysis over parsed AST structures.
        """
        parsed_files = parsed_repo.files
        all_internal_files: Set[str] = {pf.file_path for pf in parsed_files}
        warnings: List[str] = list(parsed_repo.warnings)

        # 1. Dependency Graph
        logger.info("Building module dependency graph for %s (%d files)", repo_name, len(parsed_files))
        dep_graph = dependency_resolver.build_dependency_graph(
            parsed_files=parsed_files,
            all_internal_files=all_internal_files,
        )

        # 2. Function & Method Call Graph
        logger.info("Building function call graph for %s", repo_name)
        call_graph = call_graph_builder.build_call_graph(
            parsed_files=parsed_files,
            all_internal_files=all_internal_files,
        )

        # 3. Class Relationships: Inheritance & References
        logger.info("Analyzing class relationships for %s", repo_name)
        inheritance_rels: List[InheritanceRelationship] = []
        class_references: List[ClassReference] = []

        # Index internal classes: class_name -> file_path
        class_to_file: Dict[str, str] = {}
        for pf in parsed_files:
            for cls in pf.classes:
                class_to_file[cls.name] = pf.file_path

        # Class relationships extraction
        for pf in parsed_files:
            file_rels_count = 0

            # A. Inheritance
            for cls in pf.classes:
                for base in cls.base_classes:
                    clean_base = base.split(".")[-1]
                    parent_file = class_to_file.get(clean_base) or class_to_file.get(base)
                    is_internal = parent_file is not None

                    if file_rels_count < self.max_relationships_per_file:
                        file_rels_count += 1
                        inheritance_rels.append(
                            InheritanceRelationship(
                                child_class=cls.name,
                                child_file=pf.file_path,
                                parent_class=base,
                                parent_file=parent_file,
                                relationship_type="inherits",
                                resolution_status="resolved_internal" if is_internal else "external_or_unresolved",
                                evidence=RelationshipEvidence(
                                    evidence_type="class_inheritance",
                                    statement=f"class {cls.name}({base})",
                                    file_path=pf.file_path,
                                    line_number=cls.location.start_line,
                                    confidence="high" if is_internal else "medium",
                                ),
                            )
                        )

            # B. Class References (Instantiations and Type Annotations)
            known_classes = set(class_to_file.keys())
            ref_seen: Set[Tuple[str, str, str]] = set()

            # Instantiations via function calls
            for call in pf.function_calls:
                call_target = call.call_name.split(".")[-1]
                if call_target in known_classes and call_target != call.enclosing_scope:
                    ref_key = (pf.file_path, call_target, "instantiation")
                    if ref_key not in ref_seen and file_rels_count < self.max_relationships_per_file:
                        ref_seen.add(ref_key)
                        file_rels_count += 1
                        class_references.append(
                            ClassReference(
                                source_class=call.enclosing_scope.split(".")[0] if (call.enclosing_scope and "." in call.enclosing_scope) else None,
                                source_file=pf.file_path,
                                referenced_class=call_target,
                                referenced_file=class_to_file.get(call_target),
                                reference_type="instantiation",
                                evidence=RelationshipEvidence(
                                    evidence_type="instantiation",
                                    statement=f"Instantiates {call_target}()",
                                    file_path=pf.file_path,
                                    line_number=call.line_number,
                                    confidence="high",
                                ),
                            )
                        )

            # Type annotations in functions and methods
            for func in pf.functions:
                for param in func.parameters:
                    for cls_name in known_classes:
                        if cls_name in param:
                            ref_key = (pf.file_path, cls_name, "type_annotation")
                            if ref_key not in ref_seen and file_rels_count < self.max_relationships_per_file:
                                ref_seen.add(ref_key)
                                file_rels_count += 1
                                class_references.append(
                                    ClassReference(
                                        source_class=None,
                                        source_file=pf.file_path,
                                        referenced_class=cls_name,
                                        referenced_file=class_to_file.get(cls_name),
                                        reference_type="type_annotation",
                                        evidence=RelationshipEvidence(
                                            evidence_type="type_annotation",
                                            statement=f"Parameter typed with {cls_name} in {func.name}()",
                                            file_path=pf.file_path,
                                            line_number=func.location.start_line,
                                            confidence="high",
                                        ),
                                    )
                                )

        # 4. Entry Point Detection
        logger.info("Detecting entry points for %s", repo_name)
        entry_points = entry_point_detector.detect_entry_points(
            parsed_files=parsed_files,
            local_path=local_path,
            analysis=analysis,
        )

        # 5. Component Classification
        logger.info("Classifying architectural components for %s", repo_name)
        components = component_classifier.classify_components(
            parsed_files=parsed_files,
            entry_points=entry_points,
            analysis=analysis,
        )

        # Component counts summary
        category_counts = Counter(comp.category for comp in components)
        component_counts_dict: Dict[str, int] = dict(category_counts)

        return ArchitectureAnalysisResult(
            job_id=job_id,
            repository_name=repo_name,
            dependency_graph=dep_graph,
            call_graph=call_graph,
            inheritance_relationships=inheritance_rels,
            class_references=class_references,
            entry_points=entry_points,
            components=components,
            component_counts=component_counts_dict,
            analysis_status=StatusEnum.COMPLETED,
            warnings=warnings,
        )


architecture_analyzer_service = ArchitectureAnalyzerService()
