"""
Service for Milestone 5, Phase 5.1: Visual Generation Foundation.

Responsible for:
- Initializing the scene-to-asset visual generation blueprint from an EducationalStoryboard
- Scene-by-scene asset mapping, role classification, and evidence preservation
- Safe storage directory initialization and relative path construction
- Maintaining the VisualAsset and SceneVisualAssets lifecycle (Pending -> Generating -> Completed / Failed)
- Ensuring stale assets are invalidated and deleted upon storyboard refresh
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from ...ai.project_understanding.schemas import EvidenceReference
from ...ai.script_generation.schemas import EducationalScript
from ...ai.storyboard_generation.schemas import EducationalStoryboard, StoryboardScene, VisualType
from ....models.schemas import RepositoryKnowledge
from .schemas import (
    MediaFormat,
    SceneVisualAssets,
    VideoOrientation,
    VisualAsset,
    VisualAssetStatus,
    VisualAssetType,
    VisualGenerationMetadata,
    VisualGenerationResult,
    VisualGenerationStatus,
)
from .storage import VisualAssetStorageManager, visual_storage_manager

logger = logging.getLogger(__name__)


def _map_visual_type_to_asset_type(visual_type: VisualType) -> VisualAssetType:
    """Maps a storyboard visual treatment to an asset category."""
    mapping = {
        VisualType.TITLE_CARD: VisualAssetType.TITLE_CARD,
        VisualType.ARCHITECTURE_DIAGRAM: VisualAssetType.ARCHITECTURE_DIAGRAM,
        VisualType.COMPONENT_DIAGRAM: VisualAssetType.COMPONENT_DIAGRAM,
        VisualType.WORKFLOW_DIAGRAM: VisualAssetType.WORKFLOW_DIAGRAM,
        VisualType.DATA_FLOW_VISUALIZATION: VisualAssetType.DATA_FLOW_DIAGRAM,
        VisualType.CODE_WALKTHROUGH: VisualAssetType.CODE_WALKTHROUGH,
        VisualType.SUMMARY_CARD: VisualAssetType.SUMMARY_CARD,
    }
    return mapping.get(visual_type, VisualAssetType.PRIMARY_VISUAL)


class VisualGenerationService:
    """Core service establishing the visual asset generation foundation for a job."""

    def __init__(self, storage_manager: Optional[VisualAssetStorageManager] = None):
        self.storage = storage_manager or visual_storage_manager

    def plan_visual_asset_for_scene(
        self,
        job_id: str,
        scene: StoryboardScene,
    ) -> VisualAsset:
        """
        Plans a strongly typed VisualAsset record for a single StoryboardScene.
        Initializes in PENDING status ready for downstream rendering in Phase 5.2.
        """
        asset_id = f"va_{job_id[:8]}_s{scene.scene_number:02d}_01"
        asset_type = _map_visual_type_to_asset_type(scene.visual_type)
        media_format = MediaFormat.SVG
        filename = f"{asset_id}.{media_format.value}"
        relative_path = self.storage.get_relative_asset_path(job_id, filename)

        # Extract transition name safely if Enum or string
        trans = getattr(scene.transition_to_next, "value", scene.transition_to_next)

        metadata = VisualGenerationMetadata(
            generator_name="VisualGenerationFoundation",
            renderer_version="1.0",
            diagram_syntax="pending",
            render_parameters={
                "scene_title": scene.title,
                "layout_hint": scene.layout_hint,
                "on_screen_text": list(scene.on_screen_text),
                "transition_to_next": trans,
            },
        )

        return VisualAsset(
            asset_id=asset_id,
            job_id=job_id,
            scene_id=scene.scene_id,
            scene_number=scene.scene_number,
            asset_type=asset_type,
            visual_type=scene.visual_type,
            storage_path=relative_path,
            media_format=media_format,
            width=1920,
            height=1080,
            aspect_ratio="16:9",
            status=VisualAssetStatus.PENDING,
            source_evidence=list(scene.evidence),
            related_files=list(scene.related_files),
            metadata=metadata,
        )

    def initialize_visual_assets(
        self,
        job_id: str,
        storyboard: EducationalStoryboard,
        script: Optional[EducationalScript] = None,
        knowledge: Optional[RepositoryKnowledge] = None,
        refresh: bool = False,
    ) -> VisualGenerationResult:
        """
        Establishes the visual asset generation foundation for an EducationalStoryboard.
        Creates isolated storage, plans scene visual assets, and initializes the lifecycle.
        Does not fabricate completed visuals or claim rendering has finished.
        """
        if not storyboard:
            raise ValueError("EducationalStoryboard is required to initialize visual assets.")
        if not storyboard.scenes:
            raise ValueError("Storyboard must contain at least one scene to initialize visual assets.")

        safe_job_id = self.storage.validate_job_id(job_id)

        # Invalidate and purge old disk assets if refresh requested
        if refresh:
            self.storage.delete_job_visuals(safe_job_id)

        # Ensure isolated storage directory exists
        self.storage.get_job_visuals_dir(safe_job_id, create=True)
        relative_dir = self.storage.get_relative_storage_dir(safe_job_id)

        scene_assets_list: List[SceneVisualAssets] = []
        total_assets = 0

        for scene in storyboard.scenes:
            primary_asset = self.plan_visual_asset_for_scene(safe_job_id, scene)
            total_assets += 1

            scene_assets = SceneVisualAssets(
                scene_id=scene.scene_id,
                scene_number=scene.scene_number,
                scene_title=scene.title,
                visual_type=scene.visual_type,
                visual_description=scene.visual_description,
                primary_asset=primary_asset,
                supplementary_assets=[],
                status=VisualGenerationStatus.PENDING,
            )
            scene_assets_list.append(scene_assets)

        now = datetime.now(timezone.utc)
        result = VisualGenerationResult(
            job_id=safe_job_id,
            storyboard_id=storyboard.storyboard_id,
            script_id=storyboard.script_id,
            status=VisualGenerationStatus.PENDING,
            video_orientation=VideoOrientation.LANDSCAPE,
            total_scenes=len(scene_assets_list),
            scenes_completed=0,
            scenes_failed=0,
            total_assets=total_assets,
            scene_assets=scene_assets_list,
            storage_directory=relative_dir,
            created_at=now,
            updated_at=now,
            validation_warnings=[],
        )

        logger.info(
            "Initialized visual asset foundation for job %s: %d scenes, %d assets planned",
            job_id,
            len(scene_assets_list),
            total_assets,
        )
        return result


# Singleton instance
visual_generation_service = VisualGenerationService()
