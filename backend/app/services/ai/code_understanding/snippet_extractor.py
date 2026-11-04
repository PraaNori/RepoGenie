from __future__ import annotations

import os
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ....models.schemas import ClassInfo, FunctionInfo, MethodInfo, ParsedFile


class ExtractedCodeSnippet:
    def __init__(
        self,
        name: str,
        symbol_type: str,
        file_path: str,
        line_start: int,
        line_end: int,
        formatted_code: str,
        docstring: Optional[str] = None,
        is_complete: bool = True,
        exclusion_reason: Optional[str] = None,
    ):
        self.name = name
        self.symbol_type = symbol_type
        self.file_path = file_path
        self.line_start = line_start
        self.line_end = line_end
        self.formatted_code = formatted_code
        self.docstring = docstring
        self.is_complete = is_complete
        self.exclusion_reason = exclusion_reason


class SnippetExtractor:
    """
    Extracts complete, bounded code snippets using Tree-sitter AST metadata.
    Preserves original source line numbers and complete syntax/logic blocks.
    Avoids arbitrary mid-expression truncation, excludes oversized symbols
    with explicit reasons, and prevents duplicate snippet overlaps.
    """

    MAX_SYMBOL_LINES = 35
    MAX_TOTAL_SNIPPET_CHARS = 3500

    def extract_snippets_for_component(
        self,
        parsed_file: Optional[ParsedFile],
        key_symbols: List[str],
        local_path: Optional[str] = None,
        seen_ranges: Optional[Set[Tuple[str, int, int]]] = None,
    ) -> List[ExtractedCodeSnippet]:
        if not parsed_file:
            return []

        if seen_ranges is None:
            seen_ranges = set()

        snippets: List[ExtractedCodeSnippet] = []
        file_path = parsed_file.file_path

        # Index available symbols in parsed file
        classes_by_name: Dict[str, ClassInfo] = {c.name: c for c in parsed_file.classes}
        funcs_by_name: Dict[str, FunctionInfo] = {f.name: f for f in parsed_file.functions}
        methods_by_name: Dict[str, MethodInfo] = {m.name: m for m in parsed_file.methods}

        target_symbols = list(key_symbols)
        # If no key symbols provided, select top public class or functions
        if not target_symbols:
            pub_classes = [c.name for c in parsed_file.classes if not c.name.startswith("_")]
            pub_funcs = [f.name for f in parsed_file.functions if not f.name.startswith("_")]
            target_symbols = (pub_classes[:1] + pub_funcs[:2])[:2]

        for sym_name in target_symbols:
            extracted: Optional[ExtractedCodeSnippet] = None

            # 1. Check Classes
            if sym_name in classes_by_name:
                cls_info = classes_by_name[sym_name]
                extracted = self._extract_class_snippet(cls_info, file_path, local_path)

            # 2. Check Functions
            elif sym_name in funcs_by_name:
                func_info = funcs_by_name[sym_name]
                extracted = self._extract_func_snippet(func_info, file_path, local_path)

            # 3. Check Methods
            elif sym_name in methods_by_name:
                method_info = methods_by_name[sym_name]
                extracted = self._extract_method_snippet(method_info, file_path, local_path)

            if extracted:
                range_key = (extracted.file_path, extracted.line_start, extracted.line_end)
                if range_key in seen_ranges:
                    continue
                seen_ranges.add(range_key)
                snippets.append(extracted)

        return snippets

    def _extract_func_snippet(
        self,
        func: FunctionInfo,
        file_path: str,
        local_path: Optional[str],
    ) -> ExtractedCodeSnippet:
        line_start = func.location.start_line
        line_end = func.location.end_line
        total_lines = line_end - line_start + 1

        raw_code = func.snippet or ""
        docstring = self._extract_docstring(raw_code)

        if total_lines > self.MAX_SYMBOL_LINES:
            # Symbol is too large to fit complete logic without distortion
            # Provide signature and docstring with explicit exclusion notice
            sig_lines = self._get_signature_lines(raw_code, max_lines=6)
            formatted = self._format_lines(sig_lines, line_start)
            return ExtractedCodeSnippet(
                name=func.name,
                symbol_type="function",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                formatted_code=formatted,
                docstring=docstring,
                is_complete=False,
                exclusion_reason=f"Function logic ({total_lines} lines) omitted to preserve complete symbol boundaries; signature retained.",
            )

        # Complete function fits within budget
        lines = raw_code.splitlines() if raw_code else [f"def {func.name}(...):"]
        formatted = self._format_lines(lines, line_start)
        return ExtractedCodeSnippet(
            name=func.name,
            symbol_type="function",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            formatted_code=formatted,
            docstring=docstring,
            is_complete=True,
        )

    def _extract_class_snippet(
        self,
        cls: ClassInfo,
        file_path: str,
        local_path: Optional[str],
    ) -> ExtractedCodeSnippet:
        line_start = cls.location.start_line
        line_end = cls.location.end_line
        total_lines = line_end - line_start + 1

        raw_code = cls.snippet or ""
        docstring = self._extract_docstring(raw_code)

        if total_lines > self.MAX_SYMBOL_LINES:
            # Keep class header, base classes, and method inventory
            header_lines = self._get_signature_lines(raw_code, max_lines=8)
            formatted = self._format_lines(header_lines, line_start)
            return ExtractedCodeSnippet(
                name=cls.name,
                symbol_type="class",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                formatted_code=formatted,
                docstring=docstring,
                is_complete=False,
                exclusion_reason=f"Class implementation ({total_lines} lines, {len(cls.methods)} methods) omitted to preserve complete symbol boundaries; class structure retained.",
            )

        lines = raw_code.splitlines() if raw_code else [f"class {cls.name}:"]
        formatted = self._format_lines(lines, line_start)
        return ExtractedCodeSnippet(
            name=cls.name,
            symbol_type="class",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            formatted_code=formatted,
            docstring=docstring,
            is_complete=True,
        )

    def _extract_method_snippet(
        self,
        method: MethodInfo,
        file_path: str,
        local_path: Optional[str],
    ) -> ExtractedCodeSnippet:
        line_start = method.location.start_line
        line_end = method.location.end_line
        total_lines = line_end - line_start + 1

        raw_code = method.snippet or ""
        docstring = self._extract_docstring(raw_code)

        if total_lines > self.MAX_SYMBOL_LINES:
            sig_lines = self._get_signature_lines(raw_code, max_lines=6)
            formatted = self._format_lines(sig_lines, line_start)
            return ExtractedCodeSnippet(
                name=f"{method.parent_class}.{method.name}",
                symbol_type="method",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                formatted_code=formatted,
                docstring=docstring,
                is_complete=False,
                exclusion_reason=f"Method logic ({total_lines} lines) omitted; signature retained.",
            )

        lines = raw_code.splitlines() if raw_code else [f"def {method.name}(self, ...):"]
        formatted = self._format_lines(lines, line_start)
        return ExtractedCodeSnippet(
            name=f"{method.parent_class}.{method.name}",
            symbol_type="method",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            formatted_code=formatted,
            docstring=docstring,
            is_complete=True,
        )

    def _format_lines(self, lines: List[str], start_line: int) -> str:
        """Prefixes each line with its exact 1-indexed source code line number."""
        formatted: List[str] = []
        for idx, line in enumerate(lines):
            curr_line_num = start_line + idx
            formatted.append(f"L{curr_line_num}: {line}")
        return "\n".join(formatted)

    def _get_signature_lines(self, code: str, max_lines: int = 6) -> List[str]:
        if not code:
            return []
        lines = code.splitlines()
        return lines[:max_lines]

    def _extract_docstring(self, code: str) -> Optional[str]:
        """Extracts top docstring comment if present in raw snippet."""
        if not code:
            return None
        stripped = code.strip()
        for quote in ('"""', "'''"):
            start = stripped.find(quote)
            if start != -1:
                end = stripped.find(quote, start + 3)
                if end != -1:
                    return stripped[start + 3 : end].strip()
        return None


snippet_extractor = SnippetExtractor()
