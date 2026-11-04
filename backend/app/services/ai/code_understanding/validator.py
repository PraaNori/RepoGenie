from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from ..project_understanding.validator import EvidenceValidator, evidence_validator
from .schemas import (
    CodeExplanationItem,
    ComponentInteractionItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge

logger = logging.getLogger(__name__)


class CodeEvidenceValidator:
    """
    Validates repository code-level understanding:
    1. Reuses EvidenceValidator for repository file existence and line number bounds.
    2. Validates referenced function, class, and method names against parsed Tree-sitter AST symbols.
    3. Verifies confirmed interactions against actual static dependency or call-graph edges,
       demoting unsubstantiated claims to inferred (is_confirmed=False).
    4. Distinguishes verified structural facts from conceptual explanations.
    """

    def __init__(self, base_validator: Optional[EvidenceValidator] = None):
        self.base_validator = base_validator or evidence_validator

    def _collect_file_symbols(self, knowledge: RepositoryKnowledge) -> Dict[str, Set[str]]:
        """Maps each normalized file path to its known function, class, and method names."""
        symbols_map: Dict[str, Set[str]] = {}
        if hasattr(knowledge, "code_structure") and knowledge.code_structure:
            for pf in getattr(knowledge.code_structure, "files", []):
                p = pf.file_path.replace("\\", "/").strip().lstrip("/")
                base_name = os.path.basename(p)
                syms: Set[str] = set()

                for f in pf.functions:
                    syms.add(f.name)
                for c in pf.classes:
                    syms.add(c.name)
                    for m in c.methods:
                        syms.add(m)
                        syms.add(f"{c.name}.{m}")
                for m in pf.methods:
                    syms.add(m.name)
                    syms.add(f"{m.parent_class}.{m.name}")

                symbols_map[p] = syms
                symbols_map[base_name] = syms

        return symbols_map

    def _collect_static_edges(
        self, knowledge: RepositoryKnowledge
    ) -> Set[Tuple[str, str]]:
        """Collects all verified internal static dependency and call edges as (source_path, target_path)."""
        static_edges: Set[Tuple[str, str]] = set()

        # 1. Dependency Edges (Imports)
        if hasattr(knowledge, "dependency_information") and knowledge.dependency_information:
            for edge in getattr(knowledge.dependency_information, "edges", []):
                src = edge.source.replace("\\", "/").strip().lstrip("/")
                tgt = edge.target.replace("\\", "/").strip().lstrip("/")
                static_edges.add((src, tgt))
                static_edges.add((os.path.basename(src), os.path.basename(tgt)))

        # 2. Call Graph Edges (Resolved Calls)
        if hasattr(knowledge, "architecture") and knowledge.architecture and knowledge.architecture.call_graph:
            for call_edge in getattr(knowledge.architecture.call_graph, "edges", []):
                caller_file = call_edge.caller.split(":")[0].replace("\\", "/").strip().lstrip("/")
                callee_file = call_edge.callee.split(":")[0].replace("\\", "/").strip().lstrip("/")
                static_edges.add((caller_file, callee_file))
                static_edges.add((os.path.basename(caller_file), os.path.basename(callee_file)))

        # 3. Inheritance Edges
        if hasattr(knowledge, "architecture") and knowledge.architecture:
            for inh in getattr(knowledge.architecture, "inheritance_relationships", []):
                if inh.child_file and inh.parent_file:
                    cf = inh.child_file.replace("\\", "/").strip().lstrip("/")
                    pf = inh.parent_file.replace("\\", "/").strip().lstrip("/")
                    static_edges.add((cf, pf))
                    static_edges.add((os.path.basename(cf), os.path.basename(pf)))

        return static_edges

    def validate_code_understanding(
        self,
        understanding: RepositoryCodeUnderstanding,
        knowledge: RepositoryKnowledge,
        local_path: Optional[str] = None,
    ) -> RepositoryCodeUnderstanding:
        """
        Executes complete static verification of all components, code explanations,
        symbol references, line numbers, and interaction claims.
        """
        known_files, line_counts, has_complete_inventory = (
            self.base_validator.get_repository_inventory_and_line_counts(knowledge, local_path)
        )
        symbols_map = self._collect_file_symbols(knowledge)
        static_edges = self._collect_static_edges(knowledge)

        warnings = list(understanding.validation_warnings)

        # 1. Validate Components & Code Explanations
        for comp in understanding.components:
            comp_norm = comp.file_path.replace("\\", "/").strip().lstrip("/")

            # Validate component file references
            for ev in comp.supporting_evidence:
                if not self.base_validator.validate_reference(
                    ev, known_files, line_counts, has_complete_inventory, local_path
                ):
                    warnings.append(f"Component '{comp.name}': unverified evidence file '{ev.file_path}'.")

            # Validate individual Code Explanations
            comp_syms = symbols_map.get(comp_norm, set()) or symbols_map.get(os.path.basename(comp_norm), set())

            for code_expl in comp.code_explanations:
                # Check symbol name existence in AST
                clean_sym_name = code_expl.name.strip()
                # Check if symbol exists directly or without class prefix (e.g. "invoke" in "Command.invoke")
                bare_sym = clean_sym_name.split(".")[-1]
                symbol_found = (
                    not comp_syms  # If AST has no symbols recorded, do not falsely flag
                    or clean_sym_name in comp_syms
                    or bare_sym in comp_syms
                )

                if not symbol_found:
                    code_expl.confidence = "low"
                    warnings.append(
                        f"Component '{comp.name}': symbol '{code_expl.name}' was not found in parsed AST for file '{code_expl.file_path}'."
                    )

                # Validate line bounds of the code explanation
                if comp_norm in line_counts:
                    max_lines = line_counts[comp_norm]
                    if code_expl.line_start <= 0 or (code_expl.line_end and code_expl.line_end <= 0):
                        warnings.append(f"Code explanation '{code_expl.name}': non-positive line number.")
                    elif code_expl.line_end and code_expl.line_end < code_expl.line_start:
                        warnings.append(f"Code explanation '{code_expl.name}': inverted line range.")
                    elif code_expl.line_start > max_lines or (code_expl.line_end and code_expl.line_end > max_lines):
                        code_expl.confidence = "low"
                        warnings.append(
                            f"Code explanation '{code_expl.name}': line range [{code_expl.line_start}, {code_expl.line_end}] exceeds file total lines ({max_lines})."
                        )

                # Validate supporting evidence for this code explanation
                for ev in code_expl.supporting_evidence:
                    if not self.base_validator.validate_reference(
                        ev, known_files, line_counts, has_complete_inventory, local_path
                    ):
                        warnings.append(f"Code explanation '{code_expl.name}': unverified evidence file '{ev.file_path}'.")

        # 2. Validate Cross-Component Interactions
        for inter in understanding.cross_component_interactions:
            src_norm = inter.source_component.replace("\\", "/").strip().lstrip("/")
            tgt_norm = inter.target_component.replace("\\", "/").strip().lstrip("/")
            src_base = os.path.basename(src_norm)
            tgt_base = os.path.basename(tgt_norm)

            # Check if this interaction was claimed as statically confirmed
            if inter.is_confirmed:
                has_static_edge = (
                    (src_norm, tgt_norm) in static_edges
                    or (src_base, tgt_base) in static_edges
                    or (src_norm, tgt_base) in static_edges
                    or (src_base, tgt_norm) in static_edges
                )

                if not has_static_edge:
                    # Demote to inferred conceptual relationship
                    inter.is_confirmed = False
                    inter.confidence = "medium"
                    warnings.append(
                        f"Interaction '{inter.source_component} -> {inter.target_component}': demoted from confirmed to inferred (no static call or import edge found in repository architecture)."
                    )

            # Validate supporting evidence
            for ev in inter.supporting_evidence:
                if not self.base_validator.validate_reference(
                    ev, known_files, line_counts, has_complete_inventory, local_path
                ):
                    warnings.append(
                        f"Interaction '{inter.source_component} -> {inter.target_component}': unverified evidence file '{ev.file_path}'."
                    )

        understanding.validation_warnings = warnings
        return understanding


code_evidence_validator = CodeEvidenceValidator()
