"""
Title Card Visual Generator (Milestone 5, Phase 5.3).

Generates evidence-grounded, polished 1920x1080 SVG opening cards for educational videos.
"""

from __future__ import annotations

import html
import logging
import time
from typing import List, Optional

from app.models.schemas import RepositoryKnowledge
from app.services.ai.project_understanding.schemas import EvidenceReference, ProjectUnderstanding
from app.services.ai.script_generation.schemas import EducationalScript
from app.services.ai.storyboard_generation.schemas import StoryboardScene, VisualType
from ..diagrams.base import (
    ASPECT_RATIO,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    COLOR_CANVAS_BG,
    COLOR_CARD_BG,
    COLOR_TEXT_FAINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    DiagramGenerationResult,
    DiagramType,
    sanitize_text,
)

logger = logging.getLogger(__name__)


class TitleCardGenerator:
    """Generates 1920x1080 opening title card SVGs grounded in repository knowledge."""

    def __init__(self):
        self.diagram_type = VisualType.TITLE_CARD

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: Optional[RepositoryKnowledge] = None,
        project_understanding: Optional[ProjectUnderstanding] = None,
        script: Optional[EducationalScript] = None,
        **kwargs,
    ) -> DiagramGenerationResult:
        """Generates a complete 1080p SVG title card visual."""
        start_time = time.perf_counter()
        warnings: List[str] = []

        repo_name = "Repository"
        repo_owner = ""
        if knowledge and knowledge.repository:
            repo_name = knowledge.repository.name
            repo_owner = knowledge.repository.owner
        elif project_understanding and project_understanding.identity:
            repo_name = project_understanding.identity.name or "Repository"

        full_repo_title = f"{repo_owner} / {repo_name}" if repo_owner else repo_name

        # 1. Project description
        description = ""
        if project_understanding:
            ps = project_understanding.problem_statement
            if hasattr(ps, "how_project_solves_it") and ps.how_project_solves_it:
                description = ps.how_project_solves_it
            elif hasattr(ps, "problem_addressed") and ps.problem_addressed:
                description = ps.problem_addressed
            elif isinstance(ps, str) and ps:
                description = ps
            elif project_understanding.identity and project_understanding.identity.short_description:
                description = project_understanding.identity.short_description
        elif knowledge and knowledge.project_overview and knowledge.project_overview.description:
            description = knowledge.project_overview.description
        else:
            description = f"Technical architectural overview of the {repo_name} codebase."
            warnings.append("No explicit project description available; generated neutral repository overview.")

        # 2. Technology tags
        tech_tags: List[str] = []
        if knowledge and knowledge.technology_stack:
            pri_lang = getattr(knowledge.technology_stack, "primary_language", None)
            if pri_lang:
                tech_tags.append(str(pri_lang))
            langs = getattr(knowledge.technology_stack, "languages", []) or []
            for l in langs[:2]:
                l_name = l.name if hasattr(l, "name") else str(l)
                if l_name not in tech_tags:
                    tech_tags.append(l_name)
            fworks = getattr(knowledge.technology_stack, "frameworks", []) or []
            for f in fworks[:2]:
                f_name = f.name if hasattr(f, "name") else str(f)
                if f_name not in tech_tags:
                    tech_tags.append(f_name)
        elif project_understanding and project_understanding.technology_stack:
            for item in project_understanding.technology_stack[:4]:
                tech_tags.append(item.technology_name)

        if not tech_tags:
            tech_tags = ["Software Architecture", "Code Intelligence"]

        # 3. Learning objectives / key topics (from script or knowledge)
        objectives: List[str] = []
        if script and script.learning_objectives:
            objectives = [sanitize_text(obj, max_length=90) for obj in script.learning_objectives[:3]]
        elif knowledge and knowledge.repository_structure and knowledge.repository_structure.important_directories:
            for d in knowledge.repository_structure.important_directories[:3]:
                objectives.append(f"Explore architectural subsystems in {d}")
        else:
            objectives = [
                "Understand system-level architecture and component layout",
                "Trace execution workflows and verified call paths",
                "Inspect implementation internals and key algorithms",
            ]

        # 4. Verified evidence
        evidence_used: List[EvidenceReference] = list(scene.evidence)
        if not evidence_used and knowledge and knowledge.project_overview and knowledge.project_overview.readme_path:
            evidence_used.append(
                EvidenceReference(
                    file_path=knowledge.project_overview.readme_path,
                    evidence_type="readme_overview",
                    is_valid=True,
                    path_verified=True,
                )
            )

        # 5. Render SVG
        svg_content = self._render_svg(
            full_repo_title=full_repo_title,
            description=description,
            tech_tags=tech_tags,
            objectives=objectives,
            scene=scene,
        )
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return DiagramGenerationResult(
            diagram_type=DiagramType.ARCHITECTURE,
            svg_content=svg_content,
            mermaid_source=f"graph TD\n  Title[\"{full_repo_title}\"]\n  Desc[\"{description[:60]}\"]",
            dot_source=f'// Title card for {full_repo_title}',
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            aspect_ratio=ASPECT_RATIO,
            evidence_used=evidence_used,
            files_referenced=[e.file_path for e in evidence_used if e.file_path],
            components_referenced=[repo_name],
            validation_warnings=warnings,
            render_duration_ms=duration_ms,
        )

    def _render_svg(
        self,
        full_repo_title: str,
        description: str,
        tech_tags: List[str],
        objectives: List[str],
        scene: StoryboardScene,
    ) -> str:
        """Renders 1920x1080 title card SVG."""
        esc_title = html.escape(sanitize_text(full_repo_title, max_length=50))
        esc_desc = html.escape(sanitize_text(description, max_length=180))
        esc_scene_title = html.escape(sanitize_text(scene.title, max_length=70))

        # Render tech pill badges
        pill_elements: List[str] = []
        pill_x = 0.0
        for tag in tech_tags[:4]:
            esc_tag = html.escape(sanitize_text(tag, max_length=24).upper())
            pw = max(len(esc_tag) * 9 + 28, 90)
            pill_elements.append(f"""
      <rect x="{pill_x}" y="0" width="{pw}" height="32" rx="16" fill="#EEF2FF" stroke="#6366F1" stroke-width="1.5" />
      <text x="{pill_x + (pw / 2.0)}" y="21" font-size="12" font-weight="700" fill="#4F46E5" text-anchor="middle">{esc_tag}</text>""")
            pill_x += pw + 14.0

        # Render 3 objective cards
        obj_cards: List[str] = []
        card_w = 540.0
        card_h = 240.0
        card_start_x = 100.0
        card_y = 660.0

        icons = ["01", "02", "03"]
        icon_colors = ["#4F46E5", "#059669", "#D97706"]
        icon_bgs = ["#EEF2FF", "#ECFDF5", "#FFFBEB"]

        for idx, obj in enumerate(objectives[:3]):
            cx = card_start_x + (idx * (card_w + 50.0))
            esc_obj = html.escape(sanitize_text(obj, max_length=110))
            num = icons[idx]
            ic_c = icon_colors[idx]
            ic_bg = icon_bgs[idx]

            obj_cards.append(f"""
    <!-- Objective Card {idx + 1} -->
    <g transform="translate({cx}, {card_y})">
      <rect width="{card_w}" height="{card_h}" rx="16" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1.5" />
      <rect x="0" y="0" width="8" height="{card_h}" rx="4" fill="{ic_c}" />
      <!-- Step Badge -->
      <rect x="36" y="28" width="44" height="28" rx="8" fill="{ic_bg}" />
      <text x="58" y="47" font-size="13" font-weight="700" fill="{ic_c}" text-anchor="middle">{num}</text>
      <!-- Title -->
      <text x="36" y="90" font-size="12" font-weight="700" fill="#64748B" letter-spacing="0.06em">MODULE TOPIC</text>
      <text x="36" y="126" font-size="17" font-weight="600" fill="#0F172A">{esc_obj[:46]}</text>
      {f'<text x="36" y="156" font-size="17" font-weight="600" fill="#0F172A">{esc_obj[46:92]}</text>' if len(esc_obj) > 46 else ''}
      {f'<text x="36" y="186" font-size="17" font-weight="600" fill="#0F172A">{esc_obj[92:]}</text>' if len(esc_obj) > 92 else ''}
    </g>""")

        return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}">
  <defs>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&amp;display=swap');
      text {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
      .hero-title {{ font-size: 52px; font-weight: 800; fill: #0F172A; letter-spacing: -0.02em; }}
      .hero-desc {{ font-size: 22px; font-weight: 400; fill: #475569; }}
      .badge-text {{ font-size: 13px; font-weight: 700; letter-spacing: 0.08em; fill: #4F46E5; }}
      .footer-text {{ font-size: 14px; font-weight: 500; fill: #94A3B8; }}
      .card-bg {{ fill: #FFFFFF; stroke: #E2E8F0; stroke-width: 1.5; rx: 20; }}
    </style>
    <filter id="hero-shadow" x="-3%" y="-2%" width="106%" height="106%" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="6" stdDeviation="12" flood-color="#0F172A" flood-opacity="0.06" />
    </filter>
  </defs>

  <!-- Background 16:9 Canvas -->
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="{COLOR_CANVAS_BG}" />

  <!-- Soft Accent Decorative Geometric Shapes -->
  <circle cx="180" cy="180" r="140" fill="#EEF2FF" opacity="0.6" />
  <circle cx="1780" cy="300" r="180" fill="#ECFDF5" opacity="0.6" />

  <!-- Main Canvas Card Outer Frame -->
  <rect x="40" y="30" width="1840" height="1020" class="card-bg" filter="url(#hero-shadow)" />

  <!-- Header Category Pill -->
  <g transform="translate(100, 75)">
    <rect x="0" y="0" width="160" height="30" rx="15" fill="#EEF2FF" stroke="#6366F1" stroke-width="1.5" />
    <text x="16" y="20" class="badge-text">VIDEO OVERVIEW</text>
  </g>

  <!-- Hero Content Center Group -->
  <g transform="translate(100, 150)">
    <!-- Subtitle scene purpose banner -->
    <text x="0" y="32" font-size="16" font-weight="600" fill="#6366F1" letter-spacing="0.05em">CODEBASE WALKTHROUGH</text>

    <!-- Main Repository Name Title -->
    <text x="0" y="100" class="hero-title">{esc_title}</text>

    <!-- Problem statement / Description -->
    <text x="0" y="160" class="hero-desc">{esc_desc[:90]}</text>
    {f'<text x="0" y="196" class="hero-desc">{esc_desc[90:180]}</text>' if len(esc_desc) > 90 else ''}

    <!-- Technology tags row -->
    <g transform="translate(0, 240)">
      {''.join(pill_elements)}
    </g>
  </g>

  <!-- Divider -->
  <line x1="100" y1="590" x2="1820" y2="590" stroke="#F1F5F9" stroke-width="2" />

  <!-- What you will learn section label -->
  <text x="100" y="630" font-size="14" font-weight="700" fill="#64748B" letter-spacing="0.06em">IN THIS EPISODE</text>

  <!-- 3 Objectives Cards -->
  {''.join(obj_cards)}

  <!-- Footer Section -->
  <line x1="80" y1="1000" x2="1840" y2="1000" stroke="#F1F5F9" stroke-width="1.5" />
  <g transform="translate(100, 1024)">
    <text x="0" y="0" class="footer-text">RepoGenie Educational Video Platform • Unified Code Intelligence</text>
    <text x="1720" y="0" text-anchor="end" class="footer-text">16:9 1080p • Technical Overview</text>
  </g>
</svg>"""


title_card_generator = TitleCardGenerator()
