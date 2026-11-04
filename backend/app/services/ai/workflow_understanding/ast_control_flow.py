"""
Python Tree-sitter AST Control-Flow and Call-Site Analyzer.

Analyzes Tree-sitter AST parent/ancestor node hierarchies to evaluate:
1. source_order_verified: Textual ordering of call sites within the exact same caller symbol and file.
2. same_execution_path_verified: At least one statically valid control-flow path contains both calls in order.
3. execution_guaranteed: The later call is guaranteed to execute after the earlier call.
4. runtime_execution_verified: Always False (RepoGenie does not execute code).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple, Union
import tree_sitter
import tree_sitter_python as tspython

from ....models.schemas import CallGraphEdge, FunctionCallInfo, ParsedFile
from .schemas import CallSiteEvidence

logger = logging.getLogger(__name__)


@dataclass
class ControlFlowAnalysisResult:
    """Detailed multi-dimensional control-flow evaluation for a call-site transition."""
    source_order_verified: bool = False
    same_execution_path_verified: bool = False
    execution_guaranteed: bool = False
    runtime_execution_verified: bool = False  # ALWAYS False
    is_same_caller: bool = False
    unresolved_aspects: List[str] = field(default_factory=list)


class PythonASTControlFlowAnalyzer:
    """
    Inspects Python syntax trees using Tree-sitter to analyze statement sequences,
    branch disjointness, loops, exception handlers, and early exits.
    """

    def __init__(self):
        self._language = tree_sitter.Language(tspython.language())
        self._parser = tree_sitter.Parser(self._language)

    def analyze_transition(
        self,
        source_code: Union[str, bytes],
        caller_file: str,
        caller_symbol: str,
        call_a_line: int,
        call_b_line: int,
        call_a_name: Optional[str] = None,
        call_b_name: Optional[str] = None,
        call_b_file: Optional[str] = None,
        call_b_caller_symbol: Optional[str] = None,
    ) -> ControlFlowAnalysisResult:
        """
        Evaluates the transition from Call A to Call B within a caller scope.

        Strict Rules:
        - Line numbers must NEVER be compared across different files or functions.
        - Cross-function or cross-file calls return is_same_caller=False and unverified ordering.
        - Distinguishes mutually exclusive branches (if/else), loops, and early exits.
        - Distinguishes possible same-path reachability from guaranteed execution.
        """
        result = ControlFlowAnalysisResult()

        # Rule 1: Strictly forbid cross-file or cross-function line comparisons
        norm_file_a = caller_file.replace("\\", "/").strip().lstrip("/")
        norm_file_b = (call_b_file or caller_file).replace("\\", "/").strip().lstrip("/")
        caller_sym_b = call_b_caller_symbol or caller_symbol

        if norm_file_a != norm_file_b:
            result.is_same_caller = False
            result.unresolved_aspects.append(
                f"Calls originate from different files ('{norm_file_a}' vs '{norm_file_b}'); cross-file line comparison is forbidden."
            )
            return result

        if caller_symbol != caller_sym_b:
            result.is_same_caller = False
            result.unresolved_aspects.append(
                f"Calls originate from different caller functions ('{caller_symbol}' vs '{caller_sym_b}'); cross-function line comparison is forbidden."
            )
            return result

        result.is_same_caller = True

        # Parse the source code
        content_bytes = source_code.encode("utf-8") if isinstance(source_code, str) else source_code
        tree = self._parser.parse(content_bytes)
        root = tree.root_node

        # Locate the caller function_definition AST node
        fn_node = self._find_caller_function(root, caller_symbol)
        if not fn_node:
            result.unresolved_aspects.append(
                f"Caller symbol '{caller_symbol}' could not be located in AST for file '{caller_file}'."
            )
            return result

        # Locate Call A and Call B nodes within the caller function
        call_a_node = self._find_call_node(fn_node, call_a_line, call_a_name)
        call_b_node = self._find_call_node(fn_node, call_b_line, call_b_name)

        if not call_a_node:
            result.unresolved_aspects.append(
                f"Call A ('{call_a_name or 'call'}') could not be located at line {call_a_line} in '{caller_symbol}'."
            )
            return result

        if not call_b_node:
            result.unresolved_aspects.append(
                f"Call B ('{call_b_name or 'call'}') could not be located at line {call_b_line} in '{caller_symbol}'."
            )
            return result

        # Check textual order within the same caller
        pos_a = (call_a_node.start_point.row + 1, call_a_node.start_point.column + 1)
        pos_b = (call_b_node.start_point.row + 1, call_b_node.start_point.column + 1)

        if pos_a >= pos_b:
            result.source_order_verified = False
            result.unresolved_aspects.append(
                f"Call A at line {pos_a[0]} does not textually precede Call B at line {pos_b[0]}."
            )
            return result

        result.source_order_verified = True

        # Analyze control-flow reachability and guarantees using AST ancestors
        self._evaluate_ast_control_flow(fn_node, call_a_node, call_b_node, result)
        return result

    def _find_caller_function(
        self, root: tree_sitter.Node, caller_symbol: str
    ) -> Optional[tree_sitter.Node]:
        """Finds the function_definition node matching caller_symbol (e.g. 'invoke' or 'Command.invoke')."""
        target_fn = caller_symbol.split(".")[-1]
        target_cls = caller_symbol.split(".")[-2] if "." in caller_symbol else None

        stack = [(root, None)]
        while stack:
            node, current_class = stack.pop()
            if node.type == "class_definition":
                cls_name = None
                for c in node.children:
                    if c.type == "identifier":
                        cls_name = c.text.decode("utf-8", errors="replace")
                        break
                for c in reversed(node.children):
                    stack.append((c, cls_name))
                continue

            if node.type == "function_definition":
                fn_name = None
                for c in node.children:
                    if c.type == "identifier":
                        fn_name = c.text.decode("utf-8", errors="replace")
                        break
                if fn_name == target_fn:
                    if not target_cls or (current_class == target_cls):
                        return node

            for c in reversed(node.children):
                stack.append((c, current_class))

        return None

    def _find_call_node(
        self,
        fn_node: tree_sitter.Node,
        target_line: int,
        target_name: Optional[str] = None,
    ) -> Optional[tree_sitter.Node]:
        """Finds a call node whose start line matches target_line."""
        calls: List[tree_sitter.Node] = []

        def collect(n: tree_sitter.Node):
            if n.type == "call":
                line = n.start_point.row + 1
                if line == target_line:
                    calls.append(n)
            for c in n.children:
                collect(c)

        collect(fn_node)
        if not calls:
            return None

        if target_name and len(calls) > 1:
            for call in calls:
                func_n = call.child_by_field_name("function") or (call.children[0] if call.children else None)
                if func_n:
                    name_text = func_n.text.decode("utf-8", errors="replace")
                    if target_name in name_text:
                        return call

        return calls[0]

    def _evaluate_ast_control_flow(
        self,
        fn_node: tree_sitter.Node,
        call_a: tree_sitter.Node,
        call_b: tree_sitter.Node,
        result: ControlFlowAnalysisResult,
    ) -> None:
        """
        Navigates AST ancestor relationships between Call A and Call B to establish:
        - Mutually exclusive branches
        - Same-path reachability
        - Execution guarantees
        """
        ancestors_a = self._get_ancestors(call_a, fn_node)
        ancestors_b = self._get_ancestors(call_b, fn_node)

        # Lowest Common Ancestor
        lca = self._find_lca(ancestors_a, ancestors_b)
        if not lca:
            result.unresolved_aspects.append("No common ancestor block found for calls in caller AST.")
            return

        child_a_under_lca = self._get_child_under_lca(ancestors_a, lca)
        child_b_under_lca = self._get_child_under_lca(ancestors_b, lca)

        # 1. Mutually Exclusive Branches: LCA is if_statement
        if lca.type == "if_statement":
            if self._are_disjoint_conditional_branches(lca, child_a_under_lca, child_b_under_lca):
                result.same_execution_path_verified = False
                result.execution_guaranteed = False
                result.unresolved_aspects.append(
                    "Call A and Call B reside in mutually exclusive conditional branches (if/elif/else)."
                )
                return

        # 2. Mutually Exclusive Branches: LCA is try_statement
        if lca.type == "try_statement":
            if self._are_disjoint_try_branches(lca, child_a_under_lca, child_b_under_lca):
                result.same_execution_path_verified = False
                result.execution_guaranteed = False
                result.unresolved_aspects.append(
                    "Call A and Call B reside in mutually exclusive try/except blocks."
                )
                return

        # 3. Check for loops enclosing either call
        has_loop = any(n.type in ("for_statement", "while_statement") for n in ancestors_a + ancestors_b)
        if has_loop:
            result.same_execution_path_verified = True
            result.execution_guaranteed = False
            result.unresolved_aspects.append(
                "Call occurs inside a loop; dynamic iteration count prevents guaranteed execution."
            )

        # 4. Check for exception handlers enclosing either call
        has_exception = any(n.type in ("except_clause", "finally_clause") for n in ancestors_a + ancestors_b)
        if has_exception:
            result.execution_guaranteed = False
            result.unresolved_aspects.append(
                "Call occurs inside an exception handler; execution depends on runtime exception occurrence."
            )

        # 5. Check sequential continuation and early exits
        # Traverse all blocks from call_a up to lca to detect subsequent exits in the same block
        unconditional_exit_found = False
        conditional_exit_found = False

        curr = call_a
        while curr.parent and curr.parent != lca:
            p = curr.parent
            if p.type == "block":
                stmts = [c for c in p.children if c.type not in (":", "(", ")")]
                if curr in stmts:
                    idx = stmts.index(curr)
                    for sub in stmts[idx + 1:]:
                        if sub.type in ("return_statement", "raise_statement"):
                            unconditional_exit_found = True
                        elif self._has_any_exit(sub):
                            conditional_exit_found = True
            curr = p

        # Check intervening statements in lca if lca is a block
        if lca.type in ("block", "module"):
            child_a = child_a_under_lca
            child_b = child_b_under_lca
            stmts = [c for c in lca.children if c.type not in (":", "(", ")")]
            if child_a in stmts and child_b in stmts:
                idx_a = stmts.index(child_a)
                idx_b = stmts.index(child_b)
                for mid in stmts[idx_a + 1:idx_b]:
                    if mid.type in ("return_statement", "raise_statement"):
                        unconditional_exit_found = True
                    elif self._has_any_exit(mid):
                        conditional_exit_found = True

        if unconditional_exit_found:
            result.same_execution_path_verified = False
            result.execution_guaranteed = False
            result.unresolved_aspects.append(
                "Unconditional early exit (return/raise) following Call A prevents execution from reaching Call B."
            )
            return

        # Path reachability: If no unconditional exits block it, a valid path exists
        result.same_execution_path_verified = True

        # Check if Call B is enclosed in a conditional below LCA
        b_in_conditional = any(
            n.type in ("if_statement", "elif_clause", "else_clause")
            for n in ancestors_b
            if n != lca
        )

        if (
            conditional_exit_found
            or b_in_conditional
            or has_loop
            or has_exception
        ):
            result.execution_guaranteed = False
            if conditional_exit_found:
                result.unresolved_aspects.append(
                    "Conditional early exit (return/raise) along the path prevents guaranteed execution of Call B."
                )
            elif b_in_conditional:
                result.unresolved_aspects.append(
                    "Call B is enclosed in a conditional block and is not guaranteed to execute."
                )
        else:
            result.execution_guaranteed = True

    def _get_ancestors(self, node: tree_sitter.Node, root_limit: tree_sitter.Node) -> List[tree_sitter.Node]:
        """Returns the ancestor chain from node up to root_limit inclusive."""
        res: List[tree_sitter.Node] = []
        curr = node
        while curr is not None:
            res.append(curr)
            if curr == root_limit:
                break
            curr = curr.parent
        return res

    def _find_lca(
        self, ancestors_a: List[tree_sitter.Node], ancestors_b: List[tree_sitter.Node]
    ) -> Optional[tree_sitter.Node]:
        """Finds the lowest common ancestor node."""
        set_b = set(ancestors_b)
        for a in ancestors_a:
            if a in set_b:
                return a
        return None

    def _get_child_under_lca(
        self, ancestors: List[tree_sitter.Node], lca: tree_sitter.Node
    ) -> tree_sitter.Node:
        """Finds the direct child of LCA that is an ancestor of the node."""
        for i, node in enumerate(ancestors):
            if node == lca and i > 0:
                return ancestors[i - 1]
        return ancestors[0]

    def _are_disjoint_conditional_branches(
        self, if_node: tree_sitter.Node, child_a: tree_sitter.Node, child_b: tree_sitter.Node
    ) -> bool:
        """Checks if child_a and child_b belong to mutually exclusive if/elif/else branches."""
        # Tree-sitter if_statement structure:
        # - consequence block
        # - elif_clause (has its own block)
        # - else_clause (has its own block)
        branch_types = ("block", "elif_clause", "else_clause")
        type_a = child_a.type
        type_b = child_b.type

        if type_a in branch_types and type_b in branch_types and child_a != child_b:
            return True
        return False

    def _are_disjoint_try_branches(
        self, try_node: tree_sitter.Node, child_a: tree_sitter.Node, child_b: tree_sitter.Node
    ) -> bool:
        """Checks if child_a and child_b belong to mutually exclusive try vs except branches."""
        branch_types = ("block", "except_clause")
        type_a = child_a.type
        type_b = child_b.type
        if type_a in branch_types and type_b in branch_types and child_a != child_b:
            return True
        return False

    def _has_unconditional_exit_after_node(
        self, container: tree_sitter.Node, reference_call: tree_sitter.Node
    ) -> bool:
        """Checks if an unconditional return/raise statement appears after reference_call in container."""
        ref_line = reference_call.end_point.row + 1
        for child in container.children:
            if child.start_point.row + 1 >= ref_line:
                if self._is_unconditional_exit(child):
                    return True
        return False

    def _has_conditional_exit_after_node(
        self, container: tree_sitter.Node, reference_call: tree_sitter.Node
    ) -> bool:
        """Checks if a conditional statement contains a return/raise after reference_call in container."""
        ref_line = reference_call.end_point.row + 1
        for child in container.children:
            if child.start_point.row + 1 >= ref_line:
                if child.type in ("if_statement", "elif_clause", "else_clause"):
                    if self._has_any_exit(child):
                        return True
        return False

    def _is_unconditional_exit(self, node: tree_sitter.Node) -> bool:
        """Checks if node is a top-level return or raise statement."""
        return node.type in ("return_statement", "raise_statement")

    def _has_any_exit(self, node: tree_sitter.Node) -> bool:
        """Checks recursively whether node contains any return or raise statement."""
        if node.type in ("return_statement", "raise_statement"):
            return True
        for c in node.children:
            if self._has_any_exit(c):
                return True
        return False


# Global analyzer singleton for Python AST control flow
python_ast_control_flow = PythonASTControlFlowAnalyzer()


def verify_call_site_location(
    parsed_file: ParsedFile,
    call_name: str,
    target_line: int,
    caller_scope: Optional[str] = None,
) -> bool:
    """
    Verifies that a call expression with the given name actually exists
    at target_line in parsed_file.function_calls.
    """
    scope_fn = caller_symbol_name = caller_scope.split(".")[-1] if caller_scope else None
    for fc in getattr(parsed_file, "function_calls", []):
        if fc.line_number == target_line:
            # Check call name match (exact or suffix, e.g. 'ParamType.convert' vs 'convert')
            if (
                fc.call_name == call_name
                or fc.call_name.endswith(f".{call_name}")
                or call_name.endswith(f".{fc.call_name}")
            ):
                if (
                    caller_scope is None
                    or fc.enclosing_scope == caller_scope
                    or fc.enclosing_scope == scope_fn
                    or fc.enclosing_scope is None
                ):
                    return True
    return False


def build_and_verify_call_site(
    caller_file: str,
    caller_symbol: str,
    callee_file: str,
    callee_symbol: str,
    call_name: str,
    call_site_line: int,
    call_site_column: Optional[int] = None,
    parsed_file: Optional[ParsedFile] = None,
    call_graph_edges: Optional[List[CallGraphEdge]] = None,
) -> CallSiteEvidence:
    """
    Constructs a CallSiteEvidence instance with separated graph-edge ID and
    call-site ID, verifying each dimension independently.

    A valid CallGraphEdge does NOT prove the call_site_line is correct.
    A valid line in ParsedFile does NOT prove the directional CallGraphEdge exists.
    """
    edge_id = CallSiteEvidence.format_edge_id(caller_file, caller_symbol, callee_file, callee_symbol)
    site_id = CallSiteEvidence.format_site_id(
        caller_file, caller_symbol, callee_file, callee_symbol, call_site_line, call_site_column
    )

    # 1. Verify graph edge if edges provided
    is_edge_verified = False
    if call_graph_edges:
        norm_caller_file = caller_file.replace("\\", "/").strip().lstrip("/")
        norm_callee_file = callee_file.replace("\\", "/").strip().lstrip("/")
        caller_node_id = f"{norm_caller_file}:{caller_symbol}"
        callee_node_id = f"{norm_callee_file}:{callee_symbol}"

        for edge in call_graph_edges:
            edge_src = edge.caller.replace("\\", "/").strip().lstrip("/")
            edge_tgt = edge.callee.replace("\\", "/").strip().lstrip("/")
            if (edge_src == caller_node_id or edge_src == caller_symbol) and (
                edge_tgt == callee_node_id or edge_tgt == callee_symbol
            ):
                is_edge_verified = True
                break

    # 2. Verify physical call site location in parsed file
    is_site_location_verified = False
    if parsed_file:
        is_site_location_verified = verify_call_site_location(
            parsed_file=parsed_file,
            call_name=call_name,
            target_line=call_site_line,
            caller_scope=caller_symbol,
        )

    return CallSiteEvidence(
        caller_file=caller_file,
        caller_symbol=caller_symbol,
        callee_file=callee_file,
        callee_symbol=callee_symbol,
        call_name=call_name,
        call_site_line=call_site_line,
        call_site_column=call_site_column,
        call_graph_edge_id=edge_id,
        call_site_id=site_id,
        is_edge_verified=is_edge_verified,
        is_site_location_verified=is_site_location_verified,
    )

