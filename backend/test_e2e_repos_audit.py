import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

from backend.app.services.repo.analyzer import repo_analyzer_service
from backend.app.services.repo.code_parser import code_parser_service
from backend.app.services.repo.architecture_analyzer import architecture_analyzer_service
from backend.app.services.repo.knowledge_builder import knowledge_builder_service
from backend.app.services.ai.project_understanding import project_understanding_analyzer
from backend.app.services.ai.code_understanding import code_understanding_analyzer
from backend.app.services.ai.workflow_understanding import workflow_understanding_analyzer
from backend.app.services.ai.script_generation import educational_script_analyzer
from backend.app.services.ai.storyboard_generation import educational_storyboard_analyzer

REPOS = [
    {
        "id": "e2e-anomaly",
        "name": "sachinsingh2156/Anomaly-Detection-using-GCP",
        "owner": "sachinsingh2156",
        "url": "https://github.com/sachinsingh2156/Anomaly-Detection-using-GCP",
        "path": "storage/repos/8347b135-9f51-43ff-b002-7186efc87c73",
        "type": "IoT / ML Data Pipeline (ESP32, Apps Script, BigQuery SQL, Looker Studio)",
    },
    {
        "id": "e2e-click",
        "name": "pallets/click",
        "owner": "pallets",
        "url": "https://github.com/pallets/click",
        "path": "storage/repos/audit-click",
        "type": "Python CLI Library (Command-Line Interface Creation Kit)",
    },
    {
        "id": "e2e-is",
        "name": "sindresorhus/is",
        "owner": "sindresorhus",
        "url": "https://github.com/sindresorhus/is",
        "path": "storage/repos/eb08cd2a-7020-49b0-8524-627ab90a8405",
        "type": "TypeScript / JavaScript Utility Library (Type Checking / Predicates)",
    },
]

async def audit_repository(repo_info):
    job_id = repo_info["id"]
    repo_name = repo_info["name"]
    repo_owner = repo_info["owner"]
    repo_url = repo_info["url"]
    repo_path = repo_info["path"]
    
    print(f"\n{'='*80}")
    print(f"AUDITING: {repo_name} ({repo_info['type']})")
    print(f"Local path: {repo_path}")
    print(f"{'='*80}")

    if not os.path.exists(repo_path):
        print(f"ERROR: Local path {repo_path} does not exist!")
        return {"repo": repo_name, "success": False, "error": "Path not found"}

    # 1. Structure Analysis
    analysis = repo_analyzer_service.analyze_repository(job_id, repo_name, repo_path)
    print(f"[Stage 1] Analysis: {analysis.statistics.total_files} total files, {analysis.statistics.source_files} source files")
    for lang in analysis.languages:
        print(f"  - {lang.name}: {lang.percentage}% ({lang.file_count} files, AST supported: {lang.is_parser_supported})")

    # 2. Code Parsing
    parsed = code_parser_service.parse_repository(job_id, repo_name, repo_path, analysis)
    print(f"[Stage 2] AST Parsing: {len(parsed.files)} files parsed, {parsed.total_functions} functions, {parsed.total_classes} classes")

    # 3. Architecture Analysis
    arch = architecture_analyzer_service.analyze_architecture(job_id, repo_name, parsed, analysis, repo_path)
    print(f"[Stage 3] Architecture: {len(arch.components)} components, {arch.dependency_graph.total_internal_dependencies} internal deps, {arch.call_graph.total_resolved_calls} resolved calls")

    # 4. Knowledge Consolidation
    knowledge = knowledge_builder_service.build_knowledge(
        job_id=job_id,
        repo_name=repo_name,
        repo_owner=repo_owner,
        repo_url=repo_url,
        local_path=repo_path,
        size_mb=1.0,
        file_count=analysis.statistics.total_files,
        analysis=analysis,
        parsed_repo=parsed,
        architecture=arch,
    )
    print(f"[Stage 4] Knowledge: {len(knowledge.technology_stack.languages)} languages in tech stack, {len(knowledge.source_evidence)} evidence records")
    # Verify no synthetic *.python or *.javascript paths
    bad_evidence = [se.file_path for se in knowledge.source_evidence if "*." in se.file_path]
    if bad_evidence:
        print(f"  WARNING: Synthetic evidence paths detected: {bad_evidence}")
    else:
        print(f"  VERIFIED: All evidence paths are real files ({len(knowledge.source_evidence)} verified).")

    # 5. Project Understanding
    print("[Stage 5] Running Project Understanding...")
    proj_und = await project_understanding_analyzer.analyze_project(job_id, knowledge, local_path=repo_path)
    print(f"  Project Name: {proj_und.identity.name}")
    print(f"  Summary: {proj_und.identity.short_description}")
    print(f"  Problem: {proj_und.problem_statement.problem_addressed[:120]}...")

    # 6. Code Understanding
    print("[Stage 6] Running Code Understanding...")
    code_und = await code_understanding_analyzer.analyze_codebase(job_id, knowledge, project_understanding=proj_und, local_path=repo_path)
    print(f"  Components Analyzed: {len(code_und.components)}")

    # 7. Workflow Understanding
    print("[Stage 7] Running Workflow Understanding...")
    wf_und = await workflow_understanding_analyzer.analyze_workflows(
        job_id, knowledge, project_understanding=proj_und, code_understanding=code_und, local_path=repo_path
    )
    print(f"  Workflows Discovered: {len(wf_und.workflows)}")

    # 8. Educational Script Generation
    print("[Stage 8] Generating Educational Script...")
    script = await educational_script_analyzer.generate_script(
        job_id=job_id,
        knowledge=knowledge,
        project_understanding=proj_und,
        code_understanding=code_und,
        workflow_understanding=wf_und,
        local_path=repo_path,
    )
    print(f"  Script Title: {script.title}")
    print(f"  Target Audience: {script.intended_audience}")
    print(f"  Estimated Duration: {script.total_estimated_duration_seconds}s (Sections: {len(script.sections)})")
    for idx, s in enumerate(script.sections):
        print(f"    Section {idx+1}: {s.title} [{s.purpose.value}] ({s.estimated_duration_seconds}s)")
        print(f"      Narration excerpt: {s.narration_text[:140]}...")
        print(f"      Grounded Claims: {len(s.claims)}")

    # 9. Educational Storyboard Generation
    print("[Stage 9] Generating Educational Storyboard...")
    storyboard = await educational_storyboard_analyzer.generate_storyboard(
        job_id=job_id,
        script=script,
        knowledge=knowledge,
        project_understanding=proj_und,
        code_understanding=code_und,
        workflow_understanding=wf_und,
        local_path=repo_path,
    )
    print(f"  Storyboard Title: {storyboard.title}")
    print(f"  Format: {storyboard.video_format.orientation.value} ({storyboard.video_format.aspect_ratio})")
    print(f"  Total Scenes: {len(storyboard.scenes)} (Total Duration: {storyboard.total_estimated_duration_seconds}s)")
    for scene in storyboard.scenes:
        v_type = getattr(scene.visual_type, "value", scene.visual_type)
        trans = getattr(scene.transition_to_next, "value", scene.transition_to_next)
        print(f"    Scene {scene.scene_number}: {scene.title} [{v_type}] ({scene.estimated_duration_seconds}s, transition: {trans})")
        print(f"      Visual: {scene.visual_description[:100]}...")
        print(f"      On-Screen Text: {scene.on_screen_text}")

    return {
        "repo": repo_name,
        "success": True,
        "script": script,
        "storyboard": storyboard,
        "proj_und": proj_und,
        "code_und": code_und,
        "wf_und": wf_und,
    }

async def main():
    results = []
    for r in REPOS:
        try:
            res = await audit_repository(r)
            results.append(res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"repo": r["name"], "success": False, "error": str(e)})
        # Pause briefly to allow Groq TPM token bucket to refill between repositories
        await asyncio.sleep(6)
    
    print("\n" + "="*80)
    print("AUDIT SUMMARY:")
    for r in results:
        status = "PASSED" if r.get("success") else "FAILED"
        print(f"  {r['repo']}: {status}")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
