"""
Milestone 4, Phase 2 — AI-Powered Educational Script Generation Tests.

Covers:
1. Evidence building from all four understanding outputs.
2. Missing optional understanding outputs.
3. Evidence prioritization and prompt-size limits.
4. Secret redaction and sensitive file exclusion.
5. Valid structured LLM response handling and reference hydration.
6. Malformed JSON and one-shot repair behavior.
7. Invalid section durations and ordering handling.
8. Unsupported claims, fabricated evidence, and spoken path/signature warnings.
9. Confirmed, inferred, and uncertain claims.
10. Runtime execution claims being rejected.
11. Duration validation and optional controlled duration revision.
12. Token usage and provider metadata tracking.
13. LLM provider failure handling (no fabricated fallback script).
14. Deterministic behavior of evidence selection and narrative profile adaptation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock

import pytest

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
    ParsedFile,
    ProjectOverviewInfo,
    RelationshipEvidence,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    SourceEvidenceRecord,
    StatusEnum,
    TechnologyItem,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.code_understanding.schemas import (
    CodeExplanationItem,
    ComponentInteractionItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
from app.services.ai.exceptions import (
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIProviderUnavailableError,
    AITimeoutError,
)
from app.services.ai.llm_manager import LLMManager
from app.services.ai.project_understanding.schemas import (
    ApplicationExplanation,
    CoreFeatureItem,
    EvidenceReference,
    ProblemStatement,
    ProjectIdentity,
    ProjectUnderstanding,
    TargetAudience,
    TechnologyExplanationItem,
    UseCaseItem,
)
from app.services.ai.schemas import LLMResponse, TokenUsageRecord
from app.services.ai.script_generation import (
    EducationalScript,
    EducationalScriptAnalyzer,
    GroundedClaim,
    GroundingStatus,
    ScriptEvidenceBuilder,
    ScriptGenerationError,
    ScriptValidator,
    SectionPurpose,
    UnderstandingSource,
    build_script_user_prompt,
)
from app.services.ai.workflow_understanding.schemas import (
    ApplicationWorkflow,
    CallSiteEvidence,
    DataFlow,
    DataTransformation,
    RepositoryWorkflowUnderstanding,
    StructuralCallChain,
    WorkflowComponentReference,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# Test Fixtures & Builders
# ---------------------------------------------------------------------------


def _words(count: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{i}" for i in range(1, count + 1))


def make_repository_knowledge() -> RepositoryKnowledge:
    tree = DirectoryTreeNode(
        name="click",
        path="",
        type="directory",
        children=[
            DirectoryTreeNode(name="README.md", path="README.md", type="file"),
            DirectoryTreeNode(name="pyproject.toml", path="pyproject.toml", type="file"),
            DirectoryTreeNode(name=".env", path=".env", type="file"),
            DirectoryTreeNode(
                name="src",
                path="src",
                type="directory",
                children=[
                    DirectoryTreeNode(name="core.py", path="src/click/core.py", type="file"),
                    DirectoryTreeNode(name="decorators.py", path="src/click/decorators.py", type="file"),
                    DirectoryTreeNode(name="types.py", path="src/click/types.py", type="file"),
                    DirectoryTreeNode(name="parser.py", path="src/click/parser.py", type="file"),
                ],
            ),
        ],
    )
    return RepositoryKnowledge(
        repository=RepositoryMetadataInfo(
            name="click",
            owner="pallets",
            repository_url="https://github.com/pallets/click",
            description="Python composable command line interface toolkit",
            file_count=6,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="Click is a Python package for creating command line interfaces in a composable way.",
            features=[
                "Arbitrary nesting of commands",
                "Automatic help page generation",
                "Lazy loading of subcommands at runtime",
            ],
        ),
        technology_stack=TechnologyStack(
            languages=[
                TechnologyItem(
                    name="Python",
                    category="language",
                    version=">=3.8",
                    confidence="high",
                    detection_source="manifest",
                    is_confirmed=True,
                )
            ],
            frameworks=[
                TechnologyItem(
                    name="Click",
                    category="framework",
                    confidence="high",
                    detection_source="code_import",
                    is_confirmed=True,
                )
            ],
            tools=[
                TechnologyItem(
                    name="Pytest",
                    category="tool",
                    confidence="high",
                    detection_source="manifest",
                    is_confirmed=True,
                )
            ],
        ),
        repository_structure=RepositoryStructureOverview(
            total_directories=2,
            total_files=6,
            important_directories=["src/click"],
            directory_tree=tree,
        ),
        statistics=UnifiedStatistics(
            total_files=6,
            source_files=4,
            total_lines_of_code=1200,
            total_functions=25,
            total_classes=8,
            total_methods=40,
        ),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(
            parsed_files_count=4,
            supported_languages=["Python"],
            files=[
                ParsedFile(file_path="src/click/core.py", language="Python", status="success", total_lines=500),
                ParsedFile(file_path="src/click/decorators.py", language="Python", status="success", total_lines=250),
                ParsedFile(file_path="src/click/types.py", language="Python", status="success", total_lines=250),
                ParsedFile(file_path="src/click/parser.py", language="Python", status="success", total_lines=200),
                ParsedFile(file_path="README.md", language="Markdown", status="success", total_lines=100),
                ParsedFile(file_path="pyproject.toml", language="TOML", status="success", total_lines=60),
            ],
        ),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(),
            call_graph=CallGraph(),
            components=[
                ArchitecturalComponent(
                    file_path="src/click/core.py",
                    category="core",
                    confidence="high",
                    evidence=["Defines BaseCommand, Command, Group, and Context"],
                ),
                ArchitecturalComponent(
                    file_path="src/click/decorators.py",
                    category="entry_point",
                    confidence="high",
                    evidence=["Provides @command and @option decorators"],
                ),
            ],
            component_counts={"core": 2, "entry_point": 1, "utility": 1},
        ),
        entry_points=[
            EntryPointCandidate(
                file_path="src/click/core.py",
                entry_type="application_entry_file",
                symbol_or_command="BaseCommand.main",
                confidence="high",
                evidence=[
                    RelationshipEvidence(
                        evidence_type="function_call",
                        statement="def main(",
                        file_path="src/click/core.py",
                        line_number=50,
                        confidence="high",
                    )
                ],
            )
        ],
        important_files=[
            ImportantFileInfo(
                relative_path="src/click/core.py",
                category="service",
                score=0.95,
                reason="Central command execution engine",
                evidence="Defines Command and Context",
            ),
            ImportantFileInfo(
                relative_path="src/click/decorators.py",
                category="entry_point",
                score=0.88,
                reason="Decorator API for defining CLI commands",
                evidence="Defines command() and option()",
            ),
        ],
        source_evidence=[
            SourceEvidenceRecord(
                file_path="pyproject.toml",
                start_line=1,
                end_line=20,
                evidence_type="manifest_dependency",
                symbol_or_statement="Language: Python >=3.8, Tool: Pytest",
                confidence="high",
                analysis_stage="repo_structure",
            ),
            SourceEvidenceRecord(
                file_path="src/click/core.py",
                start_line=10,
                end_line=50,
                evidence_type="class_inheritance",
                symbol_or_statement="Framework: Click Command(BaseCommand)",
                confidence="high",
                analysis_stage="architecture_analysis",
            ),
        ],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=datetime.now(timezone.utc),
            stages_completed=["repo_structure", "code_parsing", "architecture_analysis"],
        ),
    )


def make_project_understanding() -> ProjectUnderstanding:
    readme_ev = EvidenceReference(
        file_path="README.md",
        line_start=1,
        line_end=30,
        evidence_type="readme",
        confidence="high",
        status="confirmed",
        detail="Project overview in README",
        is_valid=True,
        path_verified=True,
        line_range_verified=True,
    )
    core_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=40,
        line_end=120,
        evidence_type="code",
        confidence="high",
        status="confirmed",
        detail="Command class implementation",
        is_valid=True,
        path_verified=True,
        line_range_verified=True,
    )
    return ProjectUnderstanding(
        identity=ProjectIdentity(
            name="Click",
            short_description="A composable Python CLI toolkit using decorators.",
            category="CLI Framework",
            project_type="cli_tool",
            primary_purpose="Turn Python functions into composable command-line interfaces with minimal boilerplate.",
        ),
        problem_statement=ProblemStatement(
            problem_addressed="Building nested command-line tools with manual argument parsing is repetitive and error-prone.",
            why_it_matters="Developers need predictable help generation, type conversion, and composable subcommands.",
            how_project_solves_it="Decorators attach parameter metadata to functions while Context and Command orchestrate parsing and invocation.",
        ),
        core_features=[
            CoreFeatureItem(
                name="Decorator-Based Command Definition",
                description="Functions become CLI commands via @click.command and @click.option.",
                user_benefit="Eliminates manual parser wiring.",
                supporting_evidence=[core_ev],
                confidence="high",
            ),
            CoreFeatureItem(
                name="Composable Command Groups",
                description="Groups nest arbitrary subcommands with shared execution context.",
                user_benefit="Supports modular multi-command CLI applications.",
                supporting_evidence=[readme_ev],
                confidence="high",
            ),
        ],
        target_audience=TargetAudience(
            intended_users=["Python Developers", "CLI Tool Authors"],
            likely_needs=["Fast CLI scaffolding", "Type-safe option parsing"],
            supporting_evidence=[readme_ev],
            is_established=True,
        ),
        use_cases=[
            UseCaseItem(
                name="Building Developer CLI Tools",
                description="Create multi-command developer utilities.",
                how_used="Decorate entry functions and invoke the command group.",
                supporting_evidence=[readme_ev],
            )
        ],
        technology_stack=[
            TechnologyExplanationItem(
                technology_name="Python",
                category="language",
                role_in_project="Core implementation language",
                why_used="Provides dynamic decorators and introspection for CLI binding.",
                supporting_evidence=[core_ev],
                status="confirmed",
            )
        ],
        overall_explanation=ApplicationExplanation(
            concise_overview="Click builds composable CLIs in Python.",
            detailed_explanation="Click combines decorators, option parsers, and execution contexts.",
            beginner_friendly="Add decorators to a Python function to turn it into a command-line tool.",
            interesting_aspects="Clean separation between parsing, type conversion, and invocation.",
            video_demonstration_highlights=["Decorator registration", "Command invocation workflow"],
        ),
        provider="groq",
        model="openai/gpt-oss-120b",
    )


def make_code_understanding() -> RepositoryCodeUnderstanding:
    core_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=45,
        line_end=150,
        evidence_type="code",
        confidence="high",
        status="confirmed",
        is_valid=True,
        path_verified=True,
        line_range_verified=True,
    )
    dec_ev = EvidenceReference(
        file_path="src/click/decorators.py",
        line_start=15,
        line_end=90,
        evidence_type="code",
        confidence="high",
        status="confirmed",
        is_valid=True,
        path_verified=True,
        line_range_verified=True,
    )
    return RepositoryCodeUnderstanding(
        repository_name="pallets/click",
        architecture_overview="Layered CLI architecture separating decorator registration, option parsing, type conversion, and command invocation.",
        components=[
            ComponentUnderstandingItem(
                component_id="src/click/core.py",
                name="Command Execution Engine",
                file_path="src/click/core.py",
                category="core",
                importance_score=0.96,
                primary_responsibility="Manages command lifecycle, context creation, parameter conversion, and callback invocation.",
                why_important="Central coordinator for every CLI execution.",
                inputs_and_outputs="Accepts raw CLI args and dispatches converted kwargs to user callbacks.",
                key_classes_and_functions=["BaseCommand", "Command", "Group", "Context"],
                code_explanations=[
                    CodeExplanationItem(
                        name="Command.invoke",
                        symbol_type="method",
                        file_path="src/click/core.py",
                        line_start=100,
                        line_end=140,
                        signature="def invoke(self, ctx: Context) -> Any",
                        summary="Invokes the registered command callback using converted parameters stored in Context.",
                        logic_explanation="Reads ctx.params and forwards them to the underlying Python function.",
                        parameters_and_returns="Takes active Context and returns callback result.",
                        internal_calls=["Context.invoke"],
                        supporting_evidence=[core_ev],
                        confidence="high",
                    )
                ],
                dependencies=["src/click/types.py", "src/click/parser.py"],
                dependents=["src/click/decorators.py"],
                supporting_evidence=[core_ev],
                confidence="high",
            ),
            ComponentUnderstandingItem(
                component_id="src/click/decorators.py",
                name="Decorator Registration Layer",
                file_path="src/click/decorators.py",
                category="entry_point",
                importance_score=0.89,
                primary_responsibility="Exposes @command, @group, @option, and @argument decorators to wrap user functions.",
                why_important="Primary developer-facing entry API.",
                inputs_and_outputs="Wraps a callable and returns a Command or Group instance.",
                key_classes_and_functions=["command", "option", "argument"],
                code_explanations=[],
                dependencies=["src/click/core.py"],
                dependents=[],
                supporting_evidence=[dec_ev],
                confidence="high",
            ),
        ],
        cross_component_interactions=[
            ComponentInteractionItem(
                source_component="src/click/decorators.py",
                target_component="src/click/core.py",
                interaction_type="instantiates",
                description="Decorators instantiate Command and Option objects defined in the core engine.",
                is_confirmed=True,
                supporting_evidence=[dec_ev],
                confidence="high",
            )
        ],
        provider="groq",
        model="openai/gpt-oss-120b",
    )


def make_workflow_understanding() -> RepositoryWorkflowUnderstanding:
    step_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=60,
        line_end=135,
        evidence_type="code",
        confidence="high",
        status="confirmed",
        is_valid=True,
        path_verified=True,
        line_range_verified=True,
    )
    return RepositoryWorkflowUnderstanding(
        repository_name="pallets/click",
        system_architecture_type="library",
        workflow_summary="CLI execution starts at BaseCommand.main, creates a Context, parses and converts options, and invokes the command callback.",
        workflows=[
            ApplicationWorkflow(
                workflow_id="wf-cli-execution",
                name="CLI Command Parsing and Invocation",
                category="user_request",
                description="Parses command-line arguments into typed parameters and invokes the target command callback.",
                trigger="User executes CLI command invoking BaseCommand.main",
                entry_point=WorkflowComponentReference(
                    component_id="src/click/core.py",
                    name="Command Execution Engine",
                    role_in_workflow="Initializes Context and coordinates parsing and invocation",
                ),
                participating_components=[
                    WorkflowComponentReference(
                        component_id="src/click/core.py",
                        name="Command Execution Engine",
                        role_in_workflow="Orchestrates Context creation and callback execution",
                    ),
                    WorkflowComponentReference(
                        component_id="src/click/parser.py",
                        name="Option Parser",
                        role_in_workflow="Tokenizes raw CLI arguments",
                    ),
                ],
                steps=[
                    WorkflowStep(
                        step_number=1,
                        title="Create Execution Context",
                        component_id="src/click/core.py",
                        symbol_name="BaseCommand.make_context",
                        action_type="entry",
                        description="Builds a Context instance and parses raw command-line arguments.",
                        data_received="Raw sys.argv arguments",
                        data_produced="Populated Context object",
                        next_step=2,
                        call_relationship_verified=True,
                        source_order_verified=True,
                        same_execution_path_verified=True,
                        execution_guaranteed=False,
                        runtime_execution_verified=False,
                        call_evidence=CallSiteEvidence(
                            caller_file="src/click/core.py",
                            caller_symbol="BaseCommand.main",
                            callee_file="src/click/core.py",
                            callee_symbol="BaseCommand.make_context",
                            call_name="make_context",
                            call_site_line=72,
                            call_site_column=16,
                            call_graph_edge_id="src/click/core.py:BaseCommand.main->src/click/core.py:BaseCommand.make_context",
                            call_site_id="src/click/core.py:BaseCommand.main->src/click/core.py:BaseCommand.make_context@72:16",
                            is_edge_verified=True,
                            is_site_location_verified=True,
                            evidence_reference=step_ev,
                        ),
                        supporting_evidence=[step_ev],
                        confidence="high",
                    ),
                    WorkflowStep(
                        step_number=2,
                        title="Invoke Command Callback",
                        component_id="src/click/core.py",
                        symbol_name="Command.invoke",
                        action_type="call",
                        description="Dispatches validated parameters from Context into the decorated Python function.",
                        data_received="Validated parameter dictionary",
                        data_produced="Command return value",
                        next_step=None,
                        call_relationship_verified=True,
                        source_order_verified=True,
                        same_execution_path_verified=True,
                        execution_guaranteed=False,
                        runtime_execution_verified=False,
                        supporting_evidence=[step_ev],
                        confidence="high",
                    ),
                ],
                data_flows=[
                    DataFlow(
                        flow_id="df-cli-args",
                        workflow_id="wf-cli-execution",
                        data_item_name="CLI Arguments",
                        origin=WorkflowComponentReference(
                            component_id="src/click/core.py",
                            name="BaseCommand.main",
                            role_in_workflow="Receives raw argument list",
                        ),
                        destination=WorkflowComponentReference(
                            component_id="src/click/core.py",
                            name="Command.invoke",
                            role_in_workflow="Forwards typed parameters to callback",
                        ),
                        data_relationship_status="observed",
                        lifecycle_stages=["received", "parsed", "converted", "dispatched"],
                        transformations=[
                            DataTransformation(
                                transformation_name="Convert CLI Parameter Types",
                                performed_by_component="src/click/types.py",
                                performed_by_symbol="ParamType.convert",
                                transformation_verified=True,
                                data_relationship_status="observed",
                                input_format_or_type="list[str]",
                                output_format_or_type="dict[str, Any]",
                                transformation_logic="Converts raw string tokens into typed Python values.",
                                supporting_evidence=[step_ev],
                                confidence="high",
                            )
                        ],
                        confidence="high",
                    )
                ],
                final_outcome="Target Python callback executes with converted parameters.",
                call_relationships_fully_verified=True,
                source_order_verified=True,
                same_execution_path_verified=True,
                execution_guaranteed=False,
                runtime_execution_verified=False,
                confidence="high",
            )
        ],
        provider="groq",
        model="openai/gpt-oss-120b",
    )


def make_valid_llm_script_dict() -> dict:
    """Builds a realistic 75-second (5 sections, ~185 words) LLM JSON payload."""
    return {
        "script_id": "script-pallets-click",
        "repository_name": "pallets/click",
        "title": "Inside Click: Composable Command-Line Interfaces in Python",
        "introduction": "Click turns ordinary Python functions into composable command-line tools with minimal boilerplate.",
        "intended_audience": ["Developers", "Students"],
        "learning_objectives": [
            "Understand why Click uses decorators to define command-line interfaces",
            "Identify how the Command Execution Engine and Decorator Registration Layer collaborate",
            "Trace how raw command-line arguments are parsed, converted, and dispatched",
        ],
        "total_estimated_duration_seconds": 75.0,
        "conclusion": "By separating decorator declarations from context management and option parsing, Click keeps command-line tools clean and extensible.",
        "evidence_ids": ["PROJ-IDENTITY", "COMP-1", "WF-1"],
        "limitations": [],
        "sections": [
            {
                "section_id": "sec-1-hook",
                "order": 1,
                "title": "Introduction and Problem",
                "purpose": "hook",
                "purpose_description": "Introduce Click and the CLI boilerplate problem it solves.",
                "is_narrated": True,
                "narration_text": _words(35, "intro"),
                "estimated_duration_seconds": 14.0,
                "evidence_ids": ["PROJ-IDENTITY", "PROJ-PROBLEM"],
                "claims": [
                    {
                        "statement": "Click is a Python toolkit for creating composable command-line interfaces with decorators.",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": "Let's see how the architecture is organized.",
            },
            {
                "section_id": "sec-2-architecture",
                "order": 2,
                "title": "Layered CLI Architecture",
                "purpose": "architecture_overview",
                "purpose_description": "Explain the high-level architecture and Python foundation.",
                "is_narrated": True,
                "narration_text": _words(38, "arch"),
                "estimated_duration_seconds": 15.0,
                "evidence_ids": ["ARCH-1", "TECH-1"],
                "claims": [
                    {
                        "statement": "Click separates decorator registration, option parsing, type conversion, and command invocation.",
                        "grounding_status": "inferred",
                        "evidence_ids": ["ARCH-1"],
                    }
                ],
                "transition_to_next": "Now let's examine the two core components that power this design.",
            },
            {
                "section_id": "sec-3-components",
                "order": 3,
                "title": "Decorators and the Command Execution Engine",
                "purpose": "component_deep_dive",
                "purpose_description": "Explain how the decorator layer wraps functions into Command objects.",
                "is_narrated": True,
                "narration_text": _words(45, "comp"),
                "estimated_duration_seconds": 18.0,
                "evidence_ids": ["COMP-1", "COMP-2", "SYM-1-1", "INT-1"],
                "claims": [
                    {
                        "statement": "The Command Execution Engine manages context creation and dispatches converted arguments to callbacks.",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["COMP-1"],
                    }
                ],
                "transition_to_next": "Next, let's trace what happens when a command is invoked.",
            },
            {
                "section_id": "sec-4-workflow",
                "order": 4,
                "title": "Command Parsing and Execution Flow",
                "purpose": "workflow",
                "purpose_description": "Walk through the statically traced CLI execution workflow and argument flow.",
                "is_narrated": True,
                "narration_text": _words(42, "flow"),
                "estimated_duration_seconds": 17.0,
                "evidence_ids": ["WF-1", "WF-1-S1", "WF-1-S2", "DF-1-1"],
                "claims": [
                    {
                        "statement": "In the statically traced execution path, main creates a Context and then invokes the command callback.",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["WF-1-S1", "WF-1-S2"],
                    }
                ],
                "transition_to_next": "Finally, let's recap the key takeaways.",
            },
            {
                "section_id": "sec-5-conclusion",
                "order": 5,
                "title": "Key Takeaways",
                "purpose": "conclusion",
                "purpose_description": "Summarize what the viewer learned.",
                "is_narrated": True,
                "narration_text": _words(28, "outro"),
                "estimated_duration_seconds": 11.0,
                "evidence_ids": ["PROJ-IDENTITY", "FEAT-1"],
                "claims": [],
                "transition_to_next": None,
            },
        ],
    }


def make_mock_llm(response_text: str, provider: str = "groq", model: str = "openai/gpt-oss-120b") -> AsyncMock:
    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = provider
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(
            text=response_text,
            provider=provider,
            model=model,
            finish_reason="stop",
            latency_ms=412.5,
            token_usage=TokenUsageRecord(
                prompt_tokens=920,
                completion_tokens=480,
                total_tokens=1400,
                is_estimated=False,
                provider=provider,
                model=model,
                operation="script_generation",
                job_id="job-test-1",
            ),
        )
    )
    return mock_llm


# ---------------------------------------------------------------------------
# 1. Evidence building from all four understanding outputs
# ---------------------------------------------------------------------------


def test_evidence_builder_combines_all_four_understanding_outputs():
    builder = ScriptEvidenceBuilder()
    pkg = builder.build_evidence_package(
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    assert pkg.repository_name == "pallets/click"
    assert pkg.project_name == "Click"
    assert pkg.narrative_profile == "cli_tool"
    assert set(pkg.available_sources) == {
        UnderstandingSource.REPOSITORY_KNOWLEDGE,
        UnderstandingSource.PROJECT_UNDERSTANDING,
        UnderstandingSource.CODE_UNDERSTANDING,
        UnderstandingSource.WORKFLOW_UNDERSTANDING,
    }
    assert pkg.missing_sources == []

    ids = pkg.item_ids
    assert "PROJ-IDENTITY" in ids
    assert "PROJ-PROBLEM" in ids
    assert "PROJ-AUDIENCE" in ids
    assert "FEAT-1" in ids
    assert "TECH-1" in ids
    assert "ARCH-1" in ids
    assert "COMP-1" in ids
    assert "SYM-1-1" in ids
    assert "INT-1" in ids
    assert "WF-1" in ids
    assert "WF-1-S1" in ids
    assert "DF-1-1" in ids
    assert "EP-1" in ids

    # Verify source references are preserved and verified
    comp_item = pkg.get_item("COMP-1")
    assert comp_item is not None
    assert comp_item.component_id == "src/click/core.py"
    assert comp_item.references[0].file_path == "src/click/core.py"
    assert comp_item.references[0].path_verified is True

    wf_step = pkg.get_item("WF-1-S1")
    assert wf_step is not None
    assert wf_step.verification["call_relationship_verified"] is True
    assert wf_step.verification["runtime_execution_verified"] is False


# ---------------------------------------------------------------------------
# 2. Missing optional understanding outputs
# ---------------------------------------------------------------------------


def test_evidence_builder_handles_missing_optional_understanding_outputs():
    builder = ScriptEvidenceBuilder()
    knowledge = make_repository_knowledge()

    # Only RepositoryKnowledge provided
    pkg = builder.build_evidence_package(
        knowledge=knowledge,
        project_understanding=None,
        code_understanding=None,
        workflow_understanding=None,
    )

    assert pkg.available_sources == [UnderstandingSource.REPOSITORY_KNOWLEDGE]
    assert set(pkg.missing_sources) == {
        UnderstandingSource.PROJECT_UNDERSTANDING,
        UnderstandingSource.CODE_UNDERSTANDING,
        UnderstandingSource.WORKFLOW_UNDERSTANDING,
    }
    # Falls back to RepositoryKnowledge overview, features, important files, and entry points
    assert "PROJ-IDENTITY" in pkg.item_ids
    assert "FEAT-1" in pkg.item_ids
    assert "COMP-1" in pkg.item_ids
    assert "EP-1" in pkg.item_ids
    assert "WF-1" not in pkg.item_ids

    prompt_dict = pkg.to_prompt_dict()
    assert set(prompt_dict["missing_understanding_outputs"]) == {
        "project_understanding",
        "code_understanding",
        "workflow_understanding",
    }


def test_evidence_builder_uses_structural_call_chain_when_workflows_empty():
    wu = make_workflow_understanding()
    wu.workflows = []
    wu.structural_call_chains = [
        StructuralCallChain(
            chain_id="chain-main",
            entry_symbol="BaseCommand.main",
            entry_file="src/click/core.py",
            steps=[],
        )
    ]
    pkg = ScriptEvidenceBuilder().build_evidence_package(
        knowledge=make_repository_knowledge(),
        workflow_understanding=wu,
    )
    chain_item = pkg.get_item("CHAIN-1")
    assert chain_item is not None
    assert chain_item.grounding_hint == GroundingStatus.INFERRED
    assert chain_item.verification["runtime_execution_verified"] is False


# ---------------------------------------------------------------------------
# 3. Evidence prioritization and prompt-size limits
# ---------------------------------------------------------------------------


def test_evidence_prioritization_and_character_budget_limit():
    builder = ScriptEvidenceBuilder()
    tight_budget = 1400
    pkg = builder.build_evidence_package(
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
        max_chars=tight_budget,
    )

    assert pkg.used_chars <= tight_budget
    assert len(pkg.omitted_item_ids) > 0
    assert any("Evidence budget" in r for r in pkg.truncation_reasons)
    # Tier 0 identity/problem items are prioritized ahead of tier 3 items
    assert "PROJ-IDENTITY" in pkg.item_ids
    assert "PROJ-PROBLEM" in pkg.item_ids


# ---------------------------------------------------------------------------
# 4. Secret redaction and sensitive file exclusion
# ---------------------------------------------------------------------------


def test_secret_redaction_and_sensitive_file_exclusion():
    knowledge = make_repository_knowledge()
    pu = make_project_understanding()
    pu.identity.short_description = (
        "Uses key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 and gsk_ABCDEFGHIJKLMNOPQRSTUVWX123456 "
        "plus api_key = \"super_secret_token_987654\"."
    )
    pu.core_features[0].supporting_evidence.append(
        EvidenceReference(
            file_path=".env",
            line_start=1,
            line_end=5,
            evidence_type="config",
            is_valid=True,
        )
    )
    pu.core_features[0].supporting_evidence.append(
        EvidenceReference(
            file_path="config/credentials.pem",
            line_start=1,
            line_end=10,
            evidence_type="config",
            is_valid=True,
        )
    )

    pkg = ScriptEvidenceBuilder().build_evidence_package(
        knowledge=knowledge,
        project_understanding=pu,
    )

    assert pkg.redaction_applied is True
    prompt_json = pkg.to_prompt_json()
    assert "sk-proj-" not in prompt_json
    assert "gsk_" not in prompt_json
    assert "super_secret_token_987654" not in prompt_json
    assert "<REDACTED_SECRET>" in prompt_json
    assert ".env" in pkg.excluded_sensitive_paths
    assert "config/credentials.pem" in pkg.excluded_sensitive_paths


# ---------------------------------------------------------------------------
# 5. Valid structured LLM response
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_script_with_valid_structured_llm_response():
    payload = make_valid_llm_script_dict()
    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-valid-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    assert isinstance(script, EducationalScript)
    assert script.repository_name == "pallets/click"
    assert script.total_estimated_duration_seconds == 75.0
    assert len(script.sections) == 5
    assert script.validation_warnings == []

    # Verify hydration of components, workflow steps, relationships, and data flows
    sec_comp = script.get_section("sec-3-components")
    assert sec_comp is not None
    comp_ids = [c.component_id for c in sec_comp.related_components]
    assert "src/click/core.py" in comp_ids
    assert "src/click/decorators.py" in comp_ids
    assert len(sec_comp.related_relationships) == 1
    assert sec_comp.related_relationships[0].is_statically_confirmed is True

    sec_wf = script.get_section("sec-4-workflow")
    assert sec_wf is not None
    assert len(sec_wf.related_workflow_steps) == 2
    assert all(s.runtime_execution_verified is False for s in sec_wf.related_workflow_steps)
    assert len(sec_wf.related_data_flows) == 1
    assert sec_wf.related_data_flows[0].data_relationship_status == "observed"


# ---------------------------------------------------------------------------
# 6. Malformed JSON and repair behavior
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_malformed_json_triggers_single_repair_and_succeeds():
    valid_payload = make_valid_llm_script_dict()
    broken_text = "Here is the script:\n```json\n{\"script_id\": \"broken\", INVALID_JSON"
    repaired_text = json.dumps(valid_payload)

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                text=broken_text,
                provider="groq",
                model="openai/gpt-oss-120b",
                latency_ms=200.0,
                token_usage=TokenUsageRecord(
                    prompt_tokens=800,
                    completion_tokens=100,
                    total_tokens=900,
                    provider="groq",
                    model="openai/gpt-oss-120b",
                ),
            ),
            LLMResponse(
                text=repaired_text,
                provider="groq",
                model="openai/gpt-oss-120b",
                latency_ms=300.0,
                token_usage=TokenUsageRecord(
                    prompt_tokens=400,
                    completion_tokens=450,
                    total_tokens=850,
                    provider="groq",
                    model="openai/gpt-oss-120b",
                ),
            ),
        ]
    )

    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)
    script = await analyzer.generate_script(
        job_id="job-repair-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    assert mock_llm.generate.call_count == 2
    assert script.metadata.llm_call_count == 2
    assert script.metadata.latency_ms == pytest.approx(500.0)
    assert script.metadata.token_usage.total_tokens == 1750


@pytest.mark.anyio
async def test_unrecoverable_malformed_json_raises_clear_failure():
    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(
            text="not json at all",
            provider="groq",
            model="openai/gpt-oss-120b",
            latency_ms=100.0,
        )
    )
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    with pytest.raises((ScriptGenerationError, AIInvalidResponseError)):
        await analyzer.generate_script(
            job_id="job-bad-json",
            knowledge=make_repository_knowledge(),
        )
    # Primary call + 1 repair call = 2 calls max
    assert mock_llm.generate.call_count == 2


# ---------------------------------------------------------------------------
# 7. Invalid section durations and ordering
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invalid_section_durations_and_ordering_normalized_with_warnings():
    payload = make_valid_llm_script_dict()
    # Provide non-positive duration, duplicate section_id, out-of-sequence order, and mismatched total
    payload["sections"][0]["estimated_duration_seconds"] = -5.0
    payload["sections"][1]["section_id"] = "sec-1-hook"  # duplicate ID
    payload["sections"][1]["order"] = 99
    payload["total_estimated_duration_seconds"] = 200.0

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-norm-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    assert [s.order for s in script.sections] == [1, 2, 3, 4, 5]
    assert script.sections[0].estimated_duration_seconds > 0
    assert script.sections[1].section_id == "sec-1-hook-2"
    assert script.total_estimated_duration_seconds == pytest.approx(
        sum(s.estimated_duration_seconds for s in script.sections)
    )
    assert any("invalid duration" in w for w in script.validation_warnings)
    assert any("Duplicate section_id" in w for w in script.validation_warnings)
    assert any("differed from section sum" in w for w in script.validation_warnings)


# ---------------------------------------------------------------------------
# 8. Unsupported claims and invalid evidence
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unsupported_claims_and_fabricated_evidence_rejected():
    payload = make_valid_llm_script_dict()
    payload["sections"][0]["evidence"] = [
        {"file_path": "nonexistent/hallucinated_module.py", "line_start": 1, "line_end": 50}
    ]
    payload["sections"][0]["related_components"] = [
        {"component_id": "fake/quantum_engine.py", "name": "Quantum Engine"}
    ]
    payload["sections"][0]["claims"].append(
        {
            "statement": "Quantum Engine provides 100% secure zero-latency encryption.",
            "grounding_status": "confirmed",
            "evidence_ids": ["NON-EXISTENT-ID"],
        }
    )
    payload["sections"][0]["claims"].append(
        {
            "statement": "Click uses Redis cluster caching.",
            "grounding_status": "confirmed",
            "evidence": [{"file_path": "fake/redis_cache.py", "line_start": 10, "line_end": 20}],
        }
    )
    # Include a raw file path read aloud in narration
    payload["sections"][0]["narration_text"] = (
        "In src/click/core.py we see def invoke(ctx): which handles commands " + _words(25)
    )

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-hallucination-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    sec1 = script.sections[0]
    assert all(r.file_path != "nonexistent/hallucinated_module.py" for r in sec1.evidence)
    assert all(c.component_id != "fake/quantum_engine.py" for c in sec1.related_components)
    assert all("Redis" not in c.statement and "Quantum" not in c.statement for c in sec1.claims)
    assert any("unverified evidence 'nonexistent/hallucinated_module.py'" in w for w in script.validation_warnings)
    assert any("fabricated component reference 'fake/quantum_engine.py'" in w for w in script.validation_warnings)
    assert any("reads raw file path" in w for w in script.validation_warnings)
    assert any("raw function signature" in w for w in script.validation_warnings)


# ---------------------------------------------------------------------------
# 9. Confirmed, inferred, and uncertain claims
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_confirmed_inferred_and_uncertain_claim_grounding():
    payload = make_valid_llm_script_dict()
    # ARCH-1 has grounding_hint == INFERRED, so a 'confirmed' claim citing only ARCH-1 must be downgraded to 'inferred'
    payload["sections"][1]["claims"] = [
        {
            "statement": "Click follows a layered CLI architecture.",
            "grounding_status": "confirmed",
            "evidence_ids": ["ARCH-1"],
        },
        {
            "statement": "Dynamic plugin loading behavior depends on third-party entry points.",
            "grounding_status": "uncertain",
            "evidence_ids": [],
            "uncertainty_note": "External setuptools entry-point plugins are not present in this repository.",
        },
    ]

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-claims-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    sec2 = script.sections[1]
    assert len(sec2.claims) == 2
    assert sec2.claims[0].grounding_status == GroundingStatus.INFERRED
    assert sec2.claims[1].grounding_status == GroundingStatus.UNCERTAIN
    assert "External setuptools entry-point" in (sec2.claims[1].uncertainty_note or "")
    assert any("downgraded claim" in w for w in script.validation_warnings)


# ---------------------------------------------------------------------------
# 10. Runtime execution claims being rejected
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_runtime_execution_claims_rejected():
    payload = make_valid_llm_script_dict()
    payload["sections"][3]["claims"].append(
        {
            "statement": "Static analysis proves runtime execution is verified for every CLI invocation.",
            "grounding_status": "confirmed",
            "evidence_ids": ["WF-1-S1"],
        }
    )
    payload["sections"][3]["related_workflow_steps"] = [
        {
            "workflow_id": "wf-cli-execution",
            "step_number": 1,
            "runtime_execution_verified": True,
        }
    ]

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-runtime-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    sec4 = script.sections[3]
    assert all("runtime execution is verified" not in c.statement.lower() for c in sec4.claims)
    assert all(s.runtime_execution_verified is False for s in sec4.related_workflow_steps)
    assert any("runtime execution verification" in w for w in script.validation_warnings)
    assert any("runtime_execution_verified=True; forced to False" in w for w in script.validation_warnings)


# ---------------------------------------------------------------------------
# 11. Duration validation and optional controlled revision
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_out_of_range_duration_warns_without_truncating_narration():
    payload = make_valid_llm_script_dict()
    # Make a short 35s script (2 sections)
    payload["sections"] = payload["sections"][:2]
    payload["sections"][0]["estimated_duration_seconds"] = 18.0
    payload["sections"][1]["estimated_duration_seconds"] = 17.0
    payload["sections"][1]["transition_to_next"] = None
    payload["total_estimated_duration_seconds"] = 35.0
    original_text = payload["sections"][0]["narration_text"]

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-short-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
    )

    assert script.total_estimated_duration_seconds == 35.0
    assert script.sections[0].narration_text == original_text
    assert any("shorter than the target range 60–90s" in w for w in script.validation_warnings)


@pytest.mark.anyio
async def test_controlled_duration_revision_when_enabled():
    short_payload = make_valid_llm_script_dict()
    short_payload["sections"] = short_payload["sections"][:2]
    short_payload["sections"][0]["estimated_duration_seconds"] = 20.0
    short_payload["sections"][1]["estimated_duration_seconds"] = 15.0
    short_payload["total_estimated_duration_seconds"] = 35.0

    revised_payload = make_valid_llm_script_dict()  # 75.0s

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                text=json.dumps(short_payload),
                provider="groq",
                model="openai/gpt-oss-120b",
                latency_ms=250.0,
                token_usage=TokenUsageRecord(
                    prompt_tokens=900,
                    completion_tokens=300,
                    total_tokens=1200,
                    provider="groq",
                    model="openai/gpt-oss-120b",
                ),
            ),
            LLMResponse(
                text=json.dumps(revised_payload),
                provider="groq",
                model="openai/gpt-oss-120b",
                latency_ms=310.0,
                token_usage=TokenUsageRecord(
                    prompt_tokens=1000,
                    completion_tokens=480,
                    total_tokens=1480,
                    provider="groq",
                    model="openai/gpt-oss-120b",
                ),
            ),
        ]
    )

    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)
    script = await analyzer.generate_script(
        job_id="job-revise-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
        revise_on_duration_out_of_range=True,
    )

    assert script.metadata.revision_attempted is True
    assert script.metadata.llm_call_count == 2
    assert script.total_estimated_duration_seconds == 75.0


# ---------------------------------------------------------------------------
# 12. Token usage and provider metadata
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_token_usage_and_provider_metadata_recorded():
    payload = make_valid_llm_script_dict()
    mock_llm = make_mock_llm(json.dumps(payload), provider="groq", model="openai/gpt-oss-120b")
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-meta-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        code_understanding=None,
        workflow_understanding=make_workflow_understanding(),
    )

    meta = script.metadata
    assert meta.provider == "groq"
    assert meta.model == "openai/gpt-oss-120b"
    assert meta.is_fallback is False
    assert meta.latency_ms == pytest.approx(412.5)
    assert meta.token_usage is not None
    assert meta.token_usage.prompt_tokens == 920
    assert meta.token_usage.completion_tokens == 480
    assert meta.token_usage.total_tokens == 1400
    assert meta.llm_call_count == 1
    assert meta.evidence_package_chars > 0
    assert UnderstandingSource.CODE_UNDERSTANDING in meta.missing_understandings
    assert any("code_understanding" in lim for lim in script.limitations)


# ---------------------------------------------------------------------------
# 13. LLM provider failure handling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "raised_exc",
    [
        AIProviderUnavailableError("Groq service temporarily unavailable", provider="groq"),
        AIConfigurationError("GROQ_API_KEY is not configured", provider="groq"),
        AITimeoutError("Request timed out after 60s", provider="groq"),
    ],
)
async def test_llm_provider_failure_raises_error_without_fabricating_script(raised_exc):
    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(side_effect=raised_exc)

    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    with pytest.raises(ScriptGenerationError) as exc_info:
        await analyzer.generate_script(
            job_id="job-fail-001",
            knowledge=make_repository_knowledge(),
        )
    assert isinstance(exc_info.value, AIError)
    assert isinstance(exc_info.value, type(raised_exc))


# ---------------------------------------------------------------------------
# 14. Deterministic behavior of evidence selection & narrative profiles
# ---------------------------------------------------------------------------


def test_evidence_selection_is_deterministic_across_input_ordering():
    builder = ScriptEvidenceBuilder()
    k1 = make_repository_knowledge()
    pu1 = make_project_understanding()
    cu1 = make_code_understanding()
    wu1 = make_workflow_understanding()

    k2 = make_repository_knowledge()
    k2.important_files = list(reversed(k2.important_files))
    pu2 = make_project_understanding()
    cu2 = make_code_understanding()
    cu2.components = list(reversed(cu2.components))
    wu2 = make_workflow_understanding()
    wu2.workflows[0].steps = list(reversed(wu2.workflows[0].steps))

    pkg1 = builder.build_evidence_package(k1, pu1, cu1, wu1)
    pkg2 = builder.build_evidence_package(k2, pu2, cu2, wu2)

    assert [i.evidence_id for i in pkg1.items] == [i.evidence_id for i in pkg2.items]
    assert pkg1.to_prompt_json() == pkg2.to_prompt_json()
    assert build_script_user_prompt(pkg1) == build_script_user_prompt(pkg2)


def test_narrative_profile_adapts_to_repository_type():
    builder = ScriptEvidenceBuilder()

    # Full-stack repository
    k_fs = make_repository_knowledge()
    k_fs.technology_stack.frameworks = [
        TechnologyItem(name="React", category="framework", detection_source="manifest"),
        TechnologyItem(name="FastAPI", category="framework", detection_source="manifest"),
    ]
    pkg_fs = builder.build_evidence_package(k_fs)
    assert pkg_fs.narrative_profile == "full_stack_application"

    # Machine learning repository
    k_ml = make_repository_knowledge()
    k_ml.project_overview.description = "Machine learning classifier and model training pipeline."
    k_ml.technology_stack.libraries = [
        TechnologyItem(name="scikit-learn", category="library", detection_source="manifest")
    ]
    pkg_ml = builder.build_evidence_package(k_ml)
    assert pkg_ml.narrative_profile == "machine_learning"


@pytest.mark.anyio
async def test_truncated_json_with_complete_sections_recovered_via_brace_balancing():
    payload = make_valid_llm_script_dict()
    full_json = json.dumps(payload)
    # Truncate right after the second section in the sections array
    cut_marker = '"sec-3-components"'
    idx = full_json.find(cut_marker)
    truncated_json = full_json[: idx - 10]  # cut inside the 3rd section object

    mock_llm = make_mock_llm(truncated_json)
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-trunc-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
    )

    assert len(script.sections) == 5
    assert script.sections[0].section_id == "sec-1-hook"
    assert script.sections[1].section_id == "sec-2-architecture"
    assert mock_llm.generate.call_count == 1


@pytest.mark.anyio
async def test_empty_narration_in_narrated_section_raises_generation_error():
    payload = make_valid_llm_script_dict()
    payload["sections"][0]["narration_text"] = "   "

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    with pytest.raises(ScriptGenerationError):
        await analyzer.generate_script(
            job_id="job-empty-narration",
            knowledge=make_repository_knowledge(),
        )


def test_script_validator_direct_post_validation_filters_invalid_references_and_claims():
    knowledge = make_repository_knowledge()
    valid_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=10,
        line_end=50,
        evidence_type="code",
        is_valid=True,
    )
    bad_line_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=900,
        line_end=950,  # exceeds 500 total lines
        evidence_type="code",
        is_valid=True,
    )

    script = EducationalScript(
        script_id="script-direct-val",
        repository_name="pallets/click",
        title="Direct Validator Test",
        introduction="Testing post-construction validation.",
        learning_objectives=["Verify post-validation behavior"],
        total_estimated_duration_seconds=60.0,
        conclusion="Done.",
        evidence=[valid_ev, bad_line_ev],
        sections=[
            {
                "section_id": "s1",
                "order": 1,
                "title": "Section 1",
                "purpose": SectionPurpose.INTRODUCTION,
                "narration_text": _words(75),
                "estimated_duration_seconds": 30.0,
                "evidence": [valid_ev],
                "claims": [
                    GroundedClaim(
                        statement="Valid confirmed claim.",
                        grounding_status=GroundingStatus.CONFIRMED,
                        evidence=[valid_ev],
                    ),
                    GroundedClaim(
                        statement="Claim with out-of-range line numbers.",
                        grounding_status=GroundingStatus.CONFIRMED,
                        evidence=[bad_line_ev],
                    ),
                ],
                "transition_to_next": "Next.",
            },
            {
                "section_id": "s2",
                "order": 2,
                "title": "Section 2",
                "purpose": SectionPurpose.CONCLUSION,
                "narration_text": _words(75),
                "estimated_duration_seconds": 30.0,
                "evidence": [valid_ev],
            },
        ],
    )

    validated = ScriptValidator().validate_script(script, knowledge=knowledge)
    assert len(validated.evidence) == 1
    assert validated.evidence[0].file_path == "src/click/core.py"
    assert len(validated.sections[0].claims) == 1
    assert validated.sections[0].claims[0].statement == "Valid confirmed claim."
    assert any("dropped 'confirmed' claim" in w for w in validated.validation_warnings)


def test_wrap_ai_error_mro_with_base_aierror():
    """Regression test: _wrap_ai_error handles base AIError and subclasses without MRO TypeError."""
    from app.services.ai.exceptions import AIError, AIInvalidResponseError
    from app.services.ai.script_generation.analyzer import ScriptGenerationError, _wrap_ai_error
    from app.services.ai.storyboard_generation.analyzer import StoryboardGenerationError, _wrap_ai_error as _wrap_sb_error

    base_err = AIError("Direct base AIError failure", provider="groq", status_code=413)
    sub_err = AIInvalidResponseError("Invalid JSON response", provider="groq")
    plain_exc = RuntimeError("Unexpected runtime exception")

    # Script analyzer wrap
    wrapped_base = _wrap_ai_error(base_err)
    assert isinstance(wrapped_base, ScriptGenerationError)
    assert isinstance(wrapped_base, AIError)
    assert wrapped_base.status_code == 413

    wrapped_sub = _wrap_ai_error(sub_err)
    assert isinstance(wrapped_sub, ScriptGenerationError)
    assert isinstance(wrapped_sub, AIInvalidResponseError)

    wrapped_plain = _wrap_ai_error(plain_exc)
    assert isinstance(wrapped_plain, ScriptGenerationError)
    assert "Unexpected runtime exception" in str(wrapped_plain)

    # Storyboard analyzer wrap
    sb_wrapped_base = _wrap_sb_error(base_err)
    assert isinstance(sb_wrapped_base, StoryboardGenerationError)
    assert isinstance(sb_wrapped_base, AIError)
    assert sb_wrapped_base.status_code == 413

    sb_wrapped_sub = _wrap_sb_error(sub_err)
    assert isinstance(sb_wrapped_sub, StoryboardGenerationError)
    assert isinstance(sb_wrapped_sub, AIInvalidResponseError)


@pytest.mark.anyio
async def test_script_revision_triggered_on_short_sections_count():
    """
    Verifies that when LLM returns only 1 section and revise_on_duration_out_of_range=True,
    the analyzer initiates a revision pass to expand the script into 4-6 sections.
    """
    # First response: single brief 1-section script (38 words, ~16s)
    short_payload = {
        "script_id": "script-flask",
        "repository_name": "pallets/flask",
        "title": "Brief Flask Overview",
        "introduction": "Flask is a web framework.",
        "learning_objectives": ["Understand Flask"],
        "total_estimated_duration_seconds": 16.0,
        "sections": [
            {
                "section_id": "sec-1",
                "order": 1,
                "title": "Introduction",
                "purpose": "hook",
                "narration_text": "Flask is a lightweight WSGI web application framework designed to make getting started quick and easy.",
                "estimated_duration_seconds": 16.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "Flask is a lightweight WSGI web framework",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": None,
            }
        ],
        "conclusion": "Flask is simple.",
    }

    # Second response (after revision): valid 4-section educational script
    revised_payload = make_valid_llm_script_dict()

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(
        side_effect=[
            LLMResponse(text=json.dumps(short_payload), provider="groq", model="test-model"),
            LLMResponse(text=json.dumps(revised_payload), provider="groq", model="test-model"),
        ]
    )

    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)
    script = await analyzer.generate_script(
        job_id="job-short-rev",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
        revise_on_duration_out_of_range=True,
    )

    assert mock_llm.generate.call_count == 2
    assert len(script.sections) >= 4
    assert script.metadata.revision_attempted is True


def test_script_validator_records_warning_on_brief_or_low_section_count():
    """
    Verifies that the validator flags scripts with fewer than 3 sections or brief narration.
    """
    raw_dict = {
        "script_id": "script-flask-warn",
        "repository_name": "pallets/flask",
        "title": "Brief Flask",
        "introduction": "Intro",
        "learning_objectives": ["Objective"],
        "total_estimated_duration_seconds": 16.0,
        "sections": [
            {
                "section_id": "sec-1",
                "order": 1,
                "title": "Single Section",
                "purpose": "hook",
                "narration_text": "Short 10 words narration text for testing warnings in validator.",
                "estimated_duration_seconds": 16.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [],
                "transition_to_next": None,
            }
        ],
        "conclusion": "End",
    }

    builder = ScriptEvidenceBuilder()
    pkg = builder.build_evidence_package(
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
    )

    validator = ScriptValidator()
    normalized = validator.normalize_and_ground_raw_script(
        raw_dict=raw_dict,
        evidence_package=pkg,
        knowledge=make_repository_knowledge(),
    )

    warnings = normalized.get("validation_warnings", [])
    assert any("recommended structure is 4 to 6 sections" in w for w in warnings)
    assert any("Total spoken narration is brief" in w for w in warnings)


@pytest.mark.anyio
async def test_llm_generating_two_sections_is_restructured_to_exact_five_sections():
    """
    Verifies that when LLM generates only 2 sections, the script generation service
    reliably produces a valid EducationalScript with EXACTLY 5 sections:
    1. sec-1-hook (HOOK)
    2. sec-2-architecture (ARCHITECTURE_OVERVIEW)
    3. sec-3-components (COMPONENT_DEEP_DIVE)
    4. sec-4-workflow (WORKFLOW)
    5. sec-5-conclusion (CONCLUSION)
    with non-empty narration, valid durations, and contiguous ordering (1..5).
    """
    two_section_payload = {
        "script_id": "script-pallets-click",
        "repository_name": "pallets/click",
        "title": "Inside Click: Composable Command-Line Interfaces in Python",
        "introduction": "Click turns ordinary Python functions into composable command-line tools.",
        "intended_audience": ["Developers", "Students"],
        "learning_objectives": ["Understand Click CLI architecture", "Trace command execution flow"],
        "total_estimated_duration_seconds": 75.0,
        "conclusion": "Click simplifies CLI application development.",
        "evidence_ids": ["PROJ-IDENTITY"],
        "sections": [
            {
                "section_id": "sec-1-hook",
                "order": 1,
                "title": "Introduction & Hook",
                "purpose": "hook",
                "purpose_description": "Introduce the CLI problem.",
                "is_narrated": True,
                "narration_text": "Building clean command-line interfaces often requires excessive boilerplate and argument parsing complexity.",
                "estimated_duration_seconds": 35.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "Click provides decorator-based CLI authoring.",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": "Let us examine the architecture.",
            },
            {
                "section_id": "sec-2-architecture",
                "order": 2,
                "title": "System Architecture",
                "purpose": "architecture_overview",
                "purpose_description": "Explain Click architecture.",
                "is_narrated": True,
                "narration_text": "Click structures command hierarchy through Context and Command objects to cleanly isolate parameter parsing.",
                "estimated_duration_seconds": 40.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "Click isolates parameter parsing into commands.",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": None,
            },
        ],
    }

    mock_llm = make_mock_llm(json.dumps(two_section_payload))
    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)

    script = await analyzer.generate_script(
        job_id="job-two-sec-001",
        knowledge=make_repository_knowledge(),
        project_understanding=make_project_understanding(),
    )

    assert len(script.sections) == 5
    for idx, sec in enumerate(script.sections, start=1):
        assert sec.order == idx
        assert sec.estimated_duration_seconds > 0
        assert len(sec.narration_text.strip()) > 0
        if idx < 5:
            assert sec.transition_to_next is not None

    expected_purposes = [
        SectionPurpose.HOOK,
        SectionPurpose.ARCHITECTURE_OVERVIEW,
        SectionPurpose.COMPONENT_DEEP_DIVE,
        SectionPurpose.WORKFLOW,
        SectionPurpose.CONCLUSION,
    ]
    actual_purposes = [s.purpose for s in script.sections]
    assert actual_purposes == expected_purposes

    expected_section_ids = [
        "sec-1-hook",
        "sec-2-architecture",
        "sec-3-components",
        "sec-4-workflow",
        "sec-5-conclusion",
    ]
    actual_section_ids = [s.section_id for s in script.sections]
    assert actual_section_ids == expected_section_ids




