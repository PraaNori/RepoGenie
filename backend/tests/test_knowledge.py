import os
import tempfile
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitecturalComponent,
    ArchitectureAnalysisResult,
    CallGraph,
    ClassInfo,
    ConfigurationFileInfo,
    DependencyGraph,
    DependencyItem,
    DirectoryTreeNode,
    EntryPointCandidate,
    FunctionInfo,
    ImportInfo,
    LanguageStat,
    ManifestInfo,
    ParsedFile,
    ParsedRepository,
    RelationshipEvidence,
    RepoAnalysisResult,
    RepoStatistics,
    RepositoryKnowledge,
    SourceLocation,
    StatusEnum,
)
from app.services.repo.call_graph_builder import call_graph_builder
from app.services.repo.dependency_resolver import dependency_resolver
from app.services.repo.knowledge_builder import knowledge_builder_service
from app.services.storage.job_store import job_store

client = TestClient(app)


@pytest.fixture
def sample_analysis():
    return RepoAnalysisResult(
        repository_name="test-owner/test-repo",
        directory_tree=DirectoryTreeNode(
            name="test-repo",
            path="",
            type="directory",
            children=[
                DirectoryTreeNode(name="src", path="src", type="directory", children=[]),
                DirectoryTreeNode(name="README.md", path="README.md", type="file"),
            ],
        ),
        statistics=RepoStatistics(
            total_files=10,
            total_directories=3,
            source_files=6,
            filtered_files=4,
            total_size_bytes=4096,
            configuration_files=2,
            dependency_manifests=1,
            recognized_languages_count=2,
        ),
        languages=[
            LanguageStat(name="Python", file_count=5, percentage=80.0),
            LanguageStat(name="TypeScript", file_count=1, percentage=20.0),
        ],
        dependency_files=[
            ManifestInfo(
                file_path="pyproject.toml",
                ecosystem="PyPI",
                dependencies_count=2,
                dependencies=[
                    DependencyItem(name="fastapi", version_spec="^0.110.0", source_file="pyproject.toml"),
                    DependencyItem(name="sqlalchemy", version_spec="^2.0.0", source_file="pyproject.toml"),
                ],
            )
        ],
        configuration_files=[
            ConfigurationFileInfo(file_path="Dockerfile", config_type="docker"),
            ConfigurationFileInfo(file_path=".github/workflows/ci.yml", config_type="ci_cd"),
        ],
        analysis_status=StatusEnum.COMPLETED,
        warnings=["Test structure warning"],
    )


@pytest.fixture
def sample_parsed_repo():
    loc = SourceLocation(file_path="src/main.py", start_line=1, start_column=0, end_line=10, end_column=0)
    return ParsedRepository(
        job_id="test-job-uuid",
        repository_name="test-owner/test-repo",
        total_parsed_files=2,
        total_functions=3,
        total_classes=1,
        total_methods=2,
        total_imports=2,
        total_function_calls=4,
        supported_languages=["Python"],
        files=[
            ParsedFile(
                file_path="src/main.py",
                language="Python",
                status="success",
                total_lines=50,
                imports=[
                    ImportInfo(module="fastapi", symbols=["FastAPI"], file_path="src/main.py", line_number=1),
                    ImportInfo(module=".service", symbols=["UserService"], file_path="src/main.py", line_number=2),
                ],
                functions=[FunctionInfo(name="health", file_path="src/main.py", location=loc)],
            ),
            ParsedFile(
                file_path="src/service.py",
                language="Python",
                status="success",
                total_lines=40,
                classes=[ClassInfo(name="UserService", file_path="src/service.py", location=loc)],
            ),
        ],
        parsing_status=StatusEnum.COMPLETED,
        warnings=[],
    )


@pytest.fixture
def sample_architecture():
    return ArchitectureAnalysisResult(
        job_id="test-job-uuid",
        repository_name="test-owner/test-repo",
        dependency_graph=dependency_resolver.build_dependency_graph([], set()),
        call_graph=call_graph_builder.build_call_graph([], set()),
        inheritance_relationships=[],
        class_references=[],
        entry_points=[
            EntryPointCandidate(
                file_path="src/main.py",
                entry_type="python_main_guard",
                symbol_or_command='if __name__ == "__main__":',
                confidence="high",
                evidence=[
                    RelationshipEvidence(
                        evidence_type="main_guard",
                        statement='if __name__ == "__main__":',
                        file_path="src/main.py",
                        line_number=45,
                        confidence="high",
                    )
                ],
            )
        ],
        components=[
            ArchitecturalComponent(file_path="src/main.py", category="api_route", confidence="high", evidence=["Path contains route"]),
            ArchitecturalComponent(file_path="src/service.py", category="service", confidence="high", evidence=["Path contains service"]),
        ],
        component_counts={"api_route": 1, "service": 1},
        analysis_status=StatusEnum.COMPLETED,
        warnings=[],
    )


def test_readme_extraction_and_project_overview():
    with tempfile.TemporaryDirectory() as tmpdir:
        readme_path = os.path.join(tmpdir, "README.md")
        content = """# My Sample Project

A modern, high-performance web service for data processing.
Built with FastAPI and clean architecture.

## Features
* Fast async request handling
* Integrated database migrations
* Fully typed Pydantic models

## Known Limitations
* Maximum request payload size is 10 MB

> [!WARNING]
> Do not expose debug endpoints in production environments.
"""
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)

        overview, evidence = knowledge_builder_service.extract_readme_overview(
            local_path=tmpdir,
            all_files={"README.md", "src/main.py"},
        )

        assert overview.readme_available is True
        assert overview.readme_path == "README.md"
        assert overview.description is not None
        assert "A modern, high-performance web service" in overview.description
        assert len(overview.features) == 3
        assert "Fast async request handling" in overview.features
        assert len(overview.limitations) == 1
        assert "10 MB" in overview.limitations[0]
        assert len(overview.documentation_warnings) >= 1
        assert len(evidence) >= 3


def test_consolidate_technology_stack(sample_analysis, sample_parsed_repo, sample_architecture):
    stack, _ = knowledge_builder_service.consolidate_technology_stack(
        analysis=sample_analysis,
        parsed_repo=sample_parsed_repo,
        architecture=sample_architecture,
        all_files={"src/main.py", "src/service.py", "Dockerfile", ".github/workflows/ci.yml"},
    )

    # 1. Languages
    lang_names = [l.name for l in stack.languages]
    assert "Python" in lang_names
    assert "TypeScript" in lang_names

    # 2. Frameworks (FastAPI declared and imported -> confirmed: True)
    fw_names = [f.name for f in stack.frameworks]
    assert "FastAPI" in fw_names
    fastapi_item = next(f for f in stack.frameworks if f.name == "FastAPI")
    assert fastapi_item.is_confirmed is True

    # 3. Databases (SQLAlchemy declared in pyproject.toml)
    db_names = [d.name for d in stack.databases]
    assert "SQLAlchemy" in db_names

    # 4. Deployment (Dockerfile and CI/CD workflows)
    dep_names = [d.name for d in stack.deployment_technologies]
    assert "Docker" in dep_names
    assert "GitHub Actions / CI" in dep_names


def test_identify_important_files(sample_analysis, sample_architecture):
    files = knowledge_builder_service.identify_important_files(
        analysis=sample_analysis,
        architecture=sample_architecture,
        all_files={"README.md", "pyproject.toml", "Dockerfile", "src/main.py", "src/service.py"},
    )

    paths = [f.relative_path for f in files]
    assert "README.md" in paths
    assert "src/main.py" in paths
    assert "pyproject.toml" in paths
    assert "Dockerfile" in paths

    # Check that README has top score 10.0 and entry point has 9.5
    readme_item = next(f for f in files if f.relative_path == "README.md")
    assert readme_item.score == 10.0
    assert readme_item.category == "readme"

    ep_item = next(f for f in files if f.relative_path == "src/main.py")
    assert ep_item.score == 9.5
    assert ep_item.category == "entry_point"


def test_build_knowledge_orchestration(sample_analysis, sample_parsed_repo, sample_architecture):
    with tempfile.TemporaryDirectory() as tmpdir:
        readme_path = os.path.join(tmpdir, "README.md")
        with open(readme_path, "w") as f:
            f.write("# Test Repo\nAutomated repository processor.\n## Features\n* Auto ingest\n")

        knowledge = knowledge_builder_service.build_knowledge(
            job_id="test-job-uuid",
            repo_name="test-owner/test-repo",
            repo_owner="test-owner",
            repo_url="https://github.com/test-owner/test-repo",
            local_path=tmpdir,
            size_mb=2.5,
            file_count=10,
            analysis=sample_analysis,
            parsed_repo=sample_parsed_repo,
            architecture=sample_architecture,
        )

        assert isinstance(knowledge, RepositoryKnowledge)
        assert knowledge.schema_version == "1.0"
        assert knowledge.repository.name == "test-owner/test-repo"
        assert knowledge.repository.owner == "test-owner"
        assert knowledge.repository.size_mb == 2.5
        assert knowledge.project_overview.readme_available is True
        assert len(knowledge.project_overview.features) == 1
        assert len(knowledge.important_files) >= 3
        assert len(knowledge.source_evidence) >= 1
        assert knowledge.statistics.total_lines_of_code == 90
        assert "Test structure warning" in knowledge.warnings
        assert knowledge.analysis_metadata.analysis_status == StatusEnum.COMPLETED


def test_build_knowledge_missing_prerequisites():
    with pytest.raises(ValueError, match="Repository structure analysis"):
        knowledge_builder_service.build_knowledge(
            job_id="err-job",
            repo_name="repo",
            repo_owner="owner",
            repo_url="https://github.com/owner/repo",
            analysis=None,
            parsed_repo=None,
            architecture=None,
        )


def test_get_knowledge_api_endpoint(sample_analysis, sample_parsed_repo, sample_architecture):
    # 1. Non-existent job
    resp = client.get("/api/v1/jobs/unknown-uuid-1234/knowledge")
    assert resp.status_code == 404

    # 2. Create job in store
    job = job_store.create_job(
        repo_url="https://github.com/test-owner/test-repo",
        repo_name="test-owner/test-repo",
        repository_owner="test-owner",
        repository_name="test-repo",
        clone_url="https://github.com/test-owner/test-repo.git",
    )
    job_id = job.job_id

    # In progress status returns 409
    job_store.update_job_code_parsing_started(job_id)
    in_prog_resp = client.get(f"/api/v1/jobs/{job_id}/knowledge")
    assert in_prog_resp.status_code == 409

    # Generate and store knowledge, mark stages complete
    knowledge = knowledge_builder_service.build_knowledge(
        job_id=job_id,
        repo_name="test-owner/test-repo",
        repo_owner="test-owner",
        repo_url="https://github.com/test-owner/test-repo",
        size_mb=1.2,
        file_count=8,
        analysis=sample_analysis,
        parsed_repo=sample_parsed_repo,
        architecture=sample_architecture,
    )

    internal = job_store.get_internal_job(job_id)
    assert internal is not None
    internal.ingestion_status = StatusEnum.COMPLETED
    internal.stages[0].status = StatusEnum.COMPLETED
    internal.stages[1].status = StatusEnum.COMPLETED
    job_store.update_job_knowledge_success(
        job_id=job_id,
        code_analysis=sample_parsed_repo,
        architecture=sample_architecture,
        knowledge=knowledge,
    )

    # Fetch knowledge via API
    ok_resp = client.get(f"/api/v1/jobs/{job_id}/knowledge")
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["schema_version"] == "1.0"
    assert data["repository"]["name"] == "test-owner/test-repo"
    assert "technology_stack" in data
    assert "important_files" in data
    assert "source_evidence" in data
    assert "statistics" in data
