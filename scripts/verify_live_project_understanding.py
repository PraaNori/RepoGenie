import asyncio
import json
import os
import sys
import time

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

from app.services.repo.analyzer import repo_analyzer_service
from app.services.repo.code_parser import code_parser_service
from app.services.repo.architecture_analyzer import architecture_analyzer_service
from app.services.repo.knowledge_builder import knowledge_builder_service
from app.services.ai.project_understanding import project_understanding_analyzer
from app.services.ai.token_tracker import token_tracker
from app.services.ai.llm_manager import llm_manager


async def test_repo(repo_name: str, repo_owner: str, local_path: str, repo_url: str):
    print(f"\n========================================================")
    print(f"Testing Live Project Understanding for: {repo_owner}/{repo_name}")
    print(f"Local Path: {local_path}")
    print(f"========================================================")

    job_id = f"live-test-{repo_name.replace('/', '-')}"

    # Step 1: Analyze structure
    print("1. Analyzing repository structure...")
    t0 = time.perf_counter()
    analysis = repo_analyzer_service.analyze_repository(job_id=job_id, repo_name=repo_name, local_path=local_path)
    print(f"   Done in {(time.perf_counter()-t0)*1000:.0f}ms ({analysis.statistics.source_files} source files)")

    # Step 2: Parse code
    print("2. Parsing code with Tree-sitter...")
    t0 = time.perf_counter()
    code_analysis = code_parser_service.parse_repository(job_id=job_id, repo_name=repo_name, local_path=local_path, analysis=analysis)
    print(f"   Done in {(time.perf_counter()-t0)*1000:.0f}ms ({code_analysis.total_parsed_files} files parsed)")

    # Step 3: Analyze architecture
    print("3. Analyzing architecture and dependencies...")
    t0 = time.perf_counter()
    architecture = architecture_analyzer_service.analyze_architecture(
        job_id=job_id, repo_name=repo_name, parsed_repo=code_analysis, analysis=analysis, local_path=local_path
    )
    print(f"   Done in {(time.perf_counter()-t0)*1000:.0f}ms ({architecture.dependency_graph.total_internal_dependencies} internal deps)")

    # Step 4: Build unified knowledge
    print("4. Building unified RepositoryKnowledge...")
    t0 = time.perf_counter()
    knowledge = knowledge_builder_service.build_knowledge(
        job_id=job_id,
        repo_name=repo_name,
        repo_owner=repo_owner,
        repo_url=repo_url,
        local_path=local_path,
        size_mb=4.5,
        file_count=analysis.statistics.total_files,
        analysis=analysis,
        parsed_repo=code_analysis,
        architecture=architecture,
    )
    print(f"   Done in {(time.perf_counter()-t0)*1000:.0f}ms ({len(knowledge.important_files)} important files, {len(knowledge.source_evidence)} evidence records)")

    # Step 5: Run AI Project Understanding with Groq (openai/gpt-oss-120b)
    print("5. Invoking LLM via Groq (openai/gpt-oss-120b)...")
    t0 = time.perf_counter()
    understanding = await project_understanding_analyzer.analyze_project(
        job_id=job_id,
        knowledge=knowledge,
        provider_name="groq",
    )
    wall_ms = (time.perf_counter() - t0) * 1000

    print("\n--- RESULTS ---")
    print(f"Provider / Model: {understanding.provider} / {understanding.model}")
    print(f"Wall Latency: {wall_ms:.0f}ms (reported: {understanding.latency_ms:.0f}ms)")
    if understanding.token_usage:
        print(f"Token Usage: {understanding.token_usage.prompt_tokens} prompt + {understanding.token_usage.completion_tokens} completion = {understanding.token_usage.total_tokens} total tokens")

    print(f"\n[Project Identity]")
    print(f"  Name: {understanding.identity.name}")
    print(f"  Category: {understanding.identity.category} ({understanding.identity.project_type})")
    print(f"  Short Description: {understanding.identity.short_description}")
    print(f"  Primary Purpose: {understanding.identity.primary_purpose}")

    print(f"\n[Problem Statement]")
    print(f"  Problem: {understanding.problem_statement.problem_addressed}")
    print(f"  Why it matters: {understanding.problem_statement.why_it_matters}")
    print(f"  How solved: {understanding.problem_statement.how_project_solves_it}")

    print(f"\n[Core Features ({len(understanding.core_features)})]")
    for idx, f in enumerate(understanding.core_features, 1):
        ev_summary = [f"{e.file_path}:{e.line_start or ''}" for e in f.supporting_evidence]
        print(f"  {idx}. {f.name} [{f.confidence}] -> evidence: {ev_summary}")
        print(f"     Description: {f.description}")
        print(f"     Benefit: {f.user_benefit}")

    print(f"\n[Target Audience & Use Cases]")
    print(f"  Users: {understanding.target_audience.intended_users}")
    print(f"  Needs: {understanding.target_audience.likely_needs}")
    for idx, uc in enumerate(understanding.use_cases, 1):
        print(f"  Use Case {idx}: {uc.name} - {uc.how_used}")

    print(f"\n[Technology Stack Roles ({len(understanding.technology_stack)})]")
    for idx, t in enumerate(understanding.technology_stack, 1):
        print(f"  {idx}. {t.technology_name} ({t.category}, {t.status}): {t.role_in_project}")

    print(f"\n[Educational Video Blueprint]")
    print(f"  Concise Overview: {understanding.overall_explanation.concise_overview}")
    print(f"  Analogy: {understanding.overall_explanation.beginner_friendly}")
    print(f"  Highlights for Video Scenes:")
    for idx, h in enumerate(understanding.overall_explanation.video_demonstration_highlights, 1):
        print(f"    Scene {idx}: {h}")

    return understanding


async def main():
    print("RepoGenie Milestone 3.2 - Live Verification")
    print("Testing against configured Groq model: openai/gpt-oss-120b")

    click_path = os.path.abspath("storage/repos/audit-click")
    is_path = os.path.abspath("storage/repos/3c1c7cf6-1192-4975-bf41-1ed7262e31ca")

    click_result = await test_repo(
        repo_name="click",
        repo_owner="pallets",
        local_path=click_path,
        repo_url="https://github.com/pallets/click",
    )

    print("\nWaiting 12s for Groq rate-limit buffer...")
    await asyncio.sleep(12)

    is_result = await test_repo(
        repo_name="is",
        repo_owner="sindresorhus",
        local_path=is_path,
        repo_url="https://github.com/sindresorhus/is",
    )

    print("\n========================================================")
    print("Cumulative Token Usage Summary:")
    print("========================================================")
    summary = token_tracker.get_summary()
    print(f"Total Requests: {summary.total_requests}")
    print(f"Total Tokens: {summary.total_tokens} (prompt: {summary.total_prompt_tokens}, completion: {summary.total_completion_tokens})")
    print(f"By Provider: {summary.by_provider}")
    print(f"By Model: {summary.by_model}")
    print("\nLive testing complete!")


if __name__ == "__main__":
    asyncio.run(main())
