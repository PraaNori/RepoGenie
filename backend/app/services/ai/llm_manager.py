import asyncio
import logging
from typing import Dict, List, Optional

from ...core.config import settings
from .base_provider import BaseLLMProvider
from .exceptions import AIConfigurationError, AIError
from .gemini_provider import GeminiProvider
from .groq_provider import GroqProvider
from .schemas import (
    AIStatusResponse,
    ConnectivityCheckResult,
    LLMGenerationOptions,
    LLMMessage,
    LLMResponse,
    ProviderConfigInfo,
)
from .token_tracker import token_tracker

logger = logging.getLogger(__name__)


class LLMManager:
    """
    Central orchestrator for LLM operations.
    Manages provider selection, transient error retries with exponential backoff,
    token usage recording, and connectivity verification.
    """

    def __init__(
        self,
        active_provider: Optional[str] = None,
        max_retries: Optional[int] = None,
    ):
        self._active_provider_name = (active_provider or settings.AI_PROVIDER).lower().strip()
        self._max_retries = max_retries if max_retries is not None else settings.AI_MAX_RETRIES
        self._providers: Dict[str, BaseLLMProvider] = {}

        # Register default supported providers
        self.register_provider("gemini", GeminiProvider())
        self.register_provider("groq", GroqProvider())

    @property
    def active_provider_name(self) -> str:
        return self._active_provider_name

    def set_active_provider(self, name: str) -> None:
        """
        Switches the active provider name.
        """
        norm_name = name.lower().strip()
        if norm_name not in self._providers:
            raise AIConfigurationError(
                f"Unsupported AI provider '{name}'. Available providers: {list(self._providers.keys())}",
                provider=name,
            )
        self._active_provider_name = norm_name
        logger.info("Switched active AI provider to '%s'", norm_name)

    def register_provider(self, name: str, provider: BaseLLMProvider) -> None:
        """
        Registers a new or custom provider implementation.
        """
        self._providers[name.lower().strip()] = provider

    def get_provider(self, name: Optional[str] = None) -> BaseLLMProvider:
        """
        Retrieves a registered provider instance by name, or the active provider if omitted.
        """
        target = (name or self._active_provider_name).lower().strip()
        if target not in self._providers:
            raise AIConfigurationError(
                f"Unsupported AI provider '{target}'. Available: {list(self._providers.keys())}",
                provider=target,
            )
        return self._providers[target]

    async def generate(
        self,
        prompt: str,
        options: Optional[LLMGenerationOptions] = None,
        messages: Optional[List[LLMMessage]] = None,
        provider_name: Optional[str] = None,
        operation: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> LLMResponse:
        """
        Executes text generation using the chosen or active provider.
        Transient errors are retried up to AI_MAX_RETRIES with backoff.
        Non-retryable errors (such as authentication or quota exhaustion) fail immediately.
        """
        provider = self.get_provider(provider_name)

        if not provider.is_configured():
            raise AIConfigurationError(
                f"AI provider '{provider.provider_name}' is not configured with an API key. "
                f"Please set {provider.provider_name.upper()}_API_KEY in the environment.",
                provider=provider.provider_name,
            )

        opts = options or LLMGenerationOptions(
            temperature=settings.AI_TEMPERATURE,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            timeout_seconds=settings.AI_REQUEST_TIMEOUT,
        )

        last_error: Optional[AIError] = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await provider.generate_text(
                    prompt=prompt,
                    options=opts,
                    messages=messages,
                    operation=operation,
                    job_id=job_id,
                )

                # Record token usage if available
                if response.token_usage:
                    token_tracker.record_usage(response.token_usage)

                return response

            except AIError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self._max_retries:
                    logger.error(
                        "AI generation failed permanently on provider '%s' (attempt %d/%d): %s",
                        provider.provider_name,
                        attempt + 1,
                        self._max_retries + 1,
                        exc,
                    )
                    raise exc

                backoff_delay = 0.5 * (2**attempt)
                logger.warning(
                    "AI generation transient failure on '%s' (attempt %d/%d). Retrying in %.2fs: %s",
                    provider.provider_name,
                    attempt + 1,
                    self._max_retries + 1,
                    backoff_delay,
                    exc,
                )
                await asyncio.sleep(backoff_delay)

        raise last_error or AIError("AI generation failed after retries", provider=provider.provider_name)

    async def check_connectivity(self, provider_name: Optional[str] = None) -> ConnectivityCheckResult:
        """
        Validates connectivity to the specified (or active) provider.
        """
        provider = self.get_provider(provider_name)
        return await provider.check_connectivity()

    def get_status(self) -> AIStatusResponse:
        """
        Returns the current configuration and operational status of all AI providers.
        Never reveals secret API keys.
        """
        active_provider = self.get_provider()
        available_infos: List[ProviderConfigInfo] = []

        for p_name, p_instance in self._providers.items():
            available_infos.append(
                ProviderConfigInfo(
                    provider_name=p_name,
                    is_configured=p_instance.is_configured(),
                    configured_model=p_instance.model_name,
                    is_default=(p_name == self._active_provider_name),
                    supported_models=[],
                )
            )

        return AIStatusResponse(
            active_provider=self._active_provider_name,
            is_active_provider_configured=active_provider.is_configured(),
            available_providers=available_infos,
            token_summary=token_tracker.get_summary(),
        )


# Singleton LLM manager instance
llm_manager = LLMManager()
