import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai import (
    AIAuthenticationError,
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIProviderUnavailableError,
    AIQuotaExhaustedError,
    AIRateLimitError,
    AIStatusResponse,
    AITimeoutError,
    BaseLLMProvider,
    ConnectivityCheckResult,
    GeminiProvider,
    GroqProvider,
    LLMGenerationOptions,
    LLMManager,
    LLMMessage,
    LLMResponse,
    TokenTracker,
    TokenUsageRecord,
    llm_manager,
    token_tracker,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Base Provider & Token Tracker Unit Tests
# ---------------------------------------------------------------------------


def test_token_tracker_recording_and_summary():
    tracker = TokenTracker(max_history=100)
    tracker.reset()

    # Empty summary
    summary = tracker.get_summary()
    assert summary.total_tokens == 0
    assert summary.total_requests == 0

    # Record provider 1 (actual)
    rec1 = TokenUsageRecord(
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        is_estimated=False,
        provider="gemini",
        model="gemini-2.5-flash",
        operation="summarize",
        job_id="job-123",
    )
    tracker.record_usage(rec1)

    # Record provider 2 (estimated)
    rec2 = TokenUsageRecord(
        prompt_tokens=200,
        completion_tokens=80,
        total_tokens=280,
        is_estimated=True,
        provider="groq",
        model="llama-3.3-70b-versatile",
        operation="extract",
        job_id="job-123",
    )
    tracker.record_usage(rec2)

    # Record provider 1 another job
    rec3 = TokenUsageRecord(
        prompt_tokens=50,
        completion_tokens=25,
        total_tokens=75,
        is_estimated=False,
        provider="gemini",
        model="gemini-2.5-flash",
        operation="qa",
        job_id="job-456",
    )
    tracker.record_usage(rec3)

    summary = tracker.get_summary()
    assert summary.total_requests == 3
    assert summary.total_tokens == 150 + 280 + 75  # 505
    assert summary.total_prompt_tokens == 350
    assert summary.total_completion_tokens == 155
    assert summary.estimated_requests_count == 1
    assert summary.by_provider["gemini"] == 225
    assert summary.by_provider["groq"] == 280
    assert summary.by_model["gemini-2.5-flash"] == 225
    assert summary.by_model["llama-3.3-70b-versatile"] == 280

    # Job-specific queries
    assert tracker.get_job_tokens("job-123") == 430
    assert tracker.get_job_tokens("job-456") == 75
    assert len(tracker.get_job_records("job-123")) == 2

    # Recent records
    recent = tracker.get_recent_records(limit=2)
    assert len(recent) == 2
    assert recent[0].job_id == "job-456"

    tracker.reset()
    assert tracker.get_summary().total_requests == 0


def test_base_provider_estimate_tokens():
    assert BaseLLMProvider.estimate_token_count("") == 0
    assert BaseLLMProvider.estimate_token_count("abcd") == 1
    assert BaseLLMProvider.estimate_token_count("Hello world, this is a test.") == 7


# ---------------------------------------------------------------------------
# 2. Gemini Provider Unit Tests (Mocked SDK)
# ---------------------------------------------------------------------------


def test_gemini_provider_initialization():
    # Unconfigured
    prov_empty = GeminiProvider(api_key="", model="gemini-2.5-flash")
    assert prov_empty.is_configured() is False
    assert prov_empty.provider_name == "gemini"
    assert prov_empty.model_name == "gemini-2.5-flash"

    # Configured
    prov = GeminiProvider(api_key="ai-test-key", model="gemini-custom")
    assert prov.is_configured() is True
    assert prov.model_name == "gemini-custom"


@pytest.mark.anyio
async def test_gemini_provider_missing_key_error():
    prov = GeminiProvider(api_key="")
    with pytest.raises(AIConfigurationError) as exc_info:
        await prov.generate_text("Hello")
    assert "Gemini API key is not configured" in str(exc_info.value)
    assert exc_info.value.retryable is False


@pytest.mark.anyio
async def test_gemini_provider_successful_generation():
    # Mock google-genai Client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "This is a test explanation."

    # Usage metadata
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 12
    mock_usage.candidates_token_count = 18
    mock_usage.total_token_count = 30
    mock_response.usage_metadata = mock_usage

    mock_cand = MagicMock()
    mock_cand.finish_reason = "STOP"
    mock_response.candidates = [mock_cand]

    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    prov = GeminiProvider(api_key="mock-key", model="gemini-2.5-flash", client=mock_client)
    res = await prov.generate_text(
        prompt="Explain repository structure",
        options=LLMGenerationOptions(temperature=0.3, max_output_tokens=1000),
        messages=[LLMMessage(role="user", content="Hi")],
        operation="test_op",
        job_id="job-99",
    )

    assert isinstance(res, LLMResponse)
    assert res.text == "This is a test explanation."
    assert res.provider == "gemini"
    assert res.model == "gemini-2.5-flash"
    assert res.finish_reason == "STOP"
    assert res.token_usage is not None
    assert res.token_usage.prompt_tokens == 12
    assert res.token_usage.completion_tokens == 18
    assert res.token_usage.total_tokens == 30
    assert res.token_usage.is_estimated is False
    assert res.token_usage.operation == "test_op"
    assert res.token_usage.job_id == "job-99"
    assert res.latency_ms >= 0.0

    # Verify SDK options passed to Gemini client
    call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
    assert call_kwargs["config"].max_output_tokens == 1000
    assert call_kwargs["config"].temperature == 0.3


@pytest.mark.anyio
async def test_gemini_provider_error_mapping():
    from google.genai.errors import APIError

    mock_client = MagicMock()

    # 1. Auth error (401 / 403)
    auth_err = APIError(401, {"error": {"message": "API_KEY_INVALID: Key not valid"}})
    mock_client.aio.models.generate_content = AsyncMock(side_effect=auth_err)
    prov = GeminiProvider(api_key="mock-key", client=mock_client)

    with pytest.raises(AIAuthenticationError) as exc_info:
        await prov.generate_text("Ping")
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 401

    # 2. Rate limit error (429 transient)
    rl_err = APIError(429, {"error": {"message": "Resource has been exhausted (e.g. rate limit)."}})
    mock_client.aio.models.generate_content = AsyncMock(side_effect=rl_err)
    with pytest.raises(AIRateLimitError) as exc_info:
        await prov.generate_text("Ping")
    assert exc_info.value.retryable is True

    # 3. Quota exhausted error (429 billing / quota exhausted)
    quota_err = APIError(429, {"error": {"message": "Quota exceeded for metric: Free tier quota exhausted."}})
    mock_client.aio.models.generate_content = AsyncMock(side_effect=quota_err)
    with pytest.raises(AIQuotaExhaustedError) as exc_info:
        await prov.generate_text("Ping")
    assert exc_info.value.retryable is False

    # 4. Service unavailable (503)
    srv_err = APIError(503, {"error": {"message": "Service Unavailable"}})
    mock_client.aio.models.generate_content = AsyncMock(side_effect=srv_err)
    with pytest.raises(AIProviderUnavailableError) as exc_info:
        await prov.generate_text("Ping")
    assert exc_info.value.retryable is True


# ---------------------------------------------------------------------------
# 3. Groq Provider Unit Tests (Mocked SDK)
# ---------------------------------------------------------------------------


def test_groq_provider_initialization():
    prov_empty = GroqProvider(api_key="", model="llama-3.3-70b-versatile")
    assert prov_empty.is_configured() is False
    assert prov_empty.provider_name == "groq"
    assert prov_empty.model_name == "llama-3.3-70b-versatile"

    prov = GroqProvider(api_key="gsk_valid", model="llama-3.1-8b-instant")
    assert prov.is_configured() is True
    assert prov.model_name == "llama-3.1-8b-instant"


@pytest.mark.anyio
async def test_groq_provider_missing_key_error():
    prov = GroqProvider(api_key="")
    with pytest.raises(AIConfigurationError) as exc_info:
        await prov.generate_text("Hello")
    assert "Groq API key is not configured" in str(exc_info.value)
    assert exc_info.value.retryable is False


@pytest.mark.anyio
async def test_groq_provider_successful_generation():
    mock_client = MagicMock()
    mock_response = MagicMock()

    mock_choice = MagicMock()
    mock_choice.message.content = "Groq analysis response."
    mock_choice.finish_reason = "stop"
    mock_response.choices = [mock_choice]

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 25
    mock_usage.completion_tokens = 45
    mock_usage.total_tokens = 70
    mock_response.usage = mock_usage

    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    prov = GroqProvider(api_key="gsk_test", model="llama-3.3-70b-versatile", client=mock_client)
    res = await prov.generate_text(
        prompt="Tell me about this codebase",
        options=LLMGenerationOptions(system_instruction="Be concise", max_output_tokens=500),
        operation="groq_test",
        job_id="job-groq-1",
    )

    assert isinstance(res, LLMResponse)
    assert res.text == "Groq analysis response."
    assert res.provider == "groq"
    assert res.model == "llama-3.3-70b-versatile"
    assert res.token_usage is not None
    assert res.token_usage.prompt_tokens == 25
    assert res.token_usage.completion_tokens == 45
    assert res.token_usage.total_tokens == 70
    assert res.token_usage.is_estimated is False
    assert res.latency_ms >= 0.0

    # Verify SDK options passed to Groq client
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["max_tokens"] == 500


@pytest.mark.anyio
async def test_groq_provider_error_mapping():
    from groq import AuthenticationError, RateLimitError, APIConnectionError, APITimeoutError

    mock_client = MagicMock()

    # 1. Auth error
    mock_client.chat.completions.create = AsyncMock(
        side_effect=AuthenticationError(message="Invalid API Key", response=MagicMock(status_code=401), body={})
    )
    prov = GroqProvider(api_key="gsk_bad", client=mock_client)
    with pytest.raises(AIAuthenticationError) as exc_info:
        await prov.generate_text("Hello")
    assert exc_info.value.retryable is False

    # 2. Rate limit error (retryable)
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RateLimitError(message="Rate limit reached: RPM limit", response=MagicMock(status_code=429), body={})
    )
    with pytest.raises(AIRateLimitError) as exc_info:
        await prov.generate_text("Hello")
    assert exc_info.value.retryable is True

    # 3. Connection error (unavailable / retryable)
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=MagicMock())
    )
    with pytest.raises(AIProviderUnavailableError) as exc_info:
        await prov.generate_text("Hello")
    assert exc_info.value.retryable is True

    # 4. Timeout error (retryable)
    mock_client.chat.completions.create = AsyncMock(
        side_effect=APITimeoutError(request=MagicMock())
    )
    with pytest.raises(AITimeoutError) as exc_info:
        await prov.generate_text("Hello")
    assert exc_info.value.retryable is True


# ---------------------------------------------------------------------------
# 4. LLM Manager Unit Tests (Orchestration, Provider Selection & Retries)
# ---------------------------------------------------------------------------


def test_llm_manager_provider_selection():
    mgr = LLMManager(active_provider="gemini")
    assert mgr.active_provider_name == "gemini"
    assert mgr.get_provider().provider_name == "gemini"

    mgr.set_active_provider("groq")
    assert mgr.active_provider_name == "groq"
    assert mgr.get_provider().provider_name == "groq"

    # Unsupported provider
    with pytest.raises(AIConfigurationError) as exc_info:
        mgr.set_active_provider("unsupported_provider")
    assert "Unsupported AI provider" in str(exc_info.value)


@pytest.mark.anyio
async def test_llm_manager_retry_on_transient_error():
    mgr = LLMManager(active_provider="gemini", max_retries=2)
    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.provider_name = "mock_gemini"
    mock_provider.model_name = "gemini-2.5-flash"
    mock_provider.is_configured.return_value = True

    # Fail on first 2 attempts with retryable AIRateLimitError, succeed on 3rd attempt
    success_response = LLMResponse(
        text="Success after retry",
        provider="mock_gemini",
        model="gemini-2.5-flash",
        token_usage=TokenUsageRecord(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            provider="mock_gemini",
            model="gemini-2.5-flash",
        ),
    )
    mock_provider.generate_text = AsyncMock(
        side_effect=[
            AIRateLimitError("Rate limit transient", provider="mock_gemini"),
            AIProviderUnavailableError("503 temporary", provider="mock_gemini"),
            success_response,
        ]
    )

    mgr.register_provider("mock_gemini", mock_provider)
    mgr.set_active_provider("mock_gemini")

    # Fast retries by mocking sleep
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await mgr.generate("Test prompt")
        assert res.text == "Success after retry"
        assert mock_provider.generate_text.call_count == 3
        assert mock_sleep.call_count == 2


@pytest.mark.anyio
async def test_llm_manager_fails_fast_on_auth_or_quota():
    mgr = LLMManager(active_provider="gemini", max_retries=2)
    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.provider_name = "mock_gemini"
    mock_provider.model_name = "gemini-2.5-flash"
    mock_provider.is_configured.return_value = True

    # Non-retryable authentication failure
    mock_provider.generate_text = AsyncMock(
        side_effect=AIAuthenticationError("Invalid API key", provider="mock_gemini")
    )
    mgr.register_provider("mock_gemini", mock_provider)
    mgr.set_active_provider("mock_gemini")

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(AIAuthenticationError):
            await mgr.generate("Test prompt")
        # Must fail immediately without sleeping/retrying
        assert mock_provider.generate_text.call_count == 1
        assert mock_sleep.call_count == 0


@pytest.mark.anyio
async def test_llm_manager_connectivity_check():
    mgr = LLMManager(active_provider="gemini")
    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.provider_name = "mock_prov"
    mock_provider.model_name = "test-model"
    mock_provider.check_connectivity = AsyncMock(
        return_value=ConnectivityCheckResult(
            provider="mock_prov",
            model="test-model",
            is_reachable=True,
            message="OK",
            latency_ms=45.2,
        )
    )
    mgr.register_provider("mock_prov", mock_provider)

    res = await mgr.check_connectivity("mock_prov")
    assert res.is_reachable is True
    assert res.latency_ms == 45.2


# ---------------------------------------------------------------------------
# 5. API Endpoints Tests
# ---------------------------------------------------------------------------


def test_api_ai_status_endpoint():
    resp = client.get("/api/v1/ai/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "active_provider" in data
    assert "is_active_provider_configured" in data
    assert "available_providers" in data
    assert "token_summary" in data

    # Verify no API keys are exposed
    raw_text = resp.text.lower()
    assert "api_key" not in raw_text or '"api_key"' not in raw_text
    assert "gsk_" not in resp.text
    assert "aiza" not in resp.text


@pytest.mark.anyio
async def test_api_test_connectivity_endpoint_unconfigured():
    # Calling test-connectivity when unconfigured returns valid 200 payload with is_reachable=False
    resp = client.post("/api/v1/ai/test-connectivity?provider=gemini")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "gemini"
    assert "is_reachable" in data
    if not data["is_reachable"]:
        assert "not configured" in data["message"].lower() or "failed" in data["message"].lower()


@pytest.mark.anyio
async def test_providers_respect_configured_ai_max_output_tokens():
    from app.core.config import settings

    # 1. Gemini
    gemini_mock = MagicMock()
    gemini_resp = MagicMock()
    gemini_resp.text = "{}"
    gemini_resp.candidates = [MagicMock(finish_reason="STOP")]
    gemini_mock.aio.models.generate_content = AsyncMock(return_value=gemini_resp)

    gemini_prov = GeminiProvider(api_key="mock", client=gemini_mock)
    await gemini_prov.generate_text(
        prompt="Test tokens",
        options=LLMGenerationOptions(max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS),
    )
    gemini_kwargs = gemini_mock.aio.models.generate_content.call_args.kwargs
    assert gemini_kwargs["config"].max_output_tokens == settings.AI_MAX_OUTPUT_TOKENS

    # 2. Groq
    groq_mock = MagicMock()
    groq_resp = MagicMock()
    groq_choice = MagicMock()
    groq_choice.message.content = "{}"
    groq_choice.finish_reason = "stop"
    groq_resp.choices = [groq_choice]
    groq_mock.chat.completions.create = AsyncMock(return_value=groq_resp)

    groq_prov = GroqProvider(api_key="mock", client=groq_mock)
    await groq_prov.generate_text(
        prompt="Test tokens",
        options=LLMGenerationOptions(max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS),
    )
    groq_kwargs = groq_mock.chat.completions.create.call_args.kwargs
    assert groq_kwargs["max_tokens"] == settings.AI_MAX_OUTPUT_TOKENS
