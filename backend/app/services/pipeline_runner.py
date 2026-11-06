"""
Pipeline Runner Service (Milestone 7).

Orchestrates sequential, resilient execution of the complete 9-stage
GitHub-to-educational-video generation pipeline:
  Stage 01: Repository Fetching & Ingestion
  Stage 02: Repository Structure & Dependency Analysis
  Stage 03: Code AST Parsing & Knowledge Representation
  Stage 04: AI Understanding (Project, Code, Workflow)
  Stage 05: Educational Narration Script Generation
  Stage 06: Educational Storyboard Generation
  Stage 07: Visual Asset Generation & Diagrams
  Stage 08: Voice Narration & Caption Generation
  Stage 09: Video Assembly (Preflight, Scene Rendering, Final Concatenation)

Ensures idempotent, resumable execution, granular stage retry without
invalidating upstream completed stages, and secure error sanitization.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.config import settings
from ..models.schemas import StageEnum, StatusEnum
from .ai.code_understanding import code_understanding_analyzer
from .ai.exceptions import AIError
from .ai.project_understanding import project_understanding_analyzer
from .ai.script_generation import educational_script_analyzer
from .ai.storyboard_generation import educational_storyboard_analyzer
from .ai.workflow_understanding import workflow_understanding_analyzer
from .repo.analyzer import repo_analyzer_service
from .repo.architecture_analyzer import architecture_analyzer_service
from .repo.code_parser import code_parser_service
from .repo.ingest import repo_ingestion_service
from .repo.knowledge_builder import knowledge_builder_service
from .storage.job_store import JobInternal, job_store
from .video.assembly.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FinalVideoAssemblyError,
    SceneRenderError,
)
from .video.assembly.final_service import final_video_assembly_service
from .video.assembly.scene_service import scene_render_service
from .video.assembly_input import assembly_input_service
from .video.captions import caption_service
from .video.narration import narration_service
from .video.visual_generation import visual_generation_service

logger = logging.getLogger(__name__)


def _sanitize_error(msg: str, local_path: Optional[str] = None) -> str:
    """Removes API keys and local system directory paths from error messages."""
    if not msg:
        return ""
    if local_path and local_path in msg:
        msg = msg.replace(local_path, "<REPO_ROOT>")
    if getattr(settings, "GROQ_API_KEY", None) and settings.GROQ_API_KEY in msg:
        msg = msg.replace(settings.GROQ_API_KEY, "[REDACTED]")
    if getattr(settings, "GEMINI_API_KEY", None) and settings.GEMINI_API_KEY in msg:
        msg = msg.replace(settings.GEMINI_API_KEY, "[REDACTED]")
    if getattr(settings, "ELEVENLABS_API_KEY", None) and settings.ELEVENLABS_API_KEY in msg:
        msg = msg.replace(settings.ELEVENLABS_API_KEY, "[REDACTED]")
    return msg


class PipelineRunnerService:
    """
    Coordinates end-to-end execution of all 9 pipeline stages for a RepoGenie job.
    Supports resuming from any stage and retrying specific failed stages.
    """

    async def run_pipeline(
        self,
        job_id: str,
        from_stage: Optional[int] = None,
        refresh: bool = False,
    ) -> JobInternal:
        """
        Executes or resumes the entire generation pipeline for `job_id`.
        Advances through pending stages sequentially until completion or failure.
        """
        job = job_store.get_internal_job(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")

        job_lock = await job_store.get_job_lock(job_id)
        async with job_lock:
            # Re-fetch latest job state inside lock
            job = job_store.get_internal_job(job_id)
            if not job:
                raise ValueError(f"Job '{job_id}' not found")

            # If already completed and not forced refresh, return immediately
            if job.status == StatusEnum.COMPLETED and not refresh:
                return job

            # Mark job overall status in_progress
            job.status = StatusEnum.IN_PROGRESS

            def should_run(stage_num: int, is_complete: bool) -> bool:
                if from_stage is not None:
                    if stage_num < from_stage:
                        return False
                    if stage_num == from_stage:
                        return True
                return (not is_complete) or refresh

            try:
                # -------------------------------------------------------------
                # Stage 01: Repository Ingestion
                # -------------------------------------------------------------
                if should_run(1, job.stages[0].status == StatusEnum.COMPLETED and bool(job.local_path)):
                    logger.info("Pipeline [%s]: Running Stage 01 (Ingestion)", job_id)
                    job_store.update_job_ingestion_started(job_id)
                    ingest_result = repo_ingestion_service.ingest_repository(job_id, job.clone_url)
                    job = job_store.update_job_ingestion_success(
                        job_id=job_id,
                        local_path=ingest_result.local_path,
                        file_count=ingest_result.file_count,
                        size_mb=ingest_result.size_mb,
                    )

                # -------------------------------------------------------------
                # Stage 02: Repository Analysis
                # -------------------------------------------------------------
                if should_run(2, job.stages[1].status == StatusEnum.COMPLETED):
                    logger.info("Pipeline [%s]: Running Stage 02 (Analysis)", job_id)
                    job_store.update_job_analysis_started(job_id)
                    analysis = repo_analyzer_service.analyze_repository(
                        job_id=job_id,
                        repo_name=job.repo_name,
                        local_path=job.local_path,
                    )
                    job = job_store.update_job_analysis_success(job_id, analysis)

                # -------------------------------------------------------------
                # Stage 03: Code Parsing, Architecture & Knowledge Consolidation
                # -------------------------------------------------------------
                if should_run(3, job.stages[2].status == StatusEnum.COMPLETED and bool(job.knowledge)):
                    logger.info("Pipeline [%s]: Running Stage 03 (Knowledge)", job_id)
                    job_store.update_job_code_parsing_started(job_id)
                    code_analysis = code_parser_service.parse_repository(
                        job_id=job_id,
                        repo_name=job.repo_name,
                        local_path=job.local_path,
                        analysis=job.analysis,
                    )
                    architecture = architecture_analyzer_service.analyze_architecture(
                        job_id=job_id,
                        repo_name=job.repo_name,
                        parsed_repo=code_analysis,
                        analysis=job.analysis,
                        local_path=job.local_path,
                    )
                    knowledge = knowledge_builder_service.build_knowledge(
                        job_id=job_id,
                        repo_name=job.repo_name,
                        repo_owner=job.repository_owner,
                        repo_url=job.repo_url,
                        local_path=job.local_path,
                        size_mb=job.analysis.statistics.total_size_mb if job.analysis else 0.0,
                        file_count=job.analysis.statistics.total_files if job.analysis else 0,
                        analysis=job.analysis,
                        parsed_repo=code_analysis,
                        architecture=architecture,
                    )
                    job = job_store.update_job_knowledge_success(
                        job_id=job_id,
                        code_analysis=code_analysis,
                        architecture=architecture,
                        knowledge=knowledge,
                    )

                # -------------------------------------------------------------
                # Stage 04: AI Understanding (Project, Code, Workflow)
                # -------------------------------------------------------------
                stage4_complete = (
                    job.stages[3].status == StatusEnum.COMPLETED
                    and bool(job.project_understanding)
                    and bool(job.code_understanding)
                    and bool(job.workflow_understanding)
                )
                if should_run(4, stage4_complete):
                    logger.info("Pipeline [%s]: Running Stage 04 (AI Understanding)", job_id)
                    job_store.update_job_ai_summary_started(job_id)

                    if not job.project_understanding or refresh or from_stage == 4:
                        proj_under = await project_understanding_analyzer.analyze_project(
                            job_id=job_id,
                            knowledge=job.knowledge,
                            local_path=job.local_path,
                        )
                        job = job_store.update_job_ai_summary_success(job_id, proj_under)

                    if not job.code_understanding or refresh or from_stage == 4:
                        code_under = await code_understanding_analyzer.analyze_codebase(
                            job_id=job_id,
                            knowledge=job.knowledge,
                            project_understanding=job.project_understanding,
                            local_path=job.local_path,
                        )
                        job = job_store.update_job_code_understanding_success(job_id, code_under)

                    if not job.workflow_understanding or refresh or from_stage == 4:
                        wf_under = await workflow_understanding_analyzer.analyze_workflows(
                            job_id=job_id,
                            knowledge=job.knowledge,
                            project_understanding=job.project_understanding,
                            code_understanding=job.code_understanding,
                            local_path=job.local_path,
                        )
                        job = job_store.update_job_workflow_understanding_success(job_id, wf_under)

                # -------------------------------------------------------------
                # Stage 05: Educational Script Generation
                # -------------------------------------------------------------
                stage5_complete = (
                    job.stages[4].status == StatusEnum.COMPLETED
                    and bool(job.educational_script)
                )
                if should_run(5, stage5_complete):
                    logger.info("Pipeline [%s]: Running Stage 05 (Script)", job_id)
                    job_store.update_job_educational_script_started(job_id)
                    script = await educational_script_analyzer.generate_script(
                        job_id=job_id,
                        knowledge=job.knowledge,
                        project_understanding=job.project_understanding,
                        code_understanding=job.code_understanding,
                        workflow_understanding=job.workflow_understanding,
                        local_path=job.local_path,
                        revise_on_duration_out_of_range=True,
                    )
                    job = job_store.update_job_educational_script_success(job_id, script)

                # -------------------------------------------------------------
                # Stage 06: Educational Storyboard Generation
                # -------------------------------------------------------------
                stage6_complete = (
                    job.stages[5].status == StatusEnum.COMPLETED
                    and bool(job.educational_storyboard)
                )
                if should_run(6, stage6_complete):
                    logger.info("Pipeline [%s]: Running Stage 06 (Storyboard)", job_id)
                    job_store.update_job_educational_storyboard_started(job_id)
                    storyboard = await educational_storyboard_analyzer.generate_storyboard(
                        job_id=job_id,
                        script=job.educational_script,
                        knowledge=job.knowledge,
                        project_understanding=job.project_understanding,
                        code_understanding=job.code_understanding,
                        workflow_understanding=job.workflow_understanding,
                        local_path=job.local_path,
                    )
                    job = job_store.update_job_educational_storyboard_success(job_id, storyboard)

                # -------------------------------------------------------------
                # Stage 07: Visual Asset Generation & Diagrams
                # -------------------------------------------------------------
                stage7_complete = (
                    job.stages[6].status == StatusEnum.COMPLETED
                    and bool(job.visual_generation)
                    and job.visual_generation.is_fully_rendered
                )
                if should_run(7, stage7_complete):
                    logger.info("Pipeline [%s]: Running Stage 07 (Visuals)", job_id)
                    job_store.update_job_visual_planning_started(job_id)
                    plan = visual_generation_service.initialize_visual_assets(
                        job_id=job_id,
                        storyboard=job.educational_storyboard,
                        script=job.educational_script,
                        knowledge=job.knowledge,
                        refresh=refresh or (from_stage == 7),
                    )
                    visuals_result = visual_generation_service.generate_diagrams_for_job(
                        job_id=job_id,
                        plan=plan,
                        storyboard=job.educational_storyboard,
                        knowledge=job.knowledge,
                        code_understanding=job.code_understanding,
                        workflow_understanding=job.workflow_understanding,
                        project_understanding=job.project_understanding,
                        script=job.educational_script,
                        parsed_repository=job.code_analysis,
                        repo_root_dir=job.local_path,
                        include_scene_visuals=True,
                    )
                    if visuals_result.is_fully_rendered:
                        job = job_store.update_job_visual_generation_success(job_id, visuals_result)
                    else:
                        job = job_store.update_job_visual_planning_success(job_id, visuals_result)

                # -------------------------------------------------------------
                # Stage 08: Narration Audio & Caption Generation
                # -------------------------------------------------------------
                stage8_complete = (
                    job.stages[7].status == StatusEnum.COMPLETED
                    and bool(job.narration)
                    and bool(job.captions)
                )
                if should_run(8, stage8_complete):
                    logger.info("Pipeline [%s]: Running Stage 08 (Narration & Captions)", job_id)
                    if not job.narration or refresh or from_stage == 8:
                        job_store.update_job_narration_started(job_id)
                        narration_result = await narration_service.generate_narration_for_job(
                            job_id=job_id,
                            storyboard=job.educational_storyboard,
                            script=job.educational_script,
                            refresh=refresh or (from_stage == 8),
                        )
                        job = job_store.update_job_narration_success(job_id, narration_result)

                    if not job.captions or refresh or from_stage == 8:
                        job_store.update_job_captions_started(job_id)
                        captions_result = caption_service.generate_captions_for_job(
                            job_id=job_id,
                            storyboard=job.educational_storyboard,
                            narration=job.narration,
                            script=job.educational_script,
                            refresh=refresh or (from_stage == 8),
                        )
                        job = job_store.update_job_captions_success(job_id, captions_result)

                # -------------------------------------------------------------
                # Stage 09: Video Assembly (Preflight, Scenes, Final Video)
                # -------------------------------------------------------------
                stage9_complete = (
                    job.stages[8].status == StatusEnum.COMPLETED
                    and bool(job.result)
                    and bool(job.render_job)
                    and job.render_job.status.value == "completed"
                )
                if should_run(9, stage9_complete):
                    logger.info("Pipeline [%s]: Running Stage 09 (Assembly Preflight, Scenes & Final MP4)", job_id)
                    assembly_input = assembly_input_service.build_assembly_input(
                        job_id=job_id,
                        repo_name=job.repo_name,
                        storyboard=job.educational_storyboard,
                        visual_generation=job.visual_generation,
                        narration=job.narration,
                        captions=job.captions,
                    )
                    job = job_store.update_job_assembly_input_success(job_id, assembly_input)

                    # Render individual scene clips
                    scene_result = scene_render_service.render_scenes(job_id=job_id, refresh=refresh or (from_stage == 9))
                    if scene_result:
                        job_store.update_job_scene_renders_completed(job_id, scene_result)

                    # Assemble final video
                    final_result = final_video_assembly_service.assemble_video(job_id=job_id, refresh=refresh or (from_stage == 9))
                    if final_result:
                        job = job_store.update_job_render_success(job_id, final_result)
                    else:
                        job = job_store.get_internal_job(job_id)

                logger.info("Pipeline [%s]: Successfully completed all 9 stages!", job_id)
                return job

            except Exception as exc:
                sanitized_msg = _sanitize_error(str(exc), getattr(job, "local_path", None))
                logger.error("Pipeline [%s] failed: %s", job_id, sanitized_msg, exc_info=True)
                job.status = StatusEnum.FAILED
                job.error = sanitized_msg

                # Find the currently active or in_progress stage and mark it failed
                for stg in job.stages:
                    if stg.status == StatusEnum.IN_PROGRESS:
                        stg.status = StatusEnum.FAILED
                        stg.detail = f"Failed: {sanitized_msg}"
                        break
                raise


pipeline_runner_service = PipelineRunnerService()
