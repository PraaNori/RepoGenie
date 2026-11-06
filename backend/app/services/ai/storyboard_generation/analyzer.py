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
from ..script_generation.schemas import EducationalScript
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
    ) -> EducationalStoryboard:
        """
        Generates and validates an ``EducationalStoryboard`` matching ``script``.

        Raises ``StoryboardGenerationError`` (which is also an ``AIError``) if
        generation or validation fails.
        """
        if script is None:
            raise ValueError("EducationalScript is required to generate a storyboard.")
        if knowledge is None:
            raise ValueError("RepositoryKnowledge is required to generate a storyboard.")

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
            "Job %s: Starting educational storyboard generation for %s (~%d prompt chars)",
            job_id,
            script.repository_name,
            prompt_chars,
        )

        options = LLMGenerationOptions(
            temperature=settings.AI_TEMPERATURE,
            max_output_tokens=max(settings.AI_MAX_OUTPUT_TOKENS, 2048),
            timeout_seconds=settings.AI_REQUEST_TIMEOUT,
            system_instruction=SYSTEM_PROMPT,
        )

        # 3. Call LLM provider
        llm_call_count = 0
        try:
            llm_call_count += 1
            response: LLMResponse = await self.llm_manager.generate(
                prompt=user_prompt,
                options=options,
                provider_name=provider_name,
                operation="storyboard_generation",
                job_id=job_id,
            )
        except Exception as exc:
            logger.error("Job %s: Storyboard LLM call failed: %s", job_id, exc)
            raise _wrap_ai_error(exc, default_provider=provider_name or self.llm_manager.active_provider_name) from exc

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
                    provider_name=provider_name,
                    operation="storyboard_generation_repair",
                    job_id=job_id,
                )
                total_latency_ms += float(repair_resp.latency_ms or 0.0)
                combined_usage = _merge_token_usage(combined_usage, repair_resp.token_usage)
                parsed_dict = self._extract_and_parse_json(repair_resp.text)
                logger.info("Job %s: JSON repair succeeded for storyboard generation.", job_id)
            except Exception as repair_exc:
                logger.error("Job %s: Storyboard JSON repair failed: %s", job_id, repair_exc)
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
