from fastapi import APIRouter
from .routes.health import router as health_router
from .routes.jobs import router as jobs_router

api_router = APIRouter(prefix="/api/v1")

# Mount routes under /api/v1
api_router.include_router(health_router)
api_router.include_router(jobs_router)
