"""
Strongly typed schemas for Milestone 5, Phase 5.3: Code Walkthrough Visual Generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class CodeWalkthroughLine:
    """Represents a single line of source code with 1-indexed line number and styling."""
    line_number: int
    content: str
    is_highlighted: bool = False
    is_omission_marker: bool = False
    annotation: Optional[str] = None
    tokens: List[Tuple[str, str]] = field(default_factory=list)  # (color_hex, token_text)


@dataclass
class CodeExcerpt:
    """Represents an extracted, bounded, evidence-grounded code snippet."""
    file_path: str
    language: str = "python"
    symbol_name: Optional[str] = None
    symbol_type: str = "function"  # "function", "method", "class", "module"
    signature: Optional[str] = None
    parameters_and_returns: Optional[str] = None
    docstring: Optional[str] = None
    start_line: int = 1
    end_line: int = 1
    total_file_lines: int = 1
    lines: List[CodeWalkthroughLine] = field(default_factory=list)
    highlight_lines: List[int] = field(default_factory=list)
    annotations: Dict[int, str] = field(default_factory=dict)
    has_omissions: bool = False
    omitted_line_count: int = 0
    explanation_summary: Optional[str] = None
    source_origin: str = "repository"  # "disk", "tree_sitter", "code_understanding", "fallback"
