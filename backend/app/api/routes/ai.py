import logging
from typing import Optional
from fastapi import APIRouter, Query

from ...services.ai import (
    AIStatusResponse,
    ConnectivityCheckResult,
    llm_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AIStatusResponse)
def get_ai_status() -> AIStatusResponse:
    """
    Returns the configuration and operational status of configured AI providers.
    Never exposes API keys or credentials.
    """
    return llm_manager.get_status()


@router.post("/test-connectivity", response_model=ConnectivityCheckResult)
async def test_ai_connectivity(
    provider: Optional[str] = Query(
        default=None,
        description="Optional provider name to test ('gemini' or 'groq'). Defaults to active provider.",
    )
) -> ConnectivityCheckResult:
    """
    Tests live reachability and credential validity for the specified or active AI provider.
    Executes a minimal, low-token probe. Does not execute repository analysis tasks.
    """
    return await llm_manager.check_connectivity(provider_name=provider)
