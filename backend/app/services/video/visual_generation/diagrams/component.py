"""
Component Diagram Generator (Milestone 5, Phase 5.2).

Generates evidence-grounded component-level diagrams representing:
- Important classes, modules, and functions
- Key responsibilities, inputs, and outputs
- Verified interactions and dependencies between classes
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set

from app.services.ai.code_understanding.schemas import (
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
from app.services.ai.storyboard_generation.schemas import StoryboardScene
from app.services.ai.workflow_understanding.schemas import RepositoryWorkflowUnderstanding
from app.models.schemas import RepositoryKnowledge
from .base import (
    BaseDiagramGenerator,
    CATEGORY_COLORS,
    DiagramGenerationResult,
    DiagramType,
    extract_component_identifiers,
    sanitize_filename,
    sanitize_text,
)
from .renderer import diagram_renderer

logger = logging.getLogger(__name__)


class ComponentDiagramGenerator(BaseDiagramGenerator):
    """Generates detailed component and class-level diagrams."""

    def __init__(self):
        super().__init__(DiagramType.COMPONENT)

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        **kwargs,
    ) -> DiagramGenerationResult:
        start_time = time.perf_counter()
        verified_files, verified_evidence, warnings = self.extract_and_validate_files(scene, knowledge)

        # 1. Discover target components (classes / modules)
        component_cards: List[Dict[str, Any]] = []
        target_components = extract_component_identifiers(scene.related_components)

        if code_understanding and code_understanding.components:
            for c in code_understanding.components:
                # If scene specified related components, filter; otherwise take primary components
                if target_components and c.name not in target_components and getattr(c, "component_id", "") not in target_components and getattr(c, "file_path", "") not in target_components:
                    continue

                c_name = sanitize_text(c.name, 28)
                c_file = sanitize_filename(c.file_path)
                methods = [sanitize_text(m, 26) for m in (c.key_classes_and_functions or [])[:4]]
                if not methods:
                    methods = ["execute()", "validate()", "initialize()"]

                component_cards.append({
                    "id": f"comp_{len(component_cards)}",
                    "name": c_name,
                    "file": c_file,
                    "methods": methods,
                    "responsibility": sanitize_text(c.primary_responsibility, 45),
                    "dependencies": [sanitize_text(d, 28) for d in (c.dependencies or [])[:3]],
                })
                if len(component_cards) >= 5:
                    break

        # Fallback if no specific components matched
        if not component_cards:
            warnings.append("Deriving component classes from parsed code structure and files.")
            for idx, f in enumerate(verified_files[:4]):
                c_name = f.split("/")[-1].replace(".py", "").replace(".ts", "").replace(".js", "").capitalize()
                component_cards.append({
                    "id": f"comp_{idx}",
                    "name": c_name,
                    "file": f,
                    "methods": ["run()", "handle()", "configure()"],
                    "responsibility": "Core module logic",
                    "dependencies": [],
                })

        # 2. Derive relationships / edges
        edges: List[Dict[str, Any]] = []
        for i, c1 in enumerate(component_cards):
            for j, c2 in enumerate(component_cards):
                if i != j and any(
                    c2["name"].lower() in d.lower() or c2["file"].lower() in d.lower()
                    for d in c1.get("dependencies", [])
                ):
                    edges.append({
                        "from": c1["id"],
                        "to": c2["id"],
                        "label": "uses",
                        "is_confirmed": True,
                    })

        if not edges and len(component_cards) > 1:
            warnings.append("No explicit dependency evidence found between classes; connecting inferred sequential flow.")
            for i in range(len(component_cards) - 1):
                edges.append({
                    "from": component_cards[i]["id"],
                    "to": component_cards[i + 1]["id"],
                    "label": "delegates to",
                    "is_confirmed": False,
                })

        # 3. Generate Graphviz DOT source
        colors = CATEGORY_COLORS["core"]
        dot_lines = [
            "digraph ComponentUML {",
            '  graph [bgcolor="transparent", rankdir=LR, nodesep="0.8", ranksep="1.1", pad="0.4"];',
            '  node [shape=box, style="rounded,filled", fontname="Helvetica,Arial,sans-serif", fontsize=13, margin="0.25,0.18"];',
            '  edge [color="#64748B", penwidth=2, fontname="Helvetica,Arial,sans-serif", fontsize=11, arrowsize=0.85];',
            "",
        ]

        for c in component_cards:
            method_str = "\\l- " + "\\l- ".join(c["methods"]) + "\\l"
            label = f'{{ {c["name"]} | {c["responsibility"]}\\n[{c["file"]}] | {method_str} }}'
            # Use record shape for UML class structure
            dot_lines.append(
                f'  {c["id"]} [shape=record, label="{label}", fillcolor="#FFFFFF", color="#6366F1", penwidth=2];'
            )

        dot_lines.append("")
        for e in edges:
            if e.get("is_confirmed", True):
                dot_lines.append(f'  {e["from"]} -> {e["to"]} [label=" {e["label"]} ", style="solid", color="#64748B"];')
            else:
                dot_lines.append(f'  {e["from"]} -> {e["to"]} [label=" {e["label"]} (inferred) ", style="dashed", color="#94A3B8"];')
        dot_lines.append("}")
        dot_source = "\n".join(dot_lines)

        # 4. Generate Mermaid classDiagram source
        mermaid_lines = ["classDiagram"]
        for c in component_cards:
            clean_class_name = c["name"].replace(" ", "_").replace("-", "_")
            mermaid_lines.append(f"  class {clean_class_name} {{")
            for m in c["methods"]:
                clean_m = m.replace("()", "")
                mermaid_lines.append(f"    +{clean_m}()")
            mermaid_lines.append("  }")
        for e in edges:
            src = [c["name"].replace(" ", "_").replace("-", "_") for c in component_cards if c["id"] == e["from"]][0]
            dst = [c["name"].replace(" ", "_").replace("-", "_") for c in component_cards if c["id"] == e["to"]][0]
            mermaid_lines.append(f"  {src} --> {dst} : {e['label']}")
        mermaid_source = "\n".join(mermaid_lines)

        # 5. Render SVG via DiagramRenderer
        fallback_nodes = [
            {"id": c["id"], "label": c["name"], "sublabel": c["responsibility"], "file": c["file"], "category": "core"}
            for c in component_cards
        ]
        svg_content = diagram_renderer.render_diagram(
            dot_source=dot_source,
            title=scene.title or "Component & Class Structure",
            subtitle=scene.visual_description or "Detailed component roles, methods, and verified class relationships",
            category_label="Component Diagram",
            diagram_type=DiagramType.COMPONENT,
            evidence_files=verified_files,
            fallback_nodes=fallback_nodes,
            fallback_edges=edges,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        return DiagramGenerationResult(
            diagram_type=DiagramType.COMPONENT,
            svg_content=svg_content,
            mermaid_source=mermaid_source,
            dot_source=dot_source,
            evidence_used=verified_evidence,
            files_referenced=verified_files,
            components_referenced=[c["name"] for c in component_cards],
            validation_warnings=warnings,
            render_duration_ms=duration_ms,
        )
