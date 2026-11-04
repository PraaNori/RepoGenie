from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.api import api_router
from .api.routes.health import router as root_health_router
from .core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for RepoGenie — AI-Powered GitHub Repository to Educational Video Generator",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
origins = settings.cors_origins_list
if "*" not in origins and "http://localhost:5173" not in origins:
    origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root convenience health endpoint
app.include_router(root_health_router)

# Versioned API routes under /api/v1
app.include_router(api_router)

@app.get("/", tags=["root"])
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
        "api_v1": "/api/v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
