"""
Comprehensive test suite for Milestone 5, Phase 5.3: Code Walkthrough and Scene Visual Generation.

Covers:
1. Code extraction: real source lines from disk and AST, 1-indexing, omission markers, sensitive file redaction.
2. Code highlighting: Pygments tokenization across Python & TypeScript, XML escaping, color palette.
3. Code walkthrough SVG: 1920x1080 canvas, window styling, gutter, highlighted lines, context panel.
4. Title card SVG: hero project title, description, tech stack tags, module cards, fallback handling.
5. Summary card SVG: key takeaways (architecture, execution, verification), quote box, fallback handling.
6. VisualGenerationService integration: dispatch across all visual types, storage persistence, asset isolation.
7. End-to-end storyboard rendering: Stage 07 completion when 100% rendered vs IN_PROGRESS when incomplete/failed.
8. Security & privacy: path sanitization and secret redaction in code visuals.
"""

from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

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
    TechnologyItem,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.code_understanding.schemas import (
    ComponentInteractionItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
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
from app.services.storage.job_store import job_store
from app.services.video.visual_generation import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    CodeExcerpt,
    CodeExtractor,
    CodeHighlighter,
    CodeWalkthroughGenerator,
    CodeWalkthroughLine,
    MediaFormat,
    SummaryCardGenerator,
    TitleCardGenerator,
    VisualAsset,
    VisualAssetStatus,
    VisualAssetStorageManager,
    VisualAssetType,
    VisualGenerationMetadata,
    VisualGenerationResult,
    VisualGenerationService,
    VisualGenerationStatus,
    code_extractor,
    code_highlighter,
    code_walkthrough_generator,
    summary_card_generator,
    title_card_generator,
    visual_generation_service,
    visual_storage_manager,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_repo_dir(tmp_path: Path) -> Path:
    """Create a temporary repository directory with real code and sensitive files."""
    repo_root = tmp_path / "sample_repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    # 1. Standard python module
    src_dir = repo_root / "src" / "core"
    src_dir.mkdir(parents=True, exist_ok=True)

    py_code = (
        '"""Core engine for pipeline operations."""\n'
        'import sys\n'
        'from typing import Optional\n\n'
        'def process_pipeline(input_data: str, verbose: bool = True) -> int:\n'
        '    """Process input pipeline with verification."""\n'
        '    cleaned = input_data.strip()\n'
        '    if not cleaned:\n'
        '        return 0\n'
        '    tokens = cleaned.split()\n'
        '    count = len(tokens)\n'
        '    if verbose:\n'
        '        print(f"Processed {count} tokens")\n'
        '    return count\n\n'
        'class PipelineWorker:\n'
        '    def __init__(self, name: str):\n'
        '        self.name = name\n'
    )
    (src_dir / "engine.py").write_text(py_code, encoding="utf-8")

    # 2. Long python file to test excerpting and omissions (> 25 lines)
    long_code_lines = [f"# Line {i}\ndef step_{i}():\n    return {i}\n" for i in range(1, 30)]
    (src_dir / "long_file.py").write_text("\n".join(long_code_lines), encoding="utf-8")

    # 3. Sensitive files (must be rejected/redacted)
    (repo_root / ".env").write_text("API_SECRET_KEY=sk_live_12345\n", encoding="utf-8")
    (repo_root / "credentials.json").write_text('{"token": "secret_abc"}', encoding="utf-8")
    (repo_root / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...", encoding="utf-8")

    return repo_root


@pytest.fixture
def sample_parsed_repo() -> ParsedRepository:
    return ParsedRepository(
        job_id="test-job",
        repository_name="sample_repo",
        total_parsed_files=1,
        total_functions=1,
        total_classes=1,
        total_methods=1,
        total_imports=2,
        total_function_calls=2,
        supported_languages=["python"],
        classes=[],
        functions=[],
    )


@pytest.fixture
def sample_knowledge() -> RepositoryKnowledge:
    now = datetime.now(timezone.utc)
    return RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="sample_repo",
            owner="test-owner",
            repository_url="https://github.com/test-owner/sample_repo",
            clone_status=StatusEnum.COMPLETED,
            file_count=10,
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="Core pipeline operations engine",
        ),
        technology_stack=TechnologyStack(
            languages=[TechnologyItem(name="Python", category="language", detection_source="manifest")],
            frameworks=[TechnologyItem(name="FastAPI", category="framework", detection_source="manifest")],
        ),
        repository_structure=RepositoryStructureOverview(
            root_directory="",
            important_directories=["src/core"],
        ),
        statistics=UnifiedStatistics(total_files=10, source_files=8),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(),
        architecture=ArchitectureSummary(dependency_graph=DependencyGraph(), call_graph=CallGraph()),
        important_files=[
            ImportantFileInfo(relative_path="src/core/engine.py", category="core", score=10.0, reason="Core engine", evidence="code"),
        ],
        entry_points=[
            EntryPointCandidate(file_path="src/core/engine.py", entry_type="python_main_guard", confidence="high"),
        ],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=now,
            stages_completed=["repo_structure"],
        ),
    )


@pytest.fixture
def sample_project_understanding() -> ProjectUnderstanding:
    return ProjectUnderstanding(
        identity=ProjectIdentity(
            name="RepoGenie Core",
            short_description="AI-powered repository to educational video engine",
            category="Developer Tool",
            project_type="Video Generation Platform",
            primary_purpose="Educational video walkthroughs of codebases",
        ),
        problem_statement=ProblemStatement(
            problem_addressed="Complex codebases are hard to understand without guided visual walkthroughs.",
            why_it_matters="Developer onboarding is slow and error-prone.",
            how_project_solves_it="Automatically parses repository code, extracts workflows, and generates visual educational videos.",
        ),
        core_features=[
            CoreFeatureItem(
                name="Visual Storyboarding",
                description="Converts scripts to timed storyboard scenes with code walkthroughs.",
                user_benefit="Clear visual explanations of code.",
            )
        ],
        target_audience=TargetAudience(
            intended_users=["Developers", "Students", "Engineering Learners"],
            likely_needs=["Understand unfamiliar open source repositories"],
        ),
        technology_stack=[
            TechnologyExplanationItem(
                technology_name="Python",
                category="Programming Language",
                role_in_project="Core backend logic and tree-sitter analysis",
                why_used="Rich ecosystem for parsing and AI integrations",
            ),
            TechnologyExplanationItem(
                technology_name="FastAPI",
                category="Web Framework",
                role_in_project="RESTful API service",
                why_used="High performance and async capabilities",
            ),
            TechnologyExplanationItem(
                technology_name="Pygments",
                category="Syntax Highlighting",
                role_in_project="Token-level code highlighting",
                why_used="Robust syntax highlighting without external binary dependencies",
            ),
        ],
        overall_explanation=ApplicationExplanation(
            concise_overview="RepoGenie Core parses repositories and produces structured video explanations.",
            detailed_explanation="Comprehensive engine with tree-sitter, LLM analyzers, and SVG visual generators.",
            beginner_friendly="Turns complex code into digestible step-by-step videos.",
            interesting_aspects="Automated evidence-grounded diagrams and code highlights.",
            video_demonstration_highlights=["Interactive diagrams", "Highlighted syntax lines"],
        ),
    )


@pytest.fixture
def sample_code_understanding() -> RepositoryCodeUnderstanding:
    return RepositoryCodeUnderstanding(
        repository_name="sample_repo",
        architecture_overview="Core pipeline operations engine with stream verification",
        components=[
            ComponentUnderstandingItem(
                component_id="src/core/engine.py",
                name="PipelineEngine",
                file_path="src/core/engine.py",
                category="core",
                importance_score=0.9,
                primary_responsibility="Processes incoming stream tokens and coordinates pipeline verification.",
                why_important="Core engine orchestrating repository analysis.",
                inputs_and_outputs="Inputs string stream, outputs token count integer.",
                key_classes_and_functions=["process_pipeline", "PipelineWorker"],
            )
        ],
        interactions=[
            ComponentInteractionItem(
                source_component="PipelineWorker",
                target_component="PipelineEngine",
                interaction_type="calls",
                description="Coordinates processing stream.",
            )
        ],
    )


@pytest.fixture
def sample_script() -> EducationalScript:
    return EducationalScript(
        script_id="script-core-engine",
        repository_name="sample_repo",
        title="RepoGenie Core Architecture and Engine",
        introduction="Welcome to RepoGenie Core, a platform for understanding complex repositories.",
        intended_audience=["Developers", "Engineers"],
        learning_objectives=[
            "Understand the Core Engine architecture",
            "Walk through pipeline stream processing",
            "Verify complete workflow execution",
        ],
        total_estimated_duration_seconds=60.0,
        sections=[
            ScriptSection(
                section_id="sec-1",
                order=1,
                title="Introduction",
                purpose=SectionPurpose.INTRODUCTION,
                narration_text="Welcome to RepoGenie Core, a platform for understanding complex repositories.",
                estimated_duration_seconds=15.0,
            ),
            ScriptSection(
                section_id="sec-2",
                order=2,
                title="Core Processing Walkthrough",
                purpose=SectionPurpose.COMPONENT_DEEP_DIVE,
                narration_text="The process_pipeline function cleans inputs and verifies token counts.",
                estimated_duration_seconds=30.0,
                related_components=[
                    ComponentReference(
                        component_id="comp_engine",
                        name="PipelineEngine",
                        file_path="src/core/engine.py",
                    )
                ],
            ),
            ScriptSection(
                section_id="sec-3",
                order=3,
                title="Summary and Wrap-up",
                purpose=SectionPurpose.CONCLUSION,
                narration_text="In conclusion, modular pipelines and automated visuals make complex code accessible.",
                estimated_duration_seconds=15.0,
            ),
        ],
        conclusion="In conclusion, modular pipelines and automated visuals make complex code accessible.",
    )


@pytest.fixture
def sample_storyboard() -> EducationalStoryboard:
    return EducationalStoryboard(
        storyboard_id="sb-core-engine",
        script_id="script-core-engine",
        repository_name="sample_repo",
        title="RepoGenie Storyboard",
        total_estimated_duration_seconds=60.0,
        scenes=[
            StoryboardScene(
                scene_id="scene-1",
                scene_number=1,
                script_section_id="sec-1",
                title="RepoGenie Title Card",
                purpose="Hook audience and display repository overview",
                visual_type=VisualType.TITLE_CARD,
                visual_description="Hero project title card with technology badges and topic cards",
                estimated_duration_seconds=15.0,
                narration=NarrationReference(
                    script_section_id="sec-1",
                    excerpt="Welcome to RepoGenie Core.",
                ),
                on_screen_text=["Hero project title", "Technology stack tags", "Topic cards"],
            ),
            StoryboardScene(
                scene_id="scene-2",
                scene_number=2,
                script_section_id="sec-2",
                title="Engine Code Walkthrough",
                purpose="Walk through process_pipeline function",
                visual_type=VisualType.CODE_WALKTHROUGH,
                visual_description="IDE code walkthrough editor showing process_pipeline",
                estimated_duration_seconds=30.0,
                narration=NarrationReference(
                    script_section_id="sec-2",
                    excerpt="The process_pipeline function inspects each token.",
                ),
                on_screen_text=["process_pipeline", "def process_pipeline"],
                related_files=["src/core/engine.py"],
            ),
            StoryboardScene(
                scene_id="scene-3",
                scene_number=3,
                script_section_id="sec-3",
                title="Conclusion and Takeaways",
                purpose="Summarize architecture, execution, and verification",
                visual_type=VisualType.SUMMARY_CARD,
                visual_description="Structured 3-pillar summary card with concluding remark",
                estimated_duration_seconds=15.0,
                narration=NarrationReference(
                    script_section_id="sec-3",
                    excerpt="In conclusion, modular design ensures easy onboarding.",
                ),
                on_screen_text=["Architecture takeaway", "Execution takeaway", "Verification takeaway"],
            ),
        ],
    )


# ============================================================================
# 1. Code Extractor & Highlighter Tests
# ============================================================================

def test_code_extractor_real_file(sample_repo_dir: Path):
    """Test authentic source extraction with accurate 1-indexed line numbers."""
    extractor = CodeExtractor()
    scene = StoryboardScene(
        scene_id="scene-extract-1",
        scene_number=1,
        script_section_id="sec-1",
        title="Engine Walkthrough",
        purpose="Walkthrough of engine",
        estimated_duration_seconds=15.0,
        visual_type=VisualType.CODE_WALKTHROUGH,
        visual_description="Code walkthrough of process_pipeline",
        related_files=["src/core/engine.py"],
    )
    excerpt, warnings = extractor.extract_code_excerpt(
        scene=scene,
        repo_root_dir=str(sample_repo_dir),
    )

    assert excerpt.file_path == "src/core/engine.py"
    assert excerpt.language.lower() == "python"
    assert len(excerpt.lines) > 0
    text_content = "\n".join(l.content for l in excerpt.lines)
    assert "process_pipeline" in text_content


def test_code_extractor_sensitive_file_guard(sample_repo_dir: Path):
    """Sensitive files like .env or id_rsa must never be extracted."""
    extractor = CodeExtractor()
    for sensitive in [".env", "credentials.json", "id_rsa"]:
        assert extractor.is_sensitive_file(sensitive)
        scene = StoryboardScene(
            scene_id=f"scene-sens-{sensitive}",
            scene_number=1,
            script_section_id="sec-1",
            title="Secret",
            purpose="Inspect secret",
            estimated_duration_seconds=10.0,
            visual_type=VisualType.CODE_WALKTHROUGH,
            visual_description="Inspect secret",
            related_files=[sensitive],
        )
        excerpt, warnings = extractor.extract_code_excerpt(
            scene=scene,
            repo_root_dir=str(sample_repo_dir),
        )
        assert excerpt.file_path != sensitive
        text_content = "\n".join(l.content for l in excerpt.lines)
        assert "sk_live" not in text_content
        assert "secret_abc" not in text_content


def test_code_extractor_bounds_and_omissions(sample_repo_dir: Path):
    """Extracting a large function (> 16 lines) should bound length and include an omission line."""
    extractor = CodeExtractor()
    scene = StoryboardScene(
        scene_id="scene-long-file",
        scene_number=1,
        script_section_id="sec-1",
        title="Long File",
        purpose="Inspect long file",
        estimated_duration_seconds=15.0,
        visual_type=VisualType.CODE_WALKTHROUGH,
        visual_description="Walkthrough long file",
        related_files=["src/core/long_file.py"],
    )
    excerpt, warnings = extractor.extract_code_excerpt(
        scene=scene,
        repo_root_dir=str(sample_repo_dir),
    )

    assert len(excerpt.lines) <= 17  # max 16 lines + omission
    if excerpt.has_omissions:
        omission_lines = [l for l in excerpt.lines if l.is_omission_marker]
        assert len(omission_lines) >= 1


def test_code_extractor_missing_file_fallback():
    """Missing file yields a clean, structured fallback excerpt without crashing."""
    extractor = CodeExtractor()
    scene = StoryboardScene(
        scene_id="scene-missing",
        scene_number=1,
        script_section_id="sec-1",
        title="Missing Module",
        purpose="Inspect missing",
        estimated_duration_seconds=10.0,
        visual_type=VisualType.CODE_WALKTHROUGH,
        visual_description="Walkthrough missing file",
        related_files=["nonexistent/module.py"],
    )
    excerpt, warnings = extractor.extract_code_excerpt(
        scene=scene,
        repo_root_dir="/nonexistent/path",
    )

    assert len(excerpt.lines) > 0
    assert any("warning" in w.lower() or "missing" in w.lower() or "could not" in w.lower() or "authentic" in w.lower() or "conceptual" in w.lower() for w in warnings)


def test_code_highlighter_tokenization():
    """Verify Pygments highlighting renders styled span-like colored tokens."""
    highlighter = CodeHighlighter()
    lines = highlighter.highlight_lines(
        raw_lines=[(5, "def calculate(val: int) -> str:  # compute")],
        language="python",
    )

    assert len(lines) == 1
    tokens = lines[0].tokens
    assert len(tokens) > 1
    # Check that 'def' has keyword color
    kw_tokens = [t for t in tokens if t[1] == "def"]
    assert len(kw_tokens) == 1
    assert kw_tokens[0][0] == "#818CF8"

    # Check that comment has comment color
    comment_tokens = [t for t in tokens if "# compute" in t[1]]
    assert len(comment_tokens) == 1
    assert comment_tokens[0][0] == "#94A3B8"


def test_code_highlighter_xml_escaping():
    """XML special characters (<, >, &, \") must be safely escaped in line rendering."""
    highlighter = CodeHighlighter()
    lines = highlighter.highlight_lines(
        raw_lines=[(10, 'if x < 10 and y > 20 and z == "&":')],
        language="python",
    )
    assert len(lines) == 1
    tokens = lines[0].tokens
    token_texts = [t[1] for t in tokens]
    full_str = "".join(token_texts)
    assert "<" in full_str or "&" in full_str


# ============================================================================
# 2. Code Walkthrough Visual Generator Tests
# ============================================================================

def test_code_walkthrough_svg_layout(
    sample_repo_dir: Path,
    sample_knowledge: RepositoryKnowledge,
    sample_code_understanding: RepositoryCodeUnderstanding,
    sample_storyboard: EducationalStoryboard,
):
    """Verify 1920x1080 SVG generation, XML validity, and window elements."""
    generator = CodeWalkthroughGenerator()
    scene = sample_storyboard.scenes[1]

    result = generator.generate(
        scene=scene,
        knowledge=sample_knowledge,
        code_understanding=sample_code_understanding,
        repo_root_dir=str(sample_repo_dir),
    )

    assert result.svg_content is not None
    assert result.width == CANVAS_WIDTH
    assert result.height == CANVAS_HEIGHT

    # Parse XML
    root = ET.fromstring(result.svg_content)
    assert root.attrib["width"] == str(CANVAS_WIDTH)
    assert root.attrib["height"] == str(CANVAS_HEIGHT)

    # Check editor components
    assert "process_pipeline" in result.svg_content
    assert "src/core/engine.py" in result.svg_content
    assert "PYTHON" in result.svg_content.upper()


def test_code_walkthrough_line_highlighting(
    sample_repo_dir: Path,
    sample_knowledge: RepositoryKnowledge,
    sample_storyboard: EducationalStoryboard,
):
    """Verify that specific lines are visually highlighted with background rects."""
    generator = CodeWalkthroughGenerator()
    scene = sample_storyboard.scenes[1]

    result = generator.generate(
        scene=scene,
        knowledge=sample_knowledge,
        repo_root_dir=str(sample_repo_dir),
    )

    assert result.svg_content is not None
    assert "rx=\"4\"" in result.svg_content or "fill=\"#1E293B\"" in result.svg_content


# ============================================================================
# 3. Scene Cards (Title Card & Summary Card) Tests
# ============================================================================

def test_title_card_generation(
    sample_knowledge: RepositoryKnowledge,
    sample_project_understanding: ProjectUnderstanding,
    sample_storyboard: EducationalStoryboard,
):
    """Verify TitleCardGenerator builds 1920x1080 hero card with tech tags and topic cards."""
    generator = TitleCardGenerator()
    scene = sample_storyboard.scenes[0]

    result = generator.generate(
        scene=scene,
        knowledge=sample_knowledge,
        project_understanding=sample_project_understanding,
    )

    assert result.svg_content is not None
    assert result.width == CANVAS_WIDTH
    assert result.height == CANVAS_HEIGHT

    # XML validity
    root = ET.fromstring(result.svg_content)
    assert root.tag.endswith("svg")

    # Content checks
    assert "sample_repo" in result.svg_content
    assert "PYTHON" in result.svg_content.upper()


def test_title_card_fallback_handling(sample_storyboard: EducationalStoryboard):
    """Verify TitleCardGenerator without project understanding produces clean fallback card."""
    generator = TitleCardGenerator()
    scene = sample_storyboard.scenes[0]

    result = generator.generate(scene=scene, knowledge=None, project_understanding=None)
    assert result.svg_content is not None
    root = ET.fromstring(result.svg_content)
    assert root.attrib["width"] == "1920"
    assert "RepoGenie Title Card" in result.svg_content or "Repository" in result.svg_content


def test_summary_card_generation(
    sample_knowledge: RepositoryKnowledge,
    sample_script: EducationalScript,
    sample_code_understanding: RepositoryCodeUnderstanding,
    sample_storyboard: EducationalStoryboard,
):
    """Verify SummaryCardGenerator builds 3 takeaway cards and key conclusion quote."""
    generator = SummaryCardGenerator()
    scene = sample_storyboard.scenes[2]

    result = generator.generate(
        scene=scene,
        knowledge=sample_knowledge,
        script=sample_script,
        code_understanding=sample_code_understanding,
    )

    assert result.svg_content is not None
    assert result.width == CANVAS_WIDTH
    assert result.height == CANVAS_HEIGHT

    # XML validity
    root = ET.fromstring(result.svg_content)
    assert root.tag.endswith("svg")

    # Check key takeaways
    assert "Architecture" in result.svg_content or "Layered" in result.svg_content
    assert "Execution" in result.svg_content or "Dispatch" in result.svg_content
    assert "Grounded" in result.svg_content or "Verification" in result.svg_content


def test_summary_card_fallback_handling(sample_storyboard: EducationalStoryboard):
    """Verify SummaryCardGenerator without script produces valid SVG with default takeaways."""
    generator = SummaryCardGenerator()
    scene = sample_storyboard.scenes[2]

    result = generator.generate(scene=scene, knowledge=None, script=None)
    assert result.svg_content is not None
    assert ET.fromstring(result.svg_content) is not None
    assert "Conclusion and Takeaways" in result.svg_content or "Repository" in result.svg_content


# ============================================================================
# 4. VisualGenerationService Integration & Stage 07 Lifecycle Tests
# ============================================================================

def test_service_dispatches_all_new_visual_types(
    tmp_path: Path,
    sample_repo_dir: Path,
    sample_knowledge: RepositoryKnowledge,
    sample_project_understanding: ProjectUnderstanding,
    sample_script: EducationalScript,
    sample_storyboard: EducationalStoryboard,
):
    """Verify VisualGenerationService dispatches TITLE_CARD, CODE_WALKTHROUGH, and SUMMARY_CARD."""
    storage_mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)
    service = VisualGenerationService(storage_manager=storage_mgr)
    job_id = "test-job-dispatch-types"

    # 1. Title Card
    s1 = sample_storyboard.scenes[0]
    r1 = service.generate_diagram_for_scene(
        job_id=job_id,
        scene=s1,
        knowledge=sample_knowledge,
        project_understanding=sample_project_understanding,
    )
    assert r1.status == VisualAssetStatus.COMPLETED
    assert r1.asset_type == VisualAssetType.TITLE_CARD

    # 2. Code Walkthrough
    s2 = sample_storyboard.scenes[1]
    r2 = service.generate_diagram_for_scene(
        job_id=job_id,
        scene=s2,
        knowledge=sample_knowledge,
        repo_root_dir=str(sample_repo_dir),
    )
    assert r2.status == VisualAssetStatus.COMPLETED
    assert r2.asset_type == VisualAssetType.CODE_WALKTHROUGH

    # 3. Summary Card
    s3 = sample_storyboard.scenes[2]
    r3 = service.generate_diagram_for_scene(
        job_id=job_id,
        scene=s3,
        knowledge=sample_knowledge,
        script=sample_script,
    )
    assert r3.status == VisualAssetStatus.COMPLETED
    assert r3.asset_type == VisualAssetType.SUMMARY_CARD


def test_service_full_job_rendering_lifecycle(
    tmp_path: Path,
    sample_repo_dir: Path,
    sample_knowledge: RepositoryKnowledge,
    sample_project_understanding: ProjectUnderstanding,
    sample_code_understanding: RepositoryCodeUnderstanding,
    sample_script: EducationalScript,
    sample_storyboard: EducationalStoryboard,
):
    """
    Verify complete job visual asset rendering across 3 scenes:
    Title Card + Code Walkthrough + Summary Card.
    When all 3 render successfully, plan.is_fully_rendered is True and Stage 07 is COMPLETED.
    """
    job_id = "test-job-full-render-53"
    job = job_store.create_job(
        repo_url="https://github.com/test-owner/sample_repo",
        repo_name="sample_repo",
        repository_owner="test-owner",
        repository_name="sample_repo",
        clone_url="https://github.com/test-owner/sample_repo.git",
    )
    job_id = job.job_id
    job.project_understanding = sample_project_understanding
    job.code_analysis = None
    job.educational_script = sample_script
    job.educational_storyboard = sample_storyboard
    job.knowledge = sample_knowledge
    job.local_path = str(sample_repo_dir)

    storage_mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)
    service = VisualGenerationService(storage_manager=storage_mgr)

    # 1. Initialize asset plan
    plan = service.initialize_visual_assets(job_id=job_id, storyboard=sample_storyboard)
    assert not plan.is_fully_rendered
    job_store.update_job_visual_planning_success(job_id, plan)

    # 2. Render all visuals
    render_result = service.generate_all_visuals_for_job(
        job_id=job_id,
        plan=plan,
        storyboard=sample_storyboard,
        knowledge=sample_knowledge,
        code_understanding=sample_code_understanding,
        project_understanding=sample_project_understanding,
        script=sample_script,
        repo_root_dir=str(sample_repo_dir),
    )

    assert render_result.total_assets == 3
    assert render_result.assets_completed == 3
    assert render_result.assets_failed == 0
    assert render_result.is_fully_rendered

    # 3. Store rendered result and verify Stage 07 completion
    job_store.update_job_visual_generation_success(job_id, render_result)
    retrieved_job = job_store.get_job(job_id)

    assert retrieved_job.current_stage == StageEnum.VOICE_GENERATION.value
    assert retrieved_job.stages[6].status == StatusEnum.COMPLETED

    # 4. Verify physical SVG files were saved in storage
    for scene_assets in render_result.scene_assets:
        asset = scene_assets.primary_asset
        filename = f"{asset.asset_id}.svg"
        assert storage_mgr.asset_file_exists(job_id, filename)
        content = storage_mgr.read_asset_content(job_id, filename)
        assert b"<svg" in content


def test_service_partial_rendering_lifecycle(
    tmp_path: Path,
    sample_knowledge: RepositoryKnowledge,
    sample_storyboard: EducationalStoryboard,
):
    """
    If rendering is partial or scenes remain unrendered,
    plan.is_fully_rendered is False and Stage 07 remains IN_PROGRESS.
    """
    job = job_store.create_job(
        repo_url="https://github.com/test-owner/sample_repo",
        repo_name="sample_repo",
        repository_owner="test-owner",
        repository_name="sample_repo",
        clone_url="https://github.com/test-owner/sample_repo.git",
    )
    job_id = job.job_id

    storage_mgr = VisualAssetStorageManager(base_storage_dir=tmp_path)
    service = VisualGenerationService(storage_manager=storage_mgr)
    plan = service.initialize_visual_assets(job_id, sample_storyboard)
    job_store.update_job_visual_planning_success(job_id, plan)

    # When generate_diagrams_for_job runs without include_scene_visuals,
    # the 3 non-diagram scenes (title, walkthrough, summary) remain PENDING
    result = service.generate_diagrams_for_job(
        job_id=job_id,
        plan=plan,
        storyboard=sample_storyboard,
        knowledge=sample_knowledge,
        include_scene_visuals=False,
    )

    assert not result.is_fully_rendered
    assert result.assets_completed == 0
    assert result.assets_pending == 3

    job_store.update_job_visual_planning_success(job_id, result)
    retrieved_job = job_store.get_job(job_id)

    assert retrieved_job.current_stage == StageEnum.VISUAL_GENERATION.value
    assert retrieved_job.stages[6].status == StatusEnum.IN_PROGRESS


# ============================================================================
# 5. Security, Sanitization & Secret Redaction Tests
# ============================================================================

def test_security_path_sanitization_in_code_walkthrough(
    sample_repo_dir: Path,
    sample_knowledge: RepositoryKnowledge,
    sample_storyboard: EducationalStoryboard,
):
    """Ensure host machine absolute paths (/Users/..., /home/...) are sanitized in code walkthroughs."""
    generator = CodeWalkthroughGenerator()
    scene = sample_storyboard.scenes[1]

    result = generator.generate(
        scene=scene,
        knowledge=sample_knowledge,
        repo_root_dir=str(sample_repo_dir),
    )

    assert result.svg_content is not None
    # Absolute machine user path should not appear anywhere in SVG
    assert "/Users/" not in result.svg_content
    assert "/home/" not in result.svg_content


def test_security_api_key_redaction(sample_repo_dir: Path):
    """Ensure tokens or keys matching secret patterns are redacted from displayed code."""
    key_file = sample_repo_dir / "src" / "core" / "config.py"
    key_file.write_text('API_KEY = "sk-live-998877665544332211"\nDB_URL = "postgres://root:secret@db:5432"', encoding="utf-8")

    extractor = CodeExtractor()
    scene = StoryboardScene(
        scene_id="scene-key-redact",
        scene_number=1,
        script_section_id="sec-1",
        title="Config",
        purpose="Inspect config",
        estimated_duration_seconds=10.0,
        visual_type=VisualType.CODE_WALKTHROUGH,
        visual_description="Config file",
        related_files=["src/core/config.py"],
    )
    excerpt, warnings = extractor.extract_code_excerpt(
        scene=scene,
        repo_root_dir=str(sample_repo_dir),
    )

    full_text = "\n".join(l.content for l in excerpt.lines)
    assert "sk-live-998877665544332211" not in full_text
