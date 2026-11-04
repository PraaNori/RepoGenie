import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "RepoGenie API"
    APP_VERSION: str = "0.2.1"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # CORS configuration
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Storage paths
    STORAGE_DIR: str = "./storage"
    REPOS_DIR: str = "./storage/repos"

    # Repository Ingestion limits
    CLONE_TIMEOUT_SECONDS: int = 120
    MAX_REPO_SIZE_MB: int = 500
    CLONE_DEPTH: int = 1

    # Repository Structure & Analysis limits (Milestone 2.3)
    MAX_TRAVERSAL_DEPTH: int = 15
    MAX_FILES_INDEXED: int = 5000
    MAX_FILE_SIZE_BYTES: int = 1_048_576  # 1 MB maximum for manifest content inspection

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def repos_path(self) -> Path:
        base = Path(self.REPOS_DIR)
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()

    @property
    def storage_path(self) -> Path:
        base = Path(self.STORAGE_DIR)
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()

settings = Settings()
