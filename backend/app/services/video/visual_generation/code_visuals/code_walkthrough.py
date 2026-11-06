"""
Code Walkthrough Visual Generator (Milestone 5, Phase 5.3).

Generates evidence-grounded, syntax-highlighted 1080p SVG code walkthrough visuals.
"""

from __future__ import annotations

import html
import logging
import time
from typing import Any, Dict, List, Optional

from app.models.schemas import ParsedRepository, RepositoryKnowledge
from app.services.ai.code_understanding.schemas import RepositoryCodeUnderstanding
from app.services.ai.project_understanding.schemas import EvidenceReference
from app.services.ai.storyboard_generation.schemas import StoryboardScene, VisualType
from app.services.ai.workflow_understanding.schemas import RepositoryWorkflowUnderstanding
from ..diagrams.base import (
    ASPECT_RATIO,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    CATEGORY_COLORS,
    COLOR_CANVAS_BG,
    COLOR_CARD_BG,
    COLOR_TEXT_FAINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    DiagramGenerationResult,
    DiagramType,
    sanitize_filename,
    sanitize_text,
)
from .code_extractor import code_extractor
from .schemas import CodeExcerpt, CodeWalkthroughLine

logger = logging.getLogger(__name__)


class CodeWalkthroughGenerator:
    """Generates 1920x1080 SVG code walkthrough visuals with syntax highlighting and annotations."""

    def __init__(self):
        self.diagram_type = VisualType.CODE_WALKTHROUGH

    def generate(
        self,
        scene: StoryboardScene,
        knowledge: Optional[RepositoryKnowledge] = None,
        code_understanding: Optional[RepositoryCodeUnderstanding] = None,
        workflow_understanding: Optional[RepositoryWorkflowUnderstanding] = None,
        parsed_repository: Optional[ParsedRepository] = None,
        repo_root_dir: Optional[str] = None,
        **kwargs,
    ) -> DiagramGenerationResult:
        """Generates a complete 1080p SVG code walkthrough visual."""
        start_time = time.perf_counter()

        # 1. Extract code excerpt and grounded annotations
        excerpt, warnings = code_extractor.extract_code_excerpt(
            scene=scene,
            knowledge=knowledge,
            code_understanding=code_understanding,
            parsed_repository=parsed_repository,
            repo_root_dir=repo_root_dir,
        )

        # 2. Build verified evidence reference list
        verified_evidence: List[EvidenceReference] = []
        if excerpt.file_path:
            verified_evidence.append(
                EvidenceReference(
                    file_path=excerpt.file_path,
                    line_start=excerpt.start_line,
                    line_end=excerpt.end_line,
                    evidence_type="code_walkthrough",
                    is_valid=True,
                    path_verified=True,
                )
            )
        for ev in scene.evidence:
            if ev.file_path and ev.file_path != excerpt.file_path:
                verified_evidence.append(ev)

        # 3. Render complete 1920x1080 SVG document
        svg_content = self._render_svg(scene, excerpt, verified_evidence)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Construct Mermaid equivalent representation for cross-engine compatibility
        mermaid_lines = [
            "sequenceDiagram",
            f"  autonumber",
            f"  participant File as {excerpt.file_path}",
            f"  participant Func as {excerpt.symbol_name}",
        ]
        for l in excerpt.lines:
            if l.is_highlighted:
                mermaid_lines.append(f"  Note over Func: Line {l.line_number}: {l.content.strip()[:40]}")
        mermaid_source = "\n".join(mermaid_lines)

        return DiagramGenerationResult(
            diagram_type=DiagramType.COMPONENT,  # Standard fallback enum
            svg_content=svg_content,
            mermaid_source=mermaid_source,
            dot_source=f'// Code walkthrough for {excerpt.file_path}:{excerpt.symbol_name}',
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            aspect_ratio=ASPECT_RATIO,
            evidence_used=verified_evidence,
            files_referenced=[excerpt.file_path] if excerpt.file_path else [],
            components_referenced=[excerpt.symbol_name] if excerpt.symbol_name else [],
            validation_warnings=warnings,
            render_duration_ms=duration_ms,
        )

    def _render_svg(
        self,
        scene: StoryboardScene,
        excerpt: CodeExcerpt,
        evidence: List[EvidenceReference],
    ) -> str:
        """Composites the complete 1920x1080 landscape SVG layout."""
        title = html.escape(sanitize_text(scene.title, max_length=65))
        subtitle = html.escape(sanitize_text(scene.purpose or scene.visual_description, max_length=110))
        clean_file = html.escape(sanitize_filename(excerpt.file_path) or "main.py")
        symbol_name = html.escape(sanitize_text(excerpt.symbol_name or "Function", max_length=40))
        symbol_type = html.escape((excerpt.symbol_type or "function").upper())
        lang_label = html.escape(excerpt.language.upper())

        # Evidence footer text
        if evidence and evidence[0].file_path:
            ev_str = f"Verified evidence: {evidence[0].file_path}"
            if evidence[0].line_start and evidence[0].line_end:
                ev_str += f":{evidence[0].line_start}-{evidence[0].line_end}"
        else:
            ev_str = f"Verified evidence: {clean_file}"
        esc_footer_ev = html.escape(ev_str)

        # Code window dimensions
        code_w = 1180.0
        code_h = 820.0
        code_x = 80.0
        code_y = 160.0

        # Calculate line spacing to comfortably fit up to 16 lines
        num_lines = max(len(excerpt.lines), 1)
        available_code_h = code_h - 70.0  # minus titlebar and padding
        line_height = min(42.0, max(32.0, available_code_h / num_lines))
        font_size = 15 if num_lines <= 12 else 14

        # Render code editor rows
        code_rows: List[str] = []
        start_y = code_y + 70.0

        for idx, line in enumerate(excerpt.lines):
            y_pos = start_y + (idx * line_height)

            # Highlight background band if line is marked for attention
            highlight_markup = ""
            if line.is_highlighted:
                highlight_markup = f"""
    <rect x="{code_x + 65}" y="{y_pos - (line_height * 0.72):.1f}" width="{code_w - 75:.1f}" height="{line_height:.1f}" fill="#334155" opacity="0.65" rx="4" />
    <rect x="{code_x + 65}" y="{y_pos - (line_height * 0.72):.1f}" width="4" height="{line_height:.1f}" fill="#818CF8" rx="2" />"""

            # Line number in gutter
            line_num_str = f"{line.line_number:3d}" if not line.is_omission_marker else "..."
            gutter_markup = f"""<text x="{code_x + 48}" y="{y_pos:.1f}" font-family="JetBrains Mono, Fira Code, Menlo, Consolas, monospace" font-size="13" font-weight="500" fill="#64748B" text-anchor="end">{line_num_str}</text>"""

            # Code tokens with syntax colors
            token_spans: List[str] = []
            for color, text in line.tokens:
                esc_t = html.escape(text)
                token_spans.append(f'<tspan fill="{color}">{esc_t}</tspan>')

            content_markup = f"""<text x="{code_x + 85}" y="{y_pos:.1f}" font-family="JetBrains Mono, Fira Code, Menlo, Consolas, monospace" font-size="{font_size}" font-weight="400" xml:space="preserve">{''.join(token_spans)}</text>"""

            code_rows.append(f"  <g id=\"line_{line.line_number}\">{highlight_markup}\n    {gutter_markup}\n    {content_markup}\n  </g>")

        # Right-hand explanations and context cards
        panel_x = 1290.0
        panel_y = 160.0
        panel_w = 550.0

        # Context Card 1: Symbol Header & Summary
        esc_summary = html.escape(sanitize_text(excerpt.explanation_summary or scene.purpose or "Core execution logic", max_length=160))
        esc_sig = html.escape(sanitize_text(excerpt.signature or symbol_name, max_length=70))

        # Context Card 2: Parameters & Return Contract (if present)
        contract_markup = ""
        if excerpt.parameters_and_returns:
            esc_pr = html.escape(sanitize_text(excerpt.parameters_and_returns, max_length=150))
            contract_markup = f"""
    <!-- Contract Callout -->
    <g transform="translate(0, 180)">
      <rect width="{panel_w}" height="100" rx="12" fill="#F8FAFC" stroke="#E2E8F0" stroke-width="1.5" />
      <rect x="0" y="0" width="6" height="100" rx="3" fill="#10B981" />
      <text x="24" y="32" font-size="12" font-weight="700" fill="#059669" letter-spacing="0.05em">DATA &amp; RETURN CONTRACT</text>
      <text x="24" y="60" font-size="14" font-weight="500" fill="#334155">{esc_pr[:75]}</text>
      {f'<text x="24" y="82" font-size="14" font-weight="500" fill="#334155">{esc_pr[75:]}</text>' if len(esc_pr) > 75 else ''}
    </g>"""

        # Context Card 3: Grounded Line Annotations
        annotation_items: List[str] = []
        ann_offset_y = 300.0 if contract_markup else 200.0

        for idx, l in enumerate(excerpt.lines):
            if l.annotation:
                esc_ann = html.escape(sanitize_text(l.annotation, max_length=130))
                item_card = f"""
    <g transform="translate(0, {ann_offset_y:.1f})">
      <rect width="{panel_w}" height="110" rx="12" fill="#FFFFFF" stroke="#CBD5E1" stroke-width="1.5" />
      <rect x="0" y="0" width="6" height="110" rx="3" fill="#6366F1" />
      <!-- Line Number Pin Badge -->
      <rect x="24" y="16" width="68" height="24" rx="12" fill="#EEF2FF" stroke="#6366F1" stroke-width="1" />
      <text x="58" y="32" font-size="12" font-weight="700" fill="#4F46E5" text-anchor="middle">Line {l.line_number}</text>
      <!-- Annotation explanation -->
      <text x="24" y="66" font-size="14" font-weight="500" fill="#1E293B">{esc_ann[:65]}</text>
      {f'<text x="24" y="90" font-size="14" font-weight="500" fill="#475569">{esc_ann[65:]}</text>' if len(esc_ann) > 65 else ''}
    </g>"""
                annotation_items.append(item_card)
                ann_offset_y += 125.0
                if len(annotation_items) >= 3:
                    break

        if not annotation_items:
            # Fallback note explaining the component role
            fallback_ann = f"""
    <g transform="translate(0, {ann_offset_y:.1f})">
      <rect width="{panel_w}" height="110" rx="12" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1.5" />
      <rect x="0" y="0" width="6" height="110" rx="3" fill="#818CF8" />
      <text x="24" y="32" font-size="12" font-weight="700" fill="#4F46E5" letter-spacing="0.05em">CODE INSIGHT</text>
      <text x="24" y="66" font-size="14" font-weight="500" fill="#334155">{esc_summary[:70]}</text>
      {f'<text x="24" y="90" font-size="14" font-weight="500" fill="#64748B">{esc_summary[70:]}</text>' if len(esc_summary) > 70 else ''}
    </g>"""
            annotation_items.append(fallback_ann)

        return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}">
  <defs>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@400;500;600&amp;display=swap');
      text {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
      .header-title {{ font-size: 28px; font-weight: 700; fill: {COLOR_TEXT_MAIN}; }}
      .header-sub {{ font-size: 15px; font-weight: 400; fill: {COLOR_TEXT_MUTED}; }}
      .badge-text {{ font-size: 12px; font-weight: 700; letter-spacing: 0.06em; fill: #6366F1; }}
      .footer-text {{ font-size: 13px; font-weight: 500; fill: {COLOR_TEXT_FAINT}; }}
      .card-bg {{ fill: {COLOR_CARD_BG}; stroke: #E2E8F0; stroke-width: 1.5; rx: 16; }}
    </style>
    <filter id="card-shadow" x="-4%" y="-2%" width="108%" height="106%" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#0F172A" flood-opacity="0.05" />
    </filter>
  </defs>

  <!-- Background 16:9 Canvas -->
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="{COLOR_CANVAS_BG}" />

  <!-- Main Card Outer Frame -->
  <rect x="40" y="30" width="1840" height="1020" class="card-bg" filter="url(#card-shadow)" />

  <!-- Header Section -->
  <g transform="translate(80, 56)">
    <!-- Category Pill Badge -->
    <rect x="0" y="0" width="186" height="26" rx="13" fill="#EEF2FF" stroke="#6366F1" stroke-width="1" />
    <text x="12" y="17" class="badge-text">CODE WALKTHROUGH</text>

    <!-- Scene Title & Subtitle -->
    <text x="0" y="52" class="header-title">{title}</text>
    <text x="0" y="74" class="header-sub">{subtitle}</text>
  </g>

  <!-- Header Divider Rule -->
  <line x1="80" y1="140" x2="1840" y2="140" stroke="#F1F5F9" stroke-width="2" />

  <!-- LEFT COLUMN: Modern Dark IDE Code Editor Window -->
  <g id="ide_window">
    <!-- Window Body Background -->
    <rect x="{code_x}" y="{code_y}" width="{code_w}" height="{code_h}" rx="12" fill="#1E293B" stroke="#334155" stroke-width="1.5" />

    <!-- Window Titlebar -->
    <path d="M {code_x} {code_y + 12} A 12 12 0 0 1 {code_x + 12} {code_y} L {code_x + code_w - 12} {code_y} A 12 12 0 0 1 {code_x + code_w} {code_y + 12} L {code_x + code_w} {code_y + 44} L {code_x} {code_y + 44} Z" fill="#0F172A" />

    <!-- macOS Control Dots -->
    <circle cx="{code_x + 24}" cy="{code_y + 22}" r="6" fill="#EF4444" />
    <circle cx="{code_x + 44}" cy="{code_y + 22}" r="6" fill="#F59E0B" />
    <circle cx="{code_x + 64}" cy="{code_y + 22}" r="6" fill="#10B981" />

    <!-- Active File Tab -->
    <rect x="{code_x + 95}" y="{code_y + 8}" width="{max(len(clean_file) * 9 + 48, 180)}" height="28" rx="6" fill="#1E293B" stroke="#334155" stroke-width="1" />
    <text x="{code_x + 115}" y="{code_y + 26}" font-family="JetBrains Mono, Fira Code, Menlo, Consolas, monospace" font-size="13" font-weight="500" fill="#F8FAFC">{clean_file}</text>

    <!-- Language Pill -->
    <rect x="{code_x + code_w - 95}" y="{code_y + 10}" width="75" height="24" rx="4" fill="#334155" />
    <text x="{code_x + code_w - 58}" y="{code_y + 26}" font-family="JetBrains Mono, monospace" font-size="11" font-weight="600" fill="#94A3B8" text-anchor="middle">{lang_label}</text>

    <!-- Gutter Separator Rule -->
    <line x1="{code_x + 60}" y1="{code_y + 44}" x2="{code_x + 60}" y2="{code_y + code_h}" stroke="#334155" stroke-width="1" />

    <!-- Code Rows with Highlight Bands and Tokens -->
{chr(10).join(code_rows)}
  </g>

  <!-- RIGHT COLUMN: Grounded Context & Annotations Panel -->
  <g id="explanation_panel" transform="translate({panel_x}, {panel_y})">
    <!-- Symbol Overview Card -->
    <rect width="{panel_w}" height="160" rx="12" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1.5" />
    <rect x="0" y="0" width="6" height="160" rx="3" fill="#6366F1" />

    <!-- Symbol Type Badge -->
    <rect x="24" y="20" width="90" height="22" rx="4" fill="#EEF2FF" />
    <text x="69" y="35" font-size="11" font-weight="700" fill="#4F46E5" text-anchor="middle">{symbol_type}</text>

    <!-- Symbol Signature -->
    <text x="24" y="68" font-family="JetBrains Mono, Fira Code, Consolas, monospace" font-size="15" font-weight="600" fill="#0F172A">{esc_sig}</text>

    <!-- Summary explanation -->
    <text x="24" y="105" font-size="14" font-weight="500" fill="#475569">{esc_summary[:70]}</text>
    {f'<text x="24" y="128" font-size="14" font-weight="500" fill="#64748B">{esc_summary[70:]}</text>' if len(esc_summary) > 70 else ''}

    {contract_markup}
    {''.join(annotation_items)}
  </g>

  <!-- Footer Divider Rule -->
  <line x1="80" y1="1000" x2="1840" y2="1000" stroke="#F1F5F9" stroke-width="1.5" />

  <!-- Footer Section -->
  <g transform="translate(80, 1024)">
    <text x="0" y="0" class="footer-text">{esc_footer_ev}</text>
    <text x="1760" y="0" text-anchor="end" class="footer-text">16:9 1080p • RepoGenie Code Walkthrough</text>
  </g>
</svg>"""


# Singleton generator instance
code_walkthrough_generator = CodeWalkthroughGenerator()
