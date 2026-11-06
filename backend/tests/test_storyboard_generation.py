"""
Milestone 4, Phase 3 — AI-Powered Storyboard Generation Tests.

Covers:
1. Valid storyboard generation.
2. Multiple scenes associated with one script section.
3. Missing optional understanding outputs.
4. Invalid script-section references and missing section recovery.
5. Incorrect narration references and excerpt handling.
6. Scene ordering and numbering enforcement.
7. Total and per-section duration mismatches.
8. Deterministic duration reconciliation.
9. Unsupported architecture relationships / fabricated components.
10. Fabricated file paths and workflow references.
11. Invalid or unsupported on-screen text.
12. Static-versus-runtime claims rejected.
13. Malformed JSON and limited repair pass.
14. Provider errors and timeouts (no fabricated storyboard).
15. Token usage and generation metadata.
16. Prompt-size limits, sensitive file exclusions, and secret redaction.
17. JSON serialization and round-tripping.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.services.ai.exceptions import (
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIProviderUnavailableError,
    AITimeoutError,
)
from app.services.ai.llm_manager import LLMManager
from app.services.ai.project_understanding.schemas import EvidenceReference
from app.services.ai.schemas import LLMResponse, TokenUsageRecord
from app.services.ai.script_generation.schemas import (
    EducationalScript,
    GroundedClaim,
    GroundingStatus,
    ScriptSection,
    SectionPurpose,
    UnderstandingSource,
    VideoFormatSpec,
)
from app.services.ai.storyboard_generation import (
    EducationalStoryboard,
    EducationalStoryboardAnalyzer,
    NarrationReference,
    StoryboardEvidenceBuilder,
    StoryboardGenerationError,
    StoryboardScene,
    StoryboardValidator,
    VisualType,
)
from tests.test_script_generation import (
    make_code_understanding,
    make_project_understanding,
    make_repository_knowledge,
    make_workflow_understanding,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def make_test_script() -> EducationalScript:
    """Builds a verified 75.0s EducationalScript with 5 sections."""
    core_ev = EvidenceReference(
        file_path="src/click/core.py",
        line_start=10,
        line_end=50,
        evidence_type="code",
        is_valid=True,
        path_verified=True,
    )
    readme_ev = EvidenceReference(
        file_path="README.md",
        line_start=1,
        line_end=30,
        evidence_type="readme",
        is_valid=True,
        path_verified=True,
    )
    sections = [
        ScriptSection(
            section_id="sec-1-hook",
            order=1,
            title="Introduction to Click",
            purpose=SectionPurpose.HOOK,
            narration_text="Click is a Python package for creating composable command-line interfaces.",
            estimated_duration_seconds=15.0,
            evidence=[readme_ev],
            claims=[
                GroundedClaim(
                    statement="Click builds command-line tools using Python decorators.",
                    grounding_status=GroundingStatus.CONFIRMED,
                    evidence=[core_ev],
                )
            ],
            transition_to_next="Let's look at the overall architecture.",
        ),
        ScriptSection(
            section_id="sec-2-arch",
            order=2,
            title="Layered Architecture",
            purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
            narration_text="Click separates decorators, context creation, and callback invocation.",
            estimated_duration_seconds=15.0,
            evidence=[core_ev],
            transition_to_next="Now let's examine the core components.",
        ),
        ScriptSection(
            section_id="sec-3-comp",
            order=3,
            title="Command Engine & Decorators",
            purpose=SectionPurpose.COMPONENT_DEEP_DIVE,
            narration_text="The Command Execution Engine manages context while decorators wrap user functions.",
            estimated_duration_seconds=18.0,
            evidence=[core_ev],
            transition_to_next="Next, let's trace command execution.",
        ),
        ScriptSection(
            section_id="sec-4-wf",
            order=4,
            title="Execution Workflow",
            purpose=SectionPurpose.WORKFLOW,
            narration_text="When a command executes, arguments are parsed, converted, and forwarded to the callback.",
            estimated_duration_seconds=15.0,
            evidence=[core_ev],
            transition_to_next="Finally, let's review what we learned.",
        ),
        ScriptSection(
            section_id="sec-5-outro",
            order=5,
            title="Summary and Conclusion",
            purpose=SectionPurpose.CONCLUSION,
            narration_text="Click makes building complex command-line interfaces modular and testable.",
            estimated_duration_seconds=12.0,
            evidence=[readme_ev],
            transition_to_next=None,
        ),
    ]
    return EducationalScript(
        script_id="script-click-75s",
        repository_name="pallets/click",
        title="Inside Click CLI",
        introduction="Click is a Python package for composable command-line tools.",
        learning_objectives=["Understand Click decorators", "Trace command execution flow"],
        total_estimated_duration_seconds=75.0,
        sections=sections,
        conclusion="Click provides an extensible architecture for CLIs.",
        evidence=[readme_ev],
    )


def make_valid_llm_storyboard_dict(script_id: str = "script-click-75s") -> dict:
    """Builds a realistic raw LLM storyboard response covering all 5 script sections."""
    return {
        "storyboard_id": "sb-click-75s",
        "script_id": script_id,
        "title": "Inside Click CLI Storyboard",
        "total_estimated_duration_seconds": 75.0,
        "video_format": {"orientation": "landscape", "aspect_ratio": "16:9"},
        "scenes": [
            {
                "scene_id": "scene-1",
                "scene_number": 1,
                "script_section_id": "sec-1-hook",
                "title": "Title & Hook",
                "purpose": "Introduce Click and display title card",
                "estimated_duration_seconds": 15.0,
                "visual_type": "title_card",
                "visual_description": "Clean title card with Click logo and subtitle 'Composable CLIs in Python'.",
                "on_screen_text": ["Inside Click CLI", "Composable Python CLIs"],
                "narration": {
                    "script_section_id": "sec-1-hook",
                    "excerpt": "Click is a Python package for creating composable command-line interfaces.",
                },
                "layout_hint": "centered_hero",
                "related_files": ["README.md"],
                "transition_to_next": "Crossfade to architecture diagram",
            },
            {
                "scene_id": "scene-2",
                "scene_number": 2,
                "script_section_id": "sec-2-arch",
                "title": "Layered CLI Architecture",
                "purpose": "Show high-level architectural layers",
                "estimated_duration_seconds": 15.0,
                "visual_type": "architecture_diagram",
                "visual_description": "Three horizontal layers: Decorator API -> Core Execution Engine -> Parameter Parsers.",
                "on_screen_text": ["Decorator API", "Command Engine", "Option Parsers"],
                "narration": {"script_section_id": "sec-2-arch", "excerpt": None},
                "layout_hint": "diagram_flow",
                "related_files": ["src/click/core.py"],
                "transition_to_next": "Pan right to component view",
            },
            {
                "scene_id": "scene-3",
                "scene_number": 3,
                "script_section_id": "sec-3-comp",
                "title": "Command Engine & Decorators",
                "purpose": "Show Command Execution Engine and Decorator Layer collaboration",
                "estimated_duration_seconds": 18.0,
                "visual_type": "component_diagram",
                "visual_description": "Split screen: left shows @click.command decorator wrapping function, right shows Command object.",
                "on_screen_text": ["@click.command", "Command Engine", "Context Management"],
                "narration": {"script_section_id": "sec-3-comp", "excerpt": None},
                "layout_hint": "split_screen",
                "related_files": ["src/click/core.py", "src/click/decorators.py"],
                "transition_to_next": "Wipe to execution flow animation",
            },
            {
                "scene_id": "scene-4",
                "scene_number": 4,
                "script_section_id": "sec-4-wf",
                "title": "Execution Workflow",
                "purpose": "Illustrate statically traced command execution pipeline",
                "estimated_duration_seconds": 15.0,
                "visual_type": "workflow_diagram",
                "visual_description": "Animated workflow path: CLI args -> Context parsing -> Parameter conversion -> Callback invocation.",
                "on_screen_text": ["Parse Args", "Convert Types", "Invoke Callback"],
                "narration": {"script_section_id": "sec-4-wf", "excerpt": None},
                "layout_hint": "diagram_flow",
                "related_files": ["src/click/core.py"],
                "transition_to_next": "Cut to final summary",
            },
            {
                "scene_id": "scene-5",
                "scene_number": 5,
                "script_section_id": "sec-5-outro",
                "title": "Summary & Takeaways",
                "purpose": "Summarize key architectural benefits",
                "estimated_duration_seconds": 12.0,
                "visual_type": "summary_card",
                "visual_description": "Summary card with three key takeaways: composability, clean abstractions, and robust parsing.",
                "on_screen_text": ["Composable", "Separation of Concerns", "Extensible"],
                "narration": {"script_section_id": "sec-5-outro", "excerpt": None},
                "layout_hint": "summary_grid",
                "related_files": ["README.md"],
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
            latency_ms=350.0,
            token_usage=TokenUsageRecord(
                prompt_tokens=850,
                completion_tokens=420,
                total_tokens=1270,
                provider=provider,
                model=model,
                operation="storyboard_generation",
                job_id="job-test-sb",
            ),
        )
    )
    return mock_llm


# ---------------------------------------------------------------------------
# 1. Valid storyboard generation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_valid_storyboard_generation():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    raw_payload = make_valid_llm_storyboard_dict(script.script_id)

    mock_llm = make_mock_llm(json.dumps(raw_payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-sb-001",
        script=script,
        knowledge=knowledge,
        project_understanding=make_project_understanding(),
        code_understanding=make_code_understanding(),
        workflow_understanding=make_workflow_understanding(),
    )

    assert isinstance(storyboard, EducationalStoryboard)
    assert storyboard.script_id == script.script_id
    assert storyboard.total_estimated_duration_seconds == script.total_estimated_duration_seconds
    assert len(storyboard.scenes) == 5
    assert [s.scene_number for s in storyboard.scenes] == [1, 2, 3, 4, 5]
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 2. Multiple scenes associated with one script section
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_multiple_scenes_associated_with_one_script_section():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    # Split section 3 (18.0s) into two distinct scenes: 3a (8.0s) and 3b (10.0s)
    payload["scenes"] = [
        payload["scenes"][0],
        payload["scenes"][1],
        {
            "scene_id": "scene-3a",
            "scene_number": 3,
            "script_section_id": "sec-3-comp",
            "title": "Decorator Syntax",
            "purpose": "Focus on the @click.command decorator syntax",
            "estimated_duration_seconds": 8.0,
            "visual_type": "code_walkthrough",
            "visual_description": "Code snippet highlighting @click.command and @click.option.",
            "on_screen_text": ["Decorator API"],
            "narration": {
                "script_section_id": "sec-3-comp",
                "excerpt": "decorators wrap user functions",
            },
            "transition_to_next": "Pan right to Context Engine",
        },
        {
            "scene_id": "scene-3b",
            "scene_number": 4,
            "script_section_id": "sec-3-comp",
            "title": "Context and Command Engine",
            "purpose": "Focus on internal Context lifecycle",
            "estimated_duration_seconds": 10.0,
            "visual_type": "component_diagram",
            "visual_description": "Box diagram of Context and Command objects.",
            "on_screen_text": ["Command Engine", "Context State"],
            "narration": {
                "script_section_id": "sec-3-comp",
                "excerpt": "The Command Execution Engine manages context",
            },
            "transition_to_next": "Wipe to workflow view",
        },
        payload["scenes"][3],
        payload["scenes"][4],
    ]

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-multi-scene",
        script=script,
        knowledge=knowledge,
    )

    assert len(storyboard.scenes) == 6
    sec3_scenes = [s for s in storyboard.scenes if s.script_section_id == "sec-3-comp"]
    assert len(sec3_scenes) == 2
    assert sec3_scenes[0].scene_number == 3
    assert sec3_scenes[1].scene_number == 4
    assert sum(s.estimated_duration_seconds for s in sec3_scenes) == pytest.approx(18.0)
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 3. Missing optional understanding outputs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_missing_optional_understanding_outputs_handled_gracefully():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    # Only script and RepositoryKnowledge provided (no Project/Code/Workflow understandings)
    storyboard = await analyzer.generate_storyboard(
        job_id="job-missing-outputs",
        script=script,
        knowledge=knowledge,
        project_understanding=None,
        code_understanding=None,
        workflow_understanding=None,
    )

    assert storyboard.metadata.source_understandings == [UnderstandingSource.REPOSITORY_KNOWLEDGE]
    assert set(storyboard.metadata.missing_understandings) == {
        UnderstandingSource.PROJECT_UNDERSTANDING,
        UnderstandingSource.CODE_UNDERSTANDING,
        UnderstandingSource.WORKFLOW_UNDERSTANDING,
    }
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 4. Invalid script-section references and missing section recovery
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_invalid_script_section_reference_and_missing_section_recovered():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    # Scene 2 references a completely non-existent section; section 5 is omitted entirely
    payload["scenes"][1]["script_section_id"] = "non-existent-section-id"
    payload["scenes"] = payload["scenes"][:4]  # omit section 5

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-invalid-sec-ref",
        script=script,
        knowledge=knowledge,
    )

    # The missing section 2 and section 5 must have recovered default grounded scenes
    covered_secs = {s.script_section_id for s in storyboard.scenes}
    assert covered_secs == {s.section_id for s in script.sections}
    assert any("non-existent-section-id" in w for w in storyboard.validation_warnings)
    assert any("was missing from generated scenes" in w for w in storyboard.validation_warnings)
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 5. Incorrect narration references and excerpt handling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_incorrect_narration_references_and_excerpts_sanitized():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    # Narration references a mismatching section ID, and an excerpt not found in section text
    payload["scenes"][0]["narration"] = {
        "script_section_id": "sec-99-wrong",
        "excerpt": "This sentence was completely fabricated and is not in narration text",
    }

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-narration-ref",
        script=script,
        knowledge=knowledge,
    )

    sc1 = storyboard.scenes[0]
    # script_section_id on narration must be bound to scene's script_section_id
    assert sc1.narration.script_section_id == "sec-1-hook"
    # Unmatched excerpt should be cleaned or nullified
    assert sc1.narration.excerpt is None
    assert any("narration excerpt did not appear" in w for w in storyboard.validation_warnings)
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 6. Scene ordering and numbering enforcement
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_scene_ordering_and_numbering_enforced():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    # Scramble the list order and scene numbers
    payload["scenes"] = [
        payload["scenes"][3],  # sec-4
        payload["scenes"][0],  # sec-1
        payload["scenes"][2],  # sec-3
        payload["scenes"][1],  # sec-2
        payload["scenes"][4],  # sec-5
    ]
    for s in payload["scenes"]:
        s["scene_number"] = 999

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-order-enforce",
        script=script,
        knowledge=knowledge,
    )

    # Scenes must be ordered strictly by script section order 1..5
    assert [s.script_section_id for s in storyboard.scenes] == [
        "sec-1-hook",
        "sec-2-arch",
        "sec-3-comp",
        "sec-4-wf",
        "sec-5-outro",
    ]
    assert [s.scene_number for s in storyboard.scenes] == [1, 2, 3, 4, 5]
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 7. Total and per-section duration mismatches & deterministic reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deterministic_duration_reconciliation():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    # Provide mismatched scene durations that do not sum to section or total durations
    payload["scenes"][0]["estimated_duration_seconds"] = 30.0  # section is 15.0s
    payload["scenes"][1]["estimated_duration_seconds"] = 5.0   # section is 15.0s
    payload["scenes"][2]["estimated_duration_seconds"] = 1.0   # section is 18.0s
    payload["total_estimated_duration_seconds"] = 150.0

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-reconcile-duration",
        script=script,
        knowledge=knowledge,
    )

    # Every section's scene duration must match the section duration exactly
    assert storyboard.scenes[0].estimated_duration_seconds == 15.0
    assert storyboard.scenes[1].estimated_duration_seconds == 15.0
    assert storyboard.scenes[2].estimated_duration_seconds == 18.0
    assert storyboard.total_estimated_duration_seconds == script.total_estimated_duration_seconds
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# 8. Unsupported architecture relationships / fabricated components
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unsupported_architecture_and_fabricated_components_filtered():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    # Add fabricated file path and fake components
    payload["scenes"][1]["related_files"] = [
        "fake/hallucinated_database.py",
        ".env",
        "src/click/core.py",
    ]

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-fake-files",
        script=script,
        knowledge=knowledge,
    )

    sc2 = storyboard.scenes[1]
    assert "fake/hallucinated_database.py" not in sc2.related_files
    assert ".env" not in sc2.related_files
    assert "src/click/core.py" in sc2.related_files
    assert any("rejected nonexistent file" in w for w in storyboard.validation_warnings)
    assert any("excluded sensitive file" in w for w in storyboard.validation_warnings)


# ---------------------------------------------------------------------------
# 9. Invalid or unsupported on-screen text & runtime claims
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unsupported_on_screen_text_and_runtime_claims_rejected():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    payload["scenes"][3]["on_screen_text"] = [
        "Runtime execution is verified for every invocation",
        "Guaranteed 100% bug-free",
        "Parse Arguments",
    ]
    payload["scenes"][3]["visual_description"] = (
        "Shows execution where static analysis proves runtime execution is verified at runtime."
    )

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-runtime-claims",
        script=script,
        knowledge=knowledge,
    )

    sc4 = storyboard.scenes[3]
    # Prohibited on-screen text claims dropped
    assert "Runtime execution is verified for every invocation" not in sc4.on_screen_text
    assert "Guaranteed 100% bug-free" not in sc4.on_screen_text
    assert "Parse Arguments" in sc4.on_screen_text
    # Prohibited visual description claims adjusted
    assert "runtime execution is verified" not in sc4.visual_description.lower()
    assert any("dropped prohibited runtime execution claim" in w for w in storyboard.validation_warnings)


# ---------------------------------------------------------------------------
# 10. Malformed JSON and limited repair pass
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_malformed_json_triggers_single_repair_pass_and_succeeds():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    valid_payload = make_valid_llm_storyboard_dict(script.script_id)

    broken_text = "Here is the storyboard: ```json {\"storyboard_id\": \"broken\", BAD_JSON"
    repaired_text = json.dumps(valid_payload)

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                text=broken_text,
                provider="groq",
                model="openai/gpt-oss-120b",
                latency_ms=210.0,
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
                latency_ms=290.0,
                token_usage=TokenUsageRecord(
                    prompt_tokens=400,
                    completion_tokens=420,
                    total_tokens=820,
                    provider="groq",
                    model="openai/gpt-oss-120b",
                ),
            ),
        ]
    )

    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)
    storyboard = await analyzer.generate_storyboard(
        job_id="job-repair-sb",
        script=script,
        knowledge=knowledge,
    )

    assert mock_llm.generate.call_count == 2
    assert storyboard.metadata.llm_call_count == 2
    assert storyboard.metadata.latency_ms == pytest.approx(500.0)
    assert storyboard.metadata.token_usage.total_tokens == 1720


@pytest.mark.anyio
async def test_unrecoverable_malformed_json_raises_clear_failure():
    script = make_test_script()
    knowledge = make_repository_knowledge()

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

    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)
    with pytest.raises((StoryboardGenerationError, AIInvalidResponseError)):
        await analyzer.generate_storyboard(
            job_id="job-unrec-sb",
            script=script,
            knowledge=knowledge,
        )
    assert mock_llm.generate.call_count == 2


# ---------------------------------------------------------------------------
# 11. Provider errors and timeouts (no fabricated storyboard)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "raised_exc",
    [
        AIProviderUnavailableError("Groq service temporarily down", provider="groq"),
        AIConfigurationError("GROQ_API_KEY is missing", provider="groq"),
        AITimeoutError("Request timed out after 60s", provider="groq"),
    ],
)
async def test_provider_errors_raise_clear_failure_without_fabricating_storyboard(raised_exc):
    script = make_test_script()
    knowledge = make_repository_knowledge()

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.active_provider_name = "groq"
    mock_llm.generate = AsyncMock(side_effect=raised_exc)

    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)
    with pytest.raises(StoryboardGenerationError) as exc_info:
        await analyzer.generate_storyboard(
            job_id="job-fail-sb",
            script=script,
            knowledge=knowledge,
        )
    assert isinstance(exc_info.value, AIError)
    assert isinstance(exc_info.value, type(raised_exc))


# ---------------------------------------------------------------------------
# 12. Prompt-size limits, sensitive file exclusions, and secret redaction
# ---------------------------------------------------------------------------


def test_evidence_builder_redaction_and_sensitive_exclusion():
    script = make_test_script()
    script.title = "Click with key sk-proj-12345678901234567890 and gsk_12345678901234567890"
    knowledge = make_repository_knowledge()

    builder = StoryboardEvidenceBuilder()
    pkg = builder.build_evidence_package(
        script=script,
        knowledge=knowledge,
        max_chars=2000,
    )

    assert pkg.redaction_applied is True
    prompt_json = pkg.to_prompt_json()
    assert "sk-proj-" not in prompt_json
    assert "gsk_" not in prompt_json
    assert "<REDACTED_SECRET>" in prompt_json
    assert ".env" in pkg.excluded_sensitive_paths


# ---------------------------------------------------------------------------
# 13. JSON serialization and round-tripping
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_storyboard_serialization_round_trip():
    script = make_test_script()
    knowledge = make_repository_knowledge()
    payload = make_valid_llm_storyboard_dict(script.script_id)

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-roundtrip",
        script=script,
        knowledge=knowledge,
    )

    json_str = storyboard.model_dump_json()
    restored = EducationalStoryboard.model_validate_json(json_str)

    assert restored.storyboard_id == storyboard.storyboard_id
    assert restored.script_id == script.script_id
    assert len(restored.scenes) == len(storyboard.scenes)
    assert restored.total_estimated_duration_seconds == storyboard.total_estimated_duration_seconds
    assert restored.validate_against_script(script) == []


@pytest.mark.anyio
async def test_storyboard_scenes_auto_distributed_excerpts():
    """
    Verifies that when LLM returns multiple scenes for one script section without excerpts,
    the validator automatically divides the section narration across the scenes.
    """
    script = EducationalScript(
        script_id="script-multi-scene",
        repository_name="pallets/flask",
        title="Multi-scene test",
        introduction="Intro",
        learning_objectives=["Learn multi-scene splitting"],
        total_estimated_duration_seconds=30.0,
        conclusion="Conclusion",
        sections=[
            ScriptSection(
                section_id="sec-1",
                order=1,
                title="Architecture",
                purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
                narration_text="Flask routes incoming HTTP requests to endpoints. Context locals make request objects available globally.",
                estimated_duration_seconds=30.0,
            )
        ],
    )
    knowledge = make_repository_knowledge()

    # Raw LLM response has 2 scenes pointing to sec-1 with excerpt: null
    payload = {
        "storyboard_id": "sb-multi-scene",
        "script_id": "script-multi-scene",
        "title": "Multi-scene test",
        "total_estimated_duration_seconds": 30.0,
        "scenes": [
            {
                "scene_id": "scene-1",
                "scene_number": 1,
                "script_section_id": "sec-1",
                "title": "Routing",
                "purpose": "Routing purpose",
                "estimated_duration_seconds": 15.0,
                "visual_type": "architecture_diagram",
                "visual_description": "Routing diagram",
                "on_screen_text": ["Routing"],
                "narration": {"script_section_id": "sec-1", "excerpt": None},
            },
            {
                "scene_id": "scene-2",
                "scene_number": 2,
                "script_section_id": "sec-1",
                "title": "Context",
                "purpose": "Context purpose",
                "estimated_duration_seconds": 15.0,
                "visual_type": "component_diagram",
                "visual_description": "Context diagram",
                "on_screen_text": ["Context"],
                "narration": {"script_section_id": "sec-1", "excerpt": None},
            },
        ],
    }

    mock_llm = make_mock_llm(json.dumps(payload))
    analyzer = EducationalStoryboardAnalyzer(llm_manager=mock_llm)

    storyboard = await analyzer.generate_storyboard(
        job_id="job-auto-split",
        script=script,
        knowledge=knowledge,
    )

    assert len(storyboard.scenes) == 2
    # Check that excerpts were auto-assigned sentence-by-sentence
    assert storyboard.scenes[0].narration.excerpt == "Flask routes incoming HTTP requests to endpoints."
    assert storyboard.scenes[1].narration.excerpt == "Context locals make request objects available globally."

