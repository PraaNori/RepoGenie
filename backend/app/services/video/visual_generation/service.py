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

from ...ai.code_understanding.schemas import RepositoryCodeUnderstanding
from ...ai.project_understanding.schemas import EvidenceReference, ProjectUnderstanding
from ...ai.script_generation.schemas import EducationalScript
from ...ai.storyboard_generation.schemas import EducationalStoryboard, StoryboardScene, VisualType
from ...ai.workflow_understanding.schemas import RepositoryWorkflowUnderstanding
from ....models.schemas import ParsedRepository, RepositoryKnowledge
from .code_visuals import code_walkthrough_generator
from .scene_cards import summary_card_generator, title_card_generator
from .diagrams import (
    ArchitectureDiagramGenerator,
    ComponentDiagramGenerator,
    DataFlowDiagramGenerator,
    DiagramType,
    WorkflowDiagramGenerator,
    sanitize_text,
)
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


TECHNICAL_DIAGRAM_TYPES = {
    VisualType.ARCHITECTURE_DIAGRAM,
    VisualType.COMPONENT_DIAGRAM,
    VisualType.WORKFLOW_DIAGRAM,
    VisualType.DATA_FLOW_VISUALIZATION,
}

SCENE_VISUAL_TYPES = {
    VisualType.CODE_WALKTHROUGH,
    VisualType.TITLE_CARD,
    VisualType.SUMMARY_CARD,
}


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
        VisualType.TECHNOLOGY_OVERVIEW: VisualAssetType.TITLE_CARD,
        VisualType.OTHER: VisualAssetType.PRIMARY_VISUAL,
    }
    return mapping.get(visual_type, VisualAssetType.PRIMARY_VISUAL)


class VisualGenerationService:
    """Core service establishing the visual asset generation foundation and diagram rendering for a job."""

    def __init__(self, storage_manager: Optional[VisualAssetStorageManager] = None):
        self.storage = storage_manager or visual_storage_manager
        self.diagram_generators = {
            VisualType.ARCHITECTURE_DIAGRAM: ArchitectureDiagramGenerator(),
            VisualType.COMPONENT_DIAGRAM: ComponentDiagramGenerator(),
            VisualType.WORKFLOW_DIAGRAM: WorkflowDiagramGenerator(),
            VisualType.DATA_FLOW_VISUALIZATION: DataFlowDiagramGenerator(),
        }
        self.scene_visual_generators = {
            VisualType.CODE_WALKTHROUGH: code_walkthrough_generator,
            VisualType.TITLE_CARD: title_card_generator,
            VisualType.SUMMARY_CARD: summary_card_generator,
            VisualType.TECHNOLOGY_OVERVIEW: title_card_generator,
        }
        self.all_generators = {
            **self.diagram_generators,
            **self.scene_visual_generators,
        }

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
                status=VisualGenerationStatus.PLANNED,
            )
            scene_assets_list.append(scene_assets)

        now = datetime.now(timezone.utc)
        result = VisualGenerationResult(
            job_id=safe_job_id,
            storyboard_id=storyboard.storyboard_id,
            script_id=storyboard.script_id,
            status=VisualGenerationStatus.PLANNED,
            video_orientation=VideoOrientation.LANDSCAPE,
            total_scenes=len(scene_assets_list),
            scenes_completed=0,
            scenes_failed=0,
            total_assets=total_assets,
            assets_pending=total_assets,
            assets_generating=0,
            assets_completed=0,
            assets_failed=0,
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

    def generate_diagram_for_scene(
        self,
        job_id: str,
        scene: StoryboardScene,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        project_understanding: Optional[ProjectUnderstanding] = None,
        script: Optional[EducationalScript] = None,
        parsed_repository: Optional[ParsedRepository] = None,
        repo_root_dir: Optional[str] = None,
        target_asset: Optional[VisualAsset] = None,
    ) -> VisualAsset:
        """
        Renders a production-quality technical diagram, code walkthrough, or scene card SVG
        for a single StoryboardScene.
        Saves the SVG to disk and updates the VisualAsset to COMPLETED status.
        """
        generator = self.diagram_generators.get(scene.visual_type) or self.scene_visual_generators.get(scene.visual_type)
        if not generator:
            raise ValueError(
                f"Visual type '{scene.visual_type.value}' is not a supported visual generator type."
            )

        asset = target_asset or self.plan_visual_asset_for_scene(job_id, scene)
        safe_job_id = self.storage.validate_job_id(job_id)
        filename = f"{asset.asset_id}.svg"

        logger.info(
            "Rendering visual asset (%s) for job %s scene %d...",
            getattr(generator, "diagram_type", scene.visual_type),
            job_id,
            scene.scene_number,
        )

        diag_result = generator.generate(
            scene=scene,
            knowledge=knowledge,
            code_understanding=code_understanding,
            workflow_understanding=workflow_understanding,
            project_understanding=project_understanding,
            script=script,
            parsed_repository=parsed_repository,
            repo_root_dir=repo_root_dir,
        )

        # Validate rendered SVG content is valid
        if not diag_result.svg_content or not diag_result.svg_content.strip():
            raise ValueError(f"Generated SVG content for scene {scene.scene_number} is empty.")
        if "<svg" not in diag_result.svg_content or "</svg>" not in diag_result.svg_content:
            raise ValueError(f"Generated SVG content for scene {scene.scene_number} is malformed XML.")

        # Save rendered SVG file to isolated storage
        saved_path = self.storage.save_asset_content(safe_job_id, filename, diag_result.svg_content)
        relative_path = self.storage.get_relative_asset_path(safe_job_id, filename)

        # Merge evidence
        all_evidence = list(scene.evidence)
        if diag_result.evidence_used:
            existing_fps = {e.file_path for e in all_evidence if e.file_path}
            for ev in diag_result.evidence_used:
                if ev.file_path and ev.file_path not in existing_fps:
                    all_evidence.append(ev)
                    existing_fps.add(ev.file_path)

        # Update metadata
        metadata = VisualGenerationMetadata(
            generator_name=generator.__class__.__name__,
            renderer_version="2.0",
            generation_duration_ms=diag_result.render_duration_ms,
            diagram_syntax="graphviz+mermaid",
            render_parameters={
                "diagram_type": diag_result.diagram_type.value,
                "mermaid_source": diag_result.mermaid_source,
                "dot_source": diag_result.dot_source,
                "components_referenced": diag_result.components_referenced,
                "files_referenced": diag_result.files_referenced,
                "warnings": diag_result.validation_warnings,
            },
        )

        now = datetime.now(timezone.utc)
        updated_asset = asset.model_copy(
            update={
                "status": VisualAssetStatus.COMPLETED,
                "media_format": MediaFormat.SVG,
                "storage_path": relative_path,
                "width": diag_result.width,
                "height": diag_result.height,
                "aspect_ratio": diag_result.aspect_ratio,
                "source_evidence": all_evidence,
                "related_files": diag_result.files_referenced or asset.related_files,
                "validation_warnings": diag_result.validation_warnings,
                "metadata": metadata,
                "updated_at": now,
                "error_message": None,
            }
        )

        logger.info(
            "Successfully generated diagram asset %s for scene %d (%d bytes, %.1f ms)",
            asset.asset_id,
            scene.scene_number,
            len(diag_result.svg_content),
            diag_result.render_duration_ms,
        )
        return updated_asset

    def generate_diagrams_for_job(
        self,
        job_id: str,
        plan: VisualGenerationResult,
        storyboard: EducationalStoryboard,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        project_understanding: Optional[ProjectUnderstanding] = None,
        script: Optional[EducationalScript] = None,
        parsed_repository: Optional[ParsedRepository] = None,
        repo_root_dir: Optional[str] = None,
        include_scene_visuals: bool = False,
    ) -> VisualGenerationResult:
        """
        Iterates over all planned scenes in the VisualGenerationResult and generates SVGs.
        If include_scene_visuals is False (default), renders technical diagrams.
        If include_scene_visuals is True, renders both technical diagrams and scene visuals.
        Updates SceneVisualAssets, asset counts, and returns the updated VisualGenerationResult.
        """
        safe_job_id = self.storage.validate_job_id(job_id)
        scene_by_id = {s.scene_id: s for s in storyboard.scenes}
        active_generators = self.all_generators if include_scene_visuals else self.diagram_generators

        updated_scene_assets: List[SceneVisualAssets] = []
        completed_assets = 0
        failed_assets = 0
        completed_scenes = 0
        failed_scenes = 0

        for sa in plan.scene_assets:
            scene = scene_by_id.get(sa.scene_id)
            if not scene:
                updated_scene_assets.append(sa)
                continue

            if scene.visual_type in active_generators:
                try:
                    rendered_asset = self.generate_diagram_for_scene(
                        job_id=safe_job_id,
                        scene=scene,
                        knowledge=knowledge,
                        code_understanding=code_understanding,
                        workflow_understanding=workflow_understanding,
                        project_understanding=project_understanding,
                        script=script,
                        parsed_repository=parsed_repository,
                        repo_root_dir=repo_root_dir,
                        target_asset=sa.primary_asset,
                    )
                    completed_assets += 1
                    completed_scenes += 1

                    updated_sa = sa.model_copy(
                        update={
                            "primary_asset": rendered_asset,
                            "status": VisualGenerationStatus.COMPLETED,
                            "error_message": None,
                        }
                    )
                    updated_scene_assets.append(updated_sa)
                except Exception as exc:
                    logger.exception(
                        "Failed to generate diagram for job %s scene %d: %s",
                        job_id,
                        scene.scene_number,
                        exc,
                    )
                    sanitized_err = sanitize_text(str(exc), max_length=200)
                    failed_assets += 1
                    failed_scenes += 1
                    failed_primary = (
                        sa.primary_asset.model_copy(
                            update={
                                "status": VisualAssetStatus.FAILED,
                                "error_message": sanitized_err,
                            }
                        )
                        if sa.primary_asset
                        else None
                    )
                    updated_sa = sa.model_copy(
                        update={
                            "primary_asset": failed_primary,
                            "status": VisualGenerationStatus.FAILED,
                            "error_message": sanitized_err,
                        }
                    )
                    updated_scene_assets.append(updated_sa)
            else:
                # Non-diagram scenes (title cards, summary cards, code walkthroughs)
                # preserve existing status (e.g. PLANNED / PENDING)
                if sa.primary_asset and sa.primary_asset.status == VisualAssetStatus.COMPLETED:
                    completed_assets += 1
                    completed_scenes += 1
                updated_scene_assets.append(sa)

        total_assets = plan.total_assets
        pending_assets = max(0, total_assets - completed_assets - failed_assets)

        now = datetime.now(timezone.utc)
        overall_status = VisualGenerationStatus.GENERATING
        if completed_scenes == plan.total_scenes and plan.total_scenes > 0 and failed_scenes == 0:
            overall_status = VisualGenerationStatus.COMPLETED
        elif failed_scenes > 0 and completed_scenes == 0:
            overall_status = VisualGenerationStatus.FAILED

        updated_plan = plan.model_copy(
            update={
                "scene_assets": updated_scene_assets,
                "scenes_completed": completed_scenes,
                "scenes_failed": failed_scenes,
                "assets_completed": completed_assets,
                "assets_pending": pending_assets,
                "assets_failed": failed_assets,
                "status": overall_status,
                "updated_at": now,
            }
        )

        logger.info(
            "Completed diagram generation pass for job %s: %d/%d scenes completed, %d assets rendered",
            job_id,
            completed_scenes,
            plan.total_scenes,
            completed_assets,
        )
        return updated_plan

    def generate_all_visuals_for_job(
        self,
        job_id: str,
        plan: VisualGenerationResult,
        storyboard: EducationalStoryboard,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        project_understanding: Optional[ProjectUnderstanding] = None,
        script: Optional[EducationalScript] = None,
        parsed_repository: Optional[ParsedRepository] = None,
        repo_root_dir: Optional[str] = None,
    ) -> VisualGenerationResult:
        """Generates all supported visual assets (diagrams, code walkthroughs, scene cards) for a job."""
        return self.generate_diagrams_for_job(
            job_id=job_id,
            plan=plan,
            storyboard=storyboard,
            knowledge=knowledge,
            code_understanding=code_understanding,
            workflow_understanding=workflow_understanding,
            project_understanding=project_understanding,
            script=script,
            parsed_repository=parsed_repository,
            repo_root_dir=repo_root_dir,
            include_scene_visuals=True,
        )


# Singleton instance
visual_generation_service = VisualGenerationService()
