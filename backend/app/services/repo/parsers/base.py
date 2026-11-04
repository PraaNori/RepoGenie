import bisect
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
import tree_sitter

from ....models.schemas import (
    ParsedFile,
    ParsingWarning,
    SourceLocation,
)

class BaseLanguageParser(ABC):
    """
    Abstract base class for modular language AST parsers using Tree-sitter.
    Uses byte-offset line mapping to ensure crash-proof extraction even with complex Unicode.
    """

    def __init__(self, language_name: str, supported_extensions: List[str]):
        self.language_name = language_name
        self.supported_extensions = supported_extensions
        self._language = self._init_language()

    @abstractmethod
    def _init_language(self) -> Optional[tree_sitter.Language]:
        """Initialize the Tree-sitter Language instance for this parser."""
        pass

    def get_parser(self) -> Optional[tree_sitter.Parser]:
        """Return a fresh Parser for thread-safety and clean AST state."""
        if not self._language:
            return None
        return tree_sitter.Parser(self._language)

    @abstractmethod
    def parse_file(
        self,
        content: bytes,
        rel_path: str,
        max_snippet_lines: int = 60,
        max_snippet_chars: int = 2500,
    ) -> ParsedFile:
        """
        Parse source file contents and extract functions, classes, methods, imports, and calls.
        """
        pass

    @staticmethod
    def build_line_starts(content: bytes) -> List[int]:
        """Build byte offset lookup table for fast, robust line/column conversion."""
        starts = [0]
        for idx, b in enumerate(content):
            if b == 10:  # ord('\n')
                starts.append(idx + 1)
        return starts

    @staticmethod
    def byte_to_line_col(line_starts: List[int], byte_offset: int) -> Tuple[int, int]:
        """Convert byte offset to 1-indexed (line, column)."""
        line_idx = bisect.bisect_right(line_starts, byte_offset) - 1
        line_idx = max(0, min(line_idx, len(line_starts) - 1))
        col_idx = byte_offset - line_starts[line_idx]
        return line_idx + 1, col_idx + 1

    @classmethod
    def make_source_location(
        cls,
        rel_path: str,
        node: tree_sitter.Node,
        line_starts: Optional[List[int]] = None,
    ) -> SourceLocation:
        """
        Build a 1-indexed SourceLocation from a Tree-sitter node.
        If line_starts is supplied, uses byte offsets for total immunity against Point corruption.
        """
        if line_starts is not None:
            s_line, s_col = cls.byte_to_line_col(line_starts, node.start_byte)
            e_line, e_col = cls.byte_to_line_col(line_starts, node.end_byte)
            return SourceLocation(
                file_path=rel_path,
                start_line=s_line,
                end_line=max(s_line, e_line),
                start_column=s_col,
                end_column=max(1, e_col),
            )

        # Fallback to node points if table not passed
        return SourceLocation(
            file_path=rel_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            start_column=node.start_point.column + 1,
            end_column=node.end_point.column + 1,
        )

    @classmethod
    def find_syntax_errors(
        cls,
        root_node: tree_sitter.Node,
        rel_path: str,
        line_starts: Optional[List[int]] = None,
        max_errors: int = 10,
    ) -> List[ParsingWarning]:
        """
        Scan AST for ERROR or MISSING nodes iteratively and return structured ParsingWarning list.
        """
        errors: List[ParsingWarning] = []
        if not root_node.has_error:
            return errors

        stack = [root_node]
        while stack and len(errors) < max_errors:
            n = stack.pop()
            if n.type == "ERROR" or n.is_missing:
                if line_starts:
                    s_line, _ = cls.byte_to_line_col(line_starts, n.start_byte)
                else:
                    s_line = n.start_point.row + 1

                preview = n.text.decode("utf-8", errors="ignore")[:30].strip()
                errors.append(
                    ParsingWarning(
                        file_path=rel_path,
                        line_number=s_line,
                        message=f"Syntax error near '{preview}' at line {s_line}",
                        warning_type="syntax_error",
                    )
                )
            for child in reversed(n.children):
                stack.append(child)

        return errors

    @staticmethod
    def extract_snippet(
        lines: List[str],
        start_line: int,
        end_line: int,
        max_lines: int = 60,
        max_chars: int = 2500,
    ) -> str:
        """
        Extract code snippet between 1-indexed start_line and end_line, with size guards.
        """
        if not lines:
            return ""
        s_idx = max(0, start_line - 1)
        e_idx = min(len(lines), end_line)

        selected = lines[s_idx:e_idx]
        truncated = False
        if len(selected) > max_lines:
            selected = selected[:max_lines]
            truncated = True

        joined = "\n".join(selected)
        if len(joined) > max_chars:
            joined = joined[:max_chars]
            truncated = True

        if truncated:
            joined += "\n... [truncated]"
        return joined
