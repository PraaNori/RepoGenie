from typing import List, Optional
import tree_sitter
import tree_sitter_cpp as tscpp

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

class CppParser(BaseLanguageParser):
    """
    AST Parser for C++ (and Arduino .ino) using Tree-sitter.
    Iterative AST traversal and byte-offset mapping.
    """

    def __init__(self):
        super().__init__(
            language_name="C++",
            supported_extensions=[".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh", ".ino"],
        )

    def _init_language(self) -> Optional[tree_sitter.Language]:
        return tree_sitter.Language(tscpp.language())

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
                        message="Tree-sitter C++ language is not initialized",
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

        def unwrap_function_declarator(decl_node: Optional[tree_sitter.Node]):
            curr = decl_node
            while curr and curr.type in ("pointer_declarator", "reference_declarator", "parenthesized_declarator"):
                child_decl = curr.child_by_field_name("declarator")
                if child_decl:
                    curr = child_decl
                elif len(curr.children) > 1:
                    curr = curr.children[1]
                else:
                    break
            if curr and curr.type == "function_declarator":
                name_n = curr.child_by_field_name("declarator")
                fn_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"
                params_n = curr.child_by_field_name("parameters")
                params = []
                if params_n:
                    for p in params_n.children:
                        if p.type in ("parameter_declaration", "optional_parameter_declaration"):
                            params.append(p.text.decode("utf-8", errors="replace"))
                return fn_name, params
            return None, []

        stack = [(root_node, None)]
        while stack:
            node, current_scope = stack.pop()

            if node.type == "preproc_include":
                line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                path_n = node.child_by_field_name("path")
                inc_path = path_n.text.decode("utf-8", errors="replace").strip("<>\"'") if path_n else ""
                imports.append(
                    ImportInfo(
                        module=inc_path,
                        symbols=[],
                        alias=None,
                        file_path=rel_path,
                        line_number=line,
                    )
                )
                continue

            if node.type == "call_expression":
                fn_field = node.child_by_field_name("function")
                if fn_field:
                    call_name = fn_field.text.decode("utf-8", errors="replace")
                    line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                    function_calls.append(
                        FunctionCallInfo(
                            call_name=call_name,
                            enclosing_scope=current_scope,
                            file_path=rel_path,
                            line_number=line,
                        )
                    )

            if node.type in ("class_specifier", "struct_specifier"):
                name_n = node.child_by_field_name("name")
                cls_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"

                base_classes: List[str] = []
                for c in node.children:
                    if c.type == "base_class_clause":
                        for bc in c.children:
                            if bc.type in ("type_identifier", "qualified_identifier", "identifier"):
                                base_classes.append(bc.text.decode("utf-8", errors="replace"))

                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )

                class_methods: List[str] = []
                body = node.child_by_field_name("body")
                current_access = "private" if node.type == "class_specifier" else "public"

                if body:
                    for member in body.children:
                        if member.type == "access_specifier":
                            for ac in member.children:
                                a_text = ac.text.decode("utf-8", errors="replace")
                                if a_text in ("public", "protected", "private"):
                                    current_access = a_text
                        elif member.type == "function_definition":
                            ret_n = member.child_by_field_name("type")
                            ret_type = ret_n.text.decode("utf-8", errors="replace") if ret_n else None
                            decl_n = member.child_by_field_name("declarator")
                            m_name, params = unwrap_function_declarator(decl_n)
                            if not m_name:
                                m_name = decl_n.text.decode("utf-8", errors="replace").split("(")[0] if decl_n else "<anon>"

                            m_loc = self.make_source_location(rel_path, member, line_starts=line_starts)
                            m_snippet = self.extract_snippet(
                                lines, m_loc.start_line, m_loc.end_line, max_snippet_lines, max_snippet_chars
                            )

                            m_info = MethodInfo(
                                name=m_name,
                                parent_class=cls_name,
                                file_path=rel_path,
                                location=m_loc,
                                parameters=params,
                                is_async=False,
                                visibility=current_access,
                                return_type=ret_type,
                                snippet=m_snippet,
                            )
                            methods.append(m_info)
                            class_methods.append(m_name)

                            m_body = member.child_by_field_name("body")
                            if m_body:
                                for c in reversed(m_body.children):
                                    stack.append((c, f"{cls_name}.{m_name}"))
                        else:
                            stack.append((member, cls_name))

                classes.append(
                    ClassInfo(
                        name=cls_name,
                        file_path=rel_path,
                        location=loc,
                        base_classes=base_classes,
                        methods=class_methods,
                        nested_classes=[],
                        snippet=snippet,
                    )
                )
                continue

            if node.type == "function_definition":
                ret_n = node.child_by_field_name("type")
                ret_type = ret_n.text.decode("utf-8", errors="replace") if ret_n else None
                decl_n = node.child_by_field_name("declarator")
                fn_name, params = unwrap_function_declarator(decl_n)

                if fn_name:
                    loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                    snippet = self.extract_snippet(
                        lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                    )

                    fn_info = FunctionInfo(
                        name=fn_name,
                        file_path=rel_path,
                        location=loc,
                        parameters=params,
                        is_async=False,
                        visibility="public",
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
