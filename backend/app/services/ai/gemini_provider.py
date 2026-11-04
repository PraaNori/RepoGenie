import asyncio
import logging
import time
from typing import List, Optional

from google import genai
from google.genai import errors, types

from ...core.config import settings
from .base_provider import BaseLLMProvider
from .exceptions import (
    AIAuthenticationError,
    AIConfigurationError,
    AIError,
    AIInvalidResponseError,
    AIProviderUnavailableError,
    AIQuotaExhaustedError,
    AIRateLimitError,
    AITimeoutError,
)
from .schemas import (
    ConnectivityCheckResult,
    LLMGenerationOptions,
    LLMMessage,
    LLMResponse,
    TokenUsageRecord,
)

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini provider using official google-genai SDK.
    Supports asynchronous generation, strict timeouts, quota/rate-limit error handling,
    and actual token usage extraction.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[genai.Client] = None,
    ):
        self._api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self._model = model or settings.GEMINI_MODEL
        self._client = client

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client
        if not self.is_configured():
            raise AIConfigurationError(
                "Gemini API key is not configured. Set GEMINI_API_KEY in your environment.",
                provider=self.provider_name,
            )
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_text(
        self,
        prompt: str,
        options: Optional[LLMGenerationOptions] = None,
        messages: Optional[List[LLMMessage]] = None,
        operation: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> LLMResponse:
        opts = options or LLMGenerationOptions()
        client = self._get_client()

        # Build contents from messages or raw prompt
        contents: List[Any] = []
        if messages:
            for msg in messages:
                contents.append(f"{msg.role.capitalize()}: {msg.content}")
            if prompt:
                contents.append(prompt)
        else:
            contents = [prompt]

        # Prepare SDK configuration
        http_opts = types.HttpOptions(timeout=opts.timeout_seconds * 1000)
        config = types.GenerateContentConfig(
            temperature=opts.temperature,
            max_output_tokens=opts.max_output_tokens,
            system_instruction=opts.system_instruction,
            stop_sequences=opts.stop_sequences,
            http_options=http_opts,
        )

        start_time = time.perf_counter()
        try:
            call_coro = client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
            response = await asyncio.wait_for(call_coro, timeout=float(opts.timeout_seconds))
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if not response or not hasattr(response, "text"):
                raise AIInvalidResponseError("Gemini returned an empty or malformed response", provider=self.provider_name)

            text = response.text or ""

            # Extract finish reason
            finish_reason = None
            if hasattr(response, "candidates") and response.candidates:
                cand = response.candidates[0]
                if hasattr(cand, "finish_reason"):
                    finish_reason = str(cand.finish_reason)

            # Extract token usage metadata
            token_usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                prompt_tok = getattr(um, "prompt_token_count", 0) or 0
                comp_tok = getattr(um, "candidates_token_count", 0) or 0
                tot_tok = getattr(um, "total_token_count", 0) or (prompt_tok + comp_tok)
                token_usage = TokenUsageRecord(
                    prompt_tokens=prompt_tok,
                    completion_tokens=comp_tok,
                    total_tokens=tot_tok,
                    is_estimated=False,
                    provider=self.provider_name,
                    model=self._model,
                    operation=operation,
                    job_id=job_id,
                )
            else:
                # Conservative estimation when usage_metadata is missing
                prompt_text = " ".join(str(c) for c in contents)
                prompt_tok = self.estimate_token_count(prompt_text)
                comp_tok = self.estimate_token_count(text)
                token_usage = TokenUsageRecord(
                    prompt_tokens=prompt_tok,
                    completion_tokens=comp_tok,
                    total_tokens=prompt_tok + comp_tok,
                    is_estimated=True,
                    provider=self.provider_name,
                    model=self._model,
                    operation=operation,
                    job_id=job_id,
                )

            return LLMResponse(
                text=text,
                provider=self.provider_name,
                model=self._model,
                finish_reason=finish_reason,
                token_usage=token_usage,
                latency_ms=round(latency_ms, 2),
                raw_response_metadata={},
            )

        except asyncio.TimeoutError as exc:
            raise AITimeoutError(
                f"Gemini generation request timed out after {opts.timeout_seconds}s",
                provider=self.provider_name,
            ) from exc

        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            msg = getattr(exc, "message", str(exc))

            if code in (401, 403) or "API_KEY_INVALID" in msg or "permission" in msg.lower():
                raise AIAuthenticationError(
                    f"Gemini authentication failed: {msg}",
                    provider=self.provider_name,
                    status_code=code or 401,
                ) from exc

            if code == 404 or "model" in msg.lower() and "not found" in msg.lower():
                raise AIConfigurationError(
                    f"Gemini model '{self._model}' not found or unsupported: {msg}",
                    provider=self.provider_name,
                ) from exc

            if code == 429 or "RESOURCE_EXHAUSTED" in msg:
                msg_lower = msg.lower()
                if any(w in msg_lower for w in ("quota", "billing", "credit", "balance", "daily")) and "rate limit" not in msg_lower:
                    raise AIQuotaExhaustedError(
                        f"Gemini quota exhausted: {msg}",
                        provider=self.provider_name,
                        status_code=429,
                    ) from exc
                raise AIRateLimitError(
                    f"Gemini rate limit exceeded: {msg}",
                    provider=self.provider_name,
                    status_code=429,
                ) from exc

            if code and code >= 500:
                raise AIProviderUnavailableError(
                    f"Gemini service unavailable: {msg}",
                    provider=self.provider_name,
                    status_code=code,
                ) from exc

            raise AIError(f"Gemini API error: {msg}", provider=self.provider_name, status_code=code) from exc

        except Exception as exc:
            if isinstance(exc, AIError):
                raise
            raise AIError(f"Unexpected error communicating with Gemini: {exc}", provider=self.provider_name) from exc

    async def check_connectivity(self) -> ConnectivityCheckResult:
        if not self.is_configured():
            return ConnectivityCheckResult(
                provider=self.provider_name,
                model=self._model,
                is_reachable=False,
                message="Gemini API key is not configured.",
            )

        start = time.perf_counter()
        try:
            resp = await self.generate_text(
                prompt="Respond with the single word: OK",
                options=LLMGenerationOptions(max_output_tokens=5, temperature=0.0, timeout_seconds=15),
                operation="connectivity_probe",
            )
            lat = (time.perf_counter() - start) * 1000.0
            if resp.token_usage:
                from .token_tracker import token_tracker
                token_tracker.record_usage(resp.token_usage)
            return ConnectivityCheckResult(
                provider=self.provider_name,
                model=self._model,
                is_reachable=True,
                message="Successfully reached Gemini API.",
                latency_ms=round(lat, 2),
            )
        except AIError as exc:
            lat = (time.perf_counter() - start) * 1000.0
            return ConnectivityCheckResult(
                provider=self.provider_name,
                model=self._model,
                is_reachable=False,
                message=f"Connectivity check failed: {exc.message}",
                latency_ms=round(lat, 2),
                error_details=str(exc),
            )
        except Exception as exc:
            lat = (time.perf_counter() - start) * 1000.0
            return ConnectivityCheckResult(
                provider=self.provider_name,
                model=self._model,
                is_reachable=False,
                message=f"Unexpected connectivity check failure: {exc}",
                latency_ms=round(lat, 2),
                error_details=str(exc),
            )
