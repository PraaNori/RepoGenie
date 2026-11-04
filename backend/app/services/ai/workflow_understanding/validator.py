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

                    # Check caller file consistency with step
                    if step_comp != caller_f and step_comp in known_files:
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Step component '{step_comp}' does not match call evidence caller '{caller_f}'."
                        )

                    expected_edge_id = CallSiteEvidence.format_edge_id(caller_f, ce.caller_symbol, callee_f, ce.callee_symbol)

                    # 1. Edge Identity & Graph Edge Verification
                    edge_id_matches = (ce.call_graph_edge_id == expected_edge_id)
                    if not edge_id_matches:
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Claimed call_graph_edge_id '{ce.call_graph_edge_id}' does not match expected edge ID '{expected_edge_id}'."
                        )

                    edge_in_graph = (
                        expected_edge_id in edge_id_set
                        or (caller_f, ce.caller_symbol, callee_f, ce.callee_symbol) in call_edge_map
                        or f"{ce.caller_symbol}->{ce.callee_symbol}" in edge_id_set
                    )

                    if not edge_in_graph and (caller_f, callee_f) in import_edges:
                        # Rejection of import edge as call transition
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Transition from '{caller_f}' to '{callee_f}' is only an import edge, NOT a function call edge."
                        )
                        step.call_relationship_verified = False
                        ce.is_edge_verified = False
                        step.confidence = "low"
                    elif edge_in_graph and edge_id_matches:
                        ce.is_edge_verified = True
                        step.call_relationship_verified = True
                    else:
                        step.call_relationship_verified = False
                        ce.is_edge_verified = False
                        step.confidence = "medium"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: CallGraph edge '{expected_edge_id}' was not found in static call graph."
                        )

                    # 2. Independent Call Site Expression & Location Verification
                    expected_site_id_col = CallSiteEvidence.format_site_id(
                        caller_f, ce.caller_symbol, callee_f, ce.callee_symbol, ce.call_site_line, ce.call_site_column
                    )
                    expected_site_id_no_col = CallSiteEvidence.format_site_id(
                        caller_f, ce.caller_symbol, callee_f, ce.callee_symbol, ce.call_site_line, None
                    )

                    site_id_matches = (ce.call_site_id in (expected_site_id_col, expected_site_id_no_col))
                    if not site_id_matches:
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Claimed call_site_id '{ce.call_site_id}' does not match caller/callee source location."
                        )

                    pf_caller = parsed_files_map.get(caller_f)
                    site_location_ok = False
                    if pf_caller and ce.call_site_line > 0:
                        site_location_ok = verify_call_site_location(
                            parsed_file=pf_caller,
                            call_name=ce.call_name,
                            target_line=ce.call_site_line,
                            caller_scope=ce.caller_symbol,
                            target_column=ce.call_site_column,
                        )

                    if site_location_ok and site_id_matches:
                        ce.is_site_location_verified = True
                    else:
                        ce.is_site_location_verified = False
                        wf_warnings.append(
                            f"Workflow '{wf.name}' Step {step.step_number}: Call site expression '{ce.call_name}' could not be verified at line {ce.call_site_line} (col {ce.call_site_column}) in '{caller_f}'."
                        )

                # Validate Source Order & Control-Flow with Previous Step
                if prev_step and prev_step.component_id == step.component_id and prev_step.symbol_name == step.symbol_name:
                    # Intra-caller consecutive steps
                    prev_line = prev_step.call_evidence.call_site_line if prev_step.call_evidence else 0
                    curr_line = step.call_evidence.call_site_line if step.call_evidence else 0
                    prev_call_name = prev_step.call_evidence.call_name if prev_step.call_evidence else None
                    curr_call_name = step.call_evidence.call_name if step.call_evidence else None

                    if prev_line > 0 and curr_line > 0:
                        pf_caller = parsed_files_map.get(step_comp)
                        cf_res = self.control_flow.analyze_caller_control_flow(
                            parsed_file=pf_caller,
                            caller_symbol=step.symbol_name or "",
                            call_a_line=prev_line,
                            call_b_line=curr_line,
                            call_a_name=prev_call_name,
                            call_b_name=curr_call_name,
                        )
                        step.source_order_verified = cf_res.source_order_verified
                        step.same_execution_path_verified = cf_res.same_execution_path_verified
                        step.execution_guaranteed = cf_res.execution_guaranteed

                        if not cf_res.source_order_verified:
                            wf_warnings.append(
                                f"Workflow '{wf.name}' Step {step.step_number}: Line order violated (line {curr_line} does not follow line {prev_line})."
                            )
                        if cf_res.mutually_exclusive_branches or not cf_res.same_execution_path_verified:
                            step.same_execution_path_verified = False
                            step.execution_guaranteed = False
                            wf_warnings.append(
                                f"Workflow '{wf.name}' Step {step.step_number}: Step {prev_step.step_number} and Step {step.step_number} reside in mutually exclusive branches or disconnected paths."
                            )
                        elif not cf_res.execution_guaranteed:
                            step.execution_guaranteed = False
                            reason = "try blocks/exception handlers" if cf_res.is_in_try_block else "conditional branching, loops, or early returns"
                            wf_warnings.append(
                                f"Workflow '{wf.name}' Step {step.step_number}: Execution is not guaranteed after Step {prev_step.step_number} due to {reason}."
                            )
                    else:
                        step.source_order_verified = False
                        step.execution_guaranteed = False
                elif prev_step:
                    # Cross-function or cross-file transition: Line numbers CANNOT be compared!
                    step.source_order_verified = False
                    step.execution_guaranteed = False
                else:
                    # First step in workflow
                    step.source_order_verified = True
                    step.same_execution_path_verified = True
                    step.execution_guaranteed = False

                # Step Action-Type Corroboration (Storage & External API)
                if step.action_type == "storage_io":
                    has_storage = False
                    if pf_step and step.symbol_name:
                        for fn in pf_step.functions:
                            if (fn.name == step.symbol_name or fn.name == step.symbol_name.split(".")[-1]) and fn.snippet:
                                if self.operation_verifier.verify_storage_in_code(fn.snippet, step_comp).storage_operation_verified:
                                    has_storage = True
                                    break
                    if not has_storage and step.call_evidence:
                        pf_callee = parsed_files_map.get(step.call_evidence.callee_file.replace("\\", "/").strip().lstrip("/"))
                        callee_sym = step.call_evidence.callee_symbol
                        if pf_callee and callee_sym:
                            for fn in pf_callee.functions:
                                if (fn.name == callee_sym or fn.name == callee_sym.split(".")[-1]) and fn.snippet:
                                    if self.operation_verifier.verify_storage_in_code(fn.snippet, pf_callee.file_path).storage_operation_verified:
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
                    if pf_step and step.symbol_name:
                        for fn in pf_step.functions:
                            if (fn.name == step.symbol_name or fn.name == step.symbol_name.split(".")[-1]) and fn.snippet:
                                if self.operation_verifier.verify_external_api_in_code(fn.snippet, step_comp).external_api_operation_verified:
                                    has_api = True
                                    break
                    if not has_api and step.call_evidence:
                        pf_callee = parsed_files_map.get(step.call_evidence.callee_file.replace("\\", "/").strip().lstrip("/"))
                        callee_sym = step.call_evidence.callee_symbol
                        if pf_callee and callee_sym:
                            for fn in pf_callee.functions:
                                if (fn.name == callee_sym or fn.name == callee_sym.split(".")[-1]) and fn.snippet:
                                    if self.operation_verifier.verify_external_api_in_code(fn.snippet, pf_callee.file_path).external_api_operation_verified:
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
                pf_orig = parsed_files_map.get(orig_f)

                # Storage operation corroboration
                if flow.storage_operation_verified or flow.storage_operation_type != "none":
                    dest_storage_res = None
                    for pf_cand in (pf_dest, pf_orig):
                        if pf_cand:
                            for fn in pf_cand.functions:
                                if fn.snippet:
                                    s_res = self.operation_verifier.verify_storage_in_code(fn.snippet, pf_cand.file_path)
                                    if s_res.storage_operation_verified:
                                        dest_storage_res = s_res
                                        break
                            if dest_storage_res:
                                break

                    if dest_storage_res:
                        flow.storage_operation_verified = True
                        flow.storage_operation_type = dest_storage_res.storage_operation_type
                        # Sanitize persistence_status so static writes are not described as confirmed runtime transactions
                        if any(term in (flow.persistence_status or "").lower() for term in ("success", "confirmed", "persisted_successfully", "committed")):
                            flow.persistence_status = "static_storage_operation_detected"
                    else:
                        flow.storage_operation_verified = False
                        flow.storage_operation_type = "none"
                        flow.persistence_status = "unverified_storage_claim"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}': Storage claim uncorroborated in destination '{dest_f}'."
                        )

                # External API corroboration
                if flow.external_api_operation_verified or flow.external_api_operation_type != "none":
                    dest_api_res = None
                    for pf_cand in (pf_dest, pf_orig):
                        if pf_cand:
                            for fn in pf_cand.functions:
                                if fn.snippet:
                                    a_res = self.operation_verifier.verify_external_api_in_code(fn.snippet, pf_cand.file_path)
                                    if a_res.external_api_operation_verified:
                                        dest_api_res = a_res
                                        break
                            if dest_api_res:
                                break

                    if dest_api_res:
                        flow.external_api_operation_verified = True
                        # Ensure third-party SDK calls remain external_sdk_call, not http_request
                        if dest_api_res.external_api_operation_type == "external_sdk_call":
                            if flow.external_api_operation_type != "external_sdk_call":
                                wf_warnings.append(
                                    f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}': Third-party SDK call corrected from '{flow.external_api_operation_type}' to 'external_sdk_call'."
                                )
                            flow.external_api_operation_type = "external_sdk_call"
                        else:
                            flow.external_api_operation_type = dest_api_res.external_api_operation_type

                        # Sanitize network-success claims
                        if any(term in (flow.external_api_status or "").lower() for term in ("success", "200_ok", "received_response", "succeeded")):
                            flow.external_api_status = "static_external_api_operation_detected"
                    else:
                        flow.external_api_operation_verified = False
                        flow.external_api_operation_type = "none"
                        flow.external_api_status = "unverified_external_api_claim"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}': External API claim uncorroborated in destination '{dest_f}'."
                        )

                # Data transformations validation
                valid_transforms = []
                for t in flow.transformations[:2]:
                    t_comp = t.performed_by_component.replace("\\", "/").strip().lstrip("/")
                    pf_t = parsed_files_map.get(t_comp)
                    if t_comp not in known_files or not pf_t:
                        t.transformation_verified = False
                        t.data_relationship_status = "unknown_or_unresolved"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}' transformation '{t.transformation_name}': component '{t_comp}' does not exist in repository."
                        )
                    else:
                        t_verified, status, op_desc, t_warnings = self.control_flow.verify_data_transformation_evidence(
                            parsed_file=pf_t,
                            transformation=t,
                            data_flow=flow,
                            workflow_steps=validated_steps,
                            parsed_files_map=parsed_files_map,
                        )
                        t.transformation_verified = t_verified
                        t.data_relationship_status = status
                        if op_desc:
                            t.observed_operation = op_desc
                        for tw in t_warnings:
                            wf_warnings.append(f"Workflow '{wf.name}': {tw}")
                    valid_transforms.append(t)
                flow.transformations = valid_transforms

                # Demote observed data flows without static parameter/return evidence or observed transformations
                if flow.data_relationship_status == "observed":
                    has_observed_transformation = any(t.transformation_verified and t.data_relationship_status == "observed" for t in flow.transformations)
                    has_call_traffic = any(
                        s.call_evidence and (s.call_evidence.caller_file == orig_f or s.call_evidence.callee_file == dest_f)
                        for s in validated_steps
                    )
                    if not has_call_traffic and not has_observed_transformation:
                        flow.data_relationship_status = "inferred"
                        wf_warnings.append(
                            f"Workflow '{wf.name}' DataFlow '{flow.data_item_name}': Data-flow relationship lacks verified call-parameter evidence or observed transformations; demoted from observed to inferred."
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
