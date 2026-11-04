"""
Regression tests for:
1. Python technology evidence references actual .py files.
2. JavaScript technology evidence references actual .js/.jsx files.
3. CSS evidence references actual stylesheet files (.css/.scss).
4. No synthetic *.python, *.javascript, or *.css paths are generated.
5. Missing source files do not produce fabricated evidence.
6. Existing valid manifest and import evidence still works.
7. EvidenceValidator accepts genuine paths and rejects nonexistent paths.
8. EvidenceValidator rejects extension mismatches and wildcard paths.
"""

import json
from datetime import datetime, timezone
import pytest

from app.models.schemas import (
    ArchitecturalComponent,
    ArchitectureSummary,
    CallGraph,
    CodeStructureSummary,
    DependencyGraph,
    DirectoryTreeNode,
    ImportantFileInfo,
    KnowledgeAnalysisMetadata,
    ParsedFile,
    ProjectOverviewInfo,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    RepositoryStructureOverview,
    SourceEvidenceRecord,
    StatusEnum,
    TechnologyItem,
    TechnologyStack,
    UnifiedStatistics,
)
from app.services.ai.project_understanding.analyzer import (
    ProjectUnderstandingAnalyzer,
)
from app.services.ai.project_understanding.evidence_builder import (
    evidence_builder_service,
)
from app.services.ai.project_understanding.evidence_resolver import (
    find_actual_files_for_language,
    find_actual_manifests_for_language,
    find_actual_evidence_for_framework,
    get_language_extensions,
    resolve_technology_evidence,
)
from app.services.ai.project_understanding.schemas import (
    EvidenceReference,
    ProjectIdentity,
    ProjectUnderstanding,
    ProblemStatement,
    TargetAudience,
    TechnologyExplanationItem,
    UseCaseItem,
    ApplicationExplanation,
)
from app.services.ai.project_understanding.validator import evidence_validator


@pytest.fixture
def multi_lang_knowledge() -> RepositoryKnowledge:
    """Fixture with Python, JavaScript, CSS, and manifest files in inventory."""
    return RepositoryKnowledge(
        schema_version="1.0",
        repository=RepositoryMetadataInfo(
            name="test/fullstack-app",
            owner="test",
            repository_url="https://github.com/test/fullstack-app",
            file_count=20,
            size_mb=2.5,
            description="Full-stack Python and React application with custom CSS.",
        ),
        project_overview=ProjectOverviewInfo(
            readme_available=True,
            readme_path="README.md",
            description="Full-stack web application.",
            features=["REST API backend", "Interactive React frontend", "Custom stylesheet themes"],
            limitations=[],
        ),
        technology_stack=TechnologyStack(
            languages=[
                TechnologyItem(name="Python", category="language", detection_source="language_detection"),
                TechnologyItem(name="JavaScript", category="language", detection_source="language_detection"),
                TechnologyItem(name="CSS", category="language", detection_source="language_detection"),
            ],
            frameworks=[
                TechnologyItem(name="FastAPI", category="framework", detection_source="manifest", is_confirmed=True),
                TechnologyItem(name="React", category="framework", detection_source="code_import", is_confirmed=True),
            ],
            libraries=[],
            databases=[],
            tools=[],
            deployment_technologies=[],
        ),
        repository_structure=RepositoryStructureOverview(
            total_directories=4,
            total_files=8,
            important_directories=["backend", "frontend/src", "frontend/styles"],
            directory_tree=DirectoryTreeNode(
                name="fullstack-app",
                path="",
                type="directory",
                children=[
                    DirectoryTreeNode(
                        name="backend",
                        path="backend",
                        type="directory",
                        children=[
                            DirectoryTreeNode(name="main.py", path="backend/main.py", type="file"),
                            DirectoryTreeNode(name="api.py", path="backend/api.py", type="file"),
                            DirectoryTreeNode(name="requirements.txt", path="backend/requirements.txt", type="file"),
                        ],
                    ),
                    DirectoryTreeNode(
                        name="frontend",
                        path="frontend",
                        type="directory",
                        children=[
                            DirectoryTreeNode(
                                name="src",
                                path="frontend/src",
                                type="directory",
                                children=[
                                    DirectoryTreeNode(name="index.jsx", path="frontend/src/index.jsx", type="file"),
                                    DirectoryTreeNode(name="App.js", path="frontend/src/App.js", type="file"),
                                ],
                            ),
                            DirectoryTreeNode(
                                name="styles",
                                path="frontend/styles",
                                type="directory",
                                children=[
                                    DirectoryTreeNode(name="theme.css", path="frontend/styles/theme.css", type="file"),
                                ],
                            ),
                            DirectoryTreeNode(name="package.json", path="frontend/package.json", type="file"),
                        ],
                    ),
                    DirectoryTreeNode(name="README.md", path="README.md", type="file"),
                ],
            ),
        ),
        statistics=UnifiedStatistics(
            total_files=8,
            source_files=6,
            filtered_files=2,
            total_lines_of_code=800,
            total_functions=10,
            total_classes=2,
            total_methods=4,
            total_imports=8,
            total_function_calls=25,
            total_internal_dependencies=2,
            total_external_dependencies=5,
        ),
        dependency_information=DependencyGraph(),
        code_structure=CodeStructureSummary(
            parsed_files_count=4,
            supported_languages=["python", "javascript"],
            files=[
                ParsedFile(file_path="backend/main.py", language="python", status="success", total_lines=120),
                ParsedFile(file_path="backend/api.py", language="python", status="success", total_lines=80),
                ParsedFile(file_path="frontend/src/index.jsx", language="javascript", status="success", total_lines=50),
                ParsedFile(file_path="frontend/src/App.js", language="javascript", status="success", total_lines=90),
            ],
        ),
        architecture=ArchitectureSummary(
            dependency_graph=DependencyGraph(),
            call_graph=CallGraph(),
            components=[
                ArchitecturalComponent(file_path="backend/main.py", category="entry_point", confidence="high"),
                ArchitecturalComponent(file_path="frontend/src/index.jsx", category="entry_point", confidence="high"),
            ],
        ),
        entry_points=[],
        important_files=[
            ImportantFileInfo(
                relative_path="backend/main.py",
                category="entry_point",
                score=9.0,
                reason="Backend FastAPI entry point",
                evidence="FastAPI app instance",
                confidence="high",
            ),
            ImportantFileInfo(
                relative_path="frontend/src/index.jsx",
                category="entry_point",
                score=8.5,
                reason="Frontend React root",
                evidence="ReactDOM.render root",
                confidence="high",
            ),
        ],
        source_evidence=[
            SourceEvidenceRecord(
                file_path="backend/main.py",
                start_line=1,
                evidence_type="manifest_dependency",
                symbol_or_statement="Framework: FastAPI",
                confidence="high",
                analysis_stage="code_understanding",
                status="observed",
            ),
            SourceEvidenceRecord(
                file_path="frontend/src/App.js",
                start_line=1,
                evidence_type="code_import",
                symbol_or_statement="Framework: React",
                confidence="high",
                analysis_stage="code_understanding",
                status="observed",
            ),
        ],
        warnings=[],
        analysis_metadata=KnowledgeAnalysisMetadata(
            analysis_status=StatusEnum.COMPLETED,
            created_at=datetime.now(timezone.utc),
        ),
    )


def test_python_technology_evidence_references_actual_py_files(multi_lang_knowledge):
    """1. Python technology evidence must reference actual .py files in repository."""
    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(multi_lang_knowledge)

    py_tech = next(t for t in fallback.technology_stack if t.technology_name == "Python")
    assert len(py_tech.supporting_evidence) >= 1
    assert py_tech.status == "confirmed"

    # Must be a real .py file from the repo, NOT a wildcard
    for ev in py_tech.supporting_evidence:
        assert ev.file_path.endswith((".py", ".pyw"))
        assert "*" not in ev.file_path
        assert ev.file_path in ("backend/main.py", "backend/api.py")

    # Validator must verify without warnings
    validated = evidence_validator.validate_understanding(fallback, multi_lang_knowledge)
    py_warnings = [w for w in validated.validation_warnings if "Python" in w]
    assert len(py_warnings) == 0


def test_javascript_technology_evidence_references_actual_js_files(multi_lang_knowledge):
    """2. JavaScript technology evidence must reference actual .js/.jsx files."""
    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(multi_lang_knowledge)

    js_tech = next(t for t in fallback.technology_stack if t.technology_name == "JavaScript")
    assert len(js_tech.supporting_evidence) >= 1
    assert js_tech.status == "confirmed"

    for ev in js_tech.supporting_evidence:
        assert ev.file_path.endswith((".js", ".jsx", ".mjs", ".cjs", ".gs"))
        assert "*" not in ev.file_path
        assert ev.file_path in ("frontend/src/index.jsx", "frontend/src/App.js")

    validated = evidence_validator.validate_understanding(fallback, multi_lang_knowledge)
    js_warnings = [w for w in validated.validation_warnings if "JavaScript" in w]
    assert len(js_warnings) == 0


def test_css_technology_evidence_references_actual_stylesheet_files(multi_lang_knowledge):
    """3. CSS evidence must reference actual stylesheet files (.css/.scss)."""
    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(multi_lang_knowledge)

    css_tech = next(t for t in fallback.technology_stack if t.technology_name == "CSS")
    assert len(css_tech.supporting_evidence) >= 1
    assert css_tech.status == "confirmed"

    for ev in css_tech.supporting_evidence:
        assert ev.file_path.endswith((".css", ".scss", ".sass", ".less"))
        assert "*" not in ev.file_path
        assert ev.file_path == "frontend/styles/theme.css"

    validated = evidence_validator.validate_understanding(fallback, multi_lang_knowledge)
    css_warnings = [w for w in validated.validation_warnings if "CSS" in w]
    assert len(css_warnings) == 0


def test_no_synthetic_wildcard_paths_generated(multi_lang_knowledge):
    """4. No synthetic *.python, *.javascript, *.css paths are generated anywhere in tech stack."""
    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(multi_lang_knowledge)

    for tech in fallback.technology_stack:
        for ev in tech.supporting_evidence:
            assert "*" not in ev.file_path, f"Wildcard path '{ev.file_path}' generated for {tech.technology_name}"
            assert "?" not in ev.file_path
            assert ev.file_path not in ("*.python", "*.javascript", "*.css", "*.cpp", "source_code", "manifest")


def test_missing_source_files_do_not_produce_fabricated_evidence(multi_lang_knowledge):
    """5. Missing source files do not produce fabricated evidence (returns empty list, sets status=inferred)."""
    # Add a language that does NOT exist anywhere in repository
    multi_lang_knowledge.technology_stack.languages.append(
        TechnologyItem(name="Ruby", category="language", detection_source="language_detection")
    )

    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(multi_lang_knowledge)

    ruby_tech = next(t for t in fallback.technology_stack if t.technology_name == "Ruby")
    assert ruby_tech.supporting_evidence == []
    assert ruby_tech.status == "inferred"

    # Validator must NOT warn about nonexistent files because no fake file was cited
    validated = evidence_validator.validate_understanding(fallback, multi_lang_knowledge)
    ruby_warnings = [w for w in validated.validation_warnings if "Ruby" in w]
    assert len(ruby_warnings) == 0


def test_manifest_evidence_preserved_when_no_source_files(multi_lang_knowledge):
    """6. Existing valid manifest evidence is used when source files are absent."""
    # Remove all python source files from directory tree and parsed files, but keep requirements.txt
    multi_lang_knowledge.code_structure.files = [
        f for f in multi_lang_knowledge.code_structure.files if not f.file_path.endswith(".py")
    ]
    multi_lang_knowledge.important_files = [
        f for f in multi_lang_knowledge.important_files if not f.relative_path.endswith(".py")
    ]
    multi_lang_knowledge.source_evidence = [
        e for e in multi_lang_knowledge.source_evidence if not e.file_path.endswith(".py")
    ]

    # Leave requirements.txt in the tree, but remove .py files from directory_tree
    def filter_tree(node):
        if not node or not node.children:
            return
        node.children = [ch for ch in node.children if not ch.path.endswith(".py")]
        for ch in node.children:
            filter_tree(ch)
    filter_tree(multi_lang_knowledge.repository_structure.directory_tree)

    manifests = find_actual_manifests_for_language(multi_lang_knowledge, "Python")
    assert "backend/requirements.txt" in manifests or "requirements.txt" in manifests

    refs = resolve_technology_evidence("Python", "Language", multi_lang_knowledge)
    assert len(refs) == 1
    assert refs[0].evidence_type == "manifest"
    assert "requirements.txt" in refs[0].file_path


def test_framework_evidence_uses_real_files(multi_lang_knowledge):
    """Frameworks cite actual code or manifest files, never fake strings."""
    analyzer = ProjectUnderstandingAnalyzer()
    fallback = analyzer.create_rule_based_fallback(multi_lang_knowledge)

    for fw in fallback.technology_stack:
        if fw.category == "Framework":
            assert len(fw.supporting_evidence) >= 1
            for ev in fw.supporting_evidence:
                assert ev.file_path not in ("source_code", "manifest", "repository_analysis")
                assert ev.file_path in ("backend/main.py", "frontend/src/App.js", "frontend/package.json")


def test_evidence_validator_rejects_wildcard_paths(multi_lang_knowledge):
    """7. EvidenceValidator rejects synthetic wildcard paths like *.python and *.javascript."""
    understanding = ProjectUnderstanding(
        schema_version="1.0",
        identity=ProjectIdentity(
            name="test",
            short_description="test",
            category="test",
            project_type="test",
            primary_purpose="test",
        ),
        problem_statement=ProblemStatement(
            problem_addressed="test",
            why_it_matters="test",
            how_project_solves_it="test",
        ),
        core_features=[],
        target_audience=TargetAudience(intended_users=["devs"], likely_needs=["tools"]),
        use_cases=[],
        technology_stack=[
            TechnologyExplanationItem(
                technology_name="Python",
                category="Language",
                role_in_project="Core",
                why_used="Standard",
                supporting_evidence=[
                    EvidenceReference(file_path="*.python", evidence_type="code")
                ],
                status="confirmed",
            ),
            TechnologyExplanationItem(
                technology_name="JavaScript",
                category="Language",
                role_in_project="Core",
                why_used="Standard",
                supporting_evidence=[
                    EvidenceReference(file_path="*.javascript", evidence_type="code")
                ],
                status="confirmed",
            ),
        ],
        overall_explanation=ApplicationExplanation(
            concise_overview="test",
            detailed_explanation="test",
            beginner_friendly="test",
            interesting_aspects="test",
        ),
    )

    validated = evidence_validator.validate_understanding(understanding, multi_lang_knowledge)
    assert len(validated.validation_warnings) == 2
    assert "unverified evidence '*.python'" in validated.validation_warnings[0]
    assert "unverified evidence '*.javascript'" in validated.validation_warnings[1]
    assert validated.technology_stack[0].status == "inferred"
    assert validated.technology_stack[1].status == "inferred"


def test_evidence_validator_rejects_extension_mismatch(multi_lang_knowledge):
    """8. EvidenceValidator rejects code evidence where extension does not match the language."""
    understanding = ProjectUnderstanding(
        schema_version="1.0",
        identity=ProjectIdentity(
            name="test",
            short_description="test",
            category="test",
            project_type="test",
            primary_purpose="test",
        ),
        problem_statement=ProblemStatement(
            problem_addressed="test",
            why_it_matters="test",
            how_project_solves_it="test",
        ),
        core_features=[],
        target_audience=TargetAudience(intended_users=["devs"], likely_needs=["tools"]),
        use_cases=[],
        technology_stack=[
            TechnologyExplanationItem(
                technology_name="Python",
                category="Language",
                role_in_project="Core",
                why_used="Standard",
                supporting_evidence=[
                    # theme.css exists in the repo, but its extension does not match Python!
                    EvidenceReference(file_path="frontend/styles/theme.css", evidence_type="code")
                ],
                status="confirmed",
            )
        ],
        overall_explanation=ApplicationExplanation(
            concise_overview="test",
            detailed_explanation="test",
            beginner_friendly="test",
            interesting_aspects="test",
        ),
    )

    validated = evidence_validator.validate_understanding(understanding, multi_lang_knowledge)
    assert len(validated.validation_warnings) == 1
    assert "does not match expected extensions" in validated.validation_warnings[0]
    assert validated.technology_stack[0].status == "inferred"


def test_normalization_sanitizes_synthetic_llm_wildcards(multi_lang_knowledge):
    """Normalization cleanses any LLM output containing synthetic wildcards and resolves real files."""
    analyzer = ProjectUnderstandingAnalyzer()
    malformed_parsed_dict = {
        "identity": {"name": "test"},
        "problem_statement": {"problem_addressed": "test"},
        "core_features": [],
        "target_audience": {"intended_users": ["devs"]},
        "use_cases": [],
        "technology_stack": [
            {
                "technology_name": "Python",
                "category": "Language",
                "role_in_project": "Core",
                "why_used": "Backend",
                "supporting_evidence": [
                    {"file_path": "*.python", "evidence_type": "code"}
                ],
                "status": "confirmed",
            },
            {
                "technology_name": "CSS",
                "category": "Styling",
                "role_in_project": "UI",
                "why_used": "Styles",
                "supporting_evidence": [
                    {"file_path": "*.css", "evidence_type": "code"}
                ],
                "status": "confirmed",
            },
        ],
        "overall_explanation": {"concise_overview": "test"},
    }

    normalized = analyzer._normalize_parsed_dict(malformed_parsed_dict, multi_lang_knowledge)
    techs = normalized["technology_stack"]

    py_ev = techs[0]["supporting_evidence"]
    assert len(py_ev) >= 1
    assert py_ev[0]["file_path"] in ("backend/main.py", "backend/api.py")
    assert "*" not in py_ev[0]["file_path"]

    css_ev = techs[1]["supporting_evidence"]
    assert len(css_ev) >= 1
    assert css_ev[0]["file_path"] == "frontend/styles/theme.css"
    assert "*" not in css_ev[0]["file_path"]
