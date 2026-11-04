"""
Validator for Application Workflow and Data-Flow Understanding.

Strictly verifies:
1. Workflow Identity: Entry points and participating components exist in RepositoryKnowledge.
2. Call Transitions: Call edges match static CallGraph edges; rejects import edges as execution transitions.
3. Call Site Locations: Verified against ParsedFile function call records independently of graph edges.
4. Control Flow: Verifies source order (same caller, line A < line B) and execution path guarantees.
5. Runtime Execution Invariant: runtime_execution_verified MUST ALWAYS be False.
6. Operation Corroboration: Storage and HTTP/SDK claims are checked against verified AST operations.
7. Budget & Count Bounds: Max 2 AI workflows, max 5 steps, max 2 data flows, max 5 components.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from ....models.schemas import (
    CallGraph,
    CallGraphEdge,
    ParsedFile,
    RepositoryKnowledge,
)
from ..project_understanding.validator import EvidenceValidator, evidence_validator
from .ast_control_flow import PythonASTControlFlowAnalyzer, python_ast_control_flow, verify_call_site_location
from .operation_verifier import (
    ExternalAPIVerificationResult,
    OperationVerifier,
    StorageVerificationResult,
    operation_verifier,
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

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WorkflowValidator:
    """
    Rigorously validates generated RepositoryWorkflowUnderstanding against
    grounded static analysis facts from RepositoryKnowledge and AST evidence.
    """

    def __init__(
        self,
        base_validator: Optional[EvidenceValidator] = None,
        operation_verifier_inst: Optional[OperationVerifier] = None,
        control_flow_inst: Optional[PythonASTControlFlowAnalyzer] = None,
    ):
        self.base_validator = base_validator or evidence_validator
        self.operation_verifier = operation_verifier_inst or operation_verifier
        self.control_flow = control_flow_inst or python_ast_control_flow

    def validate_workflow_understanding(
        self,
        understanding: RepositoryWorkflowUnderstanding,
        knowledge: RepositoryKnowledge,
        local_path: Optional[str] = None,
    ) -> RepositoryWorkflowUnderstanding:
        """
        Validates and sanitizes a complete RepositoryWorkflowUnderstanding payload.
        Ensures all invariants, edge IDs, control-flow claims, and operation verifications hold.
        """
        warnings: List[str] = list(understanding.validation_warnings)

        # 1. Index Known Repository Files and Symbols
        known_files: Set[str] = set()
        parsed_files_map: Dict[str, ParsedFile] = {}
        file_symbols_map: Dict[str, Set[str]] = {}

        if hasattr(knowledge, "code_structure") and knowledge.code_structure:
            for pf in getattr(knowledge.code_structure, "files", []):
                norm_p = pf.file_path.replace("\\", "/").strip().lstrip("/")
                known_files.add(norm_p)
                parsed_files_map[norm_p] = pf
                syms: Set[str] = set()
                for fn in pf.functions:
                    syms.add(fn.name)
                for cl in pf.classes:
                    syms.add(cl.name)
                    for m in cl.methods:
                        syms.add(m)
                        syms.add(f"{cl.name}.{m}")
                for mt in pf.methods:
                    syms.add(mt.name)
                    syms.add(f"{mt.parent_class}.{mt.name}")
                file_symbols_map[norm_p] = syms

        # 2. Index Verified Static Call Graph Edges (Excluding Imports!)
        # Map: (caller_file, caller_symbol, callee_file, callee_symbol) -> CallGraphEdge
        call_edge_map: Dict[Tuple[str, str, str, str], CallGraphEdge] = {}
        # Also index by edge ID format: "caller_file:caller_symbol->callee_file:callee_symbol"
        edge_id_set: Set[str] = set()

        if hasattr(knowledge, "architecture") and knowledge.architecture and knowledge.architecture.call_graph:
            for c_edge in getattr(knowledge.architecture.call_graph, "edges", []):
                # c_edge.caller: "path/to/file.py:scope.fn"
                c_caller_parts = c_edge.caller.split(":", 1)
                c_callee_parts = c_edge.callee.split(":", 1)

                caller_f = c_caller_parts[0].replace("\\", "/").strip().lstrip("/")
                caller_s = c_caller_parts[1] if len(c_caller_parts) > 1 else ""

                callee_f = c_callee_parts[0].replace("\\", "/").strip().lstrip("/")
                callee_s = c_callee_parts[1] if len(c_callee_parts) > 1 else ""

                key = (caller_f, caller_s, callee_f, callee_s)
                call_edge_map[key] = c_edge

                edge_id = CallSiteEvidence.format_edge_id(caller_f, caller_s, callee_f, callee_s)
                edge_id_set.add(edge_id)
                # Also add short symbol variant if file is empty
                if caller_s and callee_s:
                    edge_id_set.add(f"{caller_s}->{callee_s}")

        # 3. Index Import-Only Edges from DependencyGraph
        import_edges: Set[Tuple[str, str]] = set()
        if hasattr(knowledge, "dependency_information") and knowledge.dependency_information:
            for dep_edge in getattr(knowledge.dependency_information, "edges", []):
                s_file = dep_edge.source.replace("\\", "/").strip().lstrip("/")
                t_file = dep_edge.target.replace("\\", "/").strip().lstrip("/")
                import_edges.add((s_file, t_file))

        # 4. Validate Each AI Workflow
        validated_workflows: List[ApplicationWorkflow] = []

        for wf in understanding.workflows[:2]:  # Enforce max 2 workflows
            wf_warnings: List[str] = []

            # Invariant: runtime_execution_verified is ALWAYS False
            if wf.runtime_execution_verified:
                wf.runtime_execution_verified = False
                wf_warnings.append(
                    f"Workflow '{wf.name}': runtime_execution_verified forcibly set to False (runtime execution is never verified)."
                )

            # Validate Entry Point
            entry_f = wf.entry_point.component_id.replace("\\", "/").strip().lstrip("/")
            if entry_f not in known_files:
                wf_warnings.append(
                    f"Workflow '{wf.name}': Entry point file '{entry_f}' does not exist in repository knowledge."
                )

            # Validate Participating Components (max 5)
            valid_participants: List[WorkflowComponentReference] = []
            for comp in wf.participating_components[:5]:
                c_id = comp.component_id.replace("\\", "/").strip().lstrip("/")
                if c_id not in known_files:
                    wf_warnings.append(
                        f"Workflow '{wf.name}': Participating component file '{c_id}' does not exist in repository; unverified component."
                    )
                valid_participants.append(
                    WorkflowComponentReference(
                        component_id=c_id,
                        name=comp.name,
                        role_in_workflow=comp.role_in_workflow,
                    )
                )

            # Validate Steps (max 5)
            validated_steps: List[WorkflowStep] = []
            prev_step: Optional[WorkflowStep] = None

            for s_idx, step in enumerate(wf.steps[:5]):
                # Enforce runtime_execution_verified = False invariant
                if step.runtime_execution_verified:
                    step.runtime_execution_verified = False
                    wf_warnings.append(
                        f"Workflow '{wf.name}' Step {step.step_number}: runtime_execution_verified forcibly set to False."
                    )

                step_comp = step.component_id.replace("\\", "/").strip().lstrip("/")
                pf_step = parsed_files_map.get(step_comp)

                # Validate Call Evidence
                if step.call_evidence:
                    ce = step.call_evidence
                    caller_f = ce.caller_file.replace("\\", "/").strip().lstrip("/")
                    callee_f = ce.callee_file.replace("\\", "/").strip().lstrip("/")
                    edge_id = CallSiteEvidence.format_edge_id(caller_f, ce.caller_symbol, callee_f, ce.callee_symbol)

                    # Check against static call graph
                    edge_matched = (
                        edge_id in edge_id_set
                        or (caller_f, ce.caller_symbol, callee_f, ce.callee_symbol) in call_edge_map
                        or f"{ce.caller_symbol}->{ce.callee_symbol}" in edge_id_set
                    )

                    # Guard against treating imports as execution transitions!
                    if not edge_matched and (caller_f, callee_f) in import_edges:
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Transition from '{caller_f}' to '{callee_f}' is only an import edge, NOT a function call edge."
                        )
                        step.call_relationship_verified = False
                        ce.is_edge_verified = False
                        step.confidence = "low"
                    elif edge_matched:
                        ce.is_edge_verified = True
                        step.call_relationship_verified = True
                    else:
                        # Edge not matched in CallGraph
                        if step.call_relationship_verified:
                            step.call_relationship_verified = False
                            ce.is_edge_verified = False
                            step.confidence = "medium"
                            wf_warnings.append(
                                f"Workflow '{wf.name}' Step {step.step_number}: CallGraph edge '{edge_id}' was not found in static call graph."
                            )

                    # Check physical call-site location independently
                    if pf_step and ce.call_site_line > 0:
                        ce.is_site_location_verified = verify_call_site_location(
                            parsed_file=pf_step,
                            call_name=ce.call_name,
                            target_line=ce.call_site_line,
                            caller_scope=ce.caller_symbol,
                        )
                    else:
                        ce.is_site_location_verified = False

                # Validate Source Order & Control-Flow with Previous Step
                if prev_step and prev_step.component_id == step.component_id and prev_step.symbol_name == step.symbol_name:
                    # Intra-caller consecutive steps
                    prev_line = prev_step.call_evidence.call_site_line if prev_step.call_evidence else 0
                    curr_line = step.call_evidence.call_site_line if step.call_evidence else 0

                    if prev_line > 0 and curr_line > 0:
                        if prev_line >= curr_line:
                            step.source_order_verified = False
                            wf_warnings.append(
                                f"Workflow '{wf.name}' Step {step.step_number}: Line order violated (line {curr_line} does not follow line {prev_line})."
                            )
                        else:
                            step.source_order_verified = True
                    else:
                        step.source_order_verified = False
                elif prev_step:
                    # Cross-function or cross-file transition
                    # Line numbers CANNOT be compared across different functions or files
                    step.source_order_verified = False
                else:
                    # First step in workflow
                    step.source_order_verified = True
                    step.same_execution_path_verified = True

                # Step Action-Type Corroboration (Storage & External API)
                if step.action_type == "storage_io":
                    # Check if caller or callee component actually performs storage operations
                    has_storage = False
                    if pf_step:
                        for fn in pf_step.functions:
                            if fn.snippet and self.operation_verifier.verify_storage_in_code(fn.snippet, step_comp).storage_operation_verified:
                                has_storage = True
                                break
                    if not has_storage:
                        step.action_type = "call"
                        step.unresolved_aspects.append("Storage I/O claim uncorroborated by static receiver analysis; downgraded to call.")
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Claimed storage_io action uncorroborated in '{step_comp}'."
                        )

                elif step.action_type == "external_api":
                    has_api = False
                    if pf_step:
                        for fn in pf_step.functions:
                            if fn.snippet and self.operation_verifier.verify_external_api_in_code(fn.snippet, step_comp).external_api_operation_verified:
                                has_api = True
                                break
                    if not has_api:
                        step.action_type = "call"
                        step.unresolved_aspects.append("External API claim uncorroborated by static HTTP/SDK analysis; downgraded to call.")
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Claimed external_api action uncorroborated in '{step_comp}'."
                        )

                validated_steps.append(step)
                prev_step = step

            # Validate Data Flows (max 2)
            validated_flows: List[DataFlow] = []
            for flow in wf.data_flows[:2]:
                orig_f = flow.origin.component_id.replace("\\", "/").strip().lstrip("/")
                dest_f = flow.destination.component_id.replace("\\", "/").strip().lstrip("/")

                pf_dest = parsed_files_map.get(dest_f)

                # Storage operation corroboration
                if flow.storage_operation_verified or flow.storage_operation_type != "none":
                    dest_storage_verified = False
                    if pf_dest:
                        for fn in pf_dest.functions:
                            if fn.snippet:
                                s_res = self.operation_verifier.verify_storage_in_code(fn.snippet, dest_f)
                                if s_res.storage_operation_verified:
                                    dest_storage_verified = True
                                    break
                    if not dest_storage_verified:
                        flow.storage_operation_verified = False
                        flow.storage_operation_type = "none"
                        flow.persistence_status = "unverified_storage_claim"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}': Storage claim uncorroborated in destination '{dest_f}'."
                        )

                # External API corroboration
                if flow.external_api_operation_verified or flow.external_api_operation_type != "none":
                    dest_api_verified = False
                    if pf_dest:
                        for fn in pf_dest.functions:
                            if fn.snippet:
                                a_res = self.operation_verifier.verify_external_api_in_code(fn.snippet, dest_f)
                                if a_res.external_api_operation_verified:
                                    dest_api_verified = True
                                    break
                    if not dest_api_verified:
                        flow.external_api_operation_verified = False
                        flow.external_api_operation_type = "none"
                        flow.external_api_status = "unverified_external_api_claim"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}': External API claim uncorroborated in destination '{dest_f}'."
                        )

                validated_flows.append(flow)

            # Re-evaluate workflow summary verification flags
            wf_call_edges_verified = all(
                s.call_relationship_verified for s in validated_steps if s.action_type == "call" and s.call_evidence
            )
            wf_src_order_verified = all(s.source_order_verified for s in validated_steps)
            wf_same_path_verified = all(s.same_execution_path_verified for s in validated_steps)
            wf_exec_guaranteed = all(s.execution_guaranteed for s in validated_steps)

            validated_wf = ApplicationWorkflow(
                workflow_id=wf.workflow_id,
                name=wf.name,
                category=wf.category,
                description=wf.description,
                trigger=wf.trigger,
                entry_point=wf.entry_point,
                participating_components=valid_participants,
                steps=validated_steps,
                data_flows=validated_flows,
                final_outcome=wf.final_outcome,
                call_relationships_fully_verified=wf_call_edges_verified,
                source_order_verified=wf_src_order_verified,
                same_execution_path_verified=wf_same_path_verified,
                execution_guaranteed=wf_exec_guaranteed,
                runtime_execution_verified=False,  # ALWAYS False
                unresolved_aspects=list(set(wf.unresolved_aspects + wf_warnings))[:5],
                alternative_paths_detected=wf.alternative_paths_detected[:3],
                confidence=wf.confidence,
                is_deterministic=wf.is_deterministic,
            )
            validated_workflows.append(validated_wf)
            warnings.extend(wf_warnings)

        # 5. Validate Structural Call Chains (max 2)
        validated_structural_chains: List[StructuralCallChain] = []
        for s_chain in understanding.structural_call_chains[:2]:
            s_steps: List[WorkflowStep] = []
            for step in s_chain.steps[:5]:
                if step.runtime_execution_verified:
                    step.runtime_execution_verified = False
                s_steps.append(step)
            validated_structural_chains.append(
                StructuralCallChain(
                    chain_id=s_chain.chain_id,
                    entry_symbol=s_chain.entry_symbol,
                    entry_file=s_chain.entry_file,
                    steps=s_steps,
                    unresolved_reason=s_chain.unresolved_reason,
                )
            )

        # 6. Construct Validated RepositoryWorkflowUnderstanding
        limitations = list(understanding.analysis_limitations)
        if len(understanding.workflows) > 2:
            limitations.append(
                f"Generated {len(understanding.workflows)} workflows exceeded maximum limit of 2; retained top 2."
            )

        return RepositoryWorkflowUnderstanding(
            schema_version=understanding.schema_version,
            repository_name=understanding.repository_name,
            system_architecture_type=understanding.system_architecture_type,
            workflow_summary=understanding.workflow_summary,
            workflows=validated_workflows,
            structural_call_chains=validated_structural_chains,
            omitted_candidate_workflows=understanding.omitted_candidate_workflows,
            is_incomplete=understanding.is_incomplete,
            generated_at=understanding.generated_at,
            provider=understanding.provider,
            model=understanding.model,
            is_fallback=understanding.is_fallback,
            latency_ms=understanding.latency_ms,
            token_usage=understanding.token_usage,
            validation_warnings=warnings,
            analysis_limitations=limitations,
            static_analysis_caveats=understanding.static_analysis_caveats,
        )


workflow_validator = WorkflowValidator()
