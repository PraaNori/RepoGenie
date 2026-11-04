from typing import List, Optional
import tree_sitter
import tree_sitter_python as tspython

from ....models.schemas import (
    ClassInfo,
    FunctionCallInfo,
    FunctionInfo,
    ImportInfo,
    MethodInfo,
    ParsedFile,
    ParsingWarning,
)
from .base import BaseLanguageParser

class PythonParser(BaseLanguageParser):
    """
    AST Parser for Python using Tree-sitter.
    Iterative AST traversal and byte-offset mapping for crash-proof, highly performant extraction.
    """

    def __init__(self):
        super().__init__(language_name="Python", supported_extensions=[".py", ".pyw"])

    def _init_language(self) -> Optional[tree_sitter.Language]:
        return tree_sitter.Language(tspython.language())

    def parse_file(
        self,
        content: bytes,
        rel_path: str,
        max_snippet_lines: int = 60,
        max_snippet_chars: int = 2500,
    ) -> ParsedFile:
        parser = self.get_parser()
        if not parser:
            return ParsedFile(
                file_path=rel_path,
                language=self.language_name,
                status="error",
                warnings=[
                    ParsingWarning(
                        file_path=rel_path,
                        message="Tree-sitter Python language is not initialized",
                        warning_type="init_error",
                    )
                ],
            )

        tree = parser.parse(content)
        root_node = tree.root_node

        decoded = content.decode("utf-8", errors="replace")
        lines = decoded.splitlines()
        total_lines = len(lines)
        line_starts = self.build_line_starts(content)

        warnings: List[ParsingWarning] = self.find_syntax_errors(
            root_node, rel_path, line_starts=line_starts
        )
        status = "syntax_error" if warnings else "success"

        functions: List[FunctionInfo] = []
        classes: List[ClassInfo] = []
        methods: List[MethodInfo] = []
        imports: List[ImportInfo] = []
        function_calls: List[FunctionCallInfo] = []

        def get_visibility(name: str) -> str:
            if name.startswith("__") and not name.endswith("__"):
                return "private"
            if name.startswith("_") and not name.endswith("__"):
                return "protected"
            return "public"

        def parse_fn_details(fn_node: tree_sitter.Node):
            name = "<anon>"
            params: List[str] = []
            return_type: Optional[str] = None
            is_async = False
            passed_arrow = False
            body_node: Optional[tree_sitter.Node] = None

            for c in fn_node.children:
                if c.type == "async":
                    is_async = True
                elif c.type == "identifier" and name == "<anon>":
                    name = c.text.decode("utf-8", errors="replace")
                elif c.type == "parameters":
                    for p in c.children:
                        if p.type not in ("(", ")", ","):
                            params.append(p.text.decode("utf-8", errors="replace"))
                elif c.type == "->":
                    passed_arrow = True
                elif passed_arrow and c.type not in (":", "block"):
                    return_type = c.text.decode("utf-8", errors="replace")
                    passed_arrow = False
                elif c.type == "block":
                    body_node = c

            return name, params, return_type, is_async, body_node

        def parse_cls_details(cls_node: tree_sitter.Node):
            name = "<anon>"
            base_classes: List[str] = []
            body_node: Optional[tree_sitter.Node] = None

            for c in cls_node.children:
                if c.type == "identifier" and name == "<anon>":
                    name = c.text.decode("utf-8", errors="replace")
                elif c.type == "argument_list":
                    for sc in c.children:
                        if sc.type not in ("(", ")", ","):
                            base_classes.append(sc.text.decode("utf-8", errors="replace"))
                elif c.type == "block":
                    body_node = c

            return name, base_classes, body_node

        # Iterative stack traversal: (node, current_scope, parent_class)
        stack = [(root_node, None, None)]

        while stack:
            node, current_scope, parent_class = stack.pop()

            # Imports: import os
            if node.type == "import_statement":
                line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                for c in node.children:
                    if c.type == "dotted_name":
                        imports.append(
                            ImportInfo(
                                module=c.text.decode("utf-8", errors="replace"),
                                symbols=[],
                                alias=None,
                                file_path=rel_path,
                                line_number=line,
                            )
                        )
                    elif c.type == "aliased_import":
                        raw = c.text.decode("utf-8", errors="replace")
                        parts = raw.split(" as ")
                        imports.append(
                            ImportInfo(
                                module=parts[0].strip(),
                                symbols=[],
                                alias=parts[1].strip() if len(parts) > 1 else None,
                                file_path=rel_path,
                                line_number=line,
                            )
                        )
                continue

            # Imports: from sys import argv
            if node.type == "import_from_statement":
                line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                module_name = ""
                symbols: List[str] = []
                passed_import = False
                for c in node.children:
                    if c.type in ("relative_import", "dotted_name") and not passed_import:
                        module_name = c.text.decode("utf-8", errors="replace")
                    elif c.text.decode("utf-8", errors="replace") == "import":
                        passed_import = True
                    elif passed_import and c.type not in (",", ";"):
                        symbols.append(c.text.decode("utf-8", errors="replace"))

                imports.append(
                    ImportInfo(
                        module=module_name,
                        symbols=symbols,
                        alias=None,
                        file_path=rel_path,
                        line_number=line,
                    )
                )
                continue

            # Calls
            if node.type == "call":
                if node.children:
                    call_name = node.children[0].text.decode("utf-8", errors="replace")
                    line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                    function_calls.append(
                        FunctionCallInfo(
                            call_name=call_name,
                            enclosing_scope=current_scope,
                            file_path=rel_path,
                            line_number=line,
                        )
                    )

            # Unwrap decorated definition
            actual_node = node
            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type in ("function_definition", "class_definition"):
                        actual_node = child
                        break

            # Class definition
            if actual_node.type == "class_definition":
                cls_name, base_classes, body = parse_cls_details(actual_node)
                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )

                class_methods: List[str] = []
                nested_classes: List[str] = []

                if body:
                    for member in body.children:
                        m_actual = member
                        if member.type == "decorated_definition":
                            for dc in member.children:
                                if dc.type in ("function_definition", "class_definition"):
                                    m_actual = dc
                                    break
                        if m_actual.type == "function_definition":
                            for c in m_actual.children:
                                if c.type == "identifier":
                                    class_methods.append(c.text.decode("utf-8", errors="replace"))
                                    break
                        elif m_actual.type == "class_definition":
                            for c in m_actual.children:
                                if c.type == "identifier":
                                    nested_classes.append(c.text.decode("utf-8", errors="replace"))
                                    break

                    for member in reversed(body.children):
                        stack.append((member, cls_name, cls_name))

                classes.append(
                    ClassInfo(
                        name=cls_name,
                        file_path=rel_path,
                        location=loc,
                        base_classes=base_classes,
                        methods=class_methods,
                        nested_classes=nested_classes,
                        snippet=snippet,
                    )
                )
                continue

            # Function or Method definition
            if actual_node.type == "function_definition":
                fn_name, params, return_type, is_async, body = parse_fn_details(actual_node)
                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )

                if parent_class:
                    methods.append(
                        MethodInfo(
                            name=fn_name,
                            parent_class=parent_class,
                            file_path=rel_path,
                            location=loc,
                            parameters=params,
                            is_async=is_async,
                            visibility=get_visibility(fn_name),
                            return_type=return_type,
                            snippet=snippet,
                        )
                    )
                    scope_for_body = f"{parent_class}.{fn_name}"
                else:
                    functions.append(
                        FunctionInfo(
                            name=fn_name,
                            file_path=rel_path,
                            location=loc,
                            parameters=params,
                            is_async=is_async,
                            visibility=get_visibility(fn_name),
                            return_type=return_type,
                            enclosing_scope=current_scope,
                            snippet=snippet,
                        )
                    )
                    scope_for_body = fn_name

                if body:
                    for child in reversed(body.children):
                        stack.append((child, scope_for_body, None))
                continue

            for child in reversed(node.children):
                stack.append((child, current_scope, parent_class))

        return ParsedFile(
            file_path=rel_path,
            language=self.language_name,
            status=status,
            functions=functions,
            classes=classes,
            methods=methods,
            imports=imports,
            function_calls=function_calls,
            warnings=warnings,
            total_lines=total_lines,
        )
