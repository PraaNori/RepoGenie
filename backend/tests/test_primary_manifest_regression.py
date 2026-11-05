"""
Regression tests for:
1. Repository containing a supported manifest with tools (no NameError: primary_manifest).
2. Repository containing multiple manifests with tools correctly mapped to their respective manifests.
3. Repository containing no dependency manifest (primary_manifest is None, no NameError).
4. Repository containing JavaScript (.gs) and C++ (.ino) source files.
5. Real repositories sindresorhus/is and pallets/click.
"""

import os
import pytest
from app.models.schemas import (
    ArchitectureAnalysisResult,
    CallGraph,
    ConfigurationFileInfo,
    DependencyGraph,
    DependencyItem,
    DirectoryTreeNode,
    LanguageStat,
    ManifestInfo,
    ParsedFile,
    ParsedRepository,
    RepoAnalysisResult,
    RepoStatistics,
    StatusEnum,
)
from app.services.repo.analyzer import repo_analyzer_service
from app.services.repo.architecture_analyzer import architecture_analyzer_service
from app.services.repo.code_parser import code_parser_service
from app.services.repo.knowledge_builder import knowledge_builder_service


def test_repository_with_supported_manifest_containing_tools():
    """1. Repository containing a supported manifest with tools must not raise NameError: primary_manifest."""
    analysis = RepoAnalysisResult(
        repository_name="test-org/py-tools-repo",
        directory_tree=DirectoryTreeNode(
            name="py-tools-repo",
            path="",
            type="directory",
            children=[
                DirectoryTreeNode(name="requirements.txt", path="requirements.txt", type="file"),
                DirectoryTreeNode(name="main.py", path="main.py", type="file"),
            ],
        ),
        statistics=RepoStatistics(
            total_files=2,
            total_directories=1,
            source_files=1,
            filtered_files=1,
            total_size_bytes=500,
            configuration_files=0,
            dependency_manifests=1,
            recognized_languages_count=1,
        ),
        languages=[LanguageStat(name="Python", file_count=1, percentage=100.0, is_parser_supported=True)],
        dependency_files=[
            ManifestInfo(
                file_path="requirements.txt",
                ecosystem="pip",
                dependencies=[
                    DependencyItem(name="pytest", version_spec=">=7.0.0", source_file="requirements.txt"),
                    DependencyItem(name="black", version_spec=">=23.0.0", source_file="requirements.txt"),
                    DependencyItem(name="fastapi", version_spec=">=0.100.0", source_file="requirements.txt"),
                ],
                dependencies_count=3,
            )
        ],
        configuration_files=[],
        warnings=[],
    )

    parsed = ParsedRepository(
        job_id="test-job-manifest",
        repository_name="test-org/py-tools-repo",
        total_parsed_files=1,
        total_functions=1,
        total_classes=0,
        total_methods=0,
        total_imports=1,
        total_function_calls=2,
        supported_languages=["Python"],
        files=[ParsedFile(file_path="main.py", language="Python", status="success", total_lines=25)],
    )

    arch = ArchitectureAnalysisResult(
        job_id="test-job-manifest",
        repository_name="test-org/py-tools-repo",
        dependency_graph=DependencyGraph(),
        call_graph=CallGraph(),
        entry_points=[],
        inheritance_relationships=[],
        components=[],
    )

    # Must complete without NameError
    knowledge = knowledge_builder_service.build_knowledge(
        job_id="test-job-manifest",
        repo_name="py-tools-repo",
        repo_owner="test-org",
        repo_url="https://github.com/test-org/py-tools-repo",
        local_path="",
        size_mb=0.1,
        file_count=2,
        analysis=analysis,
        parsed_repo=parsed,
        architecture=arch,
    )

    tool_names = [t.name for t in knowledge.technology_stack.tools]
    assert "Pytest" in tool_names
    assert "Black" in tool_names

    tool_evidence = [e for e in knowledge.source_evidence if "Tool:" in (e.symbol_or_statement or "")]
    assert len(tool_evidence) >= 1
    for ev in tool_evidence:
        assert ev.file_path == "requirements.txt"
        assert ev.file_path != "source_code"


def test_repository_with_multiple_manifests():
    """2. Repository containing multiple manifests maps dependencies to the correct manifest file."""
    analysis = RepoAnalysisResult(
        repository_name="test-org/monorepo",
        directory_tree=DirectoryTreeNode(
            name="monorepo",
            path="",
            type="directory",
            children=[
                DirectoryTreeNode(name="backend/requirements.txt", path="backend/requirements.txt", type="file"),
                DirectoryTreeNode(name="frontend/package.json", path="frontend/package.json", type="file"),
                DirectoryTreeNode(name="backend/main.py", path="backend/main.py", type="file"),
                DirectoryTreeNode(name="frontend/src/index.js", path="frontend/src/index.js", type="file"),
            ],
        ),
        statistics=RepoStatistics(
            total_files=4,
            total_directories=3,
            source_files=2,
            filtered_files=2,
            total_size_bytes=1000,
            configuration_files=0,
            dependency_manifests=2,
            recognized_languages_count=2,
        ),
        languages=[
            LanguageStat(name="Python", file_count=1, percentage=50.0, is_parser_supported=True),
            LanguageStat(name="JavaScript", file_count=1, percentage=50.0, is_parser_supported=True),
        ],
        dependency_files=[
            ManifestInfo(
                file_path="backend/requirements.txt",
                ecosystem="pip",
                dependencies=[
                    DependencyItem(name="pytest", version_spec=">=7.0.0", source_file="backend/requirements.txt"),
                ],
                dependencies_count=1,
            ),
            ManifestInfo(
                file_path="frontend/package.json",
                ecosystem="npm",
                dependencies=[
                    DependencyItem(name="jest", version_spec="^29.0.0", source_file="frontend/package.json"),
                    DependencyItem(name="eslint", version_spec="^8.0.0", source_file="frontend/package.json"),
                ],
                dependencies_count=2,
            ),
        ],
        configuration_files=[],
        warnings=[],
    )

    parsed = ParsedRepository(
        job_id="test-job-multi-manifest",
        repository_name="test-org/monorepo",
        total_parsed_files=2,
        total_functions=2,
        total_classes=0,
        total_methods=0,
        total_imports=2,
        total_function_calls=2,
        supported_languages=["Python", "JavaScript"],
        files=[
            ParsedFile(file_path="backend/main.py", language="Python", status="success", total_lines=20),
            ParsedFile(file_path="frontend/src/index.js", language="JavaScript", status="success", total_lines=20),
        ],
    )

    arch = ArchitectureAnalysisResult(
        job_id="test-job-multi-manifest",
        repository_name="test-org/monorepo",
        dependency_graph=DependencyGraph(),
        call_graph=CallGraph(),
        entry_points=[],
        inheritance_relationships=[],
        components=[],
    )

    knowledge = knowledge_builder_service.build_knowledge(
        job_id="test-job-multi-manifest",
        repo_name="monorepo",
        repo_owner="test-org",
        repo_url="https://github.com/test-org/monorepo",
        local_path="",
        size_mb=0.2,
        file_count=4,
        analysis=analysis,
        parsed_repo=parsed,
        architecture=arch,
    )

    tool_names = [t.name for t in knowledge.technology_stack.tools]
    assert "Pytest" in tool_names
    assert "Jest" in tool_names
    assert "ESLint" in tool_names

    pytest_ev = next(e for e in knowledge.source_evidence if "Pytest" in e.symbol_or_statement)
    assert pytest_ev.file_path == "backend/requirements.txt"

    jest_ev = next(e for e in knowledge.source_evidence if "Jest" in e.symbol_or_statement)
    assert jest_ev.file_path == "frontend/package.json"


def test_repository_with_no_dependency_manifest():
    """3. Repository containing no dependency manifest defines primary_manifest as None without crashing."""
    analysis = RepoAnalysisResult(
        repository_name="test-org/no-manifest-repo",
        directory_tree=DirectoryTreeNode(
            name="no-manifest-repo",
            path="",
            type="directory",
            children=[
                DirectoryTreeNode(name="script.py", path="script.py", type="file"),
            ],
        ),
        statistics=RepoStatistics(
            total_files=1,
            total_directories=1,
            source_files=1,
            filtered_files=0,
            total_size_bytes=200,
            configuration_files=0,
            dependency_manifests=0,
            recognized_languages_count=1,
        ),
        languages=[LanguageStat(name="Python", file_count=1, percentage=100.0, is_parser_supported=True)],
        dependency_files=[],  # No dependency manifest!
        configuration_files=[],
        warnings=[],
    )

    # script.py imports unittest
    from app.models.schemas import ImportInfo, SourceLocation
    loc = SourceLocation(file_path="script.py", start_line=1, start_column=0, end_line=1, end_column=15)
    parsed = ParsedRepository(
        job_id="test-job-no-manifest",
        repository_name="test-org/no-manifest-repo",
        total_parsed_files=1,
        total_functions=0,
        total_classes=0,
        total_methods=0,
        total_imports=1,
        total_function_calls=0,
        supported_languages=["Python"],
        files=[
            ParsedFile(
                file_path="script.py",
                language="Python",
                status="success",
                total_lines=10,
                imports=[ImportInfo(module="unittest", imported_symbols=[], location=loc, file_path="script.py", line_number=1)],
            )
        ],
    )

    arch = ArchitectureAnalysisResult(
        job_id="test-job-no-manifest",
        repository_name="test-org/no-manifest-repo",
        dependency_graph=DependencyGraph(),
        call_graph=CallGraph(),
        entry_points=[],
        inheritance_relationships=[],
        components=[],
    )

    # Must not raise NameError: primary_manifest
    knowledge = knowledge_builder_service.build_knowledge(
        job_id="test-job-no-manifest",
        repo_name="no-manifest-repo",
        repo_owner="test-org",
        repo_url="https://github.com/test-org/no-manifest-repo",
        local_path="",
        size_mb=0.1,
        file_count=1,
        analysis=analysis,
        parsed_repo=parsed,
        architecture=arch,
    )

    tool_names = [t.name for t in knowledge.technology_stack.tools]
    assert "Unittest" in tool_names

    # The tool imported in script.py should resolve to script.py
    unittest_ev = next(e for e in knowledge.source_evidence if "Unittest" in e.symbol_or_statement)
    assert unittest_ev.file_path == "script.py"


def test_repository_containing_javascript_and_cpp_source_files():
    """4. Repository containing JavaScript (.gs) and C++ (.ino) builds knowledge without NameError."""
    repo_path = "backend/tests/fixtures/repos/anomaly_gcp"
    job_id = "test-job-anomaly-gcp"

    analysis = repo_analyzer_service.analyze_repository(job_id=job_id, repo_name="anomaly_gcp", local_path=repo_path)
    parsed = code_parser_service.parse_repository(job_id=job_id, repo_name="anomaly_gcp", local_path=repo_path, analysis=analysis)
    arch = architecture_analyzer_service.analyze_architecture(job_id=job_id, repo_name="anomaly_gcp", parsed_repo=parsed, analysis=analysis, local_path=repo_path)

    knowledge = knowledge_builder_service.build_knowledge(
        job_id=job_id,
        repo_name="Anomaly-Detection-using-GCP",
        repo_owner="sachinsingh2156",
        repo_url="https://github.com/sachinsingh2156/Anomaly-Detection-using-GCP",
        local_path=repo_path,
        size_mb=1.0,
        file_count=analysis.statistics.total_files,
        analysis=analysis,
        parsed_repo=parsed,
        architecture=arch,
    )

    assert knowledge.analysis_metadata.analysis_status == StatusEnum.COMPLETED
    languages = [l.name for l in knowledge.technology_stack.languages]
    assert "SQL" in languages
    assert "JavaScript" in languages
    assert "C++" in languages


def test_existing_repos_is_and_click():
    """5. Real repositories sindresorhus/is and pallets/click build knowledge cleanly."""
    for repo_name, fixture_dir, repo_url in [
        ("is", "backend/tests/fixtures/repos/is", "https://github.com/sindresorhus/is"),
        ("click", "backend/tests/fixtures/repos/click", "https://github.com/pallets/click"),
    ]:
        job_id = f"test-job-{repo_name}"
        analysis = repo_analyzer_service.analyze_repository(job_id=job_id, repo_name=repo_name, local_path=fixture_dir)
        parsed = code_parser_service.parse_repository(job_id=job_id, repo_name=repo_name, local_path=fixture_dir, analysis=analysis)
        arch = architecture_analyzer_service.analyze_architecture(job_id=job_id, repo_name=repo_name, parsed_repo=parsed, analysis=analysis, local_path=fixture_dir)

        knowledge = knowledge_builder_service.build_knowledge(
            job_id=job_id,
            repo_name=repo_name,
            repo_owner="test-owner",
            repo_url=repo_url,
            local_path=fixture_dir,
            size_mb=2.0,
            file_count=analysis.statistics.total_files,
            analysis=analysis,
            parsed_repo=parsed,
            architecture=arch,
        )

        assert knowledge.analysis_metadata.analysis_status == StatusEnum.COMPLETED
        assert len(knowledge.technology_stack.languages) >= 1
