"""
Deterministic Caption Segmentation and Proportional Timing (Milestone 5, Phase 5.5).

Splits verbatim narration text into readable, natural phrase chunks along punctuation
and syntactic boundaries without altering spoken wording.
Allocates timing proportionally using measured scene audio duration, character/word weights,
and punctuation-aware pause heuristics.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .formatter import (
    seconds_to_srt_timestamp,
    seconds_to_vtt_timestamp,
)
from .schemas import (
    Caption,
    TimingProvenance,
)

# Target constraints for educational video readability (1080p landscape)
MAX_WORDS_PER_CUE = 10
MAX_CHARS_PER_CUE = 55
MIN_CUE_DURATION_SECONDS = 0.8
INTER_CUE_GAP_SECONDS = 0.04  # 40ms visual separation between subtitles

# Punctuation regexes
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:—])\s+|(?<=\s-\s)")
CONJUNCTION_SPLIT_RE = re.compile(r"\s+(?=(?:and|but|or|which|that|because|when|where|while|with|from)\b)", re.IGNORECASE)


def split_text_into_cues(narration_text: str) -> List[str]:
    """
    Splits narration text into clean, readable subtitle cues.
    Preserves exact verbatim words; never paraphrases or summarizes.
    """
    clean_text = narration_text.strip()
    if not clean_text:
        return []

    # 1. First split into sentences
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(clean_text) if s.strip()]
    if not sentences:
        sentences = [clean_text]

    cues: List[str] = []

    for sentence in sentences:
        words = sentence.split()
        if len(words) <= MAX_WORDS_PER_CUE and len(sentence) <= MAX_CHARS_PER_CUE:
            cues.append(sentence)
            continue

        # 2. Split long sentences on clauses (commas, semicolons, dashes)
        clauses = [c.strip() for c in CLAUSE_SPLIT_RE.split(sentence) if c.strip()]
        if len(clauses) > 1:
            current_chunk: List[str] = []
            for clause in clauses:
                test_str = " ".join(current_chunk + [clause])
                if len(test_str.split()) <= MAX_WORDS_PER_CUE and len(test_str) <= MAX_CHARS_PER_CUE:
                    current_chunk.append(clause)
                else:
                    if current_chunk:
                        cues.append(" ".join(current_chunk))
                    current_chunk = [clause]
            if current_chunk:
                cues.append(" ".join(current_chunk))
            continue

        # 3. Fallback: split long sentence by conjunctions or mid-phrase word boundaries
        conjunction_parts = [p.strip() for p in CONJUNCTION_SPLIT_RE.split(sentence) if p.strip()]
        if len(conjunction_parts) > 1:
            current_chunk = []
            for part in conjunction_parts:
                test_str = " ".join(current_chunk + [part])
                if len(test_str.split()) <= MAX_WORDS_PER_CUE and len(test_str) <= MAX_CHARS_PER_CUE:
                    current_chunk.append(part)
                else:
                    if current_chunk:
                        cues.append(" ".join(current_chunk))
                    current_chunk = [part]
            if current_chunk:
                cues.append(" ".join(current_chunk))
            continue

        # 4. Strict word-boundary chunking if still oversized
        chunk_words: List[str] = []
        for word in words:
            chunk_words.append(word)
            if len(chunk_words) >= MAX_WORDS_PER_CUE or len(" ".join(chunk_words)) >= MAX_CHARS_PER_CUE:
                cues.append(" ".join(chunk_words))
                chunk_words = []
        if chunk_words:
            cues.append(" ".join(chunk_words))

    # Remove any empty or whitespace cues
    return [c.strip() for c in cues if c.strip()]


def calculate_cue_weight(cue_text: str) -> float:
    """
    Computes proportional timing weight for a cue based on word count,
    character count, and terminal punctuation pause weight.
    """
    words = cue_text.split()
    word_count = len(words)
    char_count = len(cue_text)

    # Base weight combines word count with character count for syllable weighting
    weight = (word_count * 1.0) + (char_count * 0.05)

    # Pause weight for punctuation
    clean = cue_text.strip()
    if clean.endswith((".", "!", "?")):
        weight += 0.4
    elif clean.endswith((",", ";", ":", "-", "—")):
        weight += 0.2

    return max(weight, 0.5)


def generate_scene_captions(
    scene_id: str,
    narration_text: str,
    audio_duration_seconds: float,
    timing_provenance: TimingProvenance = TimingProvenance.ESTIMATED,
    cumulative_offset_seconds: float = 0.0,
) -> List[Caption]:
    """
    Produces timed Caption objects for a scene by segmenting text and distributing
    the measured audio duration proportionally across all cues.
    
    Timestamps in the returned Captions are relative to the scene (start_seconds starting at 0.0).
    """
    if not narration_text or not narration_text.strip():
        return []

    cues = split_text_into_cues(narration_text)
    if not cues:
        return []

    duration = max(audio_duration_seconds, 0.5)
    num_cues = len(cues)

    # Calculate weights
    weights = [calculate_cue_weight(c) for c in cues]
    total_weight = sum(weights)

    # Determine lead-in and inter-cue separation
    lead_in = 0.05 if duration >= 1.0 else 0.0
    total_gaps = (num_cues - 1) * INTER_CUE_GAP_SECONDS if num_cues > 1 else 0.0

    # Ensure active spoken time fits within measured duration
    available_time = duration - lead_in - total_gaps
    if available_time <= 0.2:
        # Fallback for very short clips: eliminate gaps and lead-in
        lead_in = 0.0
        total_gaps = 0.0
        gap_sec = 0.0
        available_time = duration
    else:
        gap_sec = INTER_CUE_GAP_SECONDS

    # Allocate time per cue
    captions: List[Caption] = []
    current_time = lead_in

    for idx, (cue_text, weight) in enumerate(zip(cues, weights)):
        seq = idx + 1
        cue_duration = (weight / total_weight) * available_time

        # Ensure cue duration is reasonable
        cue_duration = max(cue_duration, 0.2)
        start_sec = round(current_time, 3)
        end_sec = round(start_sec + cue_duration, 3)

        # Clamp final cue so it does not exceed measured scene audio duration
        if idx == num_cues - 1:
            end_sec = min(end_sec, round(duration, 3))
            if end_sec <= start_sec:
                end_sec = round(start_sec + 0.2, 3)

        # Generate clean SRT and VTT timestamps
        start_srt = seconds_to_srt_timestamp(start_sec)
        end_srt = seconds_to_srt_timestamp(end_sec)
        start_vtt = seconds_to_vtt_timestamp(start_sec)
        end_vtt = seconds_to_vtt_timestamp(end_sec)

        caption_id = f"cap_{scene_id}_{seq}"
        safe_caption_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", caption_id)

        captions.append(
            Caption(
                caption_id=safe_caption_id,
                scene_id=scene_id,
                sequence_number=seq,
                start_seconds=start_sec,
                end_seconds=end_sec,
                start_timestamp_srt=start_srt,
                end_timestamp_srt=end_srt,
                start_timestamp_vtt=start_vtt,
                end_timestamp_vtt=end_vtt,
                text=cue_text,
                timing_provenance=timing_provenance,
            )
        )

        current_time = end_sec + gap_sec

    return captions
