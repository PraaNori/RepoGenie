from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
from .evidence_resolver import find_actual_files_for_language

logger = logging.getLogger(__name__)


class EvidenceBuilder:
    """
    Constructs a compact, structured, grounded evidence package from RepositoryKnowledge
    to serve as the factual context for AI project-level understanding.

    Token Budget Heuristic:
        MAX_CHAR_BUDGET is set to 6,500 characters (~1,600 prompt tokens).
        Combined with system prompt instructions and output schema definitions (~1,950 tokens)
        and max output tokens (2,048), total requested tokens per operation remain around ~5,600,
        safely below provider per-minute rate limits (e.g. Groq 8,000 TPM limit).
        Note: This calculation is an operational heuristic against provider rate limits,
        not a guarantee of available API quota.
    """

    MAX_CHAR_BUDGET = 6500  # ~1,600 tokens budget to stay safely within TPM free-tier limits

    def build_evidence_package(
        self,
        knowledge: RepositoryKnowledge,
        max_evidence_items: int = 15,
        max_libraries: int = 12,
    ) -> Dict[str, Any]:
        """
        Extracts and compacts knowledge into a structured dictionary suitable for prompt injection.
        """
        # 1. Repository Identity & Sizing
        repo_meta = {
            "name": knowledge.repository.name,
            "owner": knowledge.repository.owner,
            "url": knowledge.repository.repository_url,
            "size_mb": round(knowledge.repository.size_mb, 2),
            "file_count": knowledge.repository.file_count,
        }

        # 2. README & Documentation Overview
        overview = {
            "readme_available": knowledge.project_overview.readme_available,
            "readme_path": knowledge.project_overview.readme_path or "README.md",
            "description": (knowledge.project_overview.description or "").strip(),
            "extracted_features": knowledge.project_overview.features[:10],
            "extracted_limitations": knowledge.project_overview.limitations[:5],
        }

        # 3. Technology Stack
        languages_info = []
        for lang in knowledge.technology_stack.languages:
            sample_files = find_actual_files_for_language(knowledge, lang.name, max_files=2)
            lang_dict: Dict[str, Any] = {"name": lang.name}
            if sample_files:
                lang_dict["sample_files"] = sample_files
            languages_info.append(lang_dict)

        tech_stack = {
            "languages": [lang.name for lang in knowledge.technology_stack.languages],
            "language_evidence": languages_info,
            "frameworks": [
                {
                    "name": fw.name,
                    "category": fw.category,
                    "is_confirmed": fw.is_confirmed,
                }
                for fw in knowledge.technology_stack.frameworks
            ],
            "libraries": [
                {
                    "name": lib.name,
                    "version": lib.version,
                    "category": lib.category,
                }
                for lib in knowledge.technology_stack.libraries[:max_libraries]
            ],
            "databases": [db.name for db in knowledge.technology_stack.databases],
            "tools": [t.name for t in knowledge.technology_stack.tools],
            "deployment": [d.name for d in knowledge.technology_stack.deployment_technologies],
        }

        # 4. Code Statistics & Key Architecture
        stats = {
            "source_files": knowledge.statistics.source_files,
            "total_lines_of_code": knowledge.statistics.total_lines_of_code,
            "total_functions": knowledge.statistics.total_functions,
            "total_classes": knowledge.statistics.total_classes,
            "total_methods": knowledge.statistics.total_methods,
            "total_internal_dependencies": knowledge.statistics.total_internal_dependencies,
            "total_external_dependencies": knowledge.statistics.total_external_dependencies,
        }

        # 5. Important Files & Entry Points
        important_files = [
            {
                "path": f.relative_path,
                "category": f.category,
                "score": round(f.score, 1),
                "reason": f.reason,
            }
            for f in knowledge.important_files[:8]
        ]

        entry_points = [
            {
                "file_path": ep.file_path,
                "entry_type": ep.entry_type,
                "symbol_or_command": ep.symbol_or_command,
                "confidence": ep.confidence,
            }
            for ep in knowledge.entry_points[:5]
        ]

        components = [
            {
                "file_path": comp.file_path,
                "category": comp.category,
                "confidence": comp.confidence,
            }
            for comp in knowledge.architecture.components[:5]
        ]

        # 6. Source Evidence Records
        # Prioritize evidence from entry points, manifests, and core files
        evidence_records: List[Dict[str, Any]] = []
        for ev in knowledge.source_evidence[:max_evidence_items]:
            # Sanitize paths to avoid accidental secrets exposure
            if ".env" in ev.file_path.lower():
                continue
            evidence_records.append({
                "file_path": ev.file_path,
                "start_line": ev.start_line,
                "end_line": ev.end_line,
                "evidence_type": ev.evidence_type,
                "symbol_or_statement": (ev.symbol_or_statement or "")[:120],
                "confidence": ev.confidence,
                "status": ev.status,
            })

        evidence_package = {
            "repository": repo_meta,
            "overview": overview,
            "tech_stack": tech_stack,
            "statistics": stats,
            "important_directories": knowledge.repository_structure.important_directories[:10],
            "important_files": important_files,
            "entry_points": entry_points,
            "architectural_components": components,
            "source_evidence": evidence_records,
            "warnings": knowledge.warnings[:5],
        }

        # Ensure budget compliance
        json_str = json.dumps(evidence_package)
        if len(json_str) > self.MAX_CHAR_BUDGET:
            logger.info(
                "Evidence package (%d chars) exceeds budget (%d chars); trimming source evidence and libraries",
                len(json_str),
                self.MAX_CHAR_BUDGET,
            )
            evidence_package["source_evidence"] = evidence_records[:15]
            evidence_package["tech_stack"]["libraries"] = evidence_package["tech_stack"]["libraries"][:10]

        return evidence_package


evidence_builder_service = EvidenceBuilder()
