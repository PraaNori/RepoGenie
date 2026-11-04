"""
Python Tree-sitter AST Control-Flow, Call-Site, and Data Transformation Analyzer.

Analyzes Tree-sitter AST parent/ancestor node hierarchies to evaluate:
1. source_order_verified: Textual ordering of call sites within the exact same caller symbol and file.
2. same_execution_path_verified: At least one statically valid control-flow path contains both calls in order.
3. execution_guaranteed: The later call is guaranteed to execute after the earlier call along the normal,
   non-exceptional static control-flow path (no intervening conditionals, loops, try blocks, or early exits).
   Note: Dynamic runtime exceptions thrown inside callee functions are unobserved runtime phenomena outside
   static AST guarantee scope.
4. runtime_execution_verified: Always False (RepoGenie does not execute code).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union
import tree_sitter
import tree_sitter_python as tspython

from ....models.schemas import (
    CallGraphEdge,
    FunctionCallInfo,
    FunctionInfo,
    MethodInfo,
    ParsedFile,
)
from .schemas import CallSiteEvidence, DataFlow, DataTransformation, WorkflowStep

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
    is_in_conditional: bool = False
    is_in_loop: bool = False
    is_in_try_block: bool = False
    mutually_exclusive_branches: bool = False


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

    def analyze_caller_control_flow(
        self,
        parsed_file: Optional[ParsedFile],
        caller_symbol: str,
        call_a_line: int,
        call_b_line: int,
        call_a_name: Optional[str] = None,
        call_b_name: Optional[str] = None,
    ) -> ControlFlowAnalysisResult:
        """
        Analyzes control flow between two call sites within the same caller scope
        using the caller's AST snippet if available, or line ordering fallback.
        """
        result = ControlFlowAnalysisResult()
        result.is_same_caller = True

        if not parsed_file:
            result.source_order_verified = (call_a_line < call_b_line) if (call_a_line and call_b_line) else False
            result.same_execution_path_verified = result.source_order_verified
            result.execution_guaranteed = False
            result.unresolved_aspects.append("No parsed file available for caller AST control flow.")
            return result

        # Find matching function/method/class in parsed_file
        target_fn = caller_symbol.split(".")[-1]
        matched_snippet: Optional[str] = None
        start_line: int = 1

        for f in parsed_file.functions:
            if f.name == target_fn or f.name == caller_symbol:
                matched_snippet = f.snippet
                start_line = f.location.start_line
                break
        if not matched_snippet:
            for m in parsed_file.methods:
                if m.name == target_fn or f"{m.parent_class}.{m.name}" == caller_symbol:
                    matched_snippet = m.snippet
                    start_line = m.location.start_line
                    break

        if matched_snippet:
            # Pad snippet so 1-indexed line numbers match parsed_file lines
            padding = "\n" * max(0, start_line - 1)
            padded_code = padding + matched_snippet
            try:
                res = self.analyze_transition(
                    source_code=padded_code,
                    caller_file=parsed_file.file_path,
                    caller_symbol=caller_symbol,
                    call_a_line=call_a_line,
                    call_b_line=call_b_line,
                    call_a_name=call_a_name,
                    call_b_name=call_b_name,
                )
                if res.is_same_caller:
                    return res
            except Exception as exc:
                logger.debug("AST transition analysis fallback on error: %s", exc)

        # Fallback to line numbers if AST snippet not parseable
        result.source_order_verified = (call_a_line < call_b_line) if (call_a_line and call_b_line) else False
        result.same_execution_path_verified = result.source_order_verified
        result.execution_guaranteed = False
        result.unresolved_aspects.append("Caller AST snippet unavailable; evaluated using source line order.")
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
                result.mutually_exclusive_branches = True
                result.is_in_conditional = True
                result.unresolved_aspects.append(
                    "Call A and Call B reside in mutually exclusive conditional branches (if/elif/else)."
                )
                return

        # 2. Mutually Exclusive Branches: LCA is try_statement
        if lca.type == "try_statement":
            if self._are_disjoint_try_branches(lca, child_a_under_lca, child_b_under_lca):
                result.same_execution_path_verified = False
                result.execution_guaranteed = False
                result.mutually_exclusive_branches = True
                result.is_in_try_block = True
                result.unresolved_aspects.append(
                    "Call A and Call B reside in mutually exclusive try/except blocks."
                )
                return

        # 3. Check for loops enclosing either call
        has_loop = any(n.type in ("for_statement", "while_statement") for n in ancestors_a + ancestors_b)
        if has_loop:
            result.is_in_loop = True
            result.same_execution_path_verified = True
            result.execution_guaranteed = False
            result.unresolved_aspects.append(
                "Call occurs inside a loop; dynamic iteration count prevents guaranteed execution."
            )

        # 4. Check for try blocks or exception handlers enclosing either call
        has_try_statement = any(n.type == "try_statement" for n in ancestors_a + ancestors_b)
        has_exception_handler = any(n.type in ("except_clause", "finally_clause") for n in ancestors_a + ancestors_b)
        if has_try_statement or has_exception_handler:
            result.is_in_try_block = True
            result.execution_guaranteed = False
            if has_exception_handler:
                result.unresolved_aspects.append(
                    "Call occurs inside an exception handler; execution depends on runtime exception occurrence."
                )
            else:
                result.unresolved_aspects.append(
                    "Calls occur inside a try block; runtime exceptions can divert execution to an exception handler before reaching the later call."
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

        # Check if Call B or Call A is enclosed in a conditional
        b_in_conditional = any(
            n.type in ("if_statement", "elif_clause", "else_clause")
            for n in ancestors_b
            if n != lca
        )
        a_in_conditional = any(
            n.type in ("if_statement", "elif_clause", "else_clause")
            for n in ancestors_a
            if n != lca
        )
        if b_in_conditional or a_in_conditional or lca.type in ("if_statement", "elif_clause", "else_clause"):
            result.is_in_conditional = True

        if (
            conditional_exit_found
            or b_in_conditional
            or has_loop
            or has_try_statement
            or has_exception_handler
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

    def _find_call_by_name(
        self, root_node: tree_sitter.Node, full_name: str, short_name: str
    ) -> Optional[tree_sitter.Node]:
        """Recursively finds a call node matching full_name or short_name."""
        matching_node = None

        def _traverse(n: tree_sitter.Node):
            nonlocal matching_node
            if matching_node:
                return
            if n.type == "call":
                func_child = n.child_by_field_name("function")
                if func_child:
                    c_text = func_child.text.decode("utf-8").strip()
                    if (
                        c_text == full_name
                        or c_text == short_name
                        or c_text.endswith(f".{short_name}")
                        or (full_name and full_name.endswith(f".{c_text}"))
                    ):
                        matching_node = n
                        return
            for c in n.children:
                _traverse(c)

        _traverse(root_node)
        return matching_node

    def _get_function_parameter_names(self, fn_node: tree_sitter.Node) -> List[str]:
        """Extracts formal parameter names from a function_definition node."""
        params_node = fn_node.child_by_field_name("parameters")
        if not params_node:
            return []
        names: List[str] = []
        for child in params_node.children:
            if child.type == "identifier":
                names.append(child.text.decode("utf-8").strip())
            elif child.type in ("typed_parameter", "default_parameter", "typed_default_parameter"):
                id_child = child.child_by_field_name("name") or (child.children[0] if child.children else None)
                if id_child and id_child.type == "identifier":
                    names.append(id_child.text.decode("utf-8").strip())
        return names

    def _track_local_aliases(
        self, fn_node: tree_sitter.Node, target_call_node: tree_sitter.Node, initial_aliases: Set[str]
    ) -> Set[str]:
        """
        Scans assignments before target_call_node to track local variables
        aliasing the input data item or parameters.
        """
        aliases = {a.lower() for a in initial_aliases}
        call_row = target_call_node.start_point.row

        def _scan(n: tree_sitter.Node):
            if n.start_point.row >= call_row and n != target_call_node:
                return
            if n.type == "assignment":
                left = n.child_by_field_name("left")
                right = n.child_by_field_name("right")
                if left and right and left.type == "identifier":
                    var_name = left.text.decode("utf-8").strip().lower()
                    right_text = right.text.decode("utf-8").strip().lower()
                    if right_text in aliases or any(tok in right_text for tok in aliases):
                        aliases.add(var_name)
                    else:
                        for c in right.children:
                            if c.type == "identifier" and c.text.decode("utf-8").strip().lower() in aliases:
                                aliases.add(var_name)
                                break
            for c in n.children:
                _scan(c)

        _scan(fn_node)
        return aliases

    def _check_direct_data_operations(self, fn_node: tree_sitter.Node, data_tokens: Set[str]) -> bool:
        """
        Checks if any data item identifier in fn_node undergoes an operation
        (attribute access/method call, subscript, binary op, or transformation call).
        """
        found = False

        def _scan(n: tree_sitter.Node):
            nonlocal found
            if found:
                return
            if n.type == "identifier":
                name = n.text.decode("utf-8").strip().lower()
                if name in data_tokens or any(tok in name for tok in data_tokens):
                    p = n.parent
                    if p:
                        if p.type == "attribute" and p.child_by_field_name("object") == n:
                            found = True
                            return
                        elif p.type == "subscript" and p.child_by_field_name("value") == n:
                            found = True
                            return
                        elif p.type in ("binary_operator", "augmented_assignment"):
                            found = True
                            return
                        elif p.type == "argument_list" and p.parent and p.parent.type == "call":
                            call_fn = p.parent.child_by_field_name("function")
                            call_name = call_fn.text.decode("utf-8").strip().lower() if call_fn else ""
                            if call_name not in ("print", "isinstance", "len", "type", "debug"):
                                found = True
                                return
            for c in n.children:
                _scan(c)

        _scan(fn_node)
        return found

    def verify_data_transformation_evidence(
        self,
        parsed_file: Optional[ParsedFile],
        transformation: DataTransformation,
        data_flow: DataFlow,
        workflow_steps: List[WorkflowStep],
        parsed_files_map: Dict[str, ParsedFile],
    ) -> Tuple[bool, str, Optional[str], List[str]]:
        """
        Statically verifies whether concrete AST and data-flow evidence supports an
        observed transformation claim.
        """
        t_comp = transformation.performed_by_component.replace("\\", "/").strip().lstrip("/")
        t_sym = transformation.performed_by_symbol
        t_name = transformation.transformation_name
        data_item = (data_flow.data_item_name or "").strip()
        data_tokens = {tok.lower() for tok in data_item.replace("_", " ").split() if len(tok) > 1}
        data_tokens.add(data_item.lower())

        pf_t = parsed_files_map.get(t_comp) or parsed_file
        if not pf_t:
            return (
                False,
                "unknown_or_unresolved",
                None,
                [f"Transformation '{t_name}': component '{t_comp}' does not exist in repository."],
            )

        # 1. Verify existence of the performed_by_symbol
        target_fn: Optional[Union[FunctionInfo, MethodInfo]] = None
        if t_sym:
            sym_clean = t_sym.split(".")[-1]
            for fn in getattr(pf_t, "functions", []):
                if fn.name == t_sym or fn.name == sym_clean:
                    target_fn = fn
                    break
            if not target_fn:
                for m in getattr(pf_t, "methods", []):
                    if m.name == t_sym or m.name == sym_clean or f"{m.parent_class}.{m.name}" == t_sym:
                        target_fn = m
                        break

            if not target_fn:
                return (
                    False,
                    "unknown_or_unresolved",
                    None,
                    [f"Transformation '{t_name}': symbol '{t_sym}' not found in component '{t_comp}'."],
                )

        # Cross-function transformation check
        orig_comp = getattr(getattr(data_flow, "origin", None), "component_id", None) or getattr(data_flow, "origin_component", None)
        dest_comp = getattr(getattr(data_flow, "destination", None), "component_id", None) or getattr(data_flow, "destination_component", None)
        if orig_comp:
            orig_comp = orig_comp.replace("\\", "/").strip().lstrip("/")
        if dest_comp:
            dest_comp = dest_comp.replace("\\", "/").strip().lstrip("/")

        if orig_comp and dest_comp and orig_comp != dest_comp:
            has_param_link = False
            for s in workflow_steps:
                ce = getattr(s, "call_evidence", None)
                if ce and ce.caller_file == orig_comp and ce.callee_file == dest_comp:
                    has_param_link = True
                    break
            if not has_param_link:
                return (
                    False,
                    "inferred",
                    None,
                    [
                        f"Cross-function transformation claim for '{t_sym}' lacks verified parameter/return flow linking '{orig_comp}' and '{dest_comp}'; demoted to inferred."
                    ],
                )

        # 2. Check if t_sym is called by any step in the workflow
        step_callers = []
        for s in workflow_steps:
            if s.component_id:
                s_c = s.component_id.replace("\\", "/").strip().lstrip("/")
                s_pf = parsed_files_map.get(s_c)
                if s_pf and s.symbol_name:
                    step_callers.append((s_c, s.symbol_name, s_pf))

        is_step_symbol = any(
            (sc == t_comp and (sn == t_sym or sn == getattr(target_fn, "name", None)))
            for sc, sn, _ in step_callers
        )

        calling_step = None
        if not is_step_symbol and t_sym:
            sym_clean = t_sym.split(".")[-1]
            for sc, sn, s_pf in step_callers:
                for fc in getattr(s_pf, "function_calls", []):
                    if (
                        fc.call_name == t_sym
                        or fc.call_name == sym_clean
                        or fc.call_name.endswith(f".{sym_clean}")
                    ):
                        if (
                            fc.enclosing_scope == sn
                            or fc.enclosing_scope == sn.split(".")[-1]
                            or fc.enclosing_scope is None
                        ):
                            calling_step = (sc, sn, s_pf)
                            break
                if calling_step:
                    break

            if not calling_step:
                for sc, sn, s_pf in step_callers:
                    caller_fn = next((f for f in getattr(s_pf, "functions", []) if f.name == sn), None)
                    if not caller_fn:
                        caller_fn = next((m for m in getattr(s_pf, "methods", []) if m.name == sn), None)
                    if caller_fn and caller_fn.snippet:
                        tree = self._parser.parse(caller_fn.snippet.encode("utf-8"))
                        fn_node = self._find_caller_function(tree.root_node, sn) or tree.root_node
                        found_call = self._find_call_by_name(fn_node, t_sym, sym_clean)
                        if found_call:
                            calling_step = (sc, sn, s_pf)
                            break

            if not calling_step:
                return (
                    False,
                    "inferred",
                    None,
                    [
                        f"Transformation function '{t_sym}' exists in '{t_comp}' but is never called in workflow steps; demoted from observed to inferred."
                    ],
                )

        # 3. Argument Flow and Intermediate Variable Tracking
        if calling_step:
            sc, sn, s_pf = calling_step
            caller_fn = next((f for f in getattr(s_pf, "functions", []) if f.name == sn), None)
            if not caller_fn:
                caller_fn = next((m for m in getattr(s_pf, "methods", []) if m.name == sn), None)

            if caller_fn and caller_fn.snippet:
                tree = self._parser.parse(caller_fn.snippet.encode("utf-8"))
                fn_node = self._find_caller_function(tree.root_node, sn) or tree.root_node
                sym_clean = t_sym.split(".")[-1] if t_sym else ""
                call_node = self._find_call_by_name(fn_node, t_sym or "", sym_clean)

                if call_node:
                    aliases = set(data_tokens)
                    params = self._get_function_parameter_names(fn_node)
                    for p in params:
                        if any(tok in p.lower() for tok in data_tokens) or p.lower() in ("data", "payload", "item", "val", "msg", "record", "raw_input"):
                            aliases.add(p.lower())

                    aliases_tracked = self._track_local_aliases(fn_node, call_node, aliases)

                    args_match = False
                    arg_list = call_node.child_by_field_name("arguments")
                    if arg_list:
                        for arg_child in arg_list.children:
                            if arg_child.type in (",", "(", ")"):
                                continue
                            arg_text = arg_child.text.decode("utf-8").strip().lower()
                            if arg_text in aliases_tracked or any(tok in arg_text for tok in data_tokens):
                                args_match = True
                                break

                    if not args_match:
                        return (
                            False,
                            "inferred",
                            None,
                            [
                                f"Transformation call '{t_sym}' in '{sn}' does not receive or operate on data item '{data_item}'; demoted to inferred."
                            ],
                        )

                    op_type = "aliased_call_argument_flow_verified" if len(aliases_tracked) > len(aliases) else "call_and_argument_flow_verified"
                    return (
                        True,
                        "observed",
                        op_type,
                        [],
                    )

        # 4. Direct In-Function Transformation (when t_sym is the step function itself)
        if is_step_symbol and target_fn and target_fn.snippet:
            tree = self._parser.parse(target_fn.snippet.encode("utf-8"))
            fn_node = self._find_caller_function(tree.root_node, target_fn.name) or tree.root_node
            has_transform_op = self._check_direct_data_operations(fn_node, data_tokens)
            if has_transform_op:
                return (
                    True,
                    "observed",
                    "direct_data_operation_verified",
                    [],
                )
            else:
                return (
                    False,
                    "inferred",
                    None,
                    [
                        f"Symbol '{t_sym}' does not perform an observable transformation on data item '{data_item}'; demoted to inferred."
                    ],
                )

        # 5. Cross-Function Transformation Claims without verified parameter/return link
        if data_flow.origin_component != data_flow.destination_component:
            return (
                False,
                "inferred",
                None,
                [
                    f"Cross-function transformation claim for '{t_sym}' lacks verified parameter/return flow linking '{data_flow.origin_component}' and '{data_flow.destination_component}'; demoted to inferred."
                ],
            )

        return (False, "inferred", None, [f"Transformation '{t_name}' lacks static AST evidence; demoted to inferred."])


# Global analyzer singleton for Python AST control flow
python_ast_control_flow = PythonASTControlFlowAnalyzer()


def verify_call_site_location(
    parsed_file: ParsedFile,
    call_name: str,
    target_line: int,
    caller_scope: Optional[str] = None,
    target_column: Optional[int] = None,
) -> bool:
    """
    Verifies that a call expression with the given name actually exists
    at target_line (and target_column if specified) in parsed_file.function_calls or AST.
    """
    scope_fn = caller_scope.split(".")[-1] if caller_scope else None

    # 1. Check FunctionCallInfo list in parsed_file
    call_info_matched = False
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
                    fc_col = getattr(fc, "column_number", None)
                    if target_column is not None and fc_col is not None:
                        if target_column == fc_col or target_column == (fc_col + 1):
                            return True
                        else:
                            continue
                    elif target_column is None:
                        return True
                    else:
                        call_info_matched = True
                        break

    # 2. If target_column is specified, verify column against AST node in caller function snippet if available
    if target_column is not None:
        target_fn = scope_fn or (caller_scope or "")
        matched_snippet = None
        start_line = 1
        for f in getattr(parsed_file, "functions", []):
            if f.name == target_fn or f.name == caller_scope:
                matched_snippet = f.snippet
                start_line = getattr(getattr(f, "location", None), "start_line", 1) or 1
                break
        if not matched_snippet:
            for m in getattr(parsed_file, "methods", []):
                if m.name == target_fn or f"{m.parent_class}.{m.name}" == caller_scope:
                    matched_snippet = m.snippet
                    start_line = getattr(getattr(m, "location", None), "start_line", 1) or 1
                    break

        if matched_snippet:
            try:
                tree = python_ast_control_flow._parser.parse(matched_snippet.encode("utf-8"))
                fn_node = python_ast_control_flow._find_caller_function(tree.root_node, caller_scope or target_fn)
                fn_row = fn_node.start_point.row if fn_node else 0
                search_root = fn_node or tree.root_node

                matching_call_node = None

                def _find_matching_call(node):
                    nonlocal matching_call_node
                    if matching_call_node:
                        return
                    if node.type == "call":
                        call_line = (node.start_point.row - fn_row) + start_line
                        func_child = node.child_by_field_name("function")
                        c_name = func_child.text.decode("utf-8") if func_child else ""
                        if (call_line == target_line or (node.start_point.row + 1) == target_line) and (
                            c_name == call_name
                            or c_name.endswith(f".{call_name}")
                            or call_name.endswith(f".{c_name}")
                        ):
                            matching_call_node = node
                            return
                    for child in node.children:
                        _find_matching_call(child)

                _find_matching_call(search_root)
                if matching_call_node:
                    col_0 = matching_call_node.start_point.column
                    col_1 = col_0 + 1
                    if target_column in (col_0, col_1):
                        return True
                    else:
                        return False
                elif call_info_matched:
                    return target_column >= 0
            except Exception as exc:
                logger.debug("AST column verification fallback: %s", exc)
                return call_info_matched

    return call_info_matched


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
            target_column=call_site_column,
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

