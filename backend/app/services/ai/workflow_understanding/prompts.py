from __future__ import annotations

import json
from typing import Any, Dict, Optional
from .evidence_builder import WorkflowEvidencePackage

SYSTEM_PROMPT = """You are a Principal Application Architect and Workflow Analysis Specialist for RepoGenie.
Your mission is to reconstruct and explain how an application operates by analyzing grounded source evidence, static call relationships, AST control-flow, and data flows.

CRITICAL ARCHITECTURAL & ANTI-HALLUCINATION RULES:
1. GROUNDED EVIDENCE ONLY:
   - ONLY reference files, components, functions, methods, and line numbers provided in the evidence package.
   - NEVER invent or hallucinate functions, classes, modules, or execution transitions.
2. SEPARATE STATIC CALLS FROM RUNTIME EXECUTION:
   - A static call edge proves a syntactic call relationship was identified in the AST. It does NOT prove the call executes during every runtime invocation.
   - NEVER claim runtime verification: `runtime_execution_verified` MUST ALWAYS be false. RepoGenie does not execute or profile repository code.
   - `execution_guaranteed` reflects the normal, non-exceptional static control-flow path (no intervening branches, loops, try/except blocks, or early returns/raises). Unhandled runtime exceptions thrown dynamically by callee functions are outside static analysis scope.
   - When control flow indicates branching (if/elif/else, try/except, loops, early returns/raises), mark `execution_guaranteed` as false and detail the condition or alternative path.
3. NEVER USE IMPORTS AS EXECUTION TRANSITIONS:
   - DependencyGraph import edges indicate file-level imports and structural context only. NEVER treat an import as a function call or runtime execution step.
4. STORAGE & EXTERNAL API GROUNDING:
   - Mark storage operations as verified (`storage_operation_verified: true`) ONLY if supported by verified database/ORM or file-system operations in the evidence.
   - Distinguish explicit HTTP operations (requests, httpx, aiohttp, urllib) from recognized third-party SDK operations (boto3, stripe, openai, etc.).
   - If an operation is ambiguous or unverified, state it as unverified in unresolved_aspects.
5. DATA TRANSFORMATION GROUNDING:
   - A function's existence in the repository does NOT prove a transformation occurred in a workflow.
   - Mark a transformation as observed (`data_relationship_status: "observed"`, `transformation_verified: true`) ONLY when static AST evidence confirms a call to the transformation function passing the data item (or its variable alias) or a direct data operation in the step.
   - Otherwise, mark as `inferred` or `unknown_or_unresolved`.
6. STRICT WORKFLOW LIMITS:
   - Generate AT MOST 2 application workflows corresponding to the highest-priority selected candidates.
   - Each workflow must have AT MOST 5 steps and AT MOST 2 data flows.
   - Each workflow must have AT MOST 5 participating components.
7. OUTPUT FORMAT:
   - Output MUST be a single valid JSON object strictly matching the schema. No markdown formatting outside ```json fences, no conversational prose.
"""

USER_PROMPT_TEMPLATE = """Analyze the provided repository architecture, candidate workflow call-chains, AST control-flow evidence, and verified operations to generate structured application workflow and data-flow understanding.

GROUNDED WORKFLOW EVIDENCE:
```json
{evidence_json}
```

REQUIRED OUTPUT JSON SCHEMA:
```json
{{
  "schema_version": "1.0",
  "repository_name": "<repository name matching evidence>",
  "system_architecture_type": "<system architecture type from evidence, e.g. modular_monolith, web_service>",
  "workflow_summary": "<2-4 sentences explaining the primary application operational workflows and how components collaborate>",
  "workflows": [
    {{
      "workflow_id": "<candidate_id matching evidence>",
      "name": "<Human-readable descriptive workflow name, e.g. User Authentication and Session Creation>",
      "category": "<user_request | api_handling | initialization | business_logic | data_storage | background_job | auth>",
      "description": "<Concise explanation of the workflow purpose and operation (max 400 chars)>",
      "trigger": "<Exact event or caller that initiates this workflow, e.g. HTTP POST /login>",
      "entry_point": {{
        "component_id": "<file path of entry point>",
        "name": "<Descriptive component name>",
        "role_in_workflow": "<Role in initiating this workflow>"
      }},
      "participating_components": [
        {{
          "component_id": "<file path matching evidence>",
          "name": "<Descriptive component name>",
          "role_in_workflow": "<Role of this component in the workflow>"
        }}
      ],
      "steps": [
        {{
          "step_number": 1,
          "title": "<Concise step title (max 80 chars)>",
          "component_id": "<file path of caller component>",
          "symbol_name": "<caller symbol name>",
          "action_type": "<entry | call | transformation | storage_io | external_api | response>",
          "description": "<What occurs during this step (max 300 chars)>",
          "data_received": "<Data passed into this step or null>",
          "data_produced": "<Data output or returned by this step or null>",
          "next_step": 2,
          "call_relationship_verified": true,
          "source_order_verified": true,
          "same_execution_path_verified": true,
          "execution_guaranteed": false,
          "runtime_execution_verified": false,
          "call_evidence": {{
            "caller_file": "<caller file path>",
            "caller_symbol": "<caller symbol name>",
            "callee_file": "<callee file path>",
            "callee_symbol": "<callee symbol name>",
            "call_name": "<function name called>",
            "call_site_line": <1-based line number>,
            "call_site_column": <optional column number or null>,
            "call_graph_edge_id": "<caller_file:caller_symbol->callee_file:callee_symbol>",
            "call_site_id": "<caller_file:caller_symbol->callee_file:callee_symbol@line:col>",
            "is_edge_verified": true,
            "is_site_location_verified": true
          }},
          "unresolved_aspects": ["<any unresolved parameters, dynamic dispatches, or exceptions>"],
          "confidence": "high"
        }}
      ],
      "data_flows": [
        {{
          "flow_id": "<flow identifier, e.g. flow_credentials>",
          "workflow_id": "<matching workflow_id>",
          "data_item_name": "<Name of data item flowing through steps, e.g. UserCredentials>",
          "origin": {{
            "component_id": "<origin file path>",
            "name": "<origin component name>",
            "role_in_workflow": "<origin role>"
          }},
          "destination": {{
            "component_id": "<destination file path>",
            "name": "<destination component name>",
            "role_in_workflow": "<destination role>"
          }},
          "data_relationship_status": "<observed | inferred | unknown_or_unresolved>",
          "lifecycle_stages": ["received", "validated", "transformed", "persisted"],
          "transformations": [
            {{
              "transformation_name": "<Name of transformation, e.g. HashPassword>",
              "performed_by_component": "<file path>",
              "performed_by_symbol": "<symbol name>",
              "transformation_verified": true,
              "data_relationship_status": "<observed | inferred>",
              "input_format_or_type": "<input type/format>",
              "output_format_or_type": "<output type/format>",
              "transformation_logic": "<concrete transformation logic>",
              "confidence": "high"
            }}
          ],
          "storage_library_detected": false,
          "storage_operation_verified": false,
          "storage_operation_type": "none",
          "persistence_status": "no_storage_operation_detected",
          "external_api_library_detected": false,
          "external_api_operation_verified": false,
          "external_api_operation_type": "none",
          "external_api_status": "no_external_api_operation_detected",
          "confidence": "high"
        }}
      ],
      "final_outcome": "<Final outcome or result of the workflow (max 200 chars)>",
      "call_relationships_fully_verified": true,
      "source_order_verified": true,
      "same_execution_path_verified": true,
      "execution_guaranteed": false,
      "runtime_execution_verified": false,
      "unresolved_aspects": ["<workflow-level limitations or caveats>"],
      "alternative_paths_detected": ["<any branch alternatives detected>"],
      "confidence": "high"
    }}
  ]
}}
```

Respond ONLY with valid JSON.
"""

REPAIR_PROMPT_TEMPLATE = """The following JSON response for repository application workflow understanding had a parsing syntax error.
Error: {error}

Raw response prefix:
{raw_text}

Repair this text into 100% strictly valid JSON matching the RepositoryWorkflowUnderstanding schema.
Respond ONLY with the repaired JSON object.
"""


def build_workflow_user_prompt(evidence_package: WorkflowEvidencePackage) -> str:
    """Builds the complete user prompt with formatted evidence package."""
    evidence_dict = evidence_package.model_dump()
    evidence_json = json.dumps(evidence_dict, indent=2)
    return USER_PROMPT_TEMPLATE.format(evidence_json=evidence_json)


def build_workflow_repair_prompt(raw_text: str, error: str) -> str:
    """Builds the one-shot JSON repair prompt."""
    return REPAIR_PROMPT_TEMPLATE.format(raw_text=raw_text[:6000], error=error)
