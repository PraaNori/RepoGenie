import logging
import os
from typing import Dict, List, Optional, Set

from ...core.config import settings
from ...models.schemas import (
    DirectoryTreeNode,
    ParsedFile,
    ParsedRepository,
    ParsingWarning,
    RepoAnalysisResult,
    StatusEnum,
)
from .analyzer import EXCLUDED_DIRECTORIES
from .parsers import (
    get_parser_for_extension,
    get_supported_languages,
)

logger = logging.getLogger(__name__)

class CodeParserService:
    """
    Orchestrates AST parsing and structural extraction across repository source files.
    Applies resource boundaries, file filtering, modular language parsers, and error isolation.
    """

    def __init__(
        self,
        max_file_size_bytes: int = settings.MAX_CODE_FILE_SIZE_BYTES,
        max_files_to_parse: int = settings.MAX_CODE_FILES_TO_PARSE,
        max_snippet_lines: int = settings.MAX_SNIPPET_LINES,
        max_snippet_chars: int = settings.MAX_SNIPPET_CHARS,
    ):
        self.max_file_size_bytes = max_file_size_bytes
        self.max_files_to_parse = max_files_to_parse
        self.max_snippet_lines = max_snippet_lines
        self.max_snippet_chars = max_snippet_chars

    def collect_source_files_from_tree(
        self, node: DirectoryTreeNode, supported_extensions: Set[str]
    ) -> List[str]:
        """Collect relative paths of source files from a DirectoryTreeNode."""
        result: List[str] = []

        def walk(n: DirectoryTreeNode):
            if n.type == "file":
                ext = (n.extension or "").lower()
                if ext in supported_extensions and n.path:
                    result.append(n.path)
            elif n.children:
                for c in n.children:
                    walk(c)

        walk(node)
        return result

    def parse_repository(
        self,
        job_id: str,
        repo_name: str,
        local_path: str,
        analysis: Optional[RepoAnalysisResult] = None,
    ) -> ParsedRepository:
        """
        Parse all eligible source files in the cloned repository and return structured metadata.
        """
        repo_real_root = os.path.realpath(local_path)
        warnings: List[str] = []
        parsed_files: List[ParsedFile] = []
        languages_found: Set[str] = set()

        total_functions = 0
        total_classes = 0
        total_methods = 0
        total_imports = 0
        total_function_calls = 0

        # Collect eligible source files
        candidate_paths: List[str] = []
        supported_exts = {
            ".py", ".pyw",
            ".js", ".jsx", ".mjs", ".cjs",
            ".ts", ".tsx", ".mts", ".cts",
            ".go",
            ".rs",
            ".java",
            ".c", ".h",
            ".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh",
        }

        if analysis and analysis.directory_tree:
            candidate_paths = self.collect_source_files_from_tree(
                analysis.directory_tree, supported_exts
            )
        else:
            # Fallback scan if tree is unavailable
            for root, dirs, files in os.walk(repo_real_root):
                dirs[:] = [
                    d for d in dirs if d not in EXCLUDED_DIRECTORIES
                ]
                for f in sorted(files):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in supported_exts:
                        full_p = os.path.join(root, f)
                        rel_p = os.path.relpath(full_p, repo_real_root)
                        candidate_paths.append(rel_p)

        # Enforce max files limit
        if len(candidate_paths) > self.max_files_to_parse:
            warnings.append(
                f"Repository contains {len(candidate_paths)} eligible source files; "
                f"parsing capped at {self.max_files_to_parse} files limit."
            )
            candidate_paths = candidate_paths[: self.max_files_to_parse]

        logger.info(
            "Starting AST parsing for job %s (%s): %d source files eligible",
            job_id,
            repo_name,
            len(candidate_paths),
        )

        for rel_path in candidate_paths:
            full_path = os.path.join(repo_real_root, rel_path)
            real_file_path = os.path.realpath(full_path)

            # Security: ensure file resides inside repo root
            if (
                not real_file_path.startswith(repo_real_root + os.sep)
                and real_file_path != repo_real_root
            ):
                logger.warning(
                    "Skipping path traversal file for job %s: %s", job_id, rel_path
                )
                continue

            # Check file size limit
            try:
                file_size = os.path.getsize(real_file_path)
            except OSError as exc:
                logger.debug("Cannot stat file %s: %s", rel_path, exc)
                continue

            ext = os.path.splitext(rel_path)[1].lower()
            parser = get_parser_for_extension(ext)

            if not parser:
                # Unsupported language for AST parsing
                continue

            if file_size > self.max_file_size_bytes:
                parsed_files.append(
                    ParsedFile(
                        file_path=rel_path,
                        language=parser.language_name,
                        status="skipped",
                        warnings=[
                            ParsingWarning(
                                file_path=rel_path,
                                message=f"File size ({file_size} bytes) exceeds limit ({self.max_file_size_bytes} bytes)",
                                warning_type="size_limit_exceeded",
                            )
                        ],
                    )
                )
                continue

            # Read and parse file
            try:
                with open(real_file_path, "rb") as fh:
                    content = fh.read()

                parsed_file = parser.parse_file(
                    content=content,
                    rel_path=rel_path,
                    max_snippet_lines=self.max_snippet_lines,
                    max_snippet_chars=self.max_snippet_chars,
                )

                parsed_files.append(parsed_file)
                languages_found.add(parser.language_name)

                total_functions += len(parsed_file.functions)
                total_classes += len(parsed_file.classes)
                total_methods += len(parsed_file.methods)
                total_imports += len(parsed_file.imports)
                total_function_calls += len(parsed_file.function_calls)

            except Exception as exc:
                logger.exception("Failed parsing file %s: %s", rel_path, exc)
                parsed_files.append(
                    ParsedFile(
                        file_path=rel_path,
                        language=parser.language_name,
                        status="error",
                        warnings=[
                            ParsingWarning(
                                file_path=rel_path,
                                message=f"Parsing error: {str(exc)}",
                                warning_type="parse_exception",
                            )
                        ],
                    )
                )

        logger.info(
            "Completed code parsing for job %s: %d files, %d functions, %d classes, %d methods, %d imports",
            job_id,
            len(parsed_files),
            total_functions,
            total_classes,
            total_methods,
            total_imports,
        )

        return ParsedRepository(
            job_id=job_id,
            repository_name=repo_name,
            total_parsed_files=len(parsed_files),
            total_functions=total_functions,
            total_classes=total_classes,
            total_methods=total_methods,
            total_imports=total_imports,
            total_function_calls=total_function_calls,
            supported_languages=sorted(list(languages_found)),
            files=parsed_files,
            parsing_status=StatusEnum.COMPLETED,
            warnings=warnings,
        )

# Singleton service instance
code_parser_service = CodeParserService()
