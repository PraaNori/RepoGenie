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
from typing import Any, Dict, List, Optional, Tuple

from ....models.schemas import StatusEnum
from ...ai.storyboard_generation.schemas import EducationalStoryboard, StoryboardScene
from ..visual_generation.storage import visual_storage_manager
from ..visual_generation.schemas import VisualGenerationResult, VisualAssetStatus
from ..narration.audio_storage import audio_storage_manager
from ..narration.schemas import NarrationAssetStatus, NarrationGenerationResult
from ..captions.caption_storage import caption_storage_manager
from ..captions.schemas import CaptionGenerationResult, CaptionStatus
from .schemas import (
    AssemblyAssetReference,
    AssemblyIssueSeverity,
    AssemblyReadinessReport,
    AssemblyScene,
    AssemblyValidationIssue,
    VideoAssemblyInput,
)
from .validator import AssemblyPreflightValidator, preflight_validator

logger = logging.getLogger(__name__)


class AssemblyInputService:
    """Service that compiles, validates, and revalidates the VideoAssemblyInput package."""

    def __init__(self, validator: Optional[AssemblyPreflightValidator] = None):
        self._validator = validator or preflight_validator

    def _match_asset_for_scene(
        self,
        scene: StoryboardScene,
        candidates: List[Any],
        asset_type_name: str,
    ) -> Tuple[Optional[Any], Optional[str]]:
        """
        Finds the unique matching asset candidate for a storyboard scene.

        Matching Rules:
        1. Primary matching key is the stable `scene_id`. An exact matching scene_id always takes precedence.
        2. If multiple candidates share the exact matching scene_id, reject as duplicate/ambiguous.
        3. `scene_number` fallback is used ONLY when the candidate genuinely lacks a scene_id
           AND the fallback is unambiguous (exactly one candidate matches).
        4. If both scene_ids exist but disagree, DO NOT silently match by scene_number.
        """
        if not candidates:
            return None, None

        # 1. Primary match: exact scene_id
        exact_matches = [
            c for c in candidates
            if getattr(c, "scene_id", None) == scene.scene_id
        ]
        if len(exact_matches) > 1:
            return None, f"Duplicate asset scene_id: multiple {asset_type_name} assets found for scene_id '{scene.scene_id}'."
        if len(exact_matches) == 1:
            return exact_matches[0], None

        # 2. Strict fallback: scene_number is ONLY checked for assets that genuinely lack a scene_id
        id_less_candidates = [
            c for c in candidates
            if not getattr(c, "scene_id", None)
        ]
        number_matches = [
            c for c in id_less_candidates
            if getattr(c, "scene_number", None) == scene.scene_number
        ]
        if len(number_matches) == 1:
            return number_matches[0], None
        elif len(number_matches) > 1:
            return None, f"Ambiguous fallback: multiple {asset_type_name} assets lacking scene_id match scene_number {scene.scene_number}."

        # If candidates have a scene_id that does not match scene.scene_id,
        # rule 4 explicitly forbids matching them by scene_number.
        return None, None

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

        additional_issues: List[AssemblyValidationIssue] = []

        # 1. Validate storyboard scenes for duplicate IDs and scene numbers
        seen_sb_ids = set()
        seen_sb_nums = set()
        for s in storyboard.scenes:
            if s.scene_id in seen_sb_ids:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="DUPLICATE_SCENE_ID",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Storyboard contains duplicate scene_id '{s.scene_id}'.",
                        scene_id=s.scene_id,
                        scene_number=s.scene_number,
                    )
                )
            seen_sb_ids.add(s.scene_id)

            if s.scene_number in seen_sb_nums:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="DUPLICATE_SCENE_NUMBER",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Storyboard contains duplicate scene_number {s.scene_number}.",
                        scene_id=s.scene_id,
                        scene_number=s.scene_number,
                    )
                )
            seen_sb_nums.add(s.scene_number)

        # 2. Extract asset candidate pools and enforce storyboard generation freshness
        visual_candidates: List[Any] = []
        if visual_generation:
            vg_sb_id = getattr(visual_generation, "storyboard_id", None)
            if vg_sb_id and storyboard.storyboard_id and vg_sb_id != storyboard.storyboard_id:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="STALE_STORYBOARD_ASSETS",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Visual assets belong to older storyboard '{vg_sb_id}', but active storyboard is '{storyboard.storyboard_id}'.",
                        asset_type="visual",
                    )
                )
            else:
                if getattr(visual_generation, "scene_assets", None):
                    for sva in visual_generation.scene_assets:
                        target = sva.primary_asset if sva.primary_asset else (sva.supplementary_assets[0] if sva.supplementary_assets else None)
                        if target:
                            # Propagate scene metadata if needed
                            visual_candidates.append(target)
                        else:
                            visual_candidates.append(sva)
                elif getattr(visual_generation, "assets", None):
                    visual_candidates.extend(visual_generation.assets)

        narration_candidates: List[Any] = []
        if narration and getattr(narration, "assets", None):
            narr_sb_id = getattr(narration, "storyboard_id", None) or getattr(narration, "metadata", {}).get("storyboard_id")
            if narr_sb_id and storyboard.storyboard_id and narr_sb_id != storyboard.storyboard_id:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="STALE_STORYBOARD_ASSETS",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Narration audio belongs to older storyboard '{narr_sb_id}', but active storyboard is '{storyboard.storyboard_id}'.",
                        asset_type="narration",
                    )
                )
            else:
                narration_candidates.extend(narration.assets)

        caption_candidates: List[Any] = []
        if captions and getattr(captions, "scene_assets", None):
            cap_sb_id = getattr(captions, "storyboard_id", None) or getattr(captions, "metadata", {}).get("storyboard_id")
            if cap_sb_id and storyboard.storyboard_id and cap_sb_id != storyboard.storyboard_id:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="STALE_STORYBOARD_ASSETS",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=f"Captions belong to older storyboard '{cap_sb_id}', but active storyboard is '{storyboard.storyboard_id}'.",
                        asset_type="caption",
                    )
                )
            else:
                caption_candidates.extend(captions.scene_assets)

        # 3. Enforce strict 1-indexed monotonic scene ordering
        ordered_scenes = sorted(storyboard.scenes, key=lambda s: s.scene_number)

        assembly_scenes: List[AssemblyScene] = []
        cumulative_time = 0.0

        for scene in ordered_scenes:
            # Match narration asset
            narr_asset, narr_match_err = self._match_asset_for_scene(scene, narration_candidates, "narration")
            if narr_match_err:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="AMBIGUOUS_ASSET_MATCH",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=narr_match_err,
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_type="narration",
                    )
                )

            # Determine narration text
            narration_text = ""
            if scene.narration:
                if hasattr(scene.narration, "excerpt") and scene.narration.excerpt:
                    narration_text = scene.narration.excerpt.strip()
                elif isinstance(scene.narration, str):
                    narration_text = scene.narration.strip()

            if not narration_text and narr_asset and getattr(narr_asset, "narration_text", None):
                narration_text = narr_asset.narration_text.strip()

            # Determine if scene is intentionally silent
            if narr_asset and narr_asset.status == NarrationAssetStatus.FAILED:
                is_silent = False  # Failed narration scenes must NEVER be treated as silent
            elif narr_asset and narr_asset.status == NarrationAssetStatus.SKIPPED and len(narration_text) == 0:
                is_silent = True
            elif len(narration_text) == 0 and narr_asset is None:
                is_silent = True
            else:
                is_silent = False

            # Determine scene duration based on narration or planned estimation
            if narr_asset and narr_asset.status == NarrationAssetStatus.COMPLETED and narr_asset.duration_seconds > 0:
                scene_duration = narr_asset.duration_seconds
            else:
                scene_duration = float(scene.estimated_duration_seconds or 5.0)

            start_seconds = round(cumulative_time, 3)
            end_seconds = round(start_seconds + scene_duration, 3)
            cumulative_time = end_seconds

            # --- 3a. Visual Asset Resolution ---
            visual_ref: Optional[AssemblyAssetReference] = None
            vis_asset, vis_match_err = self._match_asset_for_scene(scene, visual_candidates, "visual")
            if vis_match_err:
                additional_issues.append(
                    AssemblyValidationIssue(
                        code="AMBIGUOUS_ASSET_MATCH",
                        severity=AssemblyIssueSeverity.BLOCKING,
                        message=vis_match_err,
                        scene_id=scene.scene_id,
                        scene_number=scene.scene_number,
                        asset_type="visual",
                    )
                )
            if vis_asset:
                asset_id = getattr(vis_asset, "asset_id", f"vis_{scene.scene_id}")
                if getattr(vis_asset, "storage_path", None):
                    filename = Path(vis_asset.storage_path).name
                    file_format = filename.split(".")[-1].lower()
                    rel_path = vis_asset.storage_path
                    if self._validator._custom_base:
                        vis_path = self._validator.base_dir / rel_path
                    else:
                        vis_path = visual_storage_manager.get_job_visuals_dir(job_id) / filename
                else:
                    filename = f"{asset_id}.svg"
                    file_format = "svg"
                    rel_path = visual_storage_manager.get_relative_asset_path(job_id, filename)
                    if self._validator._custom_base:
                        vis_path = self._validator.base_dir / rel_path
                    else:
                        vis_path = visual_storage_manager.get_job_visuals_dir(job_id) / filename

                if getattr(vis_asset, "status", None) == VisualAssetStatus.FAILED:
                    valid = False
                    err = f"Visual asset for scene {scene.scene_number} failed: {getattr(vis_asset, 'error_message', 'Generation failed')}"
                    size = 0
                else:
                    valid, err, size = self._validator.validate_visual_file(vis_path)

                visual_ref = AssemblyAssetReference(
                    asset_id=asset_id,
                    scene_id=scene.scene_id,
                    asset_type="visual",
                    relative_path=rel_path,
                    file_format=file_format,
                    file_size_bytes=size,
                    duration_seconds=None,
                    is_valid=valid,
                    validation_error=err,
                )

            # --- 3b. Narration Audio Asset Resolution ---
            narration_ref: Optional[AssemblyAssetReference] = None
            if not is_silent:
                if narr_asset:
                    asset_id = narr_asset.asset_id
                    if self._validator._custom_base and narr_asset.file_path:
                        audio_path = self._validator.base_dir / narr_asset.file_path
                    else:
                        audio_path = audio_storage_manager.get_audio_path(job_id, asset_id, format="mp3")
                    if narr_asset.status == NarrationAssetStatus.FAILED:
                        valid = False
                        err = f"Narration audio for scene {scene.scene_number} failed: {narr_asset.error_message or 'Synthesis failed'}"
                        size = 0
                        measured_dur = 0.0
                    else:
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

            # --- 3c. Per-scene Caption Asset Resolution ---
            caption_srt_ref: Optional[AssemblyAssetReference] = None
            caption_vtt_ref: Optional[AssemblyAssetReference] = None
            if not is_silent:
                cap_asset, cap_match_err = self._match_asset_for_scene(scene, caption_candidates, "caption")
                if cap_match_err:
                    additional_issues.append(
                        AssemblyValidationIssue(
                            code="AMBIGUOUS_ASSET_MATCH",
                            severity=AssemblyIssueSeverity.BLOCKING,
                            message=cap_match_err,
                            scene_id=scene.scene_id,
                            scene_number=scene.scene_number,
                            asset_type="caption",
                        )
                    )
                if cap_asset:
                    cap_id = cap_asset.asset_id
                    if self._validator._custom_base and getattr(cap_asset, "srt_file_path", None):
                        srt_path = self._validator.base_dir / cap_asset.srt_file_path
                    else:
                        srt_path = caption_storage_manager.get_caption_path(job_id, cap_id, format="srt")

                    if self._validator._custom_base and getattr(cap_asset, "vtt_file_path", None):
                        vtt_path = self._validator.base_dir / cap_asset.vtt_file_path
                    else:
                        vtt_path = caption_storage_manager.get_caption_path(job_id, cap_id, format="vtt")

                    if getattr(cap_asset, "status", None) == CaptionStatus.FAILED:
                        srt_valid = False
                        srt_err = f"Captions for scene {scene.scene_number} failed: {getattr(cap_asset, 'error_message', None) or 'Generation failed'}"
                        srt_size = 0
                        vtt_valid = False
                        vtt_err = srt_err
                        vtt_size = 0
                    else:
                        srt_valid, srt_err, srt_size = self._validator.validate_caption_file(srt_path, format="srt")
                        vtt_valid, vtt_err, vtt_size = self._validator.validate_caption_file(vtt_path, format="vtt")

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

        rel_srt = (
            getattr(captions, "full_srt_file_path", None)
            or getattr(captions, "full_video_srt_path", None)
            or caption_storage_manager.get_relative_caption_path(job_id, "full_video", format="srt")
        )
        if self._validator._custom_base:
            srt_candidate_path = self._validator.base_dir / rel_srt
            if not srt_candidate_path.is_file():
                # Check "full.srt" fallback
                alt_rel = caption_storage_manager.get_relative_caption_path(job_id, "full", format="srt")
                if (self._validator.base_dir / alt_rel).is_file():
                    rel_srt = alt_rel
                    srt_candidate_path = self._validator.base_dir / alt_rel
            has_srt_track = bool(captions and srt_candidate_path.is_file())
            srt_path = srt_candidate_path
        else:
            has_srt_track = bool(
                getattr(captions, "full_srt_file_path", None)
                or getattr(captions, "full_video_srt_path", None)
                or (captions and caption_storage_manager.caption_file_exists(job_id, "full_video", format="srt"))
                or (captions and caption_storage_manager.caption_file_exists(job_id, "full", format="srt"))
            )
            if not caption_storage_manager.caption_file_exists(job_id, "full_video", format="srt") and caption_storage_manager.caption_file_exists(job_id, "full", format="srt"):
                rel_srt = caption_storage_manager.get_relative_caption_path(job_id, "full", format="srt")
            srt_path = caption_storage_manager.base_dir / rel_srt

        if captions and has_srt_track:
            srt_valid, srt_err, srt_size = self._validator.validate_caption_file(srt_path, format="srt")
            full_srt_ref = AssemblyAssetReference(
                asset_id="full_video",
                asset_type="full_video_srt",
                relative_path=rel_srt,
                file_format="srt",
                file_size_bytes=srt_size,
                duration_seconds=round(cumulative_time, 3),
                is_valid=srt_valid,
                validation_error=srt_err,
            )

        rel_vtt = (
            getattr(captions, "full_vtt_file_path", None)
            or getattr(captions, "full_video_vtt_path", None)
            or caption_storage_manager.get_relative_caption_path(job_id, "full_video", format="vtt")
        )
        if self._validator._custom_base:
            vtt_candidate_path = self._validator.base_dir / rel_vtt
            if not vtt_candidate_path.is_file():
                # Check "full.vtt" fallback
                alt_rel_vtt = caption_storage_manager.get_relative_caption_path(job_id, "full", format="vtt")
                if (self._validator.base_dir / alt_rel_vtt).is_file():
                    rel_vtt = alt_rel_vtt
                    vtt_candidate_path = self._validator.base_dir / alt_rel_vtt
            has_vtt_track = bool(captions and vtt_candidate_path.is_file())
            vtt_path = vtt_candidate_path
        else:
            has_vtt_track = bool(
                getattr(captions, "full_vtt_file_path", None)
                or getattr(captions, "full_video_vtt_path", None)
                or (captions and caption_storage_manager.caption_file_exists(job_id, "full_video", format="vtt"))
                or (captions and caption_storage_manager.caption_file_exists(job_id, "full", format="vtt"))
            )
            if not caption_storage_manager.caption_file_exists(job_id, "full_video", format="vtt") and caption_storage_manager.caption_file_exists(job_id, "full", format="vtt"):
                rel_vtt = caption_storage_manager.get_relative_caption_path(job_id, "full", format="vtt")
            vtt_path = caption_storage_manager.base_dir / rel_vtt

        if captions and has_vtt_track:
            vtt_valid, vtt_err, vtt_size = self._validator.validate_caption_file(vtt_path, format="vtt")
            full_vtt_ref = AssemblyAssetReference(
                asset_id="full_video",
                asset_type="full_video_vtt",
                relative_path=rel_vtt,
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
            additional_issues=additional_issues,
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

    def revalidate_assembly_input(
        self,
        assembly_input: VideoAssemblyInput,
    ) -> VideoAssemblyInput:
        """
        Re-verifies physical asset integrity on disk for an already compiled package.
        Detects deleted files, truncated files (0 bytes), corrupted assets, and updates
        readiness report accordingly.

        Does NOT invoke ElevenLabs, visual generation, caption generation, or FFmpeg.
        """
        base_dir = self._validator.base_dir

        for scene in assembly_input.scenes:
            # 1. Re-validate visual asset
            if scene.visual_asset:
                vis_path = base_dir / scene.visual_asset.relative_path
                valid, err, size = self._validator.validate_visual_file(vis_path)
                scene.visual_asset.is_valid = valid
                scene.visual_asset.validation_error = err
                scene.visual_asset.file_size_bytes = size

            # 2. Re-validate narration asset
            if not scene.is_silent and scene.narration_asset:
                aud_path = base_dir / scene.narration_asset.relative_path
                valid, err, size, dur = self._validator.validate_audio_file(aud_path)
                scene.narration_asset.is_valid = valid
                scene.narration_asset.validation_error = err
                scene.narration_asset.file_size_bytes = size
                if valid:
                    scene.narration_asset.duration_seconds = dur

            # 3. Re-validate scene captions
            if not scene.is_silent:
                if scene.caption_srt_asset:
                    srt_path = base_dir / scene.caption_srt_asset.relative_path
                    valid, err, size = self._validator.validate_caption_file(srt_path, format="srt")
                    scene.caption_srt_asset.is_valid = valid
                    scene.caption_srt_asset.validation_error = err
                    scene.caption_srt_asset.file_size_bytes = size

                if scene.caption_vtt_asset:
                    vtt_path = base_dir / scene.caption_vtt_asset.relative_path
                    valid, err, size = self._validator.validate_caption_file(vtt_path, format="vtt")
                    scene.caption_vtt_asset.is_valid = valid
                    scene.caption_vtt_asset.validation_error = err
                    scene.caption_vtt_asset.file_size_bytes = size

        # 4. Re-validate full-video captions
        if assembly_input.full_video_srt:
            full_srt_path = base_dir / assembly_input.full_video_srt.relative_path
            valid, err, size = self._validator.validate_caption_file(full_srt_path, format="srt")
            assembly_input.full_video_srt.is_valid = valid
            assembly_input.full_video_srt.validation_error = err
            assembly_input.full_video_srt.file_size_bytes = size

        if assembly_input.full_video_vtt:
            full_vtt_path = base_dir / assembly_input.full_video_vtt.relative_path
            valid, err, size = self._validator.validate_caption_file(full_vtt_path, format="vtt")
            assembly_input.full_video_vtt.is_valid = valid
            assembly_input.full_video_vtt.validation_error = err
            assembly_input.full_video_vtt.file_size_bytes = size

        # 5. Re-evaluate readiness report
        fresh_report = self._validator.evaluate_package(
            job_id=assembly_input.job_id,
            scenes=assembly_input.scenes,
            full_video_srt=assembly_input.full_video_srt,
            full_video_vtt=assembly_input.full_video_vtt,
        )
        assembly_input.readiness_report = fresh_report
        return assembly_input


assembly_input_service = AssemblyInputService()
