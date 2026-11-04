"""
Analyzer for Application Workflow and Data-Flow Understanding.

Orchestrates:
1. Deterministic candidate discovery and grounded evidence building.
2. Complete prompt token envelope estimation.
3. LLM provider call with strict anti-hallucination prompt.
4. One-shot JSON repair on malformed or truncated responses.
5. Invariant enforcement (runtime_execution_verified = False).
6. Deep static validation and operation corroboration.
7. Grounded deterministic AST fallback on AI provider absence, timeout, or failure.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..code_understanding.schemas import RepositoryCodeUnderstanding
    from ..project_understanding.schemas import ProjectUnderstanding

from ....core.config import settings
from ..exceptions import AIError, AIInvalidResponseError
from ..llm_manager import LLMManager, llm_manager as default_llm_manager
from ..schemas import LLMGenerationOptions, LLMResponse
from .candidate_discoverer import WorkflowCandidateDiscoverer, workflow_candidate_discoverer
from .evidence_builder import (
    CandidateEvidenceItem,
    WorkflowEvidenceBuilder,
    WorkflowEvidencePackage,
    workflow_evidence_builder,
)
from .prompts import (
    SYSTEM_PROMPT,
    build_workflow_repair_prompt,
    build_workflow_user_prompt,
)
from .schemas import (
    ApplicationWorkflow,
    CallSiteEvidence,
    DataFlow,
    RepositoryWorkflowUnderstanding,
    StructuralCallChain,
    WorkflowComponentReference,
    WorkflowStep,
)
from .validator import WorkflowValidator, workflow_validator

logger = logging.getLogger(__name__)


class WorkflowUnderstandingAnalyzer:
    """
    Orchestrates end-to-end Application Workflow and Data-Flow Understanding.
    """

    def __init__(
        self,
        llm_manager: Optional[LLMManager] = None,
        evidence_builder: Optional[WorkflowEvidenceBuilder] = None,
        validator: Optional[WorkflowValidator] = None,
        discoverer: Optional[WorkflowCandidateDiscoverer] = None,
    ):
        self.llm_manager = llm_manager or default_llm_manager
        self.evidence_builder = evidence_builder or workflow_evidence_builder
        self.validator = validator or workflow_validator
        self.discoverer = discoverer or workflow_candidate_discoverer

    def _extract_and_parse_json(self, text: str) -> Dict[str, Any]:
        """Extracts JSON content from raw LLM output and repairs minor formatting truncation."""
        clean_text = text.strip()

        # Strip code fences
        fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
        if fenced_match:
            clean_text = fenced_match.group(1).strip()

        start_idx = clean_text.find("{")
        if start_idx == -1:
            raise json.JSONDecodeError("No JSON object found in text", clean_text, 0)

        json_candidate = clean_text[start_idx:]
        end_idx = json_candidate.rfind("}")
        if end_idx != -1:
            candidate_substr = json_candidate[: end_idx + 1]
            try:
                return json.loads(candidate_substr)
            except json.JSONDecodeError:
                pass

        # Attempt backwards brace-balancing repair for truncated JSON
        for trim_pos in range(len(json_candidate) - 1, 0, -1):
            if json_candidate[trim_pos] in (",", "}", "]"):
                truncated_prefix = json_candidate[:trim_pos].rstrip(",")
                open_braces = truncated_prefix.count("{") - truncated_prefix.count("}")
                open_brackets = truncated_prefix.count("[") - truncated_prefix.count("]")
                if open_braces >= 1:
                    test_str = truncated_prefix + ("]" * max(0, open_brackets)) + ("}" * open_braces)
                    try:
                        return json.loads(test_str)
                    except json.JSONDecodeError:
                        continue

        if end_idx != -1:
            return json.loads(json_candidate[: end_idx + 1])
        return json.loads(json_candidate)

    async def analyze_workflows(
        self,
        job_id: str,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        provider_name: Optional[str] = None,
        local_path: Optional[str] = None,
        repo_root: Optional[str] = None,
    ) -> RepositoryWorkflowUnderstanding:
        """
        Executes end-to-end application workflow and data-flow understanding.
        """
        repo_name = getattr(getattr(knowledge, "repository", None), "name", "unknown/repository")
        logger.info(
            "Starting AI application workflow understanding for job %s (repo: %s)",
            job_id,
            repo_name,
        )

        # 1. Build Grounded Evidence Package
        evidence_package = self.evidence_builder.build_evidence_package(
            knowledge=knowledge,
            project_understanding=project_understanding,
            code_understanding=code_understanding,
            local_path=local_path,
            repo_root=repo_root,
        )

        # 2. Check if any candidates exist
        if not evidence_package.selected_candidates and not evidence_package.structural_call_chains:
            logger.warning(
                "Job %s: No workflow candidates discovered; returning deterministic empty fallback.",
                job_id,
            )
            return self.create_deterministic_fallback(
                knowledge=knowledge,
                evidence_package=evidence_package,
                error_reason="No entry-point or call-chain workflow candidates could be discovered.",
            )

        # 3. Build Prompt and Measure Complete Token Envelope
        user_prompt = build_workflow_user_prompt(evidence_package)
        prompt_char_estimate = len(SYSTEM_PROMPT) + len(user_prompt)
        logger.info(
            "Job %s: Complete prompt envelope: ~%d chars (~%d tokens)",
            job_id,
            prompt_char_estimate,
            prompt_char_estimate // 4,
        )

        options = LLMGenerationOptions(
            temperature=0.2,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            timeout_seconds=90,
            system_instruction=SYSTEM_PROMPT,
        )

        # 4. Call LLM Provider Abstraction with Graceful Fallback
        response: Optional[LLMResponse] = None
        try:
            response = await self.llm_manager.generate(
                prompt=user_prompt,
                options=options,
                provider_name=provider_name,
                operation="workflow_understanding",
                job_id=job_id,
            )
        except Exception as exc:
            logger.warning(
                "Job %s: AI workflow generation failed (%s: %s). Falling back to deterministic AST workflows.",
                job_id,
                type(exc).__name__,
                exc,
            )
            return self.create_deterministic_fallback(
                knowledge=knowledge,
                evidence_package=evidence_package,
                error_reason=f"AI generation unavailable ({type(exc).__name__}: {exc})",
            )

        # 5. Parse JSON Output with One-Shot Repair
        parsed_dict: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None

        try:
            parsed_dict = self._extract_and_parse_json(response.text)
        except Exception as exc:
            parse_error = str(exc)
            logger.warning(
                "Initial JSON parsing failed for job %s workflow understanding: %s. Attempting 1 repair query.",
                job_id,
                parse_error,
            )

        if parsed_dict is None:
            repair_prompt = build_workflow_repair_prompt(response.text, parse_error or "Invalid JSON")
            repair_options = LLMGenerationOptions(
                temperature=0.0,
                max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                timeout_seconds=60,
                system_instruction="You fix invalid JSON. Output only strictly valid JSON matching the schema.",
            )
            try:
                repair_resp: LLMResponse = await self.llm_manager.generate(
                    prompt=repair_prompt,
                    options=repair_options,
                    provider_name=provider_name,
                    operation="workflow_understanding_repair",
                    job_id=job_id,
                )
                parsed_dict = self._extract_and_parse_json(repair_resp.text)
                if repair_resp.token_usage and response.token_usage:
                    response.token_usage.prompt_tokens += repair_resp.token_usage.prompt_tokens
                    response.token_usage.completion_tokens += repair_resp.token_usage.completion_tokens
                    response.token_usage.total_tokens += repair_resp.token_usage.total_tokens
                response.latency_ms += repair_resp.latency_ms
                logger.info("JSON repair successfully resolved syntax error for job %s workflow understanding", job_id)
            except Exception as repair_exc:
                logger.error("JSON repair also failed for job %s workflow understanding: %s", job_id, repair_exc)
                return self.create_deterministic_fallback(
                    knowledge=knowledge,
                    evidence_package=evidence_package,
                    error_reason=f"LLM output unparseable and repair failed: {repair_exc}",
                )

        # 6. Normalize and Sanitize Parsed Dict
        parsed_dict = self._normalize_parsed_dict(parsed_dict, evidence_package, knowledge)

        # 7. Validate Pydantic Schema
        try:
            understanding = RepositoryWorkflowUnderstanding.model_validate(parsed_dict)
            understanding.provider = response.provider
            understanding.model = response.model
            understanding.latency_ms = round(response.latency_ms, 2)
            understanding.token_usage = response.token_usage
            understanding.generated_at = datetime.now(timezone.utc)
            understanding.is_fallback = False

            # 8. Run Deep Static Validation
            understanding = self.validator.validate_workflow_understanding(
                understanding=understanding,
                knowledge=knowledge,
                local_path=local_path,
            )
            logger.info(
                "Successfully generated workflow understanding for job %s using %s/%s (%d workflows, %d structural chains, %.0fms)",
                job_id,
                understanding.provider,
                understanding.model,
                len(understanding.workflows),
                len(understanding.structural_call_chains),
                understanding.latency_ms,
            )
            return understanding
        except Exception as val_exc:
            logger.error("RepositoryWorkflowUnderstanding validation failed for job %s: %s", job_id, val_exc)
            return self.create_deterministic_fallback(
                knowledge=knowledge,
                evidence_package=evidence_package,
                error_reason=f"Schema validation error: {val_exc}",
            )

    def _normalize_parsed_dict(
        self,
        parsed_dict: Dict[str, Any],
        evidence_package: WorkflowEvidencePackage,
        knowledge: RepositoryKnowledge,
    ) -> Dict[str, Any]:
        """Ensures top-level keys, counts, and invariants adhere to schema defaults."""
        fallback = self.create_deterministic_fallback(knowledge, evidence_package)

        if not parsed_dict.get("repository_name"):
            parsed_dict["repository_name"] = evidence_package.repository_name
        if not parsed_dict.get("system_architecture_type"):
            parsed_dict["system_architecture_type"] = evidence_package.system_architecture_type
        if not parsed_dict.get("workflow_summary"):
            parsed_dict["workflow_summary"] = fallback.workflow_summary

        # Workflows list bounds & normalization
        raw_wfs = parsed_dict.get("workflows")
        if not isinstance(raw_wfs, list) or not raw_wfs:
            parsed_dict["workflows"] = [wf.model_dump() for wf in fallback.workflows]
        else:
            norm_wfs: List[Dict[str, Any]] = []
            for wf in raw_wfs[:2]:  # Enforce max 2 workflows
                if not isinstance(wf, dict):
                    continue
                # Invariant: runtime_execution_verified is ALWAYS False
                wf["runtime_execution_verified"] = False

                # Truncate string fields to max_length bounds
                if len(wf.get("name", "")) > 100:
                    wf["name"] = wf["name"][:97] + "..."
                if len(wf.get("description", "")) > 400:
                    wf["description"] = wf["description"][:397] + "..."
                if len(wf.get("trigger", "")) > 150:
                    wf["trigger"] = wf["trigger"][:147] + "..."
                if len(wf.get("final_outcome", "")) > 200:
                    wf["final_outcome"] = wf["final_outcome"][:197] + "..."

                # Normalize steps (max 5)
                raw_steps = wf.get("steps", [])
                if isinstance(raw_steps, list):
                    norm_steps: List[Dict[str, Any]] = []
                    for step in raw_steps[:5]:
                        if not isinstance(step, dict):
                            continue
                        step["runtime_execution_verified"] = False
                        if len(step.get("title", "")) > 80:
                            step["title"] = step["title"][:77] + "..."
                        if len(step.get("description", "")) > 300:
                            step["description"] = step["description"][:297] + "..."
                        norm_steps.append(step)
                    wf["steps"] = norm_steps

                # Normalize data flows (max 2)
                raw_flows = wf.get("data_flows", [])
                if isinstance(raw_flows, list):
                    wf["data_flows"] = [f for f in raw_flows[:2] if isinstance(f, dict)]

                # Normalize participating components (max 5)
                raw_comps = wf.get("participating_components", [])
                if isinstance(raw_comps, list):
                    wf["participating_components"] = [c for c in raw_comps[:5] if isinstance(c, dict)]

                norm_wfs.append(wf)
            parsed_dict["workflows"] = norm_wfs

        # Include structural call chains and omitted candidates from evidence package
        parsed_dict["structural_call_chains"] = [c.model_dump() for c in evidence_package.structural_call_chains[:2]]
        parsed_dict["omitted_candidate_workflows"] = list(evidence_package.omitted_candidates)
        parsed_dict["is_incomplete"] = len(evidence_package.omitted_candidates) > 0

        # Analysis limitations
        limitations = list(evidence_package.truncation_reasons)
        if evidence_package.budget_exceeded:
            limitations.append("Evidence budget ceiling reached; candidate call steps were truncated or omitted.")
        parsed_dict["analysis_limitations"] = limitations

        return parsed_dict

    def create_deterministic_fallback(
        self,
        knowledge: RepositoryKnowledge,
        evidence_package: Optional[WorkflowEvidencePackage] = None,
        error_reason: Optional[str] = None,
    ) -> RepositoryWorkflowUnderstanding:
        """
        Generates a grounded, verified AST fallback when the AI provider is unavailable,
        unconfigured, times out, or fails.
        """
        ev_pkg = evidence_package or self.evidence_builder.build_evidence_package(knowledge)
        repo_name = ev_pkg.repository_name
        arch_type = ev_pkg.system_architecture_type

        workflows: List[ApplicationWorkflow] = []

        # Build up to 2 deterministic workflows from selected candidates
        for cand in ev_pkg.selected_candidates[:2]:
            steps: List[WorkflowStep] = []
            for s_idx, step_ev in enumerate(cand.call_steps[:5]):
                steps.append(
                    WorkflowStep(
                        step_number=step_ev.step_number,
                        title=f"Call {step_ev.call_name}()",
                        component_id=step_ev.caller_file,
                        symbol_name=step_ev.caller_symbol,
                        action_type="call",
                        description=f"Deterministic AST call transition from {step_ev.caller_symbol} to {step_ev.callee_symbol}.",
                        call_relationship_verified=True,
                        source_order_verified=step_ev.source_order_verified,
                        same_execution_path_verified=step_ev.same_execution_path_verified,
                        execution_guaranteed=step_ev.execution_guaranteed,
                        runtime_execution_verified=False,  # ALWAYS False
                        is_deterministic=True,
                        confidence="medium",
                        call_evidence=CallSiteEvidence(
                            caller_file=step_ev.caller_file,
                            caller_symbol=step_ev.caller_symbol,
                            callee_file=step_ev.callee_file,
                            callee_symbol=step_ev.callee_symbol,
                            call_name=step_ev.call_name,
                            call_site_line=step_ev.call_site_line,
                            call_site_column=step_ev.call_site_col,
                            call_graph_edge_id=step_ev.call_graph_edge_id,
                            call_site_id=step_ev.call_site_id,
                            is_edge_verified=True,
                            is_site_location_verified=(step_ev.call_site_line > 0),
                        ),
                    )
                )

            entry_ref = WorkflowComponentReference(
                component_id=cand.entry_file,
                name=cand.entry_symbol,
                role_in_workflow=f"Entry point for {cand.name}",
            )
            participating: List[WorkflowComponentReference] = [
                WorkflowComponentReference(
                    component_id=f,
                    name=os.path.basename(f),
                    role_in_workflow=cand.component_roles.get(f, f"Component at {f}"),
                )
                for f in cand.participating_files[:5]
            ]

            wf = ApplicationWorkflow(
                workflow_id=cand.candidate_id,
                name=cand.name,
                category=cand.category,
                description=f"Deterministic static workflow reconstructed from AST call graph starting at {cand.entry_symbol}.",
                trigger=cand.trigger,
                entry_point=entry_ref,
                participating_components=participating,
                steps=steps,
                data_flows=[],
                final_outcome=f"Static call execution chain completes through {len(steps)} verified AST call sites.",
                call_relationships_fully_verified=True,
                source_order_verified=all(s.source_order_verified for s in steps),
                same_execution_path_verified=all(s.same_execution_path_verified for s in steps),
                execution_guaranteed=all(s.execution_guaranteed for s in steps),
                runtime_execution_verified=False,
                confidence="medium",
                is_deterministic=True,
                unresolved_aspects=list(cand.limitations_and_unresolved)[:5],
            )
            workflows.append(wf)

        summary = (
            f"Deterministic Static Analysis: {repo_name} contains {len(workflows)} primary verified "
            f"call chains and {len(ev_pkg.structural_call_chains)} structural call chains across {arch_type} architecture."
        )

        warnings: List[str] = []
        limitations: List[str] = list(ev_pkg.truncation_reasons)
        if error_reason:
            warnings.append(f"AI provider fallback activated: {error_reason}")
            limitations.append(f"Deterministic fallback used due to: {error_reason}")

        fallback_result = RepositoryWorkflowUnderstanding(
            schema_version="1.0",
            repository_name=repo_name,
            system_architecture_type=arch_type,
            workflow_summary=summary,
            workflows=workflows,
            structural_call_chains=ev_pkg.structural_call_chains[:2],
            omitted_candidate_workflows=ev_pkg.omitted_candidates,
            is_incomplete=len(ev_pkg.omitted_candidates) > 0,
            provider="deterministic_fallback",
            model="ast_rule_based",
            is_fallback=True,
            latency_ms=0.0,
            token_usage=None,
            validation_warnings=warnings,
            analysis_limitations=limitations,
        )

        return self.validator.validate_workflow_understanding(
            understanding=fallback_result,
            knowledge=knowledge,
        )


workflow_understanding_analyzer = WorkflowUnderstandingAnalyzer()
