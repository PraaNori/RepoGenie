import os
import tempfile
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    ArchitectureAnalysisResult,
    ClassInfo,
    FunctionCallInfo,
    FunctionInfo,
    ImportInfo,
    MethodInfo,
    ParsedFile,
    ParsedRepository,
    RepoAnalysisResult,
    SourceLocation,
    StatusEnum,
)
from app.services.repo.architecture_analyzer import architecture_analyzer_service
from app.services.repo.call_graph_builder import call_graph_builder
from app.services.repo.component_classifier import component_classifier
from app.services.repo.dependency_resolver import dependency_resolver
from app.services.repo.entry_point_detector import entry_point_detector
from app.services.storage.job_store import job_store

client = TestClient(app)


def test_dependency_resolver_python_imports():
    internal_files = {
        "app/main.py",
        "app/services/user_service.py",
        "app/models/user.py",
        "app/utils/__init__.py",
        "app/utils/crypto.py",
    }

    # Python stdlib
    target, status, is_internal = dependency_resolver.resolve_python_import(
        "json", "app/main.py", internal_files
    )
    assert status == "external_package"
    assert is_internal is False
    assert target == "json"

    # Python relative import to subfolder
    target, status, is_internal = dependency_resolver.resolve_python_import(
        ".services.user_service", "app/main.py", internal_files
    )
    assert status == "resolved_internal"
    assert is_internal is True
    assert target == "app/services/user_service.py"

    # Python relative parent import
    target, status, is_internal = dependency_resolver.resolve_python_import(
        "..models.user", "app/services/user_service.py", internal_files
    )
    assert status == "resolved_internal"
    assert is_internal is True
    assert target == "app/models/user.py"

    # Python external package
    target, status, is_internal = dependency_resolver.resolve_python_import(
        "fastapi.routing", "app/main.py", internal_files
    )
    assert status == "external_package"
    assert is_internal is False
    assert target == "fastapi"


def test_dependency_resolver_js_ts_imports():
    internal_files = {
        "src/index.ts",
        "src/components/Header.tsx",
        "src/components/index.ts",
        "src/utils/helpers.js",
    }

    # Relative with extension
    target, status, is_internal = dependency_resolver.resolve_js_ts_import(
        "./components/Header", "src/index.ts", internal_files
    )
    assert status == "resolved_internal"
    assert is_internal is True
    assert target == "src/components/Header.tsx"

    # Relative to directory index file
    target, status, is_internal = dependency_resolver.resolve_js_ts_import(
        "./components", "src/index.ts", internal_files
    )
    assert status == "resolved_internal"
    assert is_internal is True
    assert target == "src/components/index.ts"

    # Scoped external package
    target, status, is_internal = dependency_resolver.resolve_js_ts_import(
        "@sindresorhus/is", "src/index.ts", internal_files
    )
    assert status == "external_package"
    assert is_internal is False
    assert target == "@sindresorhus/is"

    # Unscoped external package
    target, status, is_internal = dependency_resolver.resolve_js_ts_import(
        "react", "src/components/Header.tsx", internal_files
    )
    assert status == "external_package"
    assert is_internal is False
    assert target == "react"


def test_dependency_resolver_other_languages():
    internal_files = {
        "pkg/server/server.go",
        "include/common.h",
        "src/main.cpp",
        "src/models/User.rs",
        "com/example/app/Main.java",
    }

    # Go stdlib
    target, status, is_internal = dependency_resolver.resolve_go_import("fmt", "main.go", internal_files)
    assert status == "external_package"
    assert is_internal is False

    # C++ system header vs internal header
    target, status, is_internal = dependency_resolver.resolve_c_cpp_include("<iostream>", "src/main.cpp", internal_files)
    assert status == "external_package"

    target, status, is_internal = dependency_resolver.resolve_c_cpp_include('"common.h"', "src/main.cpp", internal_files)
    assert status == "resolved_internal"
    assert is_internal is True
    assert target == "include/common.h"

    # Rust std vs crate
    target, status, is_internal = dependency_resolver.resolve_rust_use("std::collections::HashMap", "src/main.rs", internal_files)
    assert status == "external_package"


def test_circular_dependency_detection():
    # Build graph with A -> B -> C -> A
    parsed_files = [
        ParsedFile(
            file_path="a.py",
            language="Python",
            status="success",
            imports=[ImportInfo(module=".b", symbols=[], file_path="a.py", line_number=1)],
        ),
        ParsedFile(
            file_path="b.py",
            language="Python",
            status="success",
            imports=[ImportInfo(module=".c", symbols=[], file_path="b.py", line_number=1)],
        ),
        ParsedFile(
            file_path="c.py",
            language="Python",
            status="success",
            imports=[ImportInfo(module=".a", symbols=[], file_path="c.py", line_number=1)],
        ),
    ]
    graph = dependency_resolver.build_dependency_graph(parsed_files, {"a.py", "b.py", "c.py"})
    assert graph.total_internal_dependencies == 3
    assert len(graph.circular_dependencies) >= 1
    cycle = graph.circular_dependencies[0]
    assert "a.py" in cycle and "b.py" in cycle and "c.py" in cycle


def test_call_graph_builder():
    dummy_loc = SourceLocation(file_path="service.py", start_line=1, start_column=0, end_line=5, end_column=0)
    parsed_files = [
        ParsedFile(
            file_path="service.py",
            language="Python",
            status="success",
            functions=[
                FunctionInfo(name="calculate_total", file_path="service.py", location=dummy_loc),
                FunctionInfo(name="process_order", file_path="service.py", location=dummy_loc),
            ],
            classes=[
                ClassInfo(name="OrderProcessor", file_path="service.py", location=dummy_loc, methods=["process"])
            ],
            methods=[
                MethodInfo(name="process", parent_class="OrderProcessor", file_path="service.py", location=dummy_loc)
            ],
            function_calls=[
                # Same-file function call
                FunctionCallInfo(call_name="calculate_total", enclosing_scope="process_order", file_path="service.py", line_number=3),
                # Method call
                FunctionCallInfo(call_name="self.process", enclosing_scope="OrderProcessor.run", file_path="service.py", line_number=10),
                # External / Unresolved call
                FunctionCallInfo(call_name="external_api_call", enclosing_scope="process_order", file_path="service.py", line_number=4),
            ],
        ),
    ]

    call_graph = call_graph_builder.build_call_graph(parsed_files, {"service.py"})
    assert call_graph.total_resolved_calls >= 1
    resolved_edges = [e for e in call_graph.edges if e.resolution_status == "resolved_internal"]
    assert len(resolved_edges) >= 1
    assert any(e.call_name == "calculate_total" for e in resolved_edges)


def test_entry_point_detector_and_tempfile():
    dummy_loc = SourceLocation(file_path="main.py", start_line=1, start_column=0, end_line=5, end_column=0)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a python main file with guard
        main_py = os.path.join(tmpdir, "main.py")
        with open(main_py, "w") as f:
            f.write('def run(): pass\nif __name__ == "__main__":\n    run()\n')

        parsed_files = [
            ParsedFile(
                file_path="main.py",
                language="Python",
                status="success",
                functions=[FunctionInfo(name="run", file_path="main.py", location=dummy_loc)],
            ),
            ParsedFile(
                file_path="main.go",
                language="Go",
                status="success",
                functions=[FunctionInfo(name="main", file_path="main.go", location=SourceLocation(file_path="main.go", start_line=1, start_column=0, end_line=3, end_column=0))],
            ),
        ]

        candidates = entry_point_detector.detect_entry_points(parsed_files, local_path=tmpdir)
        types = {c.entry_type for c in candidates}
        assert "python_main_guard" in types
        assert "go_main" in types
        high_confs = [c for c in candidates if c.confidence == "high"]
        assert len(high_confs) >= 2


def test_component_classifier():
    dummy_loc = SourceLocation(file_path="dummy.py", start_line=1, start_column=0, end_line=5, end_column=0)
    parsed_files = [
        ParsedFile(file_path="tests/test_auth.py", language="Python", status="success"),
        ParsedFile(file_path="app/config/settings.py", language="Python", status="success"),
        ParsedFile(file_path="src/components/Button.tsx", language="TypeScript", status="success"),
        ParsedFile(file_path="app/api/routes/users.py", language="Python", status="success"),
        ParsedFile(file_path="app/services/payment_service.py", language="Python", status="success"),
        ParsedFile(file_path="app/repository/user_repo.py", language="Python", status="success"),
        ParsedFile(file_path="app/db/migrations.sql", language="SQL", status="success"),
        ParsedFile(
            file_path="app/models/user.py",
            language="Python",
            status="success",
            classes=[ClassInfo(name="User", file_path="app/models/user.py", location=dummy_loc, base_classes=["BaseModel"])],
        ),
        ParsedFile(file_path="app/integrations/stripe_client.py", language="Python", status="success"),
        ParsedFile(file_path="app/utils/string_helpers.py", language="Python", status="success"),
        ParsedFile(file_path="random_scratch_notes.txt", language="Text", status="success"),
    ]

    components = component_classifier.classify_components(parsed_files, entry_points=[])
    categories = {c.file_path: c.category for c in components}

    assert categories["tests/test_auth.py"] == "test"
    assert categories["app/config/settings.py"] == "configuration"
    assert categories["src/components/Button.tsx"] == "frontend"
    assert categories["app/api/routes/users.py"] == "api_route"
    assert categories["app/services/payment_service.py"] == "service"
    assert categories["app/repository/user_repo.py"] == "repository_or_dao"
    assert categories["app/db/migrations.sql"] == "database"
    assert categories["app/models/user.py"] == "model"
    assert categories["app/integrations/stripe_client.py"] == "external_integration"
    assert categories["app/utils/string_helpers.py"] == "utility"
    assert categories["random_scratch_notes.txt"] == "unknown"


def test_architecture_analyzer_orchestration():
    dummy_loc = SourceLocation(file_path="app/models.py", start_line=1, start_column=0, end_line=5, end_column=0)
    parsed_files = [
        ParsedFile(
            file_path="app/models.py",
            language="Python",
            status="success",
            classes=[
                ClassInfo(name="BaseEntity", file_path="app/models.py", location=dummy_loc),
                ClassInfo(name="User", file_path="app/models.py", location=dummy_loc, base_classes=["BaseEntity"]),
            ],
        ),
        ParsedFile(
            file_path="app/service.py",
            language="Python",
            status="success",
            imports=[ImportInfo(module=".models", symbols=["User"], file_path="app/service.py", line_number=1)],
            functions=[
                FunctionInfo(
                    name="create_user",
                    file_path="app/service.py",
                    parameters=["user_data: User"],
                    location=SourceLocation(file_path="app/service.py", start_line=1, start_column=0, end_line=5, end_column=0),
                )
            ],
            function_calls=[
                FunctionCallInfo(call_name="User", enclosing_scope="create_user", file_path="app/service.py", line_number=3)
            ],
        ),
    ]

    parsed_repo = ParsedRepository(
        job_id="test-job",
        repository_name="test-repo",
        total_parsed_files=2,
        total_functions=1,
        total_classes=2,
        total_methods=0,
        total_imports=1,
        total_function_calls=1,
        supported_languages=["Python"],
        files=parsed_files,
    )

    result = architecture_analyzer_service.analyze_architecture(
        job_id="test-job",
        repo_name="test-repo",
        parsed_repo=parsed_repo,
    )

    assert isinstance(result, ArchitectureAnalysisResult)
    assert result.dependency_graph.total_internal_dependencies >= 1
    # Check inheritance
    assert len(result.inheritance_relationships) == 1
    assert result.inheritance_relationships[0].child_class == "User"
    assert result.inheritance_relationships[0].parent_class == "BaseEntity"
    assert result.inheritance_relationships[0].resolution_status == "resolved_internal"
    # Check class references
    assert len(result.class_references) >= 1
    assert result.class_references[0].referenced_class == "User"
    # Check component counts
    assert "model" in result.component_counts
    assert "service" in result.component_counts


def test_get_architecture_api_endpoints():
    # 1. Non-existent job
    resp = client.get("/api/v1/jobs/non-existent-uuid/architecture")
    assert resp.status_code == 404

    # 2. Create job in store directly
    job = job_store.create_job(
        repo_url="https://github.com/fastapi/fastapi",
        repo_name="fastapi/fastapi",
        repository_owner="fastapi",
        repository_name="fastapi",
        clone_url="https://github.com/fastapi/fastapi.git",
    )
    job_id = job.job_id

    # In progress status returns 409
    job_store.update_job_code_parsing_started(job_id)
    arch_resp = client.get(f"/api/v1/jobs/{job_id}/architecture")
    assert arch_resp.status_code == 409

    # Directly mark stages 0 and 1 completed and inject completed architecture into job store, verify 200 OK
    internal = job_store.get_internal_job(job_id)
    assert internal is not None
    internal.ingestion_status = StatusEnum.COMPLETED
    internal.stages[0].status = StatusEnum.COMPLETED
    internal.stages[1].status = StatusEnum.COMPLETED
    dummy_arch = ArchitectureAnalysisResult(
        job_id=job_id,
        repository_name="fastapi/fastapi",
        dependency_graph=dependency_resolver.build_dependency_graph([], set()),
        call_graph=call_graph_builder.build_call_graph([], set()),
        inheritance_relationships=[],
        class_references=[],
        entry_points=[],
        components=[],
        component_counts={"model": 1, "service": 1},
        analysis_status=StatusEnum.COMPLETED,
        warnings=[],
    )
    internal.architecture = dummy_arch
    internal.stages[2].status = StatusEnum.COMPLETED

    ok_resp = client.get(f"/api/v1/jobs/{job_id}/architecture")
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["job_id"] == job_id
    assert "dependency_graph" in data
    assert "call_graph" in data
    assert "component_counts" in data
    assert data["component_counts"] == {"model": 1, "service": 1}
