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


# ===========================================================================
# 5. Candidate Discovery Tests
# ===========================================================================

def test_candidate_discovery_high_confidence_entry_point():
    """Seeds candidate workflow from high-confidence EntryPointCandidate and traces CallGraph."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    pf_core = ParsedFile(
        file_path="src/click/core.py",
        language="Python",
        status="success",
        total_lines=200,
        functions=[
            FunctionInfo(
                name="main",
                file_path="src/click/core.py",
                location=SourceLocation(file_path="src/click/core.py", start_line=10, end_line=50, start_column=0, end_column=20),
            )
        ],
    )
    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="pallets/click", owner="pallets", repository_url="https://github.com/pallets/click", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 2},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=1, supported_languages=["Python"], files=[pf_core]),
        architecture=ArchitectureSummary(
            dependency_graph={"nodes": [], "edges": []},
            call_graph=CallGraph(
                edges=[
                    CallGraphEdge(
                        caller="src/click/core.py:main",
                        callee="src/click/parser.py:split_arg_string",
                        call_name="split_arg_string",
                        resolution_status="resolved_internal",
                        evidence=RelationshipEvidence(file_path="src/click/core.py", line_number=25, confidence="high", evidence_type="function_call"),
                    )
                ]
            ),
        ),
        entry_points=[
            EntryPointCandidate(
                file_path="src/click/core.py",
                entry_type="python_main_guard",
                symbol_or_command="main",
                confidence="high",
            )
        ],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    assert len(result.selected_ai_candidates) >= 1
    top_cand = result.selected_ai_candidates[0]
    assert top_cand.entry_file == "src/click/core.py"
    assert top_cand.entry_symbol == "main"
    assert len(top_cand.call_chain) == 1
    assert top_cand.call_chain[0].callee_symbol == "split_arg_string"
    assert "src/click/parser.py" in top_cand.participating_files


def test_candidate_discovery_library_repository():
    """Discovers library API workflows when no conventional application entry points exist."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        ImportantFileInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="sindresorhus/is", owner="sindresorhus", repository_url="https://github.com/sindresorhus/is", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 2},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=1, supported_languages=["TypeScript"], files=[]),
        architecture=ArchitectureSummary(
            dependency_graph={"nodes": [], "edges": []},
            call_graph=CallGraph(
                edges=[
                    CallGraphEdge(
                        caller="source/index.ts:is",
                        callee="source/predicates.ts:isObject",
                        call_name="isObject",
                        resolution_status="resolved_internal",
                        evidence=RelationshipEvidence(file_path="source/index.ts", line_number=15, confidence="high", evidence_type="function_call"),
                    )
                ]
            ),
        ),
        entry_points=[],  # No entry points!
        important_files=[
            ImportantFileInfo(relative_path="source/index.ts", category="core", score=9.5, reason="Main entry", evidence="", confidence="high")
        ],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    assert len(result.selected_ai_candidates) >= 1
    lib_cand = result.selected_ai_candidates[0]
    assert lib_cand.is_library_flow is True
    assert lib_cand.entry_file == "source/index.ts"


def test_candidate_discovery_depth_limit_and_recursion_protection():
    """Traversal stops at MAX_DEPTH (4) and detects recursive cycles without infinite loops."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    # Cyclic call graph: A -> B -> C -> A
    edges = [
        CallGraphEdge(caller="main.py:node_a", callee="main.py:node_b", call_name="node_b", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="main.py", line_number=10, evidence_type="function_call")),
        CallGraphEdge(caller="main.py:node_b", callee="main.py:node_c", call_name="node_c", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="main.py", line_number=20, evidence_type="function_call")),
        CallGraphEdge(caller="main.py:node_c", callee="main.py:node_d", call_name="node_d", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="main.py", line_number=30, evidence_type="function_call")),
        CallGraphEdge(caller="main.py:node_d", callee="main.py:node_e", call_name="node_e", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="main.py", line_number=40, evidence_type="function_call")),
        CallGraphEdge(caller="main.py:node_e", callee="main.py:node_a", call_name="node_a", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="main.py", line_number=50, evidence_type="function_call")),  # Cycle!
    ]

    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/cycles", owner="test", repository_url="https://github.com/test/cycles", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 1},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=1, supported_languages=["Python"], files=[ParsedFile(file_path="main.py", language="Python", status="success", total_lines=100, functions=[FunctionInfo(name="node_a", file_path="main.py", location=SourceLocation(file_path="main.py", start_line=1, end_line=15, start_column=0, end_column=0))])]),
        architecture=ArchitectureSummary(dependency_graph={"nodes": [], "edges": []}, call_graph=CallGraph(edges=edges)),
        entry_points=[EntryPointCandidate(file_path="main.py", entry_type="python_main_guard", symbol_or_command="node_a", confidence="high")],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    assert len(result.selected_ai_candidates) == 1
    cand = result.selected_ai_candidates[0]
    # Chain depth must not exceed 5 nodes
    assert len(cand.call_chain) <= 5


def test_candidate_discovery_limits_and_omission_reporting():
    """Enforces max 2 AI candidates, max 2 structural chains, and reports omitted workflows."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    # Create 6 distinct entry points
    entry_points = []
    edges = []
    parsed_files = []
    for i in range(1, 7):
        fn_name = f"cli_command_{i}"
        entry_points.append(EntryPointCandidate(file_path=f"cmd_{i}.py", entry_type="python_main_guard", symbol_or_command=fn_name, confidence="high"))
        edges.append(CallGraphEdge(caller=f"cmd_{i}.py:{fn_name}", callee=f"service.py:exec_{i}", call_name=f"exec_{i}", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path=f"cmd_{i}.py", line_number=10, evidence_type="function_call")))
        parsed_files.append(
            ParsedFile(
                file_path=f"cmd_{i}.py",
                language="Python",
                status="success",
                total_lines=50,
                functions=[FunctionInfo(name=fn_name, file_path=f"cmd_{i}.py", location=SourceLocation(file_path=f"cmd_{i}.py", start_line=1, end_line=20, start_column=0, end_column=0))],
            )
        )

    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/many", owner="test", repository_url="https://github.com/test/many", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 6},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=6, supported_languages=["Python"], files=parsed_files),
        architecture=ArchitectureSummary(dependency_graph={"nodes": [], "edges": []}, call_graph=CallGraph(edges=edges)),
        entry_points=entry_points,
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    assert len(result.selected_ai_candidates) == 2  # Max 2 AI
    assert len(result.structural_call_chain_candidates) == 2  # Max 2 structural
    assert len(result.omitted_candidate_workflows) == 2  # 6 total - 4 = 2 omitted
    assert all("omitted due to workflow budget limit" in o for o in result.omitted_candidate_workflows)


def test_candidate_discovery_deduplication_preserves_distinct_workflows():
    """Two distinct workflows calling the same common utility function are NOT merged."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    edges = [
        # Workflow 1: auth -> helper
        CallGraphEdge(caller="auth.py:login", callee="util.py:log_action", call_name="log_action", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="auth.py", line_number=10, evidence_type="function_call")),
        # Workflow 2: payments -> helper
        CallGraphEdge(caller="pay.py:checkout", callee="util.py:log_action", call_name="log_action", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="pay.py", line_number=10, evidence_type="function_call")),
    ]
    pfs = [
        ParsedFile(file_path="auth.py", language="Python", status="success", total_lines=50, functions=[FunctionInfo(name="login", file_path="auth.py", location=SourceLocation(file_path="auth.py", start_line=1, end_line=20, start_column=0, end_column=0))]),
        ParsedFile(file_path="pay.py", language="Python", status="success", total_lines=50, functions=[FunctionInfo(name="checkout", file_path="pay.py", location=SourceLocation(file_path="pay.py", start_line=1, end_line=20, start_column=0, end_column=0))]),
    ]
    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/dedup", owner="test", repository_url="https://github.com/test/dedup", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 2},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=2, supported_languages=["Python"], files=pfs),
        architecture=ArchitectureSummary(dependency_graph={"nodes": [], "edges": []}, call_graph=CallGraph(edges=edges)),
        entry_points=[
            EntryPointCandidate(file_path="auth.py", entry_type="python_main_guard", symbol_or_command="login", confidence="high"),
            EntryPointCandidate(file_path="pay.py", entry_type="python_main_guard", symbol_or_command="checkout", confidence="high"),
        ],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    # Both distinct workflows must be preserved!
    assert len(result.selected_ai_candidates) == 2
    entry_symbols = {c.entry_symbol for c in result.selected_ai_candidates}
    assert "login" in entry_symbols
    assert "checkout" in entry_symbols


# ===========================================================================
# 6. Snippet Extraction Tests
# ===========================================================================

def test_snippet_extractor_complete_function_boundaries():
    """Extracts complete function snippet within the 25-line limit with line numbers."""
    from app.models.schemas import FunctionInfo, ParsedFile, SourceLocation
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    func = FunctionInfo(
        name="calculate_tax",
        file_path="billing.py",
        location=SourceLocation(file_path="billing.py", start_line=10, end_line=15, start_column=0, end_column=0),
        snippet="def calculate_tax(amount):\n    \"\"\"Calculates VAT.\"\"\"\n    rate = 0.2\n    return amount * rate",
    )
    pf = ParsedFile(file_path="billing.py", language="Python", status="success", total_lines=50, functions=[func])

    snippet = workflow_snippet_extractor.extract_symbol_snippet(pf, "calculate_tax")
    assert snippet.is_complete is True
    assert snippet.line_start == 10
    assert snippet.line_end == 15
    assert snippet.docstring == "Calculates VAT."
    assert "L10: def calculate_tax(amount):" in snippet.formatted_code
    assert "L13:     return amount * rate" in snippet.formatted_code


def test_snippet_extractor_oversized_symbol_truncation():
    """Functions exceeding 25 lines retain signature and omit body to preserve boundary clarity."""
    from app.models.schemas import FunctionInfo, ParsedFile, SourceLocation
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    oversized_lines = ["def process_huge_batch():"] + [f"    step_{i}()" for i in range(1, 40)]
    func = FunctionInfo(
        name="process_huge_batch",
        file_path="batch.py",
        location=SourceLocation(file_path="batch.py", start_line=1, end_line=41, start_column=0, end_column=0),
        snippet="\n".join(oversized_lines),
    )
    pf = ParsedFile(file_path="batch.py", language="Python", status="success", total_lines=100, functions=[func])

    snippet = workflow_snippet_extractor.extract_symbol_snippet(pf, "process_huge_batch")
    assert snippet.is_complete is False
    assert "exceeds 25-line limit" in snippet.exclusion_reason
    assert "L1: def process_huge_batch():" in snippet.formatted_code


def test_snippet_extractor_sensitive_file_exclusion():
    """Secrets, .env, and credential files are strictly excluded from extraction."""
    from app.models.schemas import FunctionInfo, ParsedFile, SourceLocation
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    pf_env = ParsedFile(
        file_path=".env",
        language="Configuration",
        status="success",
        total_lines=10,
        functions=[FunctionInfo(name="get_key", file_path=".env", location=SourceLocation(file_path=".env", start_line=1, end_line=2, start_column=0, end_column=0))],
    )
    snippet_env = workflow_snippet_extractor.extract_symbol_snippet(pf_env, "get_key")
    assert snippet_env.is_complete is False
    assert "<SNIPPET REDACTED: SENSITIVE_CONFIGURATION_FILE>" in snippet_env.formatted_code

    pf_secret = ParsedFile(
        file_path="config/secret_keys.py",
        language="Python",
        status="success",
        total_lines=10,
        functions=[FunctionInfo(name="load_key", file_path="config/secret_keys.py", location=SourceLocation(file_path="config/secret_keys.py", start_line=1, end_line=2, start_column=0, end_column=0))],
    )
    snippet_secret = workflow_snippet_extractor.extract_symbol_snippet(pf_secret, "load_key")
    assert snippet_secret.is_complete is False
    assert "matches sensitive credential/secret file pattern" in snippet_secret.exclusion_reason


def test_snippet_extractor_missing_file_or_symbol():
    """Missing parsed files or symbols return clean unresolved snippet without crashing."""
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    res_none = workflow_snippet_extractor.extract_symbol_snippet(None, "foo")
    assert res_none.is_complete is False
    assert "PARSED_FILE_UNAVAILABLE" in res_none.formatted_code


# ===========================================================================
# 7. Operation-Based Storage & External API Tests
# ===========================================================================

def test_storage_verification_sql_select_read():
    """SQL SELECT queries are classified as read-only operations."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = """
import sqlite3

def fetch_user(cursor, user_id):
    cursor.execute("SELECT id, name FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()
"""
    res = operation_verifier.verify_storage_in_code(code, "repo.py")
    assert res.storage_operation_verified is True
    assert res.storage_operation_type == "read"
    assert "read-only" in res.observed_operation


def test_storage_verification_sql_insert_write():
    """SQL INSERT queries are classified as write operations."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = """
import sqlite3

def create_audit_log(cursor, msg):
    cursor.execute("INSERT INTO logs (message) VALUES (?)", (msg,))
"""
    res = operation_verifier.verify_storage_in_code(code, "repo.py")
    assert res.storage_operation_verified is True
    assert res.storage_operation_type == "write"
    assert "SQL write" in res.observed_operation


def test_storage_verification_open_modes():
    """Distinguishes open(..., 'w') write from open(..., 'r') read."""
    from app.services.ai.workflow_understanding import operation_verifier

    code_write = """
def save_output(data):
    with open("results.json", "w") as f:
        f.write(data)
"""
    res_w = operation_verifier.verify_storage_in_code(code_write, "io.py")
    assert res_w.storage_operation_verified is True
    assert res_w.storage_operation_type == "write"

    code_read = """
def load_config():
    with open("config.json", "r") as f:
        return f.read()
"""
    res_r = operation_verifier.verify_storage_in_code(code_read, "io.py")
    assert res_r.storage_operation_verified is True
    assert res_r.storage_operation_type == "read"


def test_storage_verification_bare_commit_not_a_write():
    """A bare .commit() without preceding write evidence does not establish a write operation."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = """
from sqlalchemy.orm import Session

def just_commit(session: Session):
    # Only calls commit without any preceding add, insert, or write
    session.commit()
"""
    res = operation_verifier.verify_storage_in_code(code, "db.py")
    assert res.storage_operation_verified is False
    assert res.persistence_status == "storage_library_imported_no_write_observed"
    assert "Bare .commit() observed without preceding" in res.persistence_detail


def test_storage_verification_orm_operations():
    """ORM .add() establishes write; .delete() establishes delete."""
    from app.services.ai.workflow_understanding import operation_verifier

    code_add = """
from sqlalchemy.orm import Session

def add_user(session: Session, user):
    session.add(user)
    session.commit()
"""
    res_add = operation_verifier.verify_storage_in_code(code_add, "orm.py")
    assert res_add.storage_operation_verified is True
    assert res_add.storage_operation_type == "write"

    code_del = """
from sqlalchemy.orm import Session

def remove_user(session: Session, user):
    session.delete(user)
    session.commit()
"""
    res_del = operation_verifier.verify_storage_in_code(code_del, "orm.py")
    assert res_del.storage_operation_verified is True
    assert res_del.storage_operation_type == "delete"


def test_external_api_verification_dict_get_rejected():
    """Ordinary dict.get() lookups are strictly rejected from external API classification."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = """
def lookup_config(d, key):
    val = d.get(key)
    params = {}
    return params.get("default")
"""
    res = operation_verifier.verify_external_api_in_code(code, "util.py")
    assert res.external_api_operation_verified is False
    assert res.external_api_status == "no_external_api_operation_detected"


def test_external_api_verification_requests_get_verified():
    """requests.get() is verified with receiver evidence."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = """
import requests

def fetch_weather(city):
    resp = requests.get("https://api.weather.com/v1?city=" + city)
    return resp.json()
"""
    res = operation_verifier.verify_external_api_in_code(code, "weather.py")
    assert res.external_api_operation_verified is True
    assert res.external_api_operation_type == "http_request"
    assert res.external_api_status == "external_api_operation_verified"
    assert "requests.get()" in res.observed_operation


def test_operation_verification_non_python_conservative():
    """Non-Python languages receive conservative unresolved status."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = "function fetchUser() { return db.query('SELECT 1'); }"
    res_storage = operation_verifier.verify_storage_in_code(code, "db.js", language="JavaScript")
    assert res_storage.storage_operation_verified is False
    assert "deep AST storage verification is supported for Python in Milestone 3.4" in res_storage.persistence_detail

    res_api = operation_verifier.verify_external_api_in_code(code, "api.go", language="Go")
    assert res_api.external_api_operation_verified is False
    assert "deep external API verification is supported for Python in Milestone 3.4" in res_api.external_api_detail


# ===========================================================================
# 8. Milestone 3.4 Phase 2 Audit Tests
# ===========================================================================

def test_candidate_discovery_high_branching_work_limits():
    """Synthetic high-branching graph respects branching, visited node, and edge limits without explosion."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    # Create root seed with 10 outgoing edges, each pointing to 10 more edges
    edges = []
    parsed_files = [
        ParsedFile(
            file_path="root.py",
            language="Python",
            status="success",
            total_lines=100,
            functions=[FunctionInfo(name="entry", file_path="root.py", location=SourceLocation(file_path="root.py", start_line=1, end_line=10, start_column=0, end_column=0))],
        )
    ]

    for i in range(10):
        edges.append(
            CallGraphEdge(
                caller="root.py:entry",
                callee=f"branch_{i}.py:step_{i}",
                call_name=f"step_{i}",
                resolution_status="resolved_internal",
                evidence=RelationshipEvidence(file_path="root.py", line_number=10 + i, evidence_type="function_call"),
            )
        )
        for j in range(10):
            edges.append(
                CallGraphEdge(
                    caller=f"branch_{i}.py:step_{i}",
                    callee=f"leaf_{i}_{j}.py:sub_{j}",
                    call_name=f"sub_{j}",
                    resolution_status="resolved_internal",
                    evidence=RelationshipEvidence(file_path=f"branch_{i}.py", line_number=5 + j, evidence_type="function_call"),
                )
            )

    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/highbranch", owner="test", repository_url="https://github.com/test/highbranch", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 20},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=1, supported_languages=["Python"], files=parsed_files),
        architecture=ArchitectureSummary(dependency_graph={"nodes": [], "edges": []}, call_graph=CallGraph(edges=edges)),
        entry_points=[EntryPointCandidate(file_path="root.py", entry_type="python_main_guard", symbol_or_command="entry", confidence="high")],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    assert len(result.selected_ai_candidates) == 1
    cand = result.selected_ai_candidates[0]
    # Call chain must not explode; limited to max depth and max branches per step
    assert len(cand.call_chain) <= 6
    assert len(cand.participating_files) <= 10


def test_candidate_ranking_all_five_criteria_affect_score():
    """All 5 approved criteria (confidence, depth, call quality, file diversity, evidence completeness) affect score."""
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    # Rich multi-file workflow with verified lines and internal calls
    rich_edges = [
        CallGraphEdge(caller="main.py:run", callee="service.py:process", call_name="process", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="main.py", line_number=10, evidence_type="function_call")),
        CallGraphEdge(caller="service.py:process", callee="db.py:save", call_name="save", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="service.py", line_number=25, evidence_type="function_call")),
        CallGraphEdge(caller="db.py:save", callee="audit.py:log", call_name="log", resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path="db.py", line_number=40, evidence_type="function_call")),
    ]

    # Shallow single-file workflow with external unresolved call and no line numbers
    shallow_edges = [
        CallGraphEdge(caller="util.py:helper", callee="external_lib:foo", call_name="foo", resolution_status="unresolved_external", evidence=RelationshipEvidence(file_path="util.py", line_number=None, evidence_type="function_call")),
    ]

    pfs = [
        ParsedFile(file_path="main.py", language="Python", status="success", total_lines=50, functions=[FunctionInfo(name="run", file_path="main.py", location=SourceLocation(file_path="main.py", start_line=1, end_line=20, start_column=0, end_column=0))]),
        ParsedFile(file_path="util.py", language="Python", status="success", total_lines=50, functions=[FunctionInfo(name="helper", file_path="util.py", location=SourceLocation(file_path="util.py", start_line=1, end_line=20, start_column=0, end_column=0))]),
    ]

    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/ranking", owner="test", repository_url="https://github.com/test/ranking", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 1, "total_files": 2},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=2, supported_languages=["Python"], files=pfs),
        architecture=ArchitectureSummary(dependency_graph={"nodes": [], "edges": []}, call_graph=CallGraph(edges=rich_edges + shallow_edges)),
        entry_points=[
            EntryPointCandidate(file_path="main.py", entry_type="python_main_guard", symbol_or_command="run", confidence="high"),
            EntryPointCandidate(file_path="util.py", entry_type="python_main_guard", symbol_or_command="helper", confidence="medium"),
        ],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    assert len(result.selected_ai_candidates) == 2
    rich_cand = [c for c in result.selected_ai_candidates if c.entry_symbol == "run"][0]
    shallow_cand = [c for c in result.selected_ai_candidates if c.entry_symbol == "helper"][0]

    # Rich candidate must significantly outscore shallow candidate
    assert rich_cand.score > shallow_cand.score
    # Rich candidate has 4 participating files, 3 hops, 100% internal calls, 100% line evidence
    assert rich_cand.score >= 15.0


def test_candidate_deduplication_preserves_distinct_leaf_operations():
    """Candidates sharing the same entry point but with diverging terminal leaves are preserved."""
    from app.services.ai.workflow_understanding.candidate_discoverer import (
        CandidateCallNode,
        DiscoveredWorkflowCandidate,
        workflow_candidate_discoverer,
    )

    # Cand 1: main -> parse -> login -> save_session (terminal = save_session)
    cand1 = DiscoveredWorkflowCandidate(
        candidate_id="cand-1",
        name="Save Session Workflow",
        category="user_request",
        entry_symbol="run",
        entry_file="cli.py",
        trigger="CLI run",
        call_chain=[
            CandidateCallNode(caller_file="cli.py", caller_symbol="run", callee_file="parser.py", callee_symbol="parse", call_name="parse", call_site_line=10, call_graph_edge_id="e1", call_site_id="s1"),
            CandidateCallNode(caller_file="parser.py", caller_symbol="parse", callee_file="auth.py", callee_symbol="login", call_name="login", call_site_line=20, call_graph_edge_id="e2", call_site_id="s2"),
            CandidateCallNode(caller_file="auth.py", caller_symbol="login", callee_file="db.py", callee_symbol="save_session", call_name="save_session", call_site_line=30, call_graph_edge_id="e3", call_site_id="s3"),
        ],
        score=10.0,
    )

    # Cand 2: main -> parse -> login -> export_metrics (terminal = export_metrics)
    cand2 = DiscoveredWorkflowCandidate(
        candidate_id="cand-2",
        name="Export Metrics Workflow",
        category="user_request",
        entry_symbol="run",
        entry_file="cli.py",
        trigger="CLI run",
        call_chain=[
            CandidateCallNode(caller_file="cli.py", caller_symbol="run", callee_file="parser.py", callee_symbol="parse", call_name="parse", call_site_line=10, call_graph_edge_id="e1", call_site_id="s1"),
            CandidateCallNode(caller_file="parser.py", caller_symbol="parse", callee_file="auth.py", callee_symbol="login", call_name="login", call_site_line=20, call_graph_edge_id="e2", call_site_id="s2"),
            CandidateCallNode(caller_file="auth.py", caller_symbol="login", callee_file="report.py", callee_symbol="export_metrics", call_name="export_metrics", call_site_line=35, call_graph_edge_id="e4", call_site_id="s4"),
        ],
        score=9.5,
    )

    # Even though edge overlap is 2/3 (67%), let's test that diverging terminal leaves are NEVER merged
    deduped, reasons = workflow_candidate_discoverer._deduplicate_candidates([cand1, cand2])
    assert len(deduped) == 2
    assert {c.candidate_id for c in deduped} == {"cand-1", "cand-2"}

    # Cand 3: Identical terminal operation as cand 1 (save_session) with >=70% overlap
    cand3 = DiscoveredWorkflowCandidate(
        candidate_id="cand-3",
        name="Duplicate Save Session",
        category="user_request",
        entry_symbol="run",
        entry_file="cli.py",
        trigger="CLI run",
        call_chain=[
            CandidateCallNode(caller_file="cli.py", caller_symbol="run", callee_file="parser.py", callee_symbol="parse", call_name="parse", call_site_line=10, call_graph_edge_id="e1", call_site_id="s1"),
            CandidateCallNode(caller_file="parser.py", caller_symbol="parse", callee_file="auth.py", callee_symbol="login", call_name="login", call_site_line=20, call_graph_edge_id="e2", call_site_id="s2"),
            CandidateCallNode(caller_file="auth.py", caller_symbol="login", callee_file="db.py", callee_symbol="save_session", call_name="save_session", call_site_line=30, call_graph_edge_id="e3", call_site_id="s3"),
        ],
        score=8.0,
    )
    deduped2, reasons2 = workflow_candidate_discoverer._deduplicate_candidates([cand1, cand3])
    assert len(deduped2) == 1
    assert deduped2[0].candidate_id == "cand-1"
    assert len(reasons2) == 1
    assert "deduplicated into 'Save Session Workflow'" in reasons2[0]


def test_storage_verification_rejects_misleading_receiver_without_import():
    """Misleading receiver names (cursor, db, session) without DB library import are rejected."""
    from app.services.ai.workflow_understanding import operation_verifier

    code = """
def process_data(cursor, db, session):
    cursor.execute("SELECT * FROM users")
    session.add(item)
    session.commit()
"""
    res = operation_verifier.verify_storage_in_code(code, "handler.py")
    assert res.storage_operation_verified is False
    assert res.storage_library_detected is False
    assert res.persistence_status == "no_storage_operation_detected"


def test_storage_verification_dynamic_sql_unresolved():
    """Dynamic SQL query expressions result in unresolved_dynamic_sql status."""
    from app.services.ai.workflow_understanding import operation_verifier

    code_var = """
import sqlite3

def run_query(cursor, query_str):
    cursor.execute(query_str)
"""
    res_var = operation_verifier.verify_storage_in_code(code_var, "db.py")
    assert res_var.storage_operation_verified is False
    assert res_var.storage_library_detected is True
    assert res_var.storage_operation_type == "unresolved"
    assert res_var.persistence_status == "unresolved_dynamic_sql"
    assert "Dynamic or unresolved SQL query" in res_var.persistence_detail


def test_storage_verification_filesystem_extended_operations():
    """Path.write_text, Path.read_text, Path.unlink, and os.remove are verified."""
    from app.services.ai.workflow_understanding import operation_verifier

    code_write = """
from pathlib import Path

def save_file(content):
    p = Path("log.txt")
    p.write_text(content)
"""
    res_w = operation_verifier.verify_storage_in_code(code_write, "fs.py")
    assert res_w.storage_operation_verified is True
    assert res_w.storage_operation_type == "write"

    code_read = """
from pathlib import Path

def read_file():
    p = Path("log.txt")
    return p.read_text()
"""
    res_r = operation_verifier.verify_storage_in_code(code_read, "fs.py")
    assert res_r.storage_operation_verified is True
    assert res_r.storage_operation_type == "read"

    code_del = """
import os

def cleanup(path):
    os.remove(path)
"""
    res_d = operation_verifier.verify_storage_in_code(code_del, "fs.py")
    assert res_d.storage_operation_verified is True
    assert res_d.storage_operation_type == "delete"


def test_external_api_client_identity_verification():
    """External API verification enforces HTTP client identity and uses verified terminology."""
    from app.services.ai.workflow_understanding import operation_verifier

    # 1. Arbitrary object calling .get() without HTTP import must be rejected
    code_arbitrary = """
def fetch_something(client):
    return client.get("https://api.example.com/items")
"""
    res_arb = operation_verifier.verify_external_api_in_code(code_arbitrary, "client.py")
    assert res_arb.external_api_operation_verified is False
    assert res_arb.external_api_status == "no_external_api_operation_detected"

    # 2. Aliased import: import requests as req -> req.get()
    code_alias = """
import requests as req

def fetch_data():
    return req.get("https://api.example.com/data")
"""
    res_alias = operation_verifier.verify_external_api_in_code(code_alias, "client.py")
    assert res_alias.external_api_operation_verified is True
    assert res_alias.external_api_operation_type == "http_request"
    assert "statically identified outbound HTTP operation" in res_alias.observed_operation

    # 3. httpx client with HTTP identity
    code_httpx = """
import httpx

def post_event(payload):
    client = httpx.Client()
    return client.post("https://api.example.com/events", json=payload)
"""
    res_httpx = operation_verifier.verify_external_api_in_code(code_httpx, "client.py")
    assert res_httpx.external_api_operation_verified is True
    assert "statically identified outbound HTTP operation" in res_httpx.external_api_detail


def test_snippet_extraction_path_traversal_rejection():
    """Path traversal sequences (..) attempting directory escape are blocked."""
    from app.models.schemas import FunctionInfo, ParsedFile, SourceLocation
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    pf_traversal = ParsedFile(
        file_path="../../etc/passwd",
        language="Python",
        status="success",
        total_lines=10,
        functions=[FunctionInfo(name="leak", file_path="../../etc/passwd", location=SourceLocation(file_path="../../etc/passwd", start_line=1, end_line=5, start_column=0, end_column=0))],
    )

    snippet = workflow_snippet_extractor.extract_symbol_snippet(pf_traversal, "leak")
    assert snippet.is_complete is False
    assert "<SNIPPET REDACTED: PATH_TRAVERSAL_DETECTED>" in snippet.formatted_code
    assert "path traversal" in snippet.exclusion_reason.lower()


def test_snippet_extraction_secret_redaction():
    """Embedded API keys, tokens, and credentials are redacted without leaking secret values."""
    from app.models.schemas import FunctionInfo, ParsedFile, SourceLocation
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    # Build function snippet with hardcoded secrets
    code_with_secrets = (
        "def setup_client():\n"
        "    api_key = \"AIzaSyD-1234567890abcdefghijklmnopqr\"\n"
        "    openai_token = \"sk-proj-abcdef1234567890ghijklmnopqr\"\n"
        "    gh_token = \"ghp_1234567890abcdefghijklmnopqrstuv\"\n"
        "    aws_key = \"AKIAIOSFODNN7EXAMPLE\"\n"
        "    headers = {\"Authorization\": \"Bearer my_auth_secret_token_123456789\"}\n"
        "    password = \"my_super_secret_password_123\"\n"
        "    return api_key\n"
    )

    func = FunctionInfo(
        name="setup_client",
        file_path="client.py",
        location=SourceLocation(file_path="client.py", start_line=1, end_line=8, start_column=0, end_column=0),
        snippet=code_with_secrets,
    )
    pf = ParsedFile(file_path="client.py", language="Python", status="success", total_lines=20, functions=[func])

    snippet = workflow_snippet_extractor.extract_symbol_snippet(pf, "setup_client")
    assert snippet.is_complete is True

    # Confirm raw secret values never appear in formatted snippet
    assert "AIzaSyD" not in snippet.formatted_code
    assert "sk-proj-" not in snippet.formatted_code
    assert "ghp_" not in snippet.formatted_code
    assert "AKIAIOSFODNN7EXAMPLE" not in snippet.formatted_code
    assert "my_auth_secret_token" not in snippet.formatted_code
    assert "my_super_secret_password" not in snippet.formatted_code

    # Confirm redaction placeholders are present
    assert "<REDACTED_SECRET>" in snippet.formatted_code
    assert "Bearer <REDACTED_SECRET>" in snippet.formatted_code


# ===========================================================================
# 9. Narrowly Scoped Verification Tests
# ===========================================================================

def test_storage_verification_misleading_imports_and_unrelated_objects():
    """Importing SQLAlchemy/sqlite3 elsewhere does NOT validate arbitrary objects or runners."""
    from app.services.ai.workflow_understanding import operation_verifier

    # 1. SQLAlchemy imported, but objects are unrelated collections/forms
    code_orm_misleading = """
from sqlalchemy.orm import Session
import sqlalchemy

def handle_request(form, items, cart):
    items.add("item_1")
    form.save()
    cart.delete("item_2")
"""
    res_orm = operation_verifier.verify_storage_in_code(code_orm_misleading, "views.py")
    assert res_orm.storage_operation_verified is False
    assert res_orm.persistence_status == "no_storage_operation_detected"

    # 2. sqlite3 imported, but runner is an arbitrary command executor
    code_db_misleading = """
import sqlite3

def execute_command(runner, task):
    runner.execute("SELECT * FROM tasks WHERE id = 1")
"""
    res_db = operation_verifier.verify_storage_in_code(code_db_misleading, "runner.py")
    assert res_db.storage_operation_verified is False
    assert res_db.persistence_status == "no_storage_operation_detected"


def test_storage_verification_valid_recognized_db_orm_patterns():
    """Recognized DB connections/cursors and ORM constructions/types are verified."""
    from app.services.ai.workflow_understanding import operation_verifier

    # 1. Assignment from connect and cursor
    code_cursor_construct = """
import sqlite3

def run_query():
    conn = sqlite3.connect("app.db")
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM users")
    return cur.fetchall()
"""
    res_cur = operation_verifier.verify_storage_in_code(code_cursor_construct, "db.py")
    assert res_cur.storage_operation_verified is True
    assert res_cur.storage_operation_type == "read"

    # 2. Typed parameter with sqlite3.Cursor
    code_typed_cur = """
import sqlite3

def fetch_record(cur: sqlite3.Cursor, record_id: int):
    cur.execute("SELECT * FROM records WHERE id = ?", (record_id,))
    return cur.fetchone()
"""
    res_typed = operation_verifier.verify_storage_in_code(code_typed_cur, "db.py")
    assert res_typed.storage_operation_verified is True
    assert res_typed.storage_operation_type == "read"

    # 3. Chained db.session with Flask-SQLAlchemy style
    code_chained_session = """
from sqlalchemy.orm import Session

def create_item(db, item):
    db.session.add(item)
    db.session.commit()
"""
    res_chained = operation_verifier.verify_storage_in_code(code_chained_session, "service.py")
    assert res_chained.storage_operation_verified is True
    assert res_chained.storage_operation_type == "write"

    # 4. Typed Session parameter
    code_typed_session = """
from sqlalchemy.orm import Session

def remove_item(session: Session, item):
    session.delete(item)
    session.commit()
"""
    res_session = operation_verifier.verify_storage_in_code(code_typed_session, "service.py")
    assert res_session.storage_operation_verified is True
    assert res_session.storage_operation_type == "delete"


def test_external_api_sdk_classification_and_arbitrary_rejection():
    """Separates explicit HTTP clients from third-party SDK calls and rejects arbitrary methods."""
    from app.services.ai.workflow_understanding import operation_verifier

    # 1. Explicit HTTP client (requests)
    code_http = """
import requests

def get_status():
    return requests.get("https://api.example.com/status")
"""
    res_http = operation_verifier.verify_external_api_in_code(code_http, "client.py")
    assert res_http.external_api_operation_verified is True
    assert res_http.external_api_operation_type == "http_request"
    assert "statically identified outbound HTTP operation" in res_http.observed_operation

    # 2. Third-party SDK (boto3)
    code_sdk_boto = """
import boto3

def upload_data(bucket, key, data):
    s3 = boto3.client('s3')
    return s3.put_object(Bucket=bucket, Key=key, Body=data)
"""
    res_boto = operation_verifier.verify_external_api_in_code(code_sdk_boto, "aws.py")
    assert res_boto.external_api_operation_verified is True
    assert res_boto.external_api_operation_type == "external_sdk_call"
    assert "statically identified external SDK operation" in res_boto.observed_operation
    # Must NOT claim direct HTTP request was established
    assert "HTTP" not in res_boto.observed_operation

    # 3. Third-party SDK (stripe)
    code_sdk_stripe = """
import stripe

def charge_customer(amount, token):
    return stripe.Charge.create(amount=amount, currency="usd", source=token)
"""
    res_stripe = operation_verifier.verify_external_api_in_code(code_sdk_stripe, "billing.py")
    assert res_stripe.external_api_operation_verified is True
    assert res_stripe.external_api_operation_type == "external_sdk_call"
    assert "statically identified external SDK operation" in res_stripe.observed_operation

    # 4. Arbitrary client without HTTP or SDK import
    code_arbitrary = """
def fetch_info(client):
    return client.get("https://example.com/api")
"""
    res_arb = operation_verifier.verify_external_api_in_code(code_arbitrary, "util.py")
    assert res_arb.external_api_operation_verified is False
    assert res_arb.external_api_status == "no_external_api_operation_detected"


def test_snippet_extraction_symlink_safe_repository_containment():
    """Symlinks resolving outside repository root are strictly blocked before content reading."""
    import os
    import tempfile
    from app.models.schemas import FunctionInfo, ParsedFile, SourceLocation
    from app.services.ai.workflow_understanding import workflow_snippet_extractor

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = os.path.join(tmpdir, "my_repo")
        secret_dir = os.path.join(tmpdir, "secret_outside")
        os.makedirs(repo_dir)
        os.makedirs(secret_dir)

        # Create sensitive file outside repo
        secret_file = os.path.join(secret_dir, "leak.py")
        secret_content = "SECRET_TOKEN_DO_NOT_LEAK = 'super_secret_payload_12345'\n"
        with open(secret_file, "w") as f:
            f.write(secret_content)

        # Create symlink inside repo pointing outside
        symlink_file = os.path.join(repo_dir, "symlink_leak.py")
        os.symlink(secret_file, symlink_file)

        pf = ParsedFile(
            file_path="symlink_leak.py",
            language="Python",
            status="success",
            total_lines=10,
            functions=[
                FunctionInfo(
                    name="leaked_func",
                    file_path="symlink_leak.py",
                    location=SourceLocation(file_path="symlink_leak.py", start_line=1, end_line=5, start_column=0, end_column=0),
                    snippet=secret_content,
                )
            ],
        )

        snippet = workflow_snippet_extractor.extract_symbol_snippet(
            parsed_file=pf,
            symbol_name="leaked_func",
            local_path=symlink_file,
            repo_root=repo_dir,
        )

        assert snippet.is_complete is False
        assert "<SNIPPET REDACTED: PATH_TRAVERSAL_DETECTED>" in snippet.formatted_code
        assert "resolves outside canonical repository root" in snippet.exclusion_reason
        # Confirm sensitive outside content is NEVER read or leaked
        assert "super_secret_payload" not in snippet.formatted_code


def test_candidate_discovery_budget_exhaustion_multi_tier_omissions():
    """Budget exhaustion in Tier 1 halts subsequent tiers and reports explicit omission reasons."""
    from app.models.schemas import (
        ArchitecturalComponent,
        ArchitectureSummary,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        EntryPointCandidate,
        FunctionInfo,
        ImportantFileInfo,
        ParsedFile,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )
    from app.services.ai.workflow_understanding import workflow_candidate_discoverer

    # Construct high-edge call graph for Tier 1 entry points (more than 500 edges)
    edges = []
    pfs = []
    entry_points = []

    # 100 entry points, each generating 6 edges (total 600 edges, exceeding the 500-edge budget)
    for i in range(100):
        fn_name = f"cli_{i}"
        file_name = f"cmd_{i}.py"
        entry_points.append(EntryPointCandidate(file_path=file_name, entry_type="python_main_guard", symbol_or_command=fn_name, confidence="high"))
        pfs.append(
            ParsedFile(
                file_path=file_name,
                language="Python",
                status="success",
                total_lines=50,
                functions=[FunctionInfo(name=fn_name, file_path=file_name, location=SourceLocation(file_path=file_name, start_line=1, end_line=10, start_column=0, end_column=0))],
            )
        )
        for d1 in range(2):
            n1 = f"step_{i}_{d1}"
            edges.append(CallGraphEdge(caller=f"{file_name}:{fn_name}", callee=f"s1_{i}.py:{n1}", call_name=n1, resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path=file_name, line_number=10, evidence_type="function_call")))
            for d2 in range(2):
                n2 = f"sub_{i}_{d1}_{d2}"
                edges.append(CallGraphEdge(caller=f"s1_{i}.py:{n1}", callee=f"s2_{i}.py:{n2}", call_name=n2, resolution_status="resolved_internal", evidence=RelationshipEvidence(file_path=f"s1_{i}.py", line_number=20, evidence_type="function_call")))

    # Tier 2 API components
    api_comp = ArchitecturalComponent(
        file_path="api/routes.py",
        category="api_route",
        confidence="high",
        evidence=["FastAPI router decorator"],
    )
    pfs.append(
        ParsedFile(
            file_path="api/routes.py",
            language="Python",
            status="success",
            total_lines=50,
            functions=[FunctionInfo(name="get_users", file_path="api/routes.py", location=SourceLocation(file_path="api/routes.py", start_line=1, end_line=10, start_column=0, end_column=0))],
        )
    )

    # Tier 3 library symbols
    important_files = [
        ImportantFileInfo(
            relative_path="lib/core.py",
            category="core_logic",
            score=10.0,
            reason="Core library file",
            evidence="High out-degree",
        )
    ]
    edges.append(
        CallGraphEdge(
            caller="lib/core.py:compute",
            callee="lib/math.py:add",
            call_name="add",
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="lib/core.py", line_number=5, evidence_type="function_call"),
        )
    )

    mock_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/budget", owner="test", repository_url="https://github.com/test/budget", clone_status=StatusEnum.COMPLETED),
        project_overview={"readme_available": True},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 2, "total_files": 12},
        statistics={},
        dependency_information={"nodes": [], "edges": []},
        code_structure=CodeStructureSummary(parsed_files_count=len(pfs), supported_languages=["Python"], files=pfs),
        architecture=ArchitectureSummary(
            dependency_graph={"nodes": [], "edges": []},
            call_graph=CallGraph(edges=edges),
            components=[api_comp],
        ),
        entry_points=entry_points,
        important_files=important_files,
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    result = workflow_candidate_discoverer.discover_candidates(mock_knowledge)
    # Tier 2 and Tier 3 must NOT have explored any edges
    assert len(result.omitted_candidate_workflows) > 0
    # Confirm explicit omission reasons for budget exhaustion
    omitted_text = " ".join(result.omitted_candidate_workflows)
    assert "Candidate exploration budget reached (500 edges examined)" in omitted_text
    assert "architectural API components omitted without exploration" in omitted_text


# ===========================================================================
# 8. Phase 3: Evidence Builder, Prompts, Validator, and Analyzer Tests
# ===========================================================================

def _create_mock_knowledge_for_phase3():
    from app.models.schemas import (
        ArchitectureSummary,
        ArchitecturalComponent,
        CallGraph,
        CallGraphEdge,
        CodeStructureSummary,
        DependencyEdge,
        DependencyGraph,
        EntryPointCandidate,
        FunctionCallInfo,
        FunctionInfo,
        ImportInfo,
        RelationshipEvidence,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        SourceLocation,
        StatusEnum,
    )

    code_main = """
from app.service import process_request

def start_app():
    process_request("payload")
"""
    code_service = """
import sqlite3
from app.storage import write_db

def process_request(data):
    save_record(data)
"""
    code_save = """def save_record(data):
    import sqlite3
    conn = sqlite3.connect("test.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO items VALUES (?)", (data,))
    write_db(data)"""
    code_storage = """
def write_db(data):
    pass
"""

    pfs = [
        ParsedFile(
            file_path="app/main.py",
            language="Python",
            status="success",
            total_lines=10,
            functions=[
                FunctionInfo(
                    name="start_app",
                    file_path="app/main.py",
                    location=SourceLocation(file_path="app/main.py", start_line=4, end_line=5, start_column=0, end_column=0),
                    snippet=code_main,
                )
            ],
            function_calls=[
                FunctionCallInfo(call_name="process_request", file_path="app/main.py", line_number=5, enclosing_scope="start_app")
            ],
        ),
        ParsedFile(
            file_path="app/service.py",
            language="Python",
            status="success",
            total_lines=20,
            functions=[
                FunctionInfo(
                    name="process_request",
                    file_path="app/service.py",
                    location=SourceLocation(file_path="app/service.py", start_line=5, end_line=6, start_column=0, end_column=0),
                    snippet=code_service,
                ),
                FunctionInfo(
                    name="save_record",
                    file_path="app/service.py",
                    location=SourceLocation(file_path="app/service.py", start_line=8, end_line=14, start_column=0, end_column=0),
                    snippet=code_save,
                ),
            ],
            imports=[
                ImportInfo(module="sqlite3", file_path="app/service.py", line_number=2)
            ],
            function_calls=[
                FunctionCallInfo(call_name="save_record", file_path="app/service.py", line_number=6, enclosing_scope="process_request"),
                FunctionCallInfo(call_name="write_db", file_path="app/service.py", line_number=14, enclosing_scope="save_record"),
            ],
        ),
        ParsedFile(
            file_path="app/storage.py",
            language="Python",
            status="success",
            total_lines=10,
            functions=[
                FunctionInfo(
                    name="write_db",
                    file_path="app/storage.py",
                    location=SourceLocation(file_path="app/storage.py", start_line=2, end_line=3, start_column=0, end_column=0),
                    snippet=code_storage,
                )
            ],
            function_calls=[],
        ),
        ParsedFile(
            file_path="app/config.py",
            language="Python",
            status="success",
            total_lines=5,
            functions=[],
            function_calls=[],
        ),
    ]

    edges = [
        CallGraphEdge(
            caller="app/main.py:start_app",
            callee="app/service.py:process_request",
            call_name="process_request",
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="app/main.py", line_number=5, evidence_type="function_call"),
        ),
        CallGraphEdge(
            caller="app/service.py:process_request",
            callee="app/service.py:save_record",
            call_name="save_record",
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="app/service.py", line_number=6, evidence_type="function_call"),
        ),
        CallGraphEdge(
            caller="app/service.py:save_record",
            callee="app/storage.py:write_db",
            call_name="write_db",
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="app/service.py", line_number=14, evidence_type="function_call"),
        ),
    ]

    dep_edges = [
        DependencyEdge(
            source="app/main.py",
            target="app/service.py",
            is_internal=True,
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="app/main.py", line_number=2, evidence_type="import_statement"),
        ),
        DependencyEdge(
            source="app/service.py",
            target="app/storage.py",
            is_internal=True,
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="app/service.py", line_number=3, evidence_type="import_statement"),
        ),
        # Pure import edge with NO call edge!
        DependencyEdge(
            source="app/main.py",
            target="app/config.py",
            is_internal=True,
            resolution_status="resolved_internal",
            evidence=RelationshipEvidence(file_path="app/main.py", line_number=1, evidence_type="import_statement"),
        ),
    ]

    return RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/phase3_app", owner="test", repository_url="https://github.com/test/phase3_app", clone_status=StatusEnum.COMPLETED),
        project_overview={"description": "Test phase 3 app"},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 2, "total_files": 4},
        statistics={},
        dependency_information=DependencyGraph(nodes=[], edges=dep_edges),
        code_structure=CodeStructureSummary(parsed_files_count=len(pfs), supported_languages=["Python"], files=pfs),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(nodes=[], edges=dep_edges),
            call_graph=CallGraph(edges=edges),
            components=[
                ArchitecturalComponent(file_path="app/main.py", category="entry_point", confidence="high", evidence=["main"]),
                ArchitecturalComponent(file_path="app/service.py", category="service", confidence="high", evidence=["service"]),
                ArchitecturalComponent(file_path="app/storage.py", category="database", confidence="high", evidence=["db"]),
            ],
        ),
        entry_points=[
            EntryPointCandidate(file_path="app/main.py", entry_type="python_main_guard", symbol_or_command="start_app", confidence="high")
        ],
        important_files=[],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )


def test_evidence_builder_builds_bounded_package():
    """Evidence builder constructs structured candidate evidence with snippets and operation verifications."""
    from app.services.ai.workflow_understanding import workflow_evidence_builder

    knowledge = _create_mock_knowledge_for_phase3()
    pkg = workflow_evidence_builder.build_evidence_package(knowledge)

    assert pkg.repository_name == "test/phase3_app"
    assert len(pkg.selected_candidates) >= 1
    cand = pkg.selected_candidates[0]
    assert cand.entry_file == "app/main.py"
    assert cand.entry_symbol == "start_app"
    assert len(cand.call_steps) >= 1

    # Verify storage verification was attached to callee snippet for save_record
    save_record_step = next((s for s in cand.call_steps if s.callee_symbol == "save_record"), None)
    assert save_record_step is not None
    assert save_record_step.storage_verification is not None
    assert save_record_step.storage_verification["storage_operation_verified"] is True
    assert save_record_step.storage_verification["storage_operation_type"] == "write"

    assert pkg.budget_exceeded is False


def test_evidence_builder_candidate_budget_truncation():
    """Evidence builder enforces per-candidate character budget by truncating snippet bodies."""
    from app.services.ai.workflow_understanding.evidence_builder import WorkflowEvidenceBuilder

    knowledge = _create_mock_knowledge_for_phase3()
    builder = WorkflowEvidenceBuilder()
    builder.MAX_CANDIDATE_CHAR_BUDGET = 200  # Intentionally tiny budget

    pkg = builder.build_evidence_package(knowledge)
    assert pkg.budget_exceeded is True
    assert len(pkg.truncation_reasons) > 0
    # Confirm truncation marker in candidate limitations
    cand = pkg.selected_candidates[0]
    assert any("truncated to preserve prompt character budget" in lim for lim in cand.limitations_and_unresolved)


def test_prompts_system_and_user_prompts():
    """Prompts include strict anti-hallucination rules and accurate JSON schema."""
    from app.services.ai.workflow_understanding import (
        SYSTEM_PROMPT,
        build_workflow_repair_prompt,
        build_workflow_user_prompt,
        workflow_evidence_builder,
    )

    # System prompt assertions
    assert "runtime_execution_verified" in SYSTEM_PROMPT
    assert "MUST ALWAYS be false" in SYSTEM_PROMPT
    assert "NEVER USE IMPORTS AS EXECUTION TRANSITIONS" in SYSTEM_PROMPT
    assert "GROUNDED EVIDENCE ONLY" in SYSTEM_PROMPT

    knowledge = _create_mock_knowledge_for_phase3()
    pkg = workflow_evidence_builder.build_evidence_package(knowledge)
    user_prompt = build_workflow_user_prompt(pkg)

    assert "GROUNDED WORKFLOW EVIDENCE:" in user_prompt
    assert "test/phase3_app" in user_prompt
    assert "REQUIRED OUTPUT JSON SCHEMA:" in user_prompt

    repair_prompt = build_workflow_repair_prompt("{malformed", "Unexpected end of JSON")
    assert "Unexpected end of JSON" in repair_prompt
    assert "{malformed" in repair_prompt


def test_workflow_validator_enforces_runtime_execution_verified_invariant():
    """Validator strictly enforces runtime_execution_verified = False on all steps and workflows."""
    from app.services.ai.workflow_understanding import (
        ApplicationWorkflow,
        RepositoryWorkflowUnderstanding,
        WorkflowComponentReference,
        WorkflowStep,
        workflow_validator,
    )

    knowledge = _create_mock_knowledge_for_phase3()

    step = WorkflowStep(
        step_number=1,
        title="Start application",
        component_id="app/main.py",
        symbol_name="start_app",
        action_type="call",
        description="Entry execution",
        runtime_execution_verified=False,
    )
    wf = ApplicationWorkflow(
        workflow_id="wf_1",
        name="Main App Flow",
        description="Flow",
        trigger="run",
        entry_point=WorkflowComponentReference(component_id="app/main.py", name="start_app", role_in_workflow="entry"),
        steps=[step],
        final_outcome="Done",
        runtime_execution_verified=False,
    )

    understanding = RepositoryWorkflowUnderstanding(
        repository_name="test/phase3_app",
        system_architecture_type="modular_monolith",
        workflow_summary="Summary",
        workflows=[wf],
    )

    validated = workflow_validator.validate_workflow_understanding(understanding, knowledge)
    assert validated.workflows[0].runtime_execution_verified is False
    assert validated.workflows[0].steps[0].runtime_execution_verified is False


def test_workflow_validator_rejects_import_edges_as_execution_transitions():
    """Validator demotes call relationships backed only by import edges (not CallGraph edges)."""
    from app.services.ai.workflow_understanding import (
        ApplicationWorkflow,
        CallSiteEvidence,
        RepositoryWorkflowUnderstanding,
        WorkflowComponentReference,
        WorkflowStep,
        workflow_validator,
    )

    knowledge = _create_mock_knowledge_for_phase3()

    # Step claiming transition from main.py to config.py (exists in imports, but NOT in call graph!)
    edge_id = CallSiteEvidence.format_edge_id("app/main.py", "start_app", "app/config.py", "load_config")
    site_id = CallSiteEvidence.format_site_id("app/main.py", "start_app", "app/config.py", "load_config", 1)

    step = WorkflowStep(
        step_number=1,
        title="Load config",
        component_id="app/main.py",
        symbol_name="start_app",
        action_type="call",
        description="Attempts to claim import as call execution",
        call_relationship_verified=True,  # LLM erroneously claimed True
        call_evidence=CallSiteEvidence(
            caller_file="app/main.py",
            caller_symbol="start_app",
            callee_file="app/config.py",
            callee_symbol="load_config",
            call_name="load_config",
            call_site_line=1,
            call_graph_edge_id=edge_id,
            call_site_id=site_id,
            is_edge_verified=True,
        ),
    )
    wf = ApplicationWorkflow(
        workflow_id="wf_import",
        name="Import Flow",
        description="Flow claiming import",
        trigger="run",
        entry_point=WorkflowComponentReference(component_id="app/main.py", name="start_app", role_in_workflow="entry"),
        steps=[step],
        final_outcome="Done",
    )
    understanding = RepositoryWorkflowUnderstanding(
        repository_name="test/phase3_app",
        system_architecture_type="modular_monolith",
        workflow_summary="Summary",
        workflows=[wf],
    )

    validated = workflow_validator.validate_workflow_understanding(understanding, knowledge)
    val_step = validated.workflows[0].steps[0]
    assert val_step.call_relationship_verified is False
    assert val_step.call_evidence.is_edge_verified is False
    assert val_step.confidence == "low"
    assert any("is only an import edge, NOT a function call edge" in w for w in validated.validation_warnings)


def test_workflow_validator_matches_valid_call_graph_edges():
    """Validator verifies authentic CallGraph edges and preserves verified status."""
    from app.services.ai.workflow_understanding import (
        ApplicationWorkflow,
        CallSiteEvidence,
        RepositoryWorkflowUnderstanding,
        WorkflowComponentReference,
        WorkflowStep,
        workflow_validator,
    )

    knowledge = _create_mock_knowledge_for_phase3()

    edge_id = CallSiteEvidence.format_edge_id("app/main.py", "start_app", "app/service.py", "process_request")
    site_id = CallSiteEvidence.format_site_id("app/main.py", "start_app", "app/service.py", "process_request", 5)

    step = WorkflowStep(
        step_number=1,
        title="Process Request",
        component_id="app/main.py",
        symbol_name="start_app",
        action_type="call",
        description="Call process_request",
        call_relationship_verified=True,
        call_evidence=CallSiteEvidence(
            caller_file="app/main.py",
            caller_symbol="start_app",
            callee_file="app/service.py",
            callee_symbol="process_request",
            call_name="process_request",
            call_site_line=5,
            call_graph_edge_id=edge_id,
            call_site_id=site_id,
            is_edge_verified=True,
        ),
    )
    wf = ApplicationWorkflow(
        workflow_id="wf_valid",
        name="Valid Call Flow",
        description="Flow with valid edge",
        trigger="run",
        entry_point=WorkflowComponentReference(component_id="app/main.py", name="start_app", role_in_workflow="entry"),
        steps=[step],
        final_outcome="Done",
    )
    understanding = RepositoryWorkflowUnderstanding(
        repository_name="test/phase3_app",
        system_architecture_type="modular_monolith",
        workflow_summary="Summary",
        workflows=[wf],
    )

    validated = workflow_validator.validate_workflow_understanding(understanding, knowledge)
    val_step = validated.workflows[0].steps[0]
    assert val_step.call_relationship_verified is True
    assert val_step.call_evidence.is_edge_verified is True


def test_workflow_validator_rejects_fabricated_component_files():
    """Validator logs warnings for fabricated or non-existent component file references."""
    from app.services.ai.workflow_understanding import (
        ApplicationWorkflow,
        RepositoryWorkflowUnderstanding,
        WorkflowComponentReference,
        WorkflowStep,
        workflow_validator,
    )

    knowledge = _create_mock_knowledge_for_phase3()

    wf = ApplicationWorkflow(
        workflow_id="wf_fake",
        name="Fake Component Flow",
        description="Flow",
        trigger="run",
        entry_point=WorkflowComponentReference(component_id="nonexistent/fake_entry.py", name="fake", role_in_workflow="entry"),
        participating_components=[
            WorkflowComponentReference(component_id="nonexistent/ghost.py", name="ghost", role_in_workflow="worker")
        ],
        steps=[
            WorkflowStep(
                step_number=1,
                title="Ghost step",
                component_id="nonexistent/ghost.py",
                action_type="call",
                description="desc",
            )
        ],
        final_outcome="Done",
    )
    understanding = RepositoryWorkflowUnderstanding(
        repository_name="test/phase3_app",
        system_architecture_type="modular_monolith",
        workflow_summary="Summary",
        workflows=[wf],
    )

    validated = workflow_validator.validate_workflow_understanding(understanding, knowledge)
    assert any("Entry point file 'nonexistent/fake_entry.py' does not exist" in w for w in validated.validation_warnings)
    assert any("Participating component file 'nonexistent/ghost.py' does not exist" in w for w in validated.validation_warnings)


def test_workflow_validator_downgrades_unsubstantiated_storage_and_api_claims():
    """Validator demotes uncorroborated storage and external API claims in data flows and steps."""
    from app.services.ai.workflow_understanding import (
        ApplicationWorkflow,
        DataFlow,
        RepositoryWorkflowUnderstanding,
        WorkflowComponentReference,
        WorkflowStep,
        workflow_validator,
    )

    knowledge = _create_mock_knowledge_for_phase3()

    flow = DataFlow(
        flow_id="f1",
        workflow_id="wf_storage",
        data_item_name="UserData",
        origin=WorkflowComponentReference(component_id="app/main.py", name="main", role_in_workflow="origin"),
        destination=WorkflowComponentReference(component_id="app/main.py", name="main", role_in_workflow="dest"),
        storage_operation_verified=True,
        storage_operation_type="write",
        external_api_operation_verified=True,
        external_api_operation_type="http_request",
    )
    step = WorkflowStep(
        step_number=1,
        title="Uncorroborated IO",
        component_id="app/main.py",
        action_type="storage_io",  # main.py does not do storage!
        description="Claimed storage",
    )
    wf = ApplicationWorkflow(
        workflow_id="wf_storage",
        name="Storage Flow",
        description="Flow",
        trigger="run",
        entry_point=WorkflowComponentReference(component_id="app/main.py", name="main", role_in_workflow="entry"),
        steps=[step],
        data_flows=[flow],
        final_outcome="Done",
    )
    understanding = RepositoryWorkflowUnderstanding(
        repository_name="test/phase3_app",
        system_architecture_type="modular_monolith",
        workflow_summary="Summary",
        workflows=[wf],
    )

    validated = workflow_validator.validate_workflow_understanding(understanding, knowledge)
    val_flow = validated.workflows[0].data_flows[0]
    assert val_flow.storage_operation_verified is False
    assert val_flow.storage_operation_type == "none"
    assert val_flow.persistence_status == "unverified_storage_claim"
    assert val_flow.external_api_operation_verified is False
    assert val_flow.external_api_operation_type == "none"

    val_step = validated.workflows[0].steps[0]
    assert val_step.action_type == "call"  # Downgraded from storage_io
    assert any("Claimed storage_io action uncorroborated" in w for w in validated.validation_warnings)


def test_workflow_validator_validates_intra_caller_source_order():
    """Validator verifies source order for steps sharing the same caller function."""
    from app.services.ai.workflow_understanding import (
        ApplicationWorkflow,
        CallSiteEvidence,
        RepositoryWorkflowUnderstanding,
        WorkflowComponentReference,
        WorkflowStep,
        workflow_validator,
    )

    knowledge = _create_mock_knowledge_for_phase3()

    step1 = WorkflowStep(
        step_number=1,
        title="Call 1",
        component_id="app/service.py",
        symbol_name="process_request",
        action_type="call",
        description="First call",
        source_order_verified=True,
        call_evidence=CallSiteEvidence(
            caller_file="app/service.py",
            caller_symbol="process_request",
            callee_file="app/service.py",
            callee_symbol="save_record",
            call_name="save_record",
            call_site_line=12,  # Line 12
            call_graph_edge_id="app/service.py:process_request->app/service.py:save_record",
            call_site_id="app/service.py:process_request->app/service.py:save_record@12:0",
        ),
    )
    step2 = WorkflowStep(
        step_number=2,
        title="Call 2",
        component_id="app/service.py",
        symbol_name="process_request",
        action_type="call",
        description="Second call earlier in file (inverted!)",
        source_order_verified=True,  # Erroneous claim
        call_evidence=CallSiteEvidence(
            caller_file="app/service.py",
            caller_symbol="process_request",
            callee_file="app/storage.py",
            callee_symbol="write_db",
            call_name="write_db",
            call_site_line=6,  # Line 6 < Line 12!
            call_graph_edge_id="app/service.py:process_request->app/storage.py:write_db",
            call_site_id="app/service.py:process_request->app/storage.py:write_db@6:0",
        ),
    )
    wf = ApplicationWorkflow(
        workflow_id="wf_order",
        name="Order Flow",
        description="Flow",
        trigger="run",
        entry_point=WorkflowComponentReference(component_id="app/service.py", name="process_request", role_in_workflow="entry"),
        steps=[step1, step2],
        final_outcome="Done",
    )
    understanding = RepositoryWorkflowUnderstanding(
        repository_name="test/phase3_app",
        system_architecture_type="modular_monolith",
        workflow_summary="Summary",
        workflows=[wf],
    )

    validated = workflow_validator.validate_workflow_understanding(understanding, knowledge)
    assert validated.workflows[0].steps[1].source_order_verified is False
    assert any("Line order violated" in w for w in validated.validation_warnings)


@pytest.mark.anyio
async def test_analyzer_successful_generation_with_mock_llm():
    """Analyzer successfully produces verified RepositoryWorkflowUnderstanding with mock LLM."""
    import json
    from unittest.mock import AsyncMock
    from app.services.ai.llm_manager import LLMManager
    from app.services.ai.schemas import LLMResponse, TokenUsageRecord
    from app.services.ai.workflow_understanding import WorkflowUnderstandingAnalyzer

    knowledge = _create_mock_knowledge_for_phase3()

    mock_llm_json = {
        "schema_version": "1.0",
        "repository_name": "test/phase3_app",
        "system_architecture_type": "modular_monolith",
        "workflow_summary": "Test application starts at main and dispatches to service.",
        "workflows": [
            {
                "workflow_id": "cand_1",
                "name": "Application Startup and Processing",
                "category": "user_request",
                "description": "Workflow processing incoming request.",
                "trigger": "CLI invocation of start_app",
                "entry_point": {
                    "component_id": "app/main.py",
                    "name": "start_app",
                    "role_in_workflow": "Entry point coordinator",
                },
                "participating_components": [
                    {"component_id": "app/main.py", "name": "main", "role_in_workflow": "entry"},
                    {"component_id": "app/service.py", "name": "service", "role_in_workflow": "service"},
                ],
                "steps": [
                    {
                        "step_number": 1,
                        "title": "Start Application",
                        "component_id": "app/main.py",
                        "symbol_name": "start_app",
                        "action_type": "call",
                        "description": "Calls process_request",
                        "call_relationship_verified": True,
                        "source_order_verified": True,
                        "same_execution_path_verified": True,
                        "execution_guaranteed": True,
                        "runtime_execution_verified": False,
                        "call_evidence": {
                            "caller_file": "app/main.py",
                            "caller_symbol": "start_app",
                            "callee_file": "app/service.py",
                            "callee_symbol": "process_request",
                            "call_name": "process_request",
                            "call_site_line": 5,
                            "call_graph_edge_id": "app/main.py:start_app->app/service.py:process_request",
                            "call_site_id": "app/main.py:start_app->app/service.py:process_request@5:0",
                            "is_edge_verified": True,
                            "is_site_location_verified": True,
                        },
                        "confidence": "high",
                    }
                ],
                "data_flows": [],
                "final_outcome": "Request processed successfully.",
                "call_relationships_fully_verified": True,
                "source_order_verified": True,
                "same_execution_path_verified": True,
                "execution_guaranteed": True,
                "runtime_execution_verified": False,
                "confidence": "high",
            }
        ],
    }

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.generate.return_value = LLMResponse(
        text=f"```json\n{json.dumps(mock_llm_json)}\n```",
        provider="mock_gemini",
        model="gemini-2.5-pro",
        token_usage=TokenUsageRecord(provider="mock_gemini", model="gemini-2.5-pro", prompt_tokens=400, completion_tokens=250, total_tokens=650),
        latency_ms=120.0,
    )

    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    result = await analyzer.analyze_workflows(job_id="job_test", knowledge=knowledge)

    assert result.is_fallback is False
    assert result.provider == "mock_gemini"
    assert result.model == "gemini-2.5-pro"
    assert len(result.workflows) == 1
    assert result.workflows[0].name == "Application Startup and Processing"
    assert result.workflows[0].steps[0].call_relationship_verified is True
    assert result.workflows[0].steps[0].runtime_execution_verified is False
    assert result.token_usage.total_tokens == 650


@pytest.mark.anyio
async def test_analyzer_one_shot_json_repair_success():
    """Analyzer attempts exactly 1 JSON repair query when initial response has syntax errors."""
    import json
    from unittest.mock import AsyncMock
    from app.services.ai.llm_manager import LLMManager
    from app.services.ai.schemas import LLMResponse, TokenUsageRecord
    from app.services.ai.workflow_understanding import WorkflowUnderstandingAnalyzer

    knowledge = _create_mock_knowledge_for_phase3()

    valid_dict = {
        "schema_version": "1.0",
        "repository_name": "test/phase3_app",
        "system_architecture_type": "modular_monolith",
        "workflow_summary": "Repaired workflow summary.",
        "workflows": [
            {
                "workflow_id": "cand_repaired",
                "name": "Repaired Workflow",
                "category": "user_request",
                "description": "Repaired description.",
                "trigger": "start_app",
                "entry_point": {"component_id": "app/main.py", "name": "start_app", "role_in_workflow": "entry"},
                "participating_components": [],
                "steps": [
                    {
                        "step_number": 1,
                        "title": "Start",
                        "component_id": "app/main.py",
                        "symbol_name": "start_app",
                        "action_type": "call",
                        "description": "Start step",
                        "runtime_execution_verified": False,
                    }
                ],
                "data_flows": [],
                "final_outcome": "Finished",
            }
        ],
    }

    mock_llm = AsyncMock(spec=LLMManager)
    # First call returns malformed JSON; second call (repair) returns valid JSON
    mock_llm.generate.side_effect = [
        LLMResponse(
            text="{ 'broken_json': true, unquoted_key: ",
            provider="mock_gemini",
            model="gemini-2.5-pro",
            token_usage=TokenUsageRecord(provider="mock_gemini", model="gemini-2.5-pro", prompt_tokens=400, completion_tokens=50, total_tokens=450),
            latency_ms=100.0,
        ),
        LLMResponse(
            text=json.dumps(valid_dict),
            provider="mock_gemini",
            model="gemini-2.5-pro",
            token_usage=TokenUsageRecord(provider="mock_gemini", model="gemini-2.5-pro", prompt_tokens=200, completion_tokens=150, total_tokens=350),
            latency_ms=80.0,
        ),
    ]

    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    result = await analyzer.analyze_workflows(job_id="job_repair", knowledge=knowledge)

    assert result.is_fallback is False
    assert len(result.workflows) == 1
    assert result.workflows[0].name == "Repaired Workflow"
    assert mock_llm.generate.call_count == 2
    # Combined token usage
    assert result.token_usage.total_tokens == 800


@pytest.mark.anyio
async def test_analyzer_fallback_on_unrepairable_json():
    """Analyzer falls back to deterministic AST workflows when JSON cannot be repaired."""
    from unittest.mock import AsyncMock
    from app.services.ai.llm_manager import LLMManager
    from app.services.ai.schemas import LLMResponse
    from app.services.ai.workflow_understanding import WorkflowUnderstandingAnalyzer

    knowledge = _create_mock_knowledge_for_phase3()

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.generate.side_effect = [
        LLMResponse(text="Totally unparseable prose response", provider="mock", model="m", latency_ms=50.0),
        LLMResponse(text="Still completely unparseable prose response", provider="mock", model="m", latency_ms=50.0),
    ]

    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    result = await analyzer.analyze_workflows(job_id="job_unrepairable", knowledge=knowledge)

    assert result.is_fallback is True
    assert result.provider == "deterministic_fallback"
    assert result.model == "ast_rule_based"
    assert len(result.workflows) >= 1
    assert result.workflows[0].is_deterministic is True
    assert any("LLM output unparseable and repair failed" in lim for lim in result.analysis_limitations)


@pytest.mark.anyio
async def test_analyzer_fallback_on_ai_provider_error():
    """Analyzer falls back cleanly when LLM manager raises AIRateLimitError."""
    from unittest.mock import AsyncMock
    from app.services.ai.exceptions import AIRateLimitError
    from app.services.ai.llm_manager import LLMManager
    from app.services.ai.workflow_understanding import WorkflowUnderstandingAnalyzer

    knowledge = _create_mock_knowledge_for_phase3()

    mock_llm = AsyncMock(spec=LLMManager)
    mock_llm.generate.side_effect = AIRateLimitError("Rate limit exceeded", provider="gemini")

    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    result = await analyzer.analyze_workflows(job_id="job_error", knowledge=knowledge)

    assert result.is_fallback is True
    assert result.provider == "deterministic_fallback"
    assert result.model == "ast_rule_based"
    assert len(result.workflows) >= 1
    assert any("AI generation unavailable" in w for w in result.validation_warnings)


@pytest.mark.anyio
async def test_analyzer_empty_candidate_fallback():
    """Analyzer returns an empty deterministic fallback when no candidates can be discovered."""
    from unittest.mock import AsyncMock
    from app.models.schemas import (
        ArchitectureSummary,
        CallGraph,
        CodeStructureSummary,
        DependencyGraph,
        RepositoryKnowledge,
        RepositoryMetadataInfo,
        StatusEnum,
    )
    from app.services.ai.llm_manager import LLMManager
    from app.services.ai.workflow_understanding import WorkflowUnderstandingAnalyzer

    empty_knowledge = RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(name="test/empty", owner="test", repository_url="https://github.com/test/empty", clone_status=StatusEnum.COMPLETED),
        project_overview={},
        technology_stack={"languages": []},
        repository_structure={"total_directories": 0, "total_files": 0},
        statistics={},
        dependency_information=DependencyGraph(nodes=[], edges=[]),
        code_structure=CodeStructureSummary(parsed_files_count=0, supported_languages=[], files=[]),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(nodes=[], edges=[]),
            call_graph=CallGraph(edges=[]),
            components=[],
        ),
        entry_points=[],
        important_files=[],
        analysis_metadata={"created_at": "2026-11-05T00:00:00Z"},
    )

    mock_llm = AsyncMock(spec=LLMManager)
    analyzer = WorkflowUnderstandingAnalyzer(llm_manager=mock_llm)
    result = await analyzer.analyze_workflows(job_id="job_empty", knowledge=empty_knowledge)

    assert result.is_fallback is True
    assert len(result.workflows) == 0
    assert mock_llm.generate.call_count == 0  # Did not attempt LLM call
    assert any("No entry-point or call-chain workflow candidates" in lim for lim in result.analysis_limitations)




