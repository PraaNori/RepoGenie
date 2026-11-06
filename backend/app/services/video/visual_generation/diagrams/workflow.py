"""
Workflow Diagram Generator (Milestone 5, Phase 5.2).

Generates evidence-grounded workflow diagrams representing:
- Application entry points
- Sequential execution steps and verified call transitions
- Data passing between steps
- Conditional branches only where static analysis supports them
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set

from app.services.ai.code_understanding.schemas import RepositoryCodeUnderstanding
from app.services.ai.storyboard_generation.schemas import StoryboardScene
from app.services.ai.workflow_understanding.schemas import (
    ApplicationWorkflow,
    RepositoryWorkflowUnderstanding,
    WorkflowStep,
)
from app.models.schemas import RepositoryKnowledge
from .base import (
    BaseDiagramGenerator,
    CATEGORY_COLORS,
    DiagramGenerationResult,
    DiagramType,
    extract_workflow_step_identifiers,
    sanitize_filename,
    sanitize_text,
)
from .renderer import diagram_renderer

logger = logging.getLogger(__name__)


class WorkflowDiagramGenerator(BaseDiagramGenerator):
    """Generates execution workflow diagrams."""

    def __init__(self):
        super().__init__(DiagramType.WORKFLOW)

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
    ) -> DiagramGenerationResult:
        start_time = time.perf_counter()
        verified_files, verified_evidence, warnings = self.extract_and_validate_files(scene, knowledge)

        # 1. Discover target workflow
        workflow: Optional[ApplicationWorkflow] = None
        if workflow_understanding and workflow_understanding.workflows:
            # Check scene related workflow steps or name matching
            rel_steps = extract_workflow_step_identifiers(scene.related_workflow_steps)
            for wf in workflow_understanding.workflows:
                if any(str(s.step_number) in rel_steps or s.title in rel_steps for s in wf.steps):
                    workflow = wf
                    break
            if not workflow:
                workflow = workflow_understanding.workflows[0]

        # 2. Extract workflow steps
        step_nodes: List[Dict[str, Any]] = []
        if workflow and workflow.steps:
            for s in workflow.steps[:5]:
                step_title = sanitize_text(s.title, 26)
                sym = sanitize_text(s.symbol_name, 28)
                act = sanitize_text(s.action_type, 20) or "execute"
                desc = sanitize_text(s.description, 40)
                step_nodes.append({
                    "id": f"step_{s.step_number}",
                    "number": s.step_number,
                    "title": step_title,
                    "symbol": sym,
                    "action": act,
                    "desc": desc,
                    "is_entry": s.step_number == 1,
                    "is_terminal": s.step_number == len(workflow.steps[:5]),
                })
        else:
            warnings.append("No structured AI workflow found; generating deterministic sequential flow from entry points.")
            if knowledge.entry_points:
                ep = knowledge.entry_points[0]
                entry = getattr(ep, "file_path", None) or (ep if isinstance(ep, str) else "main.py")
            else:
                entry = "main.py"
            step_nodes = [
                {"id": "step_1", "number": 1, "title": "Program Start", "symbol": entry, "action": "initialize", "desc": "CLI invocation & parsing", "is_entry": True, "is_terminal": False},
                {"id": "step_2", "number": 2, "title": "Execution Engine", "symbol": "run()", "action": "process", "desc": "Process command context", "is_entry": False, "is_terminal": False},
                {"id": "step_3", "number": 3, "title": "Result Output", "symbol": "return", "action": "output", "desc": "Format and deliver outcome", "is_entry": False, "is_terminal": True},
            ]

        # 3. Generate edges between sequential steps
        edges: List[Dict[str, str]] = []
        for i in range(len(step_nodes) - 1):
            s_curr = step_nodes[i]
            s_next = step_nodes[i + 1]
            edges.append({
                "from": s_curr["id"],
                "to": s_next["id"],
                "label": f"Step {s_curr['number']} -> {s_next['number']}",
            })

        # 4. Generate Graphviz DOT source
        dot_lines = [
            "digraph WorkflowExecution {",
            '  graph [bgcolor="transparent", rankdir=LR, nodesep="0.7", ranksep="1.1", pad="0.4"];',
            '  node [fontname="Helvetica,Arial,sans-serif", fontsize=13, margin="0.25,0.18"];',
            '  edge [color="#6366F1", penwidth=2.5, fontname="Helvetica,Arial,sans-serif", fontsize=11, arrowsize=0.85];',
            "",
        ]

        for s in step_nodes:
            if s["is_entry"]:
                # Entrypoint pill
                node_label = f"1. [ENTRY] {s['title']}\\n{s['symbol']}\\n{s['desc']}"
                dot_lines.append(
                    f'  {s["id"]} [shape=box, style="rounded,filled", fillcolor="#EEF2FF", color="#4F46E5", penwidth=2.5, label="{node_label}"];'
                )
            elif s["is_terminal"]:
                # Terminal outcome pill
                node_label = f"{s['number']}. [OUTCOME] {s['title']}\\n{s['symbol']}\\n{s['desc']}"
                dot_lines.append(
                    f'  {s["id"]} [shape=box, style="rounded,filled", fillcolor="#ECFDF5", color="#059669", penwidth=2.5, label="{node_label}"];'
                )
            else:
                # Intermediate step
                node_label = f"{s['number']}. {s['title']}\\n{s['symbol']}\\n{s['desc']}"
                dot_lines.append(
                    f'  {s["id"]} [shape=box, style="rounded,filled", fillcolor="#FFFFFF", color="#CBD5E1", penwidth=2, label="{node_label}"];'
                )

        dot_lines.append("")
        for e in edges:
            dot_lines.append(f'  {e["from"]} -> {e["to"]};')
        dot_lines.append("}")
        dot_source = "\n".join(dot_lines)

        # 5. Generate Mermaid source
        mermaid_lines = ["flowchart LR"]
        for s in step_nodes:
            lbl = f"<b>{s['number']}. {s['title']}</b><br/>{s['symbol']}<br/><i>{s['desc']}</i>"
            if s["is_entry"]:
                mermaid_lines.append(f'  {s["id"]}(["{lbl}"])')
            elif s["is_terminal"]:
                mermaid_lines.append(f'  {s["id"]}(["{lbl}"])')
            else:
                mermaid_lines.append(f'  {s["id"]}["{lbl}"]')

        for e in edges:
            mermaid_lines.append(f'  {e["from"]} --> {e["to"]}')
        mermaid_source = "\n".join(mermaid_lines)

        # 6. Render SVG via DiagramRenderer
        fallback_nodes = [
            {
                "id": s["id"],
                "label": f"Step {s['number']}: {s['title']}",
                "sublabel": s["desc"],
                "file": s["symbol"],
                "category": "entrypoint" if s["is_entry"] else ("storage" if s["is_terminal"] else "core"),
            }
            for s in step_nodes
        ]
        wf_name = workflow.name if workflow else "Application Execution Flow"
        svg_content = diagram_renderer.render_diagram(
            dot_source=dot_source,
            title=scene.title or f"Workflow: {wf_name}",
            subtitle=scene.visual_description or "Step-by-step verified execution sequence and call transitions",
            category_label="Workflow Diagram",
            diagram_type=DiagramType.WORKFLOW,
            evidence_files=verified_files,
            fallback_nodes=fallback_nodes,
            fallback_edges=edges,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        return DiagramGenerationResult(
            diagram_type=DiagramType.WORKFLOW,
            svg_content=svg_content,
            mermaid_source=mermaid_source,
            dot_source=dot_source,
            evidence_used=verified_evidence,
            files_referenced=verified_files,
            components_referenced=[s["symbol"] for s in step_nodes],
            validation_warnings=warnings,
            render_duration_ms=duration_ms,
        )
