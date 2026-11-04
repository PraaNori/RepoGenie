from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class StageEnum(str, Enum):
    REPO_FETCHING = "Repository Fetching"
    REPO_ANALYSIS = "Repository Analysis"
    CODE_UNDERSTANDING = "Code Understanding"
    AI_SUMMARY = "AI Summary Generation"
    SCRIPT_GENERATION = "Script Generation"
    STORYBOARD_GENERATION = "Storyboard Generation"
    VISUAL_GENERATION = "Visual Generation"
    VOICE_GENERATION = "Voice Generation"
    VIDEO_ASSEMBLY = "Video Assembly"

class StatusEnum(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class StageInfo(BaseModel):
    id: int
    name: str
    status: StatusEnum = StatusEnum.PENDING
    detail: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str
    version: str
    environment: str
    timestamp: datetime

class JobCreateRequest(BaseModel):
    github_url: str = Field(..., description="Public GitHub repository URL (e.g. https://github.com/owner/repo)")

class VideoResult(BaseModel):
    repo_name: str
    repo_url: str
    description: str
    tech_stack: List[str]
    summary: str
    video_url: Optional[str] = None
    duration_seconds: Optional[int] = None

# --- Milestone 2.3: Repository Structure & File Analysis Models ---

class LanguageStat(BaseModel):
    name: str
    file_count: int
    percentage: float  # e.g., 68.5

class DependencyItem(BaseModel):
    name: str
    version_spec: Optional[str] = None
    source_file: str

class ManifestInfo(BaseModel):
    file_path: str
    ecosystem: str
    dependencies_count: int
    dependencies: List[DependencyItem] = []

class ConfigurationFileInfo(BaseModel):
    file_path: str
    config_type: str  # e.g. "docker", "ci_cd", "environment_template", "build_tool", "lint_format"

class DirectoryTreeNode(BaseModel):
    name: str
    path: str  # relative to repository root
    type: str  # "file" or "directory"
    size_bytes: Optional[int] = None
    extension: Optional[str] = None
    children: Optional[List["DirectoryTreeNode"]] = None

DirectoryTreeNode.model_rebuild()

class RepoStatistics(BaseModel):
    total_files: int
    total_directories: int
    source_files: int
    filtered_files: int
    total_size_bytes: int
    configuration_files: int
    dependency_manifests: int
    recognized_languages_count: int

class RepoAnalysisResult(BaseModel):
    repository_name: str
    directory_tree: DirectoryTreeNode
    statistics: RepoStatistics
    languages: List[LanguageStat]
    dependency_files: List[ManifestInfo]
    configuration_files: List[ConfigurationFileInfo]
    analysis_status: StatusEnum = StatusEnum.COMPLETED
    warnings: List[str] = []

# --- Milestone 2.4: Code Parsing & Structural Extraction Models ---

class SourceLocation(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    start_column: int
    end_column: int

class ParsingWarning(BaseModel):
    file_path: str
    line_number: Optional[int] = None
    message: str
    warning_type: str

class FunctionInfo(BaseModel):
    name: str
    file_path: str
    location: SourceLocation
    parameters: List[str] = []
    is_async: bool = False
    visibility: Optional[str] = None
    return_type: Optional[str] = None
    enclosing_scope: Optional[str] = None
    snippet: Optional[str] = None

class MethodInfo(BaseModel):
    name: str
    parent_class: str
    file_path: str
    location: SourceLocation
    parameters: List[str] = []
    is_async: bool = False
    visibility: Optional[str] = None
    return_type: Optional[str] = None
    snippet: Optional[str] = None

class ClassInfo(BaseModel):
    name: str
    file_path: str
    location: SourceLocation
    base_classes: List[str] = []
    methods: List[str] = []
    nested_classes: List[str] = []
    snippet: Optional[str] = None

class ImportInfo(BaseModel):
    module: str
    symbols: List[str] = []
    alias: Optional[str] = None
    file_path: str
    line_number: int

class FunctionCallInfo(BaseModel):
    call_name: str
    enclosing_scope: Optional[str] = None
    file_path: str
    line_number: int

class ParsedFile(BaseModel):
    file_path: str
    language: str
    status: str  # "success", "syntax_error", "skipped", "error"
    functions: List[FunctionInfo] = []
    classes: List[ClassInfo] = []
    methods: List[MethodInfo] = []
    imports: List[ImportInfo] = []
    function_calls: List[FunctionCallInfo] = []
    warnings: List[ParsingWarning] = []
    total_lines: int = 0

class ParsedRepository(BaseModel):
    job_id: str
    repository_name: str
    total_parsed_files: int
    total_functions: int
    total_classes: int
    total_methods: int
    total_imports: int
    total_function_calls: int
    supported_languages: List[str]
    files: List[ParsedFile] = []
    parsing_status: StatusEnum = StatusEnum.COMPLETED
    warnings: List[str] = []

# --- Main Job Models ---

class JobResponse(BaseModel):
    job_id: str
    repo_url: str
    repo_name: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    clone_url: Optional[str] = None
    ingestion_status: StatusEnum = StatusEnum.PENDING
    status: StatusEnum
    current_stage: str
    progress_percentage: int
    stages: List[StageInfo]
    created_at: datetime
    updated_at: datetime
    analysis: Optional[RepoAnalysisResult] = None
    code_analysis: Optional[ParsedRepository] = None
    result: Optional[VideoResult] = None
    error: Optional[str] = None
