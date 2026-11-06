"""
Educational storyboard schemas (Milestone 4, Phase 1).

A storyboard maps an ``EducationalScript`` onto an ordered sequence of visual
scenes. This module defines structure and validation only; it does not
generate images, diagrams, audio or video.

Cross-reference validation
--------------------------
A storyboard stores the ``script_id`` it was built from. Self-contained checks
(unique scene IDs, contiguous scene numbers, positive durations, total
duration consistency, target-range warnings) run on construction.

Checks that require the script itself — every ``script_section_id`` resolves
to a real section, scenes follow script section order, every narrated section
is covered, and the storyboard and script durations agree — are performed by
``EducationalStoryboard.validate_against_script(script)``. That method raises
``StoryboardScriptMismatchError`` for broken references and returns editorial
warnings for softer issues (also recorded in ``validation_warnings``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from ..project_understanding.schemas import EvidenceReference
from ..schemas import TokenUsageRecord
from ..script_generation.schemas import (
    DURATION_TOLERANCE_SECONDS,
    ComponentReference,
    DurationTarget,
    EducationalScript,
    UnderstandingSource,
    VideoFormatSpec,
    WorkflowStepReference,
    check_target_duration,
    find_duplicates,
    merge_warnings,
)

STORYBOARD_SCHEMA_VERSION = "1.0"

_ID_PATTERN = r"^\S+$"


class StoryboardScriptMismatchError(ValueError):
    """Raised when a storyboard references script sections that do not exist or is bound to another script."""


class VisualType(str, Enum):
    """Suggested visual treatments. Not mandatory; ``OTHER`` covers custom visuals."""
    TITLE_CARD = "title_card"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"
    COMPONENT_DIAGRAM = "component_diagram"
    CODE_WALKTHROUGH = "code_walkthrough"
    WORKFLOW_DIAGRAM = "workflow_diagram"
    DATA_FLOW_VISUALIZATION = "data_flow_visualization"
    TECHNOLOGY_OVERVIEW = "technology_overview"
    SUMMARY_CARD = "summary_card"
    OTHER = "other"


class NarrationReference(BaseModel):
    """
    Points at the narration voiced during a scene.

    By default the scene voices the whole script section. ``excerpt`` may hold
    the specific portion of the section's narration when a section is split
    across multiple scenes; it is verified against the script by
    ``EducationalStoryboard.validate_against_script``.
    """
    script_section_id: str = Field(..., min_length=1)
    excerpt: Optional[str] = None


class StoryboardScene(BaseModel):
    """A single visual scene in the storyboard."""
    scene_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    scene_number: int = Field(..., ge=1)
    script_section_id: str = Field(..., min_length=1)

    title: str = Field(..., min_length=1)
    purpose: str = Field(..., min_length=1)
    estimated_duration_seconds: float = Field(..., gt=0)

    visual_type: VisualType = VisualType.OTHER
    visual_description: str = Field(..., min_length=1)
    on_screen_text: List[str] = Field(default_factory=list)
    narration: Optional[NarrationReference] = None

    related_files: List[str] = Field(default_factory=list)
    related_components: List[ComponentReference] = Field(default_factory=list)
    related_workflow_steps: List[WorkflowStepReference] = Field(default_factory=list)
    evidence: List[EvidenceReference] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)

    transition_to_next: Optional[str] = None

    @model_validator(mode="after")
    def _narration_matches_section(self) -> "StoryboardScene":
        if self.narration is None:
            self.narration = NarrationReference(script_section_id=self.script_section_id)
        elif self.narration.script_section_id != self.script_section_id:
            raise ValueError(
                f"Scene '{self.scene_id}' narration references section '{self.narration.script_section_id}' "
                f"but the scene is bound to section '{self.script_section_id}'."
            )
        return self

    def has_grounding(self) -> bool:
        return bool(
            self.evidence
            or any(c.evidence for c in self.related_components)
            or any(w.evidence for w in self.related_workflow_steps)
        )


class StoryboardGenerationMetadata(BaseModel):
    """Provenance of a generated storyboard."""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""
    is_fallback: bool = False
    latency_ms: float = Field(default=0.0, ge=0)
    token_usage: Optional[TokenUsageRecord] = None
    source_understandings: List[UnderstandingSource] = Field(default_factory=list)


class EducationalStoryboard(BaseModel):
    """An ordered visual plan for an educational script."""
    schema_version: str = STORYBOARD_SCHEMA_VERSION
    storyboard_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    script_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)

    video_format: VideoFormatSpec = Field(default_factory=VideoFormatSpec)
    target_duration: DurationTarget = Field(default_factory=DurationTarget)
    total_estimated_duration_seconds: float = Field(..., gt=0)

    scenes: List[StoryboardScene] = Field(..., min_length=1)
    metadata: StoryboardGenerationMetadata = Field(default_factory=StoryboardGenerationMetadata)
    validation_warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_storyboard(self) -> "EducationalStoryboard":
        duplicates = find_duplicates([s.scene_id for s in self.scenes])
        if duplicates:
            raise ValueError(f"Duplicate scene_id values: {duplicates}")

        numbers = [s.scene_number for s in self.scenes]
        if numbers != list(range(1, len(self.scenes) + 1)):
            raise ValueError(
                f"scene_number values must be contiguous from 1 and match list order; got {numbers}"
            )

        scene_total = sum(s.estimated_duration_seconds for s in self.scenes)
        if abs(scene_total - self.total_estimated_duration_seconds) > DURATION_TOLERANCE_SECONDS:
            raise ValueError(
                f"total_estimated_duration_seconds ({self.total_estimated_duration_seconds:.1f}s) does not match "
                f"the sum of scene durations ({scene_total:.1f}s) within {DURATION_TOLERANCE_SECONDS:.1f}s tolerance."
            )

        warnings: List[str] = []
        warnings += check_target_duration(self.total_estimated_duration_seconds, self.target_duration, "Storyboard")
        for index, scene in enumerate(self.scenes):
            is_last = index == len(self.scenes) - 1
            if not is_last and not (scene.transition_to_next or "").strip():
                warnings.append(f"Scene '{scene.scene_id}' has no transition to the next scene.")
        self.validation_warnings = merge_warnings(self.validation_warnings, warnings)
        return self

    def validate_against_script(self, script: EducationalScript) -> List[str]:
        """
        Validates cross-references with the source script.

        Raises ``StoryboardScriptMismatchError`` if the storyboard is bound to a
        different script, references unknown sections, or orders scenes against
        the script's section order. Returns (and records) editorial warnings.
        """
        if self.script_id != script.script_id:
            raise StoryboardScriptMismatchError(
                f"Storyboard is bound to script '{self.script_id}', not '{script.script_id}'."
            )

        section_index: Dict[str, int] = {s.section_id: i for i, s in enumerate(script.sections)}
        unknown = [s.scene_id for s in self.scenes if s.script_section_id not in section_index]
        if unknown:
            raise StoryboardScriptMismatchError(
                f"Scenes reference unknown script sections: "
                + ", ".join(
                    f"{s.scene_id}->{s.script_section_id}" for s in self.scenes if s.scene_id in unknown
                )
            )

        positions = [section_index[s.script_section_id] for s in self.scenes]
        if positions != sorted(positions):
            raise StoryboardScriptMismatchError(
                "Scenes must follow script section order; scene-to-section order is "
                + ", ".join(f"{s.scene_id}->{s.script_section_id}" for s in self.scenes)
            )

        warnings: List[str] = []
        covered = {s.script_section_id for s in self.scenes}
        for section in script.sections:
            if section.section_id not in covered:
                warnings.append(f"Script section '{section.section_id}' is not covered by any storyboard scene.")

        for section in script.sections:
            scenes = [s for s in self.scenes if s.script_section_id == section.section_id]
            if not scenes:
                continue
            scene_sum = sum(s.estimated_duration_seconds for s in scenes)
            if abs(scene_sum - section.estimated_duration_seconds) > DURATION_TOLERANCE_SECONDS:
                warnings.append(
                    f"Scenes for section '{section.section_id}' total {scene_sum:.1f}s but the section is estimated "
                    f"at {section.estimated_duration_seconds:.1f}s."
                )
            for scene in scenes:
                excerpt = (scene.narration.excerpt if scene.narration else None) or ""
                if excerpt.strip() and excerpt.strip() not in section.narration_text:
                    warnings.append(
                        f"Scene '{scene.scene_id}' narration excerpt does not appear in section "
                        f"'{section.section_id}' narration."
                    )

        if abs(self.total_estimated_duration_seconds - script.total_estimated_duration_seconds) > DURATION_TOLERANCE_SECONDS:
            warnings.append(
                f"Storyboard duration {self.total_estimated_duration_seconds:.1f}s differs from script duration "
                f"{script.total_estimated_duration_seconds:.1f}s."
            )

        if self.video_format != script.video_format:
            warnings.append(
                f"Storyboard video format {self.video_format.orientation.value} {self.video_format.aspect_ratio} "
                f"differs from script format {script.video_format.orientation.value} {script.video_format.aspect_ratio}."
            )

        self.validation_warnings = merge_warnings(self.validation_warnings, warnings)
        return warnings
