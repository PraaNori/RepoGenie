"""
AI-Powered Educational Script Generation Analyzer (Milestone 4, Phase 2).

Orchestrates:
1. Deterministic evidence selection and secret redaction from ``RepositoryKnowledge``,
   ``ProjectUnderstanding``, ``RepositoryCodeUnderstanding``, and
   ``RepositoryWorkflowUnderstanding``.
2. Grounded, profile-adapted prompt construction for a 60–90 s (16:9 landscape)
   educational explainer video script.
3. Asynchronous generation through the existing ``LLMManager`` abstraction
   (with Groq as the configured primary provider).
4. Robust JSON extraction with at most one syntax-repair pass and an optional
   single duration-revision pass (never unlimited LLM calls).
5. Reference hydration, evidence verification against the repository file
   inventory, claim grounding enforcement, and runtime-verification rejection.
6. Explicit error propagation on LLM or validation failure — never returning an
   ungenerated or fabricated script as a successful AI result.
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
from .evidence_builder import (
    ScriptEvidenceBuilder,
    ScriptEvidencePackage,
    script_evidence_builder,
)
from .prompts import (
    SYSTEM_PROMPT,
    build_script_repair_prompt,
    build_script_revision_prompt,
    build_script_user_prompt,
)
from .schemas import (
    DurationTarget,
    EducationalScript,
    NarrationPacing,
    ScriptGenerationMetadata,
)
from .validator import ScriptValidator, script_validator

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..code_understanding.schemas import RepositoryCodeUnderstanding
    from ..project_understanding.schemas import ProjectUnderstanding
    from ..workflow_understanding.schemas import RepositoryWorkflowUnderstanding

logger = logging.getLogger(__name__)


class ScriptGenerationError(AIError):
    """Raised when AI educational script generation or validation fails."""


def _wrap_ai_error(exc: Exception, default_provider: Optional[str] = None) -> ScriptGenerationError:
    """
    Ensures any raised error is an instance of both ``ScriptGenerationError``
    and the original ``AIError`` subclass (when ``exc`` is an ``AIError``).
    """
    if isinstance(exc, ScriptGenerationError):
        return exc
    if isinstance(exc, AIError):
        if exc.__class__ is AIError:
            combined_cls = ScriptGenerationError
        else:
            combined_cls = type(
                exc.__class__.__name__,
                (exc.__class__, ScriptGenerationError),
                {},
            )
        wrapped = combined_cls.__new__(combined_cls)
        wrapped.__dict__.update(exc.__dict__)
        Exception.__init__(wrapped, exc.message)
        return wrapped
    return ScriptGenerationError(
        message=f"Educational script generation failed: {exc}",
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


class EducationalScriptAnalyzer:
    """
    Service that generates a grounded ``EducationalScript`` from existing
    repository understanding outputs using ``LLMManager``.
    """

    def __init__(
        self,
        llm_manager: Optional[LLMManager] = None,
        evidence_builder: Optional[ScriptEvidenceBuilder] = None,
        validator: Optional[ScriptValidator] = None,
    ):
        self.llm_manager = llm_manager or default_llm_manager
        self.evidence_builder = evidence_builder or script_evidence_builder
        self.validator = validator or script_validator

    # ------------------------------------------------------------------
    # JSON extraction & brace-balancing repair
    # ------------------------------------------------------------------

    @staticmethod
    def _unclosed_delimiters(prefix: str) -> Optional[str]:
        """
        Scans ``prefix`` outside JSON string literals and returns the exact
        closing delimiter sequence (in LIFO order) needed to balance ``{`` and ``[``.
        Returns ``None`` if ``prefix`` ends inside an unclosed string literal.
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

        # Attempt LIFO stack-based delimiter repair for truncated JSON only if at least one complete section is recovered
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
                            and isinstance(parsed.get("sections"), list)
                            and any(
                                isinstance(s, dict) and str(s.get("narration_text") or "").strip()
                                for s in parsed["sections"]
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

    # ------------------------------------------------------------------
    # Main generation entrypoint
    # ------------------------------------------------------------------

    async def generate_script(
        self,
        job_id: str,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        provider_name: Optional[str] = None,
        local_path: Optional[str] = None,
        target_duration: Optional[DurationTarget] = None,
        pacing: Optional[NarrationPacing] = None,
        max_evidence_chars: Optional[int] = None,
        revise_on_duration_out_of_range: bool = False,
    ) -> EducationalScript:
        """
        Generates and validates a grounded ``EducationalScript`` for ``knowledge``.

        Raises ``ScriptGenerationError`` (which is also an ``AIError``) if the
        LLM call fails, if the response remains unparseable after a single
        repair pass, or if the output violates required schema invariants.
        """
        if knowledge is None:
            raise ValueError("RepositoryKnowledge is required to generate an educational script.")

        target = target_duration or DurationTarget()
        pace = pacing or NarrationPacing()

        # 1. Build compact, deterministic evidence package
        evidence_package = self.evidence_builder.build_evidence_package(
            knowledge=knowledge,
            project_understanding=project_understanding,
            code_understanding=code_understanding,
            workflow_understanding=workflow_understanding,
            local_path=local_path,
            max_chars=max_evidence_chars,
        )

        # 2. Build prompt and generation options respecting configured settings
        user_prompt = build_script_user_prompt(
            evidence_package=evidence_package,
            target_duration=target,
            pacing=pace,
        )
        prompt_chars = len(SYSTEM_PROMPT) + len(user_prompt)
        logger.info(
            "Job %s: Starting educational script generation for %s (~%d prompt chars, ~%d est. tokens)",
            job_id,
            evidence_package.repository_name,
            prompt_chars,
            prompt_chars // 4,
        )

        options = LLMGenerationOptions(
            temperature=settings.AI_TEMPERATURE,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            timeout_seconds=settings.AI_REQUEST_TIMEOUT,
            system_instruction=SYSTEM_PROMPT,
        )

        # 3. Primary LLM generation call
        llm_call_count = 0
        try:
            llm_call_count += 1
            response: LLMResponse = await self.llm_manager.generate(
                prompt=user_prompt,
                options=options,
                provider_name=provider_name,
                operation="script_generation",
                job_id=job_id,
            )
        except Exception as exc:
            logger.error("Job %s: Educational script LLM call failed: %s", job_id, exc)
            raise _wrap_ai_error(exc, default_provider=provider_name or self.llm_manager.active_provider_name) from exc

        total_latency_ms = float(response.latency_ms or 0.0)
        combined_usage = response.token_usage.model_copy(deep=True) if response.token_usage else None

        # 4. Parse JSON output with at most one syntax repair attempt
        parsed_dict: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None
        try:
            parsed_dict = self._extract_and_parse_json(response.text)
        except Exception as exc:
            parse_error = str(exc)
            logger.warning(
                "Job %s: Initial script JSON parsing failed (%s). Attempting 1 repair call.",
                job_id,
                parse_error,
            )

        if parsed_dict is None:
            repair_prompt = build_script_repair_prompt(
                response.text,
                parse_error or "Invalid JSON syntax",
                evidence_package=evidence_package,
            )
            repair_options = LLMGenerationOptions(
                temperature=0.0,
                max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                timeout_seconds=settings.AI_REQUEST_TIMEOUT,
                system_instruction=(
                    "Reasoning effort: low. Do not draft in reasoning; output only a single valid JSON object "
                    "matching the EducationalScript schema."
                ),
            )
            try:
                llm_call_count += 1
                repair_resp: LLMResponse = await self.llm_manager.generate(
                    prompt=repair_prompt,
                    options=repair_options,
                    provider_name=provider_name,
                    operation="script_generation_repair",
                    job_id=job_id,
                )
                total_latency_ms += float(repair_resp.latency_ms or 0.0)
                combined_usage = _merge_token_usage(combined_usage, repair_resp.token_usage)
                parsed_dict = self._extract_and_parse_json(repair_resp.text)
                logger.info("Job %s: JSON repair succeeded for educational script generation.", job_id)
            except Exception as repair_exc:
                logger.error("Job %s: Script JSON repair failed: %s", job_id, repair_exc)
                err = AIInvalidResponseError(
                    f"Educational script LLM output was malformed JSON and repair failed: {repair_exc}",
                    provider=response.provider,
                )
                raise _wrap_ai_error(err, default_provider=response.provider) from repair_exc

        # 5. Optional controlled revision if section count, word count, or duration is outside target range
        revision_attempted = False
        if revise_on_duration_out_of_range and llm_call_count < 2:
            raw_sections = parsed_dict.get("sections") if isinstance(parsed_dict, dict) else None
            if isinstance(raw_sections, list) and raw_sections:
                try:
                    est_sum = sum(float(s.get("estimated_duration_seconds") or 0) for s in raw_sections if isinstance(s, dict))
                except (TypeError, ValueError):
                    est_sum = 0.0
                total_words = sum(
                    len(str(s.get("narration_text") or s.get("narration") or "").split())
                    for s in raw_sections
                    if isinstance(s, dict)
                )

                needs_revision = False
                reasons: list[str] = []
                if len(raw_sections) < 3:
                    needs_revision = True
                    reasons.append(
                        f"Script contains only {len(raw_sections)} section(s); 4 to 6 sections are required."
                    )
                if est_sum > 0 and (est_sum < target.min_seconds or est_sum > target.max_seconds):
                    needs_revision = True
                    reasons.append(
                        f"Total duration {est_sum:.1f}s is outside target range "
                        f"{target.min_seconds:.0f}–{target.max_seconds:.0f}s."
                    )
                elif est_sum <= 0:
                    needs_revision = True
                    reasons.append("Section durations could not be parsed.")
                if total_words < 100:
                    needs_revision = True
                    reasons.append(
                        f"Total word count of {total_words} words is below the minimum threshold of 120 words."
                    )

                if needs_revision:
                    revision_attempted = True
                    reason = " ".join(reasons)
                    rev_prompt = build_script_revision_prompt(
                        raw_script_dict=parsed_dict,
                        evidence_package=evidence_package,
                        reason=reason,
                        target_duration=target,
                        pacing=pace,
                    )
                    try:
                        llm_call_count += 1
                        rev_resp = await self.llm_manager.generate(
                            prompt=rev_prompt,
                            options=options,
                            provider_name=provider_name,
                            operation="script_generation_revision",
                            job_id=job_id,
                        )
                        total_latency_ms += float(rev_resp.latency_ms or 0.0)
                        combined_usage = _merge_token_usage(combined_usage, rev_resp.token_usage)
                        parsed_dict = self._extract_and_parse_json(rev_resp.text)
                    except Exception as rev_exc:
                        logger.warning(
                            "Job %s: Optional duration revision failed (%s); retaining initial script with warnings.",
                            job_id,
                            rev_exc,
                        )

        # 6. Normalize, hydrate evidence references, and validate
        try:
            normalized = self.validator.normalize_and_ground_raw_script(
                raw_dict=parsed_dict,
                evidence_package=evidence_package,
                knowledge=knowledge,
                local_path=local_path,
                target_duration=target,
                pacing=pace,
            )
            normalized["metadata"] = ScriptGenerationMetadata(
                generated_at=datetime.now(timezone.utc),
                provider=response.provider,
                model=response.model,
                is_fallback=False,
                latency_ms=round(total_latency_ms, 2),
                token_usage=combined_usage,
                source_understandings=list(evidence_package.available_sources),
                missing_understandings=list(evidence_package.missing_sources),
                llm_call_count=llm_call_count,
                revision_attempted=revision_attempted,
                evidence_package_chars=evidence_package.used_chars,
            ).model_dump()

            script = EducationalScript.model_validate(normalized)
            script = self.validator.validate_script(
                script=script,
                knowledge=knowledge,
                evidence_package=evidence_package,
                local_path=local_path,
            )
            logger.info(
                "Job %s: Generated educational script '%s' using %s/%s (%d sections, %.1fs, %d words, %.0fms)",
                job_id,
                script.title,
                script.metadata.provider,
                script.metadata.model,
                len(script.sections),
                script.total_estimated_duration_seconds,
                script.total_word_count,
                script.metadata.latency_ms,
            )
            return script
        except Exception as val_exc:
            logger.error("Job %s: EducationalScript validation failed: %s", job_id, val_exc)
            err = AIInvalidResponseError(
                f"Educational script failed schema or grounding validation: {val_exc}",
                provider=response.provider,
            )
            raise _wrap_ai_error(err, default_provider=response.provider) from val_exc

    # Alias for consistency with ProjectUnderstandingAnalyzer / CodeUnderstandingAnalyzer
    analyze_script = generate_script


# Service singletons and aliases
ScriptGenerationAnalyzer = EducationalScriptAnalyzer
ScriptGenerationService = EducationalScriptAnalyzer
script_generation_analyzer = EducationalScriptAnalyzer()
educational_script_analyzer = script_generation_analyzer
