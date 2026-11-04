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

    # Code Parsing & Structural Extraction limits (Milestone 2.4)
    MAX_CODE_FILE_SIZE_BYTES: int = 524_288  # 512 KB per source file eligible for AST parsing
    MAX_CODE_FILES_TO_PARSE: int = 500      # Maximum source files to parse per repository
    MAX_SNIPPET_LINES: int = 60             # Maximum lines for stored code snippet
    MAX_SNIPPET_CHARS: int = 2500           # Maximum characters for stored code snippet

    # Architecture & Dependency Analysis limits (Milestone 2.5)
    MAX_GRAPH_NODES: int = 1000             # Maximum nodes in dependency and call graphs
    MAX_GRAPH_EDGES: int = 5000             # Maximum edges in dependency and call graphs
    MAX_RELATIONSHIPS_PER_FILE: int = 100   # Maximum extracted relationships per file
    MAX_UNRESOLVED_REFS_RETAINED: int = 500 # Maximum unresolved references stored

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
