"""
Evidence builder for Educational Script Generation (Milestone 4, Phase 2).

Builds a compact, deterministic, provenance-preserving evidence package from:

1. ``RepositoryKnowledge``              (required)
2. ``ProjectUnderstanding``             (optional)
3. ``RepositoryCodeUnderstanding``      (optional)
4. ``RepositoryWorkflowUnderstanding``  (optional)

Design
------
* Every fact offered to the LLM is a ``ScriptEvidenceItem`` with a stable,
  deterministic ``evidence_id`` (e.g. ``FEAT-1``, ``COMP-2``, ``WF-1-S3``).
  The LLM may only cite these IDs; it never writes file paths or line numbers
  itself. The validator maps cited IDs back to the original
  ``EvidenceReference`` objects, so evidence cannot be fabricated.
* Every ``EvidenceReference`` is re-verified with the existing
  ``EvidenceValidator`` (path existence and line ranges) before it is offered.
  Invalid references are dropped, never repaired or invented.
* Each item carries a ``grounding_hint`` — the strongest grounding status a
  narration claim citing it may use (confirmed > inferred > uncertain).
* Selection is deterministic: items are ranked into priority tiers and added
  in (tier, rank, evidence_id) order until the character budget is reached.
  Omitted items are recorded, never silently dropped.
* All text is passed through the existing secret redactor, and references to
  sensitive files (``.env``, keys, credentials …) are excluded.
* No source code snippets are included; narration needs responsibilities and
  relationships, not code bodies.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from ..project_understanding.schemas import EvidenceReference
from ..project_understanding.validator import EvidenceValidator, evidence_validator as default_evidence_validator
from ..workflow_understanding.snippet_extractor import WorkflowSnippetExtractor, workflow_snippet_extractor
from .schemas import (
    DEFAULT_STATIC_ANALYSIS_CAVEATS,
    GroundingStatus,
    UnderstandingSource,
)

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
    from ..code_understanding.schemas import RepositoryCodeUnderstanding
    from ..project_understanding.schemas import ProjectUnderstanding
    from ..workflow_understanding.schemas import RepositoryWorkflowUnderstanding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Budgets and limits
# ---------------------------------------------------------------------------

DEFAULT_MAX_EVIDENCE_CHARS = 10000  # ~2,500 tokens of evidence JSON (stays safely under Groq 8000 TPM)
MAX_FEATURES = 4
MAX_USE_CASES = 2
MAX_TECHNOLOGIES = 6
MAX_COMPONENTS = 4
MAX_SYMBOLS_PER_COMPONENT = 2
MAX_INTERACTIONS = 4
MAX_WORKFLOWS = 2
MAX_STEPS_PER_WORKFLOW = 5
MAX_DATA_FLOWS_PER_WORKFLOW = 2
MAX_ENTRY_POINTS = 3
MAX_REFERENCES_PER_ITEM = 2

SUMMARY_CHARS = 260
SHORT_CHARS = 140

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
_TECH_CATEGORY_RANK = {
    "framework": 0,
    "language": 1,
    "database": 2,
    "orm": 2,
    "library": 3,
    "deployment": 4,
    "tool": 5,
}
_GROUNDING_RANK = {GroundingStatus.CONFIRMED: 0, GroundingStatus.INFERRED: 1, GroundingStatus.UNCERTAIN: 2}

_FRONTEND_FRAMEWORKS = {"react", "vue", "angular", "svelte", "next.js", "vite"}
_BACKEND_FRAMEWORKS = {
    "fastapi", "flask", "django", "express", "koa", "nestjs", "starlette", "tornado",
    "gin", "echo", "fiber", "actix-web", "axum", "rocket", "spring boot",
}
_CLI_FRAMEWORKS = {"click", "typer", "argparse", "commander", "yargs", "cobra"}
_ML_LIBRARIES = {
    "tensorflow", "torch", "pytorch", "scikit-learn", "sklearn", "keras", "xgboost",
    "lightgbm", "transformers", "pandas", "numpy",
}
_ML_KEYWORDS = ("machine learning", "deep learning", "neural", "model training", "prediction", "classifier", "anomaly detection")

_EXTRA_SECRET_RE_GSK = re.compile(r"\bgsk_[A-Za-z0-9_\-]{20,}\b")
_EXTRA_SECRET_RE_KV = re.compile(
    r"(?i)\b((?:api[_-]?key|secret[_-]?key|client[_-]?secret|password|passwd|auth[_-]?token|access[_-]?token)\s*[:=]\s*)(['\"][^'\"]{6,}['\"]|[A-Za-z0-9_\-\.]{16,})"
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ScriptEvidenceItem(BaseModel):
    """A single citable fact offered to the script-generation LLM."""
    evidence_id: str
    source: UnderstandingSource
    category: str  # identity, problem, audience, feature, use_case, technology, architecture,
    #                component, code_symbol, interaction, workflow, workflow_step, data_flow, entry_point
    title: str
    summary: str
    grounding_hint: GroundingStatus = GroundingStatus.INFERRED
    references: List[EvidenceReference] = Field(default_factory=list)

    component_id: Optional[str] = None
    component_name: Optional[str] = None
    symbol_names: List[str] = Field(default_factory=list)
    workflow_id: Optional[str] = None
    step_number: Optional[int] = None
    flow_id: Optional[str] = None
    source_component: Optional[str] = None
    target_component: Optional[str] = None
    relationship_type: Optional[str] = None
    data_relationship_status: Optional[str] = None
    verification: Dict[str, bool] = Field(default_factory=dict)

    tier: int = 3
    rank: int = 0

    def to_prompt_dict(self) -> Dict[str, Any]:
        """Compact representation for the prompt (no internal ranking fields)."""
        data: Dict[str, Any] = {
            "id": self.evidence_id,
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "max_grounding": self.grounding_hint.value,
        }
        if self.references:
            data["sources"] = [_format_reference(r) for r in self.references]
        if self.component_name:
            data["component"] = self.component_name
        if self.symbol_names:
            data["symbols"] = self.symbol_names
        if self.verification:
            data["static_verification"] = self.verification
        if self.data_relationship_status:
            data["data_relationship_status"] = self.data_relationship_status
        return data


class ScriptEvidencePackage(BaseModel):
    """Compact evidence package for one script-generation request."""
    repository_name: str
    project_name: Optional[str] = None
    project_type: Optional[str] = None
    architecture_type: Optional[str] = None
    narrative_profile: str = "general"

    available_sources: List[UnderstandingSource] = Field(default_factory=list)
    missing_sources: List[UnderstandingSource] = Field(default_factory=list)
    upstream_fallback_sources: List[UnderstandingSource] = Field(default_factory=list)

    items: List[ScriptEvidenceItem] = Field(default_factory=list)
    omitted_item_ids: List[str] = Field(default_factory=list)
    truncation_reasons: List[str] = Field(default_factory=list)
    redaction_applied: bool = False
    excluded_sensitive_paths: List[str] = Field(default_factory=list)
    invalid_reference_count: int = 0

    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS
    used_chars: int = 0
    static_analysis_caveats: List[str] = Field(default_factory=lambda: list(DEFAULT_STATIC_ANALYSIS_CAVEATS))

    def get_item(self, evidence_id: str) -> Optional[ScriptEvidenceItem]:
        return next((i for i in self.items if i.evidence_id == evidence_id), None)

    @property
    def item_ids(self) -> Set[str]:
        return {i.evidence_id for i in self.items}

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "repository_name": self.repository_name,
            "project_name": self.project_name,
            "project_type": self.project_type,
            "architecture_type": self.architecture_type,
            "narrative_profile": self.narrative_profile,
            "missing_understanding_outputs": [s.value for s in self.missing_sources],
            "evidence": [i.to_prompt_dict() for i in self.items],
            "static_analysis_caveats": self.static_analysis_caveats,
        }

    def to_prompt_json(self) -> str:
        return json.dumps(self.to_prompt_dict(), indent=1, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_reference(ref: EvidenceReference) -> str:
    if ref.line_start and ref.line_end and ref.line_end != ref.line_start:
        return f"{ref.file_path}:L{ref.line_start}-L{ref.line_end}"
    if ref.line_start:
        return f"{ref.file_path}:L{ref.line_start}"
    return ref.file_path


def _clip(text: Optional[str], limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _norm_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip().lstrip("/")


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ScriptEvidenceBuilder:
    """Deterministically builds a ``ScriptEvidencePackage``."""

    def __init__(
        self,
        evidence_validator: Optional[EvidenceValidator] = None,
        redactor: Optional[WorkflowSnippetExtractor] = None,
        max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
    ):
        self.evidence_validator = evidence_validator or default_evidence_validator
        self.redactor = redactor or workflow_snippet_extractor
        self.max_chars = max_chars

    # -- public -------------------------------------------------------------

    def build_evidence_package(
        self,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        local_path: Optional[str] = None,
        max_chars: Optional[int] = None,
    ) -> ScriptEvidencePackage:
        if knowledge is None:
            raise ValueError("RepositoryKnowledge is required to build a script evidence package.")

        budget = max_chars or self.max_chars
        self._state = _BuildState()
        self._known_files, self._line_counts, self._complete = (
            self.evidence_validator.get_repository_inventory_and_line_counts(knowledge, local_path)
        )
        self._local_path = local_path

        repo_name = knowledge.repository.name
        if knowledge.repository.owner and "/" not in repo_name:
            repo_name = f"{knowledge.repository.owner}/{repo_name}"

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

        candidates: List[ScriptEvidenceItem] = []
        candidates += self._identity_items(knowledge, project_understanding)
        candidates += self._feature_items(knowledge, project_understanding)
        candidates += self._technology_items(knowledge, project_understanding)
        candidates += self._architecture_items(knowledge, code_understanding, workflow_understanding)
        component_items = self._component_items(knowledge, code_understanding)
        candidates += component_items
        selected_component_ids = {i.component_id for i in component_items if i.category == "component"}
        candidates += self._interaction_items(code_understanding, selected_component_ids)
        candidates += self._workflow_items(workflow_understanding)
        candidates += self._entry_point_items(knowledge)

        items, omitted, used = self._apply_budget(candidates, budget)
        truncation: List[str] = []
        if omitted:
            truncation.append(
                f"Evidence budget of {budget} characters reached; {len(omitted)} lower-priority items omitted."
            )

        caveats = list(DEFAULT_STATIC_ANALYSIS_CAVEATS)
        if workflow_understanding is not None:
            caveats.append(
                "Workflow 'execution_guaranteed' flags describe the normal, non-exceptional static control-flow "
                "path only; runtime exceptions are not modeled."
            )

        package = ScriptEvidencePackage(
            repository_name=repo_name,
            project_name=self._redact(project_understanding.identity.name) if project_understanding else None,
            project_type=self._redact(project_understanding.identity.project_type) if project_understanding else None,
            architecture_type=(
                workflow_understanding.system_architecture_type if workflow_understanding else None
            ),
            narrative_profile=self._narrative_profile(knowledge, project_understanding),
            available_sources=available,
            missing_sources=missing,
            upstream_fallback_sources=fallback,
            items=items,
            omitted_item_ids=omitted,
            truncation_reasons=truncation,
            redaction_applied=self._state.redacted,
            excluded_sensitive_paths=sorted(self._state.sensitive),
            invalid_reference_count=self._state.invalid_refs,
            max_chars=budget,
            used_chars=used,
            static_analysis_caveats=caveats,
        )
        logger.info(
            "Script evidence package for %s: %d items (%d omitted), %d/%d chars, missing=%s",
            repo_name, len(items), len(omitted), used, budget, [m.value for m in missing],
        )
        return package

    # -- text & references --------------------------------------------------

    def _redact(self, text: Optional[str], limit: int = SUMMARY_CHARS) -> str:
        clipped = _clip(text, limit)
        redacted = self.redactor.redact_embedded_secrets(clipped)
        # Also redact Groq API keys (gsk_...) and colon/equals token assignments
        redacted = _EXTRA_SECRET_RE_GSK.sub("<REDACTED_SECRET>", redacted)
        redacted = _EXTRA_SECRET_RE_KV.sub(r'\1"<REDACTED_SECRET>"', redacted)
        if redacted != clipped:
            self._state.redacted = True
        return redacted

    def _verify_refs(self, refs: Iterable[Optional[EvidenceReference]]) -> List[EvidenceReference]:
        """Copies and re-verifies references; drops invalid, sensitive or duplicate ones."""
        verified: List[EvidenceReference] = []
        seen: Set[Tuple[str, Optional[int], Optional[int]]] = set()
        for ref in refs:
            if ref is None or not ref.file_path:
                continue
            copy = ref.model_copy(deep=True)
            copy.file_path = _norm_path(copy.file_path)
            if self.redactor.is_sensitive_file(copy.file_path):
                self._state.sensitive.add(copy.file_path)
                continue
            if not ref.is_valid:
                self._state.invalid_refs += 1
                continue
            ok = self.evidence_validator.validate_reference(
                copy, self._known_files, self._line_counts, self._complete, self._local_path
            )
            if not ok:
                self._state.invalid_refs += 1
                continue
            key = (copy.file_path, copy.line_start, copy.line_end)
            if key in seen:
                continue
            seen.add(key)
            if copy.detail:
                copy.detail = self._redact(copy.detail, SHORT_CHARS)
            verified.append(copy)
            if len(verified) >= MAX_REFERENCES_PER_ITEM:
                break
        return verified

    @staticmethod
    def _ref(path: Optional[str], start: Optional[int] = None, end: Optional[int] = None,
             evidence_type: str = "code", detail: Optional[str] = None) -> Optional[EvidenceReference]:
        if not path:
            return None
        return EvidenceReference(
            file_path=_norm_path(path),
            line_start=start if start and start > 0 else None,
            line_end=end if end and end > 0 else None,
            evidence_type=evidence_type,
            detail=detail,
        )

    @staticmethod
    def _hint(refs: List[EvidenceReference], strong: bool = True) -> GroundingStatus:
        return GroundingStatus.CONFIRMED if refs and strong else GroundingStatus.INFERRED

    # -- sections -----------------------------------------------------------

    def _readme_ref(self, knowledge: RepositoryKnowledge) -> List[EvidenceReference]:
        overview = knowledge.project_overview
        if overview and overview.readme_available and overview.readme_path:
            return self._verify_refs([self._ref(overview.readme_path, evidence_type="readme")])
        return []

    def _identity_items(self, knowledge, pu) -> List[ScriptEvidenceItem]:
        items: List[ScriptEvidenceItem] = []
        readme = self._readme_ref(knowledge)
        if pu is not None:
            ident = pu.identity
            items.append(ScriptEvidenceItem(
                evidence_id="PROJ-IDENTITY", source=UnderstandingSource.PROJECT_UNDERSTANDING,
                category="identity", title=self._redact(ident.name, SHORT_CHARS),
                summary=self._redact(f"{ident.short_description} Purpose: {ident.primary_purpose}"),
                grounding_hint=self._hint(readme, strong=not pu.is_fallback), references=readme,
                tier=0, rank=0,
            ))
            ps = pu.problem_statement
            items.append(ScriptEvidenceItem(
                evidence_id="PROJ-PROBLEM", source=UnderstandingSource.PROJECT_UNDERSTANDING,
                category="problem", title="Problem addressed",
                summary=self._redact(f"{ps.problem_addressed} How it solves it: {ps.how_project_solves_it}"),
                grounding_hint=GroundingStatus.INFERRED, references=readme, tier=0, rank=1,
            ))
            aud = pu.target_audience
            if aud.intended_users:
                refs = self._verify_refs(aud.supporting_evidence)
                items.append(ScriptEvidenceItem(
                    evidence_id="PROJ-AUDIENCE", source=UnderstandingSource.PROJECT_UNDERSTANDING,
                    category="audience", title="Intended users",
                    summary=self._redact(", ".join(aud.intended_users[:4])),
                    grounding_hint=self._hint(refs, aud.is_established), references=refs, tier=1, rank=0,
                ))
        else:
            description = knowledge.project_overview.description or knowledge.repository.description
            if description:
                items.append(ScriptEvidenceItem(
                    evidence_id="PROJ-IDENTITY", source=UnderstandingSource.REPOSITORY_KNOWLEDGE,
                    category="identity", title=self._redact(knowledge.repository.name, SHORT_CHARS),
                    summary=self._redact(description),
                    grounding_hint=self._hint(readme), references=readme, tier=0, rank=0,
                ))
        return items

    def _feature_items(self, knowledge, pu) -> List[ScriptEvidenceItem]:
        items: List[ScriptEvidenceItem] = []
        if pu is not None:
            ranked = []
            for idx, feat in enumerate(pu.core_features):
                refs = self._verify_refs(feat.supporting_evidence)
                ranked.append((0 if refs else 1, _CONFIDENCE_RANK.get(feat.confidence, 2), idx, feat, refs))
            ranked.sort(key=lambda r: r[:3])
            for n, (_, _, _, feat, refs) in enumerate(ranked[:MAX_FEATURES], start=1):
                items.append(ScriptEvidenceItem(
                    evidence_id=f"FEAT-{n}", source=UnderstandingSource.PROJECT_UNDERSTANDING,
                    category="feature", title=self._redact(feat.name, SHORT_CHARS),
                    summary=self._redact(f"{feat.description} Benefit: {feat.user_benefit}"),
                    grounding_hint=self._hint(refs, feat.confidence in ("high", "medium")),
                    references=refs, tier=1 if n <= 2 else 2, rank=n,
                ))
            for n, uc in enumerate(pu.use_cases[:MAX_USE_CASES], start=1):
                refs = self._verify_refs(uc.supporting_evidence)
                items.append(ScriptEvidenceItem(
                    evidence_id=f"USE-{n}", source=UnderstandingSource.PROJECT_UNDERSTANDING,
                    category="use_case", title=self._redact(uc.name, SHORT_CHARS),
                    summary=self._redact(f"{uc.description} {uc.how_used}"),
                    grounding_hint=self._hint(refs), references=refs, tier=3, rank=n,
                ))
        else:
            readme = self._readme_ref(knowledge)
            for n, feat in enumerate(knowledge.project_overview.features[:MAX_FEATURES], start=1):
                items.append(ScriptEvidenceItem(
                    evidence_id=f"FEAT-{n}", source=UnderstandingSource.REPOSITORY_KNOWLEDGE,
                    category="feature", title=self._redact(feat, SHORT_CHARS), summary=self._redact(feat),
                    grounding_hint=self._hint(readme), references=readme, tier=1 if n <= 2 else 2, rank=n,
                ))
        return items

    def _technology_items(self, knowledge, pu) -> List[ScriptEvidenceItem]:
        entries: Dict[str, Dict[str, Any]] = {}
        if pu is not None:
            for idx, tech in enumerate(pu.technology_stack):
                refs = self._verify_refs(tech.supporting_evidence)
                entries[tech.technology_name.lower()] = dict(
                    name=tech.technology_name, category=tech.category.lower(),
                    summary=f"Role: {tech.role_in_project} Why: {tech.why_used}",
                    refs=refs, strong=tech.status == "confirmed",
                    source=UnderstandingSource.PROJECT_UNDERSTANDING, order=idx,
                )
        stack = knowledge.technology_stack
        groups = (
            stack.frameworks + stack.languages + stack.databases + stack.libraries
            + stack.deployment_technologies + stack.tools
        )
        for idx, tech in enumerate(groups):
            key = tech.name.lower()
            if key in entries:
                continue
            refs = self._verify_refs(self._source_evidence_refs(knowledge, tech.name))
            entries[key] = dict(
                name=tech.name, category=tech.category.lower(),
                summary=f"Detected via {tech.detection_source}" + (f" (version {tech.version})" if tech.version else ""),
                refs=refs, strong=tech.is_confirmed,
                source=UnderstandingSource.REPOSITORY_KNOWLEDGE, order=1000 + idx,
            )
        ranked = sorted(
            entries.values(),
            key=lambda e: (0 if e["refs"] else 1, _TECH_CATEGORY_RANK.get(e["category"], 6), e["order"], e["name"].lower()),
        )
        items: List[ScriptEvidenceItem] = []
        for n, e in enumerate(ranked[:MAX_TECHNOLOGIES], start=1):
            items.append(ScriptEvidenceItem(
                evidence_id=f"TECH-{n}", source=e["source"], category="technology",
                title=self._redact(f"{e['name']} ({e['category']})", SHORT_CHARS),
                summary=self._redact(e["summary"]),
                grounding_hint=self._hint(e["refs"], e["strong"]), references=e["refs"],
                tier=2 if n <= 3 else 3, rank=n,
            ))
        return items

    def _source_evidence_refs(self, knowledge, name: str) -> List[EvidenceReference]:
        needle = name.lower()
        refs = []
        for ev in knowledge.source_evidence:
            if needle in (ev.symbol_or_statement or "").lower():
                refs.append(self._ref(ev.file_path, ev.start_line, ev.end_line,
                                      "manifest" if ev.evidence_type == "manifest_dependency" else "code"))
        return refs

    def _architecture_items(self, knowledge, cu, wu) -> List[ScriptEvidenceItem]:
        parts: List[str] = []
        if cu is not None and cu.architecture_overview:
            parts.append(cu.architecture_overview)
        if wu is not None and wu.system_architecture_type:
            parts.append(f"Architecture type: {wu.system_architecture_type}.")
        counts = knowledge.architecture.component_counts if knowledge.architecture else {}
        if counts:
            top = sorted(((k, v) for k, v in counts.items() if v and k not in ("test", "unknown")), key=lambda kv: (-kv[1], kv[0]))
            if top:
                parts.append("Statically classified components: " + ", ".join(f"{k}={v}" for k, v in top[:5]) + ".")
        if not parts:
            return []
        source = UnderstandingSource.CODE_UNDERSTANDING if cu is not None else UnderstandingSource.REPOSITORY_KNOWLEDGE
        return [ScriptEvidenceItem(
            evidence_id="ARCH-1", source=source, category="architecture", title="Architecture overview",
            summary=self._redact(" ".join(parts), 400), grounding_hint=GroundingStatus.INFERRED,
            tier=1, rank=5,
        )]

    def _component_items(self, knowledge, cu) -> List[ScriptEvidenceItem]:
        items: List[ScriptEvidenceItem] = []
        if cu is not None and cu.components:
            ranked = sorted(
                cu.components,
                key=lambda c: (-c.importance_score, 0 if c.category == "entry_point" else 1, c.component_id),
            )
            for n, comp in enumerate(ranked[:MAX_COMPONENTS], start=1):
                refs = self._verify_refs(list(comp.supporting_evidence) + [self._ref(comp.file_path)])
                symbols = [s.name for s in comp.code_explanations[:MAX_SYMBOLS_PER_COMPONENT]] or comp.key_classes_and_functions[:3]
                items.append(ScriptEvidenceItem(
                    evidence_id=f"COMP-{n}", source=UnderstandingSource.CODE_UNDERSTANDING, category="component",
                    title=self._redact(comp.name, SHORT_CHARS),
                    summary=self._redact(f"{comp.primary_responsibility} Why important: {comp.why_important}"),
                    grounding_hint=self._hint(refs, comp.confidence in ("high", "medium")), references=refs,
                    component_id=_norm_path(comp.component_id), component_name=self._redact(comp.name, SHORT_CHARS),
                    symbol_names=[self._redact(s, 80) for s in symbols],
                    tier=1 if n <= 2 else 2, rank=n,
                ))
                for m, expl in enumerate(comp.code_explanations[:MAX_SYMBOLS_PER_COMPONENT], start=1):
                    sym_refs = self._verify_refs(
                        list(expl.supporting_evidence) + [self._ref(expl.file_path, expl.line_start, expl.line_end)]
                    )
                    items.append(ScriptEvidenceItem(
                        evidence_id=f"SYM-{n}-{m}", source=UnderstandingSource.CODE_UNDERSTANDING,
                        category="code_symbol", title=self._redact(f"{expl.symbol_type} {expl.name}", SHORT_CHARS),
                        summary=self._redact(f"{expl.summary} {expl.logic_explanation}"),
                        grounding_hint=self._hint(sym_refs, expl.confidence in ("high", "medium")),
                        references=sym_refs, component_id=_norm_path(comp.component_id),
                        component_name=self._redact(comp.name, SHORT_CHARS), symbol_names=[self._redact(expl.name, 80)],
                        tier=3, rank=n * 10 + m,
                    ))
        else:
            ranked_files = sorted(
                (f for f in knowledge.important_files if f.category not in ("readme", "test", "manifest", "configuration")),
                key=lambda f: (-f.score, f.relative_path),
            )
            for n, f in enumerate(ranked_files[:MAX_COMPONENTS], start=1):
                refs = self._verify_refs([self._ref(f.relative_path)])
                items.append(ScriptEvidenceItem(
                    evidence_id=f"COMP-{n}", source=UnderstandingSource.REPOSITORY_KNOWLEDGE, category="component",
                    title=self._redact(f.relative_path.rsplit("/", 1)[-1], SHORT_CHARS),
                    summary=self._redact(f"{f.category} file: {f.reason}"),
                    grounding_hint=GroundingStatus.INFERRED, references=refs,
                    component_id=_norm_path(f.relative_path), component_name=self._redact(f.relative_path, SHORT_CHARS),
                    tier=2, rank=n,
                ))
        return items

    def _interaction_items(self, cu, selected: Set[Optional[str]]) -> List[ScriptEvidenceItem]:
        if cu is None:
            return []
        relevant = [
            i for i in cu.cross_component_interactions
            if _norm_path(i.source_component) in selected or _norm_path(i.target_component) in selected
        ]
        relevant.sort(key=lambda i: (0 if i.is_confirmed else 1, _CONFIDENCE_RANK.get(i.confidence, 2),
                                     i.source_component, i.target_component))
        items = []
        for n, inter in enumerate(relevant[:MAX_INTERACTIONS], start=1):
            refs = self._verify_refs(inter.supporting_evidence)
            items.append(ScriptEvidenceItem(
                evidence_id=f"INT-{n}", source=UnderstandingSource.CODE_UNDERSTANDING, category="interaction",
                title=self._redact(f"{inter.source_component} {inter.interaction_type} {inter.target_component}", SHORT_CHARS),
                summary=self._redact(inter.description),
                grounding_hint=self._hint(refs, inter.is_confirmed), references=refs,
                source_component=_norm_path(inter.source_component), target_component=_norm_path(inter.target_component),
                relationship_type=inter.interaction_type,
                verification={"statically_confirmed": bool(inter.is_confirmed)},
                tier=3, rank=n,
            ))
        return items

    def _workflow_items(self, wu) -> List[ScriptEvidenceItem]:
        if wu is None:
            return []
        items: List[ScriptEvidenceItem] = []
        ranked = sorted(
            enumerate(wu.workflows),
            key=lambda iw: (0 if iw[1].call_relationships_fully_verified else 1,
                            _CONFIDENCE_RANK.get(iw[1].confidence, 2), -len(iw[1].steps), iw[0]),
        )
        for n, (_, wf) in enumerate(ranked[:MAX_WORKFLOWS], start=1):
            wf_tier = 1 if n == 1 else 3
            entry_refs = self._verify_refs([self._ref(wf.entry_point.component_id)])
            items.append(ScriptEvidenceItem(
                evidence_id=f"WF-{n}", source=UnderstandingSource.WORKFLOW_UNDERSTANDING, category="workflow",
                title=self._redact(wf.name, SHORT_CHARS),
                summary=self._redact(f"{wf.description} Trigger: {wf.trigger}. Outcome: {wf.final_outcome}"),
                grounding_hint=self._hint(entry_refs, wf.call_relationships_fully_verified),
                references=entry_refs, workflow_id=wf.workflow_id,
                component_id=_norm_path(wf.entry_point.component_id),
                component_name=self._redact(wf.entry_point.name, SHORT_CHARS),
                verification={
                    "call_relationships_fully_verified": wf.call_relationships_fully_verified,
                    "execution_guaranteed": wf.execution_guaranteed,
                    "runtime_execution_verified": False,
                },
                tier=wf_tier, rank=10,
            ))
            for step in sorted(wf.steps, key=lambda s: s.step_number)[:MAX_STEPS_PER_WORKFLOW]:
                call_ref = None
                if step.call_evidence is not None and step.call_evidence.is_edge_verified:
                    ce = step.call_evidence
                    call_ref = self._ref(ce.caller_file, ce.call_site_line, ce.call_site_line, "code",
                                         f"call to {ce.call_name}")
                refs = self._verify_refs(list(step.supporting_evidence) + [call_ref])
                items.append(ScriptEvidenceItem(
                    evidence_id=f"WF-{n}-S{step.step_number}", source=UnderstandingSource.WORKFLOW_UNDERSTANDING,
                    category="workflow_step", title=self._redact(step.title, SHORT_CHARS),
                    summary=self._redact(step.description),
                    grounding_hint=self._hint(refs, step.call_relationship_verified), references=refs,
                    workflow_id=wf.workflow_id, step_number=step.step_number,
                    component_id=_norm_path(step.component_id),
                    symbol_names=[step.symbol_name] if step.symbol_name else [],
                    verification={
                        "call_relationship_verified": step.call_relationship_verified,
                        "source_order_verified": step.source_order_verified,
                        "same_execution_path_verified": step.same_execution_path_verified,
                        "execution_guaranteed": step.execution_guaranteed,
                        "runtime_execution_verified": False,
                    },
                    tier=2 if n == 1 else 3, rank=20 + step.step_number,
                ))
            for m, flow in enumerate(wf.data_flows[:MAX_DATA_FLOWS_PER_WORKFLOW], start=1):
                refs = self._verify_refs([t for tr in flow.transformations for t in tr.supporting_evidence])
                status = flow.data_relationship_status
                hint = (
                    GroundingStatus.CONFIRMED if status == "observed" and refs
                    else GroundingStatus.UNCERTAIN if status == "unknown_or_unresolved"
                    else GroundingStatus.INFERRED
                )
                persistence = (
                    f" Storage operation verified ({flow.storage_operation_type})." if flow.storage_operation_verified
                    else ""
                )
                items.append(ScriptEvidenceItem(
                    evidence_id=f"DF-{n}-{m}", source=UnderstandingSource.WORKFLOW_UNDERSTANDING, category="data_flow",
                    title=self._redact(flow.data_item_name, SHORT_CHARS),
                    summary=self._redact(
                        f"{flow.data_item_name} flows from {flow.origin.name} to {flow.destination.name}. "
                        f"Stages: {', '.join(flow.lifecycle_stages)}.{persistence}"
                    ),
                    grounding_hint=hint, references=refs, workflow_id=wf.workflow_id, flow_id=flow.flow_id,
                    data_relationship_status=status,
                    verification={
                        "storage_operation_verified": flow.storage_operation_verified,
                        "external_api_operation_verified": flow.external_api_operation_verified,
                    },
                    tier=3, rank=40 + m,
                ))
        if not wu.workflows and wu.structural_call_chains:
            chain = wu.structural_call_chains[0]
            refs = self._verify_refs([self._ref(chain.entry_file)])
            items.append(ScriptEvidenceItem(
                evidence_id="CHAIN-1", source=UnderstandingSource.WORKFLOW_UNDERSTANDING, category="workflow",
                title=self._redact(f"Static call chain from {chain.entry_symbol}", SHORT_CHARS),
                summary=self._redact(
                    f"Structural call chain with {len(chain.steps)} statically identified calls. {chain.unresolved_reason}"
                ),
                grounding_hint=GroundingStatus.INFERRED, references=refs,
                component_id=_norm_path(chain.entry_file), workflow_id=chain.chain_id,
                verification={"runtime_execution_verified": False}, tier=2, rank=10,
            ))
        return items

    def _entry_point_items(self, knowledge) -> List[ScriptEvidenceItem]:
        ranked = sorted(
            knowledge.entry_points,
            key=lambda e: (_CONFIDENCE_RANK.get(e.confidence, 2), e.file_path, e.entry_type),
        )
        items = []
        for n, ep in enumerate(ranked[:MAX_ENTRY_POINTS], start=1):
            refs = self._verify_refs(
                [self._ref(ev.file_path, ev.line_number, ev.line_number) for ev in ep.evidence]
                + [self._ref(ep.file_path)]
            )
            items.append(ScriptEvidenceItem(
                evidence_id=f"EP-{n}", source=UnderstandingSource.REPOSITORY_KNOWLEDGE, category="entry_point",
                title=self._redact(f"{ep.entry_type}: {ep.symbol_or_command or ep.file_path}", SHORT_CHARS),
                summary=self._redact(f"Statically detected entry point ({ep.entry_type}, {ep.confidence} confidence)."),
                grounding_hint=self._hint(refs, ep.confidence in ("high", "medium")), references=refs,
                component_id=_norm_path(ep.file_path), tier=2 if n == 1 else 3, rank=n,
            ))
        return items

    # -- profile & budget ---------------------------------------------------

    def _narrative_profile(self, knowledge, pu) -> str:
        stack = knowledge.technology_stack
        names = {t.name.lower() for t in stack.frameworks + stack.libraries + stack.tools}
        descriptive = ""
        if pu is not None:
            descriptive = " ".join([
                pu.identity.project_type, pu.identity.category, pu.identity.short_description,
            ]).lower()
        descriptive += " " + (knowledge.project_overview.description or "").lower()

        if names & _ML_LIBRARIES and any(k in descriptive for k in _ML_KEYWORDS) or "machine learning" in descriptive:
            return "machine_learning"
        has_front = bool(names & _FRONTEND_FRAMEWORKS)
        has_back = bool(names & _BACKEND_FRAMEWORKS)
        if has_front and has_back:
            return "full_stack_application"
        if "cli" in descriptive.split() or "command-line" in descriptive or "command line" in descriptive or (names & _CLI_FRAMEWORKS and "library" not in descriptive):
            return "cli_tool"
        if has_back or "api" in descriptive.split() or "web service" in descriptive:
            return "web_service"
        if has_front:
            return "frontend_application"
        if "library" in descriptive or "package" in descriptive or "framework" in descriptive:
            return "library"
        return "general"

    def _apply_budget(self, candidates: List[ScriptEvidenceItem], budget: int) -> Tuple[List[ScriptEvidenceItem], List[str], int]:
        ordered = sorted(candidates, key=lambda i: (i.tier, i.rank, i.evidence_id))
        selected: List[ScriptEvidenceItem] = []
        omitted: List[str] = []
        used = 0
        for item in ordered:
            size = len(json.dumps(item.to_prompt_dict(), ensure_ascii=False))
            if used + size > budget and selected:
                omitted.append(item.evidence_id)
                continue
            selected.append(item)
            used += size
        # Preserve a stable, readable order for the prompt (by category grouping).
        return selected, omitted, used


class _BuildState:
    def __init__(self) -> None:
        self.redacted = False
        self.sensitive: Set[str] = set()
        self.invalid_refs = 0


script_evidence_builder = ScriptEvidenceBuilder()
