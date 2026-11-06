"""
Caption Generation Package (Milestone 5, Phase 5.5).

Exports caption schemas, formatter, segmenter, storage manager, and service.
"""

from .caption_storage import CaptionAssetStorageManager, caption_storage_manager
from .formatter import (
    format_srt_cues,
    format_vtt_cues,
    seconds_to_srt_timestamp,
    seconds_to_vtt_timestamp,
    validate_srt_content,
    validate_vtt_content,
)
from .schemas import (
    Caption,
    CaptionGenerationResult,
    CaptionStatus,
    SceneCaptionAsset,
    TimingProvenance,
)
from .segmenter import (
    generate_scene_captions,
    split_text_into_cues,
)
from .service import CaptionService, caption_service

__all__ = [
    "Caption",
    "CaptionStatus",
    "TimingProvenance",
    "SceneCaptionAsset",
    "CaptionGenerationResult",
    "CaptionAssetStorageManager",
    "caption_storage_manager",
    "CaptionService",
    "caption_service",
    "format_srt_cues",
    "format_vtt_cues",
    "seconds_to_srt_timestamp",
    "seconds_to_vtt_timestamp",
    "validate_srt_content",
    "validate_vtt_content",
    "generate_scene_captions",
    "split_text_into_cues",
]
