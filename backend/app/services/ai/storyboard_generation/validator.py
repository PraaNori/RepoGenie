"""
Validator and timing synchronizer for AI-Powered Storyboard Generation (Milestone 4, Phase 3).

Responsibilities:
1. Script Synchronization:
   - Verifies `script_id` matches the source script.
   - Ensures all scenes reference valid `script_section_id`s in sequential order.
   - Ensures every script section is covered by at least one scene.
   - Performs deterministic timing reconciliation so each section's scenes sum
     to the section duration, and the storyboard total equals the script total.
2. Grounding & Anti-Hallucination:
   - Verifies referenced repository files and components against repository inventory.
   - Enforces `runtime_execution_verified = False` on all workflow steps.
   - Checks on-screen text and visual descriptions for prohibited runtime claims
     or unsupported performance/security guarantees.
   - Validates narration excerpts against actual section narration text.
3. Invariant Enforcement:
   - Ensures contiguous scene numbering (1..N) and unique scene IDs.
   - Calls ``EducationalStoryboard.validate_against_script(script)``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from ..project_understanding.schemas import EvidenceReference
from ..project_understanding.validator import EvidenceValidator, evidence_validator as default_evidence_validator
from ..script_generation.schemas import (
    ComponentReference,
    EducationalScript,
    ScriptSection,
    SectionPurpose,
    VideoFormatSpec,
    WorkflowStepReference,
    merge_warnings,
)
from ..workflow_understanding.snippet_extractor import WorkflowSnippetExtractor, workflow_snippet_extractor
from .schemas import (
    EducationalStoryboard,
    NarrationReference,
    StoryboardScene,
    StoryboardScriptMismatchError,
    VisualType,
)

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from .evidence_builder import StoryboardEvidencePackage

logger = logging.getLogger(__name__)

# Patterns indicating prohibited claims that static analysis verified runtime execution
_RUNTIME_CLAIM_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bruntime\s+execution\s+(?:is|was|has\s+been)\s+(?:verified|proven|confirmed|guaranteed)\b", re.I),
    re.compile(r"\b(?:verified|proven|confirmed)\s+(?:at|during)\s+runtime\b", re.I),
    re.compile(r"\bstatic\s+analysis\s+(?:proves|guarantees|verifies|confirms)\s+runtime\b", re.I),
    re.compile(r"\bguaranteed\s+to\s+execute\s+at\s+runtime\b", re.I),
)

# Patterns indicating unsupported marketing or security guarantees
_UNSUPPORTED_GUARANTEE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\b100%\s+(?:secure|bug[- ]free|reliable|safe)\b", re.I),
    re.compile(r"\bguaranteed\s+(?:zero[- ]latency|hack[- ]proof|vulnerability[- ]free)\b", re.I),
    re.compile(r"\bproven\s+in\s+production\s+at\s+enterprise\s+scale\b", re.I),
)


def _has_runtime_verification_claim(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in _RUNTIME_CLAIM_PATTERNS)


def _has_unsupported_guarantee(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in _UNSUPPORTED_GUARANTEE_PATTERNS)


def _coerce_visual_type(raw_val: Any) -> VisualType:
    if isinstance(raw_val, VisualType):
        return raw_val
    if isinstance(raw_val, str):
        norm = raw_val.strip().lower().replace("-", "_").replace(" ", "_")
        for member in VisualType:
            if member.value == norm:
                return member
        if "title" in norm or "intro" in norm or "hook" in norm:
            return VisualType.TITLE_CARD
        if "arch" in norm or "system" in norm:
            return VisualType.ARCHITECTURE_DIAGRAM
        if "comp" in norm or "module" in norm:
            return VisualType.COMPONENT_DIAGRAM
        if "code" in norm or "syntax" in norm or "walkthrough" in norm:
            return VisualType.CODE_WALKTHROUGH
        if "workflow" in norm or "call" in norm or "step" in norm:
            return VisualType.WORKFLOW_DIAGRAM
        if "data" in norm or "flow" in norm:
            return VisualType.DATA_FLOW_VISUALIZATION
        if "tech" in norm or "stack" in norm:
            return VisualType.TECHNOLOGY_OVERVIEW
        if "sum" in norm or "conclu" in norm or "outro" in norm:
            return VisualType.SUMMARY_CARD
    return VisualType.OTHER


class StoryboardValidator:
    """Validates and synchronizes an EducationalStoryboard with an EducationalScript."""

    def __init__(
        self,
        evidence_validator: Optional[EvidenceValidator] = None,
        redactor: Optional[WorkflowSnippetExtractor] = None,
    ):
        self.evidence_validator = evidence_validator or default_evidence_validator
        self.redactor = redactor or workflow_snippet_extractor

    def _clean_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        cleaned = " ".join(str(text).split())
        return self.redactor.redact_embedded_secrets(cleaned)

    def normalize_and_reconcile_raw_storyboard(
        self,
        raw_dict: Dict[str, Any],
        script: EducationalScript,
        knowledge: RepositoryKnowledge,
        evidence_package: Optional[StoryboardEvidencePackage] = None,
        local_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Normalizes raw LLM output, enforces script binding, synchronizes timings
        deterministically, filters unsupported files/components, and prepares a
        dictionary ready for ``EducationalStoryboard.model_validate``.
        """
        if not isinstance(raw_dict, dict):
            raise ValueError("LLM storyboard output must be a JSON object.")

        warnings: List[str] = list(raw_dict.get("validation_warnings") or [])
        known_files, line_counts, has_complete_inventory = (
            self.evidence_validator.get_repository_inventory_and_line_counts(knowledge, local_path)
        )

        storyboard_id = str(raw_dict.get("storyboard_id") or f"sb-{script.script_id}").strip()
        storyboard_id = re.sub(r"\s+", "-", storyboard_id) or f"sb-{script.script_id}"

        title = self._clean_text(raw_dict.get("title") or f"{script.title} Storyboard")

        # Map script sections
        section_map: Dict[str, ScriptSection] = {s.section_id: s for s in script.sections}
        section_order_map: Dict[str, int] = {s.section_id: s.order for s in script.sections}

        raw_scenes = raw_dict.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("LLM storyboard output must contain a non-empty 'scenes' list.")

        # Group raw scenes by valid script_section_id
        grouped_scenes: Dict[str, List[Dict[str, Any]]] = {s.section_id: [] for s in script.sections}
        unrecognized_scenes: List[Dict[str, Any]] = []

        for raw_scene in raw_scenes:
            if not isinstance(raw_scene, dict):
                continue
            sec_ref = str(raw_scene.get("script_section_id") or "").strip()
            if sec_ref in grouped_scenes:
                grouped_scenes[sec_ref].append(raw_scene)
            else:
                # Try finding closest matching section ID if LLM slightly altered it
                matched_sec = None
                for valid_sec_id in grouped_scenes:
                    if sec_ref.lower().replace("-", "") == valid_sec_id.lower().replace("-", ""):
                        matched_sec = valid_sec_id
                        break
                if matched_sec:
                    warnings.append(
                        f"Mapped scene referencing '{sec_ref}' to existing section '{matched_sec}'."
                    )
                    raw_scene["script_section_id"] = matched_sec
                    grouped_scenes[matched_sec].append(raw_scene)
                else:
                    unrecognized_scenes.append(raw_scene)

        if unrecognized_scenes:
            unrec_details = [
                f"{s.get('scene_id')} (referencing '{s.get('script_section_id')}')"
                for s in unrecognized_scenes
            ]
            warnings.append(
                f"Ignored {len(unrecognized_scenes)} scenes referencing non-existent script sections: {', '.join(unrec_details)}"
            )

        # Ensure every script section has at least one scene
        for sec in script.sections:
            if not grouped_scenes[sec.section_id]:
                warnings.append(
                    f"Script section '{sec.section_id}' was missing from generated scenes; generated default grounded scene."
                )
                default_visual_type = (
                    VisualType.TITLE_CARD if sec.purpose == SectionPurpose.HOOK
                    else VisualType.SUMMARY_CARD if sec.purpose == SectionPurpose.CONCLUSION
                    else VisualType.ARCHITECTURE_DIAGRAM
                )
                comp_names = [c.name for c in sec.related_components[:3]]
                comp_desc = f" showing {', '.join(comp_names)}" if comp_names else ""
                grouped_scenes[sec.section_id].append({
                    "scene_id": f"scene-{sec.order}",
                    "script_section_id": sec.section_id,
                    "title": f"{sec.title} Visual",
                    "purpose": f"Illustrate {sec.title}",
                    "estimated_duration_seconds": sec.estimated_duration_seconds,
                    "visual_type": default_visual_type.value,
                    "visual_description": f"Visual representation of {sec.title}{comp_desc}.",
                    "on_screen_text": [sec.title[:40]],
                    "narration": {
                        "script_section_id": sec.section_id,
                        "excerpt": None,
                    },
                    "related_files": [c.file_path for c in sec.related_components if c.file_path],
                    "related_components": [c.model_dump() for c in sec.related_components],
                    "related_workflow_steps": [w.model_dump() for w in sec.related_workflow_steps],
                    "evidence": [e.model_dump() for e in sec.evidence],
                    "transition_to_next": "Cut to next scene",
                })

        # Deterministic Duration Reconciliation per section:
        # For each section, scenes mapped to it must sum to section.estimated_duration_seconds exactly.
        reconciled_scenes: List[Dict[str, Any]] = []
        global_scene_counter = 1

        for sec in script.sections:
            sec_scenes = grouped_scenes[sec.section_id]
            sec_duration = round(sec.estimated_duration_seconds, 2)
            m = len(sec_scenes)

            # Compute raw durations
            raw_durations: List[float] = []
            for sc in sec_scenes:
                try:
                    d = float(sc.get("estimated_duration_seconds") or 0.0)
                except (TypeError, ValueError):
                    d = 0.0
                raw_durations.append(d if d > 0 else 1.0)

            # Reconcile durations
            if m == 1:
                reconciled_durations = [sec_duration]
            else:
                raw_sum = sum(raw_durations)
                if raw_sum <= 0:
                    base_dur = round(sec_duration / m, 2)
                    reconciled_durations = [base_dur] * m
                else:
                    reconciled_durations = [
                        round(d * (sec_duration / raw_sum), 2) for d in raw_durations
                    ]
                # Adjust for small float rounding diffs so sum equals sec_duration exactly
                diff = round(sec_duration - sum(reconciled_durations), 2)
                if abs(diff) > 0.0001:
                    max_idx = reconciled_durations.index(max(reconciled_durations))
                    reconciled_durations[max_idx] = round(reconciled_durations[max_idx] + diff, 2)

            for idx_in_sec, raw_scene in enumerate(sec_scenes):
                assigned_duration = reconciled_durations[idx_in_sec]
                scene_id = str(raw_scene.get("scene_id") or f"scene-{global_scene_counter}").strip()
                scene_id = re.sub(r"\s+", "-", scene_id) or f"scene-{global_scene_counter}"

                sc_title = self._clean_text(raw_scene.get("title") or f"Scene {global_scene_counter}")
                sc_purpose = self._clean_text(raw_scene.get("purpose") or f"Illustrate {sec.title}")
                sc_visual_type = _coerce_visual_type(raw_scene.get("visual_type"))
                sc_visual_desc = self._clean_text(raw_scene.get("visual_description") or f"Visual view of {sc_title}")
                sc_layout_hint = self._clean_text(raw_scene.get("layout_hint")) or None

                # On-screen text
                on_screen_text: List[str] = []
                for ost in raw_scene.get("on_screen_text") or []:
                    clean_ost = self._clean_text(str(ost))
                    if not clean_ost:
                        continue
                    if _has_runtime_verification_claim(clean_ost):
                        warnings.append(
                            f"Scene '{scene_id}': dropped prohibited runtime execution claim from on-screen text: '{clean_ost}'."
                        )
                        continue
                    if _has_unsupported_guarantee(clean_ost):
                        warnings.append(
                            f"Scene '{scene_id}': dropped unsupported guarantee from on-screen text: '{clean_ost}'."
                        )
                        continue
                    on_screen_text.append(clean_ost)

                if not on_screen_text:
                    on_screen_text = [sec.title[:40]]

                # Narration reference
                narration_dict = raw_scene.get("narration") or {}
                excerpt = narration_dict.get("excerpt") if isinstance(narration_dict, dict) else None
                if excerpt is not None:
                    excerpt_clean = self._clean_text(str(excerpt))
                    if excerpt_clean and excerpt_clean not in sec.narration_text:
                        # Check case-insensitive match or substring
                        found_excerpt = False
                        for chunk in sec.narration_text.split(". "):
                            if excerpt_clean.lower() in chunk.lower():
                                excerpt_clean = chunk
                                found_excerpt = True
                                break
                        if not found_excerpt:
                            warnings.append(
                                f"Scene '{scene_id}': narration excerpt did not appear in section narration; set to null."
                            )
                            excerpt_clean = None
                    excerpt = excerpt_clean

                # Grounding: related files
                valid_files: List[str] = []
                for fp in raw_scene.get("related_files") or []:
                    norm_fp = str(fp).replace("\\", "/").strip().lstrip("/")
                    if not norm_fp:
                        continue
                    if self.redactor.is_sensitive_file(norm_fp):
                        warnings.append(f"Scene '{scene_id}': excluded sensitive file '{norm_fp}'.")
                        continue
                    if has_complete_inventory and norm_fp not in known_files and not any(k.endswith(norm_fp) for k in known_files):
                        warnings.append(f"Scene '{scene_id}': rejected nonexistent file '{norm_fp}'.")
                        continue
                    valid_files.append(norm_fp)

                # Grounding: related components
                valid_components: List[Dict[str, Any]] = []
                sec_comp_ids = {c.component_id for c in sec.related_components}
                for c in sec.related_components:
                    valid_components.append(c.model_dump())

                # Grounding: related workflow steps (force runtime_execution_verified = False)
                valid_wf_steps: List[Dict[str, Any]] = []
                for w in sec.related_workflow_steps:
                    w_dict = w.model_dump()
                    w_dict["runtime_execution_verified"] = False
                    valid_wf_steps.append(w_dict)

                # Evidence
                valid_evidence: List[Dict[str, Any]] = []
                for ev in sec.evidence:
                    valid_evidence.append(ev.model_dump())

                # Check visual description for prohibited runtime claims
                if _has_runtime_verification_claim(sc_visual_desc):
                    warnings.append(
                        f"Scene '{scene_id}': visual description contained a prohibited runtime claim; adjusted."
                    )
                    sc_visual_desc = re.sub(
                        r"(?i)\b(?:runtime\s+execution\s+is\s+verified|verified\s+at\s+runtime)\b",
                        "statically traced execution",
                        sc_visual_desc,
                    )

                transition = raw_scene.get("transition_to_next")
                if transition is not None:
                    transition = self._clean_text(str(transition)) or None

                reconciled_scenes.append({
                    "scene_id": scene_id,
                    "scene_number": global_scene_counter,
                    "script_section_id": sec.section_id,
                    "title": sc_title,
                    "purpose": sc_purpose,
                    "estimated_duration_seconds": assigned_duration,
                    "visual_type": sc_visual_type,
                    "visual_description": sc_visual_desc,
                    "on_screen_text": on_screen_text[:3],
                    "narration": {
                        "script_section_id": sec.section_id,
                        "excerpt": excerpt,
                    },
                    "layout_hint": sc_layout_hint,
                    "related_files": sorted(set(valid_files))[:4],
                    "related_components": valid_components,
                    "related_workflow_steps": valid_wf_steps,
                    "evidence": valid_evidence,
                    "uncertainty_notes": list(sec.uncertainty_notes),
                    "transition_to_next": transition,
                })
                global_scene_counter += 1

        # Ensure last scene has None transition if desired, or all earlier have a transition
        for idx, sc in enumerate(reconciled_scenes):
            is_last = idx == len(reconciled_scenes) - 1
            if not is_last and not (sc.get("transition_to_next") or "").strip():
                sc["transition_to_next"] = "Cut to next scene"

        total_duration = round(sum(s["estimated_duration_seconds"] for s in reconciled_scenes), 2)

        return {
            "schema_version": "1.0",
            "storyboard_id": storyboard_id,
            "script_id": script.script_id,
            "title": title,
            "video_format": script.video_format.model_dump(),
            "target_duration": script.target_duration.model_dump(),
            "total_estimated_duration_seconds": total_duration,
            "scenes": reconciled_scenes,
            "validation_warnings": warnings,
        }

    def validate_storyboard(
        self,
        storyboard: EducationalStoryboard,
        script: EducationalScript,
        knowledge: RepositoryKnowledge,
        local_path: Optional[str] = None,
    ) -> EducationalStoryboard:
        """
        Validates an instantiated ``EducationalStoryboard`` against ``script``
        and ``knowledge`` using ``validate_against_script``.
        """
        cross_warnings = storyboard.validate_against_script(script)
        storyboard.validation_warnings = merge_warnings(
            storyboard.validation_warnings, cross_warnings
        )
        return storyboard


storyboard_validator = StoryboardValidator()
