from datetime import datetime, timezone
from fastapi import APIRouter
from ...core.config import settings
from ...models.schemas import HealthResponse

router = APIRouter(tags=["health"])

@router.get("/health", response_model=HealthResponse)
def get_health():
    """Health check endpoint to verify backend service operational status."""
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        timestamp=datetime.now(timezone.utc),
    )
