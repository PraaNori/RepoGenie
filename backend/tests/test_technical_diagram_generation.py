"""
Comprehensive test suite for Milestone 5, Phase 5.2: Technical Diagram Generation.

Covers:
1. Architecture diagram generation (pallets/click fixture).
2. Component diagram generation (sindresorhus/is fixture).
3. Workflow diagram generation (Anomaly-Detection-using-GCP fixture).
4. Data-flow diagram generation.
5. SVG validity, 16:9 1920x1080 canvas composition, typography, and styling.
6. Empty, partial, and incomplete evidence handling with warnings.
7. Path safety and host machine path sanitization.
8. Storage integration, file isolation, and streaming verification.
9. Graphviz failure resilience and pure-vector SVG fallback.
10. VisualGenerationService integration and Stage 07 lifecycle tracking.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitectureAnalysisResult,
    ArchitectureSummary,
    CallGraph,
    CodeStructureSummary,
    DependencyGraph,
    DirectoryTreeNode,
    EntryPointCandidate,
    ImportantFileInfo,
    KnowledgeAnalysisMetadata,
    ParsedRepository,
    ProjectOverviewInfo,
    RepoAnalysisResult,
    RepoStatistics,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    StageEnum,
    StatusEnum,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.code_understanding.schemas import (
    ComponentInteractionItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
from app.services.ai.project_understanding.schemas import EvidenceReference
from app.services.ai.script_generation.schemas import (
    ComponentReference,
    EducationalScript,
    GroundedClaim,
    GroundingStatus,
    ScriptSection,
    SectionPurpose,
    WorkflowStepReference,
)
from app.services.ai.storyboard_generation.schemas import (
    EducationalStoryboard,
    NarrationReference,
    StoryboardScene,
    VisualType,
)
from app.services.ai.workflow_understanding.schemas import (
    ApplicationWorkflow,
    DataFlow,
    DataTransformation,
    RepositoryWorkflowUnderstanding,
    WorkflowComponentReference,
    WorkflowStep,
)
from app.services.storage.job_store import job_store
from app.services.video.visual_generation import (
    ArchitectureDiagramGenerator,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    ComponentDiagramGenerator,
    DataFlowDiagramGenerator,
    DiagramGenerationResult,
    DiagramRenderer,
    DiagramType,
    MediaFormat,
    VisualAsset,
    VisualAssetStatus,
    VisualAssetStorageManager,
    VisualAssetType,
    VisualGenerationResult,
    VisualGenerationService,
    VisualGenerationStatus,
    WorkflowDiagramGenerator,
    diagram_renderer,
    visual_generation_service,
    visual_storage_manager,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixture Builders
# ---------------------------------------------------------------------------

def _build_click_fixtures():
    """Builds representative pallets/click knowledge and understanding fixtures."""
    now = datetime.now(timezone.utc)
    ev_core = EvidenceReference(
        file_path="src/click/core.py",
        line_start=10,
        line_end=50,
        evidence_type="code",
        is_valid=True,
        path_verified=True,
    )
    ev_dec = EvidenceReference(
        file_path="src/click/decorators.py",
        line_start=1,
        line_end=30,
        evidence_type="code",
        is_valid=True,
        path_verified=True,
    )

    knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="click",
            owner="pallets",
            repository_url="https://github.com/pallets/click",
            clone_status=StatusEnum.COMPLETED,
            file_count=20,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="Composable command-line interface toolkit",
        ),
        technology_stack=TechnologyStack(primary_language="Python"),
        repository_structure=RepositoryStructureOverview(
            total_directories=4,
            total_files=20,
            important_directories=["src/click"],
        ),
        statistics=UnifiedStatistics(total_files=20, source_files=15),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(dependency_graph=DependencyGraph(), call_graph=CallGraph()),
        important_files=[
            ImportantFileInfo(relative_path="src/click/core.py", category="entry_point", score=10.0, reason="Core engine", evidence="code"),
            ImportantFileInfo(relative_path="src/click/decorators.py", category="service", score=9.0, reason="Decorators", evidence="code"),
            ImportantFileInfo(relative_path="src/click/parser.py", category="utility", score=8.0, reason="Parser", evidence="code"),
        ],
        entry_points=[
            EntryPointCandidate(file_path="src/click/core.py", entry_type="python_main_guard", confidence="high"),
        ],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=["repo_structure"],
        ),
    )

    code_understanding = RepositoryCodeUnderstanding(
        repository_name="click",
        architecture_overview="Layered command dispatch engine with decorator-based interface",
        components=[
            ComponentUnderstandingItem(
                component_id="comp_decorators",
                name="Decorator API",
                file_path="src/click/decorators.py",
                category="entrypoint",
                importance_score=9.0,
                primary_responsibility="Provides @click.command and argument decorators",
                why_important="Primary developer-facing API surface",
                inputs_and_outputs="Accepts function definition, returns wrapped Command instance",
                key_classes_and_functions=["command()", "option()", "argument()"],
                dependencies=["comp_core"],
            ),
            ComponentUnderstandingItem(
                component_id="comp_core",
                name="Command Engine",
                file_path="src/click/core.py",
                category="core",
                importance_score=9.5,
                primary_responsibility="Manages Command execution, Context, and invocation",
                why_important="Core runtime execution controller",
                inputs_and_outputs="Accepts CLI arguments and context, executes command handler",
                key_classes_and_functions=["Command", "Context", "main()", "invoke()"],
                dependencies=["comp_parser"],
            ),
            ComponentUnderstandingItem(
                component_id="comp_parser",
                name="Parameter Parser",
                file_path="src/click/parser.py",
                category="utility",
                importance_score=8.0,
                primary_responsibility="Parses command-line tokens into typed option values",
                why_important="Converts argv into typed context parameters",
                inputs_and_outputs="Accepts argument strings, outputs typed parameter mapping",
                key_classes_and_functions=["OptionParser", "split_opt()"],
                dependencies=[],
            ),
        ],
        cross_component_interactions=[
            ComponentInteractionItem(
                source_component="comp_decorators",
                target_component="comp_core",
                interaction_type="invokes",
                description="Wraps user function into Command object",
                is_confirmed=True,
            ),
            ComponentInteractionItem(
                source_component="comp_core",
                target_component="comp_parser",
                interaction_type="delegates to",
                description="Delegates argv parsing to OptionParser",
                is_confirmed=True,
            ),
        ],
    )

    scene_arch = StoryboardScene(
        scene_id="scene-arch-click",
        scene_number=2,
        script_section_id="sec-2",
        title="Click Layered Architecture",
        purpose="Illustrate CLI decorator and engine relationships",
        estimated_duration_seconds=15.0,
        visual_type=VisualType.ARCHITECTURE_DIAGRAM,
        visual_description="Layered architecture showing Decorator API -> Command Engine -> Parameter Parser",
        on_screen_text=["Decorator Interface", "Command Engine", "Parameter Parser"],
        narration=NarrationReference(script_section_id="sec-2", excerpt="Click separates decorators from context."),
        related_components=[
            ComponentReference(component_id="comp_decorators", name="Decorator API", file_path="src/click/decorators.py"),
            ComponentReference(component_id="comp_core", name="Command Engine", file_path="src/click/core.py"),
            ComponentReference(component_id="comp_parser", name="Parameter Parser", file_path="src/click/parser.py"),
        ],
        related_files=["src/click/core.py", "src/click/decorators.py"],
        evidence=[ev_core, ev_dec],
    )

    scene_comp = StoryboardScene(
        scene_id="scene-comp-click",
        scene_number=3,
        script_section_id="sec-3",
        title="Command and Context Deep Dive",
        purpose="Walk through Command and Context class responsibilities",
        estimated_duration_seconds=18.0,
        visual_type=VisualType.COMPONENT_DIAGRAM,
        visual_description="Detailed UML view of Command and Context classes",
        on_screen_text=["class Command", "class Context"],
        narration=NarrationReference(script_section_id="sec-3", excerpt="The Command execution engine manages context."),
        related_components=[
            ComponentReference(component_id="comp_core", name="Command Engine", file_path="src/click/core.py"),
        ],
        related_files=["src/click/core.py"],
        evidence=[ev_core],
    )

    return knowledge, code_understanding, scene_arch, scene_comp


def _build_is_fixtures():
    """Builds representative sindresorhus/is fixtures (TypeScript/JS utility library)."""
    now = datetime.now(timezone.utc)
    ev_index = EvidenceReference(
        file_path="source/index.ts",
        line_start=1,
        line_end=40,
        evidence_type="code",
        is_valid=True,
        path_verified=True,
    )

    knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="is",
            owner="sindresorhus",
            repository_url="https://github.com/sindresorhus/is",
            clone_status=StatusEnum.COMPLETED,
            file_count=5,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="readme.md",
            description="Type check values: is.string('unicorn') //=> true",
        ),
        technology_stack=TechnologyStack(primary_language="TypeScript"),
        repository_structure=RepositoryStructureOverview(
            total_directories=1,
            total_files=5,
            important_directories=["source"],
        ),
        statistics=UnifiedStatistics(total_files=5, source_files=3),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(dependency_graph=DependencyGraph(), call_graph=CallGraph()),
        important_files=[
            ImportantFileInfo(relative_path="source/index.ts", category="entry_point", score=10.0, reason="Main entry", evidence="code"),
        ],
        entry_points=[
            EntryPointCandidate(file_path="source/index.ts", entry_type="package_script", confidence="high"),
        ],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=["repo_structure"],
        ),
    )

    code_understanding = RepositoryCodeUnderstanding(
        repository_name="is",
        architecture_overview="Modular TypeScript type predicate library",
        components=[
            ComponentUnderstandingItem(
                component_id="comp_is_core",
                name="Type Predicates Engine",
                file_path="source/index.ts",
                category="core",
                importance_score=9.8,
                primary_responsibility="Provides type guard assertions (is.string, is.number)",
                why_important="Single source of truth for runtime type validation",
                inputs_and_outputs="Accepts arbitrary values, returns boolean type predicate",
                key_classes_and_functions=["is()", "is.string()", "is.number()", "is.object()"],
                dependencies=[],
            )
        ],
    )

    scene_comp = StoryboardScene(
        scene_id="scene-comp-is",
        scene_number=2,
        script_section_id="sec-2",
        title="Type Guard Components",
        purpose="Explain type predicate dispatching",
        estimated_duration_seconds=15.0,
        visual_type=VisualType.COMPONENT_DIAGRAM,
        visual_description="Component class view of type predicates",
        on_screen_text=["Type Guard Interface", "Predicate Matchers"],
        narration=NarrationReference(script_section_id="sec-2", excerpt="is provides type guards for values."),
        related_components=[
            ComponentReference(component_id="comp_is_core", name="Type Predicates Engine", file_path="source/index.ts"),
        ],
        related_files=["source/index.ts"],
        evidence=[ev_index],
    )

    return knowledge, code_understanding, scene_comp


def _build_gcp_fixtures():
    """Builds representative Anomaly-Detection-using-GCP workflow and data flow fixtures."""
    now = datetime.now(timezone.utc)
    ev_main = EvidenceReference(file_path="main.py", line_start=1, line_end=50, is_valid=True)
    ev_model = EvidenceReference(file_path="src/model.py", line_start=1, line_end=60, is_valid=True)
    ev_gcp = EvidenceReference(file_path="src/bigquery_client.py", line_start=1, line_end=40, is_valid=True)

    knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="Anomaly-Detection-using-GCP",
            owner="sachinsingh2156",
            repository_url="https://github.com/sachinsingh2156/Anomaly-Detection-using-GCP",
            clone_status=StatusEnum.COMPLETED,
            file_count=12,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="Real-time anomaly detection pipeline using GCP BigQuery and ML",
        ),
        technology_stack=TechnologyStack(primary_language="Python"),
        repository_structure=RepositoryStructureOverview(
            total_directories=2,
            total_files=12,
            important_directories=["src"],
        ),
        statistics=UnifiedStatistics(total_files=12, source_files=8),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(dependency_graph=DependencyGraph(), call_graph=CallGraph()),
        important_files=[
            ImportantFileInfo(relative_path="main.py", category="entry_point", score=10.0, reason="Entry point", evidence="code"),
            ImportantFileInfo(relative_path="src/model.py", category="model", score=9.0, reason="Model", evidence="code"),
            ImportantFileInfo(relative_path="src/bigquery_client.py", category="database", score=8.0, reason="BigQuery Client", evidence="code"),
        ],
        entry_points=[
            EntryPointCandidate(file_path="main.py", entry_type="python_main_guard", confidence="high"),
        ],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=["repo_structure"],
        ),
    )

    ref_main = WorkflowComponentReference(
        component_id="main.py",
        name="Pipeline Driver",
        role_in_workflow="Coordinates data ingestion, ML model inference, and persistence",
    )
    ref_pubsub = WorkflowComponentReference(
        component_id="src/ingest.py",
        name="GCP Pub/Sub Stream",
        role_in_workflow="Data stream source",
    )
    ref_bq = WorkflowComponentReference(
        component_id="src/bigquery_client.py",
        name="GCP BigQuery Alerts Table",
        role_in_workflow="Alerts persistence sink",
    )

    workflow_understanding = RepositoryWorkflowUnderstanding(
        repository_name="Anomaly-Detection-using-GCP",
        system_architecture_type="Cloud Data Pipeline",
        workflow_summary="End-to-end telemetry ingestion, ML anomaly inference, and BigQuery persistence",
        workflows=[
            ApplicationWorkflow(
                workflow_id="wf_anomaly_detect",
                name="Anomaly Detection Pipeline",
                category="data_storage",
                description="Ingests streaming data, runs isolation forest ML, writes alerts to BigQuery",
                trigger="Telemetry event published to Pub/Sub topic",
                entry_point=ref_main,
                final_outcome="Alert records committed to BigQuery table",
                steps=[
                    WorkflowStep(
                        step_number=1,
                        title="Data Ingestion",
                        component_id="ingest",
                        symbol_name="ingest_records()",
                        action_type="ingestion",
                        description="Read streaming records from Pub/Sub topic",
                        data_received="Raw JSON payload",
                        data_produced="Normalized DataFrame",
                        next_step=2,
                    ),
                    WorkflowStep(
                        step_number=2,
                        title="Feature Engineering",
                        component_id="features",
                        symbol_name="extract_features()",
                        action_type="transformation",
                        description="Compute rolling statistics and Z-scores",
                        data_received="Normalized DataFrame",
                        data_produced="Feature Vector",
                        next_step=3,
                    ),
                    WorkflowStep(
                        step_number=3,
                        title="Model Inference",
                        component_id="model",
                        symbol_name="predict_anomalies()",
                        action_type="computation",
                        description="Execute Isolation Forest score calculation",
                        data_received="Feature Vector",
                        data_produced="Anomaly Flag",
                        next_step=4,
                    ),
                    WorkflowStep(
                        step_number=4,
                        title="BigQuery Persistence",
                        component_id="bigquery",
                        symbol_name="insert_alerts()",
                        action_type="persistence",
                        description="Write anomaly alerts to BigQuery table",
                        data_received="Anomaly Alert",
                        data_produced="DB Confirmation",
                        next_step=None,
                    ),
                ],
                data_flows=[
                    DataFlow(
                        flow_id="df_telemetry",
                        workflow_id="wf_anomaly_detect",
                        data_item_name="Telemetry Records",
                        origin=ref_pubsub,
                        destination=ref_bq,
                        storage_operation_verified=True,
                        storage_operation_type="write",
                        transformations=[
                            DataTransformation(
                                transformation_name="Z-Score Normalization",
                                performed_by_component="src/features.py",
                                performed_by_symbol="extract_features()",
                                observed_operation="compute z-scores",
                                input_format_or_type="Raw Sensor JSON",
                                output_format_or_type="Normalized Matrix",
                                transformation_logic="Computes mean and std dev to calculate z-scores",
                            ),
                            DataTransformation(
                                transformation_name="Anomaly Score Classification",
                                performed_by_component="src/model.py",
                                performed_by_symbol="predict_anomalies()",
                                observed_operation="predict isolation forest",
                                input_format_or_type="Normalized Matrix",
                                output_format_or_type="Alert Record",
                                transformation_logic="Evaluates isolation forest trees for anomaly thresholds",
                            ),
                        ],
                    )
                ],
            )
        ],
    )

    scene_wf = StoryboardScene(
        scene_id="scene-wf-gcp",
        scene_number=3,
        script_section_id="sec-3",
        title="GCP Anomaly Pipeline Workflow",
        purpose="Trace data from PubSub to BigQuery",
        estimated_duration_seconds=18.0,
        visual_type=VisualType.WORKFLOW_DIAGRAM,
        visual_description="Execution sequence from PubSub ingestion to BigQuery persistence",
        on_screen_text=["1. Ingest", "2. Feature Engineering", "3. Inference", "4. BigQuery"],
        narration=NarrationReference(script_section_id="sec-3", excerpt="Data is ingested, processed, and persisted."),
        related_workflow_steps=[
            WorkflowStepReference(workflow_id="wf_anomaly_detect", step_number=1, step_title="Data Ingestion"),
            WorkflowStepReference(workflow_id="wf_anomaly_detect", step_number=2, step_title="Feature Engineering"),
            WorkflowStepReference(workflow_id="wf_anomaly_detect", step_number=3, step_title="Model Inference"),
            WorkflowStepReference(workflow_id="wf_anomaly_detect", step_number=4, step_title="BigQuery Persistence"),
        ],
        related_files=["main.py", "src/model.py"],
        evidence=[ev_main, ev_model],
    )

    scene_df = StoryboardScene(
        scene_id="scene-df-gcp",
        scene_number=4,
        script_section_id="sec-4",
        title="Telemetry Data-Flow Pipeline",
        purpose="Visualizing transformations from stream to alert store",
        estimated_duration_seconds=16.0,
        visual_type=VisualType.DATA_FLOW_VISUALIZATION,
        visual_description="Data lifecycle from raw JSON through Z-score matrix to BigQuery",
        on_screen_text=["Telemetry Stream", "Z-Score Transformation", "BigQuery Sink"],
        narration=NarrationReference(script_section_id="sec-4", excerpt="Transformations turn raw records into alerts."),
        related_files=["src/bigquery_client.py"],
        evidence=[ev_gcp],
    )

    return knowledge, workflow_understanding, scene_wf, scene_df


# ---------------------------------------------------------------------------
# 1. Architecture Diagram Generator Tests
# ---------------------------------------------------------------------------

def test_architecture_diagram_generation_click():
    """Tests architecture diagram generation with pallets/click components and interactions."""
    knowledge, code_und, scene_arch, _ = _build_click_fixtures()
    generator = ArchitectureDiagramGenerator()

    result = generator.generate(scene_arch, knowledge, code_understanding=code_und)

    assert result.diagram_type == DiagramType.ARCHITECTURE
    assert result.width == CANVAS_WIDTH
    assert result.height == CANVAS_HEIGHT
    assert result.aspect_ratio == "16:9"

    # SVG content checks
    assert "<svg" in result.svg_content
    assert "</svg>" in result.svg_content
    assert f'viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}"' in result.svg_content
    assert "ARCHITECTURE DIAGRAM" in result.svg_content
    assert "Click Layered Architecture" in result.svg_content

    # Grounded component citations
    assert "Command Engine" in result.svg_content or "comp_core" in result.dot_source
    assert "Decorator API" in result.svg_content or "comp_decorators" in result.dot_source
    assert "src/click/core.py" in result.svg_content or "core.py" in result.svg_content

    # Dual syntax check
    assert "digraph Architecture" in result.dot_source
    assert "graph LR" in result.mermaid_source or "graph TB" in result.mermaid_source
    assert result.render_duration_ms > 0


# ---------------------------------------------------------------------------
# 2. Component Diagram Generator Tests
# ---------------------------------------------------------------------------

def test_component_diagram_generation_is():
    """Tests component diagram generation with sindresorhus/is TypeScript type guards."""
    knowledge, code_und, scene_comp = _build_is_fixtures()
    generator = ComponentDiagramGenerator()

    result = generator.generate(scene_comp, knowledge, code_understanding=code_und)

    assert result.diagram_type == DiagramType.COMPONENT
    assert "<svg" in result.svg_content
    assert "COMPONENT DIAGRAM" in result.svg_content
    assert "Type Guard" in result.svg_content or "Type Predicates" in result.svg_content

    # UML syntax checks
    assert "digraph ComponentUML" in result.dot_source
    assert "classDiagram" in result.mermaid_source
    assert "is" in result.mermaid_source


# ---------------------------------------------------------------------------
# 3. Workflow Diagram Generator Tests
# ---------------------------------------------------------------------------

def test_workflow_diagram_generation_gcp():
    """Tests sequential workflow diagram generation with GCP Anomaly Detection steps."""
    knowledge, wf_und, scene_wf, _ = _build_gcp_fixtures()
    generator = WorkflowDiagramGenerator()

    result = generator.generate(scene_wf, knowledge, workflow_understanding=wf_und)

    assert result.diagram_type == DiagramType.WORKFLOW
    assert "<svg" in result.svg_content
    assert "WORKFLOW DIAGRAM" in result.svg_content
    assert "Anomaly" in result.svg_content

    # Execution step checks
    assert "1. Ingest" in result.svg_content or "ingest_records" in result.dot_source
    assert "BigQuery" in result.dot_source
    assert "flowchart LR" in result.mermaid_source


# ---------------------------------------------------------------------------
# 4. Data-Flow Diagram Generator Tests
# ---------------------------------------------------------------------------

def test_data_flow_diagram_generation_gcp():
    """Tests data flow and transformation pipeline with Pub/Sub and BigQuery sinks."""
    knowledge, wf_und, _, scene_df = _build_gcp_fixtures()
    generator = DataFlowDiagramGenerator()

    result = generator.generate(scene_df, knowledge, workflow_understanding=wf_und)

    assert result.diagram_type == DiagramType.DATA_FLOW
    assert "<svg" in result.svg_content
    assert "DATA-FLOW DIAGRAM" in result.svg_content

    # Pipeline stages and storage shapes
    assert "shape=cylinder" in result.dot_source
    assert "BigQuery" in result.dot_source or "Sink" in result.dot_source
    assert "flowchart LR" in result.mermaid_source


# ---------------------------------------------------------------------------
# 5. SVG Validity & Educational Design Standards
# ---------------------------------------------------------------------------

def test_svg_xml_validity_and_standards():
    """Verifies that generated SVGs are well-formed XML and satisfy 1080p landscape specifications."""
    knowledge, code_und, scene_arch, _ = _build_click_fixtures()
    result = ArchitectureDiagramGenerator().generate(scene_arch, knowledge, code_understanding=code_und)

    # XML well-formedness parse check
    root = ET.fromstring(result.svg_content)
    assert root.tag.endswith("svg")
    assert root.attrib["width"] == "1920"
    assert root.attrib["height"] == "1080"
    assert root.attrib["viewBox"] == "0 0 1920 1080"

    # Background canvas check
    assert 'fill="#F8FAFC"' in result.svg_content or "#F8FAFC" in result.svg_content

    # Header and footer elements present
    assert "RepoGenie Visuals" in result.svg_content
    assert "16:9 1080p" in result.svg_content


# ---------------------------------------------------------------------------
# 6. Evidence Validation, Fallback & Sanitization Tests
# ---------------------------------------------------------------------------

def test_sparse_evidence_generates_safe_fallback_with_warnings():
    """Verifies that empty or sparse evidence does not crash and produces explicit warnings."""
    now = datetime.now(timezone.utc)
    sparse_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="empty-repo",
            owner="test",
            repository_url="https://github.com/test/empty-repo",
            clone_status=StatusEnum.COMPLETED,
            file_count=0,
        ),
        project_overview=ProjectOverviewInfo(readme_available=False, description="Minimal"),
        technology_stack=TechnologyStack(),
        repository_structure=RepositoryStructureOverview(total_directories=0, total_files=0),
        statistics=UnifiedStatistics(total_files=0, source_files=0),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(dependency_graph=DependencyGraph(), call_graph=CallGraph()),
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=[],
        ),
    )
    sparse_scene = StoryboardScene(
        scene_id="scene-empty",
        scene_number=1,
        script_section_id="sec-1",
        title="Empty Architecture",
        purpose="Test sparse inputs",
        estimated_duration_seconds=10.0,
        visual_type=VisualType.ARCHITECTURE_DIAGRAM,
        visual_description="No evidence available",
    )

    generator = ArchitectureDiagramGenerator()
    result = generator.generate(sparse_scene, sparse_knowledge)

    # Still renders a valid SVG
    assert "<svg" in result.svg_content
    assert len(result.validation_warnings) > 0
    assert any("sparse" in w.lower() or "no ai code components" in w.lower() for w in result.validation_warnings)


def test_host_machine_path_sanitization():
    """Verifies that sensitive local developer paths (e.g. /Users/..., /tmp/...) are sanitized."""
    knowledge, _, _, _ = _build_click_fixtures()
    dirty_scene = StoryboardScene(
        scene_id="scene-leak-check",
        scene_number=1,
        script_section_id="sec-1",
        title="Architecture",
        purpose="Test path leakage",
        estimated_duration_seconds=10.0,
        visual_type=VisualType.ARCHITECTURE_DIAGRAM,
        visual_description="Inspecting /Users/pradeepikanori/Downloads/RepoGenie/secret/config.py",
        related_files=["/Users/pradeepikanori/Downloads/RepoGenie/secret/config.py"],
    )

    generator = ArchitectureDiagramGenerator()
    result = generator.generate(dirty_scene, knowledge)

    assert "/Users/pradeepikanori" not in result.svg_content
    assert "/Users/pradeepikanori" not in result.dot_source
    assert "/Users/pradeepikanori" not in result.mermaid_source


# ---------------------------------------------------------------------------
# 7. Graphviz Failure Resilience & Vector Fallback Tests
# ---------------------------------------------------------------------------

def test_graphviz_failure_triggers_vector_fallback():
    """Verifies that when Graphviz dot binary fails or is missing, vector fallback renders valid SVG."""
    renderer = DiagramRenderer(dot_binary_path="/nonexistent/binary/path/dot")
    assert not renderer.is_graphviz_available()

    nodes = [
        {"id": "node_a", "label": "Entry Module", "sublabel": "CLI Handler", "file": "main.py", "category": "entrypoint"},
        {"id": "node_b", "label": "Processing Engine", "sublabel": "Business Logic", "file": "engine.py", "category": "core"},
    ]
    edges = [{"from": "node_a", "to": "node_b", "label": "calls"}]

    svg = renderer.render_diagram(
        dot_source="invalid dot",
        title="Fallback Architecture",
        subtitle="Pure vector rendering without external binary",
        category_label="Architecture Diagram",
        diagram_type=DiagramType.ARCHITECTURE,
        evidence_files=["main.py", "engine.py"],
        fallback_nodes=nodes,
        fallback_edges=edges,
    )

    assert "<svg" in svg
    assert "viewBox=\"0 0 1920 1080\"" in svg
    assert "Fallback Architecture" in svg
    assert "Entry Module" in svg
    assert "Processing Engine" in svg


# ---------------------------------------------------------------------------
# 8. VisualGenerationService Integration & Stage 07 Lifecycle Tests
# ---------------------------------------------------------------------------

def test_generate_diagram_for_scene_service(tmp_path: Path):
    """Tests VisualGenerationService.generate_diagram_for_scene directly."""
    storage_mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)
    service = VisualGenerationService(storage_manager=storage_mgr)
    knowledge, code_und, scene_arch, _ = _build_click_fixtures()

    job_id = "job-diag-test-1"
    asset = service.generate_diagram_for_scene(
        job_id=job_id,
        scene=scene_arch,
        knowledge=knowledge,
        code_understanding=code_und,
    )

    assert asset.status == VisualAssetStatus.COMPLETED
    assert asset.media_format == MediaFormat.SVG
    assert asset.width == 1920
    assert asset.height == 1080
    assert asset.storage_path == f"jobs/{job_id}/visuals/{asset.asset_id}.svg"
    assert asset.metadata.diagram_syntax == "graphviz+mermaid"

    # Verify file is physically on disk
    filename = f"{asset.asset_id}.svg"
    assert storage_mgr.asset_file_exists(job_id, filename)
    content = storage_mgr.read_asset_content(job_id, filename)
    assert b"<svg" in content


def test_generate_diagrams_for_job_lifecycle():
    """
    Verifies that generate_diagrams_for_job:
    - Renders diagram scenes into completed assets.
    - Leaves non-diagram scenes in PLANNED/PENDING status.
    - Accurately computes assets_completed and assets_pending.
    """
    knowledge, code_und, scene_arch, scene_comp = _build_click_fixtures()
    title_scene = StoryboardScene(
        scene_id="scene-1-title",
        scene_number=1,
        script_section_id="sec-1",
        title="Title Card",
        purpose="Intro",
        estimated_duration_seconds=10.0,
        visual_type=VisualType.TITLE_CARD,
        visual_description="Logo and title",
    )
    storyboard = EducationalStoryboard(
        storyboard_id="sb-diag-lifecycle",
        script_id="sc-1",
        repository_name="pallets/click",
        title="Click Storyboard",
        total_estimated_duration_seconds=43.0,
        scenes=[title_scene, scene_arch, scene_comp],
    )

    job_id = "job-diag-lifecycle"
    plan = visual_generation_service.initialize_visual_assets(job_id, storyboard)
    assert plan.total_scenes == 3
    assert plan.total_assets == 3
    assert plan.assets_pending == 3
    assert plan.assets_completed == 0

    # Run diagram generation pass
    result = visual_generation_service.generate_diagrams_for_job(
        job_id=job_id,
        plan=plan,
        storyboard=storyboard,
        knowledge=knowledge,
        code_understanding=code_und,
    )

    # 2 diagram scenes (arch & comp) rendered, 1 non-diagram scene (title) remains pending
    assert result.scenes_completed == 2
    assert result.assets_completed == 2
    assert result.assets_pending == 1
    assert result.is_fully_rendered is False

    # Check scene statuses
    assert result.scene_assets[0].primary_asset.status == VisualAssetStatus.PENDING  # Title card
    assert result.scene_assets[1].primary_asset.status == VisualAssetStatus.COMPLETED  # Architecture
    assert result.scene_assets[2].primary_asset.status == VisualAssetStatus.COMPLETED  # Component


def test_api_post_visual_assets_renders_diagrams_and_file_streaming():
    """
    Full API integration test:
    POST /visual-assets plans and generates technical diagrams.
    GET /file streams the rendered SVG for diagram scenes.
    """
    internal = job_store.create_job(
        repo_url="https://github.com/pallets/click",
        repo_name="click",
        repository_owner="pallets",
        repository_name="click",
        clone_url="https://github.com/pallets/click.git",
    )
    job_id = internal.job_id
    internal.local_path = f"/tmp/repos/{job_id}"

    job_store.update_job_ingestion_success(job_id, internal.local_path, 20, 1.0)
    analysis = RepoAnalysisResult(
        repository_name="click",
        directory_tree=DirectoryTreeNode(name="click", path="", type="directory"),
        statistics=RepoStatistics(
            total_files=20,
            total_directories=4,
            source_files=15,
            filtered_files=5,
            total_size_bytes=1024,
            configuration_files=1,
            dependency_manifests=1,
            recognized_languages_count=1,
        ),
        languages=[],
        dependency_files=[],
        configuration_files=[],
    )
    job_store.update_job_analysis_success(job_id, analysis)

    parsed_repo = ParsedRepository(
        job_id=job_id,
        repository_name="click",
        total_parsed_files=15,
        total_functions=10,
        total_classes=5,
        total_methods=10,
        total_imports=10,
        total_function_calls=10,
        supported_languages=["python"],
    )
    knowledge, code_und, scene_arch, _ = _build_click_fixtures()
    job_store.update_job_knowledge_success(
        job_id=job_id,
        code_analysis=parsed_repo,
        architecture=ArchitectureAnalysisResult(
            job_id=job_id,
            repository_name="click",
            dependency_graph=DependencyGraph(),
            call_graph=CallGraph(),
        ),
        knowledge=knowledge,
    )
    internal.code_understanding = code_und

    title_scene = StoryboardScene(
        scene_id="scene-1",
        scene_number=1,
        script_section_id="sec-1",
        title="Title",
        purpose="Intro",
        estimated_duration_seconds=10.0,
        visual_type=VisualType.TITLE_CARD,
        visual_description="Title card",
    )
    storyboard = EducationalStoryboard(
        storyboard_id=f"sb-{job_id}",
        script_id=f"sc-{job_id}",
        repository_name="pallets/click",
        title="Click Storyboard",
        total_estimated_duration_seconds=25.0,
        scenes=[title_scene, scene_arch],
    )
    job_store.update_job_educational_script_success(
        job_id,
        EducationalScript(
            script_id=f"sc-{job_id}",
            repository_name="pallets/click",
            title="Click Script",
            introduction="Intro to Click CLI",
            learning_objectives=["Understand Click Architecture"],
            total_estimated_duration_seconds=25.0,
            sections=[
                ScriptSection(
                    section_id="sec-1",
                    order=1,
                    title="Intro",
                    purpose=SectionPurpose.HOOK,
                    narration_text="Welcome to Click CLI.",
                    estimated_duration_seconds=10.0,
                ),
                ScriptSection(
                    section_id="sec-2",
                    order=2,
                    title="Architecture",
                    purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
                    narration_text="Click separates decorators from context.",
                    estimated_duration_seconds=15.0,
                ),
            ],
            conclusion="Outro",
        ),
    )
    job_store.update_job_educational_storyboard_success(job_id, storyboard)

    # 1. Trigger POST /visual-assets
    post_resp = client.post(f"/api/v1/jobs/{job_id}/visual-assets")
    assert post_resp.status_code == 200
    post_data = post_resp.json()

    assert post_data["total_scenes"] == 2
    assert post_data["assets_completed"] == 1  # Scene 2 (Architecture diagram) rendered!
    assert post_data["assets_pending"] == 1    # Scene 1 (Title card) pending

    # Stage 07 remains IN_PROGRESS because title card is not yet rendered
    j = job_store.get_job(job_id)
    assert j.stages[6].status == StatusEnum.IN_PROGRESS
    assert j.current_stage == StageEnum.VISUAL_GENERATION.value

    # 2. Verify file streaming for rendered architecture diagram
    arch_asset_id = post_data["scene_assets"][1]["primary_asset"]["asset_id"]
    file_resp = client.get(f"/api/v1/jobs/{job_id}/visual-assets/{arch_asset_id}/file")
    assert file_resp.status_code == 200
    assert "image/svg+xml" in file_resp.headers["content-type"]
    assert b"<svg" in file_resp.content
    assert b"ARCHITECTURE DIAGRAM" in file_resp.content
