import json
from typing import Any, Dict

SYSTEM_PROMPT = """You are a senior software educator and principal codebase architect for RepoGenie, an AI platform that transforms open-source GitHub repositories into structured educational videos.

Your mission is to perform a comprehensive, grounded project-level analysis of a repository based EXCLUSIVELY on the provided evidence package (extracted metadata, README, technology stack, directory structure, important files, entry points, and source code evidence).

CRITICAL GROUNDING AND ACCURACY RULES:
1. STRICT EVIDENCE-BASED ANALYSIS: Every claim you make about what the project does, the problems it solves, its features, audience, and tech stack MUST be directly supported by the evidence package. Never extrapolate speculative business models, enterprise features, or users not indicated by the code, README, or manifests.
2. EVIDENCE CITATIONS: Each core feature, target audience group, use case, and technology item MUST reference supporting evidence (e.g. file path, line numbers if known, and evidence type: "code", "readme", "manifest", "config"). If exact line numbers are unavailable, cite the relevant file path (e.g. "README.md", "pyproject.toml", "package.json", or a source file).
3. DISTINGUISH CONFIRMED VS INFERRED: If a technology or feature is explicitly verified by a manifest, entry point, or clear README statement, mark it as "confirmed" with "high" confidence. If it is deduced from folder structure or generic dependencies, mark it as "inferred" with "medium" or "low" confidence.
4. EDUCATIONAL AND ACCESSIBLE: Produce clear, engaging explanations suitable for an educational video. Offer a concise 1-2 sentence overview, a deeper technical explanation, a beginner-friendly analogy, and 3-5 specific visual demonstration highlights for a video script.
5. STRICT JSON OUTPUT: Return ONLY a valid JSON object matching the requested schema. Do not include markdown commentary, conversational filler, or introductory notes.
"""


def build_project_understanding_user_prompt(evidence_package: Dict[str, Any]) -> str:
    """
    Constructs the user prompt containing the evidence package and expected JSON schema.
    """
    evidence_json = json.dumps(evidence_package, indent=2)

    return f"""Analyze the following repository evidence package and generate a complete Project Understanding analysis in JSON format.

EVIDENCE PACKAGE:
{evidence_json}

SCHEMA REQUIREMENTS:
Your output must be a single valid JSON object with these exact keys:
{{
  "schema_version": "1.0",
  "identity": {{
    "name": "Project name",
    "short_description": "Single-sentence accurate description",
    "category": "E.g. CLI Framework / Web Application / Developer Tool / Utility Library",
    "project_type": "E.g. Library / Framework / Application / CLI Tool / Microservice",
    "primary_purpose": "Core objective and primary purpose of this software"
  }},
  "problem_statement": {{
    "problem_addressed": "Specific technical or domain problem this repository solves",
    "why_it_matters": "Why this problem is painful, challenging, or important to developers/users",
    "how_project_solves_it": "How the repository's design and code solves this problem"
  }},
  "core_features": [
    {{
      "name": "Feature name",
      "description": "Clear explanation of what the feature does",
      "user_benefit": "Why this feature matters to the developer or user",
      "supporting_evidence": [
        {{
          "file_path": "README.md or relative source file path",
          "line_start": 1,
          "line_end": 10,
          "evidence_type": "readme | code | manifest | config",
          "confidence": "high | medium | low",
          "status": "confirmed | inferred",
          "detail": "Brief note on what in this file supports the feature"
        }}
      ],
      "confidence": "high"
    }}
  ],
  "target_audience": {{
    "intended_users": ["User group 1", "User group 2"],
    "likely_needs": ["Key need 1", "Key need 2"],
    "supporting_evidence": [
      {{
        "file_path": "README.md or file path",
        "evidence_type": "readme",
        "confidence": "high",
        "status": "confirmed"
      }}
    ],
    "is_established": true
  }},
  "use_cases": [
    {{
      "name": "Use case title",
      "description": "Concrete real-world scenario",
      "how_used": "Step-by-step or functional way developers employ it",
      "supporting_evidence": [
        {{
          "file_path": "file path",
          "evidence_type": "code | readme | manifest",
          "confidence": "high",
          "status": "confirmed"
        }}
      ]
    }}
  ],
  "technology_stack": [
    {{
      "technology_name": "Technology name",
      "category": "Language | Framework | Library | Database | Tool | Packaging",
      "role_in_project": "Its specific function in this codebase",
      "why_used": "Why it is appropriate here",
      "supporting_evidence": [
        {{
          "file_path": "file path (e.g. pyproject.toml, package.json)",
          "evidence_type": "manifest | code",
          "confidence": "high",
          "status": "confirmed"
        }}
      ],
      "status": "confirmed"
    }}
  ],
  "overall_explanation": {{
    "concise_overview": "1-2 sentence high-level summary",
    "detailed_explanation": "In-depth paragraph explaining how the project works and its architecture",
    "beginner_friendly": "Plain-English explanation using simple concepts or an analogy",
    "interesting_aspects": "Notable engineering decisions, design patterns, or strengths",
    "video_demonstration_highlights": [
      "Key highlight 1 to show on screen in a video",
      "Key highlight 2 to show in a code walkthrough",
      "Key highlight 3 to explain architectural flow"
    ]
  }}
}}

Provide exactly 3 to 5 core features, 2 to 3 target user groups, 2 to 3 use cases, and 3 to 6 key technologies.
CRITICAL: Keep all descriptions concise (1-2 sentences per item). Do NOT list every individual function or method in the codebase; group related capabilities into high-level features.
Ensure the entire JSON is fully closed and valid. Output valid JSON only.
"""


def build_repair_prompt(malformed_json_text: str, error_message: str) -> str:
    """
    Constructs a repair prompt to fix invalid or incomplete JSON output from an LLM.
    """
    return f"""The previous response was intended to be a valid JSON object matching the ProjectUnderstanding schema, but parsing failed with error:
{error_message}

BROKEN OR TRUNCATED OUTPUT:
{malformed_json_text}

TASK:
Fix the JSON syntax errors and ensure the entire JSON object is complete and closed.
All top-level keys must be present: "schema_version", "identity", "problem_statement", "core_features", "target_audience", "use_cases", "technology_stack", "overall_explanation".
Output ONLY the valid, well-formed JSON object. Do NOT include markdown code blocks, explanations, or preamble.
"""
