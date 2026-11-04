from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..project_understanding.schemas import ProjectUnderstanding
from ....core.config import settings
from ..exceptions import AIError, AIInvalidResponseError
from ..llm_manager import LLMManager
from ..project_understanding.schemas import EvidenceReference
from ..schemas import LLMGenerationOptions, LLMResponse
from .component_selector import ComponentSelector, component_selector
from .evidence_builder import CodeEvidenceBuilder, code_evidence_builder
from .prompts import (
    SYSTEM_PROMPT,
    build_code_repair_prompt,
    build_code_understanding_user_prompt,
)
from .schemas import (
    CodeExplanationItem,
    ComponentInteractionItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
from .validator import CodeEvidenceValidator, code_evidence_validator

logger = logging.getLogger(__name__)


class CodeUnderstandingAnalyzer:
    """
    Orchestrates AI-powered component-level and code-level understanding.
    Controls prompt token budgets, prompts the LLM provider abstraction,
    validates output schemas, repairs truncated JSON, and provides grounded
    deterministic fallbacks when AI APIs are unavailable.
    """

    def __init__(
        self,
        llm_manager: Optional[LLMManager] = None,
        evidence_builder: Optional[CodeEvidenceBuilder] = None,
        validator: Optional[CodeEvidenceValidator] = None,
        selector: Optional[ComponentSelector] = None,
    ):
        from ..llm_manager import llm_manager as default_llm_manager

        self.llm_manager = llm_manager or default_llm_manager
        self.evidence_builder = evidence_builder or code_evidence_builder
        self.validator = validator or code_evidence_validator
        self.selector = selector or component_selector

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

    async def analyze_codebase(
        self,
        job_id: str,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        provider_name: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> RepositoryCodeUnderstanding:
        """
        Executes end-to-end component and code understanding using the configured LLM.
        """
        logger.info(
            "Starting AI code-level understanding for job %s (repo: %s)",
            job_id,
            knowledge.repository.name,
        )

        # 1. Build Grounded Evidence Package
        evidence_package = self.evidence_builder.build_evidence_package(
            knowledge=knowledge,
            project_understanding=project_understanding,
            local_path=local_path,
        )

        # 2. Build Prompts and Measure Complete Token Envelope
        user_prompt = build_code_understanding_user_prompt(evidence_package)
        estimated_total_tokens = self.evidence_builder.estimate_total_tokens(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
        )
        logger.info(
            "Job %s: Estimated complete request tokens: ~%d (prompt: ~%d, output ceiling: %d)",
            job_id,
            estimated_total_tokens,
            (len(SYSTEM_PROMPT) + len(user_prompt)) // 4,
            settings.AI_MAX_OUTPUT_TOKENS,
        )

        options = LLMGenerationOptions(
            temperature=0.2,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            timeout_seconds=90,
            system_instruction=SYSTEM_PROMPT,
        )

        # 3. Call LLM Provider Abstraction
        response: LLMResponse = await self.llm_manager.generate(
            prompt=user_prompt,
            options=options,
            provider_name=provider_name,
            operation="code_understanding",
            job_id=job_id,
        )

        # 4. Parse JSON Response
        parsed_dict: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None

        try:
            parsed_dict = self._extract_and_parse_json(response.text)
        except Exception as exc:
            parse_error = str(exc)
            logger.warning(
                "Initial JSON parsing failed for job %s code-understanding: %s. Attempting 1 repair query.",
                job_id,
                parse_error,
            )

        # 5. One-Shot JSON Repair
        if parsed_dict is None:
            repair_prompt = build_code_repair_prompt(response.text, parse_error or "Invalid JSON")
            repair_options = LLMGenerationOptions(
                temperature=0.0,
                max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                timeout_seconds=60,
                system_instruction="You fix invalid JSON. Output only valid JSON matching the schema.",
            )
            try:
                repair_resp: LLMResponse = await self.llm_manager.generate(
                    prompt=repair_prompt,
                    options=repair_options,
                    provider_name=provider_name,
                    operation="code_understanding_repair",
                    job_id=job_id,
                )
                parsed_dict = self._extract_and_parse_json(repair_resp.text)
                if repair_resp.token_usage and response.token_usage:
                    response.token_usage.prompt_tokens += repair_resp.token_usage.prompt_tokens
                    response.token_usage.completion_tokens += repair_resp.token_usage.completion_tokens
                    response.token_usage.total_tokens += repair_resp.token_usage.total_tokens
                response.latency_ms += repair_resp.latency_ms
                logger.info("JSON repair successfully resolved syntax error for job %s code-understanding", job_id)
            except Exception as repair_exc:
                logger.error("JSON repair also failed for job %s code-understanding: %s", job_id, repair_exc)
                raise AIInvalidResponseError(
                    f"LLM returned invalid JSON for code understanding and repair failed: {repair_exc}",
                    provider=response.provider,
                ) from repair_exc

        # 6. Normalize Parsed Dict
        parsed_dict = self._normalize_parsed_dict(parsed_dict, knowledge)

        # 7. Validate Pydantic Schema
        try:
            understanding = RepositoryCodeUnderstanding.model_validate(parsed_dict)
            understanding.provider = response.provider
            understanding.model = response.model
            understanding.latency_ms = round(response.latency_ms, 2)
            understanding.token_usage = response.token_usage
            understanding.generated_at = datetime.now(timezone.utc)
            understanding.is_fallback = False

            # 8. Run Deep Static Validation
            understanding = self.validator.validate_code_understanding(
                understanding=understanding,
                knowledge=knowledge,
                local_path=local_path,
            )
            logger.info(
                "Successfully generated code understanding for job %s using %s/%s (%d components, %d interactions, %.0fms)",
                job_id,
                understanding.provider,
                understanding.model,
                len(understanding.components),
                len(understanding.cross_component_interactions),
                understanding.latency_ms,
            )
            return understanding
        except Exception as val_exc:
            logger.error("RepositoryCodeUnderstanding validation failed for job %s: %s", job_id, val_exc)
            raise AIInvalidResponseError(
                f"Generated output does not conform to RepositoryCodeUnderstanding schema: {val_exc}",
                provider=response.provider,
            ) from val_exc

    def _normalize_parsed_dict(
        self,
        parsed_dict: Dict[str, Any],
        knowledge: RepositoryKnowledge,
    ) -> Dict[str, Any]:
        """Ensures top-level keys and structure adhere to schema defaults."""
        fallback = self.create_rule_based_fallback(knowledge)

        if not parsed_dict.get("repository_name"):
            parsed_dict["repository_name"] = fallback.repository_name
        if not parsed_dict.get("architecture_overview"):
            parsed_dict["architecture_overview"] = fallback.architecture_overview
        if not isinstance(parsed_dict.get("components"), list) or not parsed_dict["components"]:
            parsed_dict["components"] = [c.model_dump() for c in fallback.components]
        if not isinstance(parsed_dict.get("cross_component_interactions"), list):
            parsed_dict["cross_component_interactions"] = [
                i.model_dump() for i in fallback.cross_component_interactions
            ]

        return parsed_dict

    def create_rule_based_fallback(
        self,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        local_path: Optional[str] = None,
        provider: str = "rule_based_fallback",
        model: str = "deterministic-rule-based",
    ) -> RepositoryCodeUnderstanding:
        """
        Creates a grounded, deterministic fallback RepositoryCodeUnderstanding when AI APIs are unavailable.
        Uses verified static AST information, component categories, and dependency edges.
        Explicitly notes that detailed algorithmic logic branches were not evaluated by LLM.
        """
        repo_name = knowledge.repository.name
        selected_candidates = self.selector.select_components(knowledge, min_components=3, max_components=6)

        # Index parsed files
        parsed_files_map = {pf.file_path.lstrip("/"): pf for pf in knowledge.code_structure.files}
        for pf in knowledge.code_structure.files:
            parsed_files_map[pf.file_path] = pf

        components_list: List[ComponentUnderstandingItem] = []

        for cand in selected_candidates:
            pf = parsed_files_map.get(cand.file_path) or parsed_files_map.get(cand.file_path.lstrip("/"))
            code_explanations: List[CodeExplanationItem] = []

            if pf:
                # Build deterministic explanations for up to 3 symbols
                candidate_symbols = (
                    [c for c in pf.classes if not c.name.startswith("_")][:2]
                    + [f for f in pf.functions if not f.name.startswith("_")][:2]
                )[:3]

                for sym in candidate_symbols:
                    is_class = hasattr(sym, "methods")
                    name = sym.name
                    loc = sym.location
                    doc = getattr(sym, "snippet", None)
                    doc_preview = doc.splitlines()[0] if doc else "No docstring available."
                    sig = f"class {name}" if is_class else f"def {name}({', '.join(sym.parameters[:4])})"

                    code_explanations.append(
                        CodeExplanationItem(
                            name=name,
                            symbol_type="class" if is_class else "function",
                            file_path=cand.file_path,
                            line_start=loc.start_line,
                            line_end=loc.end_line,
                            signature=sig,
                            docstring=doc_preview[:120],
                            summary=f"Deterministic Structural Analysis: Primary { 'class' if is_class else 'function' } in {cand.name}.",
                            logic_explanation=f"Deterministic Structural Metadata: Signature '{sig}'. Internal branch execution not evaluated without AI provider.",
                            parameters_and_returns=f"Parameters: {getattr(sym, 'parameters', [])}. Return type: {getattr(sym, 'return_type', 'unspecified')}.",
                            internal_calls=[],
                            supporting_evidence=[
                                EvidenceReference(
                                    file_path=cand.file_path,
                                    line_start=loc.start_line,
                                    line_end=loc.end_line,
                                    evidence_type="code",
                                    confidence="high",
                                    status="confirmed",
                                    detail=f"AST verified location for symbol '{name}'",
                                )
                            ],
                            confidence="medium",
                            is_deterministic=True,
                        )
                    )

            components_list.append(
                ComponentUnderstandingItem(
                    component_id=cand.file_path,
                    name=cand.name,
                    file_path=cand.file_path,
                    category=cand.category,
                    importance_score=cand.score,
                    primary_responsibility=f"Serves as the {cand.category} module in {repo_name}, identified with {cand.score} importance score.",
                    why_important=f"Core structural module in {cand.category} layer with verified dependencies in repository architecture.",
                    inputs_and_outputs="Accepts standard module parameters and dispatches internal component calls.",
                    key_classes_and_functions=cand.key_symbols,
                    code_explanations=code_explanations,
                    dependencies=[],
                    dependents=[],
                    supporting_evidence=[
                        EvidenceReference(
                            file_path=cand.file_path,
                            evidence_type="code",
                            confidence="high",
                            status="confirmed",
                            detail=f"Verified component file ({cand.category})",
                        )
                    ],
                    confidence="medium",
                    is_deterministic=True,
                )
            )

        # Collect verified interactions from static edges
        interactions_list: List[ComponentInteractionItem] = []
        selected_paths = {c.file_path for c in selected_candidates}

        if hasattr(knowledge, "dependency_information") and knowledge.dependency_information:
            for edge in getattr(knowledge.dependency_information, "edges", []):
                src = edge.source.strip().lstrip("/")
                tgt = edge.target.strip().lstrip("/")
                if src in selected_paths and tgt in selected_paths and src != tgt:
                    ev_file = getattr(edge.evidence, "file_path", src)
                    ev_line = getattr(edge.evidence, "line_number", 1) or 1
                    interactions_list.append(
                        ComponentInteractionItem(
                            source_component=src,
                            target_component=tgt,
                            interaction_type=edge.relationship_type or "imports",
                            description=f"Static module import: {src} imports {tgt}.",
                            is_confirmed=True,
                            supporting_evidence=[
                                EvidenceReference(
                                    file_path=ev_file,
                                    line_start=ev_line,
                                    evidence_type="import",
                                    confidence="high",
                                    status="confirmed",
                                    detail="Static dependency edge",
                                )
                            ],
                            confidence="high",
                        )
                    )

        fallback_obj = RepositoryCodeUnderstanding(
            schema_version="1.0",
            repository_name=repo_name,
            architecture_overview=f"Deterministic Structural Synthesis: {repo_name} comprises {len(components_list)} primary architectural components across {knowledge.statistics.source_files} source files.",
            components=components_list,
            cross_component_interactions=interactions_list[:10],
            provider=provider,
            model=model,
            is_fallback=True,
            latency_ms=0.0,
            token_usage=None,
        )

        return self.validator.validate_code_understanding(
            understanding=fallback_obj,
            knowledge=knowledge,
            local_path=local_path,
        )


code_understanding_analyzer = CodeUnderstandingAnalyzer()
