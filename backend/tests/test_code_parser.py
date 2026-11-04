import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import StatusEnum
from app.services.repo.code_parser import CodeParserService
from app.services.repo.parsers.c_parser import CParser
from app.services.repo.parsers.cpp_parser import CppParser
from app.services.repo.parsers.go_parser import GoParser
from app.services.repo.parsers.java_parser import JavaParser
from app.services.repo.parsers.javascript_parser import JavaScriptParser
from app.services.repo.parsers.python_parser import PythonParser
from app.services.repo.parsers.rust_parser import RustParser
from app.services.repo.parsers.typescript_parser import TypeScriptParser
from app.services.storage.job_store import job_store

client = TestClient(app)

# ---------------------------------------------------------------------------
# 1. Python Parser Tests
# ---------------------------------------------------------------------------

def test_python_parser_comprehensive():
    parser = PythonParser()
    code = b"""import os
from sys import argv, exit as sys_exit

class Animal:
    def __init__(self, name: str):
        self.name = name

class Dog(Animal):
    def speak(self) -> str:
        print("bark")
        return "bark"

    class NestedHelper:
        def assist(self):
            pass

async def fetch_data(url: str, timeout: int = 5) -> dict:
    res = await client.get(url)
    return res

def simple():
    pass
"""
    res = parser.parse_file(code, "test.py")
    assert res.status == "success"
    assert len(res.classes) == 3  # Animal, NestedHelper, Dog
    class_names = [c.name for c in res.classes]
    assert "Animal" in class_names
    assert "Dog" in class_names
    assert "NestedHelper" in class_names

    # Check inheritance
    dog_class = next(c for c in res.classes if c.name == "Dog")
    assert "Animal" in dog_class.base_classes
    assert "speak" in dog_class.methods
    assert "NestedHelper" in dog_class.nested_classes

    # Check methods
    method_names = [m.name for m in res.methods]
    assert "__init__" in method_names
    assert "speak" in method_names
    assert "assist" in method_names
    speak_m = next(m for m in res.methods if m.name == "speak")
    assert speak_m.parent_class == "Dog"
    assert speak_m.return_type == "str"

    # Check functions
    fn_names = [f.name for f in res.functions]
    assert "fetch_data" in fn_names
    assert "simple" in fn_names
    fetch_fn = next(f for f in res.functions if f.name == "fetch_data")
    assert fetch_fn.is_async is True
    assert fetch_fn.return_type == "dict"
    assert len(fetch_fn.parameters) == 2

    # Check imports
    assert any(i.module == "os" for i in res.imports)
    assert any(i.module == "sys" and "argv" in i.symbols for i in res.imports)

    # Check function calls
    call_names = [c.call_name for c in res.function_calls]
    assert "print" in call_names

# ---------------------------------------------------------------------------
# 2. JavaScript Parser Tests
# ---------------------------------------------------------------------------

def test_javascript_parser_comprehensive():
    parser = JavaScriptParser()
    code = b"""import React, { useState, useEffect as useEff } from "react";
const utils = require("./utils");

class ComponentBase extends Object {
    constructor(props) {
        super(props);
    }
    async renderContent(id) {
        console.log("rendering", id);
        return id;
    }
}

function standalone(x, y) {
    return x + y;
}

const arrowFunc = async (val) => {
    helper(val);
};
"""
    res = parser.parse_file(code, "app.js")
    assert res.status == "success"
    assert len(res.classes) == 1
    assert res.classes[0].name == "ComponentBase"
    assert "Object" in res.classes[0].base_classes
    assert "constructor" in res.classes[0].methods
    assert "renderContent" in res.classes[0].methods

    # Methods
    render_m = next(m for m in res.methods if m.name == "renderContent")
    assert render_m.is_async is True
    assert render_m.parent_class == "ComponentBase"

    # Functions
    fn_names = [f.name for f in res.functions]
    assert "standalone" in fn_names
    assert "arrowFunc" in fn_names
    arrow_f = next(f for f in res.functions if f.name == "arrowFunc")
    assert arrow_f.is_async is True

    # Imports (both ESM and CommonJS require)
    assert any(i.module == "react" for i in res.imports)
    assert any(i.module == "./utils" for i in res.imports)

    # Calls
    call_names = [c.call_name for c in res.function_calls]
    assert "console.log" in call_names or "super" in call_names or "helper" in call_names

# ---------------------------------------------------------------------------
# 3. TypeScript Parser Tests
# ---------------------------------------------------------------------------

def test_typescript_parser_comprehensive():
    parser = TypeScriptParser()
    code = b"""import { User } from "./models";

export interface IService {
    getUser(id: string): Promise<User>;
}

export class UserService implements IService {
    private apiKey: string;
    constructor(apiKey: string) {
        this.apiKey = apiKey;
    }
    public async getUser(id: string): Promise<User> {
        return fetchUser(id);
    }
}

export function formatUser(u: User): string {
    return u.name;
}
"""
    res = parser.parse_file(code, "service.ts")
    assert res.status == "success"
    cls_names = [c.name for c in res.classes]
    assert "IService" in cls_names
    assert "UserService" in cls_names

    user_svc = next(c for c in res.classes if c.name == "UserService")
    assert "IService" in user_svc.base_classes
    assert "getUser" in user_svc.methods

    get_user_m = next(m for m in res.methods if m.name == "getUser")
    assert get_user_m.visibility == "public"
    assert get_user_m.is_async is True
    assert get_user_m.return_type is not None

    fn_names = [f.name for f in res.functions]
    assert "formatUser" in fn_names
    assert any(i.module == "./models" for i in res.imports)

# ---------------------------------------------------------------------------
# 4. Go, Rust, Java, C, C++ Tests
# ---------------------------------------------------------------------------

def test_go_parser():
    parser = GoParser()
    code = b"""package main
import (
    "fmt"
    alias "net/http"
)
type Server struct {
    port int
}
func (s *Server) Start() error {
    fmt.Println("start")
    return nil
}
func main() {
    s := &Server{port: 8080}
    s.Start()
}
"""
    res = parser.parse_file(code, "main.go")
    assert res.status == "success"
    assert any(c.name == "Server" for c in res.classes)
    assert any(m.name == "Start" and m.parent_class == "Server" for m in res.methods)
    assert any(f.name == "main" for f in res.functions)
    assert any(i.module == "fmt" for i in res.imports)
    assert any(i.module == "net/http" for i in res.imports)

def test_rust_parser():
    parser = RustParser()
    code = b"""use std::collections::HashMap;

pub struct Config {
    pub port: u16,
}
impl Config {
    pub fn new(port: u16) -> Self {
        Config { port }
    }
}
pub async fn run() {
    println!("running");
}
"""
    res = parser.parse_file(code, "lib.rs")
    assert res.status == "success"
    assert any(c.name == "Config" for c in res.classes)
    assert any(m.name == "new" and m.parent_class == "Config" for m in res.methods)
    run_fn = next(f for f in res.functions if f.name == "run")
    assert run_fn.is_async is True
    assert any(i.module == "std::collections::HashMap" for i in res.imports)

def test_java_parser():
    parser = JavaParser()
    code = b"""package com.example;
import java.util.List;

public class Employee extends Person implements Identifiable {
    private String id;
    public Employee(String id) {
        this.id = id;
    }
    public String getId() {
        System.out.println(id);
        return this.id;
    }
}
"""
    res = parser.parse_file(code, "Employee.java")
    assert res.status == "success"
    emp_class = next(c for c in res.classes if c.name == "Employee")
    assert "Person" in emp_class.base_classes
    assert "Identifiable" in emp_class.base_classes
    assert any(m.name == "Employee" for m in res.methods)
    assert any(m.name == "getId" for m in res.methods)
    assert any(i.module == "java.util.List" for i in res.imports)

def test_c_and_cpp_parsers():
    c_parser = CParser()
    c_code = b"""#include <stdio.h>
int add(int a, int b) {
    printf("%d", a);
    return a + b;
}
"""
    c_res = c_parser.parse_file(c_code, "util.c")
    assert c_res.status == "success"
    assert any(f.name == "add" for f in c_res.functions)
    assert any(i.module == "stdio.h" for i in c_res.imports)

    cpp_parser = CppParser()
    cpp_code = b"""#include <iostream>
class Shape {
public:
    virtual double area() = 0;
};
class Circle : public Shape {
public:
    double area() override {
        return 3.14;
    }
};
"""
    cpp_res = cpp_parser.parse_file(cpp_code, "shape.cpp")
    assert cpp_res.status == "success"
    assert any(c.name == "Shape" for c in cpp_res.classes)
    circle = next(c for c in cpp_res.classes if c.name == "Circle")
    assert "Shape" in circle.base_classes
    assert any(m.name == "area" for m in cpp_res.methods)

# ---------------------------------------------------------------------------
# 5. Error Handling & Guardrails Tests
# ---------------------------------------------------------------------------

def test_syntax_error_handling():
    parser = PythonParser()
    broken_code = b"def broken_function(:\n    pass\n"
    res = parser.parse_file(broken_code, "broken.py")
    assert res.status == "syntax_error"
    assert len(res.warnings) > 0
    assert res.warnings[0].warning_type == "syntax_error"

def test_empty_source_file():
    parser = PythonParser()
    res = parser.parse_file(b"", "empty.py")
    assert res.status == "success"
    assert len(res.functions) == 0
    assert len(res.classes) == 0
    assert res.total_lines == 0

def test_code_parser_service_limits():
    tmp_dir = tempfile.mkdtemp()
    try:
        # Create a tiny source file and an oversized source file
        tiny_path = os.path.join(tmp_dir, "small.py")
        with open(tiny_path, "w") as fh:
            fh.write("def small(): pass\n")

        large_path = os.path.join(tmp_dir, "large.py")
        with open(large_path, "w") as fh:
            fh.write("x = 1\n" * 500)

        service = CodeParserService(
            max_file_size_bytes=200,  # low limit to trigger size skipped
            max_files_to_parse=5,
            max_snippet_lines=10,
        )

        result = service.parse_repository(
            job_id="test-job",
            repo_name="test/repo",
            local_path=tmp_dir,
            analysis=None,
        )

        assert result.total_parsed_files == 2
        statuses = {f.file_path: f.status for f in result.files}
        assert statuses["small.py"] == "success"
        assert statuses["large.py"] == "skipped"

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ---------------------------------------------------------------------------
# 6. Integration and API Tests
# ---------------------------------------------------------------------------

def test_get_code_analysis_job_not_found():
    response = client.get("/api/v1/jobs/nonexistent-id/code-analysis")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_create_job_and_complete_code_analysis_pipeline():
    from unittest.mock import patch
    from app.services.repo.ingest import IngestionResult

    tmp_dir = tempfile.mkdtemp()
    try:
        py_file = os.path.join(tmp_dir, "app.py")
        with open(py_file, "w") as fh:
            fh.write("def calculate(x): return x * 2\n")

        with patch("app.api.routes.jobs.verify_repository_accessible", return_value=True):
            with patch("app.api.routes.jobs.repo_ingestion_service.ingest_repository") as mock_ingest:
                mock_ingest.return_value = IngestionResult(
                    job_id="test-job",
                    local_path=tmp_dir,
                    file_count=1,
                    size_bytes=1024,
                    size_mb=0.01,
                    clone_duration_seconds=0.1,
                )
                payload = {"github_url": "https://github.com/fastapi/fastapi"}
                response = client.post("/api/v1/jobs", json=payload)
                assert response.status_code == 201

                data = response.json()
                job_id = data["job_id"]

                # In TestClient, background tasks run synchronously
                get_res = client.get(f"/api/v1/jobs/{job_id}")
                assert get_res.status_code == 200
                res_data = get_res.json()

                assert res_data["stages"][0]["status"] == "completed"  # Fetching
                assert res_data["stages"][1]["status"] == "completed"  # Analysis
                assert res_data["stages"][2]["status"] == "completed"  # Code Understanding
                assert res_data["progress_percentage"] >= 33
                assert res_data["code_analysis"] is not None

                # Call GET /api/v1/jobs/{job_id}/code-analysis
                res = client.get(f"/api/v1/jobs/{job_id}/code-analysis")
                assert res.status_code == 200
                code_meta = res.json()
                assert code_meta["job_id"] == job_id
                assert code_meta["repository_name"] == "fastapi/fastapi"
                assert code_meta["total_parsed_files"] >= 1
                assert code_meta["total_functions"] >= 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
