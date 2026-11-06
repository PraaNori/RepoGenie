"""
Code syntax highlighter for educational code walkthrough visuals (Milestone 5, Phase 5.3).
"""

from __future__ import annotations

import html
from typing import List, Tuple

import pygments
from pygments.lexers import (
    get_lexer_by_name,
    get_lexer_for_filename,
    ClassNotFound,
    PythonLexer,
    JavascriptLexer,
    TypeScriptLexer,
    GoLexer,
    RustLexer,
    JavaLexer,
    JsonLexer,
    TextLexer,
)
from pygments.token import Token

from .schemas import CodeWalkthroughLine


# Video-optimized modern IDE palette (High-contrast on #1E293B slate dark background)
TOKEN_COLORS = {
    Token.Keyword: "#818CF8",            # Indigo 400
    Token.Keyword.Constant: "#F472B6",   # Pink 400 (True, False, None)
    Token.Keyword.Declaration: "#818CF8",
    Token.Keyword.Namespace: "#818CF8",
    Token.Keyword.Type: "#38BDF8",       # Sky 400
    Token.Name.Function: "#38BDF8",      # Sky 400
    Token.Name.Class: "#34D399",         # Emerald 400
    Token.Name.Builtin: "#38BDF8",       # Sky 400
    Token.Name.Builtin.Pseudo: "#F472B6", # self, cls
    Token.Name.Decorator: "#F59E0B",     # Amber 500 (@click.command)
    Token.String: "#34D399",             # Emerald 400
    Token.String.Doc: "#94A3B8",         # Slate 400
    Token.Number: "#F472B6",             # Pink 400
    Token.Operator: "#CBD5E1",           # Slate 300
    Token.Punctuation: "#94A3B8",        # Slate 400
    Token.Comment: "#94A3B8",            # Slate 400
    Token.Comment.Single: "#94A3B8",
    Token.Comment.Multiline: "#94A3B8",
    Token.Generic: "#F8FAFC",            # Slate 50
    Token.Text: "#F8FAFC",               # Slate 50
    Token.Name: "#F8FAFC",               # Slate 50
}

DEFAULT_TEXT_COLOR = "#F8FAFC"


class CodeHighlighter:
    """Highlights source code tokens for crisp vector SVG rendering."""

    def __init__(self):
        pass

    def _get_lexer(self, file_path: str, language: str):
        """Resolves Pygments lexer based on file path or language name."""
        if file_path:
            try:
                return get_lexer_for_filename(file_path)
            except ClassNotFound:
                pass
        if language:
            try:
                return get_lexer_by_name(language.lower())
            except ClassNotFound:
                pass
        return PythonLexer()

    def _resolve_color(self, token_type) -> str:
        """Finds matching hex color for token hierarchy."""
        curr = token_type
        while curr:
            if curr in TOKEN_COLORS:
                return TOKEN_COLORS[curr]
            curr = curr.parent
        return DEFAULT_TEXT_COLOR

    def highlight_lines(
        self,
        raw_lines: List[Tuple[int, str]],
        file_path: str = "snippet.py",
        language: str = "python",
        highlighted_line_numbers: List[int] = None,
        annotations: dict = None,
    ) -> List[CodeWalkthroughLine]:
        """
        Tokenizes lines of code and returns styled CodeWalkthroughLine items.
        raw_lines: List of (1-indexed line_number, raw text content)
        """
        highlight_set = set(highlighted_line_numbers or [])
        annotations_map = annotations or {}
        lexer = self._get_lexer(file_path, language)

        result_lines: List[CodeWalkthroughLine] = []

        for line_num, content in raw_lines:
            is_hl = line_num in highlight_set
            annotation = annotations_map.get(line_num)
            is_omission = "..." in content and ("omitted" in content.lower() or "skipped" in content.lower())

            # Tokenize single line with Pygments
            tokens: List[Tuple[str, str]] = []
            if is_omission:
                # Style omission marker distinctly in faint slate
                tokens.append(("#94A3B8", content))
            else:
                lexed_tokens = list(pygments.lex(content, lexer))
                for t_type, t_val in lexed_tokens:
                    # Strip trailing newline added by pygments
                    val = t_val.rstrip("\r\n")
                    if not val:
                        continue
                    color = self._resolve_color(t_type)
                    tokens.append((color, val))

            if not tokens:
                tokens.append((DEFAULT_TEXT_COLOR, " "))

            result_lines.append(
                CodeWalkthroughLine(
                    line_number=line_num,
                    content=content,
                    is_highlighted=is_hl,
                    is_omission_marker=is_omission,
                    annotation=annotation,
                    tokens=tokens,
                )
            )

        return result_lines


code_highlighter = CodeHighlighter()
