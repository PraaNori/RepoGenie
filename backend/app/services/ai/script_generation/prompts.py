"""
Prompt construction for AI-Powered Educational Script Generation (Milestone 4, Phase 2).

Constructs grounded, anti-hallucination prompts that guide the LLM to produce
a coherent 60–90 second (16:9 landscape) educational narration script for
developers and students from a ``ScriptEvidencePackage``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .evidence_builder import ScriptEvidencePackage
from .schemas import (
    DEFAULT_MAX_COMFORTABLE_WPM,
    DEFAULT_MIN_COMFORTABLE_WPM,
    DEFAULT_WORDS_PER_MINUTE,
    TARGET_MAX_DURATION_SECONDS,
    TARGET_MIN_DURATION_SECONDS,
    DurationTarget,
    NarrationPacing,
)

NARRATIVE_PROFILE_GUIDANCE: Dict[str, str] = {
    "library": (
        "This repository is a reusable software library, package, or framework. Focus the storyline on the "
        "developer problem it solves, its public abstractions, internal architecture (e.g. core classes, "
        "dispatch mechanisms, context management, or pipelines), how its key components collaborate, and "
        "how a caller or request moves through its primary execution workflow."
    ),
    "cli_tool": (
        "This repository is a command-line tool. Focus the storyline on its purpose, command entry point, "
        "argument/option parsing, command dispatch, and the core execution steps."
    ),
    "full_stack_application": (
        "This repository is a full-stack application. Focus the storyline on the user problem, how the "
        "frontend and backend layers collaborate, key services/components, and how requests and data flow "
        "through the application where evidence supports it."
    ),
    "web_service": (
        "This repository is a backend API or web service. Focus the storyline on the service's purpose, "
        "request entry points, core service components, and the request-handling workflow and data flow."
    ),
    "frontend_application": (
        "This repository is a frontend application. Focus the storyline on what users accomplish with it, "
        "the UI architecture and state/component structure, and the primary interaction workflow."
    ),
    "machine_learning": (
        "This repository is a machine-learning or data-science project. Focus the storyline on the problem "
        "domain, data ingestion/preprocessing, model or algorithm components, and the training or inference "
        "pipeline where evidence supports them."
    ),
    "general": (
        "Explain the project progressively: what problem it solves, how its architecture is organized, "
        "how its most important components collaborate, and how its primary workflow operates."
    ),
}

SYSTEM_PROMPT = """Reasoning effort: low. Do not draft or word-count in internal reasoning; emit the final JSON response directly.
You are a Principal Technical Educator and Scriptwriter for RepoGenie.
Your task is to write a clear, engaging, and technically accurate educational video narration script (60–90 seconds, 16:9 landscape) that helps developers and students understand a GitHub repository.

CRITICAL GROUNDING & ANTI-HALLUCINATION RULES:
1. GROUNDED EVIDENCE ONLY:
   - Base EVERY factual statement exclusively on the provided ScriptEvidencePackage JSON.
   - Cite the exact `id` values from the evidence list (e.g. "PROJ-IDENTITY", "FEAT-1", "TECH-1", "COMP-1", "WF-1", "WF-1-S1", "DF-1-1") in `evidence_ids` on sections and claims.
   - NEVER invent repository functionality, technologies, API endpoints, files, classes, functions, component interactions, execution paths, or data transformations.
   - If an upstream understanding output is listed in `missing_understanding_outputs`, do NOT invent its content; adapt the script to the available evidence and note the limitation.
2. STATIC ANALYSIS VS. RUNTIME EXECUTION:
   - RepoGenie performs static AST analysis only; repository code is NEVER executed.
   - NEVER claim or imply that static analysis has proven or verified actual runtime execution, live traffic handling, or database transaction persistence.
   - `runtime_execution_verified` MUST ALWAYS be `false`.
   - Describe workflows as statically traced or designed execution paths rather than proven runtime runs.
3. CLAIM GROUNDING STATUS:
   - Every item in `claims` must set `grounding_status` to `"confirmed"`, `"inferred"`, or `"uncertain"`.
   - Use `"confirmed"` ONLY when the cited evidence item has `"max_grounding": "confirmed"` and valid source references.
   - Use `"inferred"` for reasonable architectural or behavioral interpretations of the evidence.
   - Use `"uncertain"` when evidence is partial or unresolved, and ALWAYS provide a non-empty `uncertainty_note` explaining what is not established.
   - Omit any claim that cannot be responsibly supported by the evidence package.
   - NEVER make unsupported claims about benchmark performance, security guarantees, scalability, or production readiness.
4. NATURAL SPOKEN NARRATION QUALITY:
   - Write narration in natural, conversational spoken English suitable for voiceover.
   - Do NOT read raw file paths (such as `src/click/core.py` or `backend/app/main.py`) or raw function signatures aloud in `narration_text`. Refer to components by their human-readable names or roles, and keep file paths inside structured references.
   - Avoid unexplained jargon, repeated introductions, generic filler that could apply to any repo, or laundry lists of technologies without explaining their role in the project.
   - Do NOT explain every file or function. Select the most meaningful 2–4 components and 1–2 workflows that form one coherent educational story.
5. DURATION, PACING & MANDATORY 5-SECTION STRUCTURE:
   - Target total duration: 60–90 seconds (aim for ~70–80 seconds).
   - Speaking rate assumption: 150 words per minute (~2.5 words per second; comfortable range 110–180 wpm).
   - A 75-second script MUST contain roughly 150–200 spoken words across all sections.
   - MANDATORY 5 SECTIONS REQUIRED: You MUST generate EXACTLY 5 distinct, sequential sections. Scripts with fewer than 5 sections (such as 1, 2, 3, or 4 sections) or more than 5 sections are strictly prohibited.
   - For each section, match `narration_text` word count to `estimated_duration_seconds` (~2.2–2.7 words per second; ~35–45 words for a 14–18s section).
   - `total_estimated_duration_seconds` MUST equal the exact sum of `estimated_duration_seconds` across all 5 sections.
6. MANDATORY 5-SECTION PEDAGOGICAL SEQUENCE:
   You MUST provide EXACTLY these 5 sequential sections in order:
     Section 1 (sec-1-hook): Introduction & Core Problem (purpose: 'hook')
       Introduce the repository, developer problem solved, and core value proposition (~14–16s, ~35–45 words).
     Section 2 (sec-2-architecture): System Architecture & Core Stack (purpose: 'architecture_overview')
       Detail the foundational stack, structural layers, and architectural patterns (~14–16s, ~35–45 words).
     Section 3 (sec-3-components): Key Components & Subsystem Deep-Dive (purpose: 'component_deep_dive')
       Inspect primary abstractions, module interfaces, and core responsibilities (~16–18s, ~40–50 words).
     Section 4 (sec-4-workflow): Primary Execution Workflow & Data Flow (purpose: 'workflow')
       Walk through how a primary request or command flows across components and transforms data (~16–18s, ~40–50 words).
     Section 5 (sec-5-conclusion): Summary, Key Takeaways & Best Practices (purpose: 'conclusion')
       Summarize modular strengths, architectural design highlights, and main takeaways (~10–14s, ~25–35 words).
   - Include a natural `transition_to_next` on sections 1, 2, 3, and 4. Section 5 MUST have `transition_to_next: null`.
7. OUTPUT FORMAT:
   - Keep internal reasoning minimal (do not draft the script in reasoning first); emit the compact JSON object immediately so it finishes well within the token budget.
   - Return ONLY a single valid JSON object matching the required schema. No markdown prose outside the JSON block.
"""

USER_PROMPT_TEMPLATE = """Generate an educational explainer video script for repository `{repository_name}`.

NARRATIVE PROFILE GUIDANCE ({narrative_profile}):
{profile_guidance}

TARGET SPECIFICATION:
- Duration range: {min_duration:.0f}–{max_duration:.0f} seconds (aim for ~75 seconds across EXACTLY 5 sections)
- Speaking rate: {wpm:.0f} words per minute (comfortable range {min_wpm:.0f}–{max_wpm:.0f} wpm; ~{target_words_min}–{target_words_max} words total)
- Section count: You MUST produce EXACTLY 5 sections (`sec-1-hook`, `sec-2-architecture`, `sec-3-components`, `sec-4-workflow`, `sec-5-conclusion`). A 2-section, 3-section, or 4-section script is strictly prohibited.
- Video format: Landscape 16:9
- Audience: Developers and students

GROUNDED EVIDENCE PACKAGE:
```json
{evidence_json}
```

REQUIRED OUTPUT JSON SCHEMA (emit compact JSON immediately):
```json
{{
  "script_id": "script-{repo_slug}",
  "repository_name": "{repository_name}",
  "title": "<Clear educational title specific to this project>",
  "introduction": "<1-2 sentence overview of what the project is and why it matters>",
  "intended_audience": ["Developers", "Students"],
  "learning_objectives": [
    "<Specific learning objective 1>",
    "<Specific learning objective 2>"
  ],
  "total_estimated_duration_seconds": 75.0,
  "sections": [
    {{
      "section_id": "sec-1-hook",
      "order": 1,
      "title": "Introduction & Core Problem",
      "purpose": "hook",
      "narration_text": "<Spoken hook of ~35-45 words explaining what developer problem this project solves and why it matters.>",
      "estimated_duration_seconds": 15.0,
      "evidence_ids": ["PROJ-IDENTITY", "PROJ-PROBLEM"],
      "claims": [
        {{
          "statement": "<Concise factual claim grounded in evidence>",
          "grounding_status": "confirmed",
          "evidence_ids": ["PROJ-IDENTITY"]
        }}
      ],
      "transition_to_next": "Let us take a closer look at the architecture and underlying technologies."
    }},
    {{
      "section_id": "sec-2-architecture",
      "order": 2,
      "title": "Architecture & Core Stack",
      "purpose": "architecture_overview",
      "narration_text": "<Spoken explanation of ~35-45 words detailing the core architectural design and key technologies.>",
      "estimated_duration_seconds": 15.0,
      "evidence_ids": ["TECH-1", "COMP-1"],
      "claims": [
        {{
          "statement": "<Architectural claim grounded in evidence>",
          "grounding_status": "confirmed",
          "evidence_ids": ["TECH-1"]
        }}
      ],
      "transition_to_next": "Next, let us dive into the core components that drive this implementation."
    }},
    {{
      "section_id": "sec-3-components",
      "order": 3,
      "title": "Key Components & Subsystems",
      "purpose": "component_deep_dive",
      "narration_text": "<Spoken deep-dive of ~40-50 words explaining key modules, primary abstractions, and their responsibilities.>",
      "estimated_duration_seconds": 17.0,
      "evidence_ids": ["COMP-1", "COMP-2"],
      "claims": [
        {{
          "statement": "<Component capability claim grounded in evidence>",
          "grounding_status": "confirmed",
          "evidence_ids": ["COMP-1"]
        }}
      ],
      "transition_to_next": "Now, let us trace how execution and data flow through these components."
    }},
    {{
      "section_id": "sec-4-workflow",
      "order": 4,
      "title": "Primary Execution Workflow & Data Flow",
      "purpose": "workflow",
      "narration_text": "<Spoken walkthrough of ~40-50 words explaining how a primary request or command flows through the core components.>",
      "estimated_duration_seconds": 16.0,
      "evidence_ids": ["WF-1", "COMP-1"],
      "claims": [
        {{
          "statement": "<Workflow step claim grounded in evidence>",
          "grounding_status": "inferred",
          "evidence_ids": ["WF-1"]
        }}
      ],
      "transition_to_next": "Finally, let us review the key architectural takeaways and summary."
    }},
    {{
      "section_id": "sec-5-conclusion",
      "order": 5,
      "title": "Summary & Key Takeaways",
      "purpose": "conclusion",
      "narration_text": "<Spoken conclusion of ~25-35 words summarizing the core abstractions, developer benefits, and key architectural takeaways.>",
      "estimated_duration_seconds": 12.0,
      "evidence_ids": ["COMP-1", "PROJ-IDENTITY"],
      "claims": [
        {{
          "statement": "<Summary claim grounded in evidence>",
          "grounding_status": "confirmed",
          "evidence_ids": ["PROJ-IDENTITY"]
        }}
      ],
      "transition_to_next": null
    }}
  ],
  "conclusion": "<1-2 sentence takeaway summarizing what the viewer learned>",
  "limitations": []
}}
```

Respond ONLY with the valid JSON object.
"""

REPAIR_PROMPT_TEMPLATE = """Reasoning effort: low. Output ONLY the valid JSON object immediately without internal drafting.
The previous EducationalScript JSON response failed parsing ({error}).

Raw response prefix:
{raw_text}
{evidence_context}
Produce a single, complete, 100% valid JSON object matching the EducationalScript schema for repository `{repository_name}`.
Ensure `sections` is an array of EXACTLY 5 sections (`sec-1-hook`, `sec-2-architecture`, `sec-3-components`, `sec-4-workflow`, `sec-5-conclusion`) where every section has `section_id`, contiguous `order` (1 to 5), `title`, `purpose`, non-empty `narration_text` (~30-45 words), `estimated_duration_seconds` (~12-18s), `evidence_ids`, `claims`, and `transition_to_next` (null on section 5). Total duration must equal the exact sum of section durations.
Only cite valid `evidence_ids` from the grounded evidence. Respond ONLY with the JSON object.
"""

REVISION_PROMPT_TEMPLATE = """The generated EducationalScript JSON is outside the target narration pacing or section bounds.
Issue to correct: {reason}

Target specification:
- Total duration: {min_duration:.0f}–{max_duration:.0f} seconds
- Speaking rate: {wpm:.0f} wpm (comfortable range {min_wpm:.0f}–{max_wpm:.0f} wpm)
- Section count: EXACTLY 5 distinct sections required (`sec-1-hook`, `sec-2-architecture`, `sec-3-components`, `sec-4-workflow`, `sec-5-conclusion`). Generating only 2, 3, or 4 sections is strictly prohibited.
- Total word count: at least 130 words (~150–190 words total across all 5 sections)
- Each section's `estimated_duration_seconds` must match its `narration_text` word count at ~2.5 words/second, and `total_estimated_duration_seconds` must equal the sum of section durations.

Current script JSON:
```json
{script_json}
```

Valid evidence IDs from the evidence package:
{valid_evidence_ids}

Revise the script JSON so it contains EXACTLY 5 distinct sections with balanced narration word counts and section durations that fit cleanly within the target specification while preserving all grounded evidence IDs and anti-hallucination rules.
Respond ONLY with the revised JSON object.
"""


def _slugify_repo(repository_name: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in (repository_name or "repo"))
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "repo"


def build_script_user_prompt(
    evidence_package: ScriptEvidencePackage,
    target_duration: Optional[DurationTarget] = None,
    pacing: Optional[NarrationPacing] = None,
) -> str:
    """Builds the grounded user prompt for educational script generation."""
    target = target_duration or DurationTarget(
        min_seconds=TARGET_MIN_DURATION_SECONDS,
        max_seconds=TARGET_MAX_DURATION_SECONDS,
    )
    pace = pacing or NarrationPacing(
        words_per_minute=DEFAULT_WORDS_PER_MINUTE,
        min_comfortable_wpm=DEFAULT_MIN_COMFORTABLE_WPM,
        max_comfortable_wpm=DEFAULT_MAX_COMFORTABLE_WPM,
    )
    profile = evidence_package.narrative_profile or "general"
    guidance = NARRATIVE_PROFILE_GUIDANCE.get(profile, NARRATIVE_PROFILE_GUIDANCE["general"])

    target_words_min = int(round(target.min_seconds * pace.words_per_minute / 60.0))
    target_words_max = int(round(target.max_seconds * pace.words_per_minute / 60.0))

    return USER_PROMPT_TEMPLATE.format(
        repository_name=evidence_package.repository_name,
        repo_slug=_slugify_repo(evidence_package.repository_name),
        narrative_profile=profile,
        profile_guidance=guidance,
        min_duration=target.min_seconds,
        max_duration=target.max_seconds,
        wpm=pace.words_per_minute,
        min_wpm=pace.min_comfortable_wpm,
        max_wpm=pace.max_comfortable_wpm,
        target_words_min=target_words_min,
        target_words_max=target_words_max,
        evidence_json=evidence_package.to_prompt_json(),
    )


def build_script_repair_prompt(
    raw_text: str,
    error: str,
    evidence_package: Optional[ScriptEvidencePackage] = None,
) -> str:
    """Builds a one-shot JSON syntax repair prompt, including grounded evidence context."""
    repo_name = evidence_package.repository_name if evidence_package else "repository"
    ev_ctx = ""
    if evidence_package is not None:
        ev_ctx = f"\nGrounded evidence package:\n{evidence_package.to_prompt_json()}\n"
    return REPAIR_PROMPT_TEMPLATE.format(
        raw_text=(raw_text or "")[:5000],
        error=error,
        evidence_context=ev_ctx,
        repository_name=repo_name,
    )


def build_script_revision_prompt(
    raw_script_dict: Dict[str, Any],
    evidence_package: ScriptEvidencePackage,
    reason: str,
    target_duration: Optional[DurationTarget] = None,
    pacing: Optional[NarrationPacing] = None,
) -> str:
    """Builds a controlled revision prompt when duration or pacing is outside target bounds."""
    target = target_duration or DurationTarget()
    pace = pacing or NarrationPacing()
    return REVISION_PROMPT_TEMPLATE.format(
        reason=reason,
        min_duration=target.min_seconds,
        max_duration=target.max_seconds,
        wpm=pace.words_per_minute,
        min_wpm=pace.min_comfortable_wpm,
        max_wpm=pace.max_comfortable_wpm,
        script_json=json.dumps(raw_script_dict, indent=2, ensure_ascii=False)[:7000],
        valid_evidence_ids=sorted(evidence_package.item_ids),
    )
