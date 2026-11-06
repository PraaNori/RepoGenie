"""
Caption Generation Service (Milestone 5, Phase 5.5).

Orchestrates deterministic subtitle generation, timing calculation, and file persistence
for every scene in an EducationalStoryboard using completed ElevenLabs narration audio assets.
Generates per-scene SRT/VTT files as well as a composite full-video subtitle track.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.services.ai.script_generation.schemas import EducationalScript
from app.services.ai.storyboard_generation.schemas import EducationalStoryboard, StoryboardScene
from app.services.video.narration.schemas import (
    NarrationAsset,
    NarrationAssetStatus,
    NarrationGenerationResult,
)
from .caption_storage import CaptionAssetStorageManager, caption_storage_manager
from .formatter import (
    format_srt_cues,
    format_vtt_cues,
)
from .schemas import (
    Caption,
    CaptionGenerationResult,
    CaptionStatus,
    SceneCaptionAsset,
    TimingProvenance,
)
from .segmenter import generate_scene_captions

logger = logging.getLogger(__name__)


class CaptionService:
    """Manages scene-by-scene and full-video subtitle generation, timing, and storage."""

    def __init__(self, storage: Optional[CaptionAssetStorageManager] = None):
        self._storage = storage or caption_storage_manager

    def generate_captions_for_job(
        self,
        job_id: str,
        storyboard: EducationalStoryboard,
        script: Optional[EducationalScript] = None,
        narration: Optional[NarrationGenerationResult] = None,
        refresh: bool = False,
    ) -> CaptionGenerationResult:
        """
        Generates and persists synchronized captions (.srt and .vtt) for all scenes
        in the storyboard using measured narration audio durations.
        """
        if not storyboard or not storyboard.scenes:
            raise ValueError("Educational storyboard with at least one scene is required for caption generation.")

        if not narration or not narration.assets:
            raise ValueError("Narration audio assets must be generated before caption generation can begin.")

        # Map narration assets by scene_id and scene_number for reliable lookup
        narration_by_scene_id: Dict[str, NarrationAsset] = {
            a.scene_id: a for a in narration.assets if a.scene_id
        }
        narration_by_scene_num: Dict[int, NarrationAsset] = {
            a.scene_number: a for a in narration.assets
        }

        scene_assets: List[SceneCaptionAsset] = []
        full_video_cues: List[Tuple[float, float, str]] = []
        cumulative_time = 0.0
        total_captions_count = 0
        all_warnings: List[str] = []

        for scene in storyboard.scenes:
            scene_asset_id = f"caption_{scene.scene_id.replace('-', '_')}"
            narration_asset = narration_by_scene_id.get(scene.scene_id) or narration_by_scene_num.get(scene.scene_number)

            # 1. Check if narration asset exists and its status
            if not narration_asset:
                scene_assets.append(
                    SceneCaptionAsset(
                        asset_id=scene_asset_id,
                        job_id=job_id,
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        script_section_id=scene.script_section_id or "",
                        status=CaptionStatus.FAILED,
                        error_message=f"No narration asset found for scene {scene.scene_number} ({scene.scene_id}).",
                    )
                )
                continue

            if narration_asset.status == NarrationAssetStatus.FAILED:
                scene_assets.append(
                    SceneCaptionAsset(
                        asset_id=scene_asset_id,
                        job_id=job_id,
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        script_section_id=scene.script_section_id or "",
                        status=CaptionStatus.FAILED,
                        error_message=f"Narration generation failed for scene {scene.scene_number}: {narration_asset.error_message}",
                    )
                )
                continue

            # 2. Check if scene is skipped or has no spoken narration
            narration_text = (narration_asset.narration_text or "").strip()
            if narration_asset.status == NarrationAssetStatus.SKIPPED or not narration_text:
                scene_assets.append(
                    SceneCaptionAsset(
                        asset_id=scene_asset_id,
                        job_id=job_id,
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        script_section_id=scene.script_section_id or "",
                        status=CaptionStatus.SKIPPED,
                        duration_seconds=0.0,
                        cumulative_start_seconds=cumulative_time,
                        cumulative_end_seconds=cumulative_time,
                        captions=[],
                    )
                )
                continue

            # 3. Process completed narration scene
            scene_duration = narration_asset.duration_seconds
            if scene_duration <= 0.0:
                # Fallback to expected scene duration if audio measurement was somehow 0
                scene_duration = scene.estimated_duration_seconds or 3.0

            scene_start = round(cumulative_time, 3)
            scene_end = round(cumulative_time + scene_duration, 3)

            # Check for cache reuse
            srt_exists = self._storage.caption_file_exists(job_id, scene_asset_id, format="srt")
            vtt_exists = self._storage.caption_file_exists(job_id, scene_asset_id, format="vtt")

            try:
                # Segment narration text into timed subtitle cues
                captions = generate_scene_captions(
                    scene_id=scene.scene_id,
                    narration_text=narration_text,
                    audio_duration_seconds=scene_duration,
                    timing_provenance=TimingProvenance.ESTIMATED,
                )

                # Format scene SRT and WebVTT
                cues_tuples = [(c.start_seconds, c.end_seconds, c.text) for c in captions]
                srt_content = format_srt_cues(cues_tuples, start_index=1)
                vtt_content = format_vtt_cues(cues_tuples, header_title=f"Scene {scene.scene_number} - {scene.title}")

                # Save files atomically to disk
                srt_path = self._storage.save_caption_file(job_id, scene_asset_id, srt_content, format="srt")
                vtt_path = self._storage.save_caption_file(job_id, scene_asset_id, vtt_content, format="vtt")

                srt_size = srt_path.stat().st_size
                vtt_size = vtt_path.stat().st_size

                # Collect cues for composite full-video subtitle track (offset by scene_start)
                for c in captions:
                    full_video_cues.append(
                        (
                            round(scene_start + c.start_seconds, 3),
                            round(scene_start + c.end_seconds, 3),
                            c.text,
                        )
                    )

                scene_asset = SceneCaptionAsset(
                    asset_id=scene_asset_id,
                    job_id=job_id,
                    scene_id=scene.scene_id,
                    scene_number=scene.scene_number,
                    script_section_id=scene.script_section_id or "",
                    status=CaptionStatus.COMPLETED,
                    duration_seconds=scene_duration,
                    cumulative_start_seconds=scene_start,
                    cumulative_end_seconds=scene_end,
                    captions=captions,
                    srt_file_path=self._storage.get_relative_caption_path(job_id, scene_asset_id, format="srt"),
                    vtt_file_path=self._storage.get_relative_caption_path(job_id, scene_asset_id, format="vtt"),
                    srt_file_size_bytes=srt_size,
                    vtt_file_size_bytes=vtt_size,
                    timing_provenance=TimingProvenance.ESTIMATED,
                )
                scene_assets.append(scene_asset)
                total_captions_count += len(captions)

            except Exception as e:
                logger.exception("Failed to generate captions for scene %s: %s", scene.scene_id, e)
                scene_assets.append(
                    SceneCaptionAsset(
                        asset_id=scene_asset_id,
                        job_id=job_id,
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        script_section_id=scene.script_section_id or "",
                        status=CaptionStatus.FAILED,
                        error_message=str(e),
                    )
                )

            # Advance cumulative video timeline
            cumulative_time = scene_end

        # 4. Generate composite full-video subtitle tracks
        full_srt_rel: Optional[str] = None
        full_vtt_rel: Optional[str] = None
        full_srt_size = 0
        full_vtt_size = 0

        if full_video_cues:
            try:
                full_srt_content = format_srt_cues(full_video_cues, start_index=1)
                full_vtt_content = format_vtt_cues(full_video_cues, header_title="Full Video Track")

                full_srt_path = self._storage.save_caption_file(job_id, "full", full_srt_content, format="srt")
                full_vtt_path = self._storage.save_caption_file(job_id, "full", full_vtt_content, format="vtt")

                full_srt_rel = self._storage.get_relative_caption_path(job_id, "full", format="srt")
                full_vtt_rel = self._storage.get_relative_caption_path(job_id, "full", format="vtt")
                full_srt_size = full_srt_path.stat().st_size
                full_vtt_size = full_vtt_path.stat().st_size
            except Exception as e:
                logger.error("Failed to generate full-video composite subtitle track: %s", e)
                all_warnings.append(f"Composite subtitle track generation error: {e}")

        # 5. Aggregate overall result
        total_scenes = len(storyboard.scenes)
        completed = sum(1 for a in scene_assets if a.status == CaptionStatus.COMPLETED)
        failed = sum(1 for a in scene_assets if a.status == CaptionStatus.FAILED)
        skipped = sum(1 for a in scene_assets if a.status == CaptionStatus.SKIPPED)

        if total_scenes > 0 and (completed + skipped) == total_scenes and failed == 0:
            overall_status = CaptionStatus.COMPLETED
        elif failed > 0:
            overall_status = CaptionStatus.FAILED
        else:
            overall_status = CaptionStatus.PENDING

        return CaptionGenerationResult(
            job_id=job_id,
            status=overall_status,
            total_scenes=total_scenes,
            scenes_completed=completed,
            scenes_failed=failed,
            scenes_skipped=skipped,
            total_captions=total_captions_count,
            scene_assets=scene_assets,
            full_srt_file_path=full_srt_rel,
            full_vtt_file_path=full_vtt_rel,
            full_srt_file_size_bytes=full_srt_size,
            full_vtt_file_size_bytes=full_vtt_size,
            timing_provenance=TimingProvenance.ESTIMATED,
            total_duration_seconds=round(cumulative_time, 2),
            warnings=all_warnings,
        )


# Global singleton instance
caption_service = CaptionService()
