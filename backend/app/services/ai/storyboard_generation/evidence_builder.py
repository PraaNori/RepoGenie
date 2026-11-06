"""
Evidence builder for AI-Powered Storyboard Generation (Milestone 4, Phase 3).

Constructs a compact, structured, evidence-grounded package from:
1. ``EducationalScript``               (required)
2. ``RepositoryKnowledge``              (required)
3. ``ProjectUnderstanding``             (optional)
4. ``RepositoryCodeUnderstanding``      (optional)
5. ``RepositoryWorkflowUnderstanding``  (optional)

Design principles:
- Prioritizes the completed script's sections, narration, timing, claims, and evidence.
- Provides grounded architectural context (components, relationships, workflow steps, data flows).
- Applies secret redaction, sensitive file filtering, and character budgeting.
- Does not re-invent or alter the script's narrative.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from ..project_understanding.schemas import EvidenceReference
from ..project_understanding.validator import EvidenceValidator, evidence_validator as default_evidence_validator
from ..script_generation.schemas import EducationalScript, UnderstandingSource
from ..workflow_understanding.snippet_extractor import WorkflowSnippetExtractor, workflow_snippet_extractor

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..code_understanding.schemas import RepositoryCodeUnderstanding
    from ..project_understanding.schemas import ProjectUnderstanding
    from ..workflow_understanding.schemas import RepositoryWorkflowUnderstanding

logger = logging.getLogger(__name__)

DEFAULT_MAX_STORYBOARD_EVIDENCE_CHARS = 12000

_EXTRA_SECRET_RE_GSK = re.compile(r"\bgsk_[A-Za-z0-9_\-]{20,}\b")
_EXTRA_SECRET_RE_KV = re.compile(
    r"(?i)\b((?:api[_-]?key|secret[_-]?key|client[_-]?secret|password|passwd|auth[_-]?token|access[_-]?token)\s*[:=]\s*)(['\"][^'\"]{6,}['\"]|[A-Za-z0-9_\-\.]{16,})"
)


def _clip(text: Optional[str], limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class StoryboardSectionContext(BaseModel):
    """Context for a single script section to be illustrated in the storyboard."""
    section_id: str
    order: int
    title: str
    purpose: str
    purpose_description: Optional[str] = None
    estimated_duration_seconds: float
    narration_text: str
    word_count: int
    related_component_ids: List[str] = Field(default_factory=list)
    related_workflow_steps: List[str] = Field(default_factory=list)
    claims: List[str] = Field(default_factory=list)
    evidence_files: List[str] = Field(default_factory=list)
    transition_to_next: Optional[str] = None


class StoryboardComponentContext(BaseModel):
    """Grounded repository component information available for visual representation."""
    component_id: str
    name: str
    file_path: str
    category: str
    primary_responsibility: str
    key_symbols: List[str] = Field(default_factory=list)


class StoryboardInteractionContext(BaseModel):
    """Statically confirmed component interaction for architecture diagrams."""
    source_component: str
    target_component: str
    interaction_type: str
    description: str


class StoryboardWorkflowContext(BaseModel):
    """Statically traced workflow steps for workflow diagrams."""
    workflow_id: str
    name: str
    trigger: str
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    data_flows: List[Dict[str, Any]] = Field(default_factory=list)


class StoryboardEvidencePackage(BaseModel):
    """Complete grounded context provided to the storyboard generation LLM."""
    script_id: str
    repository_name: str
    script_title: str
    total_duration_seconds: float
    video_orientation: str = "landscape"
    aspect_ratio: str = "16:9"

    sections: List[StoryboardSectionContext] = Field(default_factory=list)
    components: List[StoryboardComponentContext] = Field(default_factory=list)
    interactions: List[StoryboardInteractionContext] = Field(default_factory=list)
    workflows: List[StoryboardWorkflowContext] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)

    available_sources: List[UnderstandingSource] = Field(default_factory=list)
    missing_sources: List[UnderstandingSource] = Field(default_factory=list)
    upstream_fallback_sources: List[UnderstandingSource] = Field(default_factory=list)

    excluded_sensitive_paths: List[str] = Field(default_factory=list)
    redaction_applied: bool = False
    used_chars: int = 0
    max_chars: int = DEFAULT_MAX_STORYBOARD_EVIDENCE_CHARS

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "script_id": self.script_id,
            "repository_name": self.repository_name,
            "script_title": self.script_title,
            "total_duration_seconds": self.total_duration_seconds,
            "video_format": {
                "orientation": self.video_orientation,
                "aspect_ratio": self.aspect_ratio,
            },
            "script_sections": [s.model_dump() for s in self.sections],
            "grounded_components": [c.model_dump() for c in self.components],
            "architecture_interactions": [i.model_dump() for i in self.interactions],
            "workflows": [w.model_dump() for w in self.workflows],
            "technologies": self.technologies,
            "missing_sources": [s.value for s in self.missing_sources],
        }

    def to_prompt_json(self) -> str:
        return json.dumps(self.to_prompt_dict(), indent=1, ensure_ascii=False)


class StoryboardEvidenceBuilder:
    """Builds a compact, grounded ``StoryboardEvidencePackage``."""

    def __init__(
        self,
        evidence_validator: Optional[EvidenceValidator] = None,
        redactor: Optional[WorkflowSnippetExtractor] = None,
        max_chars: int = DEFAULT_MAX_STORYBOARD_EVIDENCE_CHARS,
    ):
        self.evidence_validator = evidence_validator or default_evidence_validator
        self.redactor = redactor or workflow_snippet_extractor
        self.max_chars = max_chars

    def _redact(self, text: Optional[str], limit: int = 300) -> str:
        clipped = _clip(text, limit)
        redacted = self.redactor.redact_embedded_secrets(clipped)
        redacted = _EXTRA_SECRET_RE_GSK.sub("<REDACTED_SECRET>", redacted)
        redacted = _EXTRA_SECRET_RE_KV.sub(r'\1"<REDACTED_SECRET>"', redacted)
        if redacted != clipped:
            self._redaction_applied = True
        return redacted

    def build_evidence_package(
        self,
        script: EducationalScript,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        local_path: Optional[str] = None,
        max_chars: Optional[int] = None,
    ) -> StoryboardEvidencePackage:
        if script is None:
            raise ValueError("EducationalScript is required to build a storyboard evidence package.")
        if knowledge is None:
            raise ValueError("RepositoryKnowledge is required to build a storyboard evidence package.")

        budget = max_chars or self.max_chars
        self._redaction_applied = False
        self._sensitive_paths: Set[str] = set()

        known_files, _, _ = self.evidence_validator.get_repository_inventory_and_line_counts(
            knowledge, local_path
        )
        for f in known_files:
            norm_f = f.replace("\\", "/").strip().lstrip("/")
            if self.redactor.is_sensitive_file(norm_f):
                self._sensitive_paths.add(norm_f)

        available = [UnderstandingSource.REPOSITORY_KNOWLEDGE]
        missing: List[UnderstandingSource] = []
        fallback: List[UnderstandingSource] = []

        for source, obj in (
            (UnderstandingSource.PROJECT_UNDERSTANDING, project_understanding),
            (UnderstandingSource.CODE_UNDERSTANDING, code_understanding),
            (UnderstandingSource.WORKFLOW_UNDERSTANDING, workflow_understanding),
        ):
            if obj is None:
                missing.append(source)
            else:
                available.append(source)
                if getattr(obj, "is_fallback", False):
                    fallback.append(source)

        # 1. Package script sections
        section_contexts: List[StoryboardSectionContext] = []
        for sec in script.sections:
            ev_files = []
            for ev in sec.evidence:
                fp = ev.file_path.replace("\\", "/").strip().lstrip("/")
                if self.redactor.is_sensitive_file(fp):
                    self._sensitive_paths.add(fp)
                    continue
                ev_files.append(fp)

            comp_ids = [
                c.component_id for c in sec.related_components
                if not self.redactor.is_sensitive_file(c.component_id)
            ]
            wf_step_keys = [
                f"{w.workflow_id}#{w.step_number}" for w in sec.related_workflow_steps
            ]
            claim_texts = [self._redact(c.statement, 150) for c in sec.claims[:3]]

            section_contexts.append(
                StoryboardSectionContext(
                    section_id=sec.section_id,
                    order=sec.order,
                    title=self._redact(sec.title, 80),
                    purpose=sec.purpose.value,
                    purpose_description=self._redact(sec.purpose_description, 120) if sec.purpose_description else None,
                    estimated_duration_seconds=sec.estimated_duration_seconds,
                    narration_text=self._redact(sec.narration_text, 1000),
                    word_count=sec.word_count,
                    related_component_ids=comp_ids,
                    related_workflow_steps=wf_step_keys,
                    claims=claim_texts,
                    evidence_files=sorted(set(ev_files))[:3],
                    transition_to_next=self._redact(sec.transition_to_next, 80) if sec.transition_to_next else None,
                )
            )

        # 2. Package components from CodeUnderstanding or RepositoryKnowledge
        comp_contexts: List[StoryboardComponentContext] = []
        if code_understanding and code_understanding.components:
            for comp in code_understanding.components[:5]:
                fp = comp.file_path.replace("\\", "/").strip().lstrip("/")
                if self.redactor.is_sensitive_file(fp):
                    self._sensitive_paths.add(fp)
                    continue
                symbols = [
                    e.name for e in comp.code_explanations[:2]
                ] or comp.key_classes_and_functions[:2]
                comp_contexts.append(
                    StoryboardComponentContext(
                        component_id=comp.component_id,
                        name=self._redact(comp.name, 60),
                        file_path=fp,
                        category=comp.category,
                        primary_responsibility=self._redact(comp.primary_responsibility, 150),
                        key_symbols=[self._redact(s, 50) for s in symbols],
                    )
                )
        else:
            for f in knowledge.important_files[:4]:
                fp = f.relative_path.replace("\\", "/").strip().lstrip("/")
                if self.redactor.is_sensitive_file(fp):
                    self._sensitive_paths.add(fp)
                    continue
                comp_contexts.append(
                    StoryboardComponentContext(
                        component_id=fp,
                        name=self._redact(fp.rsplit("/", 1)[-1], 60),
                        file_path=fp,
                        category=f.category,
                        primary_responsibility=self._redact(f.reason, 150),
                        key_symbols=[],
                    )
                )

        # 3. Package interactions
        interaction_contexts: List[StoryboardInteractionContext] = []
        if code_understanding and code_understanding.cross_component_interactions:
            for inter in code_understanding.cross_component_interactions[:4]:
                if self.redactor.is_sensitive_file(inter.source_component) or self.redactor.is_sensitive_file(inter.target_component):
                    continue
                interaction_contexts.append(
                    StoryboardInteractionContext(
                        source_component=inter.source_component,
                        target_component=inter.target_component,
                        interaction_type=inter.interaction_type,
                        description=self._redact(inter.description, 120),
                    )
                )

        # 4. Package workflows
        workflow_contexts: List[StoryboardWorkflowContext] = []
        if workflow_understanding and workflow_understanding.workflows:
            for wf in workflow_understanding.workflows[:2]:
                steps_data = []
                for step in wf.steps[:4]:
                    steps_data.append({
                        "step_number": step.step_number,
                        "title": self._redact(step.title, 60),
                        "component_id": step.component_id,
                        "action_type": step.action_type,
                        "description": self._redact(step.description, 120),
                    })
                flows_data = []
                for df in wf.data_flows[:2]:
                    flows_data.append({
                        "flow_id": df.flow_id,
                        "data_item_name": self._redact(df.data_item_name, 50),
                        "origin": df.origin.name,
                        "destination": df.destination.name,
                        "status": df.data_relationship_status,
                    })
                workflow_contexts.append(
                    StoryboardWorkflowContext(
                        workflow_id=wf.workflow_id,
                        name=self._redact(wf.name, 70),
                        trigger=self._redact(wf.trigger, 80),
                        steps=steps_data,
                        data_flows=flows_data,
                    )
                )

        # 5. Technologies
        technologies: List[str] = []
        for tech in (knowledge.technology_stack.languages + knowledge.technology_stack.frameworks + knowledge.technology_stack.databases)[:6]:
            technologies.append(f"{tech.name} ({tech.category})")

        pkg = StoryboardEvidencePackage(
            script_id=script.script_id,
            repository_name=script.repository_name,
            script_title=self._redact(script.title, 120),
            total_duration_seconds=script.total_estimated_duration_seconds,
            video_orientation=script.video_format.orientation.value,
            aspect_ratio=script.video_format.aspect_ratio,
            sections=section_contexts,
            components=comp_contexts,
            interactions=interaction_contexts,
            workflows=workflow_contexts,
            technologies=technologies,
            available_sources=available,
            missing_sources=missing,
            upstream_fallback_sources=fallback,
            excluded_sensitive_paths=sorted(self._sensitive_paths),
            redaction_applied=self._redaction_applied,
            max_chars=budget,
        )

        prompt_str = pkg.to_prompt_json()
        pkg.used_chars = len(prompt_str)

        # If budget exceeded, trim component key symbols or interactions cleanly
        if pkg.used_chars > budget:
            pkg.interactions = pkg.interactions[:2]
            for c in pkg.components:
                c.key_symbols = c.key_symbols[:1]
            pkg.used_chars = len(pkg.to_prompt_json())

        return pkg


storyboard_evidence_builder = StoryboardEvidenceBuilder()
