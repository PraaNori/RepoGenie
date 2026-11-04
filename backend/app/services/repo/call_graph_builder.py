import logging
import posixpath
from typing import Dict, List, Optional, Set, Tuple

from ...core.config import settings
from ...models.schemas import (
    CallGraph,
    CallGraphEdge,
    CallGraphNode,
    FunctionCallInfo,
    ParsedFile,
    RelationshipEvidence,
)

logger = logging.getLogger(__name__)

# Standard language built-ins to filter out from unresolved spam
BUILTIN_FUNCTIONS: Set[str] = {
    # Python
    "print", "len", "range", "str", "int", "float", "bool", "dict", "list", "set",
    "tuple", "isinstance", "issubclass", "getattr", "setattr", "hasattr", "open",
    "type", "super", "enumerate", "zip", "map", "filter", "any", "all", "sum",
    "min", "max", "abs", "round", "repr", "dir", "id", "hash", "iter", "next",
    "format", "callable", "vars", "sorted", "reversed", "bytes", "bytearray",
    # JavaScript / TypeScript
    "console.log", "console.error", "console.warn", "console.info", "console.debug",
    "require", "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURI", "decodeURI",
    "encodeURIComponent", "decodeURIComponent", "String", "Number", "Boolean",
    "Array", "Object", "Function", "Symbol", "Error", "TypeError", "Promise",
    "fetch", "alert", "prompt", "confirm", "JSON.stringify", "JSON.parse",
    "Math.min", "Math.max", "Math.floor", "Math.ceil", "Math.round", "Math.abs",
    # Go
    "make", "new", "cap", "append", "copy", "close", "delete", "complex",
    "real", "imag", "panic", "recover", "println",
    # Rust
    "println!", "eprintln!", "format!", "vec!", "panic!", "assert!", "assert_eq!",
    # C / C++
    "printf", "scanf", "malloc", "free", "calloc", "realloc", "sizeof",
    "memcpy", "memset", "strlen", "strcmp", "strcpy", "exit", "puts",
    # Java
    "System.out.println", "System.err.println", "toString", "equals", "hashCode",
}


class CallGraphBuilder:
    """
    Constructs a directed function call graph connecting callers to callees across the repository.
    Distinguishes resolved internal function/method calls from external or unresolved references.
    """

    def __init__(
        self,
        max_nodes: int = settings.MAX_GRAPH_NODES,
        max_edges: int = settings.MAX_GRAPH_EDGES,
        max_unresolved_retained: int = settings.MAX_UNRESOLVED_REFS_RETAINED,
    ):
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self.max_unresolved_retained = max_unresolved_retained

    def build_call_graph(
        self,
        parsed_files: List[ParsedFile],
        all_internal_files: Set[str],
    ) -> CallGraph:
        """
        Builds a CallGraph with nodes representing functions/methods and edges representing calls.
        """
        nodes_dict: Dict[str, CallGraphNode] = {}
        edges: List[CallGraphEdge] = []
        edge_keys: Set[Tuple[str, str, str]] = set()

        # Indexes for fast lookup
        # 1. file_path -> function_name -> node_id
        file_functions: Dict[str, Dict[str, str]] = {}
        # 2. file_path -> class_name -> method_name -> node_id
        file_methods: Dict[str, Dict[str, Dict[str, str]]] = {}
        # 3. function_name -> list of (file_path, node_id)
        global_functions: Dict[str, List[Tuple[str, str]]] = {}
        # 4. (file_path, imported_symbol) -> target_file
        imported_symbols: Dict[Tuple[str, str], str] = {}

        # First pass: register all defined functions and methods as CallGraphNode
        for pf in parsed_files:
            file_functions.setdefault(pf.file_path, {})
            file_methods.setdefault(pf.file_path, {})

            # Register functions
            for func in pf.functions:
                node_id = f"{pf.file_path}:{func.name}"
                if len(nodes_dict) < self.max_nodes:
                    node = CallGraphNode(
                        id=node_id,
                        name=func.name,
                        file_path=pf.file_path,
                        enclosing_class=None,
                    )
                    nodes_dict[node_id] = node
                file_functions[pf.file_path][func.name] = node_id
                global_functions.setdefault(func.name, []).append((pf.file_path, node_id))

            # Register methods
            for meth in pf.methods:
                node_id = f"{pf.file_path}:{meth.parent_class}.{meth.name}"
                if len(nodes_dict) < self.max_nodes:
                    node = CallGraphNode(
                        id=node_id,
                        name=meth.name,
                        file_path=pf.file_path,
                        enclosing_class=meth.parent_class,
                    )
                    nodes_dict[node_id] = node
                file_methods[pf.file_path].setdefault(meth.parent_class, {})[meth.name] = node_id
                global_functions.setdefault(meth.name, []).append((pf.file_path, node_id))

            # Map imported symbols
            for imp in pf.imports:
                for sym in imp.symbols:
                    # Check if module maps to an internal file
                    mod_path = imp.module.replace(".", "/")
                    for cand_ext in (".py", ".ts", ".js", ".go", ".rs", "/__init__.py"):
                        cand = posixpath.normpath(posixpath.join(posixpath.dirname(pf.file_path), f"{mod_path}{cand_ext}"))
                        if cand in all_internal_files:
                            imported_symbols[(pf.file_path, sym)] = cand
                            break
                        cand_root = posixpath.normpath(f"{mod_path}{cand_ext}")
                        if cand_root in all_internal_files:
                            imported_symbols[(pf.file_path, sym)] = cand_root
                            break

        total_resolved = 0
        total_unresolved = 0
        unresolved_retained_count = 0

        # Second pass: resolve function calls to caller -> callee edges
        for pf in parsed_files:
            file_p = pf.file_path
            for call in pf.function_calls:
                call_name = call.call_name
                scope = call.enclosing_scope

                # Determine caller node ID
                if scope:
                    caller_id = f"{file_p}:{scope}"
                    if caller_id not in nodes_dict and len(nodes_dict) < self.max_nodes:
                        # Infer enclosing function/method node
                        nodes_dict[caller_id] = CallGraphNode(
                            id=caller_id,
                            name=scope.split(".")[-1],
                            file_path=file_p,
                            enclosing_class=scope.split(".")[0] if "." in scope else None,
                        )
                else:
                    caller_id = f"{file_p}:<module>"
                    if caller_id not in nodes_dict and len(nodes_dict) < self.max_nodes:
                        nodes_dict[caller_id] = CallGraphNode(
                            id=caller_id,
                            name="<module>",
                            file_path=file_p,
                            enclosing_class=None,
                        )

                # Callee resolution logic
                callee_id: Optional[str] = None
                resolution_status = "unresolved"
                confidence = "low"

                # Check 1: self.method or this.method
                if (call_name.startswith("self.") or call_name.startswith("this.")) and scope and "." in scope:
                    cls_name = scope.split(".")[0]
                    m_name = call_name.split(".", 1)[1]
                    if cls_name in file_methods.get(file_p, {}) and m_name in file_methods[file_p][cls_name]:
                        callee_id = file_methods[file_p][cls_name][m_name]
                        resolution_status = "resolved_internal"
                        confidence = "high"

                # Check 2: Same-file function
                if not callee_id and call_name in file_functions.get(file_p, {}):
                    callee_id = file_functions[file_p][call_name]
                    resolution_status = "resolved_internal"
                    confidence = "high"

                # Check 3: Same-file method (Class.method or method in current class)
                if not callee_id:
                    if "." in call_name:
                        parts = call_name.split(".", 1)
                        if parts[0] in file_methods.get(file_p, {}) and parts[1] in file_methods[file_p][parts[0]]:
                            callee_id = file_methods[file_p][parts[0]][parts[1]]
                            resolution_status = "resolved_internal"
                            confidence = "high"
                    elif scope and "." in scope:
                        cls_name = scope.split(".")[0]
                        if cls_name in file_methods.get(file_p, {}) and call_name in file_methods[file_p][cls_name]:
                            callee_id = file_methods[file_p][cls_name][call_name]
                            resolution_status = "resolved_internal"
                            confidence = "high"

                # Check 4: Imported symbol
                if not callee_id and (file_p, call_name) in imported_symbols:
                    target_file = imported_symbols[(file_p, call_name)]
                    if call_name in file_functions.get(target_file, {}):
                        callee_id = file_functions[target_file][call_name]
                        resolution_status = "resolved_internal"
                        confidence = "high"

                # Check 5: Dotted call on imported module (e.g., utils.helper)
                if not callee_id and "." in call_name:
                    mod_prefix, func_target = call_name.split(".", 1)
                    if (file_p, mod_prefix) in imported_symbols:
                        target_file = imported_symbols[(file_p, mod_prefix)]
                        if func_target in file_functions.get(target_file, {}):
                            callee_id = file_functions[target_file][func_target]
                            resolution_status = "resolved_internal"
                            confidence = "high"

                # Check 6: Unique repository-wide function
                if not callee_id and call_name not in BUILTIN_FUNCTIONS:
                    matches = global_functions.get(call_name, [])
                    if len(matches) == 1:
                        target_file, target_node_id = matches[0]
                        callee_id = target_node_id
                        resolution_status = "resolved_internal"
                        confidence = "medium"

                # Handle resolution counts and edge creation
                if resolution_status == "resolved_internal" and callee_id:
                    total_resolved += 1
                    edge_key = (caller_id, callee_id, call_name)
                    if edge_key not in edge_keys and len(edges) < self.max_edges:
                        edge_keys.add(edge_key)
                        edges.append(
                            CallGraphEdge(
                                caller=caller_id,
                                callee=callee_id,
                                call_name=call_name,
                                resolution_status="resolved_internal",
                                evidence=RelationshipEvidence(
                                    evidence_type="function_call",
                                    statement=f"{call_name}(...)",
                                    file_path=file_p,
                                    line_number=call.line_number,
                                    confidence=confidence,
                                ),
                            )
                        )
                else:
                    total_unresolved += 1
                    # Retain unresolved calls if not a standard builtin and under max unresolved limit
                    if (
                        call_name not in BUILTIN_FUNCTIONS
                        and unresolved_retained_count < self.max_unresolved_retained
                    ):
                        unresolved_id = f"external:{call_name}"
                        if unresolved_id not in nodes_dict and len(nodes_dict) < self.max_nodes:
                            nodes_dict[unresolved_id] = CallGraphNode(
                                id=unresolved_id,
                                name=call_name,
                                file_path="external",
                                enclosing_class=None,
                            )
                        edge_key = (caller_id, unresolved_id, call_name)
                        if edge_key not in edge_keys and len(edges) < self.max_edges:
                            edge_keys.add(edge_key)
                            unresolved_retained_count += 1
                            edges.append(
                                CallGraphEdge(
                                    caller=caller_id,
                                    callee=unresolved_id,
                                    call_name=call_name,
                                    resolution_status="external_or_unresolved",
                                    evidence=RelationshipEvidence(
                                        evidence_type="function_call",
                                        statement=f"{call_name}(...)",
                                        file_path=file_p,
                                        line_number=call.line_number,
                                        confidence="low",
                                    ),
                                )
                            )

        return CallGraph(
            nodes=list(nodes_dict.values()),
            edges=edges,
            total_resolved_calls=total_resolved,
            total_unresolved_calls=total_unresolved,
        )


call_graph_builder = CallGraphBuilder()
