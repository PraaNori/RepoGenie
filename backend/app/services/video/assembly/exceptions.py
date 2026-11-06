"""
Exceptions for FFmpeg Video Assembly (Milestone 6, Phase 6.1).
"""

class VideoAssemblyError(Exception):
    """Base exception for all video assembly operations."""
    pass


class FFmpegNotFoundError(VideoAssemblyError):
    """Raised when the ffmpeg executable cannot be located or is not executable."""
    pass


class FFprobeNotFoundError(VideoAssemblyError):
    """Raised when the ffprobe executable cannot be located or is not executable."""
    pass


class FFmpegExecutionError(VideoAssemblyError):
    """Raised when an ffmpeg or ffprobe subprocess exits with a non-zero status code."""
    def __init__(self, message: str, return_code: int = -1, stderr: str = "", command: str = ""):
        super().__init__(message)
        self.return_code = return_code
        self.stderr = stderr
        self.command = command


class FFmpegTimeoutError(VideoAssemblyError):
    """Raised when an ffmpeg or ffprobe subprocess exceeds its execution timeout."""
    def __init__(self, message: str, timeout_seconds: float):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class MediaProbeError(VideoAssemblyError):
    """Raised when ffprobe fails to parse or analyze media streams."""
    pass


class InvalidRenderConfigurationError(VideoAssemblyError):
    """Raised when video rendering configuration parameters violate bounds or codec constraints."""
    pass


class VideoStorageError(VideoAssemblyError):
    """Raised when file storage operations or path containment checks fail."""
    pass


class VisualPreparationError(VideoAssemblyError):
    """Raised when visual asset rasterization or SVG security validation fails."""
    pass


class SceneRenderError(VideoAssemblyError):
    """Raised when rendering an individual scene clip fails."""
    def __init__(self, message: str, scene_id: str = "", scene_number: int = 0):
        super().__init__(message)
        self.scene_id = scene_id
        self.scene_number = scene_number


class JobRenderConcurrencyError(VideoAssemblyError):
    """Raised when an operation conflicts with an ongoing render operation on the same job."""
    pass
