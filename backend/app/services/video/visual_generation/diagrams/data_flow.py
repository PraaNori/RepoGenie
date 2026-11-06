"""
Data-Flow Diagram Generator (Milestone 5, Phase 5.2).

Generates evidence-grounded data flow diagrams representing:
- Data sources and input formats
- Transformation and parsing stages
- Intermediate processing
- Storage destinations, persistence operations, and external API sinks
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set

from app.services.ai.code_understanding.schemas import RepositoryCodeUnderstanding
from app.services.ai.storyboard_generation.schemas import StoryboardScene
from app.services.ai.workflow_understanding.schemas import (
    ApplicationWorkflow,
    DataFlow,
    DataTransformation,
    RepositoryWorkflowUnderstanding,
)
from app.models.schemas import RepositoryKnowledge
from .base import (
    BaseDiagramGenerator,
    CATEGORY_COLORS,
    DiagramGenerationResult,
    DiagramType,
    sanitize_filename,
    sanitize_text,
)
from .renderer import diagram_renderer

logger = logging.getLogger(__name__)


class DataFlowDiagramGenerator(BaseDiagramGenerator):
    """Generates data-flow and transformation pipeline diagrams."""

    def __init__(self):
        super().__init__(DiagramType.DATA_FLOW)

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
    ) -> DiagramGenerationResult:
        start_time = time.perf_counter()
        verified_files, verified_evidence, warnings = self.extract_and_validate_files(scene, knowledge)

        # 1. Discover data flows from workflows
        data_flow_stages: List[Dict[str, Any]] = []

        if workflow_understanding and workflow_understanding.workflows:
            for wf in workflow_understanding.workflows:
                if wf.data_flows:
                    for df in wf.data_flows[:2]:
                        item_name = sanitize_text(df.data_item_name, 24) or "Data Stream"
                        orig_val = getattr(df.origin, "name", None) or getattr(df.origin, "component_id", None) or df.origin
                        dest_val = getattr(df.destination, "name", None) or getattr(df.destination, "component_id", None) or df.destination
                        origin = sanitize_text(orig_val, 26) or "Input Source"
                        dest = sanitize_text(dest_val, 26) or "Destination"

                        # Stage 1: Origin
                        data_flow_stages.append({
                            "id": "df_origin",
                            "name": origin,
                            "role": f"Source: {item_name}",
                            "type": "source",
                            "file": "Input Stream",
                        })

                        # Stage 2: Transformations
                        if df.transformations:
                            for idx, t in enumerate(df.transformations[:2]):
                                t_name = sanitize_text(t.transformation_name, 26)
                                t_by = sanitize_text(t.performed_by_symbol, 24) or "Transform"
                                data_flow_stages.append({
                                    "id": f"df_trans_{idx}",
                                    "name": t_name,
                                    "role": f"Transform ({t_by})",
                                    "type": "transform",
                                    "file": t_by,
                                })
                        else:
                            data_flow_stages.append({
                                "id": "df_trans_0",
                                "name": "Validation & Parse",
                                "role": "Type Conversion",
                                "type": "transform",
                                "file": "Core Logic",
                            })

                        # Stage 3: Destination
                        dest_type = "storage" if getattr(df, "storage_operation_verified", False) else "destination"
                        data_flow_stages.append({
                            "id": "df_dest",
                            "name": dest,
                            "role": f"Sink: {item_name}",
                            "type": dest_type,
                            "file": "Output / DB",
                        })
                        break
                if data_flow_stages:
                    break

        # Fallback pipeline if no structured data flows exist
        if not data_flow_stages:
            warnings.append("No structured AI data-flows found; generating deterministic input-processing-output flow.")
            data_flow_stages = [
                {"id": "df_1", "name": "Input Source", "role": "CLI Arguments / Request Payload", "type": "source", "file": "sys.argv / Request"},
                {"id": "df_2", "name": "Data Parsing & Validation", "role": "Type conversion & constraint validation", "type": "transform", "file": "Parameter Engine"},
                {"id": "df_3", "name": "Context Transformation", "role": "Assemble domain models & execution state", "type": "transform", "file": "Context Pipeline"},
                {"id": "df_4", "name": "Sink & Persistence", "role": "Structured output & response delivery", "type": "storage", "file": "Output Stream"},
            ]

        # 2. Sequential pipeline edges
        edges: List[Dict[str, str]] = []
        for i in range(len(data_flow_stages) - 1):
            edges.append({
                "from": data_flow_stages[i]["id"],
                "to": data_flow_stages[i + 1]["id"],
                "label": "flows to",
            })

        # 3. Generate Graphviz DOT source
        dot_lines = [
            "digraph DataFlowPipeline {",
            '  graph [bgcolor="transparent", rankdir=LR, nodesep="0.7", ranksep="1.1", pad="0.4"];',
            '  node [fontname="Helvetica,Arial,sans-serif", fontsize=13, margin="0.25,0.18"];',
            '  edge [color="#059669", penwidth=2.5, fontname="Helvetica,Arial,sans-serif", fontsize=11, arrowsize=0.85];',
            "",
        ]

        for s in data_flow_stages:
            node_label = f'{s["name"]}\\n{s["role"]}\\n[{s["file"]}]'
            if s["type"] == "source":
                # Source cylinder / database shape
                dot_lines.append(
                    f'  {s["id"]} [shape=cylinder, style="filled", fillcolor="#FFFBEB", color="#D97706", penwidth=2, label="{node_label}"];'
                )
            elif s["type"] == "storage":
                # Storage cylinder shape
                dot_lines.append(
                    f'  {s["id"]} [shape=cylinder, style="filled", fillcolor="#FFFBEB", color="#D97706", penwidth=2, label="{node_label}"];'
                )
            elif s["type"] == "transform":
                # Processing card
                dot_lines.append(
                    f'  {s["id"]} [shape=box, style="rounded,filled", fillcolor="#ECFDF5", color="#10B981", penwidth=2, label="{node_label}"];'
                )
            else:
                dot_lines.append(
                    f'  {s["id"]} [shape=box, style="rounded,filled", fillcolor="#EEF2FF", color="#6366F1", penwidth=2, label="{node_label}"];'
                )

        dot_lines.append("")
        for e in edges:
            dot_lines.append(f'  {e["from"]} -> {e["to"]};')
        dot_lines.append("}")
        dot_source = "\n".join(dot_lines)

        # 4. Generate Mermaid source
        mermaid_lines = ["flowchart LR"]
        for s in data_flow_stages:
            lbl = f"<b>{s['name']}</b><br/>{s['role']}<br/><i>{s['file']}</i>"
            if s["type"] in ("source", "storage"):
                mermaid_lines.append(f'  {s["id"]}[("{lbl}")]')
            else:
                mermaid_lines.append(f'  {s["id"]}["{lbl}"]')

        for e in edges:
            mermaid_lines.append(f'  {e["from"]} --> {e["to"]}')
        mermaid_source = "\n".join(mermaid_lines)

        # 5. Render SVG via DiagramRenderer
        fallback_nodes = [
            {
                "id": s["id"],
                "label": s["name"],
                "sublabel": s["role"],
                "file": s["file"],
                "category": "storage" if s["type"] in ("source", "storage") else "core",
            }
            for s in data_flow_stages
        ]
        svg_content = diagram_renderer.render_diagram(
            dot_source=dot_source,
            title=scene.title or "Data Flow & Transformation Pipeline",
            subtitle=scene.visual_description or "End-to-end data lifecycle, transformations, and persistence sinks",
            category_label="Data-Flow Diagram",
            diagram_type=DiagramType.DATA_FLOW,
            evidence_files=verified_files,
            fallback_nodes=fallback_nodes,
            fallback_edges=edges,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        return DiagramGenerationResult(
            diagram_type=DiagramType.DATA_FLOW,
            svg_content=svg_content,
            mermaid_source=mermaid_source,
            dot_source=dot_source,
            evidence_used=verified_evidence,
            files_referenced=verified_files,
            components_referenced=[s["name"] for s in data_flow_stages],
            validation_warnings=warnings,
            render_duration_ms=duration_ms,
        )
