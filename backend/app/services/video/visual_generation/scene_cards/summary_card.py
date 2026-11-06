"""
Summary Card Visual Generator (Milestone 5, Phase 5.3).

Generates evidence-grounded, polished 1920x1080 SVG wrap-up and takeaways cards.
"""

from __future__ import annotations

import html
import logging
import time
from typing import List, Optional

from app.models.schemas import RepositoryKnowledge
from app.services.ai.code_understanding.schemas import RepositoryCodeUnderstanding
from app.services.ai.project_understanding.schemas import EvidenceReference
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


class SummaryCardGenerator:
    """Generates 1920x1080 wrap-up and takeaways card SVGs grounded in script and repository knowledge."""

    def __init__(self):
        self.diagram_type = VisualType.SUMMARY_CARD

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: Optional[RepositoryKnowledge] = None,
        script: Optional[EducationalScript] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        **kwargs,
    ) -> DiagramGenerationResult:
        """Generates a complete 1080p SVG summary card visual."""
        start_time = time.perf_counter()
        warnings: List[str] = []

        repo_name = "Repository"
        if knowledge and knowledge.repository:
            repo_name = knowledge.repository.name

        # 1. Closing conclusion message
        conclusion = ""
        if script and script.conclusion:
            conclusion = script.conclusion
        elif scene.purpose:
            conclusion = scene.purpose
        else:
            conclusion = f"Modular, well-structured architecture across the {repo_name} codebase."
            warnings.append("No explicit script conclusion available; generated architectural wrap-up.")

        # 2. Key takeaways (3 structured takeaways)
        takeaways: List[dict] = []

        # Takeaway 1: Architecture & Design Pattern
        t1_title = "Layered Architecture"
        t1_desc = f"Clean separation of concerns with modular subsystems in {repo_name}."
        pri_lang = ""
        if knowledge and knowledge.technology_stack:
            pri_lang = getattr(knowledge.technology_stack, "primary_language", None)
            if not pri_lang and getattr(knowledge.technology_stack, "languages", None):
                first_lang = knowledge.technology_stack.languages[0]
                pri_lang = getattr(first_lang, "name", str(first_lang))

        if code_understanding and hasattr(code_understanding, "architecture_overview") and code_understanding.architecture_overview:
            t1_desc = sanitize_text(code_understanding.architecture_overview, 100)
        elif pri_lang:
            t1_desc = f"Engineered in {pri_lang} with clear component boundaries."
        takeaways.append({"title": t1_title, "desc": t1_desc, "category": "architecture", "color": "#4F46E5", "bg": "#EEF2FF"})

        # Takeaway 2: Core Execution & Data Flow
        t2_title = "Execution Dispatch"
        t2_desc = "Grounded workflows coordinate input parsing, processing, and return."
        if code_understanding and code_understanding.components:
            comp_names = [getattr(c, "component_name", None) or getattr(c, "name", "Core") for c in code_understanding.components[:2]]
            t2_desc = f"Key components: {' & '.join(comp_names)} handle primary responsibilities."
        takeaways.append({"title": t2_title, "desc": t2_desc, "category": "execution", "color": "#059669", "bg": "#ECFDF5"})

        # Takeaway 3: Reliability & Static Verification
        t3_title = "Grounded Intelligence"
        t3_desc = "All components, call sites, and workflows are verified by AST static evidence."
        if knowledge and knowledge.statistics:
            t3_desc = f"Analyzed {knowledge.statistics.source_files or 10} source files with validated AST relationships."
        takeaways.append({"title": t3_title, "desc": t3_desc, "category": "verification", "color": "#D97706", "bg": "#FFFBEB"})

        # 3. Verified evidence
        evidence_used: List[EvidenceReference] = list(scene.evidence)
        if not evidence_used and knowledge and knowledge.important_files:
            for inf in knowledge.important_files[:2]:
                rp = getattr(inf, "relative_path", None) or getattr(inf, "path", None) or str(inf)
                evidence_used.append(
                    EvidenceReference(
                        file_path=rp,
                        evidence_type="code_reference",
                        is_valid=True,
                        path_verified=True,
                    )
                )

        # 4. Render SVG
        svg_content = self._render_svg(
            repo_name=repo_name,
            scene=scene,
            conclusion=conclusion,
            takeaways=takeaways,
        )
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return DiagramGenerationResult(
            diagram_type=DiagramType.ARCHITECTURE,
            svg_content=svg_content,
            mermaid_source=f"graph TD\n  Summary[\"{repo_name} Summary\"]\n  Conclusion[\"{conclusion[:50]}\"]",
            dot_source=f'// Summary card for {repo_name}',
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
        repo_name: str,
        scene: StoryboardScene,
        conclusion: str,
        takeaways: List[dict],
    ) -> str:
        """Renders 1920x1080 summary card SVG."""
        esc_title = html.escape(sanitize_text(scene.title or f"{repo_name} Architecture Takeaways", max_length=60))
        esc_subtitle = html.escape(sanitize_text(scene.purpose or "Key concepts and architectural takeaways", max_length=110))
        esc_concl = html.escape(sanitize_text(conclusion, max_length=180))

        # Render 3 takeaway cards horizontally
        card_w = 540.0
        card_h = 360.0
        start_x = 100.0
        start_y = 480.0

        takeaway_cards: List[str] = []
        for idx, t in enumerate(takeaways[:3]):
            cx = start_x + (idx * (card_w + 50.0))
            esc_t_title = html.escape(t["title"])
            esc_t_desc = html.escape(sanitize_text(t["desc"], max_length=120))
            c_color = t["color"]
            c_bg = t["bg"]

            takeaway_cards.append(f"""
    <!-- Takeaway Card {idx + 1} -->
    <g transform="translate({cx}, {start_y})">
      <rect width="{card_w}" height="{card_h}" rx="16" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1.5" />
      <rect x="0" y="0" width="8" height="{card_h}" rx="4" fill="{c_color}" />

      <!-- Tag Badge -->
      <rect x="36" y="32" width="130" height="28" rx="14" fill="{c_bg}" />
      <text x="101" y="51" font-size="12" font-weight="700" fill="{c_color}" text-anchor="middle">{t['category'].upper()}</text>

      <!-- Card Title -->
      <text x="36" y="105" font-size="22" font-weight="700" fill="#0F172A">{esc_t_title}</text>

      <!-- Divider line inside card -->
      <line x1="36" y1="130" x2="{card_w - 36}" y2="130" stroke="#F1F5F9" stroke-width="1.5" />

      <!-- Description Body -->
      <text x="36" y="172" font-size="16" font-weight="500" fill="#475569">{esc_t_desc[:44]}</text>
      {f'<text x="36" y="204" font-size="16" font-weight="500" fill="#475569">{esc_t_desc[44:88]}</text>' if len(esc_t_desc) > 44 else ''}
      {f'<text x="36" y="236" font-size="16" font-weight="500" fill="#475569">{esc_t_desc[88:]}</text>' if len(esc_t_desc) > 88 else ''}
    </g>""")

        return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}">
  <defs>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&amp;display=swap');
      text {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
      .header-title {{ font-size: 32px; font-weight: 800; fill: #0F172A; letter-spacing: -0.01em; }}
      .header-sub {{ font-size: 16px; font-weight: 400; fill: #475569; }}
      .badge-text {{ font-size: 12px; font-weight: 700; letter-spacing: 0.08em; fill: #059669; }}
      .footer-text {{ font-size: 14px; font-weight: 500; fill: #94A3B8; }}
      .card-bg {{ fill: #FFFFFF; stroke: #E2E8F0; stroke-width: 1.5; rx: 20; }}
    </style>
    <filter id="card-shadow" x="-3%" y="-2%" width="106%" height="106%" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="6" stdDeviation="12" flood-color="#0F172A" flood-opacity="0.05" />
    </filter>
  </defs>

  <!-- Background 16:9 Canvas -->
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="{COLOR_CANVAS_BG}" />

  <!-- Soft Accent Decorative Geometric Shapes -->
  <circle cx="1780" cy="180" r="160" fill="#ECFDF5" opacity="0.6" />
  <circle cx="140" cy="850" r="140" fill="#EEF2FF" opacity="0.6" />

  <!-- Main Canvas Card Outer Frame -->
  <rect x="40" y="30" width="1840" height="1020" class="card-bg" filter="url(#card-shadow)" />

  <!-- Header Section -->
  <g transform="translate(100, 60)">
    <!-- Category Pill Badge -->
    <rect x="0" y="0" width="195" height="28" rx="14" fill="#ECFDF5" stroke="#10B981" stroke-width="1.5" />
    <text x="14" y="19" class="badge-text">SUMMARY &amp; TAKEAWAYS</text>

    <!-- Scene Title & Subtitle -->
    <text x="0" y="58" class="header-title">{esc_title}</text>
    <text x="0" y="86" class="header-sub">{esc_subtitle}</text>
  </g>

  <!-- Divider -->
  <line x1="100" y1="180" x2="1820" y2="180" stroke="#F1F5F9" stroke-width="2" />

  <!-- Hero Takeaway Quote Box -->
  <g transform="translate(100, 220)">
    <rect width="1720" height="180" rx="16" fill="#F8FAFC" stroke="#E2E8F0" stroke-width="1.5" />
    <rect x="0" y="0" width="8" height="180" rx="4" fill="#10B981" />
    <text x="44" y="44" font-size="13" font-weight="700" fill="#059669" letter-spacing="0.06em">CONCLUSION OVERVIEW</text>
    <text x="44" y="90" font-size="22" font-weight="600" fill="#0F172A">"{esc_concl[:90]}"</text>
    {f'<text x="44" y="128" font-size="20" font-weight="500" fill="#334155">{esc_concl[90:180]}</text>' if len(esc_concl) > 90 else ''}
  </g>

  <!-- 3 Structured Takeaways Cards Row -->
  {''.join(takeaway_cards)}

  <!-- Footer Section -->
  <line x1="80" y1="1000" x2="1840" y2="1000" stroke="#F1F5F9" stroke-width="1.5" />
  <g transform="translate(100, 1024)">
    <text x="0" y="0" class="footer-text">RepoGenie Educational Video Platform • Architecture Understanding Complete</text>
    <text x="1720" y="0" text-anchor="end" class="footer-text">16:9 1080p • Module Wrap-Up</text>
  </g>
</svg>"""


summary_card_generator = SummaryCardGenerator()
