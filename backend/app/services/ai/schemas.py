from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class LLMGenerationOptions(BaseModel):
    temperature: float = 0.2
    max_output_tokens: int = 2048
    timeout_seconds: int = 60
    system_instruction: Optional[str] = None
    stop_sequences: Optional[List[str]] = None


class TokenUsageRecord(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    is_estimated: bool = False
    provider: str
    model: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operation: Optional[str] = None
    job_id: Optional[str] = None


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    finish_reason: Optional[str] = None
    token_usage: Optional[TokenUsageRecord] = None
    latency_ms: float = 0.0
    raw_response_metadata: Dict[str, Any] = Field(default_factory=dict)


class ProviderConfigInfo(BaseModel):
    provider_name: str
    is_configured: bool
    configured_model: str
    is_default: bool
    supported_models: List[str] = Field(default_factory=list)


class ConnectivityCheckResult(BaseModel):
    provider: str
    model: str
    is_reachable: bool
    message: str
    latency_ms: Optional[float] = None
    error_details: Optional[str] = None


class TokenUsageSummary(BaseModel):
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_requests: int = 0
    estimated_requests_count: int = 0
    by_provider: Dict[str, int] = Field(default_factory=dict)
    by_model: Dict[str, int] = Field(default_factory=dict)


class AIStatusResponse(BaseModel):
    active_provider: str
    is_active_provider_configured: bool
    available_providers: List[ProviderConfigInfo] = Field(default_factory=list)
    token_summary: TokenUsageSummary
