"""
Narration Generation Module (Milestone 5, Phase 5.4).

Provides ElevenLabs Text-to-Speech audio synthesis, duration measurement,
scene-by-scene audio asset management, and duration synchronization reports.
"""

from .audio_storage import AudioAssetStorageManager, audio_storage_manager
from .elevenlabs_provider import (
    ElevenLabsAuthError,
    ElevenLabsBadRequestError,
    ElevenLabsConfigurationError,
    ElevenLabsError,
    ElevenLabsRateLimitError,
    ElevenLabsServerError,
    ElevenLabsTimeoutError,
    ElevenLabsTTSProvider,
    ElevenLabsVoiceNotFoundError,
    elevenlabs_provider,
)
from .schemas import (
    NarrationAsset,
    NarrationAssetStatus,
    NarrationGenerationResult,
    NarrationSyncSummary,
    SceneSyncReport,
)
from .service import NarrationService, narration_service

__all__ = [
    "NarrationAsset",
    "NarrationAssetStatus",
    "NarrationGenerationResult",
    "NarrationSyncSummary",
    "SceneSyncReport",
    "AudioAssetStorageManager",
    "audio_storage_manager",
    "ElevenLabsError",
    "ElevenLabsConfigurationError",
    "ElevenLabsAuthError",
    "ElevenLabsVoiceNotFoundError",
    "ElevenLabsBadRequestError",
    "ElevenLabsRateLimitError",
    "ElevenLabsTimeoutError",
    "ElevenLabsServerError",
    "ElevenLabsTTSProvider",
    "elevenlabs_provider",
    "NarrationService",
    "narration_service",
]
