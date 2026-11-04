"""
Repository Structure and File Analysis Service (Milestone 2.3).

Performs static inspection of cloned repository contents:
- Directory traversal & hierarchy extraction
- File filtering (ignoring binaries, caches, build artifacts)
- Programming language detection across 20 languages
- Dependency manifest identification & parsing
- Configuration file discovery
- Aggregated repository statistics
"""
import json
import logging
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ...core.config import settings
from ...models.schemas import (
    ConfigurationFileInfo,
    DependencyItem,
    DirectoryTreeNode,
    LanguageStat,
    ManifestInfo,
    RepoAnalysisResult,
    RepoStatistics,
    StatusEnum,
)

logger = logging.getLogger(__name__)

# --- Language Definitions (20 Supported Languages) ---
LANGUAGE_EXTENSION_MAP: Dict[str, str] = {
    # Python
    ".py": "Python",
    ".pyw": "Python",
    # JavaScript
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".gs": "JavaScript",
    # TypeScript
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    # Java
    ".java": "Java",
    # C
    ".c": "C",
    ".h": "C",
    # C++
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
    ".ino": "C++",
    # C#
    ".cs": "C#",
    # Go
    ".go": "Go",
    # Rust
    ".rs": "Rust",
    # Ruby
    ".rb": "Ruby",
    # PHP
    ".php": "PHP",
    # Swift
    ".swift": "Swift",
    # Kotlin
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    # HTML
    ".html": "HTML",
    ".htm": "HTML",
    # CSS
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".less": "CSS",
    # SQL
    ".sql": "SQL",
    # Shell
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    # Dart
    ".dart": "Dart",
    # Vue
    ".vue": "Vue",
    # Svelte
    ".svelte": "Svelte",
}

# Languages with full Tree-sitter AST parser support in RepoGenie
PARSER_SUPPORTED_LANGUAGES: Set[str] = {
    "Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C", "C++"
}

# --- Directory Exclusions ---
EXCLUDED_DIRECTORIES: Set[str] = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".turbo",
    "dist",
    "build",
    "out",
    "coverage",
    "htmlcov",
    ".nyc_output",
    "vendor",
    "target",
    ".idea",
    ".vscode",
    "__MACOSX",
    ".gradle",
}

# --- File Exclusions (Binaries, Caches, Large Assets) ---
EXCLUDED_EXTENSIONS: Set[str] = {
    # Binaries & Compiled
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".dylib", ".o", ".a", ".obj",
    ".class", ".jar", ".war", ".ear",
    # Cache & Temp
    ".cache", ".tmp", ".temp", ".swp", ".swo",
    # Media & Media Assets
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svg", ".mp4", ".mp3",
    ".mov", ".avi", ".pdf", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
    ".bin", ".woff", ".woff2", ".ttf", ".eot",
    # Documents & Office Data Files (non-code assets)
    ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt",
    # Source Maps & Minified
    ".map",
}

# Lock files retained for dependency detection but not counted as source code
LOCK_FILES: Set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
}

# Dangerous / Secret files that must NEVER be read or exposed
SECRET_FILE_PATTERNS = re.compile(
    r"^(\.env(?!\.(example|sample|template|dist)$).*|\.pem|\.key|id_rsa|.*\.keystore)$",
    re.IGNORECASE,
)

class RepoAnalyzerService:
    def __init__(
        self,
        max_traversal_depth: Optional[int] = None,
        max_files_indexed: Optional[int] = None,
        max_file_size_bytes: Optional[int] = None,
    ):
        self.max_traversal_depth = max_traversal_depth or settings.MAX_TRAVERSAL_DEPTH
        self.max_files_indexed = max_files_indexed or settings.MAX_FILES_INDEXED
        self.max_file_size_bytes = max_file_size_bytes or settings.MAX_FILE_SIZE_BYTES

    def analyze_repository(self, job_id: str, repo_name: str, local_path: str) -> RepoAnalysisResult:
        """
        Analyzes the cloned repository structure, detecting languages, manifests, and configs.
        """
        repo_root = Path(local_path).resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            raise FileNotFoundError(f"Local repository path does not exist: {local_path}")

        warnings: List[str] = []
        real_root = os.path.realpath(str(repo_root))

        total_directories = 0
        total_files = 0
        source_files = 0
        filtered_files = 0
        total_size_bytes = 0

        language_counts: Dict[str, int] = {}
        dependency_manifests: List[ManifestInfo] = []
        configuration_files: List[ConfigurationFileInfo] = []

        # Construct tree recursively
        tree_root, counts = self._traverse_directory(
            current_path=repo_root,
            repo_root=repo_root,
            real_root=real_root,
            current_depth=0,
            warnings=warnings,
        )

        total_directories = counts["directories"]
        total_files = counts["total_files"]
        source_files = counts["source_files"]
        filtered_files = counts["filtered_files"]
        total_size_bytes = counts["total_size_bytes"]
        language_counts = counts["languages"]
        manifest_files = counts["manifest_files"]
        config_files = counts["config_files"]

        # Parse detected dependency manifests
        for manifest_rel_path, ecosystem in manifest_files:
            manifest_abs = repo_root / manifest_rel_path
            manifest_info = self._parse_manifest_file(manifest_abs, manifest_rel_path, ecosystem, warnings)
            dependency_manifests.append(manifest_info)

        # Map configuration files
        for config_rel_path, config_type in config_files:
            configuration_files.append(
                ConfigurationFileInfo(file_path=config_rel_path, config_type=config_type)
            )

        # Compute language statistics
        recognized_languages = [lang for lang in language_counts if lang != "Unknown"]
        total_recognized_source = sum(language_counts[lang] for lang in recognized_languages)

        language_stats: List[LanguageStat] = []
        parsed_lang_count = 0
        unsupported_lang_count = 0
        for lang_name in sorted(recognized_languages, key=lambda l: language_counts[l], reverse=True):
            count = language_counts[lang_name]
            pct = round((count / total_recognized_source) * 100, 1) if total_recognized_source > 0 else 0.0
            is_supported = lang_name in PARSER_SUPPORTED_LANGUAGES
            if is_supported:
                parsed_lang_count += 1
            else:
                unsupported_lang_count += 1
            language_stats.append(
                LanguageStat(
                    name=lang_name,
                    file_count=count,
                    percentage=pct,
                    is_parser_supported=is_supported,
                )
            )

        stats = RepoStatistics(
            total_files=total_files,
            total_directories=total_directories,
            source_files=source_files,
            filtered_files=filtered_files,
            total_size_bytes=total_size_bytes,
            configuration_files=len(configuration_files),
            dependency_manifests=len(dependency_manifests),
            recognized_languages_count=len(language_stats),
            parsed_languages_count=parsed_lang_count,
            unsupported_languages_count=unsupported_lang_count,
        )

        return RepoAnalysisResult(
            repository_name=repo_name,
            directory_tree=tree_root,
            statistics=stats,
            languages=language_stats,
            dependency_files=dependency_manifests,
            configuration_files=configuration_files,
            analysis_status=StatusEnum.COMPLETED,
            warnings=warnings,
        )

    def _traverse_directory(
        self,
        current_path: Path,
        repo_root: Path,
        real_root: str,
        current_depth: int,
        warnings: List[str],
    ) -> Tuple[DirectoryTreeNode, Dict]:
        """
        Recursively scans directory tree with path traversal safety and file budgeting.
        """
        rel_dir_path = current_path.relative_to(repo_root).as_posix()
        if rel_dir_path == ".":
            rel_dir_path = ""

        dir_node = DirectoryTreeNode(
            name=current_path.name if current_depth > 0 else repo_root.name,
            path=rel_dir_path,
            type="directory",
            children=[],
        )

        counts = {
            "directories": 1 if current_depth > 0 else 0,
            "total_files": 0,
            "source_files": 0,
            "filtered_files": 0,
            "total_size_bytes": 0,
            "languages": {},
            "manifest_files": [],
            "config_files": [],
        }

        # Check depth limit
        if current_depth >= self.max_traversal_depth:
            warning_msg = f"Traversal depth limit reached at directory: '{rel_dir_path}'"
            if warning_msg not in warnings:
                warnings.append(warning_msg)
            return dir_node, counts

        try:
            entries = sorted(list(current_path.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (PermissionError, OSError) as exc:
            warnings.append(f"Could not read directory '{rel_dir_path}': {exc}")
            return dir_node, counts

        for entry in entries:
            # Check maximum indexed files budget
            if counts["source_files"] >= self.max_files_indexed:
                warning_msg = f"Maximum file index limit ({self.max_files_indexed}) reached."
                if warning_msg not in warnings:
                    warnings.append(warning_msg)
                break

            # Prevent symlink traversal out of root or cycles
            try:
                real_entry = os.path.realpath(str(entry))
                if not real_entry.startswith(real_root):
                    warnings.append(f"Skipping symlink escaping repository root: '{entry.name}'")
                    continue
            except (OSError, ValueError):
                continue

            entry_rel_path = entry.relative_to(repo_root).as_posix()

            if entry.is_dir():
                # Check directory exclusion
                if entry.name in EXCLUDED_DIRECTORIES or entry.name.startswith("."):
                    # Check if it's .github (we want .github/workflows)
                    if entry.name == ".github" and current_depth == 0:
                        pass
                    else:
                        continue

                sub_node, sub_counts = self._traverse_directory(
                    current_path=entry,
                    repo_root=repo_root,
                    real_root=real_root,
                    current_depth=current_depth + 1,
                    warnings=warnings,
                )
                dir_node.children.append(sub_node)

                # Aggregate metrics
                counts["directories"] += sub_counts["directories"]
                counts["total_files"] += sub_counts["total_files"]
                counts["source_files"] += sub_counts["source_files"]
                counts["filtered_files"] += sub_counts["filtered_files"]
                counts["total_size_bytes"] += sub_counts["total_size_bytes"]
                counts["manifest_files"].extend(sub_counts["manifest_files"])
                counts["config_files"].extend(sub_counts["config_files"])
                for lang, num in sub_counts["languages"].items():
                    counts["languages"][lang] = counts["languages"].get(lang, 0) + num

            elif entry.is_file():
                counts["total_files"] += 1

                # Secret exclusion check: never expose actual secrets
                if SECRET_FILE_PATTERNS.match(entry.name):
                    counts["filtered_files"] += 1
                    continue

                try:
                    file_size = entry.stat().st_size
                except (PermissionError, OSError):
                    file_size = 0

                ext = entry.suffix.lower()

                # Check if it is a configuration or dependency file
                config_type = self._classify_configuration_file(entry.name, entry_rel_path)
                ecosystem = self._classify_dependency_manifest(entry.name)

                if config_type:
                    counts["config_files"].append((entry_rel_path, config_type))

                if ecosystem:
                    counts["manifest_files"].append((entry_rel_path, ecosystem))

                # Check if file should be filtered (binary, temp, minified)
                if (
                    ext in EXCLUDED_EXTENSIONS
                    or entry.name.endswith(".min.js")
                    or entry.name.endswith(".min.css")
                    or entry.name in LOCK_FILES
                ):
                    counts["filtered_files"] += 1
                    # Note: We still create a lightweight node if it's a retained lock/config
                    if ecosystem or config_type:
                        file_node = DirectoryTreeNode(
                            name=entry.name,
                            path=entry_rel_path,
                            type="file",
                            size_bytes=file_size,
                            extension=ext,
                        )
                        dir_node.children.append(file_node)
                    continue

                # Valid source or retained file
                counts["source_files"] += 1
                counts["total_size_bytes"] += file_size

                # Language detection
                lang = LANGUAGE_EXTENSION_MAP.get(ext, "Unknown")
                if lang != "Unknown":
                    counts["languages"][lang] = counts["languages"].get(lang, 0) + 1

                file_node = DirectoryTreeNode(
                    name=entry.name,
                    path=entry_rel_path,
                    type="file",
                    size_bytes=file_size,
                    extension=ext,
                )
                dir_node.children.append(file_node)

        return dir_node, counts

    def _classify_configuration_file(self, filename: str, rel_path: str) -> Optional[str]:
        """Classifies common devops, build, and linter configuration files."""
        lower_name = filename.lower()
        if lower_name in ("dockerfile", "containerfile") or lower_name.startswith("dockerfile."):
            return "docker"
        if lower_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            return "docker_compose"
        if rel_path.startswith(".github/workflows/") and lower_name.endswith((".yml", ".yaml")):
            return "ci_cd"
        if lower_name in (".gitlab-ci.yml", "jenkinsfile", ".travis.yml", "azure-pipelines.yml"):
            return "ci_cd"
        if lower_name in (".env.example", ".env.sample", ".env.template", ".env.dist"):
            return "environment_template"
        if lower_name in ("tsconfig.json", "jsconfig.json"):
            return "typescript_config"
        if lower_name.startswith("vite.config.") or lower_name.startswith("webpack.config."):
            return "bundler_config"
        if lower_name in ("makefile", "cmakelists.txt", "meson.build"):
            return "build_tool"
        if lower_name.startswith(".eslintrc") or lower_name.startswith("eslint.config."):
            return "linter_config"
        if lower_name.startswith(".prettierrc") or lower_name.startswith("prettier.config."):
            return "formatter_config"
        return None

    def _classify_dependency_manifest(self, filename: str) -> Optional[str]:
        """Identifies dependency manifests and lock files by ecosystem."""
        lower_name = filename.lower()
        if lower_name == "package.json":
            return "javascript"
        if lower_name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb"):
            return "javascript_lock"
        if lower_name in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
            return "python_pip"
        if lower_name == "pyproject.toml":
            return "python_pyproject"
        if lower_name in ("pipfile", "pipfile.lock", "poetry.lock", "setup.py", "setup.cfg"):
            return "python_tooling"
        if lower_name in ("pom.xml", "build.gradle", "build.gradle.kts"):
            return "java_jvm"
        if lower_name in ("cmakelists.txt", "makefile", "meson.build"):
            return "c_cpp"
        if lower_name in ("go.mod", "go.sum"):
            return "go"
        if lower_name in ("cargo.toml", "cargo.lock"):
            return "rust"
        if lower_name in ("gemfile", "gemfile.lock"):
            return "ruby"
        if lower_name in ("composer.json", "composer.lock"):
            return "php"
        if lower_name == "package.swift":
            return "swift"
        return None

    def _parse_manifest_file(
        self,
        file_path: Path,
        rel_path: str,
        ecosystem: str,
        warnings: List[str],
    ) -> ManifestInfo:
        """Safely reads and extracts declared dependencies from supported manifest formats."""
        items: List[DependencyItem] = []

        try:
            size = file_path.stat().st_size
            if size > self.max_file_size_bytes:
                warnings.append(
                    f"Manifest '{rel_path}' exceeds size limit ({self.max_file_size_bytes} bytes). Skipping dependency parsing."
                )
                return ManifestInfo(
                    file_path=rel_path,
                    ecosystem=ecosystem,
                    dependencies_count=0,
                    dependencies=[],
                )

            content = file_path.read_text(encoding="utf-8", errors="replace")

            if ecosystem == "javascript":
                items = self._parse_package_json(content, rel_path)
            elif ecosystem == "python_pip":
                items = self._parse_requirements_txt(content, rel_path)
            elif ecosystem == "python_pyproject":
                items = self._parse_pyproject_toml(content, rel_path)
            elif ecosystem == "rust":
                items = self._parse_cargo_toml(content, rel_path)
            elif ecosystem == "go":
                items = self._parse_go_mod(content, rel_path)
            elif ecosystem == "java_jvm" and rel_path.endswith("pom.xml"):
                items = self._parse_pom_xml(content, rel_path)

        except Exception as exc:
            warnings.append(f"Failed to parse dependencies in '{rel_path}': {exc}")

        return ManifestInfo(
            file_path=rel_path,
            ecosystem=ecosystem,
            dependencies_count=len(items),
            dependencies=items,
        )

    def _parse_package_json(self, content: str, rel_path: str) -> List[DependencyItem]:
        """Parses package.json dependencies and devDependencies."""
        items: List[DependencyItem] = []
        data = json.loads(content)
        for dep_dict_name in ("dependencies", "devDependencies"):
            deps = data.get(dep_dict_name, {})
            if isinstance(deps, dict):
                for name, version in deps.items():
                    items.append(
                        DependencyItem(
                            name=name,
                            version_spec=str(version) if version else None,
                            source_file=rel_path,
                        )
                    )
        return items

    def _parse_requirements_txt(self, content: str, rel_path: str) -> List[DependencyItem]:
        """Parses requirements.txt dependencies with version specifications."""
        items: List[DependencyItem] = []
        req_pattern = re.compile(r"^([a-zA-Z0-9_.-]+(?:\[[a-zA-Z0-9_.,-]+\])?)\s*([=><~^!].*)?$")

        for line in content.splitlines():
            line = line.strip()
            # Skip empty, comments, or flags
            if not line or line.startswith("#") or line.startswith("-"):
                continue

            # Strip inline comments
            if " #" in line:
                line = line.split(" #", 1)[0].strip()

            match = req_pattern.match(line)
            if match:
                pkg_name = match.group(1).strip()
                version_spec = match.group(2).strip() if match.group(2) else None
                items.append(
                    DependencyItem(name=pkg_name, version_spec=version_spec, source_file=rel_path)
                )
        return items

    def _parse_pyproject_toml(self, content: str, rel_path: str) -> List[DependencyItem]:
        """Parses dependencies from pyproject.toml ([project.dependencies] or poetry)."""
        items: List[DependencyItem] = []
        try:
            data = tomllib.loads(content)
        except Exception:
            return items

        # PEP 621 [project.dependencies]
        project_deps = data.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            req_pattern = re.compile(r"^([a-zA-Z0-9_.-]+(?:\[[a-zA-Z0-9_.,-]+\])?)\s*([=><~^!].*)?$")
            for dep_str in project_deps:
                if isinstance(dep_str, str):
                    m = req_pattern.match(dep_str.strip())
                    if m:
                        items.append(
                            DependencyItem(
                                name=m.group(1).strip(),
                                version_spec=m.group(2).strip() if m.group(2) else None,
                                source_file=rel_path,
                            )
                        )

        # Poetry [tool.poetry.dependencies]
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if isinstance(poetry_deps, dict):
            for name, val in poetry_deps.items():
                if name.lower() == "python":
                    continue
                version_spec = None
                if isinstance(val, str):
                    version_spec = val
                elif isinstance(val, dict):
                    version_spec = val.get("version")
                items.append(
                    DependencyItem(name=name, version_spec=version_spec, source_file=rel_path)
                )

        return items

    def _parse_cargo_toml(self, content: str, rel_path: str) -> List[DependencyItem]:
        """Parses Rust dependencies from Cargo.toml."""
        items: List[DependencyItem] = []
        try:
            data = tomllib.loads(content)
        except Exception:
            return items

        for section_name in ("dependencies", "dev-dependencies", "build-dependencies"):
            deps = data.get(section_name, {})
            if isinstance(deps, dict):
                for name, val in deps.items():
                    version_spec = None
                    if isinstance(val, str):
                        version_spec = val
                    elif isinstance(val, dict):
                        version_spec = val.get("version")
                    items.append(
                        DependencyItem(name=name, version_spec=version_spec, source_file=rel_path)
                    )
        return items

    def _parse_go_mod(self, content: str, rel_path: str) -> List[DependencyItem]:
        """Parses Go dependencies from go.mod."""
        items: List[DependencyItem] = []
        in_require_block = False

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue

            if line.startswith("require ("):
                in_require_block = True
                continue
            if in_require_block:
                if line == ")":
                    in_require_block = False
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    items.append(
                        DependencyItem(name=parts[0], version_spec=parts[1], source_file=rel_path)
                    )
            elif line.startswith("require "):
                parts = line[len("require ") :].strip().split()
                if len(parts) >= 2:
                    items.append(
                        DependencyItem(name=parts[0], version_spec=parts[1], source_file=rel_path)
                    )

        return items

    def _parse_pom_xml(self, content: str, rel_path: str) -> List[DependencyItem]:
        """Parses Maven dependencies from pom.xml."""
        items: List[DependencyItem] = []
        try:
            root = ET.fromstring(content)
            # Handle potential XML namespace
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            for dep in root.findall(f".//{ns}dependencies/{ns}dependency"):
                group_id_el = dep.find(f"{ns}groupId")
                artifact_id_el = dep.find(f"{ns}artifactId")
                version_el = dep.find(f"{ns}version")

                group_id = group_id_el.text.strip() if group_id_el is not None and group_id_el.text else ""
                artifact_id = artifact_id_el.text.strip() if artifact_id_el is not None and artifact_id_el.text else ""
                version = version_el.text.strip() if version_el is not None and version_el.text else None

                name = f"{group_id}:{artifact_id}" if group_id else artifact_id
                if name:
                    items.append(DependencyItem(name=name, version_spec=version, source_file=rel_path))
        except Exception:
            pass

        return items

repo_analyzer_service = RepoAnalyzerService()
