"""
Educational script schemas (Milestone 4, Phase 1).

These models describe a narrated, 60–90 second, landscape (16:9) technical
explainer video script derived from RepoGenie's existing understanding outputs:

* ``ProjectUnderstanding``            (Milestone 3.2)
* ``RepositoryCodeUnderstanding``     (Milestone 3.3)
* ``RepositoryWorkflowUnderstanding`` (Milestone 3.4)
* ``RepositoryKnowledge``             (Milestone 2.6)

This module defines structure and validation only. It performs no LLM calls,
rendering, speech synthesis or video assembly.

Grounding principles
--------------------
* Evidence is expressed with the shared ``EvidenceReference`` model already
  used by Project, Code and Workflow Understanding.
* Claims may be ``confirmed`` (backed by at least one valid evidence
  reference), ``inferred`` or ``uncertain``. Uncertain content can carry an
  explicit uncertainty note, or be omitted entirely.
* Workflow references copy the *static* verification flags from Milestone 3.4.
  ``runtime_execution_verified`` is always ``False``: RepoGenie never executes
  repository code, so no script may claim runtime verification.

Validation philosophy
---------------------
Hard errors (``ValueError`` -> ``pydantic.ValidationError``) are raised only for
structurally invalid or internally inconsistent data: non-positive durations,
duplicate IDs, broken ordering, empty narration on narrated sections,
inconsistent totals, contradictory orientation/aspect ratio, and "confirmed"
claims without valid evidence.

Editorial concerns — total duration outside the 60–90 s target, narration that
is too dense or too sparse for its time slot, sections without evidence — are
reported as ``validation_warnings``. Content is never silently modified or
truncated, so shorter or longer scripts remain representable.

Speaking-rate assumptions
-------------------------
Educational narration is typically delivered at roughly 130–160 words per
minute (wpm). RepoGenie assumes:

* ``DEFAULT_WORDS_PER_MINUTE = 150`` for estimating narration time.
* ``DEFAULT_MIN_COMFORTABLE_WPM = 110``: below this the narration is sparse
  for its allotted time (long silences).
* ``DEFAULT_MAX_COMFORTABLE_WPM = 180``: above this the narration is likely too
  dense to be spoken clearly in its allotted time.

These values are configurable per script through ``NarrationPacing``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

from ..project_understanding.schemas import EvidenceReference
from ..schemas import TokenUsageRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_SCHEMA_VERSION = "1.0"

TARGET_MIN_DURATION_SECONDS: float = 60.0
TARGET_MAX_DURATION_SECONDS: float = 90.0

DEFAULT_WORDS_PER_MINUTE: float = 150.0
DEFAULT_MIN_COMFORTABLE_WPM: float = 110.0
DEFAULT_MAX_COMFORTABLE_WPM: float = 180.0

# Allowed absolute difference between a declared total duration and the sum of
# its parts (sections or scenes). Accounts for floating-point rounding.
DURATION_TOLERANCE_SECONDS: float = 1.0

DEFAULT_STATIC_ANALYSIS_CAVEATS: Tuple[str, ...] = (
    "Script content is derived from static repository analysis and AI interpretation; "
    "repository code was never executed.",
    "Workflow and data-flow descriptions reflect statically inferred paths, not verified runtime behaviour.",
)

_ID_PATTERN = r"^\S+$"
_WORD_RE = re.compile(r"\b[\w'’-]+\b", re.UNICODE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def count_words(text: Optional[str]) -> int:
    """Counts spoken words in narration text."""
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def estimate_narration_seconds(text: Optional[str], words_per_minute: float = DEFAULT_WORDS_PER_MINUTE) -> float:
    """Estimates how long ``text`` takes to speak at ``words_per_minute``."""
    if words_per_minute <= 0:
        raise ValueError("words_per_minute must be positive")
    return count_words(text) * 60.0 / words_per_minute


def merge_warnings(existing: List[str], new: List[str]) -> List[str]:
    """Appends ``new`` warnings not already present, preserving order (idempotent on re-validation)."""
    merged = list(existing)
    for warning in new:
        if warning not in merged:
            merged.append(warning)
    return merged


def find_duplicates(values: List[str]) -> List[str]:
    """Returns values that occur more than once, in first-seen order."""
    seen: set = set()
    duplicates: List[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def check_target_duration(total_seconds: float, target: "DurationTarget", label: str) -> List[str]:
    """Returns a warning when ``total_seconds`` falls outside the target range."""
    if total_seconds < target.min_seconds:
        return [
            f"{label} total duration {total_seconds:.1f}s is shorter than the target range "
            f"{target.min_seconds:.0f}–{target.max_seconds:.0f}s."
        ]
    if total_seconds > target.max_seconds:
        return [
            f"{label} total duration {total_seconds:.1f}s is longer than the target range "
            f"{target.min_seconds:.0f}–{target.max_seconds:.0f}s."
        ]
    return []


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class VideoOrientation(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class SectionPurpose(str, Enum):
    """Suggested narrative roles. Repositories may use any subset, in any count."""
    HOOK = "hook"
    INTRODUCTION = "introduction"
    PROBLEM = "problem"
    ARCHITECTURE_OVERVIEW = "architecture_overview"
    TECHNOLOGY_OVERVIEW = "technology_overview"
    COMPONENT_DEEP_DIVE = "component_deep_dive"
    WORKFLOW = "workflow"
    DATA_FLOW = "data_flow"
    CONCLUSION = "conclusion"
    OTHER = "other"


class GroundingStatus(str, Enum):
    """How strongly a statement is supported by RepoGenie's understanding outputs."""
    CONFIRMED = "confirmed"   # Backed by at least one valid EvidenceReference.
    INFERRED = "inferred"     # Reasonable interpretation of available evidence.
    UNCERTAIN = "uncertain"   # Evidence is insufficient; must be presented as uncertain.


class UnderstandingSource(str, Enum):
    """The existing RepoGenie output a reference or claim was taken from."""
    PROJECT_UNDERSTANDING = "project_understanding"
    CODE_UNDERSTANDING = "code_understanding"
    WORKFLOW_UNDERSTANDING = "workflow_understanding"
    REPOSITORY_KNOWLEDGE = "repository_knowledge"


# ---------------------------------------------------------------------------
# Format / pacing
# ---------------------------------------------------------------------------


class VideoFormatSpec(BaseModel):
    """Target video orientation and aspect ratio (default: landscape 16:9)."""
    orientation: VideoOrientation = VideoOrientation.LANDSCAPE
    aspect_ratio: str = Field(default="16:9", pattern=r"^\d+:\d+$")

    @model_validator(mode="after")
    def _orientation_matches_aspect_ratio(self) -> "VideoFormatSpec":
        width, height = (int(part) for part in self.aspect_ratio.split(":"))
        if width <= 0 or height <= 0:
            raise ValueError(f"aspect_ratio '{self.aspect_ratio}' must have positive components")
        expected = (
            VideoOrientation.LANDSCAPE if width > height
            else VideoOrientation.PORTRAIT if width < height
            else VideoOrientation.SQUARE
        )
        if expected != self.orientation:
            raise ValueError(
                f"aspect_ratio '{self.aspect_ratio}' is inconsistent with orientation '{self.orientation.value}'"
            )
        return self


class DurationTarget(BaseModel):
    """Desired total duration range. Out-of-range content produces warnings, not errors."""
    min_seconds: float = Field(default=TARGET_MIN_DURATION_SECONDS, gt=0)
    max_seconds: float = Field(default=TARGET_MAX_DURATION_SECONDS, gt=0)

    @model_validator(mode="after")
    def _min_not_above_max(self) -> "DurationTarget":
        if self.min_seconds > self.max_seconds:
            raise ValueError("DurationTarget.min_seconds must not exceed max_seconds")
        return self


class NarrationPacing(BaseModel):
    """Speaking-rate assumptions used for narration-length warnings."""
    words_per_minute: float = Field(default=DEFAULT_WORDS_PER_MINUTE, gt=0)
    min_comfortable_wpm: float = Field(default=DEFAULT_MIN_COMFORTABLE_WPM, gt=0)
    max_comfortable_wpm: float = Field(default=DEFAULT_MAX_COMFORTABLE_WPM, gt=0)

    @model_validator(mode="after")
    def _ordered_bounds(self) -> "NarrationPacing":
        if not (self.min_comfortable_wpm <= self.words_per_minute <= self.max_comfortable_wpm):
            raise ValueError("NarrationPacing requires min_comfortable_wpm <= words_per_minute <= max_comfortable_wpm")
        return self


# ---------------------------------------------------------------------------
# Grounding references
# ---------------------------------------------------------------------------


class ComponentReference(BaseModel):
    """
    References a repository component, file, class or function described by the
    existing understanding outputs (e.g. ``ComponentUnderstandingItem.component_id``).
    """
    component_id: str = Field(..., min_length=1)       # Canonical path/module ID, e.g. "src/click/core.py"
    name: str = Field(..., min_length=1)               # Display name, e.g. "Command Execution Engine"
    file_path: Optional[str] = None
    symbol_names: List[str] = Field(default_factory=list)  # Functions/classes, e.g. ["Command.invoke"]
    source: UnderstandingSource = UnderstandingSource.CODE_UNDERSTANDING
    evidence: List[EvidenceReference] = Field(default_factory=list)


class ArchitectureRelationshipReference(BaseModel):
    """References a relationship between two components (import, call, inheritance, data flow)."""
    source_component: str = Field(..., min_length=1)
    target_component: str = Field(..., min_length=1)
    relationship_type: str = "calls"  # "calls", "imports", "inherits", "instantiates", "data_flow"
    is_statically_confirmed: bool = False  # True ONLY if backed by a static dependency/call-graph edge
    source: UnderstandingSource = UnderstandingSource.CODE_UNDERSTANDING
    evidence: List[EvidenceReference] = Field(default_factory=list)


class WorkflowStepReference(BaseModel):
    """
    References a ``WorkflowStep`` from Milestone 3.4, preserving its static
    verification flags so narration never overstates certainty.
    """
    workflow_id: str = Field(..., min_length=1)
    step_number: int = Field(..., ge=1)
    step_title: Optional[str] = None
    component_id: Optional[str] = None
    symbol_name: Optional[str] = None

    call_relationship_verified: bool = False
    source_order_verified: bool = False
    same_execution_path_verified: bool = False
    execution_guaranteed: bool = False  # Normal, non-exceptional static control-flow path only
    runtime_execution_verified: bool = False  # ALWAYS False

    evidence: List[EvidenceReference] = Field(default_factory=list)

    @field_validator("runtime_execution_verified")
    @classmethod
    def _never_runtime_verified(cls, v: bool) -> bool:
        if v is True:
            raise ValueError(
                "runtime_execution_verified must always be False because RepoGenie does not execute repository code."
            )
        return False


class DataFlowReference(BaseModel):
    """References a ``DataFlow`` from Milestone 3.4."""
    workflow_id: str = Field(..., min_length=1)
    flow_id: str = Field(..., min_length=1)
    data_item_name: Optional[str] = None
    data_relationship_status: str = "inferred"  # "observed", "inferred", "unknown_or_unresolved"
    evidence: List[EvidenceReference] = Field(default_factory=list)

    @field_validator("data_relationship_status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        allowed = {"observed", "inferred", "unknown_or_unresolved"}
        if v not in allowed:
            raise ValueError(f"data_relationship_status must be one of {sorted(allowed)}")
        return v


class GroundedClaim(BaseModel):
    """
    A single factual statement made in narration, with explicit grounding.

    ``confirmed`` claims must cite at least one valid ``EvidenceReference``.
    ``uncertain`` claims must explain the uncertainty so it can be voiced or omitted.
    """
    statement: str = Field(..., min_length=1)
    grounding_status: GroundingStatus = GroundingStatus.INFERRED
    source: Optional[UnderstandingSource] = None
    evidence: List[EvidenceReference] = Field(default_factory=list)
    uncertainty_note: Optional[str] = None

    @model_validator(mode="after")
    def _grounding_is_consistent(self) -> "GroundedClaim":
        if self.grounding_status == GroundingStatus.CONFIRMED:
            if not any(ref.is_valid for ref in self.evidence):
                raise ValueError(
                    "A 'confirmed' claim requires at least one valid EvidenceReference; "
                    "use 'inferred' or 'uncertain' when evidence is insufficient."
                )
        if self.grounding_status == GroundingStatus.UNCERTAIN and not (self.uncertainty_note or "").strip():
            raise ValueError("An 'uncertain' claim requires an uncertainty_note explaining what is not established.")
        return self


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------


class ScriptSection(BaseModel):
    """An ordered narration section of an educational script."""
    section_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    order: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    purpose: SectionPurpose = SectionPurpose.OTHER
    purpose_description: Optional[str] = None  # Free-text narrative purpose

    is_narrated: bool = True
    narration_text: str = ""
    estimated_duration_seconds: float = Field(..., gt=0)

    related_components: List[ComponentReference] = Field(default_factory=list)
    related_workflow_steps: List[WorkflowStepReference] = Field(default_factory=list)
    related_relationships: List[ArchitectureRelationshipReference] = Field(default_factory=list)
    related_data_flows: List[DataFlowReference] = Field(default_factory=list)
    evidence: List[EvidenceReference] = Field(default_factory=list)
    claims: List[GroundedClaim] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)

    transition_to_next: Optional[str] = None

    @model_validator(mode="after")
    def _narration_present_when_narrated(self) -> "ScriptSection":
        if self.is_narrated and not self.narration_text.strip():
            raise ValueError(f"Section '{self.section_id}' is narrated but has empty narration_text.")
        return self

    @property
    def word_count(self) -> int:
        return count_words(self.narration_text)

    def has_grounding(self) -> bool:
        """True if the section cites any evidence directly or through its references/claims."""
        return bool(
            self.evidence
            or any(c.evidence for c in self.related_components)
            or any(w.evidence for w in self.related_workflow_steps)
            or any(r.evidence for r in self.related_relationships)
            or any(d.evidence for d in self.related_data_flows)
            or any(c.evidence for c in self.claims)
        )

    def pacing_warnings(self, pacing: NarrationPacing) -> List[str]:
        """Warns when narration is too dense or too sparse for the section's duration."""
        if not self.is_narrated:
            return []
        wpm = self.word_count * 60.0 / self.estimated_duration_seconds
        if wpm > pacing.max_comfortable_wpm:
            needed = estimate_narration_seconds(self.narration_text, pacing.words_per_minute)
            return [
                f"Section '{self.section_id}' narration is too dense: {self.word_count} words in "
                f"{self.estimated_duration_seconds:.1f}s ({wpm:.0f} wpm > {pacing.max_comfortable_wpm:.0f} wpm); "
                f"approximately {needed:.1f}s needed at {pacing.words_per_minute:.0f} wpm."
            ]
        if wpm < pacing.min_comfortable_wpm:
            return [
                f"Section '{self.section_id}' narration is sparse: {self.word_count} words in "
                f"{self.estimated_duration_seconds:.1f}s ({wpm:.0f} wpm < {pacing.min_comfortable_wpm:.0f} wpm)."
            ]
        return []


class ScriptGenerationMetadata(BaseModel):
    """Provenance of a generated script, consistent with the understanding modules."""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""
    is_fallback: bool = False
    latency_ms: float = Field(default=0.0, ge=0)
    token_usage: Optional[TokenUsageRecord] = None
    source_understandings: List[UnderstandingSource] = Field(default_factory=list)


class EducationalScript(BaseModel):
    """A complete narrated educational explainer script for a repository."""
    schema_version: str = SCRIPT_SCHEMA_VERSION
    script_id: str = Field(..., min_length=1, pattern=_ID_PATTERN)
    repository_name: str = Field(..., min_length=1)

    title: str = Field(..., min_length=1)
    introduction: str = Field(..., min_length=1)
    intended_audience: List[str] = Field(
        default_factory=lambda: ["Developers", "Students"], min_length=1
    )
    learning_objectives: List[str] = Field(..., min_length=1)

    video_format: VideoFormatSpec = Field(default_factory=VideoFormatSpec)
    target_duration: DurationTarget = Field(default_factory=DurationTarget)
    pacing: NarrationPacing = Field(default_factory=NarrationPacing)
    total_estimated_duration_seconds: float = Field(..., gt=0)

    sections: List[ScriptSection] = Field(..., min_length=1)
    conclusion: str = Field(..., min_length=1)

    evidence: List[EvidenceReference] = Field(default_factory=list)
    metadata: ScriptGenerationMetadata = Field(default_factory=ScriptGenerationMetadata)
    limitations: List[str] = Field(default_factory=list)
    static_analysis_caveats: List[str] = Field(
        default_factory=lambda: list(DEFAULT_STATIC_ANALYSIS_CAVEATS)
    )
    validation_warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_script(self) -> "EducationalScript":
        # --- Hard structural errors -----------------------------------------
        duplicates = find_duplicates([s.section_id for s in self.sections])
        if duplicates:
            raise ValueError(f"Duplicate section_id values: {duplicates}")

        orders = [s.order for s in self.sections]
        if orders != list(range(1, len(self.sections) + 1)):
            raise ValueError(
                f"Section order values must be contiguous from 1 and match list order; got {orders}"
            )

        section_total = sum(s.estimated_duration_seconds for s in self.sections)
        if abs(section_total - self.total_estimated_duration_seconds) > DURATION_TOLERANCE_SECONDS:
            raise ValueError(
                f"total_estimated_duration_seconds ({self.total_estimated_duration_seconds:.1f}s) does not match "
                f"the sum of section durations ({section_total:.1f}s) within "
                f"{DURATION_TOLERANCE_SECONDS:.1f}s tolerance."
            )

        # --- Editorial warnings (never modify content) ----------------------
        warnings: List[str] = []
        warnings += check_target_duration(self.total_estimated_duration_seconds, self.target_duration, "Script")

        for index, section in enumerate(self.sections):
            warnings += section.pacing_warnings(self.pacing)
            if section.is_narrated and not section.has_grounding() and not section.uncertainty_notes:
                warnings.append(
                    f"Section '{section.section_id}' cites no evidence and declares no uncertainty notes."
                )
            is_last = index == len(self.sections) - 1
            if not is_last and not (section.transition_to_next or "").strip():
                warnings.append(f"Section '{section.section_id}' has no transition to the next section.")

        if not self.evidence and not any(s.has_grounding() for s in self.sections):
            warnings.append("Script contains no evidence references; content grounding cannot be traced.")

        self.validation_warnings = merge_warnings(self.validation_warnings, warnings)
        return self

    def get_section(self, section_id: str) -> Optional[ScriptSection]:
        return next((s for s in self.sections if s.section_id == section_id), None)

    @property
    def total_word_count(self) -> int:
        return sum(s.word_count for s in self.sections)

    @property
    def estimated_narration_seconds(self) -> float:
        """Narration time for all sections at the configured speaking rate."""
        return sum(
            estimate_narration_seconds(s.narration_text, self.pacing.words_per_minute) for s in self.sections
        )
