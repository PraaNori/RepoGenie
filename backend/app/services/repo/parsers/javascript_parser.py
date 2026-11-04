from typing import List, Optional
import tree_sitter
import tree_sitter_javascript as tsjs

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

class JavaScriptParser(BaseLanguageParser):
    """
    AST Parser for JavaScript (JSX, and Google Apps Script) using Tree-sitter.
    Extracts functions, arrow functions, classes, methods, inheritance, parameters,
    imports (ESM and CommonJS require), and function calls.
    """

    def __init__(self, language_name: str = "JavaScript", supported_extensions: Optional[List[str]] = None):
        if supported_extensions is None:
            supported_extensions = [".js", ".jsx", ".mjs", ".cjs", ".gs"]
        super().__init__(language_name=language_name, supported_extensions=supported_extensions)

    def _init_language(self) -> Optional[tree_sitter.Language]:
        return tree_sitter.Language(tsjs.language())

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
                        message="Tree-sitter JavaScript language is not initialized",
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

        def extract_parameters(param_node: Optional[tree_sitter.Node]) -> List[str]:
            if not param_node:
                return []
            params = []
            for child in param_node.children:
                if child.type in (
                    "identifier",
                    "formal_parameters",
                    "rest_pattern",
                    "assignment_pattern",
                    "object_pattern",
                    "array_pattern",
                ):
                    params.append(child.text.decode("utf-8", errors="replace"))
            return params

        def extract_function(
            fn_node: tree_sitter.Node,
            name: Optional[str] = None,
            enclosing: Optional[str] = None,
            is_exported: bool = False,
        ) -> FunctionInfo:
            if not name:
                name_node = fn_node.child_by_field_name("name")
                name = name_node.text.decode("utf-8", errors="replace") if name_node else "<anonymous>"

            is_async = any(c.type == "async" for c in fn_node.children)
            params = extract_parameters(fn_node.child_by_field_name("parameters"))

            ret_node = fn_node.child_by_field_name("return_type")
            return_type = ret_node.text.decode("utf-8", errors="replace") if ret_node else None

            loc = self.make_source_location(rel_path, fn_node, line_starts=line_starts)
            snippet = self.extract_snippet(
                lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
            )

            return FunctionInfo(
                name=name,
                file_path=rel_path,
                location=loc,
                parameters=params,
                is_async=is_async,
                visibility="public" if is_exported else None,
                return_type=return_type,
                enclosing_scope=enclosing,
                snippet=snippet,
            )

        def extract_method(m_node: tree_sitter.Node, parent_class: str) -> MethodInfo:
            name_node = m_node.child_by_field_name("name")
            m_name = name_node.text.decode("utf-8", errors="replace") if name_node else "<anonymous>"
            is_async = any(c.type == "async" for c in m_node.children)

            params = extract_parameters(m_node.child_by_field_name("parameters"))
            ret_node = m_node.child_by_field_name("return_type")
            return_type = ret_node.text.decode("utf-8", errors="replace") if ret_node else None

            visibility = "private" if m_name.startswith("#") else "public"
            for c in m_node.children:
                if c.type == "accessibility_modifier":
                    visibility = c.text.decode("utf-8", errors="replace")
                    break

            loc = self.make_source_location(rel_path, m_node, line_starts=line_starts)
            snippet = self.extract_snippet(
                lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
            )

            return MethodInfo(
                name=m_name,
                parent_class=parent_class,
                file_path=rel_path,
                location=loc,
                parameters=params,
                is_async=is_async,
                visibility=visibility,
                return_type=return_type,
                snippet=snippet,
            )

        def parse_esm_import(node: tree_sitter.Node):
            line, _ = self.byte_to_line_col(line_starts, node.start_byte)
            source_node = node.child_by_field_name("source")
            module_name = ""
            if source_node:
                raw = source_node.text.decode("utf-8", errors="replace")
                module_name = raw.strip("\"'")

            symbols: List[str] = []
            for c in node.children:
                if c.type == "import_clause":
                    for sub in c.children:
                        if sub.type == "identifier":
                            symbols.append(sub.text.decode("utf-8", errors="replace"))
                        elif sub.type == "named_imports":
                            for spec in sub.children:
                                if spec.type == "import_specifier":
                                    s_name = spec.child_by_field_name("name")
                                    s_alias = spec.child_by_field_name("alias")
                                    name_str = s_name.text.decode("utf-8", errors="replace") if s_name else ""
                                    if s_alias:
                                        alias_str = s_alias.text.decode("utf-8", errors="replace")
                                        symbols.append(f"{name_str} as {alias_str}")
                                    elif name_str:
                                        symbols.append(name_str)
                        elif sub.type == "namespace_import":
                            symbols.append(sub.text.decode("utf-8", errors="replace"))

            imports.append(
                ImportInfo(
                    module=module_name,
                    symbols=symbols,
                    alias=None,
                    file_path=rel_path,
                    line_number=line,
                )
            )

        # Iterative stack traversal: (node, current_scope)
        stack = [(root_node, None)]
        while stack:
            node, current_scope = stack.pop()

            if node.type == "import_statement":
                parse_esm_import(node)
                continue

            if node.type == "call_expression":
                fn_field = node.child_by_field_name("function")
                if fn_field:
                    call_name = fn_field.text.decode("utf-8", errors="replace")
                    line, _ = self.byte_to_line_col(line_starts, node.start_byte)

                    if call_name == "require":
                        args = node.child_by_field_name("arguments")
                        if args and args.children:
                            for arg in args.children:
                                if arg.type == "string":
                                    mod_str = arg.text.decode("utf-8", errors="replace").strip("\"'")
                                    imports.append(
                                        ImportInfo(
                                            module=mod_str,
                                            symbols=[],
                                            alias=None,
                                            file_path=rel_path,
                                            line_number=line,
                                        )
                                    )
                                    break
                    else:
                        function_calls.append(
                            FunctionCallInfo(
                                call_name=call_name,
                                enclosing_scope=current_scope,
                                file_path=rel_path,
                                line_number=line,
                            )
                        )

            is_exported = False
            actual_node = node
            if node.type in ("export_statement", "export_default_declaration"):
                is_exported = True
                for c in node.children:
                    if c.type in (
                        "function_declaration",
                        "class_declaration",
                        "lexical_declaration",
                        "variable_declaration",
                    ):
                        actual_node = c
                        break

            if actual_node.type == "function_declaration":
                fn_info = extract_function(
                    actual_node,
                    enclosing=current_scope,
                    is_exported=is_exported,
                )
                functions.append(fn_info)
                body = actual_node.child_by_field_name("body")
                if body:
                    for child in reversed(body.children):
                        stack.append((child, fn_info.name))
                continue

            if actual_node.type in ("lexical_declaration", "variable_declaration"):
                for decl in actual_node.children:
                    if decl.type == "variable_declarator":
                        name_node = decl.child_by_field_name("name")
                        val_node = decl.child_by_field_name("value")
                        if name_node and val_node and val_node.type in ("arrow_function", "function_expression"):
                            var_name = name_node.text.decode("utf-8", errors="replace")
                            fn_info = extract_function(
                                val_node,
                                name=var_name,
                                enclosing=current_scope,
                                is_exported=is_exported,
                            )
                            functions.append(fn_info)
                            body = val_node.child_by_field_name("body")
                            if body:
                                for child in reversed(body.children):
                                    stack.append((child, var_name))
                            continue
                for child in reversed(actual_node.children):
                    stack.append((child, current_scope))
                continue

            if actual_node.type == "class_declaration":
                cls_name_node = actual_node.child_by_field_name("name")
                cls_name = (
                    cls_name_node.text.decode("utf-8", errors="replace")
                    if cls_name_node
                    else "<anonymous>"
                )

                base_classes: List[str] = []
                for c in actual_node.children:
                    if c.type == "class_heritage":
                        for clause in c.children:
                            if clause.type in ("extends_clause", "implements_clause"):
                                for hc in clause.children:
                                    if hc.type in ("identifier", "member_expression"):
                                        base_classes.append(hc.text.decode("utf-8", errors="replace"))
                            elif clause.type in ("identifier", "member_expression"):
                                base_classes.append(clause.text.decode("utf-8", errors="replace"))
                    elif c.type in ("extends_clause", "implements_clause"):
                        for hc in c.children:
                            if hc.type in ("identifier", "member_expression"):
                                base_classes.append(hc.text.decode("utf-8", errors="replace"))

                cls_loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                cls_snippet = self.extract_snippet(
                    lines,
                    cls_loc.start_line,
                    cls_loc.end_line,
                    max_snippet_lines,
                    max_snippet_chars,
                )

                class_methods: List[str] = []
                body = actual_node.child_by_field_name("body")
                if body:
                    for member in body.children:
                        if member.type == "method_definition":
                            m_info = extract_method(member, cls_name)
                            methods.append(m_info)
                            class_methods.append(m_info.name)
                            m_body = member.child_by_field_name("body")
                            if m_body:
                                for bc in reversed(m_body.children):
                                    stack.append((bc, f"{cls_name}.{m_info.name}"))
                        else:
                            stack.append((member, cls_name))

                classes.append(
                    ClassInfo(
                        name=cls_name,
                        file_path=rel_path,
                        location=cls_loc,
                        base_classes=base_classes,
                        methods=class_methods,
                        nested_classes=[],
                        snippet=cls_snippet,
                    )
                )
                continue

            for child in reversed(node.children):
                stack.append((child, current_scope))

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
