from typing import List, Optional
import tree_sitter
import tree_sitter_go as tsgo

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

class GoParser(BaseLanguageParser):
    """
    AST Parser for Go using Tree-sitter.
    Iterative AST traversal and byte-offset mapping.
    """

    def __init__(self):
        super().__init__(language_name="Go", supported_extensions=[".go"])

    def _init_language(self) -> Optional[tree_sitter.Language]:
        return tree_sitter.Language(tsgo.language())

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
                        message="Tree-sitter Go language is not initialized",
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

        def get_go_visibility(name: str) -> str:
            if name and name[0].isupper():
                return "public"
            return "private"

        def extract_parameters(param_node: Optional[tree_sitter.Node]) -> List[str]:
            if not param_node:
                return []
            params = []
            for child in param_node.children:
                if child.type == "parameter_declaration":
                    params.append(child.text.decode("utf-8", errors="replace"))
            return params

        def extract_receiver_type(recv_node: Optional[tree_sitter.Node]) -> str:
            if not recv_node:
                return "<unknown>"
            for child in recv_node.children:
                if child.type == "parameter_declaration":
                    typ_node = child.child_by_field_name("type")
                    if typ_node:
                        return typ_node.text.decode("utf-8", errors="replace").lstrip("*")
            raw = recv_node.text.decode("utf-8", errors="replace").strip("()")
            parts = raw.split()
            return parts[-1].lstrip("*") if parts else "<unknown>"

        stack = [(root_node, None)]
        while stack:
            node, current_scope = stack.pop()

            if node.type == "import_declaration":
                specs = []
                for c in node.children:
                    if c.type == "import_spec":
                        specs.append(c)
                    elif c.type == "import_spec_list":
                        for sc in c.children:
                            if sc.type == "import_spec":
                                specs.append(sc)
                for c in specs:
                    path_n = c.child_by_field_name("path")
                    name_n = c.child_by_field_name("name")
                    if path_n:
                        mod_name = path_n.text.decode("utf-8", errors="replace").strip("\"'")
                        alias = name_n.text.decode("utf-8", errors="replace") if name_n else None
                        line, _ = self.byte_to_line_col(line_starts, c.start_byte)
                        imports.append(
                            ImportInfo(
                                module=mod_name,
                                symbols=[],
                                alias=alias,
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

            if node.type == "type_declaration":
                for spec in node.children:
                    if spec.type == "type_spec":
                        name_n = spec.child_by_field_name("name")
                        typ_n = spec.child_by_field_name("type")
                        t_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"
                        loc = self.make_source_location(rel_path, spec, line_starts=line_starts)
                        snippet = self.extract_snippet(
                            lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                        )
                        base_types: List[str] = []
                        if typ_n and typ_n.type == "struct_type":
                            field_list = typ_n.child_by_field_name("fields")
                            if field_list:
                                for f in field_list.children:
                                    if f.type == "field_declaration" and not f.child_by_field_name("name"):
                                        emb_type = f.child_by_field_name("type")
                                        if emb_type:
                                            base_types.append(emb_type.text.decode("utf-8", errors="replace"))

                        classes.append(
                            ClassInfo(
                                name=t_name,
                                file_path=rel_path,
                                location=loc,
                                base_classes=base_types,
                                methods=[],
                                nested_classes=[],
                                snippet=snippet,
                            )
                        )
                continue

            if node.type == "method_declaration":
                name_n = node.child_by_field_name("name")
                m_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"
                parent_class = extract_receiver_type(node.child_by_field_name("receiver"))
                res_n = node.child_by_field_name("result")
                ret_type = res_n.text.decode("utf-8", errors="replace") if res_n else None
                params = extract_parameters(node.child_by_field_name("parameters"))
                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )

                m_info = MethodInfo(
                    name=m_name,
                    parent_class=parent_class,
                    file_path=rel_path,
                    location=loc,
                    parameters=params,
                    is_async=False,
                    visibility=get_go_visibility(m_name),
                    return_type=ret_type,
                    snippet=snippet,
                )
                methods.append(m_info)

                for cls in classes:
                    if cls.name == parent_class and m_name not in cls.methods:
                        cls.methods.append(m_name)

                body = node.child_by_field_name("body")
                if body:
                    for c in reversed(body.children):
                        stack.append((c, f"{parent_class}.{m_name}"))
                continue

            if node.type == "function_declaration":
                name_n = node.child_by_field_name("name")
                fn_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"
                res_n = node.child_by_field_name("result")
                ret_type = res_n.text.decode("utf-8", errors="replace") if res_n else None
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
                    is_async=False,
                    visibility=get_go_visibility(fn_name),
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
