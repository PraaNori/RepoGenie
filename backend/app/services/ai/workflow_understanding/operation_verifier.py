"""
Operation-Based Storage and External API Verifier.

Implements receiver-aware and semantics-aware verification:
1. Storage operations: Distinguishes read, write, delete, and unresolved.
   - SQL SELECT (read) vs INSERT/UPDATE (write) vs DELETE (delete).
   - open(..., 'w') (write) vs open(..., 'r') (read).
   - ORM .add()/.save() (write) vs .delete() (delete).
   - Dynamic/unresolved SQL query expressions -> 'unresolved_dynamic_sql'.
   - Bare .commit() without preceding write evidence does NOT establish a write.
   - Eliminates receiver-name false positives without supporting import evidence.
2. External API operations:
   - Identifiable HTTP clients (requests, httpx, aiohttp, urllib, boto3, stripe, etc.).
   - Explicitly establishes HTTP client identity backed by import evidence and aliases.
   - Rejects arbitrary or generic object/dictionary methods (.get()).
   - Uses verified terminology: 'statically identified outbound HTTP operation'.
3. Language scope:
   - Deep AST verification is Python-only in this milestone.
   - Non-Python languages return conservative unresolved results.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import tree_sitter
import tree_sitter_python as tspython

from ..project_understanding.schemas import EvidenceReference

logger = logging.getLogger(__name__)

# Known SQL write and query patterns
SQL_READ_PATTERN = re.compile(r"^\s*(SELECT|PRAGMA|EXPLAIN)\b", re.IGNORECASE)
SQL_WRITE_PATTERN = re.compile(r"^\s*(INSERT\s+INTO|UPDATE|CREATE\s+TABLE|ALTER\s+TABLE)\b", re.IGNORECASE)
SQL_DELETE_PATTERN = re.compile(r"^\s*(DELETE\s+FROM|DROP\s+TABLE|TRUNCATE)\b", re.IGNORECASE)

# Known database receiver names
DB_RECEIVER_NAMES: Set[str] = {
    "cursor", "cur", "session", "db", "conn", "connection", "engine", "client", "repo", "repository"
}

# Recognized persistent database and ORM libraries
DB_OR_ORM_LIBRARIES: Set[str] = {
    "sqlite3",
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pymongo",
    "motor",
    "tortoise",
    "peewee",
    "django",
    "django.db",
    "databases",
    "redis",
    "aioredis",
    "mysql",
    "mysql.connector",
    "aiomysql",
    "sqlmodel",
    "pony",
    "tinydb",
    "alembic",
}

# Recognized ORM-specific libraries
ORM_LIBRARIES: Set[str] = {
    "sqlalchemy",
    "sqlalchemy.orm",
    "django",
    "django.db.models",
    "tortoise",
    "peewee",
    "sqlmodel",
    "pony",
    "mongoengine",
}

# Recognized HTTP client libraries
HTTP_LIBRARIES: Set[str] = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "urllib.request",
    "urllib3",
    "boto3",
    "botocore",
    "google.cloud",
    "stripe",
    "openai",
    "anthropic",
}

# Known non-HTTP dictionary / map receivers to reject
DICT_RECEIVER_NAMES: Set[str] = {
    "dict", "d", "my_dict", "kwargs", "params", "config", "headers", "mapping", "map", "data", "row", "item"
}


class StorageVerificationResult:
    """Result of operation-based storage verification."""

    def __init__(
        self,
        storage_library_detected: bool = False,
        storage_operation_verified: bool = False,
        storage_operation_type: str = "none",  # "read", "write", "delete", "unresolved", "none"
        persistence_status: str = "no_storage_operation_detected",
        persistence_detail: Optional[str] = None,
        observed_operation: Optional[str] = None,
        supporting_evidence: Optional[List[EvidenceReference]] = None,
    ):
        self.storage_library_detected = storage_library_detected
        self.storage_operation_verified = storage_operation_verified
        self.storage_operation_type = storage_operation_type
        self.persistence_status = persistence_status
        self.persistence_detail = persistence_detail
        self.observed_operation = observed_operation
        self.supporting_evidence = supporting_evidence or []

    def to_dict(self) -> Dict[str, object]:
        return {
            "storage_library_detected": self.storage_library_detected,
            "storage_operation_verified": self.storage_operation_verified,
            "storage_operation_type": self.storage_operation_type,
            "persistence_status": self.persistence_status,
            "persistence_detail": self.persistence_detail,
            "observed_operation": self.observed_operation,
        }


class ExternalAPIVerificationResult:
    """Result of operation-based external API verification."""

    def __init__(
        self,
        external_api_library_detected: bool = False,
        external_api_operation_verified: bool = False,
        external_api_operation_type: str = "none",  # "http_request", "none"
        external_api_status: str = "no_external_api_operation_detected",
        external_api_detail: Optional[str] = None,
        observed_operation: Optional[str] = None,
        supporting_evidence: Optional[List[EvidenceReference]] = None,
    ):
        self.external_api_library_detected = external_api_library_detected
        self.external_api_operation_verified = external_api_operation_verified
        self.external_api_operation_type = external_api_operation_type
        self.external_api_status = external_api_status
        self.external_api_detail = external_api_detail
        self.observed_operation = observed_operation
        self.supporting_evidence = supporting_evidence or []

    def to_dict(self) -> Dict[str, object]:
        return {
            "external_api_library_detected": self.external_api_library_detected,
            "external_api_operation_verified": self.external_api_operation_verified,
            "external_api_operation_type": self.external_api_operation_type,
            "external_api_status": self.external_api_status,
            "external_api_detail": self.external_api_detail,
            "observed_operation": self.observed_operation,
        }


class OperationVerifier:
    """
    Verifies storage and external API operations by analyzing call receivers,
    method semantics, and argument literals in Python source code.
    """

    def __init__(self):
        self._language = tree_sitter.Language(tspython.language())
        self._parser = tree_sitter.Parser(self._language)

    def verify_storage_in_code(
        self,
        source_code: str,
        file_path: str = "source.py",
        language: str = "Python",
        file_imports: Optional[Union[Set[str], List[str], List[Any]]] = None,
    ) -> StorageVerificationResult:
        """
        Parses source code and identifies grounded storage reads, writes, and deletes.
        Requires import evidence before treating variable names as database connections.
        Non-Python languages receive conservative unresolved results.
        """
        if language.lower() not in ("python", "py"):
            return StorageVerificationResult(
                storage_library_detected=False,
                storage_operation_verified=False,
                storage_operation_type="none",
                persistence_status="no_storage_operation_detected",
                persistence_detail=f"Language '{language}': deep AST storage verification is supported for Python in Milestone 3.4.",
            )

        tree = self._parser.parse(source_code.encode("utf-8"))
        modules, aliases = self._extract_imports(tree.root_node, file_imports)
        calls = self._collect_calls(tree.root_node)

        has_db_lib = bool(modules.intersection(DB_OR_ORM_LIBRARIES) or any(any(lib in v for lib in DB_OR_ORM_LIBRARIES) for v in aliases.values()))
        has_orm_lib = bool(modules.intersection(ORM_LIBRARIES) or any(any(lib in v for lib in ORM_LIBRARIES) for v in aliases.values()))
        has_os = "os" in modules
        has_pathlib = "pathlib" in modules or "Path" in aliases
        has_shutil = "shutil" in modules

        has_preceding_write = False
        saw_bare_commit = False
        saw_unresolved_sql = False
        unresolved_sql_detail: Optional[str] = None
        verified_op_type = "none"
        observed_op: Optional[str] = None
        evidence_line: Optional[int] = None

        for call in calls:
            receiver, method, first_arg, second_arg, line = call

            # 1. SQL Database via .execute()
            if method == "execute":
                # Must have database library import evidence to accept receiver as database connection
                if has_db_lib and (not receiver or receiver.lower() in DB_RECEIVER_NAMES):
                    if first_arg and (first_arg.startswith(('"', "'"))):
                        clean_sql = first_arg.strip("'\"")
                        if SQL_WRITE_PATTERN.search(clean_sql):
                            has_preceding_write = True
                            verified_op_type = "write"
                            observed_op = f"Database SQL write: '{clean_sql[:50]}...'"
                            evidence_line = line
                            break
                        elif SQL_DELETE_PATTERN.search(clean_sql):
                            has_preceding_write = True
                            verified_op_type = "delete"
                            observed_op = f"Database SQL delete: '{clean_sql[:50]}...'"
                            evidence_line = line
                            break
                        elif SQL_READ_PATTERN.search(clean_sql):
                            if verified_op_type == "none":
                                verified_op_type = "read"
                                observed_op = f"Database SQL query (read-only): '{clean_sql[:50]}...'"
                                evidence_line = line
                        else:
                            saw_unresolved_sql = True
                            unresolved_sql_detail = f"Unrecognized SQL statement command type: '{clean_sql[:40]}'"
                            evidence_line = line
                    else:
                        # Dynamic SQL variable or formatting expression
                        saw_unresolved_sql = True
                        unresolved_sql_detail = f"Dynamic or unresolved SQL query expression passed to .execute(): {first_arg}"
                        evidence_line = line

            # 2. ORM .add() or .save() - Requires ORM library import evidence
            elif method in ("add", "save") and has_orm_lib and (receiver and receiver.lower() in ("session", "db", "db.session", "repo")):
                has_preceding_write = True
                verified_op_type = "write"
                observed_op = f"ORM entity write via .{method}()"
                evidence_line = line
                break

            # 3. ORM .delete() - Requires ORM library import evidence
            elif method == "delete" and has_orm_lib and (receiver and receiver.lower() in ("session", "db", "db.session", "repo")):
                has_preceding_write = True
                verified_op_type = "delete"
                observed_op = "ORM entity delete via .delete()"
                evidence_line = line
                break

            # 4. ORM .commit() - Requires database/ORM library import evidence
            elif method == "commit" and has_db_lib and (receiver and receiver.lower() in ("session", "db", "db.session", "conn")):
                saw_bare_commit = True
                evidence_line = line

            # 5. File System open()
            elif method == "open" and not receiver:
                mode = second_arg.strip("'\"").lower() if second_arg else "r"
                if any(m in mode for m in ("w", "a", "x")):
                    has_preceding_write = True
                    verified_op_type = "write"
                    observed_op = f"File system write: open(..., mode='{mode}')"
                    evidence_line = line
                    break
                elif "r" in mode:
                    if verified_op_type == "none":
                        verified_op_type = "read"
                        observed_op = f"File system read: open(..., mode='{mode}')"
                        evidence_line = line

            # 6. Path.write_text() / Path.write_bytes()
            elif method in ("write_text", "write_bytes") and (has_pathlib or (receiver and "path" in receiver.lower())):
                has_preceding_write = True
                verified_op_type = "write"
                observed_op = f"File system write via Path.{method}()"
                evidence_line = line
                break

            # 7. Path.read_text() / Path.read_bytes()
            elif method in ("read_text", "read_bytes") and (has_pathlib or (receiver and "path" in receiver.lower())):
                if verified_op_type == "none":
                    verified_op_type = "read"
                    observed_op = f"File system read via Path.{method}()"
                    evidence_line = line

            # 8. File deletion: os.remove() / os.unlink()
            elif method in ("remove", "unlink") and (receiver == "os" or (has_os and receiver in ("os", "pathlib"))):
                has_preceding_write = True
                verified_op_type = "delete"
                observed_op = f"File system deletion via os.{method}()"
                evidence_line = line
                break

            # 9. Path.unlink()
            elif method == "unlink" and (has_pathlib or (receiver and "path" in receiver.lower())):
                has_preceding_write = True
                verified_op_type = "delete"
                observed_op = "File system deletion via Path.unlink()"
                evidence_line = line
                break

            # 10. Directory deletion: shutil.rmtree()
            elif method == "rmtree" and (receiver == "shutil" or has_shutil):
                has_preceding_write = True
                verified_op_type = "delete"
                observed_op = "File directory tree deletion via shutil.rmtree()"
                evidence_line = line
                break

            # 11. File handle .write()
            elif method in ("write", "writelines") and receiver and receiver.lower() in ("f", "file", "fp", "handle", "out"):
                has_preceding_write = True
                verified_op_type = "write"
                observed_op = f"File write call via .{method}()"
                evidence_line = line
                break

            # 12. File handle .read()
            elif method in ("read", "readline", "readlines") and receiver and receiver.lower() in ("f", "file", "fp", "handle", "in_file"):
                if verified_op_type == "none":
                    verified_op_type = "read"
                    observed_op = f"File read call via .{method}()"
                    evidence_line = line

        # Final evaluation
        if verified_op_type in ("write", "delete"):
            ev = [EvidenceReference(file_path=file_path, line_start=evidence_line, line_end=evidence_line, confidence="high")] if evidence_line else []
            return StorageVerificationResult(
                storage_library_detected=True,
                storage_operation_verified=True,
                storage_operation_type=verified_op_type,
                persistence_status="storage_operation_verified",
                persistence_detail=f"Verified {verified_op_type} operation: {observed_op}",
                observed_operation=observed_op,
                supporting_evidence=ev,
            )

        if verified_op_type == "read":
            ev = [EvidenceReference(file_path=file_path, line_start=evidence_line, line_end=evidence_line, confidence="high")] if evidence_line else []
            return StorageVerificationResult(
                storage_library_detected=True,
                storage_operation_verified=True,
                storage_operation_type="read",
                persistence_status="storage_operation_verified",
                persistence_detail=f"Verified read-only query/read operation: {observed_op}",
                observed_operation=observed_op,
                supporting_evidence=ev,
            )

        if saw_unresolved_sql:
            return StorageVerificationResult(
                storage_library_detected=True,
                storage_operation_verified=False,
                storage_operation_type="unresolved",
                persistence_status="unresolved_dynamic_sql",
                persistence_detail=unresolved_sql_detail or "Dynamic or unresolved SQL query expression passed to .execute().",
                observed_operation="Dynamic SQL execution",
            )

        if saw_bare_commit and not has_preceding_write:
            return StorageVerificationResult(
                storage_library_detected=True,
                storage_operation_verified=False,
                storage_operation_type="none",
                persistence_status="storage_library_imported_no_write_observed",
                persistence_detail="Bare .commit() observed without preceding database write or ORM .add() mutation.",
            )

        return StorageVerificationResult(
            storage_library_detected=has_db_lib or has_orm_lib,
            storage_operation_verified=False,
            storage_operation_type="none",
            persistence_status="no_storage_operation_detected",
            persistence_detail="No persistent database or file storage operations detected.",
        )

    def verify_external_api_in_code(
        self,
        source_code: str,
        file_path: str = "source.py",
        language: str = "Python",
        file_imports: Optional[Union[Set[str], List[str], List[Any]]] = None,
    ) -> ExternalAPIVerificationResult:
        """
        Parses source code and identifies grounded outbound HTTP/API requests.
        Requires import evidence establishing HTTP client identity.
        Rejects ordinary dictionary lookups (dict.get) and methods on arbitrary objects.
        """
        if language.lower() not in ("python", "py"):
            return ExternalAPIVerificationResult(
                external_api_library_detected=False,
                external_api_operation_verified=False,
                external_api_operation_type="none",
                external_api_status="no_external_api_operation_detected",
                external_api_detail=f"Language '{language}': deep external API verification is supported for Python in Milestone 3.4.",
            )

        tree = self._parser.parse(source_code.encode("utf-8"))
        modules, aliases = self._extract_imports(tree.root_node, file_imports)
        calls = self._collect_calls(tree.root_node)

        http_modules = modules.intersection(HTTP_LIBRARIES)
        http_aliases = {k: v for k, v in aliases.items() if any(lib in v for lib in HTTP_LIBRARIES)}
        has_http_lib = bool(http_modules or http_aliases)

        for call in calls:
            receiver, method, first_arg, second_arg, line = call

            # Disqualify ordinary dictionary .get() calls
            if method == "get" and receiver and receiver.lower() in DICT_RECEIVER_NAMES:
                continue

            # Verify that receiver establishes genuine HTTP client identity backed by import evidence
            is_http_receiver = False

            if receiver and (receiver in HTTP_LIBRARIES or receiver.split(".")[0] in HTTP_LIBRARIES):
                is_http_receiver = True
            elif receiver and receiver in http_aliases:
                is_http_receiver = True
            elif has_http_lib and receiver and receiver.lower() in ("client", "http_client", "session", "api_client", "http"):
                is_http_receiver = True
            elif (receiver is None or receiver in ("urllib", "urllib.request")) and method == "urlopen" and ("urllib" in modules or "urllib.request" in modules or "urlopen" in aliases):
                is_http_receiver = True

            if not is_http_receiver:
                # Arbitrary object calling .get() or .post() without HTTP client evidence is rejected
                continue

            # Check HTTP methods on verified HTTP receivers
            if method in ("get", "post", "put", "patch", "delete", "request", "urlopen"):
                caller_desc = f"{receiver}.{method}()" if receiver else f"{method}()"
                obs = f"statically identified outbound HTTP operation: {caller_desc}"
                detail = f"statically identified outbound HTTP operation via {caller_desc}"
                ev = [EvidenceReference(file_path=file_path, line_start=line, line_end=line, confidence="high")]
                return ExternalAPIVerificationResult(
                    external_api_library_detected=True,
                    external_api_operation_verified=True,
                    external_api_operation_type="http_request",
                    external_api_status="external_api_operation_verified",
                    external_api_detail=detail,
                    observed_operation=obs,
                    supporting_evidence=ev,
                )

        return ExternalAPIVerificationResult(
            external_api_library_detected=has_http_lib,
            external_api_operation_verified=False,
            external_api_operation_type="none",
            external_api_status="no_external_api_operation_detected",
            external_api_detail="No outbound external API requests detected in code evidence.",
        )

    def _extract_imports(
        self,
        root_node: tree_sitter.Node,
        file_imports: Optional[Union[Set[str], List[str], List[Any]]] = None,
    ) -> Tuple[Set[str], Dict[str, str]]:
        """Extracts imported module names and aliases from AST and optional file_imports."""
        modules: Set[str] = set()
        aliases: Dict[str, str] = {}

        # 1. Inspect AST for import statements
        stack = [root_node]
        while stack:
            n = stack.pop()
            if n.type == "import_statement":
                for child in n.children:
                    if child.type == "dotted_name":
                        mod = child.text.decode("utf-8", errors="replace")
                        modules.add(mod)
                        modules.add(mod.split(".")[0])
                    elif child.type == "aliased_import":
                        name_n = child.child_by_field_name("name")
                        alias_n = child.child_by_field_name("alias")
                        if name_n and alias_n:
                            mod = name_n.text.decode("utf-8", errors="replace")
                            alias = alias_n.text.decode("utf-8", errors="replace")
                            modules.add(mod)
                            modules.add(mod.split(".")[0])
                            aliases[alias] = mod
            elif n.type == "import_from_statement":
                mod_n = n.child_by_field_name("module_name")
                mod_name = mod_n.text.decode("utf-8", errors="replace") if mod_n else ""
                if mod_name:
                    modules.add(mod_name)
                    modules.add(mod_name.split(".")[0])

                seen_import_kw = False
                for child in n.children:
                    if child.type == "import":
                        seen_import_kw = True
                        continue
                    if not seen_import_kw:
                        continue
                    if child.type == "aliased_import":
                        name_n = child.child_by_field_name("name")
                        alias_n = child.child_by_field_name("alias")
                        if name_n and alias_n:
                            sym = name_n.text.decode("utf-8", errors="replace")
                            alias = alias_n.text.decode("utf-8", errors="replace")
                            full = f"{mod_name}.{sym}" if mod_name else sym
                            aliases[alias] = full
                    elif child.type in ("dotted_name", "identifier"):
                        sym = child.text.decode("utf-8", errors="replace")
                        full = f"{mod_name}.{sym}" if mod_name else sym
                        aliases[sym] = full

            for c in reversed(n.children):
                stack.append(c)

        # 2. Add external file_imports if provided
        if file_imports:
            for item in file_imports:
                if isinstance(item, str):
                    modules.add(item)
                    modules.add(item.split(".")[0])
                elif hasattr(item, "module"):
                    mod = getattr(item, "module", "")
                    alias = getattr(item, "alias", None)
                    if mod:
                        modules.add(mod)
                        modules.add(mod.split(".")[0])
                    if alias:
                        aliases[alias] = mod

        return modules, aliases

    def _collect_calls(
        self, root_node: tree_sitter.Node
    ) -> List[Tuple[Optional[str], str, Optional[str], Optional[str], int]]:
        """Collects (receiver, method, first_arg, second_arg, line) for all call expressions."""
        calls: List[Tuple[Optional[str], str, Optional[str], Optional[str], int]] = []

        stack = [root_node]
        while stack:
            n = stack.pop()
            if n.type == "call":
                func_n = n.child_by_field_name("function") or (n.children[0] if n.children else None)
                args_n = n.child_by_field_name("arguments")
                line = n.start_point.row + 1

                receiver: Optional[str] = None
                method: str = ""

                if func_n:
                    if func_n.type == "attribute":
                        obj_n = func_n.child_by_field_name("object") or (func_n.children[0] if func_n.children else None)
                        attr_n = func_n.child_by_field_name("attribute") or (func_n.children[-1] if func_n.children else None)
                        receiver = obj_n.text.decode("utf-8", errors="replace") if obj_n else None
                        method = attr_n.text.decode("utf-8", errors="replace") if attr_n else ""
                    else:
                        method = func_n.text.decode("utf-8", errors="replace")

                first_arg: Optional[str] = None
                second_arg: Optional[str] = None

                if args_n:
                    arg_children = [c for c in args_n.children if c.type not in ("(", ")", ",")]
                    if len(arg_children) > 0:
                        first_arg = arg_children[0].text.decode("utf-8", errors="replace")
                    if len(arg_children) > 1:
                        second_arg = arg_children[1].text.decode("utf-8", errors="replace")

                calls.append((receiver, method, first_arg, second_arg, line))

            for c in reversed(n.children):
                stack.append(c)

        return calls


operation_verifier = OperationVerifier()
