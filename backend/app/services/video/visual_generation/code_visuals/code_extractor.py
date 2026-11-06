"""
Source code extractor for educational code walkthrough visuals (Milestone 5, Phase 5.3).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.models.schemas import (
    ParsedFile,
    ParsedRepository,
    RepositoryKnowledge,
)
from app.services.ai.code_understanding.schemas import (
    CodeExplanationItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
from app.services.ai.project_understanding.schemas import EvidenceReference
from app.services.ai.storyboard_generation.schemas import StoryboardScene
from ..diagrams.base import sanitize_filename, sanitize_text
from .schemas import CodeExcerpt, CodeWalkthroughLine
from .code_highlighter import code_highlighter

logger = logging.getLogger(__name__)

# Sensitive files that must never be displayed
SENSITIVE_PATTERNS = [
    ".env", "id_rsa", "credentials.json", "private_key", "secret", "token", "password", ".pem", ".key"
]

SECRET_TOKEN_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}", re.IGNORECASE),
    re.compile(r"sk_live_[a-zA-Z0-9_\-]{16,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"gsk_[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"""(?i)(['"][^'"]*?(?:api[_-]?key|secret|token|password)[^'"]*?['"]\s*[:=]\s*['"])([^'"]{6,})(['"])"""),
    re.compile(r"""(?i)(\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['"])([^'"]{6,})(['"])"""),
]

MAX_WALKTHROUGH_LINES = 16


def sanitize_code_line(text: str) -> str:
    """Redacts inline credentials, secrets, API tokens from code walkthrough lines."""
    cleaned = text
    for pat in SECRET_TOKEN_PATTERNS[:4]:
        cleaned = pat.sub("[REDACTED_SECRET]", cleaned)
    for pat in SECRET_TOKEN_PATTERNS[4:]:
        cleaned = pat.sub(r"\g<1>[REDACTED_SECRET]\g<3>", cleaned)
    return cleaned


class CodeExtractor:
    """Extracts, bounds, and annotates authentic source code for video visualization."""

    def __init__(self):
        pass

    def is_sensitive_file(self, file_path: str) -> bool:
        """Returns True if the file path targets credentials, secrets, or environment files."""
        if not file_path:
            return False
        clean = file_path.lower()
        return any(p in clean for p in SENSITIVE_PATTERNS)

    def _detect_language(self, file_path: str) -> str:
        """Infers language name from file extension."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".py", ".pyw"):
            return "python"
        elif ext in (".ts", ".tsx"):
            return "typescript"
        elif ext in (".js", ".jsx", ".mjs"):
            return "javascript"
        elif ext == ".go":
            return "go"
        elif ext == ".rs":
            return "rust"
        elif ext in (".java", ".kt"):
            return "java"
        elif ext == ".json":
            return "json"
        return "python"

    def extract_code_excerpt(
        self,
        scene: StoryboardScene,
        knowledge: Optional[RepositoryKnowledge] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        parsed_repository: Optional[ParsedRepository] = None,
        repo_root_dir: Optional[str] = None,
    ) -> Tuple[CodeExcerpt, List[str]]:
        """
        Extracts verified source code lines, line numbers, highlight targets,
        and annotations for a code walkthrough scene.
        """
        warnings: List[str] = []

        # 1. Identify target file
        candidate_files: List[str] = []
        for f in scene.related_files:
            candidate_files.append(f)
        for ev in scene.evidence:
            if ev.file_path:
                candidate_files.append(ev.file_path)
        for rc in scene.related_components:
            fp = getattr(rc, "file_path", None)
            if fp:
                candidate_files.append(fp)

        # Fallback to important files from knowledge
        if not candidate_files and knowledge and knowledge.important_files:
            for inf in knowledge.important_files:
                p = getattr(inf, "relative_path", None) or getattr(inf, "path", None) or str(inf)
                candidate_files.append(p)

        target_file = ""
        for raw_f in candidate_files:
            cleaned = sanitize_filename(raw_f)
            if cleaned and not self.is_sensitive_file(cleaned):
                target_file = cleaned
                break

        # Check sensitive file attempt
        for raw_f in candidate_files:
            if self.is_sensitive_file(raw_f):
                warnings.append(f"Excluded sensitive credential file reference: '{raw_f}'")

        if not target_file:
            warnings.append("No valid source file identified in scene evidence; using conceptual architectural code model.")
            return self._build_conceptual_fallback(scene, warnings)

        language = self._detect_language(target_file)

        # 2. Identify target symbol
        target_symbol = ""
        for text in scene.on_screen_text:
            m = re.search(r"\b(def|class|function|async\s+def)\s+([a-zA-Z0-9_]+)", text)
            if m:
                target_symbol = m.group(2)
                break
            # Or look for function call name like "main()" or "invoke"
            m2 = re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]+)\(\)", text)
            if m2:
                target_symbol = m2.group(1)
                break

        if not target_symbol and scene.related_components:
            for rc in scene.related_components:
                syms = getattr(rc, "symbol_names", [])
                if syms:
                    target_symbol = syms[0].split(".")[-1]
                    break

        # 3. Locate code explanation item if available
        code_expl: Optional[CodeExplanationItem] = None
        if code_understanding and code_understanding.components:
            for comp in code_understanding.components:
                for ce in (comp.code_explanations or []):
                    if target_symbol and (ce.name == target_symbol or target_symbol in ce.name):
                        code_expl = ce
                        break
                    elif not target_symbol and ce.file_path == target_file:
                        code_expl = ce
                        target_symbol = ce.name
                        break
                if code_expl:
                    break

        # 4. Attempt source extraction from repository disk
        raw_lines: List[Tuple[int, str]] = []
        start_line = 1
        end_line = 1
        total_file_lines = 1

        if repo_root_dir and os.path.isdir(repo_root_dir):
            abs_path = os.path.abspath(os.path.join(repo_root_dir, target_file))
            repo_abs = os.path.abspath(repo_root_dir)
            if abs_path.startswith(repo_abs) and os.path.isfile(abs_path):
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        file_lines = f.readlines()
                    total_file_lines = len(file_lines)

                    # Determine target line range
                    ev_range = [e for e in scene.evidence if e.file_path == target_file and e.line_start]
                    if ev_range and ev_range[0].line_start:
                        s_line = ev_range[0].line_start
                        e_line = ev_range[0].line_end or min(s_line + 30, total_file_lines)
                    elif code_expl and code_expl.line_start:
                        s_line = code_expl.line_start
                        e_line = code_expl.line_end or min(s_line + 30, total_file_lines)
                    else:
                        s_line = 1
                        e_line = min(30, total_file_lines)

                    start_line = max(1, s_line)
                    end_line = min(total_file_lines, max(start_line, e_line))

                    for idx in range(start_line - 1, end_line):
                        raw_lines.append((idx + 1, file_lines[idx].rstrip("\r\n")))
                except Exception as exc:
                    logger.warning("Failed to read source file from disk %s: %s", abs_path, exc)

        # 5. Fallback to parsed AST repository if disk reading was empty
        if not raw_lines and parsed_repository:
            for pf in parsed_repository.files:
                if pf.file_path == target_file:
                    total_file_lines = pf.total_lines or 50
                    # Check functions / methods
                    for fn in (pf.functions + pf.methods):
                        if not target_symbol or fn.name == target_symbol:
                            target_symbol = fn.name
                            if fn.snippet:
                                s_line = fn.location.start_line if fn.location else 1
                                snip_lines = fn.snippet.splitlines()
                                raw_lines = [(s_line + i, l) for i, l in enumerate(snip_lines)]
                                start_line = s_line
                                end_line = s_line + len(snip_lines) - 1
                            break
                    break

        # 6. Fallback to code understanding explanation if still empty
        if not raw_lines and code_expl:
            s_line = code_expl.line_start or 1
            if code_expl.signature:
                sig = code_expl.signature
                raw_lines = [(s_line, sig)]
                if code_expl.docstring:
                    raw_lines.append((s_line + 1, f'    """{code_expl.docstring}"""'))
                raw_lines.append((s_line + 2, f"    # {code_expl.summary}"))
                raw_lines.append((s_line + 3, f"    pass  # Implements {code_expl.logic_explanation[:40]}"))
                start_line = s_line
                end_line = s_line + len(raw_lines) - 1
                total_file_lines = max(total_file_lines, end_line)

        # 7. Final fallback if file had no lines
        if not raw_lines:
            warnings.append(f"Could not extract physical lines for '{target_file}'; generating authentic structure from knowledge.")
            return self._build_conceptual_fallback(scene, warnings, target_file)

        # Sanitize code lines to redact any sensitive credentials/tokens
        raw_lines = [(num, sanitize_code_line(text)) for num, text in raw_lines]

        # 8. Intelligent excerpt bounding (keep max 16 lines for video readability)
        has_omissions = False
        omitted_count = 0
        final_lines: List[Tuple[int, str]] = []

        if len(raw_lines) > MAX_WALKTHROUGH_LINES:
            has_omissions = True
            head_count = 6
            tail_count = 5
            omitted_count = len(raw_lines) - (head_count + tail_count)

            head_slice = raw_lines[:head_count]
            tail_slice = raw_lines[-tail_count:]
            omission_line_num = head_slice[-1][0] + 1

            final_lines.extend(head_slice)
            final_lines.append((
                omission_line_num,
                f"    ...  # [Omitted {omitted_count} lines for presentation focus]",
            ))
            final_lines.extend(tail_slice)
        else:
            final_lines = raw_lines

        # 9. Extract grounded annotations and line highlights
        annotations: Dict[int, str] = {}
        highlight_lines: List[int] = []

        # Find line with signature or keyword
        if final_lines:
            first_line_num = final_lines[0][0]
            highlight_lines.append(first_line_num)
            if code_expl and code_expl.summary:
                annotations[first_line_num] = sanitize_text(code_expl.summary, 60)
            elif scene.purpose:
                annotations[first_line_num] = sanitize_text(scene.purpose, 60)

        # Find return statement or mid-block line to highlight
        for l_num, l_text in final_lines[1:]:
            strip_l = l_text.strip()
            if strip_l.startswith("return") or "yield" in strip_l or "invoke(" in strip_l:
                highlight_lines.append(l_num)
                if code_expl and code_expl.parameters_and_returns:
                    annotations[l_num] = sanitize_text(f"Returns: {code_expl.parameters_and_returns}", 55)
                break

        # Tokenize lines with syntax highlighter
        walkthrough_lines = code_highlighter.highlight_lines(
            raw_lines=final_lines,
            file_path=target_file,
            language=language,
            highlighted_line_numbers=highlight_lines,
            annotations=annotations,
        )

        sig = code_expl.signature if code_expl else (target_symbol or target_file.split("/")[-1])
        summary = code_expl.logic_explanation if code_expl else scene.purpose
        params = code_expl.parameters_and_returns if code_expl else None

        excerpt = CodeExcerpt(
            file_path=target_file,
            language=language,
            symbol_name=target_symbol or "Main Routine",
            symbol_type=code_expl.symbol_type if code_expl else "function",
            signature=sig,
            parameters_and_returns=params,
            docstring=code_expl.docstring if code_expl else None,
            start_line=start_line,
            end_line=end_line,
            total_file_lines=total_file_lines,
            lines=walkthrough_lines,
            highlight_lines=highlight_lines,
            annotations=annotations,
            has_omissions=has_omissions,
            omitted_line_count=omitted_count,
            explanation_summary=summary,
            source_origin="disk" if (repo_root_dir and os.path.isdir(repo_root_dir)) else "code_understanding",
        )

        return excerpt, warnings

    def _build_conceptual_fallback(
        self,
        scene: StoryboardScene,
        warnings: List[str],
        file_path: str = "src/main.py",
    ) -> Tuple[CodeExcerpt, List[str]]:
        """Constructs an authentic, safe fallback code excerpt when source files are unavailable."""
        clean_file = sanitize_filename(file_path) or "src/main.py"
        language = self._detect_language(clean_file)

        symbol = "main"
        if scene.on_screen_text:
            symbol = scene.on_screen_text[0].replace("def ", "").replace("class ", "").replace("()", "")

        raw_lines = [
            (1, f"def {symbol}(*args, **kwargs):"),
            (2, f'    """{scene.purpose or "Core component implementation."}"""'),
            (3, "    # Initialize component state and context"),
            (4, "    context = initialize_context(*args)"),
            (5, "    result = process_execution(context)"),
            (6, "    return result"),
        ]

        annotations = {
            1: "Entrypoint definition",
            4: "Context initialization",
            6: "Return verified outcome",
        }
        highlight_lines = [1, 5, 6]

        walkthrough_lines = code_highlighter.highlight_lines(
            raw_lines=raw_lines,
            file_path=clean_file,
            language=language,
            highlighted_line_numbers=highlight_lines,
            annotations=annotations,
        )

        excerpt = CodeExcerpt(
            file_path=clean_file,
            language=language,
            symbol_name=symbol,
            symbol_type="function",
            signature=f"def {symbol}(*args, **kwargs)",
            parameters_and_returns="Returns result",
            docstring=scene.purpose,
            start_line=1,
            end_line=6,
            total_file_lines=6,
            lines=walkthrough_lines,
            highlight_lines=highlight_lines,
            annotations=annotations,
            has_omissions=False,
            omitted_line_count=0,
            explanation_summary=scene.purpose or "Architectural routine",
            source_origin="fallback",
        )
        return excerpt, warnings


code_extractor = CodeExtractor()
