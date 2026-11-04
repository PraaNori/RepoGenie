import asyncio
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
    CallGraphEdge,
    CallGraphNode,
    ClassInfo,
    CodeStructureSummary,
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    DirectoryTreeNode,
    EntryPointCandidate,
    FunctionInfo,
    ImportantFileInfo,
    KnowledgeAnalysisMetadata,
    MethodInfo,
    ParsedFile,
    ProjectOverviewInfo,
    RelationshipEvidence,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    SourceLocation,
    StatusEnum,
    TechnologyItem,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.code_understanding import (
    CodeEvidenceBuilder,
    CodeEvidenceValidator,
    CodeUnderstandingAnalyzer,
    ComponentSelector,
    ExtractedCodeSnippet,
    RepositoryCodeUnderstanding,
    SnippetExtractor,
    code_evidence_builder,
    code_evidence_validator,
    code_understanding_analyzer,
    component_selector,
    snippet_extractor,
)
from app.services.ai.exceptions import AIInvalidResponseError
from app.services.ai.project_understanding import ProjectUnderstanding
from app.services.ai.schemas import LLMResponse, TokenUsageRecord
from app.services.storage.job_store import PIPELINE_STAGES, job_store

client = TestClient(app)


@pytest.fixture
def sample_knowledge() -> RepositoryKnowledge:
    parsed_core = ParsedFile(
        file_path="src/click/core.py",
        language="python",
        status="success",
        total_lines=500,
        functions=[
            FunctionInfo(
                name="invoke",
                file_path="src/click/core.py",
                location=SourceLocation(
                    file_path="src/click/core.py",
                    start_line=120,
                    end_line=135,
                    start_column=0,
                    end_column=20,
                ),
                parameters=["self", "ctx"],
                snippet='def invoke(self, ctx):\n    """Executes callback command within context."""\n    return ctx.invoke(self.callback, **ctx.params)',
            ),
            FunctionInfo(
                name="make_context",
                file_path="src/click/core.py",
                location=SourceLocation(
                    file_path="src/click/core.py",
                    start_line=200,
                    end_line=225,
                    start_column=0,
                    end_column=20,
                ),
                parameters=["info_name", "args", "parent"],
                snippet="def make_context(info_name, args, parent=None):\n    return Context(self, info_name=info_name, parent=parent)",
            ),
        ],
        classes=[
            ClassInfo(
                name="Command",
                file_path="src/click/core.py",
                location=SourceLocation(
                    file_path="src/click/core.py",
                    start_line=100,
                    end_line=180,
                    start_column=0,
                    end_column=20,
                ),
                base_classes=["BaseCommand"],
                methods=["invoke", "parse_args"],
                snippet='class Command(BaseCommand):\n    """Represents a CLI command with options."""\n    pass',
            )
        ],
        methods=[],
        imports=[],
        function_calls=[],
    )

    parsed_types = ParsedFile(
        file_path="src/click/types.py",
        language="python",
        status="success",
        total_lines=350,
        functions=[
            FunctionInfo(
                name="convert",
                file_path="src/click/types.py",
                location=SourceLocation(
                    file_path="src/click/types.py",
                    start_line=45,
                    end_line=60,
                    start_column=0,
                    end_column=20,
                ),
                parameters=["self", "value", "param", "ctx"],
                snippet="def convert(self, value, param, ctx):\n    return int(value)",
            )
        ],
        classes=[
            ClassInfo(
                name="ParamType",
                file_path="src/click/types.py",
                location=SourceLocation(
                    file_path="src/click/types.py",
                    start_line=30,
                    end_line=90,
                    start_column=0,
                    end_column=20,
                ),
                methods=["convert"],
                snippet="class ParamType:\n    name = 'param'\n    pass",
            )
        ],
        methods=[],
        imports=[],
        function_calls=[],
    )

    parsed_parser = ParsedFile(
        file_path="src/click/parser.py",
        language="python",
        status="success",
        total_lines=280,
        functions=[
            FunctionInfo(
                name="_split_opt",
                file_path="src/click/parser.py",
                location=SourceLocation(
                    file_path="src/click/parser.py",
                    start_line=15,
                    end_line=30,
                    start_column=0,
                    end_column=20,
                ),
                parameters=["opt"],
                snippet="def _split_opt(opt):\n    return opt.split('=', 1)",
            ),
            FunctionInfo(
                name="split_arg_string",
                file_path="src/click/parser.py",
                location=SourceLocation(
                    file_path="src/click/parser.py",
                    start_line=50,
                    end_line=75,
                    start_column=0,
                    end_column=20,
                ),
                parameters=["string"],
                snippet="def split_arg_string(string):\n    return string.split()",
            ),
        ],
        classes=[],
        methods=[],
        imports=[],
        function_calls=[],
    )

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
            description="Click is a Python package for creating beautiful command line interfaces in a composable way.",
            features=["Arbitrary nesting of commands", "Automatic help page generation"],
            limitations=[],
        ),
        technology_stack=TechnologyStack(
            languages=[TechnologyItem(name="Python", category="language", detection_source="language_detection")],
            frameworks=[TechnologyItem(name="Click", category="framework", detection_source="manifest")],
            libraries=[],
            databases=[],
            tools=[],
            deployment_technologies=[],
        ),
        repository_structure=RepositoryStructureOverview(
            total_directories=4,
            total_files=42,
            important_directories=["src/click"],
            directory_tree=DirectoryTreeNode(
                name="click",
                path="",
                type="directory",
                children=[
                    DirectoryTreeNode(
                        name="src",
                        path="src",
                        type="directory",
                        children=[
                            DirectoryTreeNode(
                                name="click",
                                path="src/click",
                                type="directory",
                                children=[
                                    DirectoryTreeNode(name="__init__.py", path="src/click/__init__.py", type="file"),
                                    DirectoryTreeNode(name="core.py", path="src/click/core.py", type="file"),
                                    DirectoryTreeNode(name="types.py", path="src/click/types.py", type="file"),
                                    DirectoryTreeNode(name="parser.py", path="src/click/parser.py", type="file"),
                                ],
                            )
                        ],
                    ),
                    DirectoryTreeNode(name="README.rst", path="README.rst", type="file"),
                    DirectoryTreeNode(name="pyproject.toml", path="pyproject.toml", type="file"),
                ],
            ),
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
            nodes=[
                DependencyNode(id="src/click/core.py", label="core", node_type="internal_file"),
                DependencyNode(id="src/click/types.py", label="types", node_type="internal_file"),
                DependencyNode(id="src/click/parser.py", label="parser", node_type="internal_file"),
            ],
            edges=[
                DependencyEdge(
                    source="src/click/core.py",
                    target="src/click/types.py",
                    relationship_type="imports",
                    is_internal=True,
                    resolution_status="resolved_internal",
                    evidence=RelationshipEvidence(
                        evidence_type="import_statement",
                        statement="from .types import ParamType",
                        file_path="src/click/core.py",
                        line_number=14,
                        confidence="high",
                    ),
                ),
                DependencyEdge(
                    source="src/click/core.py",
                    target="src/click/parser.py",
                    relationship_type="imports",
                    is_internal=True,
                    resolution_status="resolved_internal",
                    evidence=RelationshipEvidence(
                        evidence_type="import_statement",
                        statement="from .parser import split_arg_string",
                        file_path="src/click/core.py",
                        line_number=18,
                        confidence="high",
                    ),
                ),
            ],
            total_internal_dependencies=2,
            total_external_dependencies=0,
        ),
        code_structure=CodeStructureSummary(
            parsed_files_count=3,
            supported_languages=["Python"],
            files=[parsed_core, parsed_types, parsed_parser],
        ),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(),
            call_graph=CallGraph(
                nodes=[
                    CallGraphNode(id="src/click/core.py:Command.invoke", name="invoke", file_path="src/click/core.py"),
                    CallGraphNode(id="src/click/types.py:ParamType.convert", name="convert", file_path="src/click/types.py"),
                ],
                edges=[
                    CallGraphEdge(
                        caller="src/click/core.py:Command.invoke",
                        callee="src/click/types.py:ParamType.convert",
                        call_name="convert",
                        resolution_status="resolved_internal",
                        evidence=RelationshipEvidence(
                            evidence_type="function_call",
                            statement="type.convert(val, self, ctx)",
                            file_path="src/click/core.py",
                            line_number=130,
                            confidence="high",
                        ),
                    )
                ],
                total_resolved_calls=1,
            ),
            components=[
                ArchitecturalComponent(file_path="src/click/core.py", category="core", confidence="high"),
                ArchitecturalComponent(file_path="src/click/types.py", category="parser", confidence="high"),
                ArchitecturalComponent(file_path="src/click/parser.py", category="service", confidence="high"),
            ],
            component_counts={"core": 1, "parser": 1, "service": 1},
        ),
        entry_points=[
            EntryPointCandidate(
                file_path="src/click/core.py",
                entry_type="application_entry_file",
                symbol_or_command="Command",
                confidence="high",
            )
        ],
        important_files=[
            ImportantFileInfo(
                relative_path="src/click/core.py",
                category="core",
                score=9.5,
                reason="Core command dispatch and parsing engine",
                evidence="Primary class definitions",
                confidence="high",
            ),
            ImportantFileInfo(
                relative_path="src/click/types.py",
                category="parser",
                score=8.0,
                reason="Type validation and conversion system",
                evidence="ParamType class definition",
                confidence="high",
            ),
        ],
        source_evidence=[],
        warnings=[],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=datetime.now(timezone.utc),
            stages_completed=["repo_structure", "code_parsing", "architecture", "knowledge_consolidation"],
        ),
    )


@pytest.fixture
def sample_valid_code_understanding_json() -> str:
    return json.dumps({
        "schema_version": "1.0",
        "repository_name": "pallets/click",
        "architecture_overview": "Click organizes CLI handling into modular command definitions, type conversions, and token parsing.",
        "components": [
            {
                "component_id": "src/click/core.py",
                "name": "Command Execution Engine",
                "file_path": "src/click/core.py",
                "category": "core",
                "importance_score": 9.5,
                "primary_responsibility": "Defines base CLI command abstractions, parses command-line invocations, and handles callbacks.",
                "why_important": "Acts as the central execution coordinator for all Click commands and CLI dispatch.",
                "inputs_and_outputs": "Accepts user command line tokens and dispatches to registered python callbacks.",
                "key_classes_and_functions": ["Command", "invoke"],
                "code_explanations": [
                    {
                        "name": "Command.invoke",
                        "symbol_type": "method",
                        "file_path": "src/click/core.py",
                        "line_start": 120,
                        "line_end": 135,
                        "signature": "def invoke(self, ctx)",
                        "summary": "Executes callback associated with command inside Context.",
                        "logic_explanation": "Checks if callback is set, formats parameter dictionary, and passes context to handler.",
                        "parameters_and_returns": "Parameters: self (Command), ctx (Context). Returns: callback result.",
                        "internal_calls": ["ctx.invoke"],
                        "supporting_evidence": [
                            {
                                "file_path": "src/click/core.py",
                                "line_start": 120,
                                "line_end": 135,
                                "evidence_type": "code",
                                "confidence": "high",
                                "status": "confirmed"
                            }
                        ],
                        "confidence": "high"
                    }
                ],
                "dependencies": ["src/click/types.py"],
                "dependents": [],
                "supporting_evidence": [
                    {
                        "file_path": "src/click/core.py",
                        "line_start": 1,
                        "line_end": 500,
                        "evidence_type": "code",
                        "confidence": "high",
                        "status": "confirmed"
                    }
                ],
                "confidence": "high"
            }
        ],
        "cross_component_interactions": [
            {
                "source_component": "src/click/core.py",
                "target_component": "src/click/types.py",
                "interaction_type": "calls",
                "description": "Command invokes ParamType.convert to validate option parameters.",
                "is_confirmed": True,
                "supporting_evidence": [
                    {
                        "file_path": "src/click/core.py",
                        "line_start": 130,
                        "line_end": 130,
                        "evidence_type": "code",
                        "confidence": "high",
                        "status": "confirmed"
                    }
                ],
                "confidence": "high"
            }
        ]
    })


# ---------------------------------------------------------------------------
# 1. Component Selector Tests
# ---------------------------------------------------------------------------


def test_component_selector_multi_criteria_ranking(sample_knowledge):
    selector = ComponentSelector()
    selected = selector.select_components(sample_knowledge, min_components=2, max_components=5)

    assert len(selected) >= 2
    # core.py has high importance score, entry point, and call edges, so it should rank first
    assert selected[0].file_path == "src/click/core.py"
    assert selected[0].category == "core"
    assert selected[0].score >= 9.0
    # Key symbols extracted
    assert "Command" in selected[0].key_symbols or "invoke" in selected[0].key_symbols


def test_component_selector_excludes_root_manifests_and_hidden(sample_knowledge):
    selector = ComponentSelector()
    selected = selector.select_components(sample_knowledge)
    paths = [s.file_path for s in selected]

    assert "pyproject.toml" not in paths
    assert "README.rst" not in paths
    assert not any(p.startswith(".") for p in paths)


# ---------------------------------------------------------------------------
# 2. Snippet Extractor Tests
# ---------------------------------------------------------------------------


def test_snippet_extractor_preserves_line_numbers(sample_knowledge):
    extractor = SnippetExtractor()
    pf = sample_knowledge.code_structure.files[0]  # src/click/core.py
    snippets = extractor.extract_snippets_for_component(pf, key_symbols=["invoke"])

    assert len(snippets) >= 1
    invoke_snip = snippets[0]
    assert invoke_snip.name == "invoke"
    assert invoke_snip.line_start == 120
    assert invoke_snip.line_end == 135
    assert invoke_snip.is_complete is True
    assert "L120: def invoke(self, ctx):" in invoke_snip.formatted_code


def test_snippet_extractor_bounds_and_exclusions():
    extractor = SnippetExtractor()
    # Mock a function with 100 lines (exceeding MAX_SYMBOL_LINES=35)
    long_func = FunctionInfo(
        name="huge_dispatch",
        file_path="src/big.py",
        location=SourceLocation(file_path="src/big.py", start_line=1, end_line=100, start_column=0, end_column=10),
        parameters=["a", "b"],
        snippet="def huge_dispatch(a, b):\n" + "\n".join([f"    step_{i}()" for i in range(98)]),
    )
    pf = ParsedFile(file_path="src/big.py", language="python", status="success", total_lines=150, functions=[long_func])

    snippets = extractor.extract_snippets_for_component(pf, key_symbols=["huge_dispatch"])
    assert len(snippets) == 1
    snip = snippets[0]
    # Oversized function should have signature retained but is_complete=False with explicit reason
    assert snip.is_complete is False
    assert snip.exclusion_reason is not None
    assert "omitted to preserve complete symbol boundaries" in snip.exclusion_reason
    assert "L1: def huge_dispatch(a, b):" in snip.formatted_code


# ---------------------------------------------------------------------------
# 3. Evidence Builder Tests
# ---------------------------------------------------------------------------


def test_code_evidence_builder_assembly(sample_knowledge):
    builder = CodeEvidenceBuilder()
    pkg = builder.build_evidence_package(sample_knowledge)

    assert "repository" in pkg
    assert pkg["repository"]["name"] == "pallets/click"
    assert "components" in pkg
    assert len(pkg["components"]) >= 2
    assert "confirmed_static_interactions" in pkg
    # Verify confirmed import from core.py to types.py is present
    interactions = pkg["confirmed_static_interactions"]
    assert any(i["source"] == "src/click/core.py" and i["target"] == "src/click/types.py" for i in interactions)


def test_code_evidence_builder_token_estimation():
    builder = CodeEvidenceBuilder()
    sys_prompt = "A" * 400  # ~100 tokens
    usr_prompt = "B" * 1200  # ~300 tokens
    total_est = builder.estimate_total_tokens(sys_prompt, usr_prompt, max_output_tokens=2048)
    # (400 + 1200) // 4 = 400 input tokens + 2048 = 2448
    assert total_est == 2448


# ---------------------------------------------------------------------------
# 4. Code Evidence Validator Tests
# ---------------------------------------------------------------------------


def test_code_validator_demotes_unsubstantiated_interactions(sample_knowledge, sample_valid_code_understanding_json):
    validator = CodeEvidenceValidator()
    data = json.loads(sample_valid_code_understanding_json)
    # Add an unconfirmed interaction claimed as confirmed
    data["cross_component_interactions"].append({
        "source_component": "src/click/parser.py",
        "target_component": "src/click/nonexistent_database.py",
        "interaction_type": "calls",
        "description": "Parser calls database directly.",
        "is_confirmed": True,  # FALSE claim!
        "supporting_evidence": [
            {
                "file_path": "src/click/parser.py",
                "line_start": 20,
                "line_end": 20,
                "evidence_type": "code",
            }
        ]
    })
    understanding = RepositoryCodeUnderstanding.model_validate(data)
    validated = validator.validate_code_understanding(understanding, sample_knowledge)

    # Second interaction should be demoted to inferred
    inter2 = validated.cross_component_interactions[1]
    assert inter2.is_confirmed is False
    assert inter2.confidence == "medium"
    assert any("demoted from confirmed to inferred" in w for w in validated.validation_warnings)


def test_code_validator_detects_nonexistent_symbol(sample_knowledge, sample_valid_code_understanding_json):
    validator = CodeEvidenceValidator()
    data = json.loads(sample_valid_code_understanding_json)
    # Inject fabricated symbol name
    data["components"][0]["code_explanations"][0]["name"] = "fabricated_crypto_mining_loop"

    understanding = RepositoryCodeUnderstanding.model_validate(data)
    validated = validator.validate_code_understanding(understanding, sample_knowledge)

    expl = validated.components[0].code_explanations[0]
    assert expl.confidence == "low"
    assert any("fabricated_crypto_mining_loop" in w for w in validated.validation_warnings)


# ---------------------------------------------------------------------------
# 5. Analyzer & Fallback Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_code_understanding_analyzer_success(sample_knowledge, sample_valid_code_understanding_json):
    mock_llm_manager = MagicMock()
    mock_response = LLMResponse(
        text=sample_valid_code_understanding_json,
        provider="groq",
        model="openai/gpt-oss-120b",
        finish_reason="stop",
        latency_ms=1250.0,
        token_usage=TokenUsageRecord(
            prompt_tokens=1800,
            completion_tokens=650,
            total_tokens=2450,
            provider="groq",
            model="openai/gpt-oss-120b",
        ),
    )
    mock_llm_manager.generate = AsyncMock(return_value=mock_response)

    analyzer = CodeUnderstandingAnalyzer(llm_manager=mock_llm_manager)
    result = await analyzer.analyze_codebase(
        job_id="test-job-cu-1",
        knowledge=sample_knowledge,
        provider_name="groq",
    )

    assert result.repository_name == "pallets/click"
    assert result.provider == "groq"
    assert result.is_fallback is False
    assert len(result.components) == 1
    assert result.components[0].name == "Command Execution Engine"
    assert len(result.cross_component_interactions) == 1


@pytest.mark.anyio
async def test_code_understanding_analyzer_json_repair(sample_knowledge, sample_valid_code_understanding_json):
    mock_llm_manager = MagicMock()
    # First response truncated / invalid
    invalid_response = LLMResponse(
        text="Here is the component understanding: { invalid syntax: missing quotes and brackets ",
        provider="gemini",
        model="gemini-3.8-flash",
    )
    # Repaired response valid
    repaired_response = LLMResponse(
        text=sample_valid_code_understanding_json,
        provider="gemini",
        model="gemini-3.8-flash",
        latency_ms=800.0,
        token_usage=TokenUsageRecord(
            prompt_tokens=400,
            completion_tokens=300,
            total_tokens=700,
            provider="gemini",
            model="gemini-3.8-flash",
        ),
    )
    mock_llm_manager.generate = AsyncMock(side_effect=[invalid_response, repaired_response])

    analyzer = CodeUnderstandingAnalyzer(llm_manager=mock_llm_manager)
    result = await analyzer.analyze_codebase(
        job_id="test-job-cu-2",
        knowledge=sample_knowledge,
    )

    assert result.repository_name == "pallets/click"
    assert len(result.components) >= 1
    assert mock_llm_manager.generate.call_count == 2


def test_code_understanding_deterministic_fallback(sample_knowledge):
    analyzer = CodeUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(sample_knowledge)

    assert fallback.is_fallback is True
    assert fallback.provider == "rule_based_fallback"
    assert fallback.model == "deterministic-rule-based"
    assert fallback.token_usage is None
    assert fallback.latency_ms == 0.0
    assert len(fallback.components) >= 2
    # Verify deterministic explanation flags
    comp1 = fallback.components[0]
    assert comp1.is_deterministic is True
    if comp1.code_explanations:
        expl = comp1.code_explanations[0]
        assert expl.is_deterministic is True
        assert "Deterministic Structural" in expl.summary
        assert "Internal branch execution not evaluated without AI provider" in expl.logic_explanation


# ---------------------------------------------------------------------------
# 6. API Endpoints Tests
# ---------------------------------------------------------------------------


def test_api_code_understanding_404_job():
    resp = client.get("/api/v1/jobs/non-existent-cu-job/code-understanding")
    assert resp.status_code == 404


def test_api_code_understanding_409_stages_incomplete(sample_knowledge):
    job = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    # Stage 0, 1 not completed
    resp = client.post(f"/api/v1/jobs/{job.job_id}/code-understanding")
    assert resp.status_code == 409
    assert "Repository ingestion must be completed first" in resp.json()["detail"]


def test_api_code_understanding_404_not_yet_generated(sample_knowledge):
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

    resp = client.get(f"/api/v1/jobs/{job.job_id}/code-understanding")
    assert resp.status_code == 404
    assert "has not yet been generated" in resp.json()["detail"]


@patch.object(code_understanding_analyzer, "analyze_codebase")
def test_api_post_and_get_code_understanding(mock_analyze, sample_knowledge, sample_valid_code_understanding_json):
    cu_obj = RepositoryCodeUnderstanding.model_validate(json.loads(sample_valid_code_understanding_json))
    cu_obj.provider = "groq"
    cu_obj.model = "openai/gpt-oss-120b"
    mock_analyze.return_value = cu_obj

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
    post_resp = client.post(f"/api/v1/jobs/{job.job_id}/code-understanding")
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["repository_name"] == "pallets/click"
    assert len(data["components"]) == 1

    # Verify JobResponse flag without embedding entire duplicate object
    job_resp = client.get(f"/api/v1/jobs/{job.job_id}")
    assert job_resp.status_code == 200
    assert job_resp.json()["has_code_understanding"] is True

    # 2. GET to retrieve cached
    get_resp = client.get(f"/api/v1/jobs/{job.job_id}/code-understanding")
    assert get_resp.status_code == 200
    assert get_resp.json()["repository_name"] == "pallets/click"


@pytest.mark.anyio
async def test_concurrent_code_understanding_requests_per_job_serialization(sample_knowledge, sample_valid_code_understanding_json):
    from app.api.routes.jobs import generate_job_code_understanding

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

    cu_obj = RepositoryCodeUnderstanding.model_validate(json.loads(sample_valid_code_understanding_json))
    cu_obj.provider = "groq"
    cu_obj.model = "openai/gpt-oss-120b"

    execution_count = 0

    async def mock_analyze_slow(*args, **kwargs):
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)
        return cu_obj

    with patch.object(code_understanding_analyzer, "analyze_codebase", side_effect=mock_analyze_slow):
        task1 = generate_job_code_understanding(job_id=job.job_id, provider=None, refresh=False)
        task2 = generate_job_code_understanding(job_id=job.job_id, provider=None, refresh=False)
        res1, res2 = await asyncio.gather(task1, task2)

        assert res1.repository_name == "pallets/click"
        assert res2.repository_name == "pallets/click"
        # Analyzer called exactly once due to atomic per-job locking
        assert execution_count == 1
