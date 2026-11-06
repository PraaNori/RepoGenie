"""
Video Assembly Input Service (Milestone 5, Phase 5.6).

Aggregates, orders, cross-references, and validates all generated visual, narration,
and caption assets into a structured, unified VideoAssemblyInput package ready
for video compilation in Milestone 6.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....models.schemas import StatusEnum
from ...ai.storyboard_generation.schemas import EducationalStoryboard, StoryboardScene
from ..visual_generation.storage import visual_storage_manager
from ..visual_generation.schemas import VisualGenerationResult
from ..narration.audio_storage import audio_storage_manager
from ..narration.schemas import NarrationAssetStatus, NarrationGenerationResult
from ..captions.caption_storage import caption_storage_manager
from ..captions.schemas import CaptionGenerationResult, CaptionStatus
from .schemas import (
    AssemblyAssetReference,
    AssemblyReadinessReport,
    AssemblyScene,
    VideoAssemblyInput,
)
from .validator import AssemblyPreflightValidator, preflight_validator

logger = logging.getLogger(__name__)


class AssemblyInputService:
    """Service that compiles and validates the VideoAssemblyInput package."""

    def __init__(self, validator: Optional[AssemblyPreflightValidator] = None):
        self._validator = validator or preflight_validator

    def build_assembly_input(
        self,
        job_id: str,
        repo_name: str,
        storyboard: Optional[EducationalStoryboard],
        visual_generation: Optional[VisualGenerationResult],
        narration: Optional[NarrationGenerationResult],
        captions: Optional[CaptionGenerationResult],
    ) -> VideoAssemblyInput:
        """
        Builds the complete VideoAssemblyInput package from job assets and validates
        all references on disk.
        """
        if not storyboard or not storyboard.scenes:
            # Package with empty scenes to trigger proper preflight validation failure
            empty_report = self._validator.evaluate_package(
                job_id=job_id,
                scenes=[],
                full_video_srt=None,
                full_video_vtt=None,
            )
            return VideoAssemblyInput(
                job_id=job_id,
                repo_name=repo_name,
                scenes=[],
                total_scenes=0,
                total_duration_seconds=0.0,
                readiness_report=empty_report,
            )

        # 1. Enforce strict 1-indexed monotonic scene ordering
        ordered_scenes = sorted(storyboard.scenes, key=lambda s: s.scene_number)

        # Build lookup maps for fast asset association
        visual_map = {}
        if visual_generation:
            if getattr(visual_generation, "scene_assets", None):
                for sva in visual_generation.scene_assets:
                    target_asset = sva.primary_asset if sva.primary_asset else (sva.supplementary_assets[0] if sva.supplementary_assets else None)
                    if target_asset:
                        visual_map[sva.scene_id] = target_asset
                        visual_map[f"num_{sva.scene_number}"] = target_asset
            elif getattr(visual_generation, "assets", None):
                for va in visual_generation.assets:
                    visual_map[va.scene_id] = va
                    visual_map[f"num_{va.scene_number}"] = va

        narration_map = {}
        if narration and narration.assets:
            for na in narration.assets:
                narration_map[na.scene_id] = na
                narration_map[f"num_{na.scene_number}"] = na

        caption_map = {}
        if captions and captions.scene_assets:
            for ca in captions.scene_assets:
                caption_map[ca.scene_id] = ca
                caption_map[f"num_{ca.scene_number}"] = ca

        assembly_scenes: List[AssemblyScene] = []
        cumulative_time = 0.0

        for scene in ordered_scenes:
            # 1. Determine narration text
            narration_text = ""
            if scene.narration:
                if hasattr(scene.narration, "excerpt") and scene.narration.excerpt:
                    narration_text = scene.narration.excerpt.strip()
                elif isinstance(scene.narration, str):
                    narration_text = scene.narration.strip()

            # Find narration asset
            narr_asset = narration_map.get(scene.scene_id) or narration_map.get(f"num_{scene.scene_number}")
            if not narration_text and narr_asset and getattr(narr_asset, "narration_text", None):
                narration_text = narr_asset.narration_text.strip()

            # Determine if scene is intentionally silent (no spoken text planned or asset was skipped)
            is_silent = (len(narration_text) == 0) and (narr_asset is None or narr_asset.status == NarrationAssetStatus.SKIPPED)

            # Determine scene duration based on narration or planned estimation
            if narr_asset and narr_asset.status == NarrationAssetStatus.COMPLETED and narr_asset.duration_seconds > 0:
                scene_duration = narr_asset.duration_seconds
            else:
                scene_duration = float(scene.estimated_duration_seconds or 5.0)

            start_seconds = round(cumulative_time, 3)
            end_seconds = round(start_seconds + scene_duration, 3)
            cumulative_time = end_seconds

            # --- 1. Visual Asset Resolution ---
            visual_ref: Optional[AssemblyAssetReference] = None
            vis_asset = visual_map.get(scene.scene_id) or visual_map.get(f"num_{scene.scene_number}")
            if vis_asset:
                asset_id = vis_asset.asset_id
                svg_filename = f"{asset_id}.svg"
                vis_path = visual_storage_manager.get_job_visuals_dir(job_id) / svg_filename
                valid, err, size = self._validator.validate_visual_file(vis_path)
                visual_ref = AssemblyAssetReference(
                    asset_id=asset_id,
                    scene_id=scene.scene_id,
                    asset_type="visual",
                    relative_path=visual_storage_manager.get_relative_asset_path(job_id, svg_filename),
                    file_format="svg",
                    file_size_bytes=size,
                    duration_seconds=None,
                    is_valid=valid,
                    validation_error=err,
                )

            # --- 2. Narration Audio Asset Resolution ---
            narration_ref: Optional[AssemblyAssetReference] = None
            if not is_silent:
                if narr_asset:
                    asset_id = narr_asset.asset_id
                    audio_path = audio_storage_manager.get_audio_path(job_id, asset_id, format="mp3")
                    valid, err, size, measured_dur = self._validator.validate_audio_file(audio_path)
                    narration_ref = AssemblyAssetReference(
                        asset_id=asset_id,
                        scene_id=scene.scene_id,
                        asset_type="narration",
                        relative_path=audio_storage_manager.get_relative_audio_path(job_id, asset_id, format="mp3"),
                        file_format="mp3",
                        file_size_bytes=size,
                        duration_seconds=measured_dur if valid else narr_asset.duration_seconds,
                        is_valid=valid,
                        validation_error=err,
                    )

            # --- 3. Per-scene Caption Asset Resolution ---
            caption_srt_ref: Optional[AssemblyAssetReference] = None
            caption_vtt_ref: Optional[AssemblyAssetReference] = None
            if not is_silent:
                cap_asset = caption_map.get(scene.scene_id) or caption_map.get(f"num_{scene.scene_number}")
                if cap_asset:
                    cap_id = cap_asset.asset_id
                    srt_path = caption_storage_manager.get_caption_path(job_id, cap_id, format="srt")
                    vtt_path = caption_storage_manager.get_caption_path(job_id, cap_id, format="vtt")

                    srt_valid, srt_err, srt_size = self._validator.validate_caption_file(srt_path, format="srt")
                    caption_srt_ref = AssemblyAssetReference(
                        asset_id=cap_id,
                        scene_id=scene.scene_id,
                        asset_type="caption_srt",
                        relative_path=caption_storage_manager.get_relative_caption_path(job_id, cap_id, format="srt"),
                        file_format="srt",
                        file_size_bytes=srt_size,
                        is_valid=srt_valid,
                        validation_error=srt_err,
                    )

                    vtt_valid, vtt_err, vtt_size = self._validator.validate_caption_file(vtt_path, format="vtt")
                    caption_vtt_ref = AssemblyAssetReference(
                        asset_id=cap_id,
                        scene_id=scene.scene_id,
                        asset_type="caption_vtt",
                        relative_path=caption_storage_manager.get_relative_caption_path(job_id, cap_id, format="vtt"),
                        file_format="vtt",
                        file_size_bytes=vtt_size,
                        is_valid=vtt_valid,
                        validation_error=vtt_err,
                    )

            raw_purpose = getattr(scene, "purpose", getattr(scene, "section_purpose", "scene_overview"))
            section_purpose_val = raw_purpose.value if hasattr(raw_purpose, "value") else str(raw_purpose)

            assembly_scene = AssemblyScene(
                scene_id=scene.scene_id,
                scene_number=scene.scene_number,
                script_section_id=scene.script_section_id,
                section_purpose=section_purpose_val,
                title=scene.title or f"Scene {scene.scene_number}",
                visual_asset=visual_ref,
                narration_asset=narration_ref,
                caption_srt_asset=caption_srt_ref,
                caption_vtt_asset=caption_vtt_ref,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                duration_seconds=round(end_seconds - start_seconds, 3),
                is_silent=is_silent,
                narration_text=narration_text or None,
            )
            assembly_scenes.append(assembly_scene)

        # --- 4. Full-video Composite Subtitle Tracks ---
        full_srt_ref: Optional[AssemblyAssetReference] = None
        full_vtt_ref: Optional[AssemblyAssetReference] = None
        has_srt_track = bool(getattr(captions, "full_srt_file_path", None) or getattr(captions, "full_video_srt_path", None) or (captions and caption_storage_manager.caption_file_exists(job_id, "full_video", format="srt")))
        if captions and has_srt_track:
            srt_path = caption_storage_manager.get_caption_path(job_id, "full_video", format="srt")
            srt_valid, srt_err, srt_size = self._validator.validate_caption_file(srt_path, format="srt")
            full_srt_ref = AssemblyAssetReference(
                asset_id="full_video",
                asset_type="full_video_srt",
                relative_path=caption_storage_manager.get_relative_caption_path(job_id, "full_video", format="srt"),
                file_format="srt",
                file_size_bytes=srt_size,
                duration_seconds=round(cumulative_time, 3),
                is_valid=srt_valid,
                validation_error=srt_err,
            )

        has_vtt_track = bool(getattr(captions, "full_vtt_file_path", None) or getattr(captions, "full_video_vtt_path", None) or (captions and caption_storage_manager.caption_file_exists(job_id, "full_video", format="vtt")))
        if captions and has_vtt_track:
            vtt_path = caption_storage_manager.get_caption_path(job_id, "full_video", format="vtt")
            vtt_valid, vtt_err, vtt_size = self._validator.validate_caption_file(vtt_path, format="vtt")
            full_vtt_ref = AssemblyAssetReference(
                asset_id="full_video",
                asset_type="full_video_vtt",
                relative_path=caption_storage_manager.get_relative_caption_path(job_id, "full_video", format="vtt"),
                file_format="vtt",
                file_size_bytes=vtt_size,
                duration_seconds=round(cumulative_time, 3),
                is_valid=vtt_valid,
                validation_error=vtt_err,
            )

        # --- 5. Preflight Readiness Evaluation ---
        readiness_report = self._validator.evaluate_package(
            job_id=job_id,
            scenes=assembly_scenes,
            full_video_srt=full_srt_ref,
            full_video_vtt=full_vtt_ref,
        )

        total_duration = assembly_scenes[-1].end_seconds if assembly_scenes else 0.0

        return VideoAssemblyInput(
            job_id=job_id,
            repo_name=repo_name,
            scenes=assembly_scenes,
            total_scenes=len(assembly_scenes),
            total_duration_seconds=round(total_duration, 3),
            full_video_srt=full_srt_ref,
            full_video_vtt=full_vtt_ref,
            readiness_report=readiness_report,
        )


assembly_input_service = AssemblyInputService()
