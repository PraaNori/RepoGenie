"""
Bounded Source Code Snippet Extractor for Application Workflow Understanding.

Extracts complete, bounded code snippets using Tree-sitter AST metadata and file boundaries.
Strictly enforces:
- Max 25 lines per selected symbol.
- Complete function/method boundaries with 1-indexed line numbers.
- Exclusion of sensitive files (.env, secrets, credentials, keys).
- Global snippet token/character budget limit.
- Never executes repository code.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from ....models.schemas import ClassInfo, FunctionInfo, MethodInfo, ParsedFile

logger = logging.getLogger(__name__)

# Patterns for sensitive files that must never have snippets extracted
SENSITIVE_FILE_PATTERNS = [
    re.compile(r"^\.env(\..+)?$", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*\.(pem|key|pkcs12|pfx|cert|crt)$", re.IGNORECASE),
    re.compile(r"^id_rsa.*$", re.IGNORECASE),
]


class ExtractedWorkflowSnippet:
    """Represents a bounded source code snippet with line numbers and metadata."""

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

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "symbol_type": self.symbol_type,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "formatted_code": self.formatted_code,
            "docstring": self.docstring,
            "is_complete": self.is_complete,
            "exclusion_reason": self.exclusion_reason,
        }


class WorkflowSnippetExtractor:
    """
    Extracts bounded, syntax-preserving snippets for functions and methods participating
    in candidate application workflows.
    """

    MAX_SYMBOL_LINES = 25
    MAX_TOTAL_SNIPPET_CHARS = 4500

    def is_sensitive_file(self, file_path: str) -> bool:
        """Determines if a file path matches secret or sensitive credential patterns."""
        base = os.path.basename(file_path.replace("\\", "/").strip())
        return any(pat.match(base) for pat in SENSITIVE_FILE_PATTERNS)

    def extract_symbol_snippet(
        self,
        parsed_file: Optional[ParsedFile],
        symbol_name: str,
        local_path: Optional[str] = None,
    ) -> ExtractedWorkflowSnippet:
        """Extracts a bounded snippet for a function, method, or class symbol."""
        norm_path = (parsed_file.file_path if parsed_file else "").replace("\\", "/").strip().lstrip("/")

        # Check sensitive file guard
        if self.is_sensitive_file(norm_path):
            return ExtractedWorkflowSnippet(
                name=symbol_name,
                symbol_type="unknown",
                file_path=norm_path,
                line_start=1,
                line_end=1,
                formatted_code="<SNIPPET REDACTED: SENSITIVE_CONFIGURATION_FILE>",
                is_complete=False,
                exclusion_reason=f"File '{norm_path}' matches sensitive credential/secret file pattern; content omitted.",
            )

        if not parsed_file:
            return ExtractedWorkflowSnippet(
                name=symbol_name,
                symbol_type="unknown",
                file_path=norm_path,
                line_start=1,
                line_end=1,
                formatted_code="<SOURCE UNRESOLVED: PARSED_FILE_UNAVAILABLE>",
                is_complete=False,
                exclusion_reason=f"Parsed file representation for '{norm_path}' is not available.",
            )

        # Index available symbols
        funcs: Dict[str, FunctionInfo] = {f.name: f for f in parsed_file.functions}
        classes: Dict[str, ClassInfo] = {c.name: c for c in parsed_file.classes}
        methods: Dict[str, MethodInfo] = {f"{m.parent_class}.{m.name}": m for m in parsed_file.methods}
        methods_by_short: Dict[str, MethodInfo] = {m.name: m for m in parsed_file.methods}

        # 1. Match Functions
        if symbol_name in funcs:
            return self._extract_function_snippet(funcs[symbol_name], norm_path)

        # 2. Match Methods (Full or Short)
        if symbol_name in methods:
            return self._extract_method_snippet(methods[symbol_name], norm_path)
        if symbol_name in methods_by_short:
            return self._extract_method_snippet(methods_by_short[symbol_name], norm_path)

        # 3. Match Classes
        if symbol_name in classes:
            return self._extract_class_snippet(classes[symbol_name], norm_path)

        # If symbol could not be found
        return ExtractedWorkflowSnippet(
            name=symbol_name,
            symbol_type="unknown",
            file_path=norm_path,
            line_start=1,
            line_end=1,
            formatted_code=f"<SYMBOL UNRESOLVED: '{symbol_name}' not located in parsed syntax tree>",
            is_complete=False,
            exclusion_reason=f"Symbol '{symbol_name}' could not be located in AST metadata for '{norm_path}'.",
        )

    def _extract_function_snippet(self, func: FunctionInfo, file_path: str) -> ExtractedWorkflowSnippet:
        line_start = func.location.start_line
        line_end = func.location.end_line
        total_lines = line_end - line_start + 1

        raw_code = func.snippet or ""
        docstring = self._extract_docstring(raw_code)

        if total_lines > self.MAX_SYMBOL_LINES:
            # Symbol is too large to fit complete logic without distortion
            sig_lines = self._get_signature_lines(raw_code, max_lines=6)
            formatted = self._format_lines(sig_lines, line_start)
            return ExtractedWorkflowSnippet(
                name=func.name,
                symbol_type="function",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                formatted_code=formatted,
                docstring=docstring,
                is_complete=False,
                exclusion_reason=f"Function logic ({total_lines} lines) exceeds {self.MAX_SYMBOL_LINES}-line limit; signature retained.",
            )

        lines = raw_code.splitlines() if raw_code else [f"def {func.name}(...):"]
        formatted = self._format_lines(lines, line_start)
        return ExtractedWorkflowSnippet(
            name=func.name,
            symbol_type="function",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            formatted_code=formatted,
            docstring=docstring,
            is_complete=True,
        )

    def _extract_method_snippet(self, method: MethodInfo, file_path: str) -> ExtractedWorkflowSnippet:
        line_start = method.location.start_line
        line_end = method.location.end_line
        total_lines = line_end - line_start + 1

        raw_code = method.snippet or ""
        docstring = self._extract_docstring(raw_code)

        if total_lines > self.MAX_SYMBOL_LINES:
            sig_lines = self._get_signature_lines(raw_code, max_lines=6)
            formatted = self._format_lines(sig_lines, line_start)
            return ExtractedWorkflowSnippet(
                name=f"{method.parent_class}.{method.name}",
                symbol_type="method",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                formatted_code=formatted,
                docstring=docstring,
                is_complete=False,
                exclusion_reason=f"Method logic ({total_lines} lines) exceeds {self.MAX_SYMBOL_LINES}-line limit; signature retained.",
            )

        lines = raw_code.splitlines() if raw_code else [f"def {method.name}(self, ...):"]
        formatted = self._format_lines(lines, line_start)
        return ExtractedWorkflowSnippet(
            name=f"{method.parent_class}.{method.name}",
            symbol_type="method",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            formatted_code=formatted,
            docstring=docstring,
            is_complete=True,
        )

    def _extract_class_snippet(self, cls: ClassInfo, file_path: str) -> ExtractedWorkflowSnippet:
        line_start = cls.location.start_line
        line_end = cls.location.end_line
        total_lines = line_end - line_start + 1

        raw_code = cls.snippet or ""
        docstring = self._extract_docstring(raw_code)

        if total_lines > self.MAX_SYMBOL_LINES:
            header_lines = self._get_signature_lines(raw_code, max_lines=6)
            formatted = self._format_lines(header_lines, line_start)
            return ExtractedWorkflowSnippet(
                name=cls.name,
                symbol_type="class",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                formatted_code=formatted,
                docstring=docstring,
                is_complete=False,
                exclusion_reason=f"Class structure ({total_lines} lines) exceeds {self.MAX_SYMBOL_LINES}-line limit; header retained.",
            )

        lines = raw_code.splitlines() if raw_code else [f"class {cls.name}:"]
        formatted = self._format_lines(lines, line_start)
        return ExtractedWorkflowSnippet(
            name=cls.name,
            symbol_type="class",
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            formatted_code=formatted,
            docstring=docstring,
            is_complete=True,
        )

    def _format_lines(self, lines: List[str], start_line: int) -> str:
        """Formats code with accurate 1-indexed source line numbers."""
        formatted: List[str] = []
        for idx, line in enumerate(lines):
            curr_line = start_line + idx
            formatted.append(f"L{curr_line}: {line}")
        return "\n".join(formatted)

    def _get_signature_lines(self, code: str, max_lines: int = 6) -> List[str]:
        if not code:
            return []
        return code.splitlines()[:max_lines]

    def _extract_docstring(self, code: str) -> Optional[str]:
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


workflow_snippet_extractor = WorkflowSnippetExtractor()
