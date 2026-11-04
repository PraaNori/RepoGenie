"""
Unit and integration tests for repository structure, file filtering, language detection, and dependency parsing.
"""
import os
from pathlib import Path
import pytest
from app.models.schemas import DirectoryTreeNode, RepoAnalysisResult
from app.services.repo.analyzer import (
    EXCLUDED_DIRECTORIES,
    EXCLUDED_EXTENSIONS,
    LANGUAGE_EXTENSION_MAP,
    RepoAnalyzerService,
    repo_analyzer_service,
)

@pytest.fixture
def sample_repo(tmp_path):
    """Creates a realistic test repository structure with multiple languages, configs, and manifests."""
    repo = tmp_path / "sample_project"
    repo.mkdir(parents=True, exist_ok=True)

    # 1. Source files
    src = repo / "src"
    src.mkdir()
    (src / "main.py").write_text("def main():\n    print('Hello')\n")
    (src / "utils.py").write_text("def helper(): pass\n")
    (src / "app.ts").write_text("export const run = () => console.log('TS');\n")
    (src / "index.js").write_text("console.log('JS');\n")
    (src / "styles.css").write_text("body { margin: 0; }\n")
    (src / "query.sql").write_text("SELECT * FROM users;\n")

    # 2. Nested directory with other languages
    native = repo / "native"
    native.mkdir()
    (native / "core.c").write_text("int main() { return 0; }\n")
    (native / "core.h").write_text("#pragma once\n")
    (native / "logic.cpp").write_text("#include <iostream>\n")
    (native / "server.go").write_text("package main\nfunc main() {}\n")
    (native / "lib.rs").write_text("pub fn test() {}\n")

    # 3. Empty directory
    (repo / "empty_dir").mkdir()

    # 4. Excluded directories and files
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

    node_modules = repo / "node_modules"
    node_modules.mkdir()
    (node_modules / "lodash.js").write_text("module.exports = {};\n")

    venv_dir = repo / ".venv"
    venv_dir.mkdir()
    (venv_dir / "lib.py").write_text("x = 1\n")

    dist_dir = repo / "dist"
    dist_dir.mkdir()
    (dist_dir / "bundle.js").write_text("bundle content\n")

    # Excluded files in src
    (src / "app.pyc").write_bytes(b"\x00\x01\x02")
    (src / "image.png").write_bytes(b"\x89PNG")
    (src / "temp.tmp").write_text("temp data")
    (src / "bundle.min.js").write_text("minified js")

    # Secret file that must NOT be exposed
    (repo / ".env").write_text("SECRET_KEY=123456\n")

    # 5. Retained documentation and configuration files
    (repo / "README.md").write_text("# Sample Project\n\nEducational demo.\n")
    (repo / "Dockerfile").write_text("FROM python:3.12-slim\n")
    (repo / "docker-compose.yml").write_text("version: '3.8'\nservices:\n  web:\n    build: .\n")
    (repo / ".env.example").write_text("API_KEY=your_key_here\n")
    (repo / "tsconfig.json").write_text('{"compilerOptions": {"target": "ES6"}}\n')

    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\njobs: {}\n")

    # 6. Dependency manifests
    (repo / "requirements.txt").write_text(
        "fastapi>=0.115.0\n"
        "uvicorn[standard]>=0.32.0\n"
        "pydantic~=2.10.0\n"
        "# comment line\n"
        "-r other.txt\n"
    )

    (repo / "package.json").write_text(
        '{\n'
        '  "name": "sample-ui",\n'
        '  "dependencies": {\n'
        '    "react": "^18.3.1",\n'
        '    "react-dom": "^18.3.1"\n'
        '  },\n'
        '  "devDependencies": {\n'
        '    "vite": "^6.0.0"\n'
        '  }\n'
        '}\n'
    )

    (repo / "package-lock.json").write_text('{"name": "sample-ui", "lockfileVersion": 3}\n')

    (repo / "pyproject.toml").write_text(
        '[project]\n'
        'name = "sample-python"\n'
        'dependencies = [\n'
        '  "httpx>=0.28.0",\n'
        '  "pytest>=8.3.0"\n'
        ']\n'
    )

    (repo / "Cargo.toml").write_text(
        '[package]\n'
        'name = "sample-rust"\n'
        '[dependencies]\n'
        'serde = "1.0"\n'
        'tokio = { version = "1.0" }\n'
    )

    (repo / "go.mod").write_text(
        'module example.com/sample\n\n'
        'go 1.22\n\n'
        'require (\n'
        '    github.com/gin-gonic/gin v1.9.1\n'
        '    golang.org/x/crypto v0.21.0\n'
        ')\n'
    )

    (repo / "pom.xml").write_text(
        '<project>\n'
        '  <dependencies>\n'
        '    <dependency>\n'
        '      <groupId>org.springframework.boot</groupId>\n'
        '      <artifactId>spring-boot-starter-web</artifactId>\n'
        '      <version>3.2.0</version>\n'
        '    </dependency>\n'
        '  </dependencies>\n'
        '</project>\n'
    )

    return repo

def test_repository_traversal_and_filtering(sample_repo):
    result = repo_analyzer_service.analyze_repository(
        job_id="test-analysis-1",
        repo_name="sample-project",
        local_path=str(sample_repo),
    )

    assert isinstance(result, RepoAnalysisResult)
    assert result.repository_name == "sample-project"
    assert result.analysis_status == "completed"

    # Verify exclusions: .git, node_modules, .venv, dist must NOT appear in tree
    def collect_paths(node: DirectoryTreeNode) -> list:
        paths = [node.path]
        if node.children:
            for c in node.children:
                paths.extend(collect_paths(c))
        return paths

    all_paths = collect_paths(result.directory_tree)
    assert not any(p == ".git" or p.startswith(".git/") for p in all_paths)
    assert not any(p == "node_modules" or p.startswith("node_modules/") for p in all_paths)
    assert not any(p == ".venv" or p.startswith(".venv/") for p in all_paths)
    assert not any(p == "dist" or p.startswith("dist/") for p in all_paths)

    # Filtered binary / temp files must be counted
    assert result.statistics.filtered_files >= 4
    # Real .env secret must not be indexed
    assert ".env" not in all_paths

    # README and source files must be indexed
    assert "README.md" in all_paths
    assert "src/main.py" in all_paths
    assert "native/lib.rs" in all_paths
    assert "empty_dir" in all_paths

def test_language_detection_distribution(sample_repo):
    result = repo_analyzer_service.analyze_repository(
        job_id="test-analysis-2",
        repo_name="sample-project",
        local_path=str(sample_repo),
    )

    lang_names = [l.name for l in result.languages]
    assert "Python" in lang_names
    assert "JavaScript" in lang_names
    assert "TypeScript" in lang_names
    assert "C" in lang_names
    assert "C++" in lang_names
    assert "Go" in lang_names
    assert "Rust" in lang_names
    assert "CSS" in lang_names
    assert "SQL" in lang_names

    # Check percentage calculation
    total_percentage = sum(l.percentage for l in result.languages)
    assert 99.0 <= total_percentage <= 101.0  # account for rounding

    # Python has 2 files (main.py, utils.py)
    py_stat = next(l for l in result.languages if l.name == "Python")
    assert py_stat.file_count == 2

def test_all_twenty_languages():
    """Verify that all 20 required languages are mapped."""
    required_languages = [
        "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go",
        "Rust", "Ruby", "PHP", "Swift", "Kotlin", "HTML", "CSS", "SQL",
        "Shell", "Dart", "Vue", "Svelte"
    ]
    mapped_languages = set(LANGUAGE_EXTENSION_MAP.values())
    for lang in required_languages:
        assert lang in mapped_languages, f"Missing mapping for required language: {lang}"

def test_dependency_detection(sample_repo):
    result = repo_analyzer_service.analyze_repository(
        job_id="test-analysis-3",
        repo_name="sample-project",
        local_path=str(sample_repo),
    )

    manifest_map = {m.file_path: m for m in result.dependency_files}
    assert "requirements.txt" in manifest_map
    assert "package.json" in manifest_map
    assert "pyproject.toml" in manifest_map
    assert "Cargo.toml" in manifest_map
    assert "go.mod" in manifest_map
    assert "pom.xml" in manifest_map

    # Test requirements.txt dependencies
    req_deps = {d.name: d.version_spec for d in manifest_map["requirements.txt"].dependencies}
    assert "fastapi" in req_deps
    assert req_deps["fastapi"] == ">=0.115.0"
    assert "uvicorn[standard]" in req_deps
    assert "pydantic" in req_deps

    # Test package.json dependencies
    pkg_deps = {d.name: d.version_spec for d in manifest_map["package.json"].dependencies}
    assert "react" in pkg_deps
    assert pkg_deps["react"] == "^18.3.1"
    assert "vite" in pkg_deps

    # Test Cargo.toml dependencies
    cargo_deps = {d.name: d.version_spec for d in manifest_map["Cargo.toml"].dependencies}
    assert "serde" in cargo_deps
    assert cargo_deps["serde"] == "1.0"

    # Test go.mod dependencies
    go_deps = {d.name: d.version_spec for d in manifest_map["go.mod"].dependencies}
    assert "github.com/gin-gonic/gin" in go_deps
    assert go_deps["github.com/gin-gonic/gin"] == "v1.9.1"

    # Test pom.xml dependencies
    pom_deps = {d.name: d.version_spec for d in manifest_map["pom.xml"].dependencies}
    assert "org.springframework.boot:spring-boot-starter-web" in pom_deps
    assert pom_deps["org.springframework.boot:spring-boot-starter-web"] == "3.2.0"

def test_configuration_detection(sample_repo):
    result = repo_analyzer_service.analyze_repository(
        job_id="test-analysis-4",
        repo_name="sample-project",
        local_path=str(sample_repo),
    )

    config_map = {c.file_path: c.config_type for c in result.configuration_files}
    assert "Dockerfile" in config_map
    assert config_map["Dockerfile"] == "docker"
    assert "docker-compose.yml" in config_map
    assert config_map["docker-compose.yml"] == "docker_compose"
    assert ".github/workflows/ci.yml" in config_map
    assert config_map[".github/workflows/ci.yml"] == "ci_cd"
    assert ".env.example" in config_map
    assert config_map[".env.example"] == "environment_template"
    assert "tsconfig.json" in config_map
    assert config_map["tsconfig.json"] == "typescript_config"

def test_symlink_path_traversal_safety(tmp_path):
    """Ensure symlinks pointing outside the repository root are ignored."""
    repo = tmp_path / "safe_repo"
    repo.mkdir()
    (repo / "index.py").write_text("print('safe')")

    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("super_secret")

    # Create symlink pointing outside
    symlink_path = repo / "escaped_link"
    try:
        os.symlink(str(outside), str(symlink_path))
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/filesystem")

    service = RepoAnalyzerService()
    result = service.analyze_repository("job-sym", "safe-repo", str(repo))

    all_paths = [node.path for node in result.directory_tree.children or []]
    assert "escaped_link" not in all_paths
    assert any("escaping" in w.lower() for w in result.warnings)

def test_traversal_depth_limit(tmp_path):
    """Ensure traversal depth limit is respected and reported in warnings."""
    repo = tmp_path / "deep_repo"
    repo.mkdir()

    current = repo
    for i in range(5):
        current = current / f"level_{i}"
        current.mkdir()
        (current / f"file_{i}.py").write_text("x = 1")

    # Set depth limit to 2
    service = RepoAnalyzerService(max_traversal_depth=2)
    result = service.analyze_repository("job-depth", "deep-repo", str(repo))

    assert any("depth limit reached" in w.lower() for w in result.warnings)
