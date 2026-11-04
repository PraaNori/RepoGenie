import os
import posixpath
from typing import Dict, List, Optional, Set, Tuple

from ...models.schemas import (
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    ImportInfo,
    ParsedFile,
    RelationshipEvidence,
)

# Standard libraries across languages for accurate external detection
PYTHON_STDLIB: Set[str] = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "bisect", "builtins",
    "calendar", "collections", "contextlib", "copy", "csv", "ctypes", "dataclasses",
    "datetime", "decimal", "difflib", "dis", "enum", "errno", "exceptions", "faulthandler",
    "fcntl", "fnmatch", "fractions", "functools", "gc", "glob", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "importlib", "inspect", "io", "itertools", "json",
    "keyword", "linecache", "locale", "logging", "math", "mimetypes", "mmap",
    "multiprocessing", "numbers", "operator", "os", "pathlib", "pickle", "platform",
    "posixpath", "pprint", "pstats", "py_compile", "queue", "quopri", "random", "re",
    "readline", "resource", "sched", "secrets", "select", "selectors", "shelve",
    "shlex", "shutil", "signal", "site", "socket", "socketserver", "sqlite3", "ssl",
    "stat", "statistics", "string", "struct", "subprocess", "sys", "sysconfig",
    "tarfile", "tempfile", "termios", "textwrap", "threading", "time", "timeit",
    "token", "tokenize", "trace", "traceback", "tracemalloc", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "xml", "xmlrpc", "zipfile", "zipimport", "zlib", "zoneinfo",
}

GO_STDLIB_PREFIXES: Tuple[str, ...] = (
    "fmt", "net", "os", "io", "sync", "strings", "time", "context", "errors",
    "bytes", "path", "log", "math", "bufio", "crypto", "database", "encoding",
    "flag", "html", "image", "mime", "reflect", "regexp", "runtime", "sort",
    "strconv", "syscall", "testing", "unicode",
)

JAVA_STDLIB_PREFIXES: Tuple[str, ...] = (
    "java.", "javax.", "sun.", "com.sun.", "org.w3c.", "org.xml.",
)

C_SYSTEM_HEADERS: Set[str] = {
    "stdio.h", "stdlib.h", "string.h", "math.h", "time.h", "assert.h", "ctype.h",
    "errno.h", "float.h", "limits.h", "locale.h", "setjmp.h", "signal.h", "stdarg.h",
    "stddef.h", "stdint.h", "stdbool.h", "inttypes.h", "unistd.h", "fcntl.h",
    "sys/types.h", "sys/stat.h", "sys/socket.h", "netinet/in.h", "arpa/inet.h",
    "pthread.h", "iostream", "vector", "string", "map", "set", "unordered_map",
    "unordered_set", "memory", "algorithm", "functional", "chrono", "thread",
    "mutex", "future", "utility", "sstream", "fstream", "queue", "deque", "stack",
}

RUST_STDLIB_PREFIXES: Tuple[str, ...] = (
    "std::", "core::", "alloc::", "proc_macro::",
)

class DependencyResolver:
    """
    Analyzes imports across parsed repository files and constructs a directed dependency graph.
    Distinguishes internal file dependencies from external packages and identifies circular dependencies.
    """

    def __init__(self, max_nodes: int = 1000, max_edges: int = 5000):
        self.max_nodes = max_nodes
        self.max_edges = max_edges

    def resolve_python_import(
        self,
        module_raw: str,
        importing_file: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        """
        Resolves Python imports (absolute and relative) to internal files or external packages.
        Returns: (resolved_target, resolution_status, is_internal)
        """
        clean_mod = module_raw.strip()
        if not clean_mod:
            return None, "unresolved", False

        # Check for relative import (leading dots)
        if clean_mod.startswith("."):
            importing_dir = posixpath.dirname(importing_file)
            dot_count = len(clean_mod) - len(clean_mod.lstrip("."))
            sub_mod = clean_mod.lstrip(".")

            # . is current dir, .. is parent dir
            curr_dir = importing_dir
            for _ in range(dot_count - 1):
                curr_dir = posixpath.dirname(curr_dir)

            rel_as_path = sub_mod.replace(".", "/") if sub_mod else ""
            target_base = posixpath.normpath(posixpath.join(curr_dir, rel_as_path)) if rel_as_path else curr_dir

            # Candidates: target_base.py or target_base/__init__.py
            for candidate in (
                f"{target_base}.py",
                posixpath.join(target_base, "__init__.py"),
                f"{target_base}.pyw",
            ):
                norm_cand = posixpath.normpath(candidate)
                if norm_cand in all_internal_files:
                    return norm_cand, "resolved_internal", True

            return clean_mod, "unresolved", False

        # Absolute import: check standard library
        top_package = clean_mod.split(".")[0]
        if top_package in PYTHON_STDLIB:
            return top_package, "external_package", False

        # Check absolute resolution against internal files
        path_candidate = clean_mod.replace(".", "/")
        candidates = [
            f"{path_candidate}.py",
            posixpath.join(path_candidate, "__init__.py"),
        ]

        # Check in root directly
        for cand in candidates:
            norm_cand = posixpath.normpath(cand)
            if norm_cand in all_internal_files:
                return norm_cand, "resolved_internal", True

        # Check if project has sub-roots like backend/, src/, app/
        importing_top_dir = importing_file.split("/")[0] if "/" in importing_file else ""
        if importing_top_dir:
            for cand in candidates:
                prefixed = posixpath.normpath(posixpath.join(importing_top_dir, cand))
                if prefixed in all_internal_files:
                    return prefixed, "resolved_internal", True

        # Check common roots: src/, app/, lib/
        for root_prefix in ("src", "app", "lib", "backend", "pkg"):
            for cand in candidates:
                prefixed = posixpath.normpath(posixpath.join(root_prefix, cand))
                if prefixed in all_internal_files:
                    return prefixed, "resolved_internal", True

        # Suffix matching: e.g. clean_mod is "services.user_service", check if any internal file ends with it
        suffix_match = f"/{path_candidate}.py"
        for internal_f in all_internal_files:
            if internal_f.endswith(suffix_match) or internal_f == f"{path_candidate}.py":
                return internal_f, "resolved_internal", True

        # Otherwise treat top package as external
        return top_package, "external_package", False

    def resolve_js_ts_import(
        self,
        module_raw: str,
        importing_file: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        """
        Resolves JavaScript and TypeScript imports to relative files, index files, or packages.
        """
        clean_mod = module_raw.strip("\"' ")
        if not clean_mod:
            return None, "unresolved", False

        # Relative import
        if clean_mod.startswith("./") or clean_mod.startswith("../"):
            importing_dir = posixpath.dirname(importing_file)
            joined = posixpath.normpath(posixpath.join(importing_dir, clean_mod))

            # Test exact match
            if joined in all_internal_files:
                return joined, "resolved_internal", True

            # Test extensions
            for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
                cand = f"{joined}{ext}"
                if cand in all_internal_files:
                    return cand, "resolved_internal", True

            # Test index files
            for idx_file in (
                posixpath.join(joined, "index.ts"),
                posixpath.join(joined, "index.tsx"),
                posixpath.join(joined, "index.js"),
                posixpath.join(joined, "index.jsx"),
            ):
                if idx_file in all_internal_files:
                    return idx_file, "resolved_internal", True

            return clean_mod, "unresolved", False

        # Aliased path (@/...)
        if clean_mod.startswith("@/"):
            stripped = clean_mod[2:]
            for prefix in ("src", "", "frontend/src"):
                base = posixpath.normpath(posixpath.join(prefix, stripped)) if prefix else stripped
                for ext in ("", ".ts", ".tsx", ".js", ".jsx"):
                    cand = f"{base}{ext}"
                    if cand in all_internal_files:
                        return cand, "resolved_internal", True

        # External package (npm / yarn)
        pkg_name = clean_mod
        if pkg_name.startswith("@"):
            # Scoped package like @sindresorhus/is
            parts = pkg_name.split("/")
            pkg_name = "/".join(parts[:2]) if len(parts) >= 2 else pkg_name
        else:
            pkg_name = pkg_name.split("/")[0]

        return pkg_name, "external_package", False

    def resolve_go_import(
        self,
        module_raw: str,
        importing_file: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        clean_mod = module_raw.strip("\"' ")
        if not clean_mod:
            return None, "unresolved", False

        for prefix in GO_STDLIB_PREFIXES:
            if clean_mod == prefix or clean_mod.startswith(f"{prefix}/"):
                return clean_mod, "external_package", False

        # Check internal repository packages by directory
        for f in all_internal_files:
            if f.endswith(".go") and (clean_mod in f or posixpath.dirname(f).endswith(clean_mod)):
                return f, "resolved_internal", True

        return clean_mod, "external_package", False

    def resolve_java_import(
        self,
        module_raw: str,
        importing_file: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        clean_mod = module_raw.strip("; ")
        if not clean_mod:
            return None, "unresolved", False

        for prefix in JAVA_STDLIB_PREFIXES:
            if clean_mod.startswith(prefix):
                return clean_mod.split(".")[0] + "." + clean_mod.split(".")[1], "external_package", False

        # com.example.service.UserService -> com/example/service/UserService.java
        as_path = clean_mod.replace(".", "/") + ".java"
        for f in all_internal_files:
            if f.endswith(as_path):
                return f, "resolved_internal", True

        return clean_mod.split(".")[0], "external_package", False

    def resolve_c_cpp_include(
        self,
        module_raw: str,
        importing_file: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        clean_mod = module_raw.strip("<>\"' ")
        if not clean_mod:
            return None, "unresolved", False

        if clean_mod in C_SYSTEM_HEADERS:
            return clean_mod, "external_package", False

        # Check relative to importing file
        importing_dir = posixpath.dirname(importing_file)
        joined = posixpath.normpath(posixpath.join(importing_dir, clean_mod))
        if joined in all_internal_files:
            return joined, "resolved_internal", True

        # Check include/ or src/
        for prefix in ("include", "src", "inc", ""):
            cand = posixpath.normpath(posixpath.join(prefix, clean_mod)) if prefix else clean_mod
            if cand in all_internal_files:
                return cand, "resolved_internal", True

        # Suffix match
        for f in all_internal_files:
            if f.endswith(f"/{clean_mod}") or f == clean_mod:
                return f, "resolved_internal", True

        return clean_mod, "external_package", False

    def resolve_rust_use(
        self,
        module_raw: str,
        importing_file: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        clean_mod = module_raw.strip("; ")
        if not clean_mod:
            return None, "unresolved", False

        for prefix in RUST_STDLIB_PREFIXES:
            if clean_mod.startswith(prefix):
                return clean_mod.split("::")[0], "external_package", False

        if clean_mod.startswith("crate::"):
            sub = clean_mod.replace("crate::", "").split("::")[0]
            for ext in (".rs", "/mod.rs"):
                for root_dir in ("src", ""):
                    cand = posixpath.normpath(posixpath.join(root_dir, f"{sub}{ext}"))
                    if cand in all_internal_files:
                        return cand, "resolved_internal", True

        # Check if first segment matches an internal file
        top_seg = clean_mod.split("::")[0]
        for f in all_internal_files:
            if f.endswith(f"/{top_seg}.rs") or f == f"{top_seg}.rs":
                return f, "resolved_internal", True

        return top_seg, "external_package", False

    def resolve_import(
        self,
        import_info: ImportInfo,
        importing_file: str,
        language: str,
        all_internal_files: Set[str],
    ) -> Tuple[Optional[str], str, bool]:
        """
        Dispatch language-specific import resolution rules.
        """
        lang = language.lower()
        mod = import_info.module

        if "python" in lang:
            return self.resolve_python_import(mod, importing_file, all_internal_files)
        elif "javascript" in lang or "typescript" in lang:
            return self.resolve_js_ts_import(mod, importing_file, all_internal_files)
        elif "go" in lang:
            return self.resolve_go_import(mod, importing_file, all_internal_files)
        elif "java" in lang:
            return self.resolve_java_import(mod, importing_file, all_internal_files)
        elif "rust" in lang:
            return self.resolve_rust_use(mod, importing_file, all_internal_files)
        elif "c" in lang:
            return self.resolve_c_cpp_include(mod, importing_file, all_internal_files)
        else:
            # Fallback relative resolution
            if mod.startswith("./") or mod.startswith("../"):
                importing_dir = posixpath.dirname(importing_file)
                cand = posixpath.normpath(posixpath.join(importing_dir, mod))
                if cand in all_internal_files:
                    return cand, "resolved_internal", True
            return mod, "unresolved", False

    def detect_circular_dependencies(self, edges: List[DependencyEdge]) -> List[List[str]]:
        """
        Finds elementary circular dependencies among internal file nodes using DFS.
        """
        adj: Dict[str, Set[str]] = {}
        for edge in edges:
            if edge.is_internal and edge.resolution_status == "resolved_internal":
                if edge.source != edge.target:
                    adj.setdefault(edge.source, set()).add(edge.target)

        cycles: List[List[str]] = []
        visited: Set[str] = set()
        rec_stack: List[str] = []

        def dfs(node: str):
            visited.add(node)
            rec_stack.append(node)

            for neighbor in sorted(adj.get(node, set())):
                if neighbor in rec_stack:
                    # Found cycle
                    idx = rec_stack.index(neighbor)
                    cycle = rec_stack[idx:] + [neighbor]
                    if len(cycle) > 2 and cycle not in cycles:
                        cycles.append(cycle)
                elif neighbor not in visited:
                    dfs(neighbor)

            rec_stack.pop()

        for n in sorted(adj.keys()):
            if n not in visited:
                dfs(n)

        return cycles[:20]  # Cap recorded cycles to 20

    def build_dependency_graph(
        self,
        parsed_files: List[ParsedFile],
        all_internal_files: Set[str],
    ) -> DependencyGraph:
        """
        Constructs a complete DependencyGraph connecting internal and external components.
        """
        nodes_dict: Dict[str, DependencyNode] = {}
        edges: List[DependencyEdge] = []
        edge_keys: Set[Tuple[str, str, str]] = set()

        total_internal = 0
        total_external = 0
        total_unresolved = 0

        # Register internal file nodes first
        for pf in parsed_files:
            nodes_dict[pf.file_path] = DependencyNode(
                id=pf.file_path,
                label=posixpath.basename(pf.file_path),
                node_type="internal_file",
                language=pf.language,
            )

        for pf in parsed_files:
            for imp in pf.imports:
                target, status, is_internal = self.resolve_import(
                    import_info=imp,
                    importing_file=pf.file_path,
                    language=pf.language,
                    all_internal_files=all_internal_files,
                )

                if not target:
                    continue

                if is_internal:
                    total_internal += 1
                    node_type = "internal_file"
                elif status == "external_package":
                    total_external += 1
                    node_type = "external_package"
                else:
                    total_unresolved += 1
                    node_type = "unresolved"

                # Ensure target node exists
                if target not in nodes_dict and len(nodes_dict) < self.max_nodes:
                    nodes_dict[target] = DependencyNode(
                        id=target,
                        label=posixpath.basename(target) if is_internal else target,
                        node_type=node_type,
                        language=pf.language if is_internal else None,
                    )

                # Add edge if not duplicate and below limits
                edge_key = (pf.file_path, target, "imports")
                if edge_key not in edge_keys and len(edges) < self.max_edges:
                    edge_keys.add(edge_key)
                    edges.append(
                        DependencyEdge(
                            source=pf.file_path,
                            target=target,
                            relationship_type="imports",
                            is_internal=is_internal,
                            resolution_status=status,
                            evidence=RelationshipEvidence(
                                evidence_type="import_statement",
                                statement=f"import {imp.module}" + (f" ({', '.join(imp.symbols)})" if imp.symbols else ""),
                                file_path=pf.file_path,
                                line_number=imp.line_number,
                                confidence="high" if is_internal else ("high" if status == "external_package" else "low"),
                            ),
                        )
                    )

        circular = self.detect_circular_dependencies(edges)

        return DependencyGraph(
            nodes=list(nodes_dict.values()),
            edges=edges,
            total_internal_dependencies=total_internal,
            total_external_dependencies=total_external,
            total_unresolved_dependencies=total_unresolved,
            circular_dependencies=circular,
        )

dependency_resolver = DependencyResolver()
