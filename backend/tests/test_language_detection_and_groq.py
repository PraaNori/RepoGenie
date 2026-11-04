"""
Regression tests for:
1. Language detection, generic extension mapping (.gs, .ino, .sql, .cpp, .js), and zero-stats handling.
2. Groq as the default and primary AI provider, explicit Gemini availability, and fallback isolation.
3. Verification on sachinsingh2156/Anomaly-Detection-using-GCP fixture.
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.schemas import (
    LanguageStat,
    RepoAnalysisResult,
    RepoStatistics,
    StatusEnum,
)
from app.services.ai import (
    BaseLLMProvider,
    GroqProvider,
    GeminiProvider,
    LLMManager,
    LLMResponse,
)
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIConfigurationError,
    AIError,
    AIProviderUnavailableError,
)
from app.services.ai.project_understanding import project_understanding_analyzer
from app.services.ai.code_understanding import code_understanding_analyzer
from app.services.ai.workflow_understanding import workflow_understanding_analyzer
from app.services.repo.analyzer import (
    LANGUAGE_EXTENSION_MAP,
    PARSER_SUPPORTED_LANGUAGES,
    repo_analyzer_service,
)
from app.services.repo.architecture_analyzer import architecture_analyzer_service
from app.services.repo.code_parser import code_parser_service
from app.services.repo.ingest import IngestionResult, repo_ingestion_service
from app.services.repo.knowledge_builder import knowledge_builder_service
from app.services.repo.parsers.cpp_parser import CppParser
from app.services.repo.parsers.javascript_parser import JavaScriptParser
from app.services.storage.job_store import job_store

client = TestClient(app)

ANOMALY_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "repos" / "anomaly_gcp"


# =============================================================================
# PART A: Language Detection & Parsing Separation Tests
# =============================================================================

def test_language_extension_mappings_include_gs_and_ino():
    """Verify that .gs maps to JavaScript and .ino maps to C++ in LANGUAGE_EXTENSION_MAP."""
    assert ".gs" in LANGUAGE_EXTENSION_MAP
    assert LANGUAGE_EXTENSION_MAP[".gs"] == "JavaScript"
    assert ".ino" in LANGUAGE_EXTENSION_MAP
    assert LANGUAGE_EXTENSION_MAP[".ino"] == "C++"


def test_parser_support_distinction():
    """Verify that detected languages correctly distinguish parser-supported vs unsupported."""
    assert "JavaScript" in PARSER_SUPPORTED_LANGUAGES
    assert "C++" in PARSER_SUPPORTED_LANGUAGES
    assert "Python" in PARSER_SUPPORTED_LANGUAGES
    assert "SQL" not in PARSER_SUPPORTED_LANGUAGES


def test_javascript_parser_handles_google_apps_script():
    """JavaScript parser successfully parses Google Apps Script (.gs) files."""
    parser = JavaScriptParser()
    gs_code = b"""
    function onEdit(e) {
        const sheet = SpreadsheetApp.getActiveSheet();
        sheet.appendRow(["Edited", new Date()]);
        return true;
    }
    """
    res = parser.parse_file(gs_code, "script.gs")
    assert res.status == "success"
    assert len(res.functions) == 1
    assert res.functions[0].name == "onEdit"
    assert len(res.function_calls) >= 2


def test_cpp_parser_handles_arduino_ino():
    """C++ parser successfully parses Arduino (.ino) files."""
    parser = CppParser()
    ino_code = b"""
    #include <Arduino.h>
    void setup() {
        Serial.begin(9600);
    }
    void loop() {
        int val = analogRead(A0);
        delay(100);
    }
    """
    res = parser.parse_file(ino_code, "sensor.ino")
    assert res.status == "success"
    fn_names = [f.name for f in res.functions]
    assert "setup" in fn_names
    assert "loop" in fn_names
    assert len(res.function_calls) >= 2


def test_mixed_language_repository_percentages_and_denominators():
    """
    Test language detection with a synthetic repository containing:
    - 5 SQL files (.sql)
    - 1 Google Apps Script file (.gs)
    - 1 Arduino C++ file (.ino)
    - 1 C++ file (.cpp)
    - 2 PNG images (.png - must be excluded)
    - 1 Excel file (.xlsx - must be excluded)
    - 1 Readme.md (non-language documentation)
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir)
        (repo_dir / "bigquery").mkdir()
        (repo_dir / "scripts").mkdir()
        (repo_dir / "src").mkdir()
        (repo_dir / "media").mkdir()

        # Create files
        for i in range(5):
            (repo_dir / "bigquery" / f"query_{i}.sql").write_text("SELECT 1;")
        (repo_dir / "scripts" / "app.gs").write_text("function run() {}")
        (repo_dir / "src" / "sensor.ino").write_text("void setup() {} void loop() {}")
        (repo_dir / "src" / "main.cpp").write_text("int main() { return 0; }")
        (repo_dir / "media" / "chart1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (repo_dir / "media" / "chart2.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (repo_dir / "data.xlsx").write_bytes(b"PK\x03\x04")
        (repo_dir / "README.md").write_text("# Test Repo")

        analysis = repo_analyzer_service.analyze_repository(
            job_id="test-mixed-lang",
            repo_name="test/mixed-lang",
            local_path=str(repo_dir),
        )

        # 5 SQL + 1 JS (.gs) + 2 C++ (.ino, .cpp) = 8 recognized code files
        lang_map = {l.name: l for l in analysis.languages}
        assert "SQL" in lang_map
        assert "JavaScript" in lang_map
        assert "C++" in lang_map

        assert lang_map["SQL"].file_count == 5
        assert lang_map["JavaScript"].file_count == 1
        assert lang_map["C++"].file_count == 2

        # Verify percentages: 5/8 = 62.5%, 1/8 = 12.5%, 2/8 = 25.0%
        assert lang_map["SQL"].percentage == 62.5
        assert lang_map["JavaScript"].percentage == 12.5
        assert lang_map["C++"].percentage == 25.0

        # Verify parser support flags
        assert lang_map["SQL"].is_parser_supported is False
        assert lang_map["JavaScript"].is_parser_supported is True
        assert lang_map["C++"].is_parser_supported is True

        # Total recognized languages count
        assert analysis.statistics.recognized_languages_count == 3
        assert analysis.statistics.parsed_languages_count == 2
        assert analysis.statistics.unsupported_languages_count == 1

        # Check total vs filtered: 2 PNG + 1 XLSX = 3 filtered files
        assert analysis.statistics.filtered_files == 3


def test_case_insensitive_extensions():
    """Verify that uppercase extensions (.SQL, .GS, .INO, .CPP) are correctly normalized and classified."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir)
        (repo_dir / "UPPER.SQL").write_text("SELECT 1;")
        (repo_dir / "SCRIPT.GS").write_text("function test() {}")
        (repo_dir / "DEVICE.INO").write_text("void setup() {}")
        (repo_dir / "SOURCE.CPP").write_text("int main() {}")

        analysis = repo_analyzer_service.analyze_repository(
            job_id="test-upper-ext",
            repo_name="test/upper-ext",
            local_path=str(repo_dir),
        )

        lang_names = {l.name for l in analysis.languages}
        assert "SQL" in lang_names
        assert "JavaScript" in lang_names
        assert "C++" in lang_names


def test_end_to_end_anomaly_gcp_repository_analysis():
    """
    Scenario: Verify analysis on real fixture sachinsingh2156/Anomaly-Detection-using-GCP:
    - 21 total files (12 PNG + 1 XLSX filtered = 13 filtered files)
    - 8 source files (5 SQL + 1 .gs + 1 .ino + 1 Readme.md)
    - 7 recognized source files: SQL (5, 71.4%), JavaScript (1, 14.3%), C++ (1, 14.3%)
    - Tree-sitter parses 2 files, extracting functions and calls (not 0!)
    - Components and knowledge built successfully.
    """
    assert ANOMALY_FIXTURE_PATH.exists(), f"Anomaly GCP fixture not found at {ANOMALY_FIXTURE_PATH}"

    # 1. Structure Analysis
    analysis = repo_analyzer_service.analyze_repository(
        job_id="test-anomaly",
        repo_name="sachinsingh2156/Anomaly-Detection-using-GCP",
        local_path=str(ANOMALY_FIXTURE_PATH),
    )
    assert analysis.statistics.total_files == 21
    assert analysis.statistics.filtered_files == 13
    assert analysis.statistics.source_files == 8

    lang_map = {l.name: l for l in analysis.languages}
    assert set(lang_map.keys()) == {"SQL", "JavaScript", "C++"}
    assert lang_map["SQL"].file_count == 5
    assert lang_map["SQL"].percentage == 71.4
    assert lang_map["SQL"].is_parser_supported is False

    assert lang_map["JavaScript"].file_count == 1
    assert lang_map["JavaScript"].percentage == 14.3
    assert lang_map["JavaScript"].is_parser_supported is True

    assert lang_map["C++"].file_count == 1
    assert lang_map["C++"].percentage == 14.3
    assert lang_map["C++"].is_parser_supported is True

    # 2. Code Parsing
    code_res = code_parser_service.parse_repository(
        job_id="test-anomaly",
        repo_name="sachinsingh2156/Anomaly-Detection-using-GCP",
        local_path=str(ANOMALY_FIXTURE_PATH),
        analysis=analysis,
    )
    # Both .gs and .ino are parsed!
    assert code_res.total_parsed_files == 2
    assert code_res.total_functions == 4  # doPost, exportRealTimeData, setup, loop
    assert code_res.total_function_calls >= 30
    assert set(code_res.supported_languages) == {"C++", "JavaScript"}

    # 3. Architecture Analysis
    arch = architecture_analyzer_service.analyze_architecture(
        job_id="test-anomaly",
        repo_name="sachinsingh2156/Anomaly-Detection-using-GCP",
        parsed_repo=code_res,
        analysis=analysis,
        local_path=str(ANOMALY_FIXTURE_PATH),
    )
    assert len(arch.components) == 2
    comp_files = {c.file_path for c in arch.components}
    assert "apps_script/code.gs" in comp_files
    assert "esp32/esp32_mq135_sensor.ino" in comp_files

    # 4. Knowledge Consolidation
    knowledge = knowledge_builder_service.build_knowledge(
        job_id="test-anomaly",
        repo_name="sachinsingh2156/Anomaly-Detection-using-GCP",
        repo_owner="sachinsingh2156",
        repo_url="https://github.com/sachinsingh2156/Anomaly-Detection-using-GCP",
        local_path=str(ANOMALY_FIXTURE_PATH),
        size_mb=0.5,
        file_count=analysis.statistics.total_files,
        analysis=analysis,
        parsed_repo=code_res,
        architecture=arch,
    )
    assert knowledge.repository.name == "sachinsingh2156/Anomaly-Detection-using-GCP"
    assert len(knowledge.technology_stack.languages) == 3


# =============================================================================
# PART B: Groq as Primary AI Provider & Gemini Optionality Tests
# =============================================================================

def test_groq_is_default_provider_in_settings():
    """Verify that settings.AI_PROVIDER defaults to 'groq'."""
    assert settings.AI_PROVIDER.lower() == "groq"
    assert settings.GROQ_MODEL == "openai/gpt-oss-120b"


def test_llm_manager_initializes_with_groq_default():
    """LLMManager selects Groq as default active provider when unconfigured."""
    manager = LLMManager()
    assert manager.active_provider_name == "groq"
    assert isinstance(manager.get_provider(), GroqProvider)
    assert manager.get_provider().model_name == "openai/gpt-oss-120b"


def test_explicit_gemini_provider_selection():
    """Gemini remains selectable explicitly via set_active_provider or get_provider('gemini')."""
    manager = LLMManager()
    gemini_prov = manager.get_provider("gemini")
    assert isinstance(gemini_prov, GeminiProvider)
    assert gemini_prov.provider_name == "gemini"

    manager.set_active_provider("gemini")
    assert manager.active_provider_name == "gemini"
    assert isinstance(manager.get_provider(), GeminiProvider)


@pytest.mark.anyio
async def test_groq_failure_does_not_silently_fallback_to_gemini():
    """When Groq fails with an error, it raises AIError and does NOT silently route to Gemini."""
    manager = LLMManager(active_provider="groq", max_retries=1)

    mock_groq = MagicMock(spec=BaseLLMProvider)
    mock_groq.provider_name = "groq"
    mock_groq.model_name = "openai/gpt-oss-120b"
    mock_groq.is_configured.return_value = True
    mock_groq.generate_text = AsyncMock(
        side_effect=AIProviderUnavailableError("Groq service unavailable", provider="groq")
    )
    manager.register_provider("groq", mock_groq)

    mock_gemini = MagicMock(spec=BaseLLMProvider)
    mock_gemini.provider_name = "gemini"
    mock_gemini.generate_text = AsyncMock()
    manager.register_provider("gemini", mock_gemini)

    with pytest.raises(AIProviderUnavailableError) as exc_info:
        await manager.generate("Prompt", job_id="test-no-silent-switch")

    assert exc_info.value.provider == "groq"
    mock_gemini.generate_text.assert_not_called()


@pytest.mark.anyio
async def test_groq_missing_key_fails_fast_without_retries():
    """GroqProvider fails fast with AIConfigurationError if GROQ_API_KEY is empty."""
    provider = GroqProvider(api_key="")
    with pytest.raises(AIConfigurationError) as exc:
        await provider.generate_text("Prompt")
    assert "Groq API key is not configured" in str(exc.value)
    assert exc.value.retryable is False


def test_all_analyzers_respect_configured_groq_provider():
    """Project, Code, and Workflow analyzers use LLMManager with active provider Groq."""
    assert project_understanding_analyzer.llm_manager.active_provider_name == "groq"
    assert code_understanding_analyzer.llm_manager.active_provider_name == "groq"
    assert workflow_understanding_analyzer.llm_manager.active_provider_name == "groq"


def test_deterministic_fallback_provenance_and_zero_fabricated_tokens():
    """Verify that deterministic fallback strictly identifies rule-based status without fabricated tokens."""
    from tests.test_workflow_understanding import _create_mock_knowledge_for_phase3
    knowledge = _create_mock_knowledge_for_phase3()

    pu_fallback = project_understanding_analyzer.create_rule_based_fallback(knowledge)
    assert pu_fallback.is_fallback is True
    assert pu_fallback.provider == "rule_based_fallback"
    assert pu_fallback.model == "deterministic-rule-based"
    assert pu_fallback.token_usage is None

    cu_fallback = code_understanding_analyzer.create_rule_based_fallback(knowledge)
    assert cu_fallback.is_fallback is True
    assert cu_fallback.provider == "rule_based_fallback"
    assert cu_fallback.model == "deterministic-rule-based"
    assert cu_fallback.token_usage is None

    wu_fallback = workflow_understanding_analyzer.create_deterministic_fallback(knowledge)
    assert wu_fallback.is_fallback is True
    assert wu_fallback.token_usage is None
