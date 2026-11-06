"""
Food_ordering_WebAPP Full Pipeline Verification Suite (Mocked AI Mode).

Tests the complete repository analysis, project understanding, code understanding,
workflow understanding, educational script generation, storyboard generation,
narration audio synthesis, subtitle caption generation, assembly input packaging,
and FFmpeg scene video rendering for the Food_ordering_WebAPP repository.

All external Groq LLM and ElevenLabs TTS network calls are strictly mocked.
No paid external API calls are made during execution.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import RepositoryKnowledge, StatusEnum
from app.services.storage.job_store import job_store
from app.services.ai.exceptions import AIError
from app.services.ai.llm_manager import LLMManager
from app.services.ai.schemas import LLMResponse
from app.services.ai.project_understanding import project_understanding_analyzer
from app.services.ai.code_understanding import code_understanding_analyzer
from app.services.ai.workflow_understanding import workflow_understanding_analyzer
from app.services.ai.script_generation import (
    EducationalScript,
    EducationalScriptAnalyzer,
    ScriptSection,
    SectionPurpose,
)
from app.services.ai.storyboard_generation import (
    EducationalStoryboard,
    EducationalStoryboardAnalyzer,
    StoryboardScene,
    VisualType,
    NarrationReference,
)
from app.services.repo.analyzer import repo_analyzer_service
from app.services.repo.architecture_analyzer import architecture_analyzer_service
from app.services.repo.code_parser import code_parser_service
from app.services.repo.knowledge_builder import knowledge_builder_service
from app.services.video.assembly.ffmpeg_manager import ffmpeg_manager
from app.services.video.assembly.scene_service import SceneRenderService
from app.services.video.assembly.final_service import FinalVideoAssemblyService
from app.services.video.assembly.storage import VideoStorageManager
from app.services.video.assembly.schemas import (
    SceneRenderAsset,
    SceneRenderResult,
    SceneRenderStatus,
    VideoRenderConfiguration,
    VideoRenderResult,
    VideoRenderStatus,
)
from app.services.video.assembly_input.service import AssemblyInputService
from app.services.video.assembly_input.validator import AssemblyPreflightValidator
from app.services.video.assembly_input.schemas import AssemblyReadinessStatus
from app.services.video.captions.service import CaptionService
from app.services.video.captions.caption_storage import CaptionAssetStorageManager
from app.services.video.narration import (
    AudioAssetStorageManager,
    ElevenLabsTTSProvider,
    NarrationAssetStatus,
    NarrationService,
)
from app.services.video.visual_generation.schemas import (
    SceneVisualAssets,
    VisualAsset,
    VisualAssetStatus,
    VisualGenerationResult,
    VisualGenerationStatus,
)

FOOD_ORDERING_REPO_PATH = Path("storage/repos/cf13925b-34a1-4833-95dd-aa076d1af1bc")


def create_test_mp3_bytes(num_frames: int = 40) -> bytes:
    """Generates synthetic valid MPEG-1 Layer III audio frame bytes."""
    id3 = b"ID3\x03\x00\x00\x00\x00\x00\x0a" + b"x" * 10
    frame_body = b"\x00" * 413
    frame = b"\xff\xfb\x90\x00" + frame_body
    return id3 + (frame * num_frames)


SAMPLE_VALID_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" width="1920" height="1080">
  <rect width="1920" height="1080" fill="#0f172a"/>
  <text x="960" y="540" fill="#38bdf8" font-size="52" text-anchor="middle" font-family="sans-serif">
    Food Ordering WebApp - Scene Preview
  </text>
</svg>"""


@pytest.fixture(scope="module")
def food_ordering_knowledge() -> RepositoryKnowledge:
    """Runs genuine static repository analysis on the local Food_ordering_WebAPP repository."""
    if not FOOD_ORDERING_REPO_PATH.is_dir():
        pytest.skip("Food_ordering_WebAPP local repository not found at expected storage path.")

    job_id = "job-food-ordering-test"
    repo_name = "Food_ordering_WebAPP"
    repo_owner = "ritchi-e"
    repo_url = "https://github.com/ritchi-e/Food_ordering_WebAPP.git"
    local_path = str(FOOD_ORDERING_REPO_PATH)

    # 1. Static structure analysis
    analysis = repo_analyzer_service.analyze_repository(
        job_id=job_id,
        repo_name=repo_name,
        local_path=local_path,
    )

    # 2. AST Parsing
    parsed_code = code_parser_service.parse_repository(
        job_id=job_id,
        repo_name=repo_name,
        local_path=local_path,
        analysis=analysis,
    )

    # 3. Architecture analysis
    arch = architecture_analyzer_service.analyze_architecture(
        job_id=job_id,
        repo_name=repo_name,
        parsed_repo=parsed_code,
        analysis=analysis,
        local_path=local_path,
    )

    # 4. Consolidated Knowledge
    knowledge = knowledge_builder_service.build_knowledge(
        job_id=job_id,
        repo_name=repo_name,
        repo_owner=repo_owner,
        repo_url=repo_url,
        local_path=local_path,
        size_mb=12.5,
        file_count=analysis.statistics.total_files,
        analysis=analysis,
        parsed_repo=parsed_code,
        architecture=arch,
    )
    return knowledge


def test_food_ordering_static_analysis_and_knowledge(food_ordering_knowledge: RepositoryKnowledge):
    """Verifies static repository analysis extracts Python/JS structure accurately without AI."""
    k = food_ordering_knowledge
    assert k.repository.name == "Food_ordering_WebAPP"
    assert k.repository.owner == "ritchi-e"
    assert k.repository.file_count >= 100

    lang_names = [lang.name for lang in k.technology_stack.languages]
    assert "Python" in lang_names
    assert "JavaScript" in lang_names

    framework_names = [f.name for f in k.technology_stack.frameworks]
    assert "Django" in framework_names or "Next.js" in framework_names or "React" in framework_names


@pytest.mark.anyio
async def test_food_ordering_understandings_fallback(food_ordering_knowledge: RepositoryKnowledge):
    """Verifies deterministic understanding modules analyze Food_ordering_WebAPP without live Groq API."""
    k = food_ordering_knowledge
    proj = project_understanding_analyzer.create_rule_based_fallback(knowledge=k)
    assert proj.identity.name is not None
    assert proj.is_fallback is True

    code = code_understanding_analyzer.create_rule_based_fallback(knowledge=k, project_understanding=proj)
    assert len(code.components) > 0
    assert code.is_fallback is True

    wf = workflow_understanding_analyzer.create_deterministic_fallback(knowledge=k)
    assert len(wf.workflows) > 0
    assert wf.is_fallback is True


@pytest.mark.anyio
async def test_food_ordering_script_generation_mocked(food_ordering_knowledge: RepositoryKnowledge):
    """Verifies grounded 4-section educational script generation for Food_ordering_WebAPP with mocked Groq response."""
    k = food_ordering_knowledge
    proj = project_understanding_analyzer.create_rule_based_fallback(knowledge=k)
    code = code_understanding_analyzer.create_rule_based_fallback(knowledge=k, project_understanding=proj)
    wf = workflow_understanding_analyzer.create_deterministic_fallback(knowledge=k)

    mock_script_dict = {
        "script_id": "script-food-ordering",
        "repository_name": "ritchi-e/Food_ordering_WebAPP",
        "title": "Architecture of Food Ordering WebApp",
        "introduction": "Food Ordering WebApp is a full-stack platform built with Django REST Framework and Next.js.",
        "intended_audience": ["Developers", "Students"],
        "learning_objectives": [
            "Understand full-stack food ordering architecture",
            "Trace order dispatching and menu API requests",
        ],
        "total_estimated_duration_seconds": 72.0,
        "sections": [
            {
                "section_id": "sec-1-hook",
                "order": 1,
                "title": "Introduction and Core Problem",
                "purpose": "hook",
                "narration_text": (
                    "Modern food delivery applications require seamless coordination between customer cart interactions, "
                    "restaurant menu updates, and reliable order dispatching. Food Ordering WebApp tackles this with a "
                    "decoupled architecture built in Python and JavaScript."
                ),
                "estimated_duration_seconds": 14.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "Food Ordering WebApp coordinates customer orders with restaurant dispatching",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": "Let us examine the core architecture that makes this possible.",
            },
            {
                "section_id": "sec-2-arch",
                "order": 2,
                "title": "Decoupled Architecture and Core Stack",
                "purpose": "architecture_overview",
                "narration_text": (
                    "The backend leverages the Django REST Framework to expose modular API endpoints, while the frontend "
                    "uses Next.js and React for interactive menus and cart state management. Middleware components enforce "
                    "authentication and request isolation."
                ),
                "estimated_duration_seconds": 15.0,
                "evidence_ids": ["TECH-1", "PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "The project uses Django REST Framework on the backend and Next.js on the frontend",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["TECH-1"],
                    }
                ],
                "transition_to_next": "Now, let us examine the core subsystems and components.",
            },
            {
                "section_id": "sec-3-components",
                "order": 3,
                "title": "Core Components and Subsystems",
                "purpose": "component_deep_dive",
                "narration_text": (
                    "The application separates data access repositories from client state handlers. The menu subsystem "
                    "manages real-time item availability and pricing, while dedicated order serializers validate incoming customer checkout requests."
                ),
                "estimated_duration_seconds": 14.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "The menu subsystem manages item availability while order serializers validate requests",
                        "grounding_status": "inferred",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": "Next, let us trace how an order moves through the system.",
            },
            {
                "section_id": "sec-4-workflow",
                "order": 4,
                "title": "Order Processing and Checkout Workflow",
                "purpose": "workflow",
                "narration_text": (
                    "When a user places an order, the Next.js client dispatches an HTTP POST payload to the order endpoint. "
                    "Django validates the cart items, calculates totals, checks authentication credentials, and persists the "
                    "order record before returning an order confirmation response."
                ),
                "estimated_duration_seconds": 15.0,
                "evidence_ids": ["WF-1"],
                "claims": [
                    {
                        "statement": "Order requests are validated and processed through Django API endpoints",
                        "grounding_status": "inferred",
                        "evidence_ids": ["WF-1"],
                    }
                ],
                "transition_to_next": "Finally, let us review the key implementation highlights.",
            },
            {
                "section_id": "sec-5-conclusion",
                "order": 5,
                "title": "Key Implementation Highlights",
                "purpose": "conclusion",
                "narration_text": (
                    "By separating frontend state management from backend API business logic, the repository maintains clean "
                    "boundaries and modularity. This structure demonstrates a production-style pattern for full-stack food delivery applications."
                ),
                "estimated_duration_seconds": 14.0,
                "evidence_ids": ["PROJ-IDENTITY"],
                "claims": [
                    {
                        "statement": "The modular architecture separates client state from server business logic",
                        "grounding_status": "confirmed",
                        "evidence_ids": ["PROJ-IDENTITY"],
                    }
                ],
                "transition_to_next": None,
            },
        ],
        "conclusion": "Food Ordering WebApp provides a clean full-stack reference implementation.",
        "limitations": [],
    }

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(
            text=json.dumps(mock_script_dict),
            provider="groq",
            model="openai/gpt-oss-120b",
        )
    )

    analyzer = EducationalScriptAnalyzer(llm_manager=mock_llm)
    script = await analyzer.generate_script(
        job_id="job-food-ordering-script",
        knowledge=k,
        project_understanding=proj,
        code_understanding=code,
        workflow_understanding=wf,
        local_path=str(FOOD_ORDERING_REPO_PATH),
    )

    assert script.script_id == "script-food-ordering"
    assert len(script.sections) == 5
    assert script.total_estimated_duration_seconds == 72.0
    assert script.total_word_count >= 130
    assert all(len(s.narration_text.split()) >= 25 for s in script.sections)


@pytest.mark.anyio
async def test_food_ordering_complete_pipeline_mocked(tmp_path: Path, food_ordering_knowledge: RepositoryKnowledge):
    """
    Executes the entire downstream pipeline for Food_ordering_WebAPP with mocked AI:
    Script -> Storyboard -> Narration Synthesis -> Subtitle Captions -> Assembly Input -> Scene Video Rendering.
    """
    k = food_ordering_knowledge
    job_id = "job-food-pipeline-e2e"

    # --- 1. Prepare Grounded Script ---
    script = EducationalScript(
        script_id="script-food-app",
        repository_name="ritchi-e/Food_ordering_WebAPP",
        title="Food Ordering WebApp Architectural Walkthrough",
        introduction="A full-stack food ordering platform built with Django and Next.js.",
        learning_objectives=["Understand food ordering architecture", "Trace order flow"],
        total_estimated_duration_seconds=68.0,
        conclusion="Demonstrates decoupled full-stack architecture.",
        sections=[
            ScriptSection(
                section_id="sec-1",
                order=1,
                title="System Overview",
                purpose=SectionPurpose.HOOK,
                narration_text="Food Ordering WebApp coordinates customer menu browsing, real-time cart updates, and secure order placement.",
                estimated_duration_seconds=16.0,
            ),
            ScriptSection(
                section_id="sec-2",
                order=2,
                title="Full-Stack Architecture",
                purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
                narration_text="The backend provides Django REST endpoints while the Next.js frontend delivers responsive client views.",
                estimated_duration_seconds=16.0,
            ),
            ScriptSection(
                section_id="sec-3",
                order=3,
                title="Order Dispatch Workflow",
                purpose=SectionPurpose.WORKFLOW,
                narration_text="When an order is submitted, the payload is validated, authentication is confirmed, and the record is stored.",
                estimated_duration_seconds=18.0,
            ),
            ScriptSection(
                section_id="sec-4",
                order=4,
                title="Implementation Summary",
                purpose=SectionPurpose.CONCLUSION,
                narration_text="Clean architectural boundaries make the application scalable, testable, and maintainable across all layers.",
                estimated_duration_seconds=18.0,
            ),
        ],
    )

    # --- 2. Prepare Storyboard ---
    storyboard = EducationalStoryboard(
        storyboard_id="sb-food-app",
        script_id="script-food-app",
        title="Food Ordering WebApp Storyboard",
        total_estimated_duration_seconds=68.0,
        scenes=[
            StoryboardScene(
                scene_id="scene-1",
                scene_number=1,
                script_section_id="sec-1",
                title="Title Card & Overview",
                purpose="Hook",
                estimated_duration_seconds=16.0,
                visual_type=VisualType.TITLE_CARD,
                visual_description="Title view of Food Ordering WebApp",
                narration=NarrationReference(
                    script_section_id="sec-1",
                    excerpt="Food Ordering WebApp coordinates customer menu browsing, real-time cart updates, and secure order placement.",
                ),
            ),
            StoryboardScene(
                scene_id="scene-2",
                scene_number=2,
                script_section_id="sec-2",
                title="Architecture Diagram",
                purpose="Architecture",
                estimated_duration_seconds=16.0,
                visual_type=VisualType.ARCHITECTURE_DIAGRAM,
                visual_description="Django backend and Next.js frontend diagram",
                narration=NarrationReference(
                    script_section_id="sec-2",
                    excerpt="The backend provides Django REST endpoints while the Next.js frontend delivers responsive client views.",
                ),
            ),
            StoryboardScene(
                scene_id="scene-3",
                scene_number=3,
                script_section_id="sec-3",
                title="Order Workflow",
                purpose="Workflow",
                estimated_duration_seconds=18.0,
                visual_type=VisualType.WORKFLOW_DIAGRAM,
                visual_description="Order submission and validation flow",
                narration=NarrationReference(
                    script_section_id="sec-3",
                    excerpt="When an order is submitted, the payload is validated, authentication is confirmed, and the record is stored.",
                ),
            ),
            StoryboardScene(
                scene_id="scene-4",
                scene_number=4,
                script_section_id="sec-4",
                title="Summary Card",
                purpose="Summary",
                estimated_duration_seconds=18.0,
                visual_type=VisualType.SUMMARY_CARD,
                visual_description="Key architectural takeaways",
                narration=NarrationReference(
                    script_section_id="sec-4",
                    excerpt="Clean architectural boundaries make the application scalable, testable, and maintainable across all layers.",
                ),
            ),
        ],
    )

    # --- 3. Narration Generation (Mocked ElevenLabs) ---
    audio_storage = AudioAssetStorageManager(base_storage_dir=str(tmp_path))
    provider = MagicMock(spec=ElevenLabsTTSProvider)
    provider.voice_id = "test-alice-voice"
    provider.model_id = "eleven_multilingual_v2"
    provider.validate_configuration = MagicMock(return_value=None)
    mock_audio = create_test_mp3_bytes(num_frames=35)
    provider.synthesize = AsyncMock(return_value=mock_audio)

    narration_service = NarrationService(provider=provider, storage=audio_storage)
    narration_result = await narration_service.generate_narration_for_job(
        job_id=job_id,
        storyboard=storyboard,
        script=script,
    )

    assert narration_result.status.value == "completed"
    assert len(narration_result.assets) == 4
    assert narration_result.scenes_completed == 4
    # All 4 scenes have non-empty, distinct narration texts
    distinct_texts = {a.narration_text for a in narration_result.assets}
    assert len(distinct_texts) == 4
    assert provider.synthesize.call_count == 4

    # --- 4. Subtitle Caption Generation ---
    caption_storage = CaptionAssetStorageManager(base_dir=tmp_path)
    caption_service = CaptionService(storage=caption_storage)
    caption_result = caption_service.generate_captions_for_job(
        job_id=job_id,
        storyboard=storyboard,
        narration=narration_result,
        script=script,
    )

    assert caption_result.status.value == "completed"
    assert len(caption_result.scene_assets) == 4
    assert caption_result.full_srt_file_path is not None
    assert caption_result.full_vtt_file_path is not None
    # Cumulative full-video timing progression check
    assert caption_result.scene_assets[0].cumulative_start_seconds == 0.0
    assert caption_result.scene_assets[1].cumulative_start_seconds > 0.0
    assert caption_result.scene_assets[2].cumulative_start_seconds > caption_result.scene_assets[1].cumulative_start_seconds

    # --- 5. Visual Assets Preparation (Synthetic SVGs) ---
    vis_dir = tmp_path / "jobs" / job_id / "visuals"
    vis_dir.mkdir(parents=True, exist_ok=True)
    scene_assets = []
    for sc in storyboard.scenes:
        svg_file = vis_dir / f"visual_{sc.scene_id}.svg"
        svg_file.write_text(SAMPLE_VALID_SVG, encoding="utf-8")
        vis_asset = VisualAsset(
            asset_id=f"vis_{sc.scene_id}",
            job_id=job_id,
            scene_id=sc.scene_id,
            scene_number=sc.scene_number,
            visual_type=sc.visual_type,
            storage_path=f"jobs/{job_id}/visuals/visual_{sc.scene_id}.svg",
            status=VisualAssetStatus.COMPLETED,
            width=1920,
            height=1080,
            file_size_bytes=len(SAMPLE_VALID_SVG),
        )
        sva = SceneVisualAssets(
            scene_id=sc.scene_id,
            scene_number=sc.scene_number,
            scene_title=sc.title,
            visual_type=sc.visual_type,
            visual_description=sc.visual_description,
            primary_asset=vis_asset,
            status=VisualGenerationStatus.COMPLETED,
        )
        scene_assets.append(sva)

    visual_result = VisualGenerationResult(
        job_id=job_id,
        storyboard_id=storyboard.storyboard_id,
        script_id=script.script_id,
        storage_directory=f"jobs/{job_id}/visuals",
        scene_assets=scene_assets,
        total_scenes=4,
        scenes_completed=4,
        total_assets=4,
        assets_completed=4,
        status=VisualGenerationStatus.COMPLETED,
    )

    # --- 6. Video Assembly Input Packaging ---
    validator = AssemblyPreflightValidator(base_storage_dir=tmp_path)
    assembly_service = AssemblyInputService(validator=validator)
    assembly_input = assembly_service.build_assembly_input(
        job_id=job_id,
        repo_name="ritchi-e/Food_ordering_WebAPP",
        storyboard=storyboard,
        visual_generation=visual_result,
        narration=narration_result,
        captions=caption_result,
    )

    assert assembly_input.job_id == job_id
    assert len(assembly_input.scenes) == 4
    assert assembly_input.readiness_report.status in (
        AssemblyReadinessStatus.READY,
        AssemblyReadinessStatus.READY_WITH_WARNINGS,
    )

    # --- 7. Scene Video Rendering with FFmpeg ---
    if ffmpeg_manager.resolve_binary() is not None:
        video_storage = VideoStorageManager(base_storage_dir=tmp_path)
        scene_service = SceneRenderService(storage_mgr=video_storage)
        config = VideoRenderConfiguration()
        rendered_assets = []
        for sc in assembly_input.scenes:
            ra = scene_service._render_individual_scene(
                job_id=job_id,
                scene=sc,
                config=config,
                refresh=True,
            )
            assert ra.status == SceneRenderStatus.COMPLETED
            assert ra.actual_duration_seconds > 0.0
            rendered_assets.append(ra)

        # Register in JobStore
        job = job_store.create_job(
            repo_url="https://github.com/ritchi-e/Food_ordering_WebAPP",
            repo_name="ritchi-e/Food_ordering_WebAPP",
            repository_owner="ritchi-e",
            repository_name="Food_ordering_WebAPP",
            clone_url="https://github.com/ritchi-e/Food_ordering_WebAPP.git",
        )
        job.job_id = job_id
        job_store._jobs[job_id] = job
        job.assembly_input = assembly_input
        job_store.update_job_scene_renders_completed(
            job_id,
            SceneRenderResult(
                job_id=job_id,
                total_scenes=4,
                completed_scenes=4,
                failed_scenes=0,
                is_complete=True,
                scenes=rendered_assets,
            ),
        )

        # --- 8. Final Video Assembly with FFmpeg ---
        final_assembly_svc = FinalVideoAssemblyService(storage_mgr=video_storage)
        final_result = final_assembly_svc.assemble_video(job_id=job_id, refresh=True)

        assert final_result.status == VideoRenderStatus.COMPLETED
        assert final_result.duration_seconds > 3.0
        assert final_result.resolution == "1920x1080"
        assert final_result.video_codec == "h264"
        assert final_result.audio_codec == "aac"

        # Verify Stage 09 completion
        assert job.stages[8].status == StatusEnum.COMPLETED
        assert job.status == StatusEnum.COMPLETED
        assert job.progress_percentage == 100
        assert job.result is not None
        assert f"/api/v1/jobs/{job_id}/video/file" in job.result.video_url
