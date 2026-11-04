from typing import Optional


class AIError(Exception):
    """Base exception for all AI provider and manager errors."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable

    def __str__(self) -> str:
        prov_prefix = f"[{self.provider}] " if self.provider else ""
        code_suffix = f" (Status {self.status_code})" if self.status_code else ""
        return f"{prov_prefix}{self.message}{code_suffix}"


class AIConfigurationError(AIError):
    """Raised when an AI provider is missing required configuration (e.g. API key) or model."""

    def __init__(self, message: str, provider: Optional[str] = None):
        super().__init__(message, provider=provider, status_code=500, retryable=False)


class AIAuthenticationError(AIError):
    """Raised when provider authentication fails (e.g. invalid API key, 401/403)."""

    def __init__(self, message: str, provider: Optional[str] = None, status_code: int = 401):
        super().__init__(message, provider=provider, status_code=status_code, retryable=False)


class AIRateLimitError(AIError):
    """Raised when provider rate limits are exceeded (RPM / TPM). Typically transient."""

    def __init__(self, message: str, provider: Optional[str] = None, status_code: int = 429):
        super().__init__(message, provider=provider, status_code=status_code, retryable=True)


class AIQuotaExhaustedError(AIError):
    """Raised when provider quota or credits are exhausted. Non-retryable."""

    def __init__(self, message: str, provider: Optional[str] = None, status_code: int = 429):
        super().__init__(message, provider=provider, status_code=status_code, retryable=False)


class AITimeoutError(AIError):
    """Raised when an AI generation request exceeds the timeout threshold."""

    def __init__(self, message: str, provider: Optional[str] = None):
        super().__init__(message, provider=provider, status_code=504, retryable=True)


class AIProviderUnavailableError(AIError):
    """Raised when the provider service is down or unreachable (e.g. 500/502/503/504)."""

    def __init__(self, message: str, provider: Optional[str] = None, status_code: int = 503):
        super().__init__(message, provider=provider, status_code=status_code, retryable=True)


class AIInvalidResponseError(AIError):
    """Raised when the provider returns an empty, invalid, or unparseable response."""

    def __init__(self, message: str, provider: Optional[str] = None):
        super().__init__(message, provider=provider, status_code=502, retryable=False)
