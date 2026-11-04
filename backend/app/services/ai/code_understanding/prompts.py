from __future__ import annotations

import json
from typing import Any, Dict

SYSTEM_PROMPT = """You are a Principal Software Architect and Code Analysis Specialist for RepoGenie.
Your mission is to produce rigorous, component-level and code-level architectural explanations of a software repository based strictly on provided source evidence.

GROUNDING & INTEGRITY RULES:
1. ONLY reference files, classes, methods, and line numbers provided in the evidence package.
2. For each component, explain its primary responsibility, why it is important to the architecture, its inputs/outputs, and how its key code symbols execute.
3. For code explanations, provide step-by-step logic, parameter descriptions, return types, and internal function calls based on the line-numbered code snippets.
4. For component interactions:
   - Mark `is_confirmed: true` ONLY for relationships backed by confirmed static import or call evidence in the prompt.
   - If you describe a logical or conceptual data flow that lacks direct static call edges in the evidence, mark `is_confirmed: false`.
5. Every explanation must cite exact `file_path` and `line_start`/`line_end` in `supporting_evidence`.
6. Output MUST be a single valid JSON object strictly matching the schema. No markdown formatting outside ```json fences, no conversational prose.
"""

USER_PROMPT_TEMPLATE = """Analyze the provided repository components, source-code snippets, and static interactions to generate structured component-level and code-level understanding.

GROUNDED REPOSITORY EVIDENCE:
```json
{evidence_json}
```

REQUIRED OUTPUT JSON SCHEMA:
```json
{{
  "schema_version": "1.0",
  "repository_name": "<repository name>",
  "architecture_overview": "<2-4 sentences explaining how these core components collaborate to deliver the application's primary functionality>",
  "components": [
    {{
      "component_id": "<file path or module id matching evidence>",
      "name": "<Human-readable component name, e.g. Command Parsing Engine>",
      "file_path": "<exact file path>",
      "category": "<architectural category, e.g. core, entry_point, service, parser>",
      "importance_score": <number matching evidence or priority rank>,
      "primary_responsibility": "<concise explanation of what this component is responsible for doing>",
      "why_important": "<architectural justification of why this component is vital to the system>",
      "inputs_and_outputs": "<clear explanation of what data, parameters, or configurations flow into this component and what it returns or dispatches>",
      "key_classes_and_functions": ["<symbol names>"],
      "code_explanations": [
        {{
          "name": "<function, method, or class name>",
          "symbol_type": "<function | method | class>",
          "file_path": "<exact file path>",
          "line_start": <positive integer start line>,
          "line_end": <positive integer end line>,
          "signature": "<optional parameter signature>",
          "summary": "<concise summary of what this code does in the application>",
          "logic_explanation": "<step-by-step breakdown of the execution flow, algorithms, branching, and error handling>",
          "parameters_and_returns": "<explanation of inputs and outputs>",
          "internal_calls": ["<names of internal functions called>"],
          "supporting_evidence": [
            {{
              "file_path": "<exact file path>",
              "line_start": <start line>,
              "line_end": <end line>,
              "evidence_type": "code",
              "confidence": "high",
              "status": "confirmed"
            }}
          ],
          "confidence": "high"
        }}
      ],
      "dependencies": ["<paths of components it imports or calls>"],
      "dependents": ["<paths of components that depend on it>"],
      "supporting_evidence": [
        {{
          "file_path": "<exact file path>",
          "line_start": <start line>,
          "line_end": <end line>,
          "evidence_type": "code",
          "confidence": "high",
          "status": "confirmed"
        }}
      ],
      "confidence": "high"
    }}
  ],
  "cross_component_interactions": [
    {{
      "source_component": "<source component file path or name>",
      "target_component": "<target component file path or name>",
      "interaction_type": "<calls | imports | inherits | instantiates | data_flow>",
      "description": "<concrete description of how the two components interact>",
      "is_confirmed": <true if backed by static call/import evidence, false if inferred>,
      "supporting_evidence": [
        {{
          "file_path": "<file path containing call or import>",
          "line_start": <line number>,
          "line_end": <line number>,
          "evidence_type": "code",
          "confidence": "high",
          "status": "confirmed"
        }}
      ],
      "confidence": "high"
    }}
  ]
}}
```

Respond ONLY with valid JSON.
"""

REPAIR_PROMPT_TEMPLATE = """The following JSON response for repository code-level understanding had a parsing syntax error.
Error: {error}

Raw response prefix:
{raw_text}

Repair this text into 100% strictly valid JSON matching the RepositoryCodeUnderstanding schema.
Respond ONLY with the repaired JSON object.
"""


def build_code_understanding_user_prompt(evidence_package: Dict[str, Any]) -> str:
    """Builds the complete user prompt with formatted evidence package."""
    evidence_json = json.dumps(evidence_package, indent=2)
    return USER_PROMPT_TEMPLATE.format(evidence_json=evidence_json)


def build_code_repair_prompt(raw_text: str, error: str) -> str:
    """Builds the one-shot JSON repair prompt."""
    return REPAIR_PROMPT_TEMPLATE.format(raw_text=raw_text[:6000], error=error)
