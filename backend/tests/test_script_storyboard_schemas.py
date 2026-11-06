"""
Milestone 4, Phase 1 — Educational script and storyboard schema tests.

Covers: valid creation, invalid durations, duplicate IDs, invalid section
references, duration consistency, narration length warnings, evidence
preservation, uncertain evidence representation and JSON round-tripping.
"""

import pytest
from pydantic import ValidationError

from app.services.ai.project_understanding.schemas import EvidenceReference
from app.services.ai.script_generation import (
    ComponentReference,
    DataFlowReference,
    EducationalScript,
    GroundedClaim,
    GroundingStatus,
    ScriptSection,
    SectionPurpose,
    VideoFormatSpec,
    VideoOrientation,
    WorkflowStepReference,
    count_words,
    estimate_narration_seconds,
)
from app.services.ai.storyboard_generation import (
    EducationalStoryboard,
    NarrationReference,
    StoryboardScene,
    StoryboardScriptMismatchError,
    VisualType,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def evidence(path: str = "src/click/core.py", start: int = 10, end: int = 40) -> EvidenceReference:
    return EvidenceReference(
        file_path=path,
        line_start=start,
        line_end=end,
        evidence_type="code",
        confidence="high",
        status="confirmed",
        detail="Command.invoke definition",
        path_verified=True,
        line_range_verified=True,
    )


# 150 wpm => 2.5 words/second. Durations: 10 + 15 + 20 + 15 + 10 = 70s.
SECTION_PLAN = [
    ("s1-hook", SectionPurpose.HOOK, 10),
    ("s2-problem", SectionPurpose.PROBLEM, 15),
    ("s3-architecture", SectionPurpose.ARCHITECTURE_OVERVIEW, 20),
    ("s4-workflow", SectionPurpose.WORKFLOW, 15),
    ("s5-conclusion", SectionPurpose.CONCLUSION, 10),
]


def make_section(section_id: str, order: int, purpose: SectionPurpose, seconds: float, **overrides) -> ScriptSection:
    data = dict(
        section_id=section_id,
        order=order,
        title=f"Title {section_id}",
        purpose=purpose,
        narration_text=words(int(seconds * 2.5)),
        estimated_duration_seconds=seconds,
        evidence=[evidence()],
        transition_to_next="Next, let's look closer.",
    )
    data.update(overrides)
    return ScriptSection(**data)


def make_sections(plan=SECTION_PLAN):
    return [make_section(sid, i + 1, purpose, secs) for i, (sid, purpose, secs) in enumerate(plan)]


def make_script(**overrides) -> EducationalScript:
    sections = overrides.pop("sections", None) or make_sections()
    data = dict(
        script_id="script-click-001",
        repository_name="pallets/click",
        title="How Click Builds Command-Line Interfaces",
        introduction="Click is a Python package for composable command-line interfaces.",
        learning_objectives=["Understand Click's purpose", "Follow a command invocation"],
        total_estimated_duration_seconds=sum(s.estimated_duration_seconds for s in sections),
        sections=sections,
        conclusion="Click turns decorated functions into robust CLIs.",
        evidence=[evidence("README.md", 1, 20)],
    )
    data.update(overrides)
    return EducationalScript(**data)


def make_scene(scene_id: str, number: int, section_id: str, seconds: float, **overrides) -> StoryboardScene:
    data = dict(
        scene_id=scene_id,
        scene_number=number,
        script_section_id=section_id,
        title=f"Scene {scene_id}",
        purpose="Explain the section visually",
        estimated_duration_seconds=seconds,
        visual_type=VisualType.ARCHITECTURE_DIAGRAM,
        visual_description="Boxes for core modules connected by arrows.",
        on_screen_text=["Click core"],
        related_files=["src/click/core.py"],
        evidence=[evidence()],
        transition_to_next="Cut to next scene",
    )
    data.update(overrides)
    return StoryboardScene(**data)


def make_storyboard(script: EducationalScript = None, **overrides) -> EducationalStoryboard:
    script = script or make_script()
    scenes = overrides.pop("scenes", None) or [
        make_scene(f"scene-{i + 1}", i + 1, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections)
    ]
    data = dict(
        storyboard_id="sb-click-001",
        script_id=script.script_id,
        title="Click storyboard",
        total_estimated_duration_seconds=sum(s.estimated_duration_seconds for s in scenes),
        scenes=scenes,
    )
    data.update(overrides)
    return EducationalStoryboard(**data)


# ---------------------------------------------------------------------------
# Valid creation
# ---------------------------------------------------------------------------


def test_valid_educational_script_creation():
    script = make_script()
    assert script.total_estimated_duration_seconds == 70
    assert script.video_format.orientation == VideoOrientation.LANDSCAPE
    assert script.video_format.aspect_ratio == "16:9"
    assert script.intended_audience == ["Developers", "Students"]
    assert [s.order for s in script.sections] == [1, 2, 3, 4, 5]
    assert script.validation_warnings == []
    assert script.static_analysis_caveats  # caveats present by default
    assert script.get_section("s3-architecture").purpose == SectionPurpose.ARCHITECTURE_OVERVIEW


def test_script_section_structure_is_adaptable():
    """Repositories are not forced into six sections; three sections are valid."""
    plan = [
        ("intro", SectionPurpose.INTRODUCTION, 25),
        ("components", SectionPurpose.COMPONENT_DEEP_DIVE, 25),
        ("outro", SectionPurpose.CONCLUSION, 15),
    ]
    script = make_script(sections=make_sections(plan))
    assert len(script.sections) == 3
    assert script.validation_warnings == []


def test_valid_storyboard_creation_and_script_cross_validation():
    script = make_script()
    storyboard = make_storyboard(script)
    assert storyboard.scenes[0].narration.script_section_id == "s1-hook"
    assert storyboard.video_format.aspect_ratio == "16:9"
    assert storyboard.validate_against_script(script) == []
    assert storyboard.validation_warnings == []


def test_storyboard_allows_multiple_scenes_per_section():
    script = make_script()
    scenes = [
        make_scene("scene-1", 1, "s1-hook", 10, visual_type=VisualType.TITLE_CARD),
        make_scene("scene-2a", 2, "s2-problem", 7),
        make_scene("scene-2b", 3, "s2-problem", 8),
        make_scene("scene-3", 4, "s3-architecture", 20),
        make_scene("scene-4", 5, "s4-workflow", 15, visual_type=VisualType.WORKFLOW_DIAGRAM),
        make_scene("scene-5", 6, "s5-conclusion", 10, visual_type=VisualType.SUMMARY_CARD, transition_to_next=None),
    ]
    storyboard = make_storyboard(script, scenes=scenes)
    assert storyboard.validate_against_script(script) == []


# ---------------------------------------------------------------------------
# Invalid durations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -5])
def test_section_rejects_non_positive_duration(bad):
    with pytest.raises(ValidationError):
        make_section("s1", 1, SectionPurpose.HOOK, 10, estimated_duration_seconds=bad)


@pytest.mark.parametrize("bad", [0, -1.5])
def test_scene_rejects_non_positive_duration(bad):
    with pytest.raises(ValidationError):
        make_scene("scene-1", 1, "s1-hook", bad)


def test_script_rejects_non_positive_total_duration():
    with pytest.raises(ValidationError):
        make_script(total_estimated_duration_seconds=0)


# ---------------------------------------------------------------------------
# Unique IDs and ordering
# ---------------------------------------------------------------------------


def test_duplicate_section_ids_rejected():
    sections = make_sections()
    sections[1] = make_section("s1-hook", 2, SectionPurpose.PROBLEM, 15)
    with pytest.raises(ValidationError, match="Duplicate section_id"):
        make_script(sections=sections)


def test_duplicate_scene_ids_rejected():
    script = make_script()
    scenes = [
        make_scene("scene-1", i + 1, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections)
    ]
    with pytest.raises(ValidationError, match="Duplicate scene_id"):
        make_storyboard(script, scenes=scenes)


def test_section_order_must_be_contiguous_and_match_list_order():
    sections = make_sections()
    sections[1], sections[2] = sections[2], sections[1]
    with pytest.raises(ValidationError, match="order"):
        make_script(sections=sections)


def test_scene_numbers_must_be_contiguous():
    script = make_script()
    scenes = [
        make_scene(f"scene-{i + 1}", (i + 1) * 2, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections)
    ]
    with pytest.raises(ValidationError, match="scene_number"):
        make_storyboard(script, scenes=scenes)


# ---------------------------------------------------------------------------
# Script-section references
# ---------------------------------------------------------------------------


def test_storyboard_rejects_unknown_script_section_reference():
    script = make_script()
    scenes = [
        make_scene(f"scene-{i + 1}", i + 1, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections)
    ]
    scenes[2] = make_scene("scene-3", 3, "s99-missing", 20)
    storyboard = make_storyboard(script, scenes=scenes)
    with pytest.raises(StoryboardScriptMismatchError, match="s99-missing"):
        storyboard.validate_against_script(script)


def test_storyboard_rejects_different_script_id():
    script = make_script()
    storyboard = make_storyboard(script, script_id="another-script")
    with pytest.raises(StoryboardScriptMismatchError, match="another-script"):
        storyboard.validate_against_script(script)


def test_storyboard_rejects_scenes_out_of_section_order():
    script = make_script()
    secs = script.sections
    order = [secs[0], secs[2], secs[1], secs[3], secs[4]]
    scenes = [make_scene(f"scene-{i + 1}", i + 1, s.section_id, s.estimated_duration_seconds) for i, s in enumerate(order)]
    storyboard = make_storyboard(script, scenes=scenes)
    with pytest.raises(StoryboardScriptMismatchError, match="section order"):
        storyboard.validate_against_script(script)


def test_scene_narration_reference_must_match_scene_section():
    with pytest.raises(ValidationError, match="narration references section"):
        make_scene("scene-1", 1, "s1-hook", 10, narration=NarrationReference(script_section_id="s2-problem"))


def test_uncovered_section_produces_warning_not_error():
    script = make_script()
    scenes = [
        make_scene(f"scene-{i + 1}", i + 1, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections[:4])
    ]
    storyboard = make_storyboard(script, scenes=scenes)
    warnings = storyboard.validate_against_script(script)
    assert any("'s5-conclusion' is not covered" in w for w in warnings)
    assert any("differs from script duration" in w for w in warnings)
    assert set(warnings) <= set(storyboard.validation_warnings)


def test_narration_excerpt_not_in_section_produces_warning():
    script = make_script()
    scenes = [
        make_scene(f"scene-{i + 1}", i + 1, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections)
    ]
    scenes[0] = make_scene(
        "scene-1", 1, "s1-hook", 10,
        narration=NarrationReference(script_section_id="s1-hook", excerpt="fabricated sentence"),
    )
    warnings = make_storyboard(script, scenes=scenes).validate_against_script(script)
    assert any("excerpt does not appear" in w for w in warnings)


# ---------------------------------------------------------------------------
# Duration consistency and target range
# ---------------------------------------------------------------------------


def test_script_total_must_match_sum_of_sections():
    with pytest.raises(ValidationError, match="sum of section durations"):
        make_script(total_estimated_duration_seconds=90)


def test_script_total_within_tolerance_is_accepted():
    script = make_script(total_estimated_duration_seconds=70.6)
    assert script.total_estimated_duration_seconds == 70.6


def test_storyboard_total_must_match_sum_of_scenes():
    with pytest.raises(ValidationError, match="sum of scene durations"):
        make_storyboard(total_estimated_duration_seconds=120)


def test_short_script_warns_but_remains_valid():
    plan = [("intro", SectionPurpose.INTRODUCTION, 20), ("outro", SectionPurpose.CONCLUSION, 10)]
    script = make_script(sections=make_sections(plan))
    assert script.total_estimated_duration_seconds == 30
    assert any("shorter than the target range 60–90s" in w for w in script.validation_warnings)
    assert script.sections[0].narration_text == words(50)  # untouched


def test_long_script_warns_but_is_not_truncated():
    plan = [(f"s{i}", SectionPurpose.COMPONENT_DEEP_DIVE, 30) for i in range(1, 5)]
    script = make_script(sections=make_sections(plan))
    assert script.total_estimated_duration_seconds == 120
    assert len(script.sections) == 4
    assert any("longer than the target range" in w for w in script.validation_warnings)


def test_storyboard_out_of_range_warning():
    plan = [("intro", SectionPurpose.INTRODUCTION, 20), ("outro", SectionPurpose.CONCLUSION, 10)]
    script = make_script(sections=make_sections(plan))
    storyboard = make_storyboard(script)
    assert any("Storyboard total duration 30.0s is shorter" in w for w in storyboard.validation_warnings)


def test_section_scene_duration_mismatch_warns():
    script = make_script()
    scenes = [
        make_scene(f"scene-{i + 1}", i + 1, s.section_id, s.estimated_duration_seconds)
        for i, s in enumerate(script.sections)
    ]
    scenes[0] = make_scene("scene-1", 1, "s1-hook", 15)
    warnings = make_storyboard(script, scenes=scenes).validate_against_script(script)
    assert any("Scenes for section 's1-hook' total 15.0s" in w for w in warnings)


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------


def test_narrated_section_requires_narration():
    with pytest.raises(ValidationError, match="empty narration_text"):
        make_section("s1", 1, SectionPurpose.HOOK, 10, narration_text="   ")


def test_non_narrated_section_may_omit_narration():
    section = make_section("s1", 1, SectionPurpose.HOOK, 3, is_narrated=False, narration_text="")
    assert section.word_count == 0
    assert section.pacing_warnings(make_script().pacing) == []


def test_dense_narration_warns():
    sections = make_sections()
    sections[0] = make_section("s1-hook", 1, SectionPurpose.HOOK, 10, narration_text=words(60))  # 360 wpm
    script = make_script(sections=sections)
    assert any("'s1-hook' narration is too dense" in w for w in script.validation_warnings)
    assert script.sections[0].word_count == 60


def test_sparse_narration_warns():
    sections = make_sections()
    sections[1] = make_section("s2-problem", 2, SectionPurpose.PROBLEM, 15, narration_text=words(5))  # 20 wpm
    script = make_script(sections=sections)
    assert any("'s2-problem' narration is sparse" in w for w in script.validation_warnings)


def test_speaking_rate_helpers():
    assert count_words("Click turns functions into commands.") == 5
    assert estimate_narration_seconds(words(150)) == pytest.approx(60.0)
    assert estimate_narration_seconds(words(150), words_per_minute=120) == pytest.approx(75.0)
    with pytest.raises(ValueError):
        estimate_narration_seconds("x", words_per_minute=0)


def test_custom_pacing_bounds_are_validated():
    with pytest.raises(ValidationError):
        make_script(pacing={"words_per_minute": 200, "min_comfortable_wpm": 110, "max_comfortable_wpm": 180})


def test_missing_transition_warns():
    sections = make_sections()
    sections[0] = make_section("s1-hook", 1, SectionPurpose.HOOK, 10, transition_to_next=None)
    script = make_script(sections=sections)
    assert any("'s1-hook' has no transition" in w for w in script.validation_warnings)


# ---------------------------------------------------------------------------
# Video format
# ---------------------------------------------------------------------------


def test_orientation_must_match_aspect_ratio():
    with pytest.raises(ValidationError, match="inconsistent"):
        VideoFormatSpec(orientation=VideoOrientation.LANDSCAPE, aspect_ratio="9:16")
    assert VideoFormatSpec(orientation=VideoOrientation.PORTRAIT, aspect_ratio="9:16").aspect_ratio == "9:16"


def test_storyboard_format_mismatch_warns():
    script = make_script()
    storyboard = make_storyboard(script, video_format=VideoFormatSpec(orientation="square", aspect_ratio="1:1"))
    warnings = storyboard.validate_against_script(script)
    assert any("video format" in w for w in warnings)


# ---------------------------------------------------------------------------
# Grounding, evidence and uncertainty
# ---------------------------------------------------------------------------


def test_evidence_references_are_preserved():
    ev = evidence("src/click/core.py", 1200, 1250)
    section = make_section(
        "s3-architecture", 3, SectionPurpose.ARCHITECTURE_OVERVIEW, 20,
        evidence=[ev],
        related_components=[
            ComponentReference(
                component_id="src/click/core.py",
                name="Command Execution Engine",
                file_path="src/click/core.py",
                symbol_names=["Command.invoke"],
                evidence=[ev],
            )
        ],
    )
    sections = make_sections()
    sections[2] = section
    script = make_script(sections=sections)
    restored = EducationalScript.model_validate_json(script.model_dump_json())
    ref = restored.get_section("s3-architecture").evidence[0]
    assert ref == ev
    assert ref.line_start == 1200 and ref.line_range_verified is True
    assert restored.get_section("s3-architecture").related_components[0].symbol_names == ["Command.invoke"]


def test_confirmed_claim_requires_valid_evidence():
    with pytest.raises(ValidationError, match="requires at least one valid EvidenceReference"):
        GroundedClaim(statement="Click uses Flask.", grounding_status=GroundingStatus.CONFIRMED)

    invalid = evidence()
    invalid.is_valid = False
    with pytest.raises(ValidationError):
        GroundedClaim(statement="X", grounding_status=GroundingStatus.CONFIRMED, evidence=[invalid])

    ok = GroundedClaim(statement="Click defines Command.", grounding_status="confirmed", evidence=[evidence()])
    assert ok.grounding_status == GroundingStatus.CONFIRMED


def test_uncertain_claim_requires_note_and_is_representable():
    with pytest.raises(ValidationError, match="uncertainty_note"):
        GroundedClaim(statement="Data may be persisted.", grounding_status=GroundingStatus.UNCERTAIN)

    claim = GroundedClaim(
        statement="Results may be stored in a database.",
        grounding_status=GroundingStatus.UNCERTAIN,
        uncertainty_note="No verified storage operation was detected statically.",
    )
    sections = make_sections()
    sections[3] = make_section(
        "s4-workflow", 4, SectionPurpose.WORKFLOW, 15,
        evidence=[], claims=[claim],
        uncertainty_notes=["Persistence behaviour is not established by static analysis."],
    )
    script = make_script(sections=sections)
    restored = EducationalScript.model_validate_json(script.model_dump_json())
    assert restored.get_section("s4-workflow").claims[0].grounding_status == GroundingStatus.UNCERTAIN
    # Section declares uncertainty, so no "no evidence" warning.
    assert not any("'s4-workflow' cites no evidence" in w for w in script.validation_warnings)


def test_section_without_evidence_or_uncertainty_warns():
    sections = make_sections()
    sections[1] = make_section("s2-problem", 2, SectionPurpose.PROBLEM, 15, evidence=[])
    script = make_script(sections=sections)
    assert any("'s2-problem' cites no evidence" in w for w in script.validation_warnings)


def test_script_without_any_evidence_warns():
    sections = [
        make_section(sid, i + 1, p, s, evidence=[]) for i, (sid, p, s) in enumerate(SECTION_PLAN)
    ]
    script = make_script(sections=sections, evidence=[])
    assert any("contains no evidence references" in w for w in script.validation_warnings)


def test_workflow_step_reference_cannot_claim_runtime_verification():
    with pytest.raises(ValidationError, match="runtime_execution_verified"):
        WorkflowStepReference(workflow_id="wf-1", step_number=1, runtime_execution_verified=True)

    ref = WorkflowStepReference(
        workflow_id="wf-1", step_number=2, step_title="Convert parameters",
        component_id="src/click/core.py", symbol_name="Command.invoke",
        call_relationship_verified=True, source_order_verified=True,
        same_execution_path_verified=True, execution_guaranteed=False,
        evidence=[evidence()],
    )
    assert ref.runtime_execution_verified is False


def test_data_flow_reference_status_is_validated():
    with pytest.raises(ValidationError):
        DataFlowReference(workflow_id="wf-1", flow_id="df-1", data_relationship_status="verified_at_runtime")
    assert DataFlowReference(workflow_id="wf-1", flow_id="df-1").data_relationship_status == "inferred"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_script_round_trip_serialization():
    sections = make_sections()
    sections[3] = make_section(
        "s4-workflow", 4, SectionPurpose.WORKFLOW, 15,
        related_workflow_steps=[WorkflowStepReference(workflow_id="wf-1", step_number=1, evidence=[evidence()])],
        related_data_flows=[DataFlowReference(workflow_id="wf-1", flow_id="df-1", data_relationship_status="observed")],
    )
    script = make_script(sections=sections)
    payload = script.model_dump(mode="json")
    assert payload["video_format"] == {"orientation": "landscape", "aspect_ratio": "16:9"}
    assert payload["sections"][3]["purpose"] == "workflow"

    restored = EducationalScript.model_validate(payload)
    assert restored == script
    # Re-validation must not duplicate warnings.
    assert restored.validation_warnings == script.validation_warnings


def test_storyboard_round_trip_serialization():
    script = make_script()
    storyboard = make_storyboard(script)
    restored = EducationalStoryboard.model_validate_json(storyboard.model_dump_json())
    assert restored == storyboard
    assert restored.scenes[0].visual_type == VisualType.ARCHITECTURE_DIAGRAM
    assert restored.scenes[0].evidence[0].file_path == "src/click/core.py"
    assert restored.validate_against_script(script) == []


def test_warnings_round_trip_without_duplication():
    plan = [("intro", SectionPurpose.INTRODUCTION, 20), ("outro", SectionPurpose.CONCLUSION, 10)]
    script = make_script(sections=make_sections(plan))
    restored = EducationalScript.model_validate_json(script.model_dump_json())
    assert restored.validation_warnings == script.validation_warnings
    assert len(restored.validation_warnings) == len(set(restored.validation_warnings))
