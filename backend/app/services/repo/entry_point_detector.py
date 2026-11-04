import json
import logging
import os
import posixpath
import re
from typing import Dict, List, Optional, Set

from ...models.schemas import (
    EntryPointCandidate,
    ParsedFile,
    RelationshipEvidence,
    RepoAnalysisResult,
)

logger = logging.getLogger(__name__)

PYTHON_MAIN_GUARD_RE = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]")
DOCKER_CMD_ENTRYPOINT_RE = re.compile(r"^(?:ENTRYPOINT|CMD)\s+(.*)$", re.MULTILINE)
SPRING_BOOT_RE = re.compile(r"@SpringBootApplication")


class EntryPointDetector:
    """
    Detects repository application entry points from code structures, main guards,
    framework instances, manifest scripts, and Docker configuration files.
    """

    def detect_entry_points(
        self,
        parsed_files: List[ParsedFile],
        local_path: Optional[str] = None,
        analysis: Optional[RepoAnalysisResult] = None,
    ) -> List[EntryPointCandidate]:
        candidates: List[EntryPointCandidate] = []
        seen_entries: Set[str] = set()

        def add_candidate(cand: EntryPointCandidate):
            key = f"{cand.file_path}:{cand.entry_type}:{cand.symbol_or_command}"
            if key not in seen_entries:
                seen_entries.add(key)
                candidates.append(cand)

        # 1. AST Inspection across parsed files
        for pf in parsed_files:
            file_p = pf.file_path
            base_name = posixpath.basename(file_p)
            lang = pf.language.lower()

            # A. Main functions across compiled/typed languages
            for func in pf.functions:
                if func.name == "main":
                    if "go" in lang:
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="go_main",
                                symbol_or_command="func main()",
                                confidence="high",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="main_guard",
                                        statement="func main() entry point",
                                        file_path=file_p,
                                        line_number=func.location.start_line,
                                        confidence="high",
                                    )
                                ],
                            )
                        )
                    elif "rust" in lang:
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="rust_main",
                                symbol_or_command="fn main()",
                                confidence="high",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="main_guard",
                                        statement="fn main() entry point",
                                        file_path=file_p,
                                        line_number=func.location.start_line,
                                        confidence="high",
                                    )
                                ],
                            )
                        )
                    elif "c" in lang or "cpp" in lang:
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="c_cpp_main",
                                symbol_or_command="int main(...)",
                                confidence="high",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="main_guard",
                                        statement="main() execution entry point",
                                        file_path=file_p,
                                        line_number=func.location.start_line,
                                        confidence="high",
                                    )
                                ],
                            )
                        )

            # B. Java public static void main
            if "java" in lang:
                for meth in pf.methods:
                    if meth.name == "main":
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="java_main_method",
                                symbol_or_command=f"{meth.parent_class}.main(String[] args)",
                                confidence="high",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="main_guard",
                                        statement=f"public static void main in class {meth.parent_class}",
                                        file_path=file_p,
                                        line_number=meth.location.start_line,
                                        confidence="high",
                                    )
                                ],
                            )
                        )

            # C. Framework app instances & server listeners
            for call in pf.function_calls:
                cname = call.call_name
                if cname in ("FastAPI", "Flask", "express", "Koa"):
                    add_candidate(
                        EntryPointCandidate(
                            file_path=file_p,
                            entry_type="framework_app_instance",
                            symbol_or_command=f"{cname}()",
                            confidence="medium",
                            evidence=[
                                RelationshipEvidence(
                                    evidence_type="framework_app_instance",
                                    statement=f"Instantiates framework application: {cname}()",
                                    file_path=file_p,
                                    line_number=call.line_number,
                                    confidence="medium",
                                )
                            ],
                        )
                    )
                elif cname in ("app.listen", "server.listen"):
                    add_candidate(
                        EntryPointCandidate(
                            file_path=file_p,
                            entry_type="framework_app_instance",
                            symbol_or_command=cname,
                            confidence="high",
                            evidence=[
                                RelationshipEvidence(
                                    evidence_type="framework_app_instance",
                                    statement=f"HTTP server listener: {cname}(...)",
                                    file_path=file_p,
                                    line_number=call.line_number,
                                    confidence="high",
                                )
                            ],
                        )
                    )

            # D. Conventional entry file names
            if base_name in (
                "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py", "cli.py", "run.py",
                "server.ts", "server.js", "index.ts", "index.js", "main.ts", "main.js",
            ):
                add_candidate(
                    EntryPointCandidate(
                        file_path=file_p,
                        entry_type="application_entry_file",
                        symbol_or_command=base_name,
                        confidence="medium",
                        evidence=[
                            RelationshipEvidence(
                                evidence_type="configuration",
                                statement=f"Standard application entry filename: {base_name}",
                                file_path=file_p,
                                line_number=1,
                                confidence="medium",
                            )
                        ],
                    )
                )

        # 2. Filesystem Inspection (if local_path is accessible)
        if local_path and os.path.isdir(local_path):
            # A. Scan Python files for `if __name__ == "__main__":`
            for pf in parsed_files:
                if "python" in pf.language.lower():
                    full_p = os.path.join(local_path, pf.file_path)
                    try:
                        if os.path.isfile(full_p):
                            with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                                for line_idx, line in enumerate(f, 1):
                                    if PYTHON_MAIN_GUARD_RE.search(line):
                                        add_candidate(
                                            EntryPointCandidate(
                                                file_path=pf.file_path,
                                                entry_type="python_main_guard",
                                                symbol_or_command='if __name__ == "__main__":',
                                                confidence="high",
                                                evidence=[
                                                    RelationshipEvidence(
                                                        evidence_type="main_guard",
                                                        statement=line.strip(),
                                                        file_path=pf.file_path,
                                                        line_number=line_idx,
                                                        confidence="high",
                                                    )
                                                ],
                                            )
                                        )
                                        break
                    except Exception as exc:
                        logger.debug("Failed to read python file %s for main guard: %s", full_p, exc)

            # B. Check package.json scripts (start, dev, main)
            package_json_path = os.path.join(local_path, "package.json")
            if os.path.isfile(package_json_path):
                try:
                    with open(package_json_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                        main_entry = data.get("main")
                        if main_entry and isinstance(main_entry, str):
                            add_candidate(
                                EntryPointCandidate(
                                    file_path="package.json",
                                    entry_type="package_script",
                                    symbol_or_command=f"main: {main_entry}",
                                    confidence="high",
                                    evidence=[
                                        RelationshipEvidence(
                                            evidence_type="configuration",
                                            statement=f"package.json main entry: {main_entry}",
                                            file_path="package.json",
                                            line_number=None,
                                            confidence="high",
                                        )
                                    ],
                                )
                            )
                        scripts = data.get("scripts", {})
                        for script_key in ("start", "dev"):
                            if script_key in scripts:
                                add_candidate(
                                    EntryPointCandidate(
                                        file_path="package.json",
                                        entry_type="package_script",
                                        symbol_or_command=f"npm run {script_key} -> {scripts[script_key]}",
                                        confidence="high",
                                        evidence=[
                                            RelationshipEvidence(
                                                evidence_type="configuration",
                                                statement=f"package.json script '{script_key}': {scripts[script_key]}",
                                                file_path="package.json",
                                                line_number=None,
                                                confidence="high",
                                            )
                                        ],
                                    )
                                )
                except Exception as exc:
                    logger.debug("Failed reading package.json entry points: %s", exc)

            # C. Check Dockerfiles for ENTRYPOINT / CMD
            docker_candidates = ["Dockerfile", "docker/Dockerfile", "deploy/Dockerfile"]
            for dfile in docker_candidates:
                full_docker = os.path.join(local_path, dfile)
                if os.path.isfile(full_docker):
                    try:
                        with open(full_docker, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            matches = DOCKER_CMD_ENTRYPOINT_RE.findall(content)
                            for match in matches:
                                add_candidate(
                                    EntryPointCandidate(
                                        file_path=dfile,
                                        entry_type="docker_entrypoint",
                                        symbol_or_command=match.strip(),
                                        confidence="high",
                                        evidence=[
                                            RelationshipEvidence(
                                                evidence_type="configuration",
                                                statement=f"Docker startup command: {match.strip()}",
                                                file_path=dfile,
                                                line_number=None,
                                                confidence="high",
                                            )
                                        ],
                                    )
                                )
                    except Exception as exc:
                        logger.debug("Failed reading Dockerfile %s: %s", full_docker, exc)

        # Sort candidates: high confidence first, then medium, then low
        order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(key=lambda c: (order.get(c.confidence, 3), c.file_path))
        return candidates


entry_point_detector = EntryPointDetector()
