from typing import List, Optional
import tree_sitter
import tree_sitter_java as tsjava

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

class JavaParser(BaseLanguageParser):
    """
    AST Parser for Java using Tree-sitter.
    Iterative AST traversal and byte-offset mapping.
    """

    def __init__(self):
        super().__init__(language_name="Java", supported_extensions=[".java"])

    def _init_language(self) -> Optional[tree_sitter.Language]:
        return tree_sitter.Language(tsjava.language())

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
                        message="Tree-sitter Java language is not initialized",
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

        def get_java_visibility(node: tree_sitter.Node) -> str:
            for c in node.children:
                if c.type == "modifiers":
                    for mod in c.children:
                        m_text = mod.text.decode("utf-8", errors="replace")
                        if m_text in ("public", "protected", "private"):
                            return m_text
            return "package-private"

        def extract_parameters(param_node: Optional[tree_sitter.Node]) -> List[str]:
            if not param_node:
                return []
            params = []
            for child in param_node.children:
                if child.type in ("formal_parameter", "spread_parameter"):
                    params.append(child.text.decode("utf-8", errors="replace"))
            return params

        stack = [(root_node, None)]
        while stack:
            node, current_scope = stack.pop()

            if node.type == "import_declaration":
                line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                raw = node.text.decode("utf-8", errors="replace")
                cleaned = raw.replace("import ", "").replace("static ", "").rstrip(";").strip()
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

            if node.type == "method_invocation":
                name_n = node.child_by_field_name("name")
                obj_n = node.child_by_field_name("object")
                call_name = ""
                if obj_n and name_n:
                    call_name = f"{obj_n.text.decode('utf-8', errors='replace')}.{name_n.text.decode('utf-8', errors='replace')}"
                elif name_n:
                    call_name = name_n.text.decode("utf-8", errors="replace")

                if call_name:
                    line, _ = self.byte_to_line_col(line_starts, node.start_byte)
                    function_calls.append(
                        FunctionCallInfo(
                            call_name=call_name,
                            enclosing_scope=current_scope,
                            file_path=rel_path,
                            line_number=line,
                        )
                    )

            if node.type in ("class_declaration", "interface_declaration", "record_declaration", "enum_declaration"):
                name_n = node.child_by_field_name("name")
                cls_name = name_n.text.decode("utf-8", errors="replace") if name_n else "<anon>"

                base_classes: List[str] = []
                super_n = node.child_by_field_name("superclass")
                if super_n:
                    clean_super = super_n.text.decode("utf-8", errors="replace").replace("extends ", "").strip()
                    base_classes.append(clean_super)

                ifaces_n = node.child_by_field_name("interfaces")
                if ifaces_n:
                    clean_ifaces = ifaces_n.text.decode("utf-8", errors="replace").replace("implements ", "").split(",")
                    for iface in clean_ifaces:
                        if iface.strip():
                            base_classes.append(iface.strip())

                loc = self.make_source_location(rel_path, node, line_starts=line_starts)
                snippet = self.extract_snippet(
                    lines, loc.start_line, loc.end_line, max_snippet_lines, max_snippet_chars
                )

                class_methods: List[str] = []
                nested_classes: List[str] = []

                body = node.child_by_field_name("body")
                if body:
                    for member in body.children:
                        if member.type in ("method_declaration", "constructor_declaration"):
                            m_name_n = member.child_by_field_name("name")
                            m_name = m_name_n.text.decode("utf-8", errors="replace") if m_name_n else "<anon>"
                            ret_n = member.child_by_field_name("type")
                            ret_type = ret_n.text.decode("utf-8", errors="replace") if ret_n else None
                            params = extract_parameters(member.child_by_field_name("parameters"))
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
                                visibility=get_java_visibility(member),
                                return_type=ret_type,
                                snippet=m_snippet,
                            )
                            methods.append(m_info)
                            class_methods.append(m_name)

                            m_body = member.child_by_field_name("body")
                            if m_body:
                                for c in reversed(m_body.children):
                                    stack.append((c, f"{cls_name}.{m_name}"))
                        elif member.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                            n_name_n = member.child_by_field_name("name")
                            if n_name_n:
                                nested_classes.append(n_name_n.text.decode("utf-8", errors="replace"))
                            stack.append((member, cls_name))
                        else:
                            stack.append((member, cls_name))

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
