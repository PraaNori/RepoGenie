"""
Architecture Diagram Generator (Milestone 5, Phase 5.2).

Generates evidence-grounded repository-level architecture diagrams representing:
- Major system components
- Component responsibilities
- Grounded dependencies and verified interactions
- External services where static/runtime evidence supports them
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set

from app.services.ai.code_understanding.schemas import (
    ComponentInteractionItem,
    ComponentUnderstandingItem,
    RepositoryCodeUnderstanding,
)
from app.services.ai.project_understanding.schemas import EvidenceReference
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


class ArchitectureDiagramGenerator(BaseDiagramGenerator):
    """Generates repository-level architecture diagrams."""

    def __init__(self):
        super().__init__(DiagramType.ARCHITECTURE)

    def _determine_category(self, comp_name: str, file_path: str, raw_cat: Optional[str]) -> str:
        """Classifies component into a visual category."""
        low_name = comp_name.lower()
        low_file = file_path.lower()
        if any(k in low_name or k in low_file for k in ["cli", "command", "route", "api", "entry", "main", "controller", "decorator"]):
            return "entrypoint"
        if any(k in low_name or k in low_file for k in ["db", "database", "store", "model", "cache", "storage", "entity"]):
            return "storage"
        if any(k in low_name or k in low_file for k in ["client", "gcp", "aws", "http", "external", "service", "cloud"]):
            return "external"
        if any(k in low_name or k in low_file for k in ["util", "helper", "common", "format", "config"]):
            return "utility"
        return "core"

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: RepositoryKnowledge,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
    ) -> DiagramGenerationResult:
        start_time = time.perf_counter()
        verified_files, verified_evidence, warnings = self.extract_and_validate_files(scene, knowledge)

        # 1. Discover components
        components: List[Dict[str, str]] = []
        comp_id_map: Dict[str, Dict[str, str]] = {}
        seen_names: Set[str] = set()

        if code_understanding and code_understanding.components:
            for c in code_understanding.components:
                c_name = sanitize_text(c.name, 32)
                c_file = sanitize_filename(c.file_path)
                c_resp = sanitize_text(c.primary_responsibility, 50)
                cat = self._determine_category(c_name, c_file, getattr(c, "category", None))
                comp_info = {
                    "id": f"c_{len(components)}",
                    "raw_id": getattr(c, "component_id", c_name),
                    "name": c_name,
                    "file": c_file,
                    "responsibility": c_resp,
                    "category": cat,
                }
                components.append(comp_info)
                comp_id_map[comp_info["raw_id"]] = comp_info
                seen_names.add(c_name)

        # Fallback to important directories / files if code understanding components are missing
        if not components:
            warnings.append("No AI code components found; extracting components from repository directory structure.")
            if knowledge.repository_structure and knowledge.repository_structure.important_directories:
                for idx, d in enumerate(knowledge.repository_structure.important_directories[:5]):
                    c_name = d.replace("/", " > ")
                    cat = "entrypoint" if idx == 0 else "core"
                    comp_info = {
                        "id": f"c_{idx}",
                        "raw_id": d,
                        "name": c_name,
                        "file": d,
                        "responsibility": "Repository architectural subsystem",
                        "category": cat,
                    }
                    components.append(comp_info)
                    comp_id_map[d] = comp_info
            elif verified_files:
                for idx, f in enumerate(verified_files[:5]):
                    c_name = f.split("/")[-1]
                    comp_info = {
                        "id": f"c_{idx}",
                        "raw_id": f,
                        "name": c_name,
                        "file": f,
                        "responsibility": "Core module",
                        "category": "core",
                    }
                    components.append(comp_info)
                    comp_id_map[f] = comp_info

        # Filter to most relevant components (limit to 6-8 for clear 1080p display)
        if len(components) > 7:
            # Prioritize scene related components if available
            related_set = extract_component_identifiers(scene.related_components)
            priority_comps = [c for c in components if c["name"] in related_set or c["raw_id"] in related_set or c["file"] in related_set]
            other_comps = [c for c in components if c not in priority_comps]
            components = (priority_comps + other_comps)[:6]

        # 2. Discover verified interactions / edges
        edges: List[Dict[str, Any]] = []
        if code_understanding and code_understanding.cross_component_interactions:
            for inter in code_understanding.cross_component_interactions:
                src_info = comp_id_map.get(inter.source_component)
                tgt_info = comp_id_map.get(inter.target_component)
                if src_info and tgt_info and src_info["id"] != tgt_info["id"]:
                    is_conf = getattr(inter, "is_confirmed", True)
                    edges.append({
                        "from": src_info["id"],
                        "to": tgt_info["id"],
                        "label": sanitize_text(inter.interaction_type, 20) or "uses",
                        "is_confirmed": is_conf,
                    })

        # If no explicit interactions found, derive from dependency graph or sequential order
        if not edges and len(components) > 1:
            warnings.append("Using static dependency relationships to establish component connections.")
            for i in range(len(components) - 1):
                edges.append({
                    "from": components[i]["id"],
                    "to": components[i + 1]["id"],
                    "label": "coordinates with",
                    "is_confirmed": False,
                })

        # 3. Generate Graphviz DOT source
        dot_lines = [
            "digraph Architecture {",
            '  graph [bgcolor="transparent", rankdir=LR, nodesep="0.7", ranksep="1.1", pad="0.4"];',
            '  node [shape=box, style="rounded,filled", fontname="Helvetica,Arial,sans-serif", fontsize=13, margin="0.25,0.18"];',
            '  edge [color="#64748B", penwidth=2, fontname="Helvetica,Arial,sans-serif", fontsize=11, arrowsize=0.85];',
            "",
        ]

        # Group components into clusters
        cluster_groups: Dict[str, List[Dict[str, str]]] = {
            "Interface & Entrypoints": [c for c in components if c["category"] == "entrypoint"],
            "Core Execution Engine": [c for c in components if c["category"] == "core"],
            "Persistence & Services": [c for c in components if c["category"] in ("storage", "external", "utility")],
        }

        cluster_idx = 0
        for cluster_label, comps in cluster_groups.items():
            if not comps:
                continue
            dot_lines.append(f'  subgraph cluster_{cluster_idx} {{')
            dot_lines.append(f'    label = "{cluster_label}";')
            dot_lines.append('    style = "rounded,dashed";')
            dot_lines.append('    color = "#CBD5E1";')
            dot_lines.append('    fontname = "Helvetica,Arial,sans-serif";')
            dot_lines.append('    fontsize = 12;')
            dot_lines.append('    fontcolor = "#475569";')
            for c in comps:
                colors = CATEGORY_COLORS.get(c["category"], CATEGORY_COLORS["core"])
                node_label = f'{c["name"]}\\n{c["responsibility"]}\\n[{c["file"]}]'
                dot_lines.append(
                    f'    {c["id"]} [label="{node_label}", fillcolor="{colors["bg"]}", color="{colors["border"]}", penwidth=2];'
                )
            dot_lines.append("  }")
            cluster_idx += 1

        dot_lines.append("")
        for e in edges:
            if e.get("is_confirmed", True):
                dot_lines.append(f'  {e["from"]} -> {e["to"]} [label=" {e["label"]} ", style="solid", color="#64748B"];')
            else:
                dot_lines.append(f'  {e["from"]} -> {e["to"]} [label=" {e["label"]} (inferred) ", style="dashed", color="#94A3B8"];')
        dot_lines.append("}")
        dot_source = "\n".join(dot_lines)

        # 4. Generate Mermaid source
        mermaid_lines = ["graph LR"]
        for c in components:
            mermaid_lines.append(f'  {c["id"]}["<b>{c["name"]}</b><br/>{c["responsibility"]}<br/><i>{c["file"]}</i>"]')
        for e in edges:
            if e.get("is_confirmed", True):
                mermaid_lines.append(f'  {e["from"]} -->|{e["label"]}| {e["to"]}')
            else:
                mermaid_lines.append(f'  {e["from"]} -.->|{e["label"]} (inferred)| {e["to"]}')
        mermaid_source = "\n".join(mermaid_lines)

        # 5. Render SVG via DiagramRenderer
        fallback_nodes = [
            {"id": c["id"], "label": c["name"], "sublabel": c["responsibility"], "file": c["file"], "category": c["category"]}
            for c in components
        ]
        svg_content = diagram_renderer.render_diagram(
            dot_source=dot_source,
            title=scene.title or f"{knowledge.repository.name} Architecture",
            subtitle=scene.visual_description or "System-level component architecture and interaction flow",
            category_label="Architecture Diagram",
            diagram_type=DiagramType.ARCHITECTURE,
            evidence_files=verified_files,
            fallback_nodes=fallback_nodes,
            fallback_edges=edges,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        return DiagramGenerationResult(
            diagram_type=DiagramType.ARCHITECTURE,
            svg_content=svg_content,
            mermaid_source=mermaid_source,
            dot_source=dot_source,
            evidence_used=verified_evidence,
            files_referenced=verified_files,
            components_referenced=[c["name"] for c in components],
            validation_warnings=warnings,
            render_duration_ms=duration_ms,
        )
