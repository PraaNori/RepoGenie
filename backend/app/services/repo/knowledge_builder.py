import json
import logging
import os
import posixpath
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from ...core.config import settings
from ...models.schemas import (
    ArchitectureAnalysisResult,
    ArchitectureSummary,
    CodeStructureSummary,
    DirectoryTreeNode,
    ImportantFileInfo,
    KnowledgeAnalysisMetadata,
    ParsedFile,
    ParsedRepository,
    ProjectOverviewInfo,
    RepoAnalysisResult,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    SourceEvidenceRecord,
    StatusEnum,
    TechnologyItem,
    TechnologyStack,
    UnifiedStatistics,
)

logger = logging.getLogger(__name__)

# Standard markdown headers regex
FEATURE_HEADING_RE = re.compile(r"^#{1,3}\s+(?:Key\s+)?(?:Features|Capabilities|Highlights|What\s+it\s+does)\b", re.IGNORECASE)
LIMITATION_HEADING_RE = re.compile(r"^#{1,3}\s+(?:Known\s+)?(?:Limitations|Caveats|Issues)\b", re.IGNORECASE)
WARNING_HEADING_RE = re.compile(r"^#{1,3}\s+(?:Warnings?|Alerts?|Caution)\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,4}\s+.*$")
BULLET_RE = re.compile(r"^[\*\-\+]\s+(.*)$|^\d+\.\s+(.*)$")
DOC_WARNING_CALLOUT_RE = re.compile(r"^>\s*\[!(?:WARNING|CAUTION)\]|^>\s*\*\*(?:Warning|Caution)\*\*", re.IGNORECASE)

# Technology catalogs
FRAMEWORK_CATALOG: Dict[str, Tuple[str, str]] = {
    # python
    "fastapi": ("FastAPI", "Python"),
    "flask": ("Flask", "Python"),
    "django": ("Django", "Python"),
    "click": ("Click", "Python"),
    "typer": ("Typer", "Python"),
    "tornado": ("Tornado", "Python"),
    "starlette": ("Starlette", "Python"),
    # javascript / typescript
    "react": ("React", "JavaScript/TypeScript"),
    "vue": ("Vue", "JavaScript/TypeScript"),
    "@angular/core": ("Angular", "TypeScript"),
    "svelte": ("Svelte", "JavaScript/TypeScript"),
    "next": ("Next.js", "JavaScript/TypeScript"),
    "express": ("Express", "JavaScript/TypeScript"),
    "koa": ("Koa", "JavaScript/TypeScript"),
    "nestjs": ("NestJS", "TypeScript"),
    "vite": ("Vite", "JavaScript/TypeScript"),
    # go
    "github.com/gin-gonic/gin": ("Gin", "Go"),
    "github.com/labstack/echo": ("Echo", "Go"),
    "github.com/gofiber/fiber": ("Fiber", "Go"),
    # rust
    "actix-web": ("Actix-web", "Rust"),
    "axum": ("Axum", "Rust"),
    "rocket": ("Rocket", "Rust"),
    # java
    "org.springframework.boot": ("Spring Boot", "Java"),
}

DATABASE_CATALOG: Dict[str, Tuple[str, str]] = {
    "psycopg2": ("PostgreSQL", "database"),
    "psycopg2-binary": ("PostgreSQL", "database"),
    "asyncpg": ("PostgreSQL", "database"),
    "pg": ("PostgreSQL", "database"),
    "mysql": ("MySQL", "database"),
    "mysqlclient": ("MySQL", "database"),
    "pymysql": ("MySQL", "database"),
    "sqlite3": ("SQLite", "database"),
    "pymongo": ("MongoDB", "database"),
    "mongodb": ("MongoDB", "database"),
    "mongoose": ("MongoDB", "database"),
    "redis": ("Redis", "database"),
    "ioredis": ("Redis", "database"),
    "sqlalchemy": ("SQLAlchemy", "orm"),
    "prisma": ("Prisma", "orm"),
    "@prisma/client": ("Prisma", "orm"),
    "typeorm": ("TypeORM", "orm"),
    "alembic": ("Alembic", "migrations"),
}

TOOL_CATALOG: Dict[str, Tuple[str, str]] = {
    "pytest": ("Pytest", "test_runner"),
    "unittest": ("Unittest", "test_runner"),
    "jest": ("Jest", "test_runner"),
    "vitest": ("Vitest", "test_runner"),
    "mocha": ("Mocha", "test_runner"),
    "eslint": ("ESLint", "linter"),
    "prettier": ("Prettier", "formatter"),
    "black": ("Black", "formatter"),
    "ruff": ("Ruff", "linter_formatter"),
    "flake8": ("Flake8", "linter"),
    "mypy": ("MyPy", "type_checker"),
    "webpack": ("Webpack", "bundler"),
    "babel": ("Babel", "compiler"),
    "rollup": ("Rollup", "bundler"),
}


class KnowledgeBuilderService:
    """
    Consolidates static analysis, AST code parsing, and architecture relationship models
    into a unified repository knowledge representation.
    """

    def __init__(
        self,
        max_important_files: int = settings.MAX_IMPORTANT_FILES,
        max_evidence_records: int = settings.MAX_SOURCE_EVIDENCE_RECORDS,
    ):
        self.max_important_files = max_important_files
        self.max_evidence_records = max_evidence_records

    def extract_readme_overview(
        self,
        local_path: Optional[str],
        all_files: Set[str],
    ) -> Tuple[ProjectOverviewInfo, List[SourceEvidenceRecord]]:
        """
        Statically inspects README documentation for project description, feature bullets,
        limitations, and warnings without employing an LLM.
        """
        overview = ProjectOverviewInfo()
        evidence_list: List[SourceEvidenceRecord] = []

        if not local_path or not os.path.isdir(local_path):
            return overview, evidence_list

        # Locate README candidate
        readme_candidates = [
            "README.md", "readme.md", "README.rst", "readme.rst",
            "README.txt", "readme.txt", "README", "readme",
        ]
        chosen_readme: Optional[str] = None
        for cand in readme_candidates:
            if cand in all_files or os.path.isfile(os.path.join(local_path, cand)):
                chosen_readme = cand
                break

        if not chosen_readme:
            return overview, evidence_list

        overview.readme_available = True
        overview.readme_path = chosen_readme
        full_readme_path = os.path.join(local_path, chosen_readme)

        try:
            with open(full_readme_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            # State machine for section parsing
            current_section: Optional[str] = None
            desc_lines: List[str] = []
            features: List[str] = []
            limitations: List[str] = []
            warnings: List[str] = []
            first_heading_seen = False

            for line_idx, line in enumerate(lines, 1):
                clean_line = line.strip()

                # Callout warnings check
                if DOC_WARNING_CALLOUT_RE.match(clean_line):
                    warnings.append(clean_line)
                    evidence_list.append(
                        SourceEvidenceRecord(
                            file_path=chosen_readme,
                            start_line=line_idx,
                            evidence_type="documentation",
                            symbol_or_statement=clean_line[:120],
                            confidence="high",
                            analysis_stage="documentation",
                            status="observed",
                        )
                    )

                # Check section headings
                if HEADING_RE.match(clean_line):
                    if not first_heading_seen:
                        first_heading_seen = True
                        current_section = None
                        continue

                    if FEATURE_HEADING_RE.match(clean_line):
                        current_section = "features"
                    elif LIMITATION_HEADING_RE.match(clean_line):
                        current_section = "limitations"
                    elif WARNING_HEADING_RE.match(clean_line):
                        current_section = "warnings"
                    else:
                        current_section = "other"
                    continue

                # Top description extraction (paragraphs following first heading before second section)
                if first_heading_seen and current_section is None and clean_line:
                    # Filter badges like [![Build]...] or HTML tags
                    if not clean_line.startswith("[![") and not clean_line.startswith("<") and not clean_line.startswith("[!"):
                        if len(desc_lines) < 3 and len(" ".join(desc_lines)) < 400:
                            desc_lines.append(clean_line)

                # Bullet items in identified sections
                bullet_match = BULLET_RE.match(clean_line)
                if bullet_match and current_section:
                    bullet_text = (bullet_match.group(1) or bullet_match.group(2) or "").strip()
                    if bullet_text:
                        if current_section == "features" and len(features) < 10:
                            features.append(bullet_text)
                            if len(evidence_list) < self.max_evidence_records:
                                evidence_list.append(
                                    SourceEvidenceRecord(
                                        file_path=chosen_readme,
                                        start_line=line_idx,
                                        evidence_type="documentation",
                                        symbol_or_statement=f"Feature: {bullet_text[:100]}",
                                        confidence="high",
                                        analysis_stage="documentation",
                                        status="observed",
                                    )
                                )
                        elif current_section == "limitations" and len(limitations) < 5:
                            limitations.append(bullet_text)
                        elif current_section == "warnings" and len(warnings) < 5:
                            warnings.append(bullet_text)

            if desc_lines:
                overview.description = " ".join(desc_lines)
                evidence_list.append(
                    SourceEvidenceRecord(
                        file_path=chosen_readme,
                        start_line=1,
                        evidence_type="documentation",
                        symbol_or_statement=f"Description: {overview.description[:120]}",
                        confidence="high",
                        analysis_stage="documentation",
                        status="observed",
                    )
                )

            overview.features = features
            overview.limitations = limitations
            overview.documentation_warnings = warnings

        except Exception as exc:
            logger.warning("Error inspecting README at %s: %s", full_readme_path, exc)

        return overview, evidence_list

    def consolidate_technology_stack(
        self,
        analysis: RepoAnalysisResult,
        parsed_repo: ParsedRepository,
        architecture: ArchitectureAnalysisResult,
        all_files: Set[str],
    ) -> Tuple[TechnologyStack, List[SourceEvidenceRecord]]:
        """
        Consolidates programming languages, frameworks, libraries, databases, tools,
        and deployment technologies, distinguishing confirmed technologies from inferred signals.
        """
        stack = TechnologyStack()
        evidence_list: List[SourceEvidenceRecord] = []
        seen_names: Set[str] = set()

        # 1. Programming Languages from static language statistics
        for lang_stat in analysis.languages:
            if lang_stat.name not in seen_names:
                seen_names.add(lang_stat.name)
                stack.languages.append(
                    TechnologyItem(
                        name=lang_stat.name,
                        category="language",
                        version=None,
                        confidence="high",
                        detection_source="language_detection",
                        is_confirmed=True,
                    )
                )

        # Build lookup of all imported symbols and modules across parsed code
        imported_modules: Set[str] = set()
        for pf in parsed_repo.files:
            for imp in pf.imports:
                imported_modules.add(imp.module.lower())
                top_mod = imp.module.split(".")[0].split("/")[0].lower()
                imported_modules.add(top_mod)

        # Build lookup of all manifest dependencies
        declared_dependencies: Dict[str, Optional[str]] = {}
        for manifest in analysis.dependency_files:
            for dep in manifest.dependencies:
                dep_clean = dep.name.lower()
                declared_dependencies[dep_clean] = dep.version_spec

        # 2. Frameworks
        for framework_key, (disp_name, _lang) in FRAMEWORK_CATALOG.items():
            key_lower = framework_key.lower()
            in_deps = key_lower in declared_dependencies
            in_imports = key_lower in imported_modules or any(key_lower in mod for mod in imported_modules)

            if in_deps or in_imports:
                is_confirmed = in_imports or in_deps
                confidence = "high" if (in_deps and in_imports) else ("high" if in_deps else "medium")
                if disp_name not in seen_names:
                    seen_names.add(disp_name)
                    stack.frameworks.append(
                        TechnologyItem(
                            name=disp_name,
                            category="framework",
                            version=declared_dependencies.get(key_lower),
                            confidence=confidence,
                            detection_source="manifest" if in_deps else "code_import",
                            is_confirmed=is_confirmed,
                        )
                    )

        # Check framework app instances from entry points
        for ep in architecture.entry_points:
            if ep.entry_type == "framework_app_instance" and ep.symbol_or_command:
                base_fw = ep.symbol_or_command.split("(")[0].strip()
                if base_fw and base_fw not in seen_names:
                    seen_names.add(base_fw)
                    stack.frameworks.append(
                        TechnologyItem(
                            name=base_fw,
                            category="framework",
                            version=None,
                            confidence="high",
                            detection_source="framework_instance",
                            is_confirmed=True,
                        )
                    )

        # 3. Databases and ORMs
        for db_key, (disp_name, db_type) in DATABASE_CATALOG.items():
            key_lower = db_key.lower()
            in_deps = key_lower in declared_dependencies
            in_imports = key_lower in imported_modules or any(key_lower in mod for mod in imported_modules)

            if in_deps or in_imports:
                if disp_name not in seen_names:
                    seen_names.add(disp_name)
                    stack.databases.append(
                        TechnologyItem(
                            name=disp_name,
                            category=db_type,
                            version=declared_dependencies.get(key_lower),
                            confidence="high" if (in_deps and in_imports) else "medium",
                            detection_source="manifest" if in_deps else "code_import",
                            is_confirmed=in_imports or in_deps,
                        )
                    )

        # 4. Tools (Test runners, linters, formatters)
        for tool_key, (disp_name, _category) in TOOL_CATALOG.items():
            key_lower = tool_key.lower()
            in_deps = key_lower in declared_dependencies
            in_imports = key_lower in imported_modules or any(key_lower in mod for mod in imported_modules)

            if in_deps or in_imports:
                if disp_name not in seen_names:
                    seen_names.add(disp_name)
                    stack.tools.append(
                        TechnologyItem(
                            name=disp_name,
                            category="tool",
                            version=declared_dependencies.get(key_lower),
                            confidence="high" if in_deps else "medium",
                            detection_source="manifest" if in_deps else "code_import",
                            is_confirmed=True,
                        )
                    )

        # 5. Libraries (remaining top dependencies from manifests)
        for dep_name, version in declared_dependencies.items():
            # If already categorized under frameworks, databases, or tools, skip
            if (
                any(dep_name == k.lower() for k in FRAMEWORK_CATALOG)
                or any(dep_name == k.lower() for k in DATABASE_CATALOG)
                or any(dep_name == k.lower() for k in TOOL_CATALOG)
            ):
                continue

            if dep_name not in seen_names and len(stack.libraries) < 40:
                seen_names.add(dep_name)
                is_active = dep_name in imported_modules or any(dep_name in mod for mod in imported_modules)
                stack.libraries.append(
                    TechnologyItem(
                        name=dep_name,
                        category="library",
                        version=version,
                        confidence="high",
                        detection_source="manifest",
                        is_confirmed=is_active,
                    )
                )

        # 6. Deployment Technologies
        if any(f.lower() in ("dockerfile", "docker-compose.yml", "docker-compose.yaml") or "docker/" in f.lower() for f in all_files):
            if "Docker" not in seen_names:
                seen_names.add("Docker")
                stack.deployment_technologies.append(
                    TechnologyItem(
                        name="Docker",
                        category="deployment",
                        confidence="high",
                        detection_source="configuration",
                        is_confirmed=True,
                    )
                )

        if any(".github/workflows/" in f or ".gitlab-ci.yml" in f for f in all_files):
            if "CI/CD" not in seen_names:
                seen_names.add("CI/CD")
                stack.deployment_technologies.append(
                    TechnologyItem(
                        name="GitHub Actions / CI",
                        category="deployment",
                        confidence="high",
                        detection_source="configuration",
                        is_confirmed=True,
                    )
                )

        if any("k8s/" in f or "kubernetes/" in f or f.endswith(".k8s.yaml") for f in all_files):
            if "Kubernetes" not in seen_names:
                seen_names.add("Kubernetes")
                stack.deployment_technologies.append(
                    TechnologyItem(
                        name="Kubernetes",
                        category="deployment",
                        confidence="high",
                        detection_source="configuration",
                        is_confirmed=True,
                    )
                )

        return stack, evidence_list

    def identify_important_files(
        self,
        analysis: RepoAnalysisResult,
        architecture: ArchitectureAnalysisResult,
        all_files: Set[str],
    ) -> List[ImportantFileInfo]:
        """
        Ranks repository files by structural significance using deterministic scoring.
        """
        candidate_map: Dict[str, ImportantFileInfo] = {}

        def record(path: str, category: str, score: float, reason: str, evidence: str, confidence: str = "high"):
            norm_p = posixpath.normpath(path)
            if norm_p not in candidate_map or score > candidate_map[norm_p].score:
                candidate_map[norm_p] = ImportantFileInfo(
                    relative_path=norm_p,
                    category=category,
                    score=score,
                    reason=reason,
                    evidence=evidence,
                    confidence=confidence,
                )

        # 1. README documentation
        for f in all_files:
            bname = posixpath.basename(f).lower()
            if bname in ("readme.md", "readme.rst", "readme.txt", "readme"):
                record(
                    f, "readme", 10.0,
                    "Primary repository documentation and project overview",
                    f"Filename matches '{bname}'",
                    "high"
                )

        # 2. Entry points
        for ep in architecture.entry_points:
            score = 9.5 if ep.confidence == "high" else 8.0
            record(
                ep.file_path, "entry_point", score,
                f"Application entry point candidate ({ep.entry_type})",
                ep.symbol_or_command or ep.entry_type,
                ep.confidence
            )

        # 3. Dependency manifests
        for mf in analysis.dependency_files:
            bname = posixpath.basename(mf.file_path).lower()
            record(
                mf.file_path, "manifest", 9.0,
                f"Package dependency manifest ({mf.ecosystem})",
                f"{mf.dependencies_count} declared dependencies",
                "high"
            )

        # 4. Central configuration files
        for cf in analysis.configuration_files:
            bname = posixpath.basename(cf.file_path).lower()
            if bname in (
                "dockerfile", "docker-compose.yml", "docker-compose.yaml",
                "vite.config.ts", "vite.config.js", "tsconfig.json", "webpack.config.js",
                "settings.py", "config.py",
            ):
                record(
                    cf.file_path, "configuration", 8.5,
                    f"Core application configuration ({cf.config_type})",
                    f"Configuration type '{cf.config_type}'",
                    "high"
                )

        # 5. Classified Architectural Components
        for comp in architecture.components:
            fpath = comp.file_path
            cat = comp.category
            evidence_str = "; ".join(comp.evidence) if comp.evidence else cat

            if cat == "api_route":
                record(fpath, "api_route", 7.5, "API endpoint routing or controller module", evidence_str, comp.confidence)
            elif cat == "service":
                record(fpath, "service", 7.0, "Domain service or core business logic module", evidence_str, comp.confidence)
            elif cat in ("model", "database"):
                record(fpath, cat, 6.5, "Data model definition or database schema", evidence_str, comp.confidence)
            elif cat == "test" and any(posixpath.basename(fpath).startswith(p) for p in ("test_main", "setupTests", "conftest")):
                record(fpath, "test", 5.5, "Core test suite harness or configuration", evidence_str, comp.confidence)

        # Sort descending by score, tie-break by relative_path
        sorted_files = sorted(candidate_map.values(), key=lambda x: (-x.score, x.relative_path))
        return sorted_files[: self.max_important_files]

    def collect_source_evidence(
        self,
        doc_evidence: List[SourceEvidenceRecord],
        architecture: ArchitectureAnalysisResult,
        analysis: RepoAnalysisResult,
    ) -> List[SourceEvidenceRecord]:
        """
        Assembles all traceable source evidence records with deduplication.
        """
        records: List[SourceEvidenceRecord] = list(doc_evidence)
        seen_keys: Set[Tuple[str, int, str]] = {
            (e.file_path, e.start_line, e.evidence_type) for e in doc_evidence
        }

        def add_rec(rec: SourceEvidenceRecord):
            key = (rec.file_path, rec.start_line, rec.evidence_type)
            if key not in seen_keys and len(records) < self.max_evidence_records:
                seen_keys.add(key)
                records.append(rec)

        # From entry point evidence
        for ep in architecture.entry_points:
            for ev in ep.evidence:
                add_rec(
                    SourceEvidenceRecord(
                        file_path=ev.file_path,
                        start_line=ev.line_number or 1,
                        evidence_type=ev.evidence_type,
                        symbol_or_statement=ev.statement or ep.entry_type,
                        confidence=ev.confidence,
                        analysis_stage="architecture_analysis",
                        status="statically_resolved",
                    )
                )

        # From inheritance relationships evidence
        for inh in architecture.inheritance_relationships:
            ev = inh.evidence
            add_rec(
                SourceEvidenceRecord(
                    file_path=ev.file_path,
                    start_line=ev.line_number or 1,
                    evidence_type="class_inheritance",
                    symbol_or_statement=ev.statement or f"{inh.child_class} -> {inh.parent_class}",
                    confidence=ev.confidence,
                    analysis_stage="architecture_analysis",
                    status="statically_resolved",
                )
            )

        # From call graph edges evidence (sample up to 100 resolved calls)
        sample_edges = [e for e in architecture.call_graph.edges if e.resolution_status == "resolved_internal"][:100]
        for edge in sample_edges:
            ev = edge.evidence
            add_rec(
                SourceEvidenceRecord(
                    file_path=ev.file_path,
                    start_line=ev.line_number or 1,
                    evidence_type="function_call",
                    symbol_or_statement=ev.statement or edge.call_name,
                    confidence=ev.confidence,
                    analysis_stage="architecture_analysis",
                    status="statically_resolved",
                )
            )

        # From manifest dependencies
        for mf in analysis.dependency_files:
            add_rec(
                SourceEvidenceRecord(
                    file_path=mf.file_path,
                    start_line=1,
                    evidence_type="manifest_dependency",
                    symbol_or_statement=f"Manifest declared {mf.dependencies_count} dependencies ({mf.ecosystem})",
                    confidence="high",
                    analysis_stage="repo_structure",
                    status="observed",
                )
            )

        return records

    def build_knowledge(
        self,
        job_id: str,
        repo_name: str,
        repo_owner: str,
        repo_url: str,
        local_path: Optional[str] = None,
        size_mb: float = 0.0,
        file_count: int = 0,
        analysis: Optional[RepoAnalysisResult] = None,
        parsed_repo: Optional[ParsedRepository] = None,
        architecture: Optional[ArchitectureAnalysisResult] = None,
    ) -> RepositoryKnowledge:
        """
        Consolidates complete analysis outputs into a single validated RepositoryKnowledge model.
        """
        warnings: List[str] = []

        # Validate prerequisite stages
        if not analysis:
            raise ValueError(f"Repository structure analysis (Milestone 2.3) missing for job '{job_id}'")
        if not parsed_repo:
            raise ValueError(f"Code parsing metadata (Milestone 2.4) missing for job '{job_id}'")
        if not architecture:
            raise ValueError(f"Architecture analysis (Milestone 2.5) missing for job '{job_id}'")

        # Collect warnings across stages
        warnings.extend(analysis.warnings)
        warnings.extend(parsed_repo.warnings)
        warnings.extend(architecture.warnings)

        # Extract all repository-relative files
        all_files: Set[str] = {pf.file_path for pf in parsed_repo.files}

        # 1. Repository Metadata
        repo_meta = RepositoryMetadataInfo(
            name=repo_name,
            owner=repo_owner,
            repository_url=repo_url,
            clone_status=StatusEnum.COMPLETED,
            size_mb=round(size_mb, 2),
            file_count=file_count if file_count > 0 else analysis.statistics.total_files,
            description=None,
        )

        # 2. Project Overview from README
        logger.info("Extracting project overview from README for %s", repo_name)
        project_overview, doc_evidence = self.extract_readme_overview(local_path, all_files)

        # If README had a description, assign to repo_meta
        if project_overview.description:
            repo_meta.description = project_overview.description

        # 3. Technology Stack Consolidation
        logger.info("Consolidating technology stack for %s", repo_name)
        tech_stack, _ = self.consolidate_technology_stack(
            analysis=analysis,
            parsed_repo=parsed_repo,
            architecture=architecture,
            all_files=all_files,
        )

        # 4. Important Files Identification
        logger.info("Identifying important files for %s", repo_name)
        important_files = self.identify_important_files(
            analysis=analysis,
            architecture=architecture,
            all_files=all_files,
        )

        # 5. Source Evidence Traceability
        logger.info("Collecting source evidence records for %s", repo_name)
        source_evidence = self.collect_source_evidence(
            doc_evidence=doc_evidence,
            architecture=architecture,
            analysis=analysis,
        )

        # 6. Repository Structure Overview
        important_dirs: List[str] = []
        if analysis.directory_tree and analysis.directory_tree.children:
            for ch in analysis.directory_tree.children:
                if ch.type == "directory":
                    important_dirs.append(ch.name)

        repo_structure = RepositoryStructureOverview(
            total_directories=analysis.statistics.total_directories,
            total_files=analysis.statistics.total_files,
            important_directories=important_dirs,
            directory_tree=analysis.directory_tree,
        )

        # 7. Unified Statistics
        total_loc = sum(pf.total_lines for pf in parsed_repo.files)
        statistics = UnifiedStatistics(
            total_files=analysis.statistics.total_files,
            source_files=analysis.statistics.source_files,
            filtered_files=analysis.statistics.filtered_files,
            total_lines_of_code=total_loc,
            total_functions=parsed_repo.total_functions,
            total_classes=parsed_repo.total_classes,
            total_methods=parsed_repo.total_methods,
            total_imports=parsed_repo.total_imports,
            total_function_calls=parsed_repo.total_function_calls,
            total_internal_dependencies=architecture.dependency_graph.total_internal_dependencies,
            total_external_dependencies=architecture.dependency_graph.total_external_dependencies,
            circular_dependencies_count=len(architecture.dependency_graph.circular_dependencies),
        )

        # 8. Code Structure Summary
        code_structure = CodeStructureSummary(
            parsed_files_count=parsed_repo.total_parsed_files,
            supported_languages=parsed_repo.supported_languages,
            files=parsed_repo.files,
        )

        # 9. Architecture Summary
        arch_summary = ArchitectureSummary(
            dependency_graph=architecture.dependency_graph,
            call_graph=architecture.call_graph,
            inheritance_relationships=architecture.inheritance_relationships,
            class_references=architecture.class_references,
            components=architecture.components,
            component_counts=architecture.component_counts,
        )

        # 10. Analysis Metadata
        now = datetime.now(timezone.utc)
        meta = KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=[
                "repo_fetching",
                "repo_analysis",
                "code_understanding",
                "knowledge_consolidation",
            ],
        )

        return RepositoryKnowledge(
            schema_version="1.0",
            repository=repo_meta,
            project_overview=project_overview,
            technology_stack=tech_stack,
            repository_structure=repo_structure,
            statistics=statistics,
            dependency_information=architecture.dependency_graph,
            code_structure=code_structure,
            architecture=arch_summary,
            entry_points=architecture.entry_points,
            important_files=important_files,
            source_evidence=source_evidence,
            warnings=warnings,
            analysis_metadata=meta,
        )


knowledge_builder_service = KnowledgeBuilderService()
