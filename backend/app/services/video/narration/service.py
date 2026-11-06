"""
Narration Generation Service (Milestone 5, Phase 5.4).

Orchestrates audio generation for every scene in an EducationalStoryboard using
ElevenLabs Text-to-Speech, measures audio duration, compares synchronization against
planned scene timings, and isolates audio asset files per job.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from app.services.ai.script_generation.schemas import EducationalScript
from app.services.ai.storyboard_generation.schemas import EducationalStoryboard, StoryboardScene
from .audio_storage import AudioAssetStorageManager, audio_storage_manager
from .elevenlabs_provider import ElevenLabsTTSProvider, elevenlabs_provider
from .schemas import (
    NarrationAsset,
    NarrationAssetStatus,
    NarrationGenerationResult,
    NarrationSyncSummary,
    SceneSyncReport,
)

logger = logging.getLogger(__name__)

# Synchronization thresholds for video assembly warnings
# Audio diverging by more than 3.0 seconds AND 25% of the scene duration triggers a sync notice
SYNC_ABSOLUTE_DIFF_THRESHOLD_SECONDS = 3.0
SYNC_RELATIVE_DIFF_THRESHOLD_RATIO = 0.25


class NarrationService:
    """Manages scene-by-scene narration planning, synthesis, duration analysis, and storage."""

    def __init__(
        self,
        provider: Optional[ElevenLabsTTSProvider] = None,
        storage: Optional[AudioAssetStorageManager] = None,
    ):
        self._provider = provider or elevenlabs_provider
        self._storage = storage or audio_storage_manager

    def initialize_narration_plan(
        self,
        job_id: str,
        storyboard: EducationalStoryboard,
        script: Optional[EducationalScript] = None,
        refresh: bool = False,
    ) -> NarrationGenerationResult:
        """
        Creates an initial narration asset blueprint from storyboard scenes.
        Extracts narration text from storyboard scene excerpts or matched script sections.
        Ensures multiple scenes never receive duplicate narration text.
        Scenes with empty narration text are explicitly classified as SKIPPED.
        """
        assets: List[NarrationAsset] = []

        # Build map of script sections for fast lookup
        script_sections: Dict[str, str] = {}
        if script and script.sections:
            for sec in script.sections:
                script_sections[sec.section_id] = sec.narration_text.strip() if sec.narration_text else ""

        # Step 1: Pre-resolve narration text for each scene to prevent identical full-section fallbacks
        scene_texts: List[str] = [""] * len(storyboard.scenes)
        section_to_unresolved_indices: Dict[str, List[int]] = {}

        for idx, scene in enumerate(storyboard.scenes):
            excerpt = ""
            if scene.narration and scene.narration.excerpt and scene.narration.excerpt.strip():
                excerpt = scene.narration.excerpt.strip()

            if excerpt:
                scene_texts[idx] = excerpt
            elif scene.script_section_id in script_sections:
                section_to_unresolved_indices.setdefault(scene.script_section_id, []).append(idx)

        # Step 2: Distribute script section text across scenes lacking individual excerpts
        for sec_id, scene_indices in section_to_unresolved_indices.items():
            full_section_text = script_sections.get(sec_id, "")
            if not full_section_text:
                continue

            if len(scene_indices) == 1:
                scene_texts[scene_indices[0]] = full_section_text
            else:
                # Multiple scenes share the section without excerpts: split into sentences!
                sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_section_text) if s.strip()]
                if not sentences:
                    sentences = [full_section_text]

                if len(sentences) >= len(scene_indices):
                    chunk_size = len(sentences) // len(scene_indices)
                    remainder = len(sentences) % len(scene_indices)
                    start = 0
                    for i, s_idx in enumerate(scene_indices):
                        extra = 1 if i < remainder else 0
                        end = start + chunk_size + extra
                        scene_texts[s_idx] = " ".join(sentences[start:end])
                        start = end
                else:
                    # Fewer sentences than scenes: assign sentences to earlier scenes;
                    # subsequent scenes remain visual continuations (skipped narration)
                    for i, s_idx in enumerate(scene_indices):
                        scene_texts[s_idx] = sentences[i] if i < len(sentences) else ""

        # Step 3: Global duplicate text elimination (never synthesize identical narration)
        seen_texts: Set[str] = set()
        duplicate_warnings: Dict[int, str] = {}
        for idx in range(len(scene_texts)):
            txt = scene_texts[idx]
            if txt:
                norm_txt = " ".join(txt.lower().split())
                if norm_txt in seen_texts:
                    duplicate_warnings[idx] = "Duplicate narration text detected from earlier scene; audio generation skipped."
                    scene_texts[idx] = ""
                else:
                    seen_texts.add(norm_txt)

        # Step 4: Construct NarrationAsset instances
        for idx, scene in enumerate(storyboard.scenes):
            narration_text = scene_texts[idx]

            # Derive unique asset ID
            clean_scene_id = scene.scene_id.replace("-", "_")
            asset_id = f"audio_{clean_scene_id}"

            # Classify status: empty text is SKIPPED
            is_empty = not bool(narration_text)
            status = NarrationAssetStatus.SKIPPED if is_empty else NarrationAssetStatus.PENDING

            if idx in duplicate_warnings:
                warning = duplicate_warnings[idx]
            elif is_empty:
                warning = "No narration text provided for scene; audio generation skipped."
            else:
                warning = None

            rel_path = self._storage.get_relative_audio_path(job_id, asset_id, format="mp3") if not is_empty else None

            asset = NarrationAsset(
                asset_id=asset_id,
                job_id=job_id,
                scene_id=scene.scene_id,
                scene_number=scene.scene_number,
                script_section_id=scene.script_section_id,
                status=status,
                file_path=rel_path,
                format="mp3",
                file_size_bytes=0,
                duration_seconds=0.0,
                expected_scene_duration_seconds=round(scene.estimated_duration_seconds, 2),
                duration_difference_seconds=0.0,
                is_synchronized=True,
                sync_warning=warning,
                voice_id=self._provider.voice_id,
                model_id=self._provider.model_id,
                narration_text=narration_text,
            )
            assets.append(asset)

        result = self._aggregate_result(
            job_id=job_id,
            assets=assets,
            voice_id=self._provider.voice_id,
            model_id=self._provider.model_id,
        )
        return result

    async def generate_narration_for_job(
        self,
        job_id: str,
        storyboard: EducationalStoryboard,
        script: Optional[EducationalScript] = None,
        refresh: bool = False,
    ) -> NarrationGenerationResult:
        """
        Executes narration audio synthesis for all scenes in the storyboard.
        Reuses already completed audio assets unless refresh=True is specified or narration text changed.
        Stores audio files, extracts measured durations, and computes synchronization metrics.
        """
        # Validate configuration upfront
        self._provider.validate_configuration()

        # Initialize base plan
        plan = self.initialize_narration_plan(
            job_id=job_id,
            storyboard=storyboard,
            script=script,
            refresh=refresh,
        )

        updated_assets: List[NarrationAsset] = []

        for asset in plan.assets:
            # 1. Skip scenes that have no narration text
            if asset.status == NarrationAssetStatus.SKIPPED or not asset.narration_text:
                updated_assets.append(asset)
                continue

            text_hash = hashlib.sha256(asset.narration_text.encode("utf-8")).hexdigest()[:16]

            # 2. Check if already completed and readable on disk (reuse unless refresh or text changed)
            if not refresh and self._storage.audio_file_exists(job_id, asset.asset_id, format=asset.format):
                cached_meta = self._storage.get_audio_metadata(job_id, asset.asset_id)
                meta_matches = (
                    cached_meta is not None
                    and cached_meta.get("text_hash") == text_hash
                    and cached_meta.get("voice_id") == asset.voice_id
                )
                # If metadata exists and matches (or no metadata yet recorded for legacy file with same name), check reuse
                if meta_matches or cached_meta is None:
                    file_path = self._storage.get_audio_path(job_id, asset.asset_id, format=asset.format)
                    file_size = file_path.stat().st_size
                    measured_duration = self._storage.measure_audio_duration(file_path)
                    sync_info = self._analyze_scene_sync(
                        expected_seconds=asset.expected_scene_duration_seconds,
                        actual_seconds=measured_duration,
                    )

                    asset.status = NarrationAssetStatus.COMPLETED
                    asset.file_size_bytes = file_size
                    asset.duration_seconds = measured_duration
                    asset.duration_difference_seconds = sync_info.difference_seconds
                    asset.is_synchronized = (sync_info.status == "synced")
                    asset.sync_warning = sync_info.warning
                    updated_assets.append(asset)
                    continue

            # 3. Synthesize audio with ElevenLabs
            asset.status = NarrationAssetStatus.GENERATING
            try:
                audio_bytes = await self._provider.synthesize(
                    text=asset.narration_text,
                    voice_id=asset.voice_id,
                    model_id=asset.model_id,
                )

                # 4. Save to isolated storage atomically with metadata
                target_path = self._storage.save_audio(
                    job_id=job_id,
                    asset_id=asset.asset_id,
                    audio_bytes=audio_bytes,
                    format=asset.format,
                )
                self._storage.save_audio_metadata(
                    job_id=job_id,
                    asset_id=asset.asset_id,
                    metadata={
                        "text_hash": text_hash,
                        "voice_id": asset.voice_id,
                        "model_id": asset.model_id,
                        "narration_text": asset.narration_text,
                    },
                )

                # 5. Measure actual duration
                file_size = len(audio_bytes)
                measured_duration = self._storage.measure_audio_duration(target_path)
                sync_info = self._analyze_scene_sync(
                    expected_seconds=asset.expected_scene_duration_seconds,
                    actual_seconds=measured_duration,
                )

                asset.status = NarrationAssetStatus.COMPLETED
                asset.file_size_bytes = file_size
                asset.duration_seconds = measured_duration
                asset.duration_difference_seconds = sync_info.difference_seconds
                asset.is_synchronized = (sync_info.status == "synced")
                asset.sync_warning = sync_info.warning
                asset.generation_timestamp = datetime.now(timezone.utc)
                asset.error_message = None

            except Exception as e:
                logger.error("Failed to generate narration audio for scene %s: %s", asset.scene_id, e)
                asset.status = NarrationAssetStatus.FAILED
                asset.error_message = str(e)
                asset.file_size_bytes = 0
                asset.duration_seconds = 0.0

            updated_assets.append(asset)

        final_result = self._aggregate_result(
            job_id=job_id,
            assets=updated_assets,
            voice_id=self._provider.voice_id,
            model_id=self._provider.model_id,
        )
        return final_result

    def _analyze_scene_sync(
        self,
        expected_seconds: float,
        actual_seconds: float,
    ) -> SceneSyncReport:
        """Analyzes duration divergence between planned scene timing and actual spoken audio."""
        diff = round(actual_seconds - expected_seconds, 2)
        ratio = round(actual_seconds / expected_seconds, 2) if expected_seconds > 0 else 1.0

        is_divergent = (
            abs(diff) > SYNC_ABSOLUTE_DIFF_THRESHOLD_SECONDS
            and abs(diff) / max(expected_seconds, 1.0) > SYNC_RELATIVE_DIFF_THRESHOLD_RATIO
        )

        if not is_divergent:
            status = "synced"
            warning = None
        elif diff > 0:
            status = "audio_longer"
            warning = (
                f"Narration audio ({actual_seconds:.1f}s) is longer than planned scene duration "
                f"({expected_seconds:.1f}s) by {diff:+.1f}s (+{int((ratio - 1) * 100)}%)."
            )
        else:
            status = "audio_shorter"
            warning = (
                f"Narration audio ({actual_seconds:.1f}s) is shorter than planned scene duration "
                f"({expected_seconds:.1f}s) by {diff:+.1f}s ({int((ratio - 1) * 100)}%)."
            )

        return SceneSyncReport(
            scene_id="",
            scene_number=0,
            expected_seconds=expected_seconds,
            actual_seconds=actual_seconds,
            difference_seconds=diff,
            ratio=ratio,
            status=status,
            warning=warning,
        )

    def _aggregate_result(
        self,
        job_id: str,
        assets: List[NarrationAsset],
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> NarrationGenerationResult:
        """Computes aggregate generation counts, synchronization summary, and overall status."""
        total = len(assets)
        completed = sum(1 for a in assets if a.status == NarrationAssetStatus.COMPLETED)
        failed = sum(1 for a in assets if a.status == NarrationAssetStatus.FAILED)
        skipped = sum(1 for a in assets if a.status == NarrationAssetStatus.SKIPPED)
        pending = sum(1 for a in assets if a.status == NarrationAssetStatus.PENDING)
        generating = sum(1 for a in assets if a.status == NarrationAssetStatus.GENERATING)

        # Build sync reports and summary
        scene_reports: List[SceneSyncReport] = []
        sync_warnings: List[str] = []
        total_expected = 0.0
        total_actual = 0.0
        scenes_synced = 0
        scenes_diverged = 0

        for a in assets:
            if a.status == NarrationAssetStatus.COMPLETED:
                total_expected += a.expected_scene_duration_seconds
                total_actual += a.duration_seconds
                report = self._analyze_scene_sync(
                    expected_seconds=a.expected_scene_duration_seconds,
                    actual_seconds=a.duration_seconds,
                )
                report.scene_id = a.scene_id
                report.scene_number = a.scene_number
                scene_reports.append(report)

                if report.status == "synced":
                    scenes_synced += 1
                else:
                    scenes_diverged += 1
                    if report.warning:
                        sync_warnings.append(f"Scene {a.scene_number}: {report.warning}")
            elif a.status == NarrationAssetStatus.SKIPPED:
                scene_reports.append(
                    SceneSyncReport(
                        scene_id=a.scene_id,
                        scene_number=a.scene_number,
                        expected_seconds=a.expected_scene_duration_seconds,
                        actual_seconds=0.0,
                        difference_seconds=-a.expected_scene_duration_seconds,
                        ratio=0.0,
                        status="skipped",
                        warning="Skipped (no narration)",
                    )
                )

        sync_summary = NarrationSyncSummary(
            total_expected_duration_seconds=round(total_expected, 2),
            total_actual_duration_seconds=round(total_actual, 2),
            total_difference_seconds=round(total_actual - total_expected, 2),
            scenes_synchronized=scenes_synced,
            scenes_with_divergence=scenes_diverged,
            scene_reports=scene_reports,
            synchronization_warnings=sync_warnings,
        )

        # Overall Status
        if total > 0 and (completed + skipped) == total and failed == 0:
            overall_status = NarrationAssetStatus.COMPLETED
        elif failed > 0:
            overall_status = NarrationAssetStatus.FAILED
        elif generating > 0:
            overall_status = NarrationAssetStatus.GENERATING
        else:
            overall_status = NarrationAssetStatus.PENDING

        return NarrationGenerationResult(
            job_id=job_id,
            status=overall_status,
            total_scenes=total,
            scenes_completed=completed,
            scenes_failed=failed,
            scenes_skipped=skipped,
            scenes_pending=pending,
            scenes_generating=generating,
            total_assets=total,
            assets_completed=completed,
            assets_failed=failed,
            assets_skipped=skipped,
            assets_pending=pending,
            assets_generating=generating,
            assets=assets,
            sync_summary=sync_summary,
            voice_id=voice_id,
            model_id=model_id,
            warnings=sync_warnings,
        )


# Default singleton instance
narration_service = NarrationService()
