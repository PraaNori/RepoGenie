"""
Caption Formatting and Standards Validation (Milestone 5, Phase 5.5).

Produces standards-compliant SubRip (.srt) and WebVTT (.vtt) file content,
formats timestamps with exact millisecond precision, handles Unicode and special
characters, and validates syntactic correctness before disk persistence.
"""

from __future__ import annotations

import math
import re
from typing import List, Tuple

# SRT timestamp regex: 00:00:00,000 --> 00:00:00,000
SRT_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})$")
# VTT timestamp regex: 00:00:00.000 --> 00:00:00.000 (also allows 00:00.000)
VTT_TIME_RE = re.compile(r"^(\d{2}:)?(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d{2}:)?(\d{2}):(\d{2})\.(\d{3})")


def seconds_to_srt_timestamp(seconds: float) -> str:
    """
    Converts floating-point seconds into SRT timestamp string: HH:MM:SS,mmm
    Example: 74.321 -> '00:01:14,321'
    """
    if seconds < 0:
        seconds = 0.0
    
    total_millis = int(round(seconds * 1000.0))
    millis = total_millis % 1000
    total_seconds = total_millis // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def seconds_to_vtt_timestamp(seconds: float) -> str:
    """
    Converts floating-point seconds into WebVTT timestamp string: HH:MM:SS.mmm
    Example: 74.321 -> '00:01:14.321'
    """
    if seconds < 0:
        seconds = 0.0
    
    total_millis = int(round(seconds * 1000.0))
    millis = total_millis % 1000
    total_seconds = total_millis // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60

    return f"{hours:02d}:{mins:02d}:{secs:02d}.{millis:03d}"


def format_srt_cues(cues: List[Tuple[float, float, str]], start_index: int = 1) -> str:
    """
    Formats a list of (start_seconds, end_seconds, text) tuples into standard SubRip (SRT) format.
    Blank lines separate cues; indices are strictly consecutive.
    """
    if not cues:
        return ""

    blocks: List[str] = []
    for idx, (start_sec, end_sec, text) in enumerate(cues):
        seq = start_index + idx
        start_ts = seconds_to_srt_timestamp(start_sec)
        end_ts = seconds_to_srt_timestamp(end_sec)
        clean_text = text.strip()
        blocks.append(f"{seq}\n{start_ts} --> {end_ts}\n{clean_text}")

    return "\n\n".join(blocks) + "\n"


def format_vtt_cues(cues: List[Tuple[float, float, str]], header_title: str = "RepoGenie Captions") -> str:
    """
    Formats a list of (start_seconds, end_seconds, text) tuples into standard WebVTT (.vtt) format.
    Begins with WEBVTT signature header followed by blank line and cues.
    """
    header = f"WEBVTT - {header_title}\n\n"
    if not cues:
        return header

    blocks: List[str] = []
    for idx, (start_sec, end_sec, text) in enumerate(cues):
        start_ts = seconds_to_vtt_timestamp(start_sec)
        end_ts = seconds_to_vtt_timestamp(end_sec)
        clean_text = text.strip()
        blocks.append(f"{start_ts} --> {end_ts}\n{clean_text}")

    return header + "\n\n".join(blocks) + "\n"


def validate_srt_content(content: str) -> bool:
    """
    Validates that a string adheres strictly to SubRip (.srt) syntax.
    Returns True if valid, False otherwise.
    """
    if not content or not content.strip():
        return False

    blocks = content.strip().split("\n\n")
    expected_seq = 1

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3:
            return False

        # 1. Sequence number check
        try:
            seq = int(lines[0])
            if seq != expected_seq:
                return False
        except ValueError:
            return False

        # 2. Timestamp line check
        time_match = SRT_TIME_RE.match(lines[1])
        if not time_match:
            return False

        # 3. Text content check
        text_lines = lines[2:]
        if not any(tl for tl in text_lines):
            return False

        expected_seq += 1

    return True


def validate_vtt_content(content: str) -> bool:
    """
    Validates that a string adheres strictly to WebVTT (.vtt) syntax.
    Returns True if valid, False otherwise.
    """
    if not content or not content.strip():
        return False

    lines = content.splitlines()
    if not lines:
        return False

    # 1. Header signature
    if not lines[0].startswith("WEBVTT"):
        return False

    # If it only contains the header line and blank lines, it's a valid empty VTT file
    non_empty = [l.strip() for l in lines[1:] if l.strip()]
    if not non_empty:
        return True

    # Check that at least one valid timestamp cue exists
    has_valid_cue = False
    for line in non_empty:
        if "-->" in line:
            if VTT_TIME_RE.match(line):
                has_valid_cue = True
                break

    return has_valid_cue
