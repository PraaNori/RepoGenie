from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ....models.schemas import RepositoryKnowledge
from .schemas import EvidenceReference

# Mapping of programming and markup/styling language names to their valid file extensions
LANGUAGE_EXTENSIONS: Dict[str, Tuple[str, ...]] = {
    "Python": (".py", ".pyw"),
    "JavaScript": (".js", ".jsx", ".mjs", ".cjs", ".gs"),
    "TypeScript": (".ts", ".tsx", ".mts", ".cts"),
    "Java": (".java",),
    "C": (".c", ".h"),
    "C++": (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ino"),
    "C#": (".cs",),
    "Go": (".go",),
    "Rust": (".rs",),
    "Ruby": (".rb",),
    "PHP": (".php",),
    "Swift": (".swift",),
    "Kotlin": (".kt", ".kts"),
    "HTML": (".html", ".htm"),
    "CSS": (".css", ".scss", ".sass", ".less"),
    "SQL": (".sql",),
    "Shell": (".sh", ".bash", ".zsh"),
    "Dart": (".dart",),
    "Vue": (".vue",),
    "Svelte": (".svelte",),
}

# Common ecosystem manifests associated with languages
LANGUAGE_ECOSYSTEM_MANIFESTS: Dict[str, Tuple[str, ...]] = {
    "Python": ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"),
    "JavaScript": ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"),
    "TypeScript": ("tsconfig.json", "package.json"),
    "Rust": ("Cargo.toml", "Cargo.lock"),
    "Go": ("go.mod", "go.sum"),
    "Java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "Ruby": ("Gemfile", "Gemfile.lock"),
    "PHP": ("composer.json", "composer.lock"),
}


def get_language_extensions(lang_name: str) -> Tuple[str, ...]:
    """Returns valid file extensions for a given language name (case-insensitive)."""
    target = lang_name.strip().lower()
    for lang, exts in LANGUAGE_EXTENSIONS.items():
        if lang.lower() == target:
            return exts
    return ()


def get_language_manifests(lang_name: str) -> Tuple[str, ...]:
    """Returns ecosystem manifest filenames for a language name (case-insensitive)."""
    target = lang_name.strip().lower()
    for lang, manifests in LANGUAGE_ECOSYSTEM_MANIFESTS.items():
        if lang.lower() == target:
            return manifests
    return ()


def find_actual_files_for_language(
    knowledge: RepositoryKnowledge,
    lang_name: str,
    max_files: int = 3,
) -> List[str]:
    """
    Finds real files in RepositoryKnowledge matching the valid extensions for the given language.
    Never returns synthetic wildcards like '*.python' or '*.js'.
    """
    exts = get_language_extensions(lang_name)
    if not exts:
        return []

    matched_files: List[str] = []
    seen: Set[str] = set()

    def add_candidate(path: Optional[str]) -> None:
        if not path:
            return
        norm = path.replace("\\", "/").strip().lstrip("/")
        if not norm or norm in seen:
            return
        # Never accept synthetic paths or wildcards
        if "*" in norm or "?" in norm or norm in ("source_code", "manifest", "repository_analysis"):
            return
        ext = os.path.splitext(norm.lower())[1]
        if ext in exts:
            seen.add(norm)
            matched_files.append(norm)

    # 1. From parsed code files (highest confidence, verified AST syntax)
    if hasattr(knowledge, "code_structure") and knowledge.code_structure:
        for pf in getattr(knowledge.code_structure, "files", []):
            if pf.language and pf.language.lower() == lang_name.lower():
                add_candidate(pf.file_path)
            else:
                add_candidate(pf.file_path)

    # 2. From entry points
    for ep in getattr(knowledge, "entry_points", []):
        add_candidate(getattr(ep, "file_path", None))

    # 3. From important files
    for imp in getattr(knowledge, "important_files", []):
        add_candidate(getattr(imp, "relative_path", None))

    # 4. From source evidence records
    for ev in getattr(knowledge, "source_evidence", []):
        add_candidate(getattr(ev, "file_path", None))

    # 5. From directory tree
    if (
        hasattr(knowledge, "repository_structure")
        and knowledge.repository_structure
        and getattr(knowledge.repository_structure, "directory_tree", None) is not None
    ):
        def traverse_node(node: Any) -> None:
            if not node:
                return
            if getattr(node, "type", "") == "file":
                p = getattr(node, "path", "")
                add_candidate(p)
            for child in getattr(node, "children", []) or []:
                traverse_node(child)

        traverse_node(knowledge.repository_structure.directory_tree)

    return matched_files[:max_files]


def find_actual_manifests_for_language(
    knowledge: RepositoryKnowledge,
    lang_name: str,
) -> List[str]:
    """
    Finds real manifest files in the repository associated with a given language ecosystem.
    """
    manifest_names = get_language_manifests(lang_name)
    if not manifest_names:
        return []

    known_paths: Set[str] = set()

    # Collect known files from directory tree
    if (
        hasattr(knowledge, "repository_structure")
        and knowledge.repository_structure
        and getattr(knowledge.repository_structure, "directory_tree", None) is not None
    ):
        def traverse(node: Any) -> None:
            if not node:
                return
            if getattr(node, "type", "") == "file":
                p = getattr(node, "path", "")
                if p:
                    norm = p.replace("\\", "/").strip().lstrip("/")
                    known_paths.add(norm)
                    known_paths.add(os.path.basename(norm))
            for child in getattr(node, "children", []) or []:
                traverse(child)

        traverse(knowledge.repository_structure.directory_tree)

    for f in getattr(knowledge, "important_files", []):
        if getattr(f, "relative_path", None):
            norm = f.relative_path.replace("\\", "/").strip().lstrip("/")
            known_paths.add(norm)
            known_paths.add(os.path.basename(norm))

    for ev in getattr(knowledge, "source_evidence", []):
        if getattr(ev, "file_path", None):
            norm = ev.file_path.replace("\\", "/").strip().lstrip("/")
            known_paths.add(norm)
            known_paths.add(os.path.basename(norm))

    matched: List[str] = []
    for m in manifest_names:
        if m in known_paths:
            matched.append(m)
    return matched


def find_actual_evidence_for_framework(
    knowledge: RepositoryKnowledge,
    fw_name: str,
) -> List[Dict[str, Any]]:
    """
    Finds real code or manifest files evidencing a framework or library.
    Never returns fake strings like 'manifest' or 'source_code'.
    """
    fw_lower = fw_name.lower()
    matched: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    # 1. Check code imports in parsed files
    if hasattr(knowledge, "code_structure") and knowledge.code_structure:
        for pf in getattr(knowledge.code_structure, "files", []):
            for imp in getattr(pf, "imports", []):
                if fw_lower in getattr(imp, "module", "").lower():
                    if pf.file_path not in seen:
                        seen.add(pf.file_path)
                        matched.append({
                            "file_path": pf.file_path,
                            "evidence_type": "code",
                            "confidence": "high",
                            "detail": f"Imports {fw_name} module '{imp.module}'",
                        })
                    break

    # 2. Check source evidence records from knowledge
    for ev in getattr(knowledge, "source_evidence", []):
        fp = getattr(ev, "file_path", "")
        if fp in ("source_code", "manifest", "repository_analysis") or "*" in fp or "?" in fp:
            continue
        stmt = getattr(ev, "symbol_or_statement", "")
        if stmt and fw_lower in stmt.lower():
            if fp not in seen:
                seen.add(fp)
                matched.append({
                    "file_path": fp,
                    "evidence_type": getattr(ev, "evidence_type", "manifest_dependency"),
                    "confidence": getattr(ev, "confidence", "high"),
                    "detail": stmt,
                })

    # 3. Check manifest important files
    for imp_f in getattr(knowledge, "important_files", []):
        rp = getattr(imp_f, "relative_path", "")
        if getattr(imp_f, "category", "") == "manifest" or (imp_f.reason and fw_lower in imp_f.reason.lower()):
            if rp not in seen and rp:
                seen.add(rp)
                matched.append({
                    "file_path": rp,
                    "evidence_type": "manifest",
                    "confidence": "high",
                    "detail": imp_f.reason or f"Manifest dependency for {fw_name}",
                })

    # 4. Check directory tree for standard manifests
    if not matched:
        manifest_candidates = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "requirements.txt")
        known_files: Set[str] = set()
        if (
            hasattr(knowledge, "repository_structure")
            and knowledge.repository_structure
            and getattr(knowledge.repository_structure, "directory_tree", None) is not None
        ):
            def traverse(node: Any) -> None:
                if not node:
                    return
                if getattr(node, "type", "") == "file":
                    p = getattr(node, "path", "")
                    if p:
                        known_files.add(p)
                        known_files.add(os.path.basename(p))
                for child in getattr(node, "children", []) or []:
                    traverse(child)

            traverse(knowledge.repository_structure.directory_tree)

        for mc in manifest_candidates:
            if mc in known_files and mc not in seen:
                seen.add(mc)
                matched.append({
                    "file_path": mc,
                    "evidence_type": "manifest",
                    "confidence": "medium",
                    "detail": f"Repository manifest declaring {fw_name}",
                })
                break

    return matched


def resolve_technology_evidence(
    tech_name: str,
    category: str,
    knowledge: RepositoryKnowledge,
) -> List[EvidenceReference]:
    """
    Resolves concrete repository files as evidence for a technology or programming language.
    Never generates wildcard or synthetic paths. If no genuine evidence exists, returns [].
    """
    is_lang = (
        category.lower() == "language"
        or bool(get_language_extensions(tech_name))
    )
    if is_lang:
        real_files = find_actual_files_for_language(knowledge, tech_name)
        if real_files:
            return [
                EvidenceReference(
                    file_path=rf,
                    evidence_type="code",
                    confidence="high",
                    status="confirmed",
                    detail=f"Source file implementing {tech_name}",
                )
                for rf in real_files[:2]
            ]
        # Check for ecosystem manifest
        manifests = find_actual_manifests_for_language(knowledge, tech_name)
        if manifests:
            return [
                EvidenceReference(
                    file_path=manifests[0],
                    evidence_type="manifest",
                    confidence="medium",
                    status="confirmed",
                    detail=f"Manifest configuring {tech_name} ecosystem",
                )
            ]
        return []

    # Framework, tool, library, database
    fw_ev = find_actual_evidence_for_framework(knowledge, tech_name)
    if fw_ev:
        return [
            EvidenceReference(
                file_path=item["file_path"],
                evidence_type=item.get("evidence_type", "manifest"),
                confidence=item.get("confidence", "high"),
                status="confirmed",
                detail=item.get("detail", f"Evidence for {tech_name}"),
            )
            for item in fw_ev[:2]
        ]
    return []
