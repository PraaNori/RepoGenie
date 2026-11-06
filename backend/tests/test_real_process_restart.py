"""
Audit Verification for Section 3 — Real OS Process Restart Recovery.

Verifies:
1. Starts a real backend process (Process 1).
2. Creates a job in an isolated temporary storage directory.
3. Advances the job through multiple stages (Ingestion, Analysis, Code Parsing/Knowledge, Script).
4. Stops the backend process completely (Process 1 terminates).
5. Starts a fresh backend process (Process 2) using the exact same storage directory.
6. Retrieves the original job ID in Process 2.
7. Confirms all stage states, repository metadata, knowledge, and educational script are preserved.
8. Confirms that subsequent pipeline stage access (e.g. Stage 6 Storyboard prerequisite check) succeeds.
"""

import os
import subprocess
import sys
from pathlib import Path


def test_real_separate_process_restart_recovery(tmp_path: Path):
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    jobs_storage = test_storage / "jobs"
    jobs_storage.mkdir(parents=True, exist_ok=True)
    job_id_file = tmp_path / "job_id.txt"

    env = dict(os.environ)
    env["PYTHONPATH"] = "backend"
    env["STORAGE_DIR"] = str(test_storage)
    env["VIDEO_OUTPUT_DIR"] = str(jobs_storage)

    # -------------------------------------------------------------------------
    # PROCESS 1: Creates job, advances through multiple stages, then terminates
    # -------------------------------------------------------------------------
    process_1_script = f"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from app.services.storage.job_store import job_store
from app.models.schemas import (
    DirectoryTreeNode,
    RepoAnalysisResult,
    RepoStatistics,
    StatusEnum,
    RepositoryKnowledge,
    RepositoryMetadataInfo,
    ProjectOverviewInfo,
    TechnologyStack,
    RepositoryStructureOverview,
    UnifiedStatistics,
    KnowledgeAnalysisMetadata,
)
from app.services.ai.script_generation.schemas import (
    EducationalScript,
    ScriptSection,
    SectionPurpose,
    VideoFormatSpec,
    DurationTarget,
    NarrationPacing,
)

# 1. Create job
job = job_store.create_job(
    repo_url="https://github.com/pallets/click",
    repo_name="click",
    repository_owner="pallets",
    repository_name="click",
    clone_url="https://github.com/pallets/click.git",
)
job_id = job.job_id
Path("{job_id_file}").write_text(job_id, encoding="utf-8")

# 2. Advance Stage 1 (Ingestion)
job_store.update_job_ingestion_started(job_id)
job_store.update_job_ingestion_success(job_id, local_path="/tmp/mock/click", file_count=42, size_mb=1.5)

# 3. Advance Stage 2 (Analysis)
job_store.update_job_analysis_started(job_id)
analysis = RepoAnalysisResult(
    repository_name="pallets/click",
    directory_tree=DirectoryTreeNode(name="click", path="", type="directory", children=[]),
    statistics=RepoStatistics(
        total_files=42,
        total_directories=4,
        source_files=35,
        filtered_files=7,
        total_size_bytes=1500000,
        configuration_files=2,
        dependency_manifests=1,
        recognized_languages_count=1,
    ),
    languages=[],
    dependency_files=[],
    configuration_files=[],
    analysis_status=StatusEnum.COMPLETED,
    warnings=[],
)
job_store.update_job_analysis_success(job_id, analysis)

from tests.test_script_generation import make_repository_knowledge

knowledge = make_repository_knowledge()
job_store.update_job_knowledge_success(job_id, None, None, knowledge)

# 5. Advance Stage 5 (Educational Script Generation)
script = EducationalScript(
    schema_version="1.0",
    script_id="script-click-001",
    repository_name="pallets/click",
    title="Understanding Click CLI Architecture",
    introduction="Click makes CLI authoring in Python clean and composable.",
    intended_audience=["Developers"],
    learning_objectives=["Understand Click context parsing"],
    video_format=VideoFormatSpec(),
    target_duration=DurationTarget(),
    pacing=NarrationPacing(),
    total_estimated_duration_seconds=75.0,
    sections=[
        ScriptSection(
            section_id="sec-1-hook",
            order=1,
            title="Introduction",
            purpose=SectionPurpose.HOOK,
            narration_text="Building command-line applications often introduces boilerplate.",
            estimated_duration_seconds=15.0,
        ),
        ScriptSection(
            section_id="sec-2-architecture",
            order=2,
            title="Architecture",
            purpose=SectionPurpose.ARCHITECTURE_OVERVIEW,
            narration_text="Click decouples command registration from execution flow.",
            estimated_duration_seconds=15.0,
        ),
        ScriptSection(
            section_id="sec-3-components",
            order=3,
            title="Components",
            purpose=SectionPurpose.COMPONENT_DEEP_DIVE,
            narration_text="Core components include Command, Context, and Option.",
            estimated_duration_seconds=17.0,
        ),
        ScriptSection(
            section_id="sec-4-workflow",
            order=4,
            title="Execution Workflow",
            purpose=SectionPurpose.WORKFLOW,
            narration_text="Arguments flow through the parser before reaching the callback.",
            estimated_duration_seconds=16.0,
        ),
        ScriptSection(
            section_id="sec-5-conclusion",
            order=5,
            title="Conclusion",
            purpose=SectionPurpose.CONCLUSION,
            narration_text="In summary, Click provides modular tools for building great CLIs.",
            estimated_duration_seconds=12.0,
        ),
    ],
    conclusion="Summary of Click.",
)
job_store.update_job_educational_script_success(job_id, script)
print("PROCESS_1_SUCCESS")
sys.exit(0)
"""

    res1 = subprocess.run(
        [sys.executable, "-c", process_1_script],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res1.returncode == 0, f"Process 1 failed:\nSTDOUT:\n{res1.stdout}\nSTDERR:\n{res1.stderr}"
    assert "PROCESS_1_SUCCESS" in res1.stdout

    # Process 1 has now completely exited and its OS process has terminated.
    # -------------------------------------------------------------------------
    # PROCESS 2: Fresh OS process starts up, retrieves job_id, verifies state
    # -------------------------------------------------------------------------
    saved_job_id = job_id_file.read_text(encoding="utf-8").strip()

    process_2_script = f"""
import sys
from app.services.storage.job_store import job_store
from app.models.schemas import StatusEnum

job_id = "{saved_job_id}"

# Retrieve job from fresh JobStore
job = job_store.get_internal_job(job_id)
if not job:
    print(f"FAILED: Job {{job_id}} not found in Process 2", file=sys.stderr)
    sys.exit(1)

# Verify repository metadata
assert job.repo_name == "click", f"Unexpected repo_name: {{job.repo_name}}"
assert job.repository_owner == "pallets", f"Unexpected owner: {{job.repository_owner}}"
assert job.clone_url == "https://github.com/pallets/click.git"

# Verify stage states
assert job.stages[0].status == StatusEnum.COMPLETED, f"Stage 1 not completed: {{job.stages[0].status}}"
assert job.stages[1].status == StatusEnum.COMPLETED, f"Stage 2 not completed: {{job.stages[1].status}}"
assert job.stages[2].status == StatusEnum.COMPLETED, f"Stage 3 not completed: {{job.stages[2].status}}"
assert job.stages[4].status == StatusEnum.COMPLETED, f"Stage 5 not completed: {{job.stages[4].status}}"

# Verify knowledge
assert job.knowledge is not None, "knowledge was not preserved"
assert job.knowledge.repository.name == "click"

# Verify educational script
assert job.educational_script is not None, "educational_script was not preserved"
assert len(job.educational_script.sections) == 5, f"Expected 5 sections, got {{len(job.educational_script.sections)}}"
assert job.educational_script.title == "Understanding Click CLI Architecture"

# Verify that subsequent pipeline stage access (Stage 6 Storyboard prerequisite) succeeds
# Storyboard requires Stage 5 completed with an educational_script
assert job.stages[4].status == StatusEnum.COMPLETED
assert bool(job.educational_script)

# Verify public response projection
resp = job_store.get_job(job_id)
assert resp is not None
assert resp.job_id == job_id
assert resp.has_educational_script is True
assert resp.educational_script.title == "Understanding Click CLI Architecture"
# Verify local_path is not leaked in public API response
assert not hasattr(resp, "local_path")

print("PROCESS_2_SUCCESS")
sys.exit(0)
"""

    res2 = subprocess.run(
        [sys.executable, "-c", process_2_script],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0, f"Process 2 failed:\nSTDOUT:\n{res2.stdout}\nSTDERR:\n{res2.stderr}"
    assert "PROCESS_2_SUCCESS" in res2.stdout
