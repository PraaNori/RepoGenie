from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, Optional, Set, Tuple

if TYPE_CHECKING:
    from ....models.schemas import DirectoryTreeNode, RepositoryKnowledge
from .schemas import EvidenceReference, ProjectUnderstanding


class EvidenceValidator:
    """
    Validates every EvidenceReference in a ProjectUnderstanding against actual
    repository knowledge. Ensures referenced files actually exist and line numbers
    are well-formed. Marks fabricated or missing references as invalid/unverified.
    """

    def _traverse_directory_tree(self, node: Any, known_files: Set[str]) -> None:
        """Recursively traverses a DirectoryTreeNode hierarchy to collect all relative file paths."""
        if not node:
            return
        if getattr(node, "type", "") == "file":
            rel_path = getattr(node, "path", "")
            if rel_path:
                norm = rel_path.replace("\\", "/").strip().lstrip("/")
                known_files.add(norm)
                known_files.add(os.path.basename(norm))
        children = getattr(node, "children", None)
        if children:
            for child in children:
                self._traverse_directory_tree(child, known_files)

    def get_repository_inventory_and_line_counts(
        self,
        knowledge: RepositoryKnowledge,
        local_path: Optional[str] = None,
    ) -> Tuple[Set[str], Dict[str, int], bool]:
        """
        Builds the repository file index and known line counts from all available sources:
        1. Complete directory tree from repository structure analysis (Milestone 2.3).
        2. Cloned repository files on local disk (if local_path is accessible).
        3. Parsed code structure files and their total line counts (Milestone 2.4).
        4. Curated lists (important files, entry points, architectural components, manifests).
        
        Returns:
            (known_files, line_counts, has_complete_inventory)
        """
        known_files: Set[str] = set()
        line_counts: Dict[str, int] = {}
        has_complete_inventory = False

        # 1. Directory Tree from Repository Structure Analysis (Milestone 2.3)
        if (
            hasattr(knowledge, "repository_structure")
            and knowledge.repository_structure
            and getattr(knowledge.repository_structure, "directory_tree", None) is not None
        ):
            tree = knowledge.repository_structure.directory_tree
            before_count = len(known_files)
            self._traverse_directory_tree(tree, known_files)
            if len(known_files) > before_count:
                has_complete_inventory = True

        # 2. Local cloned repository files on disk (if available)
        if local_path and os.path.isdir(local_path):
            has_complete_inventory = True
            try:
                for root, _, files in os.walk(local_path):
                    if "/.git" in root.replace("\\", "/") or root.replace("\\", "/").endswith("/.git"):
                        continue
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, local_path).replace("\\", "/").strip().lstrip("/")
                        known_files.add(rel_path)
                        known_files.add(file)
            except Exception:
                pass

        # 3. Code structure parsed files & line counts (Milestone 2.4)
        if hasattr(knowledge, "code_structure") and knowledge.code_structure:
            for cf in getattr(knowledge.code_structure, "files", []):
                fp = getattr(cf, "file_path", None) or getattr(cf, "relative_path", None)
                if fp:
                    norm = fp.replace("\\", "/").strip().lstrip("/")
                    known_files.add(norm)
                    known_files.add(os.path.basename(norm))
                    lines = getattr(cf, "total_lines", 0)
                    if lines > 0:
                        line_counts[norm] = lines
                        line_counts[os.path.basename(norm)] = lines

        # 4. Standard root files & documentation
        if hasattr(knowledge, "project_overview") and knowledge.project_overview:
            if knowledge.project_overview.readme_path:
                p = knowledge.project_overview.readme_path.replace("\\", "/").strip().lstrip("/")
                known_files.add(p)
                known_files.add(os.path.basename(p))

        for root_name in (
            "README.md",
            "README.rst",
            "README",
            "pyproject.toml",
            "package.json",
            "setup.py",
            "setup.cfg",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "Dockerfile",
            "tsconfig.json",
            "Makefile",
            "LICENSE",
        ):
            known_files.add(root_name)

        # 5. Important files
        for f in getattr(knowledge, "important_files", []):
            if hasattr(f, "relative_path") and f.relative_path:
                p = f.relative_path.replace("\\", "/").strip().lstrip("/")
                known_files.add(p)
                known_files.add(os.path.basename(p))

        # 6. Entry points
        for ep in getattr(knowledge, "entry_points", []):
            if hasattr(ep, "file_path") and ep.file_path:
                p = ep.file_path.replace("\\", "/").strip().lstrip("/")
                known_files.add(p)
                known_files.add(os.path.basename(p))

        # 7. Source evidence records
        for ev in getattr(knowledge, "source_evidence", []):
            if hasattr(ev, "file_path") and ev.file_path:
                p = ev.file_path.replace("\\", "/").strip().lstrip("/")
                known_files.add(p)
                known_files.add(os.path.basename(p))

        # 8. Architectural components
        if hasattr(knowledge, "architecture") and knowledge.architecture:
            for comp in getattr(knowledge.architecture, "components", []):
                if hasattr(comp, "file_path") and comp.file_path:
                    p = comp.file_path.replace("\\", "/").strip().lstrip("/")
                    known_files.add(p)
                    known_files.add(os.path.basename(p))

        # 9. Dependency nodes
        if hasattr(knowledge, "dependency_information") and knowledge.dependency_information:
            for node in getattr(knowledge.dependency_information, "nodes", []):
                if hasattr(node, "file_path") and node.file_path:
                    p = node.file_path.replace("\\", "/").strip().lstrip("/")
                    known_files.add(p)
                    known_files.add(os.path.basename(p))

        return known_files, line_counts, has_complete_inventory

    def get_known_repository_files(self, knowledge: RepositoryKnowledge) -> Set[str]:
        """Backward-compatible helper returning known files set."""
        known, _, _ = self.get_repository_inventory_and_line_counts(knowledge)
        return known

    def _get_file_line_count(
        self,
        file_path: str,
        local_path: Optional[str],
        line_counts: Dict[str, int],
    ) -> Optional[int]:
        """Retrieves total line count for a file from AST cache or disk."""
        norm_path = file_path.replace("\\", "/").strip().lstrip("/")
        base_name = os.path.basename(norm_path)

        if norm_path in line_counts:
            return line_counts[norm_path]
        if base_name in line_counts:
            return line_counts[base_name]

        # Check local disk if available
        if local_path and os.path.isdir(local_path):
            candidates = [
                os.path.join(local_path, norm_path),
            ]
            for cand in candidates:
                if os.path.isfile(cand):
                    try:
                        with open(cand, "rb") as f:
                            count = sum(1 for _ in f)
                        line_counts[norm_path] = count
                        return count
                    except Exception:
                        pass
        return None

    def validate_reference(
        self,
        ref: EvidenceReference,
        known_files: Set[str],
        line_counts: Optional[Dict[str, int]] = None,
        has_complete_inventory: bool = True,
        local_path: Optional[str] = None,
    ) -> bool:
        """
        Validates an EvidenceReference against known files and line count limits.
        Distinguishes between path verification and line range verification.
        """
        if line_counts is None:
            line_counts = {}

        norm_path = ref.file_path.replace("\\", "/").strip().lstrip("/")
        base_name = os.path.basename(norm_path)

        # Check existence against known inventory or disk
        is_known = (
            norm_path in known_files
            or base_name in known_files
            or any(k.endswith(norm_path) for k in known_files)
        )
        if not is_known and local_path and os.path.isdir(local_path):
            is_known = os.path.isfile(os.path.join(local_path, norm_path))

        # Case 1: File not found in repository inventory
        if not is_known:
            if has_complete_inventory:
                ref.is_valid = False
                ref.path_verified = False
                ref.line_range_verified = False
                ref.status = "unverified"
                ref.confidence = "low"
                ref.detail = f"File '{ref.file_path}' does not exist in repository inventory."
                return False
            else:
                # Complete inventory is unavailable; do not falsely declare file nonexistent
                ref.is_valid = True
                ref.path_verified = False
                ref.line_range_verified = False
                ref.status = "unverified"
                ref.confidence = "low"
                ref.detail = f"File '{ref.file_path}' unverified: complete file inventory unavailable."
                return True

        # Case 2: File path is verified!
        ref.path_verified = True

        # Check line numbers
        # Subcase A: No line numbers specified
        if ref.line_start is None and ref.line_end is None:
            ref.is_valid = True
            ref.line_range_verified = False
            ref.status = "confirmed"
            ref.detail = "File path verified; no line numbers specified."
            return True

        # Subcase B: Non-positive line number
        if (ref.line_start is not None and ref.line_start <= 0) or (ref.line_end is not None and ref.line_end <= 0):
            ref.is_valid = False
            ref.line_range_verified = False
            ref.status = "unverified"
            ref.confidence = "low"
            ref.detail = f"Invalid line range [{ref.line_start}, {ref.line_end}]: line numbers must be positive integers (> 0)."
            return False

        # Subcase C: Inverted line range
        if ref.line_start is not None and ref.line_end is not None and ref.line_end < ref.line_start:
            ref.is_valid = False
            ref.line_range_verified = False
            ref.status = "unverified"
            ref.confidence = "low"
            ref.detail = f"Inverted line range [{ref.line_start}, {ref.line_end}]: line_end must be greater than or equal to line_start."
            return False

        # Subcase D: Check against total line count if known
        total_lines = self._get_file_line_count(norm_path, local_path, line_counts)
        if total_lines is not None:
            max_requested = ref.line_end if ref.line_end is not None else ref.line_start
            if max_requested > total_lines:
                ref.is_valid = False
                ref.line_range_verified = False
                ref.status = "unverified"
                ref.confidence = "low"
                ref.detail = f"Line range [{ref.line_start}, {ref.line_end or ref.line_start}] exceeds file total lines ({total_lines})."
                return False
            else:
                ref.is_valid = True
                ref.line_range_verified = True
                ref.status = "confirmed"
                ref.detail = f"File path and line range [{ref.line_start}, {ref.line_end or ref.line_start}] verified ({total_lines} total lines)."
                return True

        # Subcase E: Source line count unavailable
        ref.is_valid = True
        ref.line_range_verified = False
        ref.status = "confirmed"
        ref.detail = f"File path verified; line range [{ref.line_start}, {ref.line_end or ref.line_start}] unverified (source line count unavailable)."
        return True

    def validate_understanding(
        self,
        understanding: ProjectUnderstanding,
        knowledge: RepositoryKnowledge,
        local_path: Optional[str] = None,
    ) -> ProjectUnderstanding:
        known_files, line_counts, has_complete_inventory = self.get_repository_inventory_and_line_counts(
            knowledge, local_path
        )
        warnings = list(understanding.validation_warnings)

        # Validate Core Features
        for feat in understanding.core_features:
            valid_count = 0
            for ev in feat.supporting_evidence:
                if self.validate_reference(ev, known_files, line_counts, has_complete_inventory, local_path):
                    valid_count += 1
                else:
                    warnings.append(f"Feature '{feat.name}': unverified evidence '{ev.file_path}' ({ev.detail}).")
            if feat.supporting_evidence and valid_count == 0:
                feat.confidence = "low"

        # Validate Target Audience
        for ev in understanding.target_audience.supporting_evidence:
            if not self.validate_reference(ev, known_files, line_counts, has_complete_inventory, local_path):
                warnings.append(f"Target audience: unverified evidence '{ev.file_path}' ({ev.detail}).")

        # Validate Use Cases
        for uc in understanding.use_cases:
            for ev in uc.supporting_evidence:
                if not self.validate_reference(ev, known_files, line_counts, has_complete_inventory, local_path):
                    warnings.append(f"Use case '{uc.name}': unverified evidence '{ev.file_path}' ({ev.detail}).")

        # Validate Technology Stack
        for tech in understanding.technology_stack:
            valid_count = 0
            for ev in tech.supporting_evidence:
                if self.validate_reference(ev, known_files, line_counts, has_complete_inventory, local_path):
                    valid_count += 1
                else:
                    warnings.append(f"Technology '{tech.technology_name}': unverified evidence '{ev.file_path}' ({ev.detail}).")
            if tech.supporting_evidence and valid_count == 0 and tech.status == "confirmed":
                tech.status = "inferred"

        understanding.validation_warnings = warnings
        return understanding


evidence_validator = EvidenceValidator()
