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


def classify_path_role(file_path: str) -> str:
    """
    Distinguishes whether a file resides in examples, tests, or application source.
    """
    parts = [p.lower() for p in file_path.replace("\\", "/").split("/")[:-1]]
    if any(p in ("examples", "example", "samples", "sample", "demos", "demo") for p in parts):
        return "example"
    if any(p in ("tests", "test", "__tests__", "testing") for p in parts):
        return "test"
    return "app"


class EntryPointDetector:
    """
    Detects repository application entry points from code structures, main guards,
    framework instances, manifest scripts, and Docker configuration files,
    distinguishing primary application entry points from examples and test scripts.
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
            role = classify_path_role(file_p)

            # A. Main functions across compiled/typed languages
            for func in pf.functions:
                if func.name == "main":
                    if role == "example":
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="example_entry_point",
                                symbol_or_command=f"{func.name}()",
                                confidence="medium",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="main_guard",
                                        statement=f"Example main function in {file_p}",
                                        file_path=file_p,
                                        line_number=func.location.start_line,
                                        confidence="medium",
                                    )
                                ],
                            )
                        )
                    elif role == "test":
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="test_entry_point",
                                symbol_or_command=f"{func.name}()",
                                confidence="low",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="main_guard",
                                        statement=f"Test entry main function in {file_p}",
                                        file_path=file_p,
                                        line_number=func.location.start_line,
                                        confidence="low",
                                    )
                                ],
                            )
                        )
                    elif "go" in lang:
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
                        if role == "example":
                            add_candidate(
                                EntryPointCandidate(
                                    file_path=file_p,
                                    entry_type="example_entry_point",
                                    symbol_or_command=f"{meth.parent_class}.main(String[] args)",
                                    confidence="medium",
                                    evidence=[
                                        RelationshipEvidence(
                                            evidence_type="main_guard",
                                            statement=f"Example main method in class {meth.parent_class}",
                                            file_path=file_p,
                                            line_number=meth.location.start_line,
                                            confidence="medium",
                                        )
                                    ],
                                )
                            )
                        elif role == "test":
                            add_candidate(
                                EntryPointCandidate(
                                    file_path=file_p,
                                    entry_type="test_entry_point",
                                    symbol_or_command=f"{meth.parent_class}.main(String[] args)",
                                    confidence="low",
                                    evidence=[
                                        RelationshipEvidence(
                                            evidence_type="main_guard",
                                            statement=f"Test main method in class {meth.parent_class}",
                                            file_path=file_p,
                                            line_number=meth.location.start_line,
                                            confidence="low",
                                        )
                                    ],
                                )
                            )
                        else:
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
                    if role == "example":
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="example_entry_point",
                                symbol_or_command=f"{cname}()",
                                confidence="low",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="framework_app_instance",
                                        statement=f"Example framework application instance: {cname}()",
                                        file_path=file_p,
                                        line_number=call.line_number,
                                        confidence="low",
                                    )
                                ],
                            )
                        )
                    elif role == "app":
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
                    if role == "example":
                        add_candidate(
                            EntryPointCandidate(
                                file_path=file_p,
                                entry_type="example_entry_point",
                                symbol_or_command=cname,
                                confidence="medium",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="framework_app_instance",
                                        statement=f"Example HTTP server listener: {cname}(...)",
                                        file_path=file_p,
                                        line_number=call.line_number,
                                        confidence="medium",
                                    )
                                ],
                            )
                        )
                    elif role == "app":
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
                if role == "example":
                    add_candidate(
                        EntryPointCandidate(
                            file_path=file_p,
                            entry_type="example_entry_point",
                            symbol_or_command=base_name,
                            confidence="low",
                            evidence=[
                                RelationshipEvidence(
                                    evidence_type="configuration",
                                    statement=f"Example script with common entry filename: {base_name}",
                                    file_path=file_p,
                                    line_number=1,
                                    confidence="low",
                                )
                            ],
                        )
                    )
                elif role == "test":
                    add_candidate(
                        EntryPointCandidate(
                            file_path=file_p,
                            entry_type="test_entry_point",
                            symbol_or_command=base_name,
                            confidence="low",
                            evidence=[
                                RelationshipEvidence(
                                    evidence_type="configuration",
                                    statement=f"Test script with common entry filename: {base_name}",
                                    file_path=file_p,
                                    line_number=1,
                                    confidence="low",
                                )
                            ],
                        )
                    )
                else:
                    dir_name = posixpath.dirname(file_p)
                    is_root_or_src = dir_name in ("", "src", "app", "cmd", "bin")
                    entry_type = (
                        "primary_application_entry"
                        if is_root_or_src and base_name in ("main.py", "app.py", "server.js", "server.ts", "index.js", "index.ts")
                        else "application_entry_file"
                    )
                    conf = "high" if is_root_or_src else "medium"
                    add_candidate(
                        EntryPointCandidate(
                            file_path=file_p,
                            entry_type=entry_type,
                            symbol_or_command=base_name,
                            confidence=conf,
                            evidence=[
                                RelationshipEvidence(
                                    evidence_type="configuration",
                                    statement=f"Standard application entry filename: {base_name}",
                                    file_path=file_p,
                                    line_number=1,
                                    confidence=conf,
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
                            role = classify_path_role(pf.file_path)
                            with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                                for line_idx, line in enumerate(f, 1):
                                    if PYTHON_MAIN_GUARD_RE.search(line):
                                        if role == "example":
                                            entry_t = "example_entry_point"
                                            conf = "medium"
                                            stmt = f"Example script entry guard: {line.strip()}"
                                        elif role == "test":
                                            entry_t = "test_entry_point"
                                            conf = "low"
                                            stmt = f"Test script entry guard: {line.strip()}"
                                        else:
                                            entry_t = "python_main_guard"
                                            conf = "high"
                                            stmt = line.strip()

                                        add_candidate(
                                            EntryPointCandidate(
                                                file_path=pf.file_path,
                                                entry_type=entry_t,
                                                symbol_or_command='if __name__ == "__main__":',
                                                confidence=conf,
                                                evidence=[
                                                    RelationshipEvidence(
                                                        evidence_type="main_guard",
                                                        statement=stmt,
                                                        file_path=pf.file_path,
                                                        line_number=line_idx,
                                                        confidence=conf,
                                                    )
                                                ],
                                            )
                                        )
                                        break
                    except Exception as exc:
                        logger.debug("Failed to read python file %s for main guard: %s", full_p, exc)

            # B. Check pyproject.toml for console scripts
            pyproject_path = os.path.join(local_path, "pyproject.toml")
            if os.path.isfile(pyproject_path):
                try:
                    import tomllib
                    with open(pyproject_path, "rb") as f:
                        py_data = tomllib.load(f)
                    scripts = py_data.get("project", {}).get("scripts", {})
                    if not scripts:
                        scripts = py_data.get("tool", {}).get("poetry", {}).get("scripts", {})
                    for script_name, target in scripts.items():
                        add_candidate(
                            EntryPointCandidate(
                                file_path="pyproject.toml",
                                entry_type="package_script",
                                symbol_or_command=f"console_script: {script_name} = {target}",
                                confidence="high",
                                evidence=[
                                    RelationshipEvidence(
                                        evidence_type="configuration",
                                        statement=f"pyproject.toml console script '{script_name}': {target}",
                                        file_path="pyproject.toml",
                                        line_number=None,
                                        confidence="high",
                                    )
                                ],
                            )
                        )
                except Exception as exc:
                    logger.debug("Failed reading pyproject.toml scripts: %s", exc)

            # C. Check package.json scripts (main, bin, start, dev)
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
                        bin_entry = data.get("bin")
                        if isinstance(bin_entry, str):
                            add_candidate(
                                EntryPointCandidate(
                                    file_path="package.json",
                                    entry_type="package_script",
                                    symbol_or_command=f"bin: {bin_entry}",
                                    confidence="high",
                                    evidence=[
                                        RelationshipEvidence(
                                            evidence_type="configuration",
                                            statement=f"package.json bin executable: {bin_entry}",
                                            file_path="package.json",
                                            line_number=None,
                                            confidence="high",
                                        )
                                    ],
                                )
                            )
                        elif isinstance(bin_entry, dict):
                            for bin_cmd, bin_p in bin_entry.items():
                                add_candidate(
                                    EntryPointCandidate(
                                        file_path="package.json",
                                        entry_type="package_script",
                                        symbol_or_command=f"bin: {bin_cmd} -> {bin_p}",
                                        confidence="high",
                                        evidence=[
                                            RelationshipEvidence(
                                                evidence_type="configuration",
                                                statement=f"package.json bin '{bin_cmd}': {bin_p}",
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

            # D. Check Dockerfiles for ENTRYPOINT / CMD
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
