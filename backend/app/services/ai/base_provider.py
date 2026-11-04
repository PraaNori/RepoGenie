from abc import ABC, abstractmethod
from typing import List, Optional

from .schemas import (
    ConnectivityCheckResult,
    LLMGenerationOptions,
    LLMMessage,
    LLMResponse,
    TokenUsageRecord,
)


class BaseLLMProvider(ABC):
    """
    Abstract interface for LLM providers.
    All concrete providers (Gemini, Groq, OpenAI, Claude) must adhere to this interface.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Normalized unique identifier for the provider (e.g. 'gemini', 'groq')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Active model identifier currently configured for the provider."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if the provider has all credentials and settings required to make calls."""
        pass

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        options: Optional[LLMGenerationOptions] = None,
        messages: Optional[List[LLMMessage]] = None,
        operation: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> LLMResponse:
        """
        Sends an asynchronous text generation request to the provider.

        Args:
            prompt: Main prompt or user instruction string.
            options: Optional generation parameters (temperature, max_tokens, etc.).
            messages: Optional structured conversational message history.
            operation: Identifier for the calling operation (e.g. 'connectivity_check', 'repo_summary').
            job_id: Optional UUID of the active RepoGenie job.

        Returns:
            Normalized LLMResponse containing generated text and usage metadata.
        """
        pass

    @abstractmethod
    async def check_connectivity(self) -> ConnectivityCheckResult:
        """
        Performs a lightweight, low-token probe to confirm that the provider endpoint is reachable
        and credentials are valid, without executing full analysis workloads.
        """
        pass

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """
        Conservative token estimator (~4 characters per token) used strictly when
        a provider does not supply token usage metadata.
        """
        if not text:
            return 0
        return max(1, len(text) // 4)
