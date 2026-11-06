"""
Validator and grounding normalizer for Educational Script Generation (Milestone 4, Phase 2).

Responsibilities
----------------
1. Resolve ``evidence_ids`` emitted by the LLM against the ``ScriptEvidencePackage``
   so file paths, line ranges, component identities, and static workflow flags
   come directly from verified repository artifacts rather than free-form LLM text.
2. Re-verify every ``EvidenceReference`` against ``RepositoryKnowledge`` using the
   shared ``EvidenceValidator`` (path existence and line-range bounds).
3. Enforce claim grounding rules:
   - ``confirmed`` claims must have at least one verified ``EvidenceReference`` and
     cannot exceed the supporting evidence item's ``grounding_hint``.
   - ``inferred`` claims must be grounded in available evidence or clearly marked.
   - ``uncertain`` claims must include a non-empty ``uncertainty_note``.
   - Unsupported or hallucinated claims (citing non-existent files/IDs or making
     prohibited runtime-verification / unverified performance/security guarantees)
     are rejected and recorded in ``validation_warnings``.
4. Enforce static-analysis invariants:
   - ``runtime_execution_verified`` is always ``False``.
   - Static-analysis caveats and missing-understanding limitations are always
     preserved on the resulting ``EducationalScript``.
5. Check spoken narration quality (no raw file paths or signatures read aloud,
   speaking-rate pacing, and 60–90 s target duration warnings without silent
   truncation).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from ..project_understanding.schemas import EvidenceReference
from ..project_understanding.validator import EvidenceValidator, evidence_validator as default_evidence_validator
from ..workflow_understanding.snippet_extractor import WorkflowSnippetExtractor, workflow_snippet_extractor
from .evidence_builder import ScriptEvidenceItem, ScriptEvidencePackage
from .schemas import (
    DEFAULT_STATIC_ANALYSIS_CAVEATS,
    DURATION_TOLERANCE_SECONDS,
    ArchitectureRelationshipReference,
    ComponentReference,
    DataFlowReference,
    DurationTarget,
    EducationalScript,
    GroundedClaim,
    GroundingStatus,
    NarrationPacing,
    ScriptSection,
    SectionPurpose,
    UnderstandingSource,
    VideoFormatSpec,
    WorkflowStepReference,
    check_target_duration,
    estimate_narration_seconds,
    merge_warnings,
)

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge

logger = logging.getLogger(__name__)

# Patterns that indicate prohibited runtime-execution verification claims
_RUNTIME_CLAIM_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bruntime\s+execution\s+(?:is|was|has\s+been)\s+(?:verified|proven|confirmed|guaranteed)\b", re.I),
    re.compile(r"\b(?:verified|proven|confirmed)\s+(?:at|during)\s+runtime\b", re.I),
    re.compile(r"\bstatic\s+analysis\s+(?:proves|guarantees|verifies|confirms)\s+runtime\b", re.I),
    re.compile(r"\bguaranteed\s+to\s+execute\s+at\s+runtime\b", re.I),
)

# Patterns that indicate unsupported marketing/performance/security guarantees
_UNSUPPORTED_GUARANTEE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\b100%\s+(?:secure|bug[- ]free|reliable|safe)\b", re.I),
    re.compile(r"\bguaranteed\s+(?:zero[- ]latency|hack[- ]proof|vulnerability[- ]free)\b", re.I),
    re.compile(r"\bproven\s+in\s+production\s+at\s+enterprise\s+scale\b", re.I),
)

# Detects file paths with directory separators and source extensions read aloud in narration
_SPOKEN_FILEPATH_RE = re.compile(
    r"\b(?:[\w.-]+/)+[\w.-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|cpp|cc|c|h|hpp|rb|php|cs|sql|yaml|yml|toml|json|md)\b"
)

# Detects raw code signatures like `def foo(bar, baz):` read aloud in narration
_SPOKEN_SIGNATURE_RE = re.compile(r"\b(?:def|function|func|fn)\s+[A-Za-z_]\w*\s*\([^)]*\)\s*:?")


def _has_runtime_verification_claim(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in _RUNTIME_CLAIM_PATTERNS)


def _has_unsupported_guarantee(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in _UNSUPPORTED_GUARANTEE_PATTERNS)


def _coerce_section_purpose(raw_purpose: Any) -> SectionPurpose:
    if isinstance(raw_purpose, SectionPurpose):
        return raw_purpose
    if isinstance(raw_purpose, str):
        norm = raw_purpose.strip().lower().replace("-", "_").replace(" ", "_")
        for member in SectionPurpose:
            if member.value == norm:
                return member
        if "hook" in norm:
            return SectionPurpose.HOOK
        if "intro" in norm:
            return SectionPurpose.INTRODUCTION
        if "problem" in norm or "motivation" in norm:
            return SectionPurpose.PROBLEM
        if "arch" in norm:
            return SectionPurpose.ARCHITECTURE_OVERVIEW
        if "tech" in norm or "stack" in norm:
            return SectionPurpose.TECHNOLOGY_OVERVIEW
        if "comp" in norm or "module" in norm or "code" in norm:
            return SectionPurpose.COMPONENT_DEEP_DIVE
        if "workflow" in norm or "execution" in norm or "flow" in norm and "data" not in norm:
            return SectionPurpose.WORKFLOW
        if "data" in norm:
            return SectionPurpose.DATA_FLOW
        if "conclu" in norm or "summary" in norm or "outro" in norm or "takeaway" in norm:
            return SectionPurpose.CONCLUSION
    return SectionPurpose.OTHER


def _coerce_grounding_status(raw_status: Any) -> GroundingStatus:
    if isinstance(raw_status, GroundingStatus):
        return raw_status
    if isinstance(raw_status, str):
        norm = raw_status.strip().lower()
        for member in GroundingStatus:
            if member.value == norm:
                return member
    return GroundingStatus.INFERRED


class ScriptValidator:
    """
    Validates and normalizes AI-generated educational scripts against
    ``RepositoryKnowledge`` and ``ScriptEvidencePackage``.
    """

    def __init__(
        self,
        evidence_validator: Optional[EvidenceValidator] = None,
        redactor: Optional[WorkflowSnippetExtractor] = None,
    ):
        self.evidence_validator = evidence_validator or default_evidence_validator
        self.redactor = redactor or workflow_snippet_extractor

    # ------------------------------------------------------------------
    # Normalization from raw LLM dict -> validated schema dict
    # ------------------------------------------------------------------

    def normalize_and_ground_raw_script(
        self,
        raw_dict: Dict[str, Any],
        evidence_package: ScriptEvidencePackage,
        knowledge: RepositoryKnowledge,
        local_path: Optional[str] = None,
        target_duration: Optional[DurationTarget] = None,
        pacing: Optional[NarrationPacing] = None,
    ) -> Dict[str, Any]:
        """
        Normalizes a raw JSON dictionary produced by the LLM, resolves cited
        ``evidence_ids`` against ``evidence_package``, verifies any explicit
        ``EvidenceReference`` items against ``knowledge``, enforces grounding
        and runtime invariants, and prepares a dictionary ready for
        ``EducationalScript.model_validate``.
        """
        if not isinstance(raw_dict, dict):
            raise ValueError("LLM script output must be a JSON object.")

        known_files, line_counts, has_complete_inventory = (
            self.evidence_validator.get_repository_inventory_and_line_counts(knowledge, local_path)
        )
        warnings: List[str] = list(raw_dict.get("validation_warnings") or [])
        target = target_duration or DurationTarget()
        pace = pacing or NarrationPacing()

        repo_name = evidence_package.repository_name
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in repo_name).strip("-") or "repo"

        script_id = str(raw_dict.get("script_id") or f"script-{slug}").strip()
        script_id = re.sub(r"\s+", "-", script_id) or f"script-{slug}"

        title = self._clean_text(raw_dict.get("title") or f"Understanding {evidence_package.project_name or repo_name}")
        introduction = self._clean_text(
            raw_dict.get("introduction")
            or f"An educational walkthrough of {evidence_package.project_name or repo_name}."
        )
        conclusion = self._clean_text(
            raw_dict.get("conclusion")
            or f"That concludes our overview of {evidence_package.project_name or repo_name}."
        )

        audience_raw = raw_dict.get("intended_audience")
        if isinstance(audience_raw, list) and any(str(a).strip() for a in audience_raw):
            intended_audience = [self._clean_text(str(a)) for a in audience_raw if str(a).strip()]
        else:
            intended_audience = ["Developers", "Students"]

        objectives_raw = raw_dict.get("learning_objectives")
        if isinstance(objectives_raw, list) and any(str(o).strip() for o in objectives_raw):
            learning_objectives = [self._clean_text(str(o)) for o in objectives_raw if str(o).strip()]
        else:
            learning_objectives = [f"Understand the architecture and workflow of {repo_name}"]

        # Top-level evidence from evidence_ids and explicit evidence
        script_evidence: List[EvidenceReference] = []
        top_ev_ids = raw_dict.get("evidence_ids") or []
        if isinstance(top_ev_ids, list):
            for eid in top_ev_ids:
                item = evidence_package.get_item(str(eid))
                if item is None:
                    warnings.append(f"Script cited unknown evidence_id '{eid}'; ignored.")
                else:
                    script_evidence.extend(item.references)
        for raw_ref in raw_dict.get("evidence") or []:
            ref = self._parse_and_verify_ref(raw_ref, known_files, line_counts, has_complete_inventory, local_path, warnings, "Script")
            if ref is not None:
                script_evidence.append(ref)

        # Sections
        raw_sections = raw_dict.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValueError("LLM script output must contain a non-empty 'sections' list.")

        normalized_sections: List[Dict[str, Any]] = []
        seen_section_ids: Set[str] = set()

        for idx, raw_sec in enumerate(raw_sections, start=1):
            if not isinstance(raw_sec, dict):
                continue

            sec_id = str(raw_sec.get("section_id") or f"sec-{idx}").strip()
            sec_id = re.sub(r"\s+", "-", sec_id) or f"sec-{idx}"
            if sec_id in seen_section_ids:
                dedup_id = f"{sec_id}-{idx}"
                warnings.append(f"Duplicate section_id '{sec_id}' renamed to '{dedup_id}'.")
                sec_id = dedup_id
            seen_section_ids.add(sec_id)

            sec_title = self._clean_text(raw_sec.get("title") or f"Section {idx}")
            purpose = _coerce_section_purpose(raw_sec.get("purpose"))
            purpose_desc = self._clean_text(raw_sec.get("purpose_description")) if raw_sec.get("purpose_description") else None

            is_narrated = bool(raw_sec.get("is_narrated", True))
            if "narration_text" in raw_sec:
                raw_narration = raw_sec.get("narration_text")
            else:
                raw_narration = raw_sec.get("narration") or raw_sec.get("text")
            narration_text = self._clean_text(raw_narration or "")

            if is_narrated and not narration_text:
                if "narration_text" not in raw_sec and normalized_sections:
                    warnings.append(
                        f"Dropped incomplete trailing section '{sec_id}' lacking narration_text."
                    )
                    continue
                raise ValueError(f"Section '{sec_id}' is marked narrated but has empty narration_text.")

            # Duration handling: ensure positive float; if missing or <= 0, estimate from word count
            raw_dur = raw_sec.get("estimated_duration_seconds")
            try:
                dur = float(raw_dur) if raw_dur is not None else 0.0
            except (TypeError, ValueError):
                dur = 0.0
            if dur <= 0:
                estimated = max(5.0, round(estimate_narration_seconds(narration_text, pace.words_per_minute), 1))
                warnings.append(
                    f"Section '{sec_id}' had invalid duration ({raw_dur}); estimated {estimated:.1f}s from narration word count."
                )
                dur = estimated

            # Resolve section evidence_ids into structured references
            sec_ev_ids = raw_sec.get("evidence_ids") or []
            resolved_items: List[ScriptEvidenceItem] = []
            if isinstance(sec_ev_ids, list):
                for eid in sec_ev_ids:
                    item = evidence_package.get_item(str(eid))
                    if item is None:
                        warnings.append(f"Section '{sec_id}' cited unknown evidence_id '{eid}'; ignored.")
                    else:
                        resolved_items.append(item)

            sec_evidence: List[EvidenceReference] = []
            sec_components: List[ComponentReference] = []
            sec_workflow_steps: List[WorkflowStepReference] = []
            sec_relationships: List[ArchitectureRelationshipReference] = []
            sec_data_flows: List[DataFlowReference] = []

            for item in resolved_items:
                sec_evidence.extend(item.references)
                self._populate_references_from_item(
                    item,
                    sec_components,
                    sec_workflow_steps,
                    sec_relationships,
                    sec_data_flows,
                )

            # Also validate any explicit evidence / references on the section
            for raw_ref in raw_sec.get("evidence") or []:
                ref = self._parse_and_verify_ref(
                    raw_ref, known_files, line_counts, has_complete_inventory, local_path, warnings, f"Section '{sec_id}'"
                )
                if ref is not None:
                    sec_evidence.append(ref)

            for raw_comp in raw_sec.get("related_components") or []:
                comp = self._parse_component_ref(
                    raw_comp, known_files, line_counts, has_complete_inventory, local_path, warnings, sec_id
                )
                if comp is not None:
                    sec_components.append(comp)

            for raw_wf in raw_sec.get("related_workflow_steps") or []:
                wf_ref = self._parse_workflow_step_ref(
                    raw_wf, known_files, line_counts, has_complete_inventory, local_path, warnings, sec_id
                )
                if wf_ref is not None:
                    sec_workflow_steps.append(wf_ref)

            for raw_rel in raw_sec.get("related_relationships") or []:
                rel_ref = self._parse_relationship_ref(
                    raw_rel, known_files, line_counts, has_complete_inventory, local_path, warnings, sec_id
                )
                if rel_ref is not None:
                    sec_relationships.append(rel_ref)

            for raw_df in raw_sec.get("related_data_flows") or []:
                df_ref = self._parse_data_flow_ref(
                    raw_df, known_files, line_counts, has_complete_inventory, local_path, warnings, sec_id
                )
                if df_ref is not None:
                    sec_data_flows.append(df_ref)

            # Validate claims
            sec_claims: List[GroundedClaim] = []
            sec_uncertainty_notes: List[str] = [
                self._clean_text(str(n)) for n in (raw_sec.get("uncertainty_notes") or []) if str(n).strip()
            ]
            for raw_claim in raw_sec.get("claims") or []:
                claim = self._normalize_claim(
                    raw_claim=raw_claim,
                    section_id=sec_id,
                    section_items=resolved_items,
                    evidence_package=evidence_package,
                    known_files=known_files,
                    line_counts=line_counts,
                    has_complete_inventory=has_complete_inventory,
                    local_path=local_path,
                    warnings=warnings,
                    uncertainty_notes=sec_uncertainty_notes,
                )
                if claim is not None:
                    sec_claims.append(claim)

            # Check narration text for prohibited assertions or spoken file paths
            self._check_narration_text(narration_text, sec_id, warnings)

            transition = raw_sec.get("transition_to_next")
            if transition is not None:
                transition = self._clean_text(str(transition)) or None
            if idx == len(raw_sections):
                transition = transition  # Final section may omit transition

            normalized_sections.append(
                {
                    "section_id": sec_id,
                    "order": len(normalized_sections) + 1,
                    "title": sec_title,
                    "purpose": purpose,
                    "purpose_description": purpose_desc,
                    "is_narrated": is_narrated,
                    "narration_text": narration_text,
                    "estimated_duration_seconds": round(dur, 2),
                    "related_components": self._dedup_components(sec_components),
                    "related_workflow_steps": self._dedup_workflow_steps(sec_workflow_steps),
                    "related_relationships": sec_relationships,
                    "related_data_flows": sec_data_flows,
                    "evidence": self._dedup_evidence(sec_evidence),
                    "claims": sec_claims,
                    "uncertainty_notes": sec_uncertainty_notes,
                    "transition_to_next": transition,
                }
            )

        if not normalized_sections:
            raise ValueError("No valid script sections could be constructed from LLM output.")

        # Total duration consistency: align declared total to sum of section durations
        # while recording a warning if the LLM's declared total differed by more than tolerance.
        section_sum = round(sum(s["estimated_duration_seconds"] for s in normalized_sections), 2)
        declared_total = raw_dict.get("total_estimated_duration_seconds")
        try:
            declared_val = float(declared_total) if declared_total is not None else section_sum
        except (TypeError, ValueError):
            declared_val = section_sum

        if abs(declared_val - section_sum) > DURATION_TOLERANCE_SECONDS:
            warnings.append(
                f"Declared total_estimated_duration_seconds ({declared_val:.1f}s) differed from section sum "
                f"({section_sum:.1f}s); synchronized to section sum without truncating narration."
            )

        # Combine top-level evidence with section evidence if top-level is empty
        all_script_evidence = self._dedup_evidence(
            script_evidence + [ref for s in normalized_sections for ref in s["evidence"]]
        )

        # Limitations and caveats
        limitations: List[str] = [
            self._clean_text(str(lim)) for lim in (raw_dict.get("limitations") or []) if str(lim).strip()
        ]
        for missing_src in evidence_package.missing_sources:
            note = f"Upstream '{missing_src.value}' output was not provided; script relies on remaining understanding outputs."
            if note not in limitations:
                limitations.append(note)
        for fallback_src in evidence_package.upstream_fallback_sources:
            note = f"Upstream '{fallback_src.value}' used deterministic fallback analysis."
            if note not in limitations:
                limitations.append(note)
        for trunc in evidence_package.truncation_reasons:
            if trunc not in limitations:
                limitations.append(trunc)

        caveats = list(DEFAULT_STATIC_ANALYSIS_CAVEATS)
        for c in evidence_package.static_analysis_caveats:
            if c not in caveats:
                caveats.append(c)

        return {
            "schema_version": "1.0",
            "script_id": script_id,
            "repository_name": repo_name,
            "title": title,
            "introduction": introduction,
            "intended_audience": intended_audience,
            "learning_objectives": learning_objectives,
            "video_format": raw_dict.get("video_format") or VideoFormatSpec().model_dump(),
            "target_duration": target.model_dump(),
            "pacing": pace.model_dump(),
            "total_estimated_duration_seconds": section_sum,
            "sections": normalized_sections,
            "conclusion": conclusion,
            "evidence": all_script_evidence,
            "limitations": limitations,
            "static_analysis_caveats": caveats,
            "validation_warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Post-validation of an EducationalScript instance
    # ------------------------------------------------------------------

    def validate_script(
        self,
        script: EducationalScript,
        knowledge: RepositoryKnowledge,
        evidence_package: Optional[ScriptEvidencePackage] = None,
        local_path: Optional[str] = None,
    ) -> EducationalScript:
        """
        Validates every evidence reference, component reference, workflow step
        reference, claim, and narration section on ``script`` against
        ``knowledge`` (and ``evidence_package`` when available).
        """
        known_files, line_counts, has_complete_inventory = (
            self.evidence_validator.get_repository_inventory_and_line_counts(knowledge, local_path)
        )
        warnings: List[str] = list(script.validation_warnings)

        # 1. Validate top-level evidence references
        valid_top_evidence: List[EvidenceReference] = []
        for ref in script.evidence:
            if self.evidence_validator.validate_reference(
                ref, known_files, line_counts, has_complete_inventory, local_path
            ):
                valid_top_evidence.append(ref)
            else:
                warnings.append(f"Script top-level evidence '{ref.file_path}' failed verification: {ref.detail}")
        script.evidence = valid_top_evidence

        # 2. Validate each section
        for section in script.sections:
            sec_id = section.section_id
            section.narration_text = self.redactor.redact_embedded_secrets(section.narration_text)
            self._check_narration_text(section.narration_text, sec_id, warnings)

            # Section direct evidence
            valid_sec_ev: List[EvidenceReference] = []
            for ref in section.evidence:
                if self.evidence_validator.validate_reference(
                    ref, known_files, line_counts, has_complete_inventory, local_path
                ):
                    valid_sec_ev.append(ref)
                else:
                    warnings.append(f"Section '{sec_id}': unverified evidence '{ref.file_path}' ({ref.detail}).")
            section.evidence = valid_sec_ev

            # Component references
            valid_comps: List[ComponentReference] = []
            for comp in section.related_components:
                comp_path = (comp.file_path or comp.component_id or "").replace("\\", "/").strip().lstrip("/")
                comp_ev: List[EvidenceReference] = []
                for ref in comp.evidence:
                    if self.evidence_validator.validate_reference(
                        ref, known_files, line_counts, has_complete_inventory, local_path
                    ):
                        comp_ev.append(ref)
                    else:
                        warnings.append(
                            f"Section '{sec_id}' component '{comp.name}': unverified evidence '{ref.file_path}'."
                        )
                comp.evidence = comp_ev
                if comp_path and has_complete_inventory and not self._path_exists(comp_path, known_files):
                    warnings.append(
                        f"Section '{sec_id}': removed component reference '{comp.component_id}' (file not in repository inventory)."
                    )
                    continue
                valid_comps.append(comp)
            section.related_components = valid_comps

            # Workflow step references
            for wf_step in section.related_workflow_steps:
                wf_step.runtime_execution_verified = False
                valid_wf_ev: List[EvidenceReference] = []
                for ref in wf_step.evidence:
                    if self.evidence_validator.validate_reference(
                        ref, known_files, line_counts, has_complete_inventory, local_path
                    ):
                        valid_wf_ev.append(ref)
                    else:
                        warnings.append(
                            f"Section '{sec_id}' workflow step '{wf_step.workflow_id}#{wf_step.step_number}': "
                            f"unverified evidence '{ref.file_path}'."
                        )
                wf_step.evidence = valid_wf_ev

            # Claims
            valid_claims: List[GroundedClaim] = []
            for claim in section.claims:
                if _has_runtime_verification_claim(claim.statement):
                    warnings.append(
                        f"Section '{sec_id}': rejected claim asserting runtime execution verification: '{claim.statement}'."
                    )
                    continue
                if _has_unsupported_guarantee(claim.statement):
                    warnings.append(
                        f"Section '{sec_id}': rejected unsupported guarantee claim: '{claim.statement}'."
                    )
                    continue

                verified_claim_ev: List[EvidenceReference] = []
                for ref in claim.evidence:
                    if self.evidence_validator.validate_reference(
                        ref, known_files, line_counts, has_complete_inventory, local_path
                    ):
                        verified_claim_ev.append(ref)
                    else:
                        warnings.append(
                            f"Section '{sec_id}' claim '{claim.statement[:60]}': unverified evidence '{ref.file_path}'."
                        )
                claim.evidence = verified_claim_ev

                if claim.grounding_status == GroundingStatus.CONFIRMED and not verified_claim_ev:
                    warnings.append(
                        f"Section '{sec_id}': dropped 'confirmed' claim '{claim.statement[:80]}' because no valid supporting evidence remained."
                    )
                    continue

                valid_claims.append(claim)
            section.claims = valid_claims

            # Warn if section lost all grounding after verification
            if section.is_narrated and not section.has_grounding() and not section.uncertainty_notes:
                warnings.append(
                    f"Section '{sec_id}' cites no evidence and declares no uncertainty notes."
                )

        # 3. Ensure static analysis caveats are preserved
        for caveat in DEFAULT_STATIC_ANALYSIS_CAVEATS:
            if caveat not in script.static_analysis_caveats:
                script.static_analysis_caveats.append(caveat)

        if evidence_package is not None:
            for missing_src in evidence_package.missing_sources:
                note = (
                    f"Upstream '{missing_src.value}' output was not provided; "
                    f"script relies on remaining understanding outputs."
                )
                if note not in script.limitations:
                    script.limitations.append(note)

        # 4. Target duration and pacing warnings
        warnings += check_target_duration(
            script.total_estimated_duration_seconds, script.target_duration, "Script"
        )
        for section in script.sections:
            warnings += section.pacing_warnings(script.pacing)

        script.validation_warnings = merge_warnings(script.validation_warnings, warnings)
        return script

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clean_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        cleaned = " ".join(str(text).split())
        return self.redactor.redact_embedded_secrets(cleaned)

    @staticmethod
    def _path_exists(norm_path: str, known_files: Set[str]) -> bool:
        if norm_path in known_files:
            return True
        base = norm_path.rsplit("/", 1)[-1]
        return base in known_files or any(k.endswith(norm_path) for k in known_files)

    def _check_narration_text(self, narration_text: str, section_id: str, warnings: List[str]) -> None:
        if not narration_text:
            return
        if _has_runtime_verification_claim(narration_text):
            warnings.append(
                f"Section '{section_id}' narration contains a prohibited claim that static analysis verified runtime execution."
            )
        if _has_unsupported_guarantee(narration_text):
            warnings.append(
                f"Section '{section_id}' narration contains an unsupported guarantee about security, latency, or scale."
            )
        spoken_paths = _SPOKEN_FILEPATH_RE.findall(narration_text)
        if spoken_paths:
            warnings.append(
                f"Section '{section_id}' narration reads raw file path(s) aloud ({', '.join(spoken_paths[:2])}); "
                f"prefer human-readable component names in spoken narration."
            )
        if _SPOKEN_SIGNATURE_RE.search(narration_text):
            warnings.append(
                f"Section '{section_id}' narration reads a raw function signature aloud."
            )

    def _parse_and_verify_ref(
        self,
        raw_ref: Any,
        known_files: Set[str],
        line_counts: Dict[str, int],
        has_complete_inventory: bool,
        local_path: Optional[str],
        warnings: List[str],
        context: str,
    ) -> Optional[EvidenceReference]:
        if isinstance(raw_ref, EvidenceReference):
            ref = raw_ref.model_copy(deep=True)
        elif isinstance(raw_ref, dict) and raw_ref.get("file_path"):
            try:
                ref = EvidenceReference(
                    file_path=str(raw_ref["file_path"]),
                    line_start=raw_ref.get("line_start"),
                    line_end=raw_ref.get("line_end"),
                    evidence_type=str(raw_ref.get("evidence_type") or "code"),
                    confidence=str(raw_ref.get("confidence") or "high"),
                    status=str(raw_ref.get("status") or "confirmed"),
                    detail=raw_ref.get("detail"),
                )
            except Exception as exc:
                warnings.append(f"{context}: malformed EvidenceReference ignored ({exc}).")
                return None
        else:
            return None

        if self.redactor.is_sensitive_file(ref.file_path):
            warnings.append(f"{context}: sensitive file reference '{ref.file_path}' excluded.")
            return None

        if self.evidence_validator.validate_reference(
            ref, known_files, line_counts, has_complete_inventory, local_path
        ):
            return ref

        warnings.append(f"{context}: unverified evidence '{ref.file_path}' rejected ({ref.detail}).")
        return None

    def _populate_references_from_item(
        self,
        item: ScriptEvidenceItem,
        components: List[ComponentReference],
        workflow_steps: List[WorkflowStepReference],
        relationships: List[ArchitectureRelationshipReference],
        data_flows: List[DataFlowReference],
    ) -> None:
        if item.category in ("component", "code_symbol", "entry_point") and item.component_id:
            components.append(
                ComponentReference(
                    component_id=item.component_id,
                    name=item.component_name or item.title,
                    file_path=item.component_id,
                    symbol_names=list(item.symbol_names),
                    source=item.source,
                    evidence=[r.model_copy(deep=True) for r in item.references],
                )
            )
        elif item.category == "workflow_step" and item.workflow_id and item.step_number:
            ver = item.verification
            workflow_steps.append(
                WorkflowStepReference(
                    workflow_id=item.workflow_id,
                    step_number=item.step_number,
                    step_title=item.title,
                    component_id=item.component_id,
                    symbol_name=item.symbol_names[0] if item.symbol_names else None,
                    call_relationship_verified=bool(ver.get("call_relationship_verified", False)),
                    source_order_verified=bool(ver.get("source_order_verified", False)),
                    same_execution_path_verified=bool(ver.get("same_execution_path_verified", False)),
                    execution_guaranteed=bool(ver.get("execution_guaranteed", False)),
                    runtime_execution_verified=False,
                    evidence=[r.model_copy(deep=True) for r in item.references],
                )
            )
        elif item.category == "interaction" and item.source_component and item.target_component:
            relationships.append(
                ArchitectureRelationshipReference(
                    source_component=item.source_component,
                    target_component=item.target_component,
                    relationship_type=item.relationship_type or "calls",
                    is_statically_confirmed=bool(item.verification.get("statically_confirmed", False)),
                    source=item.source,
                    evidence=[r.model_copy(deep=True) for r in item.references],
                )
            )
        elif item.category == "data_flow" and item.workflow_id and item.flow_id:
            status = item.data_relationship_status or "inferred"
            if status not in ("observed", "inferred", "unknown_or_unresolved"):
                status = "inferred"
            data_flows.append(
                DataFlowReference(
                    workflow_id=item.workflow_id,
                    flow_id=item.flow_id,
                    data_item_name=item.title,
                    data_relationship_status=status,
                    evidence=[r.model_copy(deep=True) for r in item.references],
                )
            )

    def _parse_component_ref(
        self,
        raw_comp: Any,
        known_files: Set[str],
        line_counts: Dict[str, int],
        has_complete_inventory: bool,
        local_path: Optional[str],
        warnings: List[str],
        sec_id: str,
    ) -> Optional[ComponentReference]:
        if isinstance(raw_comp, ComponentReference):
            comp = raw_comp.model_copy(deep=True)
        elif isinstance(raw_comp, dict) and raw_comp.get("component_id") and raw_comp.get("name"):
            ev_list: List[EvidenceReference] = []
            for r in raw_comp.get("evidence") or []:
                ref = self._parse_and_verify_ref(
                    r, known_files, line_counts, has_complete_inventory, local_path, warnings, f"Section '{sec_id}'"
                )
                if ref is not None:
                    ev_list.append(ref)
            comp = ComponentReference(
                component_id=str(raw_comp["component_id"]),
                name=self._clean_text(str(raw_comp["name"])),
                file_path=raw_comp.get("file_path") or str(raw_comp["component_id"]),
                symbol_names=[str(s) for s in (raw_comp.get("symbol_names") or []) if str(s).strip()],
                evidence=ev_list,
            )
        else:
            return None

        comp_path = (comp.file_path or comp.component_id).replace("\\", "/").strip().lstrip("/")
        if has_complete_inventory and comp_path and not self._path_exists(comp_path, known_files):
            warnings.append(
                f"Section '{sec_id}': rejected fabricated component reference '{comp.component_id}'."
            )
            return None
        return comp

    def _parse_workflow_step_ref(
        self,
        raw_wf: Any,
        known_files: Set[str],
        line_counts: Dict[str, int],
        has_complete_inventory: bool,
        local_path: Optional[str],
        warnings: List[str],
        sec_id: str,
    ) -> Optional[WorkflowStepReference]:
        if isinstance(raw_wf, WorkflowStepReference):
            return raw_wf.model_copy(deep=True)
        if not isinstance(raw_wf, dict) or not raw_wf.get("workflow_id"):
            return None
        if raw_wf.get("runtime_execution_verified") is True:
            warnings.append(
                f"Section '{sec_id}': workflow step '{raw_wf.get('workflow_id')}' claimed runtime_execution_verified=True; forced to False."
            )
        ev_list: List[EvidenceReference] = []
        for r in raw_wf.get("evidence") or []:
            ref = self._parse_and_verify_ref(
                r, known_files, line_counts, has_complete_inventory, local_path, warnings, f"Section '{sec_id}'"
            )
            if ref is not None:
                ev_list.append(ref)
        try:
            step_num = max(1, int(raw_wf.get("step_number") or 1))
        except (TypeError, ValueError):
            step_num = 1
        return WorkflowStepReference(
            workflow_id=str(raw_wf["workflow_id"]),
            step_number=step_num,
            step_title=raw_wf.get("step_title"),
            component_id=raw_wf.get("component_id"),
            symbol_name=raw_wf.get("symbol_name"),
            call_relationship_verified=bool(raw_wf.get("call_relationship_verified", False)),
            source_order_verified=bool(raw_wf.get("source_order_verified", False)),
            same_execution_path_verified=bool(raw_wf.get("same_execution_path_verified", False)),
            execution_guaranteed=bool(raw_wf.get("execution_guaranteed", False)),
            runtime_execution_verified=False,
            evidence=ev_list,
        )

    def _parse_relationship_ref(
        self,
        raw_rel: Any,
        known_files: Set[str],
        line_counts: Dict[str, int],
        has_complete_inventory: bool,
        local_path: Optional[str],
        warnings: List[str],
        sec_id: str,
    ) -> Optional[ArchitectureRelationshipReference]:
        if isinstance(raw_rel, ArchitectureRelationshipReference):
            return raw_rel.model_copy(deep=True)
        if not isinstance(raw_rel, dict) or not raw_rel.get("source_component") or not raw_rel.get("target_component"):
            return None
        ev_list: List[EvidenceReference] = []
        for r in raw_rel.get("evidence") or []:
            ref = self._parse_and_verify_ref(
                r, known_files, line_counts, has_complete_inventory, local_path, warnings, f"Section '{sec_id}'"
            )
            if ref is not None:
                ev_list.append(ref)
        return ArchitectureRelationshipReference(
            source_component=str(raw_rel["source_component"]),
            target_component=str(raw_rel["target_component"]),
            relationship_type=str(raw_rel.get("relationship_type") or "calls"),
            is_statically_confirmed=bool(raw_rel.get("is_statically_confirmed", False)),
            evidence=ev_list,
        )

    def _parse_data_flow_ref(
        self,
        raw_df: Any,
        known_files: Set[str],
        line_counts: Dict[str, int],
        has_complete_inventory: bool,
        local_path: Optional[str],
        warnings: List[str],
        sec_id: str,
    ) -> Optional[DataFlowReference]:
        if isinstance(raw_df, DataFlowReference):
            return raw_df.model_copy(deep=True)
        if not isinstance(raw_df, dict) or not raw_df.get("workflow_id") or not raw_df.get("flow_id"):
            return None
        status = str(raw_df.get("data_relationship_status") or "inferred")
        if status not in ("observed", "inferred", "unknown_or_unresolved"):
            status = "inferred"
        ev_list: List[EvidenceReference] = []
        for r in raw_df.get("evidence") or []:
            ref = self._parse_and_verify_ref(
                r, known_files, line_counts, has_complete_inventory, local_path, warnings, f"Section '{sec_id}'"
            )
            if ref is not None:
                ev_list.append(ref)
        return DataFlowReference(
            workflow_id=str(raw_df["workflow_id"]),
            flow_id=str(raw_df["flow_id"]),
            data_item_name=raw_df.get("data_item_name"),
            data_relationship_status=status,
            evidence=ev_list,
        )

    def _normalize_claim(
        self,
        raw_claim: Any,
        section_id: str,
        section_items: List[ScriptEvidenceItem],
        evidence_package: ScriptEvidencePackage,
        known_files: Set[str],
        line_counts: Dict[str, int],
        has_complete_inventory: bool,
        local_path: Optional[str],
        warnings: List[str],
        uncertainty_notes: List[str],
    ) -> Optional[GroundedClaim]:
        if isinstance(raw_claim, GroundedClaim):
            raw_dict = raw_claim.model_dump()
        elif isinstance(raw_claim, dict):
            raw_dict = raw_claim
        else:
            return None

        statement = self._clean_text(raw_dict.get("statement") or "")
        if not statement:
            return None

        if _has_runtime_verification_claim(statement):
            warnings.append(
                f"Section '{section_id}': rejected claim asserting runtime execution verification: '{statement}'."
            )
            return None

        if _has_unsupported_guarantee(statement):
            warnings.append(
                f"Section '{section_id}': rejected unsupported guarantee claim: '{statement}'."
            )
            return None

        status = _coerce_grounding_status(raw_dict.get("grounding_status"))
        uncertainty_note = self._clean_text(raw_dict.get("uncertainty_note")) or None

        claim_ev_ids = raw_dict.get("evidence_ids") or []
        cited_items: List[ScriptEvidenceItem] = []
        had_unknown_id = False
        if isinstance(claim_ev_ids, list):
            for eid in claim_ev_ids:
                item = evidence_package.get_item(str(eid))
                if item is None:
                    had_unknown_id = True
                    warnings.append(f"Section '{section_id}' claim cited unknown evidence_id '{eid}'.")
                else:
                    cited_items.append(item)

        claim_refs: List[EvidenceReference] = []
        for item in cited_items:
            claim_refs.extend([r.model_copy(deep=True) for r in item.references])

        had_explicit_refs = bool(raw_dict.get("evidence"))
        for r in raw_dict.get("evidence") or []:
            ref = self._parse_and_verify_ref(
                r, known_files, line_counts, has_complete_inventory, local_path,
                warnings, f"Section '{section_id}' claim"
            )
            if ref is not None:
                claim_refs.append(ref)

        # If claim had explicit evidence IDs or refs that ALL failed verification, reject the unsupported claim
        if (had_unknown_id or had_explicit_refs) and not cited_items and not claim_refs and status != GroundingStatus.UNCERTAIN:
            warnings.append(
                f"Section '{section_id}': omitted unsupported claim '{statement[:80]}' because all cited evidence was invalid or unknown."
            )
            return None

        # Inherit section items if claim didn't specify its own evidence_ids
        if not cited_items and not claim_refs and section_items:
            cited_items = list(section_items)
            for item in cited_items:
                claim_refs.extend([r.model_copy(deep=True) for r in item.references])

        claim_refs = self._dedup_evidence(claim_refs)
        source = cited_items[0].source if cited_items else None

        # Enforce grounding cap based on cited items and verified references
        if status == GroundingStatus.CONFIRMED:
            can_confirm = bool(claim_refs) and (
                not cited_items or any(i.grounding_hint == GroundingStatus.CONFIRMED for i in cited_items)
            )
            if not can_confirm:
                if cited_items or section_items:
                    warnings.append(
                        f"Section '{section_id}': downgraded claim '{statement[:60]}' from 'confirmed' to 'inferred' "
                        f"(supporting evidence is inferred or lacks verified source lines)."
                    )
                    status = GroundingStatus.INFERRED
                else:
                    warnings.append(
                        f"Section '{section_id}': omitted ungrounded 'confirmed' claim '{statement[:80]}'."
                    )
                    return None

        if status == GroundingStatus.UNCERTAIN:
            if not uncertainty_note:
                uncertainty_note = "Available static repository evidence is insufficient to confirm this aspect."
            if uncertainty_note not in uncertainty_notes:
                uncertainty_notes.append(uncertainty_note)

        return GroundedClaim(
            statement=statement,
            grounding_status=status,
            source=source,
            evidence=claim_refs,
            uncertainty_note=uncertainty_note,
        )

    @staticmethod
    def _dedup_evidence(refs: List[EvidenceReference]) -> List[EvidenceReference]:
        deduped: List[EvidenceReference] = []
        seen: Set[Tuple[str, Optional[int], Optional[int]]] = set()
        for ref in refs:
            key = (ref.file_path, ref.line_start, ref.line_end)
            if key not in seen:
                seen.add(key)
                deduped.append(ref)
        return deduped

    @staticmethod
    def _dedup_components(comps: List[ComponentReference]) -> List[ComponentReference]:
        deduped: List[ComponentReference] = []
        seen: Set[str] = set()
        for c in comps:
            if c.component_id not in seen:
                seen.add(c.component_id)
                deduped.append(c)
        return deduped

    @staticmethod
    def _dedup_workflow_steps(steps: List[WorkflowStepReference]) -> List[WorkflowStepReference]:
        deduped: List[WorkflowStepReference] = []
        seen: Set[Tuple[str, int]] = set()
        for s in steps:
            key = (s.workflow_id, s.step_number)
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        return deduped


script_validator = ScriptValidator()
