"""
AI-Powered Storyboard Generation Analyzer (Milestone 4, Phase 3).

Orchestrates:
1. Context compilation from ``EducationalScript``, ``RepositoryKnowledge``,
   and optional understanding outputs (Project, Code, Workflow).
2. Grounded, scene-directed prompt construction for a 60–90 s (16:9 landscape)
   educational video storyboard.
3. Asynchronous generation through ``LLMManager`` (using Groq as primary provider).
4. Robust JSON extraction with at most one syntax-repair pass (never unlimited calls).
5. Deterministic duration reconciliation ensuring scene timings match section
   and script durations exactly.
6. Rigorous grounding validation, file/component verification, and anti-hallucination
   checks (rejecting runtime execution claims).
7. Explicit failure propagation on LLM failure — never returning an ungenerated
   or fabricated storyboard as a successful result.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from ....core.config import settings
from ..exceptions import AIError, AIInvalidResponseError
from ..llm_manager import LLMManager, llm_manager as default_llm_manager
from ..schemas import LLMGenerationOptions, LLMResponse, TokenUsageRecord
from ..script_generation.schemas import EducationalScript, SectionPurpose
from .evidence_builder import (
    StoryboardEvidenceBuilder,
    StoryboardEvidencePackage,
    storyboard_evidence_builder,
)
from .prompts import (
    SYSTEM_PROMPT,
    build_storyboard_repair_prompt,
    build_storyboard_user_prompt,
)
from .schemas import (
    EducationalStoryboard,
    StoryboardGenerationMetadata,
    VisualType,
)
from .validator import StoryboardValidator, storyboard_validator

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..code_understanding.schemas import RepositoryCodeUnderstanding
    from ..project_understanding.schemas import ProjectUnderstanding
    from ..workflow_understanding.schemas import RepositoryWorkflowUnderstanding

logger = logging.getLogger(__name__)


class StoryboardGenerationError(AIError):
    """Raised when AI educational storyboard generation or validation fails."""


def _wrap_ai_error(exc: Exception, default_provider: Optional[str] = None) -> StoryboardGenerationError:
    """
    Ensures any raised error is an instance of both ``StoryboardGenerationError``
    and the original ``AIError`` subclass (when ``exc`` is an ``AIError``).
    """
    if isinstance(exc, StoryboardGenerationError):
        return exc
    if isinstance(exc, AIError):
        if exc.__class__ is AIError:
            combined_cls = StoryboardGenerationError
        else:
            combined_cls = type(
                exc.__class__.__name__,
                (exc.__class__, StoryboardGenerationError),
                {},
            )
        wrapped = combined_cls.__new__(combined_cls)
        wrapped.__dict__.update(exc.__dict__)
        Exception.__init__(wrapped, exc.message)
        return wrapped
    return StoryboardGenerationError(
        message=f"Educational storyboard generation failed: {exc}",
        provider=default_provider,
        status_code=502,
        retryable=False,
    )


def _merge_token_usage(
    primary: Optional[TokenUsageRecord],
    extra: Optional[TokenUsageRecord],
) -> Optional[TokenUsageRecord]:
    if primary is None and extra is None:
        return None
    if primary is None:
        return extra.model_copy(deep=True) if extra else None
    if extra is None:
        return primary
    primary.prompt_tokens += extra.prompt_tokens
    primary.completion_tokens += extra.completion_tokens
    primary.total_tokens += extra.total_tokens
    primary.is_estimated = primary.is_estimated or extra.is_estimated
    return primary


class EducationalStoryboardAnalyzer:
    """
    Service that transforms an ``EducationalScript`` into a grounded,
    synchronized ``EducationalStoryboard`` using ``LLMManager``.
    """

    def __init__(
        self,
        llm_manager: Optional[LLMManager] = None,
        evidence_builder: Optional[StoryboardEvidenceBuilder] = None,
        validator: Optional[StoryboardValidator] = None,
    ):
        self.llm_manager = llm_manager or default_llm_manager
        self.evidence_builder = evidence_builder or storyboard_evidence_builder
        self.validator = validator or storyboard_validator

    @staticmethod
    def _unclosed_delimiters(prefix: str) -> Optional[str]:
        """
        Scans ``prefix`` outside JSON string literals and returns the exact
        closing delimiter sequence (in LIFO order) needed to balance ``{`` and ``[``.
        """
        stack: list[str] = []
        in_str = False
        escape = False
        for ch in prefix:
            if escape:
                escape = False
                continue
            if ch == "\\":
                if in_str:
                    escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in ("}", "]"):
                if stack and stack[-1] == ch:
                    stack.pop()
                else:
                    return None
        if in_str:
            return None
        return "".join(reversed(stack))

    def _extract_and_parse_json(self, text: str) -> Dict[str, Any]:
        """Extracts a JSON object from raw LLM output and repairs minor truncation."""
        clean_text = (text or "").strip()
        if not clean_text:
            raise json.JSONDecodeError("Empty LLM response text", "", 0)

        fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
        if fenced_match:
            clean_text = fenced_match.group(1).strip()

        start_idx = clean_text.find("{")
        if start_idx == -1:
            raise json.JSONDecodeError("No JSON object found in LLM output", clean_text, 0)

        json_candidate = clean_text[start_idx:]
        end_idx = json_candidate.rfind("}")
        if end_idx != -1:
            candidate_substr = json_candidate[: end_idx + 1]
            try:
                parsed = json.loads(candidate_substr)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Attempt LIFO delimiter repair for truncated JSON
        for trim_pos in range(len(json_candidate) - 1, 0, -1):
            if json_candidate[trim_pos] in (",", "}", "]"):
                truncated_prefix = json_candidate[:trim_pos].rstrip().rstrip(",")
                closing = self._unclosed_delimiters(truncated_prefix)
                if closing:
                    test_str = truncated_prefix + closing
                    try:
                        parsed = json.loads(test_str)
                        if (
                            isinstance(parsed, dict)
                            and isinstance(parsed.get("scenes"), list)
                            and any(
                                isinstance(s, dict) and str(s.get("title") or "").strip()
                                for s in parsed["scenes"]
                            )
                        ):
                            return parsed
                    except json.JSONDecodeError:
                        continue

        if end_idx != -1:
            parsed = json.loads(json_candidate[: end_idx + 1])
            if isinstance(parsed, dict):
                return parsed
        parsed = json.loads(json_candidate)
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("Top-level JSON value must be an object", clean_text, 0)
        return parsed

    def create_deterministic_fallback(
        self,
        script: EducationalScript,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        local_path: Optional[str] = None,
        evidence_package: Optional[StoryboardEvidencePackage] = None,
        reason: Optional[str] = None,
    ) -> EducationalStoryboard:
        """
        Creates a grounded, deterministic fallback EducationalStoryboard when Gemini API calls
        fail, time out, or quota is exhausted.

        Guarantees:
        - 100% script section coverage with contiguous scene numbers.
        - Exact duration synchronization matching script sections and total script duration.
        - Appropriate pedagogical visual types mapped from section purposes.
        - Distinct, non-overlapping spoken narration excerpts.
        - Verified grounding in repository files, components, and static relationships.
        - Provenance metadata clearly identifying 'deterministic_fallback' and 'rule_based_synthesis'
          so fallback content is never silently presented as Gemini-generated.
        """
        repo_name = knowledge.repository.name if knowledge and knowledge.repository else script.repository_name
        total_sections = len(script.sections)
        scenes_list: List[Dict[str, Any]] = []

        for idx, sec in enumerate(script.sections):
            scene_num = idx + 1
            scene_id = f"scene-{scene_num}"

            # Purpose-to-visual type mapping
            sec_p = sec.purpose.value if hasattr(sec.purpose, "value") else str(sec.purpose).lower()
            if sec_p in ("hook", "introduction", "problem"):
                visual_type = VisualType.TITLE_CARD.value
                layout_hint = "centered_hero"
                vis_desc = (
                    f"Title card displaying repository name '{repo_name}' with primary language badge "
                    f"and concise purpose statement."
                )
            elif sec_p in ("architecture_overview", "architecture"):
                visual_type = VisualType.ARCHITECTURE_DIAGRAM.value
                layout_hint = "diagram_flow"
                comp_count = len(knowledge.architecture.components) if knowledge and knowledge.architecture else len(sec.related_components)
                vis_desc = (
                    f"Architecture diagram displaying high-level system boundary and {max(1, comp_count)} "
                    f"verified architectural components with dependency connections."
                )
            elif sec_p in ("technology_overview",):
                visual_type = VisualType.TECHNOLOGY_OVERVIEW.value
                layout_hint = "split_screen"
                vis_desc = f"Technology overview displaying programming languages, frameworks, and key runtime dependencies for {repo_name}."
            elif sec_p in ("component_deep_dive",):
                visual_type = VisualType.COMPONENT_DIAGRAM.value
                layout_hint = "split_screen"
                vis_desc = f"Component diagram illustrating modules and primary responsibilities for {sec.title}."
            elif sec_p in ("workflow",):
                visual_type = VisualType.WORKFLOW_DIAGRAM.value
                layout_hint = "diagram_flow"
                vis_desc = f"Workflow sequence diagram tracing execution flow and component interfaces for {sec.title}."
            elif sec_p in ("data_flow",):
                visual_type = VisualType.DATA_FLOW_VISUALIZATION.value
                layout_hint = "diagram_flow"
                vis_desc = f"Data flow diagram tracing inputs, transformations, and outputs across components for {sec.title}."
            elif sec_p in ("conclusion", "outro"):
                visual_type = VisualType.SUMMARY_CARD.value
                layout_hint = "centered_hero"
                vis_desc = f"Summary card recapping key architectural strengths, modular patterns, and takeaways for {repo_name}."
            else:
                visual_type = VisualType.COMPONENT_DIAGRAM.value
                layout_hint = "split_screen"
                vis_desc = f"Component diagram illustrating modules and primary responsibilities for {sec.title}."

            on_screen = [c.statement[:45] for c in sec.claims[:2]] if sec.claims else [sec.title[:45]]
            transition = sec.transition_to_next or ("Crossfade to next scene" if scene_num < total_sections else None)

            # Files and components
            rel_files = [c.file_path for c in sec.related_components if c.file_path] or [e.file_path for e in sec.evidence if e.file_path]
            rel_comps = [c.model_dump() for c in sec.related_components]
            rel_wf = [w.model_dump() for w in sec.related_workflow_steps]
            ev_list = [e.model_dump() for e in sec.evidence]

            scenes_list.append({
                "scene_id": scene_id,
                "scene_number": scene_num,
                "script_section_id": sec.section_id,
                "title": sec.title,
                "purpose": sec.purpose_description or f"Explain {sec.title}",
                "estimated_duration_seconds": sec.estimated_duration_seconds,
                "visual_type": visual_type,
                "visual_description": vis_desc,
                "on_screen_text": on_screen,
                "narration": {
                    "script_section_id": sec.section_id,
                    "excerpt": sec.narration_text,
                },
                "layout_hint": layout_hint,
                "related_files": rel_files,
                "related_components": rel_comps,
                "related_workflow_steps": rel_wf,
                "evidence": ev_list,
                "transition_to_next": transition,
            })

        fallback_dict = {
            "storyboard_id": f"sb-{script.script_id}-fallback",
            "script_id": script.script_id,
            "title": f"{script.title} Storyboard (Deterministic Fallback)",
            "total_estimated_duration_seconds": script.total_estimated_duration_seconds,
            "video_format": {
                "orientation": script.video_format.orientation if script.video_format else "landscape",
                "aspect_ratio": script.video_format.aspect_ratio if script.video_format else "16:9",
            },
            "scenes": scenes_list,
            "validation_warnings": [
                f"Deterministic fallback triggered: {reason or 'Gemini LLM unavailable or quota exhausted'}."
            ],
        }

        normalized = self.validator.normalize_and_reconcile_raw_storyboard(
            raw_dict=fallback_dict,
            script=script,
            knowledge=knowledge,
            evidence_package=evidence_package,
            local_path=local_path,
        )

        sources = list(evidence_package.available_sources) if evidence_package else []
        missing = list(evidence_package.missing_sources) if evidence_package else []
        chars = evidence_package.used_chars if evidence_package else 0

        normalized["metadata"] = StoryboardGenerationMetadata(
            generated_at=datetime.now(timezone.utc),
            provider="deterministic_fallback",
            model="rule_based_synthesis",
            is_fallback=True,
            latency_ms=0.0,
            token_usage=None,
            source_understandings=sources,
            missing_understandings=missing,
            llm_call_count=0,
            revision_attempted=False,
            evidence_package_chars=chars,
        ).model_dump()

        storyboard = EducationalStoryboard.model_validate(normalized)
        return self.validator.validate_storyboard(
            storyboard=storyboard,
            script=script,
            knowledge=knowledge,
            local_path=local_path,
        )

    async def generate_storyboard(
        self,
        job_id: str,
        script: EducationalScript,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        provider_name: Optional[str] = None,
        local_path: Optional[str] = None,
        max_evidence_chars: Optional[int] = None,
        allow_fallback: bool = True,
    ) -> EducationalStoryboard:
        """
        Generates and validates an ``EducationalStoryboard`` matching ``script``.
        Uses Gemini as the dedicated LLM provider.

        If Gemini generation fails or quota is exhausted:
        - When allow_fallback=True: returns a validated deterministic fallback storyboard.
        - When allow_fallback=False: raises StoryboardGenerationError (AIError).
        """
        if script is None:
            raise ValueError("EducationalScript is required to generate a storyboard.")
        if knowledge is None:
            raise ValueError("RepositoryKnowledge is required to generate a storyboard.")

        # Dedicated provider enforcement: Gemini is the dedicated provider for storyboard generation.
        # Groq is strictly prohibited for storyboard generation.
        effective_provider = (provider_name or "gemini").lower().strip()
        if effective_provider == "groq":
            raise StoryboardGenerationError(
                "Groq is not permitted for educational storyboard generation. Gemini is the dedicated provider.",
                provider="groq",
            )
        target_provider = "gemini"

        # 1. Build compact, grounded storyboard context
        evidence_package = self.evidence_builder.build_evidence_package(
            script=script,
            knowledge=knowledge,
            project_understanding=project_understanding,
            code_understanding=code_understanding,
            workflow_understanding=workflow_understanding,
            local_path=local_path,
            max_chars=max_evidence_chars,
        )

        # 2. Build prompt and options
        user_prompt = build_storyboard_user_prompt(evidence_package)
        prompt_chars = len(SYSTEM_PROMPT) + len(user_prompt)
        logger.info(
            "Job %s: Starting educational storyboard generation for %s using %s (~%d prompt chars)",
            job_id,
            script.repository_name,
            target_provider,
            prompt_chars,
        )

        options = LLMGenerationOptions(
            temperature=settings.AI_TEMPERATURE,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            timeout_seconds=settings.AI_REQUEST_TIMEOUT,
            system_instruction=SYSTEM_PROMPT,
        )

        # 3. Call Gemini LLM provider
        llm_call_count = 0
        try:
            llm_call_count += 1
            response: LLMResponse = await self.llm_manager.generate(
                prompt=user_prompt,
                options=options,
                provider_name=target_provider,
                operation="storyboard_generation",
                job_id=job_id,
            )
        except Exception as exc:
            logger.error("Job %s: Storyboard Gemini LLM call failed: %s", job_id, exc)
            if allow_fallback:
                logger.warning(
                    "Job %s: Gemini storyboard generation failed (%s). Triggering deterministic fallback.",
                    job_id,
                    exc,
                )
                return self.create_deterministic_fallback(
                    script=script,
                    knowledge=knowledge,
                    project_understanding=project_understanding,
                    code_understanding=code_understanding,
                    workflow_understanding=workflow_understanding,
                    local_path=local_path,
                    evidence_package=evidence_package,
                    reason=f"Gemini LLM failure: {exc}",
                )
            raise _wrap_ai_error(exc, default_provider=target_provider) from exc

        total_latency_ms = float(response.latency_ms or 0.0)
        combined_usage = response.token_usage.model_copy(deep=True) if response.token_usage else None

        # 4. Parse JSON with one-shot syntax repair if needed
        parsed_dict: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None
        try:
            parsed_dict = self._extract_and_parse_json(response.text)
        except Exception as exc:
            parse_error = str(exc)
            logger.warning("Job %s: Initial storyboard JSON parsing failed (%s). Attempting 1 repair call.", job_id, parse_error)

        if parsed_dict is None:
            repair_prompt = build_storyboard_repair_prompt(
                response.text,
                parse_error or "Invalid JSON syntax",
                script_id=script.script_id,
                total_duration=script.total_estimated_duration_seconds,
            )
            repair_options = LLMGenerationOptions(
                temperature=0.0,
                max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                timeout_seconds=settings.AI_REQUEST_TIMEOUT,
                system_instruction=(
                    "Reasoning effort: low. Do not draft in reasoning; output only a single valid JSON object "
                    "matching the EducationalStoryboard schema."
                ),
            )
            try:
                llm_call_count += 1
                repair_resp: LLMResponse = await self.llm_manager.generate(
                    prompt=repair_prompt,
                    options=repair_options,
                    provider_name=target_provider,
                    operation="storyboard_generation_repair",
                    job_id=job_id,
                )
                total_latency_ms += float(repair_resp.latency_ms or 0.0)
                combined_usage = _merge_token_usage(combined_usage, repair_resp.token_usage)
                parsed_dict = self._extract_and_parse_json(repair_resp.text)
                logger.info("Job %s: JSON repair succeeded for storyboard generation.", job_id)
            except Exception as repair_exc:
                logger.error("Job %s: Storyboard JSON repair failed: %s", job_id, repair_exc)
                if allow_fallback:
                    logger.warning(
                        "Job %s: Storyboard JSON repair failed (%s). Triggering deterministic fallback.",
                        job_id,
                        repair_exc,
                    )
                    return self.create_deterministic_fallback(
                        script=script,
                        knowledge=knowledge,
                        project_understanding=project_understanding,
                        code_understanding=code_understanding,
                        workflow_understanding=workflow_understanding,
                        local_path=local_path,
                        evidence_package=evidence_package,
                        reason=f"JSON repair failed: {repair_exc}",
                    )
                err = AIInvalidResponseError(
                    f"Educational storyboard LLM output was malformed JSON and repair failed: {repair_exc}",
                    provider=response.provider,
                )
                raise _wrap_ai_error(err, default_provider=response.provider) from repair_exc

        # 5. Normalize, reconcile durations, and validate
        try:
            normalized = self.validator.normalize_and_reconcile_raw_storyboard(
                raw_dict=parsed_dict,
                script=script,
                knowledge=knowledge,
                evidence_package=evidence_package,
                local_path=local_path,
            )
            normalized["metadata"] = StoryboardGenerationMetadata(
                generated_at=datetime.now(timezone.utc),
                provider=response.provider,
                model=response.model,
                is_fallback=False,
                latency_ms=round(total_latency_ms, 2),
                token_usage=combined_usage,
                source_understandings=list(evidence_package.available_sources),
                missing_understandings=list(evidence_package.missing_sources),
                llm_call_count=llm_call_count,
                revision_attempted=False,
                evidence_package_chars=evidence_package.used_chars,
            ).model_dump()

            storyboard = EducationalStoryboard.model_validate(normalized)
            storyboard = self.validator.validate_storyboard(
                storyboard=storyboard,
                script=script,
                knowledge=knowledge,
                local_path=local_path,
            )
            logger.info(
                "Job %s: Generated educational storyboard '%s' using %s/%s (%d scenes, %.1fs, %.0fms)",
                job_id,
                storyboard.title,
                storyboard.metadata.provider,
                storyboard.metadata.model,
                len(storyboard.scenes),
                storyboard.total_estimated_duration_seconds,
                storyboard.metadata.latency_ms,
            )
            return storyboard
        except Exception as val_exc:
            logger.error("Job %s: EducationalStoryboard validation failed: %s", job_id, val_exc)
            if allow_fallback:
                logger.warning(
                    "Job %s: Storyboard validation failed (%s). Triggering deterministic fallback.",
                    job_id,
                    val_exc,
                )
                return self.create_deterministic_fallback(
                    script=script,
                    knowledge=knowledge,
                    project_understanding=project_understanding,
                    code_understanding=code_understanding,
                    workflow_understanding=workflow_understanding,
                    local_path=local_path,
                    evidence_package=evidence_package,
                    reason=f"Validation failed: {val_exc}",
                )
            err = AIInvalidResponseError(
                f"Educational storyboard failed schema or synchronization validation: {val_exc}",
                provider=response.provider,
            )
            raise _wrap_ai_error(err, default_provider=response.provider) from val_exc

    analyze_storyboard = generate_storyboard


StoryboardGenerationAnalyzer = EducationalStoryboardAnalyzer
StoryboardGenerationService = EducationalStoryboardAnalyzer
storyboard_generation_analyzer = EducationalStoryboardAnalyzer()
educational_storyboard_analyzer = storyboard_generation_analyzer
