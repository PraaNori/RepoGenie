"""
Operation-Based Storage and External API Verifier.

Implements receiver-aware and semantics-aware verification:
1. Storage operations: Distinguishes read, write, delete, and unresolved.
   - SQL SELECT (read) vs INSERT/UPDATE (write) vs DELETE (delete).
   - open(..., 'w') (write) vs open(..., 'r') (read).
   - ORM .add()/.save() (write) vs .delete() (delete).
   - Bare .commit() without preceding write evidence does NOT establish a write.
2. External API operations:
   - Identifiable HTTP clients (requests, httpx, aiohttp, urllib, ClientSession).
   - Rejects ordinary dictionary/object methods (dict.get).
3. Language scope:
   - Deep AST verification is Python-only in this milestone.
   - Non-Python languages return conservative unresolved results.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple
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

# Known HTTP client receivers
HTTP_CLIENT_RECEIVERS: Set[str] = {
    "requests", "httpx", "aiohttp", "urllib", "client", "http_client", "session", "api_client"
}

# Known non-HTTP dictionary / map receivers to reject
DICT_RECEIVER_NAMES: Set[str] = {
    "dict", "d", "my_dict", "kwargs", "params", "config", "headers", "mapping", "map", "data"
}


class StorageVerificationResult:
    """Result of operation-based storage verification."""

    def __init__(
        self,
        storage_library_detected: bool = False,
        storage_operation_verified: bool = False,
        storage_operation_type: str = "none",  # "read", "write", "delete", "none"
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
    ) -> StorageVerificationResult:
        """
        Parses source code and identifies grounded storage reads, writes, and deletes.
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
        calls = self._collect_calls(tree.root_node)

        has_preceding_write = False
        saw_bare_commit = False
        verified_op_type = "none"
        observed_op: Optional[str] = None
        evidence_line: Optional[int] = None

        for call in calls:
            receiver, method, first_arg, second_arg, line = call

            # 1. SQL Database via .execute()
            if method == "execute":
                if not receiver or receiver.lower() in DB_RECEIVER_NAMES:
                    if first_arg:
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
                    # Unknown receiver for execute
                    pass

            # 2. ORM .add() or .save()
            elif method in ("add", "save") and (not receiver or receiver.lower() in ("session", "db", "repo")):
                has_preceding_write = True
                verified_op_type = "write"
                observed_op = f"ORM entity write via .{method}()"
                evidence_line = line
                break

            # 3. ORM .delete()
            elif method == "delete" and (not receiver or receiver.lower() in ("session", "db", "repo")):
                has_preceding_write = True
                verified_op_type = "delete"
                observed_op = "ORM entity delete via .delete()"
                evidence_line = line
                break

            # 4. ORM .commit()
            elif method == "commit" and (not receiver or receiver.lower() in ("session", "db", "conn")):
                saw_bare_commit = True

            # 5. File System open()
            elif method == "open" and not receiver:
                # Inspect mode argument (second_arg)
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

            # 6. File handle .write()
            elif method in ("write", "writelines") and receiver and receiver.lower() in ("f", "file", "fp", "handle", "out"):
                has_preceding_write = True
                verified_op_type = "write"
                observed_op = f"File write call via .{method}()"
                evidence_line = line
                break

            # 7. File handle .read()
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

        if saw_bare_commit and not has_preceding_write:
            # Bare commit without preceding write evidence does not establish persistence
            return StorageVerificationResult(
                storage_library_detected=True,
                storage_operation_verified=False,
                storage_operation_type="none",
                persistence_status="storage_library_imported_no_write_observed",
                persistence_detail="Bare .commit() observed without preceding database write or ORM .add() mutation.",
            )

        return StorageVerificationResult(
            storage_library_detected=False,
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
    ) -> ExternalAPIVerificationResult:
        """
        Parses source code and identifies grounded outbound HTTP/API requests.
        Rejects ordinary dictionary lookups (e.g. dict.get).
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
        calls = self._collect_calls(tree.root_node)

        for call in calls:
            receiver, method, first_arg, second_arg, line = call

            # Disqualify ordinary dictionary .get() calls
            if method == "get" and receiver and receiver.lower() in DICT_RECEIVER_NAMES:
                continue

            # Check HTTP methods on verified HTTP receivers
            if method in ("get", "post", "put", "patch", "delete", "request"):
                if receiver and (
                    receiver.lower() in HTTP_CLIENT_RECEIVERS
                    or "client" in receiver.lower()
                    or "session" in receiver.lower()
                    or "http" in receiver.lower()
                ):
                    clean_arg = first_arg.strip("'\"") if first_arg else ""
                    # Check if argument looks like a URL or endpoint path
                    is_url = bool(re.match(r"^(https?://|/|\{)", clean_arg)) or "url" in clean_arg.lower()
                    obs = f"Outbound HTTP {method.upper()} request via {receiver}.{method}()"
                    ev = [EvidenceReference(file_path=file_path, line_start=line, line_end=line, confidence="high")]
                    return ExternalAPIVerificationResult(
                        external_api_library_detected=True,
                        external_api_operation_verified=True,
                        external_api_operation_type="http_request",
                        external_api_status="external_api_operation_verified",
                        external_api_detail=obs,
                        observed_operation=obs,
                        supporting_evidence=ev,
                    )

            # urllib urlopen
            if method == "urlopen" and (not receiver or "urllib" in receiver.lower()):
                obs = "Outbound HTTP request via urllib.request.urlopen()"
                ev = [EvidenceReference(file_path=file_path, line_start=line, line_end=line, confidence="high")]
                return ExternalAPIVerificationResult(
                    external_api_library_detected=True,
                    external_api_operation_verified=True,
                    external_api_operation_type="http_request",
                    external_api_status="external_api_operation_verified",
                    external_api_detail=obs,
                    observed_operation=obs,
                    supporting_evidence=ev,
                )

        return ExternalAPIVerificationResult(
            external_api_library_detected=False,
            external_api_operation_verified=False,
            external_api_operation_type="none",
            external_api_status="no_external_api_operation_detected",
            external_api_detail="No outbound external API requests detected in code evidence.",
        )

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
