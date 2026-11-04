import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    RateLimitError,
)

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


class GroqProvider(BaseLLMProvider):
    """
    Groq provider using official AsyncGroq Python SDK.
    Supports asynchronous generation, strict timeouts, rate-limit/quota error handling,
    and actual token usage extraction.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[AsyncGroq] = None,
    ):
        self._api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self._model = model or settings.GROQ_MODEL
        self._client = client

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _get_client(self) -> AsyncGroq:
        if self._client is not None:
            return self._client
        if not self.is_configured():
            raise AIConfigurationError(
                "Groq API key is not configured. Set GROQ_API_KEY in your environment.",
                provider=self.provider_name,
            )
        self._client = AsyncGroq(api_key=self._api_key)
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

        # Build chat message payload
        chat_messages: List[Dict[str, str]] = []
        if opts.system_instruction:
            chat_messages.append({"role": "system", "content": opts.system_instruction})

        if messages:
            for m in messages:
                chat_messages.append({"role": m.role, "content": m.content})

        if prompt:
            chat_messages.append({"role": "user", "content": prompt})

        start_time = time.perf_counter()
        try:
            call_coro = client.chat.completions.create(
                model=self._model,
                messages=chat_messages,
                temperature=opts.temperature,
                max_tokens=opts.max_output_tokens,
                stop=opts.stop_sequences,
                timeout=float(opts.timeout_seconds),
            )
            response = await asyncio.wait_for(call_coro, timeout=float(opts.timeout_seconds))
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if not response or not hasattr(response, "choices") or not response.choices:
                raise AIInvalidResponseError("Groq returned an empty response or choices list", provider=self.provider_name)

            choice = response.choices[0]
            text = (choice.message.content or "") if choice.message else ""
            finish_reason = getattr(choice, "finish_reason", None)

            # Extract token usage metadata
            token_usage = None
            if hasattr(response, "usage") and response.usage:
                u = response.usage
                prompt_tok = getattr(u, "prompt_tokens", 0) or 0
                comp_tok = getattr(u, "completion_tokens", 0) or 0
                tot_tok = getattr(u, "total_tokens", 0) or (prompt_tok + comp_tok)
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
                prompt_text = " ".join(m["content"] for m in chat_messages)
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
                f"Groq generation request timed out after {opts.timeout_seconds}s",
                provider=self.provider_name,
            ) from exc

        except APITimeoutError as exc:
            raise AITimeoutError(
                f"Groq SDK request timed out: {exc}",
                provider=self.provider_name,
            ) from exc

        except AuthenticationError as exc:
            raise AIAuthenticationError(
                f"Groq authentication failed: {exc}",
                provider=self.provider_name,
                status_code=401,
            ) from exc

        except RateLimitError as exc:
            msg = str(exc)
            msg_lower = msg.lower()
            if any(w in msg_lower for w in ("quota", "billing", "credit", "balance", "daily")) and "rate limit" not in msg_lower:
                raise AIQuotaExhaustedError(
                    f"Groq quota exhausted: {msg}",
                    provider=self.provider_name,
                    status_code=429,
                ) from exc
            raise AIRateLimitError(
                f"Groq rate limit exceeded: {msg}",
                provider=self.provider_name,
                status_code=429,
            ) from exc

        except APIConnectionError as exc:
            raise AIProviderUnavailableError(
                f"Failed to connect to Groq API: {exc}",
                provider=self.provider_name,
            ) from exc

        except APIStatusError as exc:
            code = getattr(exc, "status_code", None)
            msg = str(exc)
            if code in (401, 403):
                raise AIAuthenticationError(f"Groq authentication error: {msg}", provider=self.provider_name, status_code=code) from exc
            if code == 404 or "model" in msg.lower() and "not found" in msg.lower():
                raise AIConfigurationError(f"Groq model '{self._model}' not found: {msg}", provider=self.provider_name) from exc
            if code and code >= 500:
                raise AIProviderUnavailableError(f"Groq service error: {msg}", provider=self.provider_name, status_code=code) from exc
            raise AIError(f"Groq status error: {msg}", provider=self.provider_name, status_code=code) from exc

        except Exception as exc:
            if isinstance(exc, AIError):
                raise
            raise AIError(f"Unexpected error communicating with Groq: {exc}", provider=self.provider_name) from exc

    async def check_connectivity(self) -> ConnectivityCheckResult:
        if not self.is_configured():
            return ConnectivityCheckResult(
                provider=self.provider_name,
                model=self._model,
                is_reachable=False,
                message="Groq API key is not configured.",
            )

        start = time.perf_counter()
        try:
            resp = await self.generate_text(
                prompt="Respond with the single word: OK",
                options=LLMGenerationOptions(max_output_tokens=5, temperature=0.0, timeout_seconds=15),
                operation="connectivity_probe",
            )
            lat = (time.perf_counter() - start) * 1000.0
            return ConnectivityCheckResult(
                provider=self.provider_name,
                model=self._model,
                is_reachable=True,
                message="Successfully reached Groq API.",
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
