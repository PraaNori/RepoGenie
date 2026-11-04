"""
Unit tests for Milestone 3.4 Application Workflow and Data-Flow Understanding:
1. Pydantic schema validation, strict limits, and concrete nested models.
2. Python Tree-sitter AST control-flow path analysis (reachability, branches, guarantees).
3. Call-site vs CallGraph edge identity separation and location verification.
"""

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    CallGraphEdge,
    FunctionCallInfo,
    ParsedFile,
    RelationshipEvidence,
)
from app.services.ai.workflow_understanding import (
    ApplicationWorkflow,
    CallSiteEvidence,
    ControlFlowAnalysisResult,
    DataFlow,
    DataTransformation,
    PythonASTControlFlowAnalyzer,
    RepositoryWorkflowUnderstanding,
    StructuralCallChain,
    WorkflowComponentReference,
    WorkflowStep,
    build_and_verify_call_site,
    python_ast_control_flow,
    verify_call_site_location,
)


# ===========================================================================
# 1. Schema Validation & Concrete Types Tests
# ===========================================================================

def test_workflow_component_reference_concrete():
    ref = WorkflowComponentReference(
        component_id="src/click/core.py",
        name="Command Execution Engine",
        role_in_workflow="Dispatches invocations",
    )
    assert ref.component_id == "src/click/core.py"
    assert ref.name == "Command Execution Engine"
    assert ref.role_in_workflow == "Dispatches invocations"


def test_workflow_step_runtime_verification_always_false():
    # Attempting to construct with runtime_execution_verified=True must raise ValidationError
    with pytest.raises(ValidationError):
        WorkflowStep(
            step_number=1,
            title="Execute Command",
            component_id="src/click/core.py",
            description="Executes CLI command callback.",
            runtime_execution_verified=True,  # Forbidden
        )


def test_application_workflow_concrete_types_and_limits():
    entry = WorkflowComponentReference(
        component_id="src/click/core.py",
        name="Command Engine",
        role_in_workflow="Entry point",
    )
    part = WorkflowComponentReference(
        component_id="src/click/types.py",
        name="Type Parser",
        role_in_workflow="Parameter conversion",
    )
    step1 = WorkflowStep(
        step_number=1,
        title="Parse Parameters",
        component_id="src/click/core.py",
        description="Parses parameters into context.",
    )
    flow1 = DataFlow(
        flow_id="flow-1",
        workflow_id="wf-1",
        data_item_name="CLI Args",
        origin=entry,
        destination=part,
    )

    wf = ApplicationWorkflow(
        workflow_id="wf-1",
        name="CLI Command Execution Flow",
        description="End-to-end command execution.",
        trigger="User executes click command in terminal.",
        entry_point=entry,
        participating_components=[part],
        steps=[step1],
        data_flows=[flow1],
        final_outcome="Command output printed to stdout.",
    )
    assert isinstance(wf.entry_point, WorkflowComponentReference)
    assert isinstance(wf.participating_components[0], WorkflowComponentReference)
    assert isinstance(wf.data_flows[0], DataFlow)
    assert wf.runtime_execution_verified is False


def test_application_workflow_step_limit_enforced():
    entry = WorkflowComponentReference(
        component_id="src/click/core.py",
        name="Command Engine",
        role_in_workflow="Entry point",
    )
    # Creating 6 steps when max is 5 must raise ValidationError
    steps = [
        WorkflowStep(
            step_number=i,
            title=f"Step {i}",
            component_id="src/click/core.py",
            description=f"Description {i}",
        )
        for i in range(1, 7)
    ]
    with pytest.raises(ValidationError):
        ApplicationWorkflow(
            workflow_id="wf-too-many-steps",
            name="Too Many Steps Workflow",
            description="Testing step limits.",
            trigger="CLI trigger",
            entry_point=entry,
            steps=steps,  # 6 steps > max 5
            final_outcome="Outcome",
        )


def test_repository_workflow_understanding_strict_limits():
    entry = WorkflowComponentReference(
        component_id="src/click/core.py",
        name="Command Engine",
        role_in_workflow="Entry point",
    )
    wf_factory = lambda i: ApplicationWorkflow(
        workflow_id=f"wf-{i}",
        name=f"Workflow {i}",
        description=f"Description {i}",
        trigger="Trigger",
        entry_point=entry,
        final_outcome="Outcome",
    )

    # Max 2 workflows allowed
    wf1 = wf_factory(1)
    wf2 = wf_factory(2)
    wf3 = wf_factory(3)

    # Valid with 2 workflows
    repo_wf = RepositoryWorkflowUnderstanding(
        repository_name="pallets/click",
        system_architecture_type="CLI Application",
        workflow_summary="Click executes commands through modular parsing.",
        workflows=[wf1, wf2],
    )
    assert len(repo_wf.workflows) == 2

    # Exceeding 2 workflows must raise ValidationError
    with pytest.raises(ValidationError):
        RepositoryWorkflowUnderstanding(
            repository_name="pallets/click",
            system_architecture_type="CLI Application",
            workflow_summary="Click executes commands.",
            workflows=[wf1, wf2, wf3],  # 3 workflows > max 2
        )

    # Exceeding 2 structural call chains must raise ValidationError
    sc_factory = lambda i: StructuralCallChain(
        chain_id=f"chain-{i}",
        entry_symbol="cli",
        entry_file="cli.py",
    )
    with pytest.raises(ValidationError):
        RepositoryWorkflowUnderstanding(
            repository_name="pallets/click",
            system_architecture_type="CLI Application",
            workflow_summary="Click executes commands.",
            workflows=[wf1],
            structural_call_chains=[sc_factory(1), sc_factory(2), sc_factory(3)],  # 3 > max 2
        )


# ===========================================================================
# 2. Python AST Control-Flow Path Analysis Tests
# ===========================================================================

def test_ast_control_flow_linear_block_guaranteed_execution():
    """Two calls in the same basic block without branches are guaranteed to execute sequentially."""
    code = """
def process_data(val):
    clean_val = sanitize(val)
    result = transform(clean_val)
    return result
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="processor.py",
        caller_symbol="process_data",
        call_a_line=3,
        call_b_line=4,
        call_a_name="sanitize",
        call_b_name="transform",
    )
    assert res.is_same_caller is True
    assert res.source_order_verified is True
    assert res.same_execution_path_verified is True
    assert res.execution_guaranteed is True
    assert res.runtime_execution_verified is False
    assert len(res.unresolved_aspects) == 0


def test_ast_control_flow_mutually_exclusive_branches():
    """Calls inside if and else blocks reside on mutually exclusive execution paths."""
    code = """
def route_request(mode, payload):
    if mode == "sync":
        execute_sync(payload)
    else:
        execute_async(payload)
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="router.py",
        caller_symbol="route_request",
        call_a_line=4,
        call_b_line=6,
        call_a_name="execute_sync",
        call_b_name="execute_async",
    )
    assert res.is_same_caller is True
    assert res.source_order_verified is True
    assert res.same_execution_path_verified is False
    assert res.execution_guaranteed is False
    assert any("mutually exclusive conditional branches" in w for w in res.unresolved_aspects)


def test_ast_control_flow_mutually_exclusive_elif_branches():
    """Calls inside elif and else blocks are also mutually exclusive."""
    code = """
def dispatch(level):
    if level == 1:
        log_info()
    elif level == 2:
        log_warn()
    else:
        log_error()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="logger.py",
        caller_symbol="dispatch",
        call_a_line=5,
        call_b_line=7,
        call_a_name="log_warn",
        call_b_name="log_error",
    )
    assert res.same_execution_path_verified is False
    assert res.execution_guaranteed is False


def test_ast_control_flow_nested_condition_with_early_return():
    """
    User specification example:
    if flag:
        validate()
        if another_condition:
            return
    save()
    Valid path exists (when another_condition is False), but execution is NOT guaranteed.
    """
    code = """
def handle_action(flag, another_condition):
    if flag:
        validate()
        if another_condition:
            return
    save()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="handler.py",
        caller_symbol="handle_action",
        call_a_line=4,
        call_b_line=7,
        call_a_name="validate",
        call_b_name="save",
    )
    assert res.is_same_caller is True
    assert res.source_order_verified is True
    assert res.same_execution_path_verified is True
    assert res.execution_guaranteed is False
    assert any("Conditional early exit" in w for w in res.unresolved_aspects)


def test_ast_control_flow_unconditional_early_return_prevents_same_path():
    """When an unconditional return appears after Call A, execution can never reach Call B."""
    code = """
def handle_exit(flag):
    if flag:
        cleanup()
        return
    proceed()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="cleanup.py",
        caller_symbol="handle_exit",
        call_a_line=4,
        call_b_line=6,
        call_a_name="cleanup",
        call_b_name="proceed",
    )
    assert res.same_execution_path_verified is False
    assert res.execution_guaranteed is False
    assert any("Unconditional early exit" in w for w in res.unresolved_aspects)


def test_ast_control_flow_loop_enclosing_call_prevents_guarantee():
    """Calls inside loops can execute 0 or N times; execution is reachable but not guaranteed."""
    code = """
def iterate_items(items):
    for item in items:
        inspect_item(item)
    finalize_batch()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="batch.py",
        caller_symbol="iterate_items",
        call_a_line=4,
        call_b_line=5,
        call_a_name="inspect_item",
        call_b_name="finalize_batch",
    )
    assert res.same_execution_path_verified is True
    assert res.execution_guaranteed is False
    assert any("loop" in w for w in res.unresolved_aspects)


def test_ast_control_flow_try_except_mutually_exclusive():
    """Calls in try and except clauses are mutually exclusive."""
    code = """
def safe_io():
    try:
        perform_read()
    except IOError:
        handle_error()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="io.py",
        caller_symbol="safe_io",
        call_a_line=4,
        call_b_line=6,
        call_a_name="perform_read",
        call_b_name="handle_error",
    )
    assert res.same_execution_path_verified is False
    assert res.execution_guaranteed is False
    assert any("mutually exclusive try/except" in w for w in res.unresolved_aspects)


# ===========================================================================
# 3. Source-Order & Boundary Restriction Tests
# ===========================================================================

def test_source_order_verified_same_caller():
    """Source line order within the same caller evaluates to True when line A < line B."""
    code = """
def linear_ops():
    step_one()
    step_two()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="ops.py",
        caller_symbol="linear_ops",
        call_a_line=3,
        call_b_line=4,
    )
    assert res.is_same_caller is True
    assert res.source_order_verified is True


def test_source_order_inverted_lines():
    """If call A line > call B line, source_order_verified is False."""
    code = """
def linear_ops():
    step_one()
    step_two()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="ops.py",
        caller_symbol="linear_ops",
        call_a_line=4,
        call_b_line=3,
    )
    assert res.source_order_verified is False
    assert any("does not textually precede" in w for w in res.unresolved_aspects)


def test_rejection_of_cross_file_line_comparisons():
    """Line numbers must NEVER be compared across different files."""
    code = "def stub(): pass"
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="file_a.py",
        caller_symbol="stub",
        call_a_line=10,
        call_b_line=20,
        call_b_file="file_b.py",  # Cross-file comparison!
    )
    assert res.is_same_caller is False
    assert res.source_order_verified is False
    assert res.same_execution_path_verified is False
    assert any("different files" in w for w in res.unresolved_aspects)


def test_rejection_of_cross_function_line_comparisons():
    """Line numbers must NEVER be compared across different functions."""
    code = """
def func_a():
    call_in_a()

def func_b():
    call_in_b()
"""
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="shared.py",
        caller_symbol="func_a",
        call_a_line=3,
        call_b_line=6,
        call_b_caller_symbol="func_b",  # Cross-function comparison!
    )
    assert res.is_same_caller is False
    assert res.source_order_verified is False
    assert res.same_execution_path_verified is False
    assert any("different caller functions" in w for w in res.unresolved_aspects)


def test_unresolved_when_caller_symbol_not_found():
    """When caller symbol cannot be found in AST, returns clean unresolved result."""
    code = "def other_func(): pass"
    res = python_ast_control_flow.analyze_transition(
        source_code=code,
        caller_file="test.py",
        caller_symbol="nonexistent_function",
        call_a_line=1,
        call_b_line=2,
    )
    assert res.same_execution_path_verified is False
    assert any("could not be located in AST" in w for w in res.unresolved_aspects)


# ===========================================================================
# 4. Call-Site Identity & Graph-Edge Separation Tests
# ===========================================================================

def test_call_site_id_distinguishes_multiple_calls_to_same_callee():
    """
    When a caller invokes the same callee multiple times, call_graph_edge_id
    is identical, but call_site_id is distinct due to line/col coordinates.
    """
    edge_id_1 = CallSiteEvidence.format_edge_id(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/types.py",
        callee_symbol="ParamType.convert",
    )
    edge_id_2 = CallSiteEvidence.format_edge_id(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/types.py",
        callee_symbol="ParamType.convert",
    )
    # The graph edge ID is identical
    assert edge_id_1 == edge_id_2 == "src/click/core.py:Command.invoke->src/click/types.py:ParamType.convert"

    site_id_1 = CallSiteEvidence.format_site_id(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/types.py",
        callee_symbol="ParamType.convert",
        line=130,
        col=8,
    )
    site_id_2 = CallSiteEvidence.format_site_id(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/types.py",
        callee_symbol="ParamType.convert",
        line=145,
        col=12,
    )
    # The physical call-site IDs are distinct!
    assert site_id_1 != site_id_2
    assert site_id_1.endswith("@130:8")
    assert site_id_2.endswith("@145:12")


def test_duplicate_symbol_names_across_different_files_disambiguated():
    """Identical function names in different files produce distinct edge and site IDs."""
    edge_1 = CallSiteEvidence.format_edge_id(
        caller_file="pkg/alpha.py",
        caller_symbol="run",
        callee_file="pkg/parser.py",
        callee_symbol="parse",
    )
    edge_2 = CallSiteEvidence.format_edge_id(
        caller_file="pkg/beta.py",
        caller_symbol="run",
        callee_file="pkg/parser.py",
        callee_symbol="parse",
    )
    assert edge_1 != edge_2
    assert "pkg/alpha.py:run" in edge_1
    assert "pkg/beta.py:run" in edge_2


def test_build_and_verify_call_site_edge_and_location_independence():
    """
    Verifies that a valid CallGraphEdge does NOT verify the physical site location,
    and a valid location in ParsedFile does NOT verify the directional graph edge.
    """
    mock_parsed_file = ParsedFile(
        file_path="src/click/core.py",
        language="Python",
        status="success",
        total_lines=200,
        function_calls=[
            FunctionCallInfo(
                call_name="convert",
                enclosing_scope="Command.invoke",
                file_path="src/click/core.py",
                line_number=130,
            )
        ],
    )

    mock_edges = [
        CallGraphEdge(
            caller="src/click/core.py:Command.invoke",
            callee="src/click/types.py:ParamType.convert",
            call_name="convert",
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(
                evidence_type="function_call",
                file_path="src/click/core.py",
                line_number=130,
            ),
        )
    ]

    # Scenario 1: Both edge and location are valid
    evidence_both = build_and_verify_call_site(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/types.py",
        callee_symbol="ParamType.convert",
        call_name="convert",
        call_site_line=130,
        parsed_file=mock_parsed_file,
        call_graph_edges=mock_edges,
    )
    assert evidence_both.is_edge_verified is True
    assert evidence_both.is_site_location_verified is True

    # Scenario 2: Valid graph edge, but INVALID call_site_line (e.g. line 999)
    evidence_bad_line = build_and_verify_call_site(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/types.py",
        callee_symbol="ParamType.convert",
        call_name="convert",
        call_site_line=999,  # Line not in parsed_file
        parsed_file=mock_parsed_file,
        call_graph_edges=mock_edges,
    )
    assert evidence_bad_line.is_edge_verified is True
    assert evidence_bad_line.is_site_location_verified is False  # Must not blindly pass

    # Scenario 3: Valid call_site_line, but NO matching graph edge
    evidence_bad_edge = build_and_verify_call_site(
        caller_file="src/click/core.py",
        caller_symbol="Command.invoke",
        callee_file="src/click/unrelated.py",
        callee_symbol="Unrelated.foo",
        call_name="convert",
        call_site_line=130,  # Line exists
        parsed_file=mock_parsed_file,
        call_graph_edges=mock_edges,  # But edge does not exist
    )
    assert evidence_bad_edge.is_edge_verified is False  # Edge not found
    assert evidence_bad_edge.is_site_location_verified is True
