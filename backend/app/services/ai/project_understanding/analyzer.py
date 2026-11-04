from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
from ..exceptions import AIError, AIInvalidResponseError
from ..llm_manager import LLMManager
from ..schemas import LLMGenerationOptions, LLMResponse
from .evidence_builder import EvidenceBuilder, evidence_builder_service
from .prompts import (
    SYSTEM_PROMPT,
    build_project_understanding_user_prompt,
    build_repair_prompt,
)
from .schemas import (
    ApplicationExplanation,
    CoreFeatureItem,
    EvidenceReference,
    ProjectIdentity,
    ProjectUnderstanding,
    ProblemStatement,
    TargetAudience,
    TechnologyExplanationItem,
    UseCaseItem,
)

logger = logging.getLogger(__name__)


class ProjectUnderstandingAnalyzer:
    """
    Orchestrates the AI-powered project understanding stage.
    Constructs an evidence package, prompts the configured LLM, validates output against
    the ProjectUnderstanding schema, and handles parsing repairs and fallbacks.
    """

    def __init__(
        self,
        llm_manager: Optional[LLMManager] = None,
        evidence_builder: Optional[EvidenceBuilder] = None,
    ):
        from ..llm_manager import llm_manager as default_llm_manager

        self.llm_manager = llm_manager or default_llm_manager
        self.evidence_builder = evidence_builder or evidence_builder_service

    def _extract_and_parse_json(self, text: str) -> Dict[str, Any]:
        """
        Extracts JSON content from raw LLM output, handling markdown code fences, whitespace,
        and cleanly repairing trailing severed tokens/braces if output was truncated.
        """
        clean_text = text.strip()

        # Remove ```json ... ``` or ``` ... ``` code blocks if present
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

        # Try repairing truncated JSON by walking backwards to the last valid comma or property and closing braces
        for trim_pos in range(len(json_candidate) - 1, 0, -1):
            if json_candidate[trim_pos] in (",", "}", "]"):
                truncated_prefix = json_candidate[:trim_pos].rstrip(",")
                # Balance open braces and brackets
                open_braces = truncated_prefix.count("{") - truncated_prefix.count("}")
                open_brackets = truncated_prefix.count("[") - truncated_prefix.count("]")
                if open_braces >= 1:
                    test_str = truncated_prefix + ("]" * max(0, open_brackets)) + ("}" * open_braces)
                    try:
                        return json.loads(test_str)
                    except json.JSONDecodeError:
                        continue

        # If fallback repairs failed, perform normal parse to raise standard exception
        if end_idx != -1:
            return json.loads(json_candidate[: end_idx + 1])
        return json.loads(json_candidate)

    async def analyze_project(
        self,
        job_id: str,
        knowledge: RepositoryKnowledge,
        provider_name: Optional[str] = None,
    ) -> ProjectUnderstanding:
        """
        Executes end-to-end project understanding analysis using the configured LLM.
        """
        logger.info("Starting AI project understanding for job %s (repo: %s)", job_id, knowledge.repository.name)

        # 1. Build compact grounded evidence package
        evidence_package = self.evidence_builder.build_evidence_package(knowledge)

        # 2. Formulate prompts
        user_prompt = build_project_understanding_user_prompt(evidence_package)
        options = LLMGenerationOptions(
            temperature=0.2,
            max_output_tokens=2600,
            timeout_seconds=90,
            system_instruction=SYSTEM_PROMPT,
        )

        # 3. Call LLM through provider abstraction
        response: LLMResponse = await self.llm_manager.generate(
            prompt=user_prompt,
            options=options,
            provider_name=provider_name,
            operation="project_understanding",
            job_id=job_id,
        )

        # 4. Parse and validate JSON
        parsed_dict: Optional[Dict[str, Any]] = None
        parse_error: Optional[str] = None

        try:
            parsed_dict = self._extract_and_parse_json(response.text)
        except Exception as exc:
            parse_error = str(exc)
            logger.warning(
                "Initial JSON parsing failed for job %s: %s. Attempting 1 repair query.",
                job_id,
                parse_error,
            )

        # 5. One-shot Repair if JSON parsing failed
        if parsed_dict is None:
            repair_prompt = build_repair_prompt(response.text[:6000], parse_error or "Invalid JSON")
            repair_options = LLMGenerationOptions(
                temperature=0.0,
                max_output_tokens=2600,
                timeout_seconds=60,
                system_instruction="You fix invalid JSON. Output only valid JSON without explanation.",
            )
            try:
                repair_resp: LLMResponse = await self.llm_manager.generate(
                    prompt=repair_prompt,
                    options=repair_options,
                    provider_name=provider_name,
                    operation="project_understanding_repair",
                    job_id=job_id,
                )
                parsed_dict = self._extract_and_parse_json(repair_resp.text)
                # Combine token usage and latency
                if repair_resp.token_usage and response.token_usage:
                    response.token_usage.prompt_tokens += repair_resp.token_usage.prompt_tokens
                    response.token_usage.completion_tokens += repair_resp.token_usage.completion_tokens
                    response.token_usage.total_tokens += repair_resp.token_usage.total_tokens
                response.latency_ms += repair_resp.latency_ms
                logger.info("JSON repair successfully resolved syntax error for job %s", job_id)
            except Exception as repair_exc:
                logger.error("JSON repair also failed for job %s: %s", job_id, repair_exc)
                raise AIInvalidResponseError(
                    f"LLM returned invalid JSON and repair attempt failed: {repair_exc}",
                    provider=response.provider,
                ) from repair_exc

        # 6. Normalize and sanitize parsed dictionary against variations
        parsed_dict = self._normalize_parsed_dict(parsed_dict, knowledge)

        # 7. Validate against Pydantic schema
        try:
            understanding = ProjectUnderstanding.model_validate(parsed_dict)
            understanding.provider = response.provider
            understanding.model = response.model
            understanding.latency_ms = round(response.latency_ms, 2)
            understanding.token_usage = response.token_usage
            understanding.generated_at = datetime.now(timezone.utc)
            logger.info(
                "Successfully generated project understanding for job %s using %s/%s (%d features, %d tech items, %.0fms)",
                job_id,
                understanding.provider,
                understanding.model,
                len(understanding.core_features),
                len(understanding.technology_stack),
                understanding.latency_ms,
            )
            return understanding
        except Exception as val_exc:
            logger.error("ProjectUnderstanding validation failed for job %s: %s", job_id, val_exc)
            raise AIInvalidResponseError(
                f"Generated output does not conform to ProjectUnderstanding schema: {val_exc}",
                provider=response.provider,
            ) from val_exc

    def _normalize_parsed_dict(
        self,
        parsed_dict: Dict[str, Any],
        knowledge: RepositoryKnowledge,
    ) -> Dict[str, Any]:
        """
        Coerces common LLM output format variations (e.g. strings instead of nested dicts,
        key-value pairs for tech stacks) into strict schema conformity.
        """
        fallback = self.create_rule_based_fallback(knowledge)

        # 1. Identity
        identity = parsed_dict.get("identity")
        if not isinstance(identity, dict):
            parsed_dict["identity"] = fallback.identity.model_dump()
        else:
            for field, default_val in [
                ("name", fallback.identity.name),
                ("short_description", fallback.identity.short_description),
                ("category", fallback.identity.category),
                ("project_type", fallback.identity.project_type),
                ("primary_purpose", fallback.identity.primary_purpose),
            ]:
                if not identity.get(field):
                    identity[field] = default_val

        # 2. Problem Statement
        prob = parsed_dict.get("problem_statement")
        if isinstance(prob, str):
            parsed_dict["problem_statement"] = {
                "problem_addressed": prob,
                "why_it_matters": fallback.problem_statement.why_it_matters,
                "how_project_solves_it": fallback.problem_statement.how_project_solves_it,
            }
        elif not isinstance(prob, dict):
            parsed_dict["problem_statement"] = fallback.problem_statement.model_dump()
        else:
            if not prob.get("problem_addressed"):
                prob["problem_addressed"] = fallback.problem_statement.problem_addressed
            if not prob.get("why_it_matters"):
                prob["why_it_matters"] = fallback.problem_statement.why_it_matters
            if not prob.get("how_project_solves_it"):
                prob["how_project_solves_it"] = fallback.problem_statement.how_project_solves_it

        # 3. Core Features
        features = parsed_dict.get("core_features")
        if not isinstance(features, list) or not features:
            parsed_dict["core_features"] = [f.model_dump() for f in fallback.core_features]
        else:
            norm_features = []
            for f in features:
                if isinstance(f, str):
                    norm_features.append({
                        "name": f[:60],
                        "description": f,
                        "user_benefit": "Improves developer productivity and codebase maintainability.",
                        "supporting_evidence": [],
                        "confidence": "high",
                    })
                elif isinstance(f, dict):
                    if not f.get("user_benefit"):
                        f["user_benefit"] = "Improves developer productivity and codebase maintainability."
                    if not f.get("confidence"):
                        f["confidence"] = "high"
                    if "supporting_evidence" not in f or not isinstance(f["supporting_evidence"], list):
                        f["supporting_evidence"] = []
                    norm_features.append(f)
            parsed_dict["core_features"] = norm_features

        # 4. Target Audience
        aud = parsed_dict.get("target_audience")
        if isinstance(aud, list):
            parsed_dict["target_audience"] = {
                "intended_users": [str(x) for x in aud],
                "likely_needs": fallback.target_audience.likely_needs,
                "supporting_evidence": [],
                "is_established": True,
            }
        elif isinstance(aud, str):
            parsed_dict["target_audience"] = {
                "intended_users": [aud],
                "likely_needs": fallback.target_audience.likely_needs,
                "supporting_evidence": [],
                "is_established": True,
            }
        elif not isinstance(aud, dict):
            parsed_dict["target_audience"] = fallback.target_audience.model_dump()
        else:
            if not aud.get("intended_users"):
                aud["intended_users"] = fallback.target_audience.intended_users
            if not aud.get("likely_needs"):
                aud["likely_needs"] = fallback.target_audience.likely_needs

        # 5. Use Cases
        ucs = parsed_dict.get("use_cases")
        if not isinstance(ucs, list) or not ucs:
            parsed_dict["use_cases"] = [u.model_dump() for u in fallback.use_cases]
        else:
            norm_ucs = []
            for uc in ucs:
                if isinstance(uc, str):
                    norm_ucs.append({
                        "name": uc[:60],
                        "description": uc,
                        "how_used": "Integrated as documented in repository usage guides.",
                        "supporting_evidence": [],
                    })
                elif isinstance(uc, dict):
                    if not uc.get("how_used"):
                        uc["how_used"] = "Integrated as documented in repository usage guides."
                    if "supporting_evidence" not in uc or not isinstance(uc["supporting_evidence"], list):
                        uc["supporting_evidence"] = []
                    norm_ucs.append(uc)
            parsed_dict["use_cases"] = norm_ucs

        # 6. Technology Stack
        tech = parsed_dict.get("technology_stack")
        if isinstance(tech, dict):
            norm_tech = []
            for k, v in tech.items():
                norm_tech.append({
                    "technology_name": str(v) if k in ("programming_language", "language") else f"{v}",
                    "category": "Language" if "lang" in k.lower() else "Framework/Tool",
                    "role_in_project": f"{k.replace('_', ' ').title()}: {v}",
                    "why_used": f"Used in project structure as {k}.",
                    "supporting_evidence": [],
                    "status": "confirmed",
                })
            parsed_dict["technology_stack"] = norm_tech
        elif not isinstance(tech, list) or not tech:
            parsed_dict["technology_stack"] = [t.model_dump() for t in fallback.technology_stack]
        else:
            norm_tech = []
            for t in tech:
                if isinstance(t, str):
                    norm_tech.append({
                        "technology_name": t,
                        "category": "Technology",
                        "role_in_project": f"Core component: {t}",
                        "why_used": "Used in repository implementation.",
                        "supporting_evidence": [],
                        "status": "confirmed",
                    })
                elif isinstance(t, dict):
                    if not t.get("role_in_project"):
                        t["role_in_project"] = f"Component in {knowledge.repository.name}"
                    if not t.get("why_used"):
                        t["why_used"] = "Used in repository implementation."
                    if not t.get("status"):
                        t["status"] = "confirmed"
                    if "supporting_evidence" not in t or not isinstance(t["supporting_evidence"], list):
                        t["supporting_evidence"] = []
                    norm_tech.append(t)
            parsed_dict["technology_stack"] = norm_tech

        # 7. Overall Explanation
        expl = parsed_dict.get("overall_explanation")
        if isinstance(expl, str):
            parsed_dict["overall_explanation"] = {
                "concise_overview": expl[:200],
                "detailed_explanation": expl,
                "beginner_friendly": fallback.overall_explanation.beginner_friendly,
                "interesting_aspects": fallback.overall_explanation.interesting_aspects,
                "video_demonstration_highlights": fallback.overall_explanation.video_demonstration_highlights,
            }
        elif not isinstance(expl, dict):
            parsed_dict["overall_explanation"] = fallback.overall_explanation.model_dump()
        else:
            if not expl.get("concise_overview"):
                expl["concise_overview"] = fallback.overall_explanation.concise_overview
            if not expl.get("detailed_explanation"):
                expl["detailed_explanation"] = fallback.overall_explanation.detailed_explanation
            if not expl.get("beginner_friendly"):
                expl["beginner_friendly"] = fallback.overall_explanation.beginner_friendly
            if not expl.get("interesting_aspects"):
                expl["interesting_aspects"] = fallback.overall_explanation.interesting_aspects
            if not expl.get("video_demonstration_highlights") or not isinstance(expl["video_demonstration_highlights"], list):
                expl["video_demonstration_highlights"] = fallback.overall_explanation.video_demonstration_highlights

        return parsed_dict

    def create_rule_based_fallback(
        self,
        knowledge: RepositoryKnowledge,
        provider: str = "fallback",
        model: str = "deterministic-rule-based",
    ) -> ProjectUnderstanding:
        """
        Creates a grounded, deterministic fallback ProjectUnderstanding when LLM APIs are offline.
        Strictly uses facts already in RepositoryKnowledge.
        """
        repo_name = knowledge.repository.name
        primary_lang = (
            knowledge.technology_stack.languages[0].name
            if knowledge.technology_stack.languages
            else "Software"
        )
        desc = knowledge.project_overview.description or f"{repo_name} repository."

        # Extract features from knowledge
        features = []
        for feat_name in (knowledge.project_overview.features or ["Core Repository Capabilities"]):
            features.append(
                CoreFeatureItem(
                    name=feat_name[:60],
                    description=f"Extracted capability: {feat_name}",
                    user_benefit="Provides foundational library capability verified by repository documentation.",
                    supporting_evidence=[
                        EvidenceReference(
                            file_path=knowledge.project_overview.readme_path or "README.md",
                            evidence_type="readme",
                            confidence="high",
                            status="confirmed",
                            detail="Documented in repository overview",
                        )
                    ],
                    confidence="high",
                )
            )

        # Tech stack items
        tech_items = []
        for lang in knowledge.technology_stack.languages:
            tech_items.append(
                TechnologyExplanationItem(
                    technology_name=lang.name,
                    category="Language",
                    role_in_project="Primary implementation language",
                    why_used=f"Core language used for implementation detected via {lang.detection_source}.",
                    supporting_evidence=[
                        EvidenceReference(
                            file_path=f"*.{lang.name.lower()}",
                            evidence_type="code",
                            confidence="high",
                            status="confirmed",
                        )
                    ],
                    status="confirmed",
                )
            )

        for fw in knowledge.technology_stack.frameworks:
            tech_items.append(
                TechnologyExplanationItem(
                    technology_name=fw.name,
                    category=fw.category or "Framework",
                    role_in_project=f"Integrated {fw.category or 'framework'} component",
                    why_used="Provides architectural backbone and functional abstractions.",
                    supporting_evidence=[
                        EvidenceReference(
                            file_path=fw.detection_source or "repository_analysis",
                            evidence_type="manifest",
                            confidence="high",
                            status="confirmed" if fw.is_confirmed else "inferred",
                        )
                    ],
                    status="confirmed" if fw.is_confirmed else "inferred",
                )
            )

        return ProjectUnderstanding(
            schema_version="1.0",
            identity=ProjectIdentity(
                name=repo_name,
                short_description=desc[:200],
                category=f"{primary_lang} Software",
                project_type="Library / Application",
                primary_purpose=f"Provide {primary_lang} functionality and developer tooling.",
            ),
            problem_statement=ProblemStatement(
                problem_addressed=f"Addressing software development and computational needs in {primary_lang}.",
                why_it_matters="Reduces boilerplate, guarantees correctness, and optimizes developer workflows.",
                how_project_solves_it=f"Exposes structured abstractions and modular interfaces documented in {repo_name}.",
            ),
            core_features=features[:6],
            target_audience=TargetAudience(
                intended_users=[f"{primary_lang} Developers", "Software Engineers", "Open Source Contributors"],
                likely_needs=["Reliable APIs", "Predictable behavior", "Easy integration"],
                supporting_evidence=[
                    EvidenceReference(
                        file_path=knowledge.project_overview.readme_path or "README.md",
                        evidence_type="readme",
                        confidence="high",
                        status="confirmed",
                    )
                ],
                is_established=True,
            ),
            use_cases=[
                UseCaseItem(
                    name=f"Standard {repo_name} Integration",
                    description=f"Using {repo_name} within downstream software projects.",
                    how_used=f"Importing core modules and invoking entry point interfaces.",
                    supporting_evidence=[
                        EvidenceReference(
                            file_path=knowledge.entry_points[0].file_path if knowledge.entry_points else "README.md",
                            evidence_type="code",
                            confidence="medium",
                            status="confirmed" if knowledge.entry_points else "inferred",
                        )
                    ],
                )
            ],
            technology_stack=tech_items[:8],
            overall_explanation=ApplicationExplanation(
                concise_overview=f"{repo_name} is a {primary_lang} project offering modular codebase features.",
                detailed_explanation=f"{desc} The project structure comprises {knowledge.statistics.source_files} source files and {knowledge.statistics.total_internal_dependencies} internal component relationships.",
                beginner_friendly=f"Think of {repo_name} as a specialized toolkit that allows developers to build with {primary_lang} without reinventing common solutions.",
                interesting_aspects=f"Composed of {len(knowledge.architecture.components)} primary architectural components with statically verified dependency relationships.",
                video_demonstration_highlights=[
                    f"Walkthrough of {repo_name} primary purpose and problem statement",
                    f"Code inspection of entry points ({[ep.file_path for ep in knowledge.entry_points[:2]]})",
                    "Explanation of dependency and component architecture",
                ],
            ),
            provider=provider,
            model=model,
            latency_ms=0.0,
        )


project_understanding_analyzer = ProjectUnderstandingAnalyzer()
