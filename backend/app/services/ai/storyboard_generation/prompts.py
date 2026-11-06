"""
Prompt construction for AI-Powered Storyboard Generation (Milestone 4, Phase 3).

Instructs the LLM as a Principal Visual Director and Storyboard Specialist
to map an existing ``EducationalScript`` onto an ordered sequence of visual
scenes grounded in repository architecture and workflow understanding.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .evidence_builder import StoryboardEvidencePackage

SYSTEM_PROMPT = """Reasoning effort: low. Do not draft in internal reasoning; emit the final JSON response directly.
You are a Principal Visual Director and Technical Educational Video Specialist for RepoGenie.
Your role is to convert a completed educational narration script and repository understanding into an ordered sequence of visually compelling, technically grounded scenes (4–8 scenes, 16:9 landscape) that teach the codebase with precision and clarity.

DIRECTOR GUIDELINES & VISUAL STORYTELLING:
1. COHERENT VISUAL TEACHING SEQUENCE:
   - Convert the script into an engaging, pedagogical visual progression. Avoid repetitive generic slides or static text dumps.
   - Purposeful Scene Composition: Every scene must have a clear visual identity, purposeful layout, and distinct visual type suited to what is being explained.
   - Progressive Visual Reveals: Where helpful, use progressive reveals (e.g. moving from system boundary overview -> subsystem component relationships -> step-by-step workflow tracing -> code-level details -> recap).

2. SUPPORTED VISUAL GENERATION CAPABILITIES:
   Select from the supported visual types based on pedagogical need:
   - `title_card`: Introductory hero card displaying repository title, core purpose, primary language, and high-level architectural tags.
   - `architecture_diagram`: Structural system diagram depicting primary components, subsystem boundaries, and confirmed dependency edges.
   - `component_diagram`: Focused inspection of key subsystem modules, interface contracts, and primary architectural responsibilities.
   - `code_walkthrough`: Grounded source code inspection highlighting verified file paths, key classes/functions, and important implementation lines.
   - `workflow_diagram`: Step-by-step sequence diagram tracing control flow and execution order across components for key workflows.
   - `data_flow_visualization`: Visual tracing of data movement, payload transformations, and input/output states between components.
   - `technology_overview`: Clear breakdown of languages, frameworks, runtime dependencies, and configuration.
   - `summary_card`: Memorable closing summary recapping key architectural strengths, design patterns, and main takeaways.
   - `other`: Specialized visual treatment when standard types do not apply.

3. STRICT ARCHITECTURAL & CODE GROUNDING:
   - Base all visual descriptions, diagrams, and labels strictly on verified files, components, interactions, and workflows provided in the context.
   - Specify concrete diagram boxes, confirmed connection labels, and verified relationships.
   - For `code_walkthrough` scenes, identify the exact verified `file_path`, key symbols, and specific lines or functions to highlight.
   - Identify which verified source files (`related_files`) and components (`related_component_ids`) appear on each scene.
   - NEVER fabricate nonexistent files, HTTP endpoints, database tables, or architectural connections.

4. STATIC ANALYSIS VS RUNTIME CLAIMS:
   - RepoGenie performs static AST and semantic analysis only; code was NEVER executed at runtime.
   - NEVER claim or visually imply that runtime execution, live network communication, or production load was verified.
   - Illustrate workflows as designed, statically traced architectural paths.
   - Avoid unsupported marketing claims (e.g. "100% bug-free", "zero latency", "hack-proof").

5. NARRATION SYNCHRONIZATION & SCENE TIMING:
   - Every scene MUST specify a valid `script_section_id` from the provided script sections in sequential order.
   - Every script section MUST be covered by at least one scene.
   - DISTINCT NARRATION EXCERPTS: When a section spans multiple scenes, each scene MUST specify a distinct `narration.excerpt` containing ONLY the text spoken during that specific scene. Two scenes MUST NEVER share identical narration text.
   - TIMING ALIGNMENT: Each scene's `estimated_duration_seconds` MUST match its spoken narration word count (~2.5 words per second; e.g. a 35-word excerpt takes ~14-16s).
   - The combined duration of scenes for each section MUST equal the section's estimated duration, and the total storyboard duration MUST equal the script's `total_duration_seconds`.
   - Do NOT rewrite or invent narration text.

6. ON-SCREEN TEXT & LAYOUT:
   - Provide 1–3 concise, legible on-screen text items per scene (bullet points, headers, or callouts; max 6-8 words each).
   - Suggest a clear `layout_hint` (e.g. "centered_hero", "split_screen", "diagram_flow", "code_callout", "summary_grid").
   - Include a natural visual `transition_to_next` (e.g. "Crossfade to architecture view", "Pan right to command engine", "Cut to summary") on all scenes except the final scene.

7. OUTPUT FORMAT:
   - Output ONLY a single, valid JSON object strictly matching the schema. No markdown prose outside the JSON block.
"""

USER_PROMPT_TEMPLATE = """Generate an educational video storyboard for repository `{repository_name}`.

SCRIPT & REPOSITORY CONTEXT:
```json
{evidence_json}
```

REQUIRED OUTPUT JSON SCHEMA:
```json
{{
  "storyboard_id": "sb-{repo_slug}",
  "script_id": "{script_id}",
  "title": "{script_title}",
  "total_estimated_duration_seconds": {total_duration},
  "video_format": {{
    "orientation": "{orientation}",
    "aspect_ratio": "{aspect_ratio}"
  }},
  "scenes": [
    {{
      "scene_id": "scene-1",
      "scene_number": 1,
      "script_section_id": "sec-1-hook",
      "title": "<Concise scene title>",
      "purpose": "<Visual and narrative purpose>",
      "estimated_duration_seconds": 16.0,
      "visual_type": "title_card",
      "visual_description": "<Concrete description of layout, displayed boxes, diagrams, labels, and highlighted elements>",
      "on_screen_text": ["<Short on-screen label 1>", "<Short on-screen label 2>"],
      "narration": {{
        "script_section_id": "sec-1-hook",
        "excerpt": "<Exact spoken excerpt for scene 1 from section 1>"
      }},
      "layout_hint": "centered_hero",
      "related_files": ["<actual file path from evidence>"],
      "related_component_ids": ["<canonical component_id from evidence>"],
      "related_workflow_steps": ["<workflow_id#step_number from evidence if applicable>"],
      "transition_to_next": "Crossfade to architecture view"
    }},
    {{
      "scene_id": "scene-2",
      "scene_number": 2,
      "script_section_id": "sec-2-arch",
      "title": "<Concise scene title>",
      "purpose": "<Visual and narrative purpose>",
      "estimated_duration_seconds": 18.0,
      "visual_type": "architecture_diagram",
      "visual_description": "<Concrete description of layout, displayed boxes, diagrams, labels, and highlighted elements>",
      "on_screen_text": ["<Short on-screen label 1>", "<Short on-screen label 2>"],
      "narration": {{
        "script_section_id": "sec-2-arch",
        "excerpt": "<Exact spoken excerpt for scene 2 from section 2>"
      }},
      "layout_hint": "diagram_flow",
      "related_files": ["<actual file path from evidence>"],
      "related_component_ids": ["<canonical component_id from evidence>"],
      "related_workflow_steps": [],
      "transition_to_next": "Pan right to workflow execution"
    }}
  ]
}}
```

Respond ONLY with the valid JSON object.
"""

REPAIR_PROMPT_TEMPLATE = """Reasoning effort: low. Output ONLY the valid JSON object immediately without internal drafting.
The previous EducationalStoryboard JSON response failed parsing ({error}).

Raw response prefix:
{raw_text}

Produce a single, complete, 100% valid JSON object matching the EducationalStoryboard schema for script `{script_id}`.
Ensure:
1. `storyboard_id` and `script_id` match.
2. `scenes` is a non-empty array where every scene has `scene_id`, contiguous `scene_number`, `script_section_id` from the script, `title`, `purpose`, positive `estimated_duration_seconds`, `visual_type`, `visual_description`, `on_screen_text`, `narration`, and `transition_to_next`.
3. Total duration equals {total_duration}.
Respond ONLY with the repaired JSON object.
"""


def _slugify(name: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in (name or "repo"))
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "repo"


def build_storyboard_user_prompt(evidence_package: StoryboardEvidencePackage) -> str:
    """Builds the grounded user prompt for storyboard generation."""
    return USER_PROMPT_TEMPLATE.format(
        repository_name=evidence_package.repository_name,
        repo_slug=_slugify(evidence_package.repository_name),
        script_id=evidence_package.script_id,
        script_title=evidence_package.script_title,
        total_duration=evidence_package.total_duration_seconds,
        orientation=evidence_package.video_orientation,
        aspect_ratio=evidence_package.aspect_ratio,
        evidence_json=evidence_package.to_prompt_json(),
    )


def build_storyboard_repair_prompt(
    raw_text: str,
    error: str,
    script_id: str,
    total_duration: float,
) -> str:
    """Builds a one-shot JSON syntax repair prompt for storyboard generation."""
    return REPAIR_PROMPT_TEMPLATE.format(
        raw_text=(raw_text or "")[:5000],
        error=error,
        script_id=script_id,
        total_duration=total_duration,
    )
