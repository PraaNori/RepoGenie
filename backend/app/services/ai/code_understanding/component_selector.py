from __future__ import annotations

import math
import posixpath
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ....models.schemas import (
        ClassInfo,
        FunctionInfo,
        ParsedFile,
        RepositoryKnowledge,
    )


class SelectedComponentCandidate:
    def __init__(
        self,
        file_path: str,
        name: str,
        category: str,
        score: float,
        reason: str,
        key_symbols: List[str],
    ):
        self.file_path = file_path
        self.name = name
        self.category = category
        self.score = score
        self.reason = reason
        self.key_symbols = key_symbols


class ComponentSelector:
    """
    Ranks and selects the most significant components/modules in the repository
    using multi-criteria balancing:
    - Important-file ranking from unified knowledge
    - Entry-point relevance
    - Architectural layer classification
    - Call-graph call site frequency
    - Dependency centrality (logarithmically bounded so high import counts do not dominate)
    - Symbol-level public interface density
    - Package/directory structural diversity
    """

    def select_components(
        self,
        knowledge: RepositoryKnowledge,
        min_components: int = 3,
        max_components: int = 6,
    ) -> List[SelectedComponentCandidate]:
        # Map parsed files for fast lookup
        parsed_files_map: Dict[str, ParsedFile] = {
            pf.file_path: pf for pf in knowledge.code_structure.files
        }
        # Also index by relative normalized paths
        for pf in knowledge.code_structure.files:
            parsed_files_map[pf.file_path.lstrip("/")] = pf

        # 1. Collect Important Files metadata
        important_map: Dict[str, float] = {}
        important_reasons: Dict[str, str] = {}
        for imp in getattr(knowledge, "important_files", []):
            p = imp.relative_path.strip().lstrip("/")
            important_map[p] = imp.score
            important_reasons[p] = imp.reason

        # 2. Collect Entry Points
        entry_points_set: Set[str] = {
            ep.file_path.strip().lstrip("/") for ep in getattr(knowledge, "entry_points", [])
        }

        # 3. Collect Architectural Categories
        arch_categories: Dict[str, str] = {}
        if hasattr(knowledge, "architecture") and knowledge.architecture:
            for comp in getattr(knowledge.architecture, "components", []):
                p = comp.file_path.strip().lstrip("/")
                arch_categories[p] = comp.category

        # 4. Compute Dependency Centrality (in-degree & out-degree)
        dep_in_degree: Counter = Counter()
        dep_out_degree: Counter = Counter()
        if hasattr(knowledge, "dependency_information") and knowledge.dependency_information:
            for edge in getattr(knowledge.dependency_information, "edges", []):
                dep_out_degree[edge.source.strip().lstrip("/")] += 1
                dep_in_degree[edge.target.strip().lstrip("/")] += 1

        # 5. Compute Call Graph Frequency
        call_frequency: Counter = Counter()
        if hasattr(knowledge, "architecture") and knowledge.architecture and knowledge.architecture.call_graph:
            for edge in getattr(knowledge.architecture.call_graph, "edges", []):
                # Caller & Callee node IDs typically formatted as "path/to/file.py:func"
                caller_path = edge.caller.split(":")[0].strip().lstrip("/")
                callee_path = edge.callee.split(":")[0].strip().lstrip("/")
                call_frequency[caller_path] += 1
                call_frequency[callee_path] += 1

        # Candidate pool: all parsed files or architectural components
        all_candidate_paths: Set[str] = set(parsed_files_map.keys())
        all_candidate_paths.update(arch_categories.keys())
        all_candidate_paths.update(important_map.keys())

        scored_candidates: List[Tuple[float, str, str, str, List[str]]] = []

        for p in all_candidate_paths:
            # Skip non-source files or root manifests for component-level code logic
            bname = posixpath.basename(p).lower()
            if bname in (
                "readme.md", "readme.rst", "readme", "pyproject.toml",
                "package.json", "setup.py", "setup.cfg", "cargo.toml",
                "go.mod", "dockerfile", "license",
            ):
                continue
            if bname.startswith(".") or "/." in p:
                continue

            # Compute balanced multi-criteria score
            score = 0.0

            # A. Important File Score
            if p in important_map:
                score += important_map[p] * 1.4
            else:
                score += 2.0

            # B. Entry Point Relevance
            if p in entry_points_set:
                score += 3.0

            # C. Architectural Classification
            cat = arch_categories.get(p, "core")
            if cat in ("entry_point", "api_route"):
                score += 2.5
            elif cat in ("core", "service"):
                score += 2.0
            elif cat in ("parser", "model", "database"):
                score += 1.5
            elif cat == "utility":
                score += 0.5
            elif cat == "test":
                score -= 4.0  # Strongly penalize test files

            # D. Call Graph Frequency (logarithmic boost)
            calls = call_frequency[p]
            if calls > 0:
                score += min(2.5, math.log2(1 + calls) * 0.6)

            # E. Dependency Centrality (logarithmic boost, capped to prevent dominance)
            in_deg = dep_in_degree[p]
            out_deg = dep_out_degree[p]
            score += min(2.0, math.log2(1 + in_deg + out_deg) * 0.4)

            # F. Symbol Density & Key Symbols Selection
            pf = parsed_files_map.get(p)
            key_symbols: List[str] = []
            if pf:
                pub_funcs = [f for f in pf.functions if not f.name.startswith("_") or f.name in ("__init__", "__call__")]
                pub_classes = [c for c in pf.classes if not c.name.startswith("_")]
                score += min(1.5, (len(pub_funcs) + len(pub_classes)) * 0.15)

                # Prioritize classes with most methods or public functions
                for c in sorted(pub_classes, key=lambda x: len(x.methods), reverse=True)[:2]:
                    key_symbols.append(c.name)
                for f in sorted(pub_funcs, key=lambda x: len(x.parameters), reverse=True)[:2]:
                    if f.name not in key_symbols:
                        key_symbols.append(f.name)

            reason = important_reasons.get(p, f"High architectural centrality ({cat}) with {len(key_symbols)} primary symbols.")
            name = self._generate_component_name(p, cat)

            scored_candidates.append((score, p, name, cat, key_symbols, reason))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # Apply package diversity filtering: max 2 components per immediate directory
        selected: List[SelectedComponentCandidate] = []
        dir_counts: Counter = Counter()

        for score, p, name, cat, key_symbols, reason in scored_candidates:
            dirname = posixpath.dirname(p)
            if dir_counts[dirname] >= 2 and len(selected) < min_components:
                # If we haven't reached min_components, allow slight overflow
                pass
            elif dir_counts[dirname] >= 2:
                continue

            dir_counts[dirname] += 1
            selected.append(
                SelectedComponentCandidate(
                    file_path=p,
                    name=name,
                    category=cat,
                    score=round(score, 2),
                    reason=reason,
                    key_symbols=key_symbols[:3],
                )
            )
            if len(selected) >= max_components:
                break

        return selected

    def _generate_component_name(self, file_path: str, category: str) -> str:
        """Derives a human-readable title for the component from its file path."""
        stem = posixpath.splitext(posixpath.basename(file_path))[0]
        cleaned = stem.replace("_", " ").title()
        if category == "entry_point":
            return f"{cleaned} (Entry Point)"
        elif category in ("api_route", "controller"):
            return f"{cleaned} Controller"
        elif category == "service":
            return f"{cleaned} Service"
        elif category == "parser":
            return f"{cleaned} Parser"
        return f"{cleaned} Component"


component_selector = ComponentSelector()
