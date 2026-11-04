from __future__ import annotations

import json
import logging
import posixpath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from ....core.config import settings
from .component_selector import ComponentSelector, SelectedComponentCandidate, component_selector
from .snippet_extractor import ExtractedCodeSnippet, SnippetExtractor, snippet_extractor

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..project_understanding.schemas import ProjectUnderstanding

logger = logging.getLogger(__name__)


class CodeEvidenceBuilder:
    """
    Constructs a compact, strictly grounded evidence package for component-level
    and code-level understanding. Combines multi-criteria selected components,
    bounded Tree-sitter snippets, and verified static dependency/call edges.
    """

    MAX_EVIDENCE_CHAR_BUDGET = 6500  # ~1,600 prompt tokens

    def __init__(
        self,
        selector: Optional[ComponentSelector] = None,
        extractor: Optional[SnippetExtractor] = None,
    ):
        self.selector = selector or component_selector
        self.extractor = extractor or snippet_extractor

    def build_evidence_package(
        self,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        local_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Builds grounded evidence payload containing:
        1. Repository & Project Context
        2. Selected Components with Key Symbols & Bounded Snippets
        3. Confirmed Static Component Interactions (import & call edges)
        """
        repo_name = knowledge.repository.name

        # 1. High-level Context
        proj_context: Dict[str, str] = {
            "name": repo_name,
            "description": knowledge.project_overview.description or "",
        }
        if project_understanding and hasattr(project_understanding, "identity"):
            proj_context["short_description"] = project_understanding.identity.short_description
            proj_context["category"] = project_understanding.identity.category
            proj_context["primary_purpose"] = project_understanding.identity.primary_purpose
            if hasattr(project_understanding, "problem_statement"):
                proj_context["problem_solved"] = project_understanding.problem_statement.problem_addressed

        # 2. Select Top Components using Multi-Criteria Ranking
        selected_candidates = self.selector.select_components(knowledge, min_components=3, max_components=6)
        selected_paths: Set[str] = {c.file_path for c in selected_candidates}

        # Index ParsedFiles
        parsed_files_map = {pf.file_path.lstrip("/"): pf for pf in knowledge.code_structure.files}
        for pf in knowledge.code_structure.files:
            parsed_files_map[pf.file_path] = pf

        # 3. Extract Static Dependencies and Confirmed Interactions
        internal_deps_by_source: Dict[str, List[str]] = {}
        confirmed_interactions: List[Dict[str, Any]] = []

        if hasattr(knowledge, "dependency_information") and knowledge.dependency_information:
            for edge in getattr(knowledge.dependency_information, "edges", []):
                src = edge.source.strip().lstrip("/")
                tgt = edge.target.strip().lstrip("/")
                if src in selected_paths:
                    if src not in internal_deps_by_source:
                        internal_deps_by_source[src] = []
                    if tgt not in internal_deps_by_source[src]:
                        internal_deps_by_source[src].append(tgt)

                # Confirmed interaction between selected components
                if src in selected_paths and tgt in selected_paths and src != tgt:
                    ev_file = getattr(edge.evidence, "file_path", src)
                    ev_line = getattr(edge.evidence, "line_number", 1) or 1
                    confirmed_interactions.append({
                        "source": src,
                        "target": tgt,
                        "interaction_type": edge.relationship_type or "imports",
                        "is_confirmed": True,
                        "evidence_file": ev_file,
                        "evidence_line": ev_line,
                        "statement": getattr(edge.evidence, "statement", None),
                    })

        # Static Call Graph Edges between selected components
        if hasattr(knowledge, "architecture") and knowledge.architecture and knowledge.architecture.call_graph:
            for call_edge in getattr(knowledge.architecture.call_graph, "edges", []):
                caller_file = call_edge.caller.split(":")[0].strip().lstrip("/")
                callee_file = call_edge.callee.split(":")[0].strip().lstrip("/")
                if caller_file in selected_paths and callee_file in selected_paths and caller_file != callee_file:
                    ev_file = getattr(call_edge.evidence, "file_path", caller_file)
                    ev_line = getattr(call_edge.evidence, "line_number", 1) or 1
                    confirmed_interactions.append({
                        "source": caller_file,
                        "target": callee_file,
                        "interaction_type": "calls",
                        "is_confirmed": True,
                        "evidence_file": ev_file,
                        "evidence_line": ev_line,
                        "statement": f"{call_edge.caller} -> {call_edge.callee} ({call_edge.call_name})",
                    })

        # Deduplicate confirmed interactions
        deduped_interactions: List[Dict[str, Any]] = []
        seen_inter_keys: Set[Tuple[str, str, str]] = set()
        for ci in confirmed_interactions:
            key = (ci["source"], ci["target"], ci["interaction_type"])
            if key not in seen_inter_keys:
                seen_inter_keys.add(key)
                deduped_interactions.append(ci)

        # 4. Extract Bounded Code Snippets per Component
        seen_snippet_ranges: Set[Tuple[str, int, int]] = set()
        components_payload: List[Dict[str, Any]] = []

        total_snippet_chars = 0

        for cand in selected_candidates:
            pf = parsed_files_map.get(cand.file_path) or parsed_files_map.get(cand.file_path.lstrip("/"))
            snippets = self.extractor.extract_snippets_for_component(
                parsed_file=pf,
                key_symbols=cand.key_symbols,
                local_path=local_path,
                seen_ranges=seen_snippet_ranges,
            )

            snippets_payload: List[Dict[str, Any]] = []
            for snip in snippets:
                if total_snippet_chars + len(snip.formatted_code) > self.extractor.MAX_TOTAL_SNIPPET_CHARS:
                    # Budget limit reached: record exclusion rather than corrupting syntax
                    snippets_payload.append({
                        "name": snip.name,
                        "symbol_type": snip.symbol_type,
                        "line_start": snip.line_start,
                        "line_end": snip.line_end,
                        "docstring": snip.docstring,
                        "omitted": True,
                        "reason": "Omitted to preserve prompt token ceiling.",
                    })
                    continue

                total_snippet_chars += len(snip.formatted_code)
                snip_item: Dict[str, Any] = {
                    "name": snip.name,
                    "symbol_type": snip.symbol_type,
                    "line_start": snip.line_start,
                    "line_end": snip.line_end,
                    "code_with_line_numbers": snip.formatted_code,
                }
                if snip.docstring:
                    snip_item["docstring"] = snip.docstring
                if not snip.is_complete and snip.exclusion_reason:
                    snip_item["exclusion_notice"] = snip.exclusion_reason
                snippets_payload.append(snip_item)

            comp_entry: Dict[str, Any] = {
                "component_id": cand.file_path,
                "name": cand.name,
                "file_path": cand.file_path,
                "category": cand.category,
                "importance_score": cand.score,
                "selection_reason": cand.reason,
                "static_dependencies": internal_deps_by_source.get(cand.file_path, [])[:6],
                "key_symbols": cand.key_symbols,
                "snippets": snippets_payload,
            }
            components_payload.append(comp_entry)

        evidence_package: Dict[str, Any] = {
            "repository": proj_context,
            "components": components_payload,
            "confirmed_static_interactions": deduped_interactions[:12],
        }

        # Measure & log character budget
        serialized = json.dumps(evidence_package)
        logger.info(
            "Built code evidence package: %d components, %d confirmed interactions, %d characters (~%d tokens)",
            len(components_payload),
            len(deduped_interactions),
            len(serialized),
            len(serialized) // 4,
        )

        return evidence_package

    @staticmethod
    def estimate_total_tokens(
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> int:
        """
        Estimates total request tokens (input + output budget) to ensure requests
        remain safely below provider per-minute rate limits (e.g. Groq 8,000 TPM limit).
        """
        input_tokens = (len(system_prompt) + len(user_prompt)) // 4
        return input_tokens + max_output_tokens


code_evidence_builder = CodeEvidenceBuilder()
