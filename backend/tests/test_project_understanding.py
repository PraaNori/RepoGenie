import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitecturalComponent,
    ArchitectureSummary,
    CallGraph,
    CodeStructureSummary,
    DependencyGraph,
    DirectoryTreeNode,
    EntryPointCandidate,
    ImportantFileInfo,
    KnowledgeAnalysisMetadata,
    ProjectOverviewInfo,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    SourceEvidenceRecord,
    StageEnum,
    StageInfo,
    StatusEnum,
    TechnologyItem,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.exceptions import AIInvalidResponseError
from app.services.ai.project_understanding import (
    EvidenceBuilder,
    ProjectUnderstanding,
    ProjectUnderstandingAnalyzer,
    evidence_builder_service,
    project_understanding_analyzer,
)
from app.services.ai.schemas import LLMResponse, TokenUsageRecord
from app.services.storage.job_store import PIPELINE_STAGES, JobInternal, job_store

client = TestClient(app)


@pytest.fixture
def sample_knowledge() -> RepositoryKnowledge:
    return RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="pallets/click",
            owner="pallets",
            repository_url="https://github.com/pallets/click",
            clone_url="https://github.com/pallets/click.git",
            clone_status=StatusEnum.COMPLETED,
            size_mb=4.8,
            file_count=42,
            description="Composable command line interface toolkit.",
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.rst",
            description="Click is a Python package for creating beautiful command line interfaces in a composable way with as little code as necessary.",
            features=[
                "Arbitrary nesting of commands",
                "Automatic help page generation",
                "Supports lazy loading of subcommands at runtime",
            ],
            limitations=[],
        ),
        technology_stack=TechnologyStack(
            languages=[
                TechnologyItem(name="Python", category="language", detection_source="language_detection"),
            ],
            frameworks=[
                TechnologyItem(
                    name="Click",
                    category="framework",
                    detection_source="manifest",
                    is_confirmed=True,
                )
            ],
            libraries=[
                TechnologyItem(name="colorama", category="library", version=">=0.4.3", detection_source="manifest"),
            ],
            databases=[],
            tools=[
                TechnologyItem(name="pytest", category="tool", detection_source="configuration"),
            ],
            deployment_technologies=[
                TechnologyItem(name="GitHub Actions / CI", category="deployment", detection_source="configuration"),
            ],
        ),
        repository_structure=RepositoryStructureOverview(
            total_directories=5,
            total_files=42,
            important_directories=["src/click", "tests", "docs"],
        ),
        statistics=UnifiedStatistics(
            total_files=42,
            source_files=35,
            filtered_files=7,
            total_lines_of_code=8500,
            total_functions=150,
            total_classes=45,
            total_methods=300,
            total_imports=210,
            total_function_calls=520,
            total_internal_dependencies=78,
            total_external_dependencies=12,
        ),
        dependency_information=DependencyGraph(
            total_internal_dependencies=78,
            total_external_dependencies=12,
            nodes=[],
            internal_dependencies=[],
            external_dependencies=[],
        ),
        code_structure=CodeStructureSummary(
            parsed_files_count=35,
            supported_languages=["Python"],
            files=[],
        ),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(
                total_internal_dependencies=78,
                total_external_dependencies=12,
                nodes=[],
                internal_dependencies=[],
                external_dependencies=[],
            ),
            call_graph=CallGraph(
                total_call_sites=520,
                total_resolved_calls=480,
                nodes=[],
                edges=[],
            ),
            components=[
                ArchitecturalComponent(file_path="src/click/core.py", category="core", confidence="high", evidence=["Core engine"]),
                ArchitecturalComponent(file_path="src/click/types.py", category="type_system", confidence="high", evidence=["Param types"]),
            ],
            component_counts={"core": 1, "type_system": 1},
        ),
        entry_points=[
            EntryPointCandidate(
                file_path="src/click/__init__.py",
                entry_type="module_init",
                symbol_or_command="click",
                confidence="high",
                evidence=[],
            )
        ],
        important_files=[
            ImportantFileInfo(
                relative_path="src/click/core.py",
                category="entry_point",
                score=9.5,
                reason="Core command parsing engine",
                evidence="Imports and dispatches CLI commands",
                confidence="high",
            ),
            ImportantFileInfo(
                relative_path="pyproject.toml",
                category="manifest",
                score=8.5,
                reason="Build system configuration and dependencies",
                evidence="Defines dependencies and package metadata",
                confidence="high",
            ),
        ],
        source_evidence=[
            SourceEvidenceRecord(
                file_path="src/click/core.py",
                start_line=120,
                end_line=145,
                evidence_type="class_definition",
                symbol_or_statement="class Command(BaseCommand):",
                confidence="high",
                analysis_stage="code_parsing",
                status="statically_resolved",
            ),
            SourceEvidenceRecord(
                file_path="src/click/decorators.py",
                start_line=30,
                end_line=45,
                evidence_type="function_call",
                symbol_or_statement="def command(name=None, cls=None, **attrs):",
                confidence="high",
                analysis_stage="code_parsing",
                status="statically_resolved",
            ),
        ],
        warnings=[],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=datetime.now(timezone.utc),
            stages_completed=["repo_structure", "code_parsing", "architecture", "knowledge_consolidation"],
        ),
    )


@pytest.fixture
def sample_valid_llm_json_str() -> str:
    return json.dumps({
        "schema_version": "1.0",
        "identity": {
            "name": "pallets/click",
            "short_description": "Composable command line interface toolkit for Python.",
            "category": "CLI Framework",
            "project_type": "Library",
            "primary_purpose": "Enable Python developers to build command line tools with minimum boilerplate."
        },
        "problem_statement": {
            "problem_addressed": "Building ergonomic command-line tools in Python traditionally required verbose argparse boilerplate.",
            "why_it_matters": "Poor CLI design causes developer friction and inconsistent flag parsing.",
            "how_project_solves_it": "Provides a declarative decorator-based API with automatic type coercion and help generation."
        },
        "core_features": [
            {
                "name": "Decorator-driven Command Creation",
                "description": "Decorators to convert Python functions into CLI commands.",
                "user_benefit": "Write clean CLI tools without boilerplate.",
                "supporting_evidence": [
                    {
                        "file_path": "src/click/decorators.py",
                        "line_start": 30,
                        "line_end": 45,
                        "evidence_type": "code",
                        "confidence": "high",
                        "status": "confirmed"
                    }
                ],
                "confidence": "high"
            }
        ],
        "target_audience": {
            "intended_users": ["Python Developers", "DevOps Engineers"],
            "likely_needs": ["Easy CLI flags", "Subcommand routing", "ANSI color output"],
            "supporting_evidence": [
                {
                    "file_path": "README.rst",
                    "evidence_type": "readme",
                    "confidence": "high",
                    "status": "confirmed"
                }
            ],
            "is_established": True
        },
        "use_cases": [
            {
                "name": "Building Developer Utility CLI",
                "description": "Creating internal script runners and admin consoles.",
                "how_used": "Define functions with @click.command() and @click.option().",
                "supporting_evidence": [
                    {
                        "file_path": "src/click/decorators.py",
                        "evidence_type": "code",
                        "confidence": "high",
                        "status": "confirmed"
                    }
                ]
            }
        ],
        "technology_stack": [
            {
                "technology_name": "Python",
                "category": "Language",
                "role_in_project": "Core implementation language",
                "why_used": "Standard dynamic language for ecosystem utility scripts.",
                "supporting_evidence": [
                    {
                        "file_path": "pyproject.toml",
                        "evidence_type": "manifest",
                        "confidence": "high",
                        "status": "confirmed"
                    }
                ],
                "status": "confirmed"
            }
        ],
        "overall_explanation": {
            "concise_overview": "Click is Python's leading toolkit for writing composable command-line interfaces.",
            "detailed_explanation": "Click structures command parsing into Commands, Groups, Contexts, and Parameters.",
            "beginner_friendly": "Like LEGO blocks for command line interfaces.",
            "interesting_aspects": "Lazy subcommand loading avoids slow startup times.",
            "video_demonstration_highlights": [
                "Demonstrating @click.command decorator syntax",
                "Showing automatic --help generation",
                "Tracing context propagation through subcommands"
            ]
        }
    })


# --- 1. Evidence Builder Tests ---

def test_evidence_builder_structure(sample_knowledge):
    package = evidence_builder_service.build_evidence_package(sample_knowledge)
    assert "repository" in package
    assert "overview" in package
    assert "tech_stack" in package
    assert "statistics" in package
    assert "important_files" in package
    assert "entry_points" in package
    assert "architectural_components" in package
    assert "source_evidence" in package

    assert package["repository"]["name"] == "pallets/click"
    assert "Python" in package["tech_stack"]["languages"]
    assert len(package["source_evidence"]) >= 1


def test_evidence_builder_sanitizes_env_files(sample_knowledge):
    # Add a fake .env evidence record
    sample_knowledge.source_evidence.append(
        SourceEvidenceRecord(
            file_path=".env.production",
            start_line=1,
            evidence_type="configuration",
            symbol_or_statement="SECRET_KEY=12345",
            confidence="high",
            analysis_stage="repo_structure",
            status="observed",
        )
    )
    package = evidence_builder_service.build_evidence_package(sample_knowledge)
    for ev in package["source_evidence"]:
        assert ".env" not in ev["file_path"].lower()


# --- 2. Schema Validation Tests ---

def test_project_understanding_schema_valid(sample_valid_llm_json_str):
    data = json.loads(sample_valid_llm_json_str)
    understanding = ProjectUnderstanding.model_validate(data)
    assert understanding.identity.name == "pallets/click"
    assert understanding.identity.category == "CLI Framework"
    assert len(understanding.core_features) == 1
    assert understanding.core_features[0].supporting_evidence[0].file_path == "src/click/decorators.py"
    assert len(understanding.overall_explanation.video_demonstration_highlights) == 3


def test_project_understanding_schema_missing_fields():
    with pytest.raises(Exception):
        # Missing identity & problem_statement
        ProjectUnderstanding.model_validate({"schema_version": "1.0"})


# --- 3. Analyzer & LLM Generation Tests (Mocked) ---

@pytest.mark.anyio
async def test_analyze_project_success(sample_knowledge, sample_valid_llm_json_str):
    mock_llm_manager = MagicMock()
    mock_response = LLMResponse(
        text=f"```json\n{sample_valid_llm_json_str}\n```",
        provider="groq",
        model="openai/gpt-oss-120b",
        latency_ms=850.0,
        token_usage=TokenUsageRecord(
            prompt_tokens=1200,
            completion_tokens=600,
            total_tokens=1800,
            provider="groq",
            model="openai/gpt-oss-120b",
        ),
    )
    mock_llm_manager.generate = AsyncMock(return_value=mock_response)

    analyzer = ProjectUnderstandingAnalyzer(llm_manager=mock_llm_manager)
    result = await analyzer.analyze_project(job_id="test-job", knowledge=sample_knowledge)

    assert isinstance(result, ProjectUnderstanding)
    assert result.identity.name == "pallets/click"
    assert result.provider == "groq"
    assert result.model == "openai/gpt-oss-120b"
    assert result.latency_ms == 850.0
    assert result.token_usage.total_tokens == 1800
    mock_llm_manager.generate.assert_called_once()


@pytest.mark.anyio
async def test_analyze_project_json_repair_success(sample_knowledge, sample_valid_llm_json_str):
    mock_llm_manager = MagicMock()
    # First response has invalid JSON syntax
    broken_response = LLMResponse(
        text="Here is the json: { identity: broken_json... ",
        provider="groq",
        model="openai/gpt-oss-120b",
        latency_ms=400.0,
        token_usage=TokenUsageRecord(
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
            provider="groq",
            model="openai/gpt-oss-120b",
        ),
    )
    # Second response (repair) returns clean JSON
    repaired_response = LLMResponse(
        text=sample_valid_llm_json_str,
        provider="groq",
        model="openai/gpt-oss-120b",
        latency_ms=500.0,
        token_usage=TokenUsageRecord(
            prompt_tokens=800,
            completion_tokens=500,
            total_tokens=1300,
            provider="groq",
            model="openai/gpt-oss-120b",
        ),
    )
    mock_llm_manager.generate = AsyncMock(side_effect=[broken_response, repaired_response])

    analyzer = ProjectUnderstandingAnalyzer(llm_manager=mock_llm_manager)
    result = await analyzer.analyze_project(job_id="test-job", knowledge=sample_knowledge)

    assert isinstance(result, ProjectUnderstanding)
    assert result.identity.name == "pallets/click"
    assert mock_llm_manager.generate.call_count == 2


@pytest.mark.anyio
async def test_analyze_project_unrecoverable_json(sample_knowledge):
    mock_llm_manager = MagicMock()
    broken = LLMResponse(
        text="Not valid json at all",
        provider="groq",
        model="openai/gpt-oss-120b",
        latency_ms=300.0,
    )
    mock_llm_manager.generate = AsyncMock(side_effect=[broken, broken])

    analyzer = ProjectUnderstandingAnalyzer(llm_manager=mock_llm_manager)
    with pytest.raises(AIInvalidResponseError):
        await analyzer.analyze_project(job_id="test-job", knowledge=sample_knowledge)


def test_rule_based_fallback(sample_knowledge):
    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(sample_knowledge)

    assert isinstance(fallback, ProjectUnderstanding)
    assert fallback.identity.name == "pallets/click"
    assert len(fallback.core_features) >= 1
    assert len(fallback.technology_stack) >= 1
    assert fallback.provider == "fallback"


# --- 4. API Endpoints Tests ---

def test_api_project_understanding_404_job():
    resp = client.get("/api/v1/jobs/non-existent-job-id/project-understanding")
    assert resp.status_code == 404


def test_api_project_understanding_409_stages_incomplete():
    # Create job without completing ingestion or analysis
    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    resp = client.get(f"/api/v1/jobs/{job.job_id}/project-understanding")
    assert resp.status_code == 409


def test_api_project_understanding_404_not_yet_generated(sample_knowledge):
    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    # Mark first 3 stages complete
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    job.knowledge = sample_knowledge
    job_store.update_job(job)

    resp = client.get(f"/api/v1/jobs/{job.job_id}/project-understanding")
    assert resp.status_code == 404
    assert "not yet been generated" in resp.json()["detail"]


@patch.object(project_understanding_analyzer, "analyze_project")
def test_api_post_and_get_project_understanding(mock_analyze, sample_knowledge, sample_valid_llm_json_str):
    understanding_obj = ProjectUnderstanding.model_validate(json.loads(sample_valid_llm_json_str))
    understanding_obj.provider = "groq"
    understanding_obj.model = "openai/gpt-oss-120b"
    understanding_obj.latency_ms = 912.0
    mock_analyze.return_value = understanding_obj

    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    job.knowledge = sample_knowledge
    job_store.update_job(job)

    # 1. POST to generate
    post_resp = client.post(f"/api/v1/jobs/{job.job_id}/project-understanding")
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["identity"]["name"] == "pallets/click"
    assert data["provider"] == "groq"
    assert data["model"] == "openai/gpt-oss-120b"

    # Verify stage update
    updated_job = job_store.get_internal_job(job.job_id)
    assert updated_job.stages[3].status == StatusEnum.COMPLETED
    assert updated_job.current_stage == PIPELINE_STAGES[4]
    assert updated_job.progress_percentage == 44

    # 2. GET to retrieve cached
    get_resp = client.get(f"/api/v1/jobs/{job.job_id}/project-understanding")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["identity"]["name"] == "pallets/click"


def test_api_simulate_step_ai_summary(sample_knowledge):
    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job.stages[0].status = StatusEnum.COMPLETED
    job.stages[1].status = StatusEnum.COMPLETED
    job.stages[2].status = StatusEnum.COMPLETED
    job.stages[3].status = StatusEnum.IN_PROGRESS
    job.knowledge = sample_knowledge
    job_store.update_job(job)

    resp = client.post(f"/api/v1/jobs/{job.job_id}/simulate-step")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["project_understanding"] is not None
    assert res_data["project_understanding"]["identity"]["name"] == "pallets/click"
