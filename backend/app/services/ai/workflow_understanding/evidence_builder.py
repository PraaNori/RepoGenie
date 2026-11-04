"""
Deterministic Grounded Evidence Builder for Application Workflow Understanding.

Combines:
1. RepositoryKnowledge and ParsedFile AST metadata.
2. Directional CallGraph edges and grounded CallSiteEvidence.
3. Tree-sitter AST control-flow relationships (same execution path, branch exclusivity, guarantees).
4. Phase 2 candidate discovery and deterministic ranking.
5. Phase 2 syntax-preserving source code snippets (with 25-line bounds and secret redaction).
6. Phase 2 storage and external HTTP/SDK operation verifications.
7. Optional Milestone 3.3 CodeUnderstanding context.

Strictly enforces:
- Explicit per-candidate and total evidence character/token budgets.
- Absolute machine path exclusion (canonical repository-relative paths only).
- Complete secret redaction.
- Non-runtime verification caveats (runtime_execution_verified is always False).
- Never treats import dependencies as execution transitions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from ....models.schemas import (
    CallGraph,
    CallGraphEdge,
    ParsedFile,
    RepositoryKnowledge,
)
from .ast_control_flow import PythonASTControlFlowAnalyzer, build_and_verify_call_site, python_ast_control_flow
from .candidate_discoverer import (
    CandidateCallNode,
    CandidateDiscoveryResult,
    DiscoveredWorkflowCandidate,
    WorkflowCandidateDiscoverer,
    workflow_candidate_discoverer,
)
from .operation_verifier import (
    ExternalAPIVerificationResult,
    OperationVerifier,
    StorageVerificationResult,
    operation_verifier as default_operation_verifier,
)
from .schemas import (
    CallSiteEvidence,
    StructuralCallChain,
    WorkflowComponentReference,
    WorkflowStep,
)
from .snippet_extractor import (
    ExtractedWorkflowSnippet,
    WorkflowSnippetExtractor,
    workflow_snippet_extractor,
)

if TYPE_CHECKING:
    from ..code_understanding.schemas import RepositoryCodeUnderstanding
    from ..project_understanding.schemas import ProjectUnderstanding

logger = logging.getLogger(__name__)


class CandidateCallStepEvidence(BaseModel):
    """Grounded evidence for a single directional call transition in a candidate workflow."""
    step_number: int
    caller_file: str
    caller_symbol: str
    callee_file: str
    callee_symbol: str
    call_name: str
    call_site_line: int
    call_site_col: Optional[int] = None
    call_graph_edge_id: str
    call_site_id: str
    is_internal: bool = True
    hop_depth: int = 1

    # Static control flow relationship from previous step (if same caller)
    source_order_verified: bool = False
    same_execution_path_verified: bool = False
    execution_guaranteed: bool = False
    is_in_conditional: bool = False
    is_in_loop: bool = False
    is_in_try_block: bool = False
    mutually_exclusive_with_previous: bool = False

    # Snippets (caller and callee)
    caller_snippet: Optional[Dict[str, Any]] = None
    callee_snippet: Optional[Dict[str, Any]] = None

    # Storage and external API classifications
    storage_verification: Optional[Dict[str, Any]] = None
    external_api_verification: Optional[Dict[str, Any]] = None


class CandidateEvidenceItem(BaseModel):
    """Structured, bounded evidence for a single selected workflow candidate."""
    candidate_id: str
    name: str
    category: str
    entry_file: str
    entry_symbol: str
    trigger: str
    score: float
    seed_type: str
    participating_files: List[str] = Field(default_factory=list)
    participating_symbols: List[str] = Field(default_factory=list)
    call_steps: List[CandidateCallStepEvidence] = Field(default_factory=list)
    component_roles: Dict[str, str] = Field(default_factory=dict)
    limitations_and_unresolved: List[str] = Field(default_factory=list)


class WorkflowEvidencePackage(BaseModel):
    """Grounded evidence payload supplied to the AI workflow generator."""
    repository_name: str
    architecture_overview: str
    system_architecture_type: str
    selected_candidates: List[CandidateEvidenceItem] = Field(default_factory=list)
    structural_call_chains: List[StructuralCallChain] = Field(default_factory=list)
    omitted_candidates: List[str] = Field(default_factory=list)
    total_candidates_discovered: int = 0
    truncation_reasons: List[str] = Field(default_factory=list)
    budget_exceeded: bool = False


class WorkflowEvidenceBuilder:
    """
    Constructs compact, grounded, and verified evidence packages for
    application workflow and data-flow understanding.
    """

    MAX_CANDIDATE_CHAR_BUDGET = 3500       # ~875 tokens per candidate
    MAX_TOTAL_EVIDENCE_CHAR_BUDGET = 8000   # ~2,000 prompt tokens total

    def __init__(
        self,
        discoverer: Optional[WorkflowCandidateDiscoverer] = None,
        snippet_extractor: Optional[WorkflowSnippetExtractor] = None,
        operation_verifier: Optional[OperationVerifier] = None,
        control_flow_analyzer: Optional[PythonASTControlFlowAnalyzer] = None,
    ):
        self.discoverer = discoverer or workflow_candidate_discoverer
        self.snippet_extractor = snippet_extractor or workflow_snippet_extractor
        self.operation_verifier = operation_verifier or default_operation_verifier
        self.control_flow = control_flow_analyzer or python_ast_control_flow

    def build_evidence_package(
        self,
        knowledge: RepositoryKnowledge,
        project_understanding: Optional[ProjectUnderstanding] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        local_path: Optional[str] = None,
        repo_root: Optional[str] = None,
    ) -> WorkflowEvidencePackage:
        """
        Builds a bounded, verified evidence package for the top discovered workflow candidates.
        """
        repo_name = getattr(getattr(knowledge, "repository", None), "name", "unknown/repository")
        arch = getattr(knowledge, "architecture", None)
        arch_type = getattr(getattr(arch, "inferred_pattern", None), "pattern_type", "modular_monolith") if arch else "modular_monolith"
        arch_overview = getattr(knowledge.project_overview, "description", "") or "Application software repository."

        # 1. Run deterministic candidate discovery
        discovery_result: CandidateDiscoveryResult = self.discoverer.discover_candidates(knowledge)
        selected_ai_cands = discovery_result.selected_ai_candidates
        structural_cands = discovery_result.structural_call_chain_candidates
        omitted_cands = list(discovery_result.omitted_candidate_workflows)
        total_discovered = discovery_result.total_candidates_discovered

        # Index parsed files
        parsed_files_map: Dict[str, ParsedFile] = {
            f.file_path.replace("\\", "/").strip().lstrip("/"): f
            for f in getattr(getattr(knowledge, "code_structure", None), "files", [])
        }

        # Index code understanding component roles if available
        code_roles: Dict[str, str] = {}
        if code_understanding and hasattr(code_understanding, "components"):
            for comp in code_understanding.components:
                c_path = comp.file_path.replace("\\", "/").strip().lstrip("/")
                role_desc = f"{comp.name}: {comp.primary_responsibility}"
                code_roles[c_path] = role_desc

        truncation_reasons: List[str] = []
        total_evidence_chars = 0
        budget_exceeded = False

        built_candidates: List[CandidateEvidenceItem] = []

        # 2. Build structured evidence for each selected AI candidate
        for cand in selected_ai_cands:
            cand_chars = 0
            call_steps_evidence: List[CandidateCallStepEvidence] = []
            cand_limitations: List[str] = list(cand.omission_reasons)

            prev_step_node: Optional[CandidateCallNode] = None

            for idx, node in enumerate(cand.call_chain):
                step_num = idx + 1
                caller_norm = node.caller_file.replace("\\", "/").strip().lstrip("/")
                callee_norm = node.callee_file.replace("\\", "/").strip().lstrip("/")

                pf_caller = parsed_files_map.get(caller_norm)
                pf_callee = parsed_files_map.get(callee_norm)

                # Extract source snippets
                caller_snip = self.snippet_extractor.extract_symbol_snippet(
                    pf_caller, node.caller_symbol, repo_root=repo_root
                )
                callee_snip = self.snippet_extractor.extract_symbol_snippet(
                    pf_callee, node.callee_symbol, repo_root=repo_root
                )

                # Operation verification on callee snippet
                storage_res: Optional[StorageVerificationResult] = None
                api_res: Optional[ExternalAPIVerificationResult] = None
                callee_imports = [imp.module for imp in getattr(pf_callee, "imports", [])] if pf_callee else None

                if callee_snip.is_complete or callee_snip.formatted_code:
                    storage_res = self.operation_verifier.verify_storage_in_code(
                        callee_snip.formatted_code, file_path=callee_norm, file_imports=callee_imports
                    )
                    api_res = self.operation_verifier.verify_external_api_in_code(
                        callee_snip.formatted_code, file_path=callee_norm, file_imports=callee_imports
                    )

                # Control-flow analysis between consecutive intra-caller steps
                src_order = False
                same_path = False
                guaranteed = False
                in_cond = False
                in_loop = False
                in_try = False
                mut_exclusive = False

                if prev_step_node and prev_step_node.caller_file == node.caller_file and prev_step_node.caller_symbol == node.caller_symbol:
                    # Intra-caller consecutive calls
                    if pf_caller and node.call_site_line and prev_step_node.call_site_line:
                        cf_res = self.control_flow.analyze_caller_control_flow(
                            pf_caller,
                            node.caller_symbol,
                            prev_step_node.call_site_line,
                            node.call_site_line,
                        )
                        src_order = cf_res.source_order_verified
                        same_path = cf_res.same_execution_path_verified
                        guaranteed = cf_res.execution_guaranteed
                        in_cond = cf_res.is_in_conditional
                        in_loop = cf_res.is_in_loop
                        in_try = cf_res.is_in_try_block
                        mut_exclusive = cf_res.mutually_exclusive_branches
                elif idx == 0:
                    # First call in chain
                    src_order = True
                    same_path = True
                    guaranteed = True

                # Budget-conscious snippet truncation
                caller_snip_dict = caller_snip.to_dict()
                callee_snip_dict = callee_snip.to_dict()

                step_char_est = len(caller_snip.formatted_code) + len(callee_snip.formatted_code)
                if cand_chars + step_char_est > self.MAX_CANDIDATE_CHAR_BUDGET:
                    # Truncate callee snippet body to header/signature
                    callee_snip_dict["formatted_code"] = callee_snip.formatted_code.splitlines()[0] + "\n# ... [Snippet truncated for prompt budget]"
                    callee_snip_dict["is_complete"] = False
                    cand_limitations.append(f"Snippet for '{node.callee_symbol}' body truncated to preserve prompt character budget.")
                    truncation_reasons.append(f"Candidate '{cand.name}': Snippet body for '{node.callee_symbol}' truncated.")
                    budget_exceeded = True

                step_ev = CandidateCallStepEvidence(
                    step_number=step_num,
                    caller_file=caller_norm,
                    caller_symbol=node.caller_symbol,
                    callee_file=callee_norm,
                    callee_symbol=node.callee_symbol,
                    call_name=node.call_name,
                    call_site_line=node.call_site_line,
                    call_site_col=node.call_site_col,
                    call_graph_edge_id=node.call_graph_edge_id,
                    call_site_id=node.call_site_id,
                    is_internal=node.is_internal,
                    hop_depth=node.hop_depth,
                    source_order_verified=src_order,
                    same_execution_path_verified=same_path,
                    execution_guaranteed=guaranteed,
                    is_in_conditional=in_cond,
                    is_in_loop=in_loop,
                    is_in_try_block=in_try,
                    mutually_exclusive_with_previous=mut_exclusive,
                    caller_snippet=caller_snip_dict,
                    callee_snippet=callee_snip_dict,
                    storage_verification=storage_res.to_dict() if storage_res else None,
                    external_api_verification=api_res.to_dict() if api_res else None,
                )
                call_steps_evidence.append(step_ev)
                cand_chars += step_char_est
                prev_step_node = node

            # Build component roles for participating files
            roles: Dict[str, str] = {}
            for f in cand.participating_files:
                norm_f = f.replace("\\", "/").strip().lstrip("/")
                roles[norm_f] = code_roles.get(norm_f, f"Component defined at {norm_f}")

            # Check total evidence budget
            if total_evidence_chars + cand_chars > self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET:
                for step_ev in call_steps_evidence:
                    if step_ev.caller_snippet and len(step_ev.caller_snippet.get("formatted_code", "")) > 100:
                        step_ev.caller_snippet["formatted_code"] = step_ev.caller_snippet["formatted_code"].splitlines()[0] + "\n# ... [Snippet truncated for prompt budget]"
                        step_ev.caller_snippet["is_complete"] = False
                    if step_ev.callee_snippet and len(step_ev.callee_snippet.get("formatted_code", "")) > 100:
                        step_ev.callee_snippet["formatted_code"] = step_ev.callee_snippet["formatted_code"].splitlines()[0] + "\n# ... [Snippet truncated for prompt budget]"
                        step_ev.callee_snippet["is_complete"] = False
                cand_chars = sum(
                    len((s.caller_snippet or {}).get("formatted_code", "")) + len((s.callee_snippet or {}).get("formatted_code", ""))
                    for s in call_steps_evidence
                )

                if total_evidence_chars + cand_chars > self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET:
                    omitted_cands.append(
                        f"Candidate '{cand.name}' omitted to enforce total evidence package budget ({self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET} chars)."
                    )
                    truncation_reasons.append(
                        f"Candidate '{cand.name}' omitted to respect total evidence ceiling ({self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET} chars)."
                    )
                    budget_exceeded = True
                    continue
                else:
                    budget_exceeded = True
                    truncation_reasons.append(
                        f"Candidate '{cand.name}' snippets truncated to stay within total evidence ceiling ({self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET} chars)."
                    )
                    cand_limitations.append("Candidate snippets truncated to stay within total prompt evidence budget.")

            built_candidates.append(
                CandidateEvidenceItem(
                    candidate_id=cand.candidate_id,
                    name=cand.name,
                    category=cand.category,
                    entry_file=cand.entry_file,
                    entry_symbol=cand.entry_symbol,
                    trigger=cand.trigger,
                    score=cand.score,
                    seed_type=cand.seed_type,
                    participating_files=cand.participating_files,
                    participating_symbols=cand.participating_symbols,
                    call_steps=call_steps_evidence,
                    component_roles=roles,
                    limitations_and_unresolved=cand_limitations,
                )
            )
            total_evidence_chars += cand_chars

        # 3. Format deterministic structural call chains (max 2)
        structural_chains: List[StructuralCallChain] = []
        for s_cand in structural_cands[:2]:
            steps: List[WorkflowStep] = []
            for s_idx, node in enumerate(s_cand.call_chain):
                steps.append(
                    WorkflowStep(
                        step_number=s_idx + 1,
                        title=f"Call {node.call_name}()",
                        component_id=node.caller_file,
                        symbol_name=node.caller_symbol,
                        action_type="call",
                        description=f"Static call transition from {node.caller_symbol} to {node.callee_symbol}.",
                        call_relationship_verified=True,
                        source_order_verified=(s_idx == 0 or node.caller_file == s_cand.call_chain[s_idx - 1].caller_file),
                        same_execution_path_verified=True,
                        execution_guaranteed=False,
                        runtime_execution_verified=False,
                        is_deterministic=True,
                        confidence="medium",
                        call_evidence=CallSiteEvidence(
                            caller_file=node.caller_file,
                            caller_symbol=node.caller_symbol,
                            callee_file=node.callee_file,
                            callee_symbol=node.callee_symbol,
                            call_name=node.call_name,
                            call_site_line=node.call_site_line,
                            call_site_column=node.call_site_col,
                            call_graph_edge_id=node.call_graph_edge_id,
                            call_site_id=node.call_site_id,
                            is_edge_verified=True,
                            is_site_location_verified=(node.call_site_line > 0),
                        ),
                    )
                )
            structural_chains.append(
                StructuralCallChain(
                    chain_id=s_cand.candidate_id,
                    entry_symbol=s_cand.entry_symbol,
                    entry_file=s_cand.entry_file,
                    steps=steps,
                    unresolved_reason="Deterministic static call chain extracted from CallGraph; semantic AI workflow omitted to conserve budget.",
                )
            )

        if total_evidence_chars > self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET:
            budget_exceeded = True
            truncation_reasons.append(
                f"Total evidence package size ({total_evidence_chars} chars) exceeded total ceiling ({self.MAX_TOTAL_EVIDENCE_CHAR_BUDGET} chars)."
            )

        return WorkflowEvidencePackage(
            repository_name=repo_name,
            architecture_overview=arch_overview,
            system_architecture_type=arch_type,
            selected_candidates=built_candidates,
            structural_call_chains=structural_chains,
            omitted_candidates=omitted_cands,
            total_candidates_discovered=total_discovered,
            truncation_reasons=truncation_reasons,
            budget_exceeded=budget_exceeded,
        )


workflow_evidence_builder = WorkflowEvidenceBuilder()
