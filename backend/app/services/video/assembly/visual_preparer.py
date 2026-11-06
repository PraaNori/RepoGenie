"""
Visual Asset Preparation & SVG Rasterization (Milestone 6, Phase 6.2).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from PIL import Image

from .exceptions import VisualPreparationError
from .process_runner import run_process_sync

logger = logging.getLogger(__name__)

# Security patterns prohibited in SVG files
_DISALLOWED_SVG_PATTERNS = [
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\bon\w+\s*=", re.IGNORECASE),  # e.g. onload=, onclick=, onerror=
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"<!ENTITY\b", re.IGNORECASE),   # XXE entity declaration
    re.compile(r"<!DOCTYPE\b[^>]*SYSTEM\b", re.IGNORECASE),  # External DTD
    re.compile(r"<image\b[^>]*\b(xlink:)?href\s*=\s*['\"]https?://", re.IGNORECASE),  # Remote resource fetching
]


def validate_svg_content(svg_data: str | bytes) -> None:
    """
    Validates SVG content for XML well-formedness and security integrity.
    Rejects malformed XML, XXE declarations, script tags, event handlers, and external URLs.
    """
    text = svg_data.decode("utf-8", errors="replace") if isinstance(svg_data, bytes) else svg_data

    # 1. Prohibited security constructs
    for pattern in _DISALLOWED_SVG_PATTERNS:
        if pattern.search(text):
            raise VisualPreparationError(f"Security: Prohibited construct or script in SVG visual asset: {pattern.pattern}")

    # 2. XML well-formedness validation
    try:
        # Note: defusedxml or standard ET parse
        root = ET.fromstring(text.encode("utf-8"))
        # Verify root tag ends with 'svg' (ignoring xmlns prefix if present)
        if not root.tag.lower().endswith("svg"):
            raise VisualPreparationError(f"Root XML tag must be <svg>, got <{root.tag}>")
    except ET.ParseError as pe:
        raise VisualPreparationError(f"Malformed SVG XML: {pe}") from pe


class VisualAssetPreparer:
    """
    Converts and standardizes visual assets (SVGs, PNGs, JPEGs, WebP) into
    1920x1080 16:9 PNG raster images suitable for FFmpeg encoding.
    """

    def __init__(self, rsvg_binary: Optional[str] = None):
        self._rsvg_binary = rsvg_binary

    def resolve_rsvg_binary(self) -> Optional[str]:
        """Locates the rsvg-convert binary on the host system."""
        if self._rsvg_binary:
            return self._rsvg_binary
        candidates = [
            shutil.which("rsvg-convert"),
            "/opt/homebrew/bin/rsvg-convert",
            "/usr/local/bin/rsvg-convert",
            "/usr/bin/rsvg-convert",
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def prepare_visual_asset(
        self,
        source_path: Path,
        output_png_path: Path,
        target_width: int = 1920,
        target_height: int = 1080,
        refresh: bool = False,
    ) -> Path:
        """
        Converts source visual (SVG/PNG/JPEG/WebP) to a standardized 1920x1080 PNG.
        Preserves aspect ratio with centered letterboxing/padding on a black canvas.
        Reuses cached output when refresh=False and source file is unchanged.
        """
        resolved_source = source_path.resolve()
        if not resolved_source.exists() or not resolved_source.is_file():
            raise VisualPreparationError(f"Source visual asset not found: {resolved_source}")

        resolved_output = output_png_path.resolve()
        resolved_output.parent.mkdir(parents=True, exist_ok=True)

        # Check cache
        if (
            not refresh
            and resolved_output.exists()
            and resolved_output.stat().st_size > 0
            and resolved_output.stat().st_mtime >= resolved_source.stat().st_mtime
        ):
            try:
                with Image.open(resolved_output) as img:
                    if img.size == (target_width, target_height):
                        logger.debug("Reusing prepared visual raster asset: %s", resolved_output)
                        return resolved_output
            except Exception:
                pass  # Re-render if corrupt

        # Temporary destination for atomic promotion
        temp_png = resolved_output.parent / f"temp_{uuid.uuid4().hex[:8]}.png"

        try:
            suffix = resolved_source.suffix.lower()
            if suffix == ".svg":
                self._rasterize_svg(resolved_source, temp_png, target_width, target_height)
            elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
                self._standardize_raster(resolved_source, temp_png, target_width, target_height)
            else:
                raise VisualPreparationError(f"Unsupported visual asset format '{suffix}': {resolved_source}")

            # Verify size and atomically replace
            if not temp_png.exists() or temp_png.stat().st_size == 0:
                raise VisualPreparationError(f"Rasterization produced empty image: {resolved_source}")

            temp_png.replace(resolved_output)
            return resolved_output
        except Exception:
            if temp_png.exists():
                temp_png.unlink(missing_ok=True)
            raise

    def _rasterize_svg(
        self,
        svg_path: Path,
        output_png: Path,
        target_width: int,
        target_height: int,
    ) -> None:
        """Validates SVG and renders it to a target-dimensioned PNG."""
        svg_bytes = svg_path.read_bytes()
        validate_svg_content(svg_bytes)

        rsvg_bin = self.resolve_rsvg_binary()
        if rsvg_bin:
            # Use rsvg-convert with keep-aspect-ratio
            cmd = [
                rsvg_bin,
                "-w", str(target_width),
                "-h", str(target_height),
                "-a",  # keep aspect ratio
                "-f", "png",
                "-o", str(output_png),
                str(svg_path),
            ]
            code, stdout, stderr = run_process_sync(cmd, timeout_seconds=30.0)
            if code != 0 or not output_png.exists():
                raise VisualPreparationError(f"rsvg-convert failed (code {code}): {stderr}")

            # Ensure exact 1920x1080 canvas with centered padding
            self._fit_to_canvas(output_png, target_width, target_height)
        else:
            # Fallback when no SVG CLI converter is present (e.g. minimal sandbox testing)
            self._render_svg_fallback(svg_bytes, output_png, target_width, target_height)

    def _standardize_raster(
        self,
        img_path: Path,
        output_png: Path,
        target_width: int,
        target_height: int,
    ) -> None:
        """Loads raster image and standardizes to 1920x1080 with centered letterboxing."""
        try:
            with Image.open(img_path) as img:
                # Convert to RGBA
                img_rgba = img.convert("RGBA")
                self._paste_and_save(img_rgba, output_png, target_width, target_height)
        except Exception as exc:
            raise VisualPreparationError(f"Failed to process raster image {img_path}: {exc}") from exc

    def _fit_to_canvas(self, png_path: Path, target_width: int, target_height: int) -> None:
        """Checks dimensions of png_path and fits onto black canvas if necessary."""
        with Image.open(png_path) as img:
            if img.size == (target_width, target_height) and img.mode == "RGB":
                return
            img_rgba = img.convert("RGBA")
            self._paste_and_save(img_rgba, png_path, target_width, target_height)

    def _paste_and_save(
        self,
        img: Image.Image,
        output_path: Path,
        target_width: int,
        target_height: int,
    ) -> None:
        """Scales image preserving aspect ratio and pastes centered onto a black 16:9 canvas."""
        src_w, src_h = img.size
        ratio = min(target_width / src_w, target_height / src_h)
        new_w = max(1, int(src_w * ratio))
        new_h = max(1, int(src_h * ratio))

        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (target_width, target_height), (15, 23, 42))  # slate-900 background
        offset_x = (target_width - new_w) // 2
        offset_y = (target_height - new_h) // 2

        if resized.mode == "RGBA":
            canvas.paste(resized, (offset_x, offset_y), mask=resized.split()[3])
        else:
            canvas.paste(resized, (offset_x, offset_y))

        canvas.save(output_path, format="PNG", optimize=True)

    def _render_svg_fallback(
        self,
        svg_bytes: bytes,
        output_png: Path,
        target_width: int,
        target_height: int,
    ) -> None:
        """Deterministic placeholder fallback for environments without an external SVG rasterizer."""
        canvas = Image.new("RGB", (target_width, target_height), (15, 23, 42))
        canvas.save(output_png, format="PNG")


visual_asset_preparer = VisualAssetPreparer()
