"""
RepoGenie AI Services Foundation (Milestone 3.1).
Provider-independent LLM integration foundation for Google Gemini and Groq.
"""

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
from .gemini_provider import GeminiProvider
from .groq_provider import GroqProvider
from .llm_manager import LLMManager, llm_manager
from .schemas import (
    AIStatusResponse,
    ConnectivityCheckResult,
    LLMGenerationOptions,
    LLMMessage,
    LLMResponse,
    ProviderConfigInfo,
    TokenUsageRecord,
    TokenUsageSummary,
)
from .token_tracker import TokenTracker, token_tracker

__all__ = [
    "BaseLLMProvider",
    "GeminiProvider",
    "GroqProvider",
    "LLMManager",
    "llm_manager",
    "TokenTracker",
    "token_tracker",
    "LLMMessage",
    "LLMGenerationOptions",
    "LLMResponse",
    "TokenUsageRecord",
    "TokenUsageSummary",
    "ProviderConfigInfo",
    "ConnectivityCheckResult",
    "AIStatusResponse",
    "AIError",
    "AIConfigurationError",
    "AIAuthenticationError",
    "AIRateLimitError",
    "AIQuotaExhaustedError",
    "AITimeoutError",
    "AIProviderUnavailableError",
    "AIInvalidResponseError",
]
