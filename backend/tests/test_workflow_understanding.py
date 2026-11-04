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


