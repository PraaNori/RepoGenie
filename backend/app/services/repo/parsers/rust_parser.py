from typing import List, Optional
import tree_sitter
import tree_sitter_rust as tsrust

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

class RustParser(BaseLanguageParser):
    """
    AST Parser for Rust using Tree-sitter.
    Iterative AST traversal and byte-offset mapping.
    """

    def __init__(self):
        super().__init__(language_name="Rust", supported_extensions=[".rs"])

    def _init_language(self) -> Optional[tree_sitter.Language]:
        return tree_sitter.Language(tsrust.language())

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
                        message="Tree-sitter Rust language is not initialized",
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
                if child.type in ("parameter", "self_parameter"):
                    params.append(child.text.decode("utf-8", errors="replace"))
            return params

        def get_rust_visibility(node: tree_sitter.Node) -> str:
            for c in node.children:
                if c.type == "visibility_modifier":
                    return c.text.decode("utf-8", errors="replace")
            return "private"

        def is_async_function(node: tree_sitter.Node) -> bool:
            for c in node.children:
                if c.type == "function_modifiers" and "async" in c.text.decode("utf-8", errors="replace"):
                    return True
                if c.type == "async":
                    return True
            return False

        stack = [(root_node, None)]
        while stack:
            node, current_scope = stack.pop()

            if node.type == "use_declaration":
                line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                raw = node.text.decode("utf-8", errors="replace")
                cleaned = raw.replace("use ", "").rstrip(";").strip()
                imports.append(
                    ImportInfo(
                        module=cleaned,
                        symbols=[],
                        alias=None,
                        file_path=rel_path,
                        line_number=line,
                    )
                )
                continue

            if node.type in ("call_expression", "macro_invocation"):
                line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                call_name = ""
                if node.type == "call_expression":
                    fn_f = node.child_by_field_name("function")
                    call_name = fn_f.text.decode("utf-8", errors="replace") if fn_f else ""
                else:
                    macro_f = node.child_by_field_name("macro")
                    call_name = (macro_f.text.decode("utf-8", errors="replace") + "!") if macro_f else "macro!"

                if call_name:
                    function_calls.append(
                        FunctionCallInfo(
                            call_name=call_name,
                            enclosing_scope=current_scope,
                            file_path=rel_path,
                            line_number=line,
                        )
                    )

            if node.type in ("struct_item", "trait_item", "enum_item"):
                name_n = node.child_by_field_name("name")
                name_str = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"
                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )
                classes.append(
                    ClassInfo(
                        name=name_str,
                        file_path=rel_path,
                        location=loc,
                        base_classes=[],
                        methods=[],
                        nested_classes=[],
                        snippet=snippet,
                    )
                )
                continue

            if node.type == "impl_item":
                typ_n = node.child_by_field_name("type")
                trait_n = node.child_by_field_name("trait")
                parent_type = typ_n.text.decode("utf-8", errors="replace") if typ_n else "<unknown>"
                trait_str = trait_n.text.decode("utf-8", errors="replace") if trait_n else None

                if trait_str:
                    for cls in classes:
                        if cls.name == parent_type and trait_str not in cls.base_classes:
                            cls.base_classes.append(trait_str)

                body = node.child_by_field_name("body")
                if body:
                    for m in body.children:
                        if m.type == "function_item":
                            m_name_n = m.child_by_field_name("name")
                            m_name = m_name_n.text.decode("utf-8", errors="replace") if m_name_n else "<anon>"
                            ret_n = m.child_by_field_name("return_type")
                            ret_type = ret_n.text.decode("utf-8", errors="replace") if ret_n else None
                            params = extract_parameters(m.child_by_field_name("parameters"))
                            loc = self.make_source_location(rel_path, m, line_starts=line_starts)
                            snippet = self.extract_snippet(
                                lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                            )

                            m_info = MethodInfo(
                                name=m_name,
                                parent_class=parent_type,
                                file_path=rel_path,
                                location=loc,
                                parameters=params,
                                is_async=is_async_function(m),
                                visibility=get_rust_visibility(m),
                                return_type=ret_type,
                                snippet=snippet,
                            )
                            methods.append(m_info)

                            m_body = m.child_by_field_name("body")
                            if m_body:
                                for c in reversed(m_body.children):
                                    stack.append((c, f"{parent_type}.{m_name}"))
                continue

            if node.type == "function_item":
                name_n = node.child_by_field_name("name")
                fn_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"
                ret_n = node.child_by_field_name("return_type")
                ret_type = ret_n.text.decode("utf-8", errors="replace") if ret_n else None
                params = extract_parameters(node.child_by_field_name("parameters"))
                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )

                fn_info = FunctionInfo(
                    name=fn_name,
                    file_path=rel_path,
                    location=loc,
                    parameters=params,
                    is_async=is_async_function(node),
                    visibility=get_rust_visibility(node),
                    return_type=ret_type,
                    enclosing_scope=current_scope,
                    snippet=snippet,
                )
                functions.append(fn_info)

                body = node.child_by_field_name("body")
                if body:
                    for c in reversed(body.children):
                        stack.append((c, fn_name))
                continue

            for child in reversed(node.children):
                stack.append((child, current_scope))

        class_dict = {c.name: c for c in classes}
        for m in methods:
            if m.parent_class in class_dict and m.name not in class_dict[m.parent_class].methods:
                class_dict[m.parent_class].methods.append(m.name)

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
