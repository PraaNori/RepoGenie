from __future__ import annotations

import os
from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
from .schemas import EvidenceReference, ProjectUnderstanding


class EvidenceValidator:
    """
    Validates every EvidenceReference in a ProjectUnderstanding against actual
    repository knowledge. Ensures referenced files actually exist and line numbers
    are well-formed. Marks fabricated or missing references as invalid/unverified.
    """

    def get_known_repository_files(self, knowledge: RepositoryKnowledge) -> Set[str]:
        known: Set[str] = set()

        # 1. Project overview README
        if knowledge.project_overview.readme_path:
            p = knowledge.project_overview.readme_path.strip().lstrip("/")
            known.add(p)
            known.add(os.path.basename(p))

        # Root standard files
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
        ):
            known.add(root_name)

        # 2. Important files
        for f in knowledge.important_files:
            known.add(f.relative_path.strip().lstrip("/"))

        # 3. Entry points
        for ep in knowledge.entry_points:
            known.add(ep.file_path.strip().lstrip("/"))

        # 4. Source evidence records
        for ev in knowledge.source_evidence:
            known.add(ev.file_path.strip().lstrip("/"))

        # 5. Code structure files
        for cf in knowledge.code_structure.files:
            if hasattr(cf, "file_path") and cf.file_path:
                known.add(cf.file_path.strip().lstrip("/"))
            elif hasattr(cf, "relative_path") and cf.relative_path:
                known.add(cf.relative_path.strip().lstrip("/"))

        # 6. Architectural components
        for comp in knowledge.architecture.components:
            known.add(comp.file_path.strip().lstrip("/"))

        # 7. Dependency nodes
        for node in knowledge.dependency_information.nodes:
            if hasattr(node, "file_path") and node.file_path:
                known.add(node.file_path.strip().lstrip("/"))

        return known

    def validate_reference(
        self,
        ref: EvidenceReference,
        known_files: Set[str],
    ) -> bool:
        norm_path = ref.file_path.strip().lstrip("/")

        # Check exact path or basename or suffix match
        is_known = (
            norm_path in known_files
            or os.path.basename(norm_path) in known_files
            or any(k.endswith(norm_path) for k in known_files)
        )

        # Validate line numbers
        if ref.line_start is not None:
            if ref.line_start <= 0:
                ref.line_start = None
                ref.line_end = None
            elif ref.line_end is not None and ref.line_end < ref.line_start:
                ref.line_end = ref.line_start

        if not is_known:
            ref.is_valid = False
            ref.status = "unverified"
            ref.confidence = "low"
            ref.detail = f"File '{ref.file_path}' does not exist in repository files or analysis."
            return False

        ref.is_valid = True
        return True

    def validate_understanding(
        self,
        understanding: ProjectUnderstanding,
        knowledge: RepositoryKnowledge,
    ) -> ProjectUnderstanding:
        known_files = self.get_known_repository_files(knowledge)
        warnings = list(understanding.validation_warnings)

        # Validate Core Features
        for feat in understanding.core_features:
            valid_count = 0
            for ev in feat.supporting_evidence:
                if self.validate_reference(ev, known_files):
                    valid_count += 1
                else:
                    warnings.append(f"Feature '{feat.name}': unverified evidence file '{ev.file_path}'.")
            if feat.supporting_evidence and valid_count == 0:
                feat.confidence = "low"

        # Validate Target Audience
        for ev in understanding.target_audience.supporting_evidence:
            if not self.validate_reference(ev, known_files):
                warnings.append(f"Target audience: unverified evidence file '{ev.file_path}'.")

        # Validate Use Cases
        for uc in understanding.use_cases:
            for ev in uc.supporting_evidence:
                if not self.validate_reference(ev, known_files):
                    warnings.append(f"Use case '{uc.name}': unverified evidence file '{ev.file_path}'.")

        # Validate Technology Stack
        for tech in understanding.technology_stack:
            valid_count = 0
            for ev in tech.supporting_evidence:
                if self.validate_reference(ev, known_files):
                    valid_count += 1
                else:
                    warnings.append(f"Technology '{tech.technology_name}': unverified evidence file '{ev.file_path}'.")
            if tech.supporting_evidence and valid_count == 0 and tech.status == "confirmed":
                tech.status = "inferred"

        understanding.validation_warnings = warnings
        return understanding


evidence_validator = EvidenceValidator()
