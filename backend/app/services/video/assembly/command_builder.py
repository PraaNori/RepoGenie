"""
FFmpeg Command Builder (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .schemas import VideoRenderConfiguration

logger = logging.getLogger(__name__)


class FFmpegCommandBuilder:
    """Builds secure, validated argument lists for FFmpeg subprocess execution."""

    def __init__(self, ffmpeg_executable: str = "ffmpeg"):
        self.ffmpeg_executable = ffmpeg_executable

    def build_version_command(self) -> List[str]:
        return [self.ffmpeg_executable, "-version"]

    def build_encoders_command(self) -> List[str]:
        return [self.ffmpeg_executable, "-encoders"]

    def build_scene_render_command(
        self,
        image_path: Path,
        audio_path: Optional[Path],
        output_path: Path,
        duration_seconds: float,
        config: VideoRenderConfiguration,
        is_silent: bool = False,
    ) -> List[str]:
        """
        Builds the argument array to render a single scene MP4 segment.
        - For narrated scenes: includes audio stream, encodes with AAC 44.1 kHz.
        - For silent scenes: uses -an to generate a valid video-only MP4 segment without inventing audio.
        """
        cmd: List[str] = [
            self.ffmpeg_executable,
            "-y",  # Overwrite output
            "-loglevel", "error",
            "-loop", "1",
            "-i", str(image_path.resolve()),
        ]

        has_audio = (not is_silent) and audio_path is not None
        if has_audio:
            cmd.extend(["-i", str(audio_path.resolve())])

        # Video filters: scale to exact dimensions with padding/letterboxing if necessary
        # Force exact resolution and even width/height
        scale_filter = (
            f"scale={config.resolution_width}:{config.resolution_height}:force_original_aspect_ratio=decrease,"
            f"pad={config.resolution_width}:{config.resolution_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1"
        )

        cmd.extend([
            "-vf", scale_filter,
            "-c:v", config.video_codec,
            "-tune", "stillimage",
            "-pix_fmt", config.pixel_format,
            "-r", str(config.fps),
        ])

        if config.crf is not None and config.video_codec in ("libx264", "libx265"):
            cmd.extend(["-crf", str(config.crf)])
        if config.preset:
            cmd.extend(["-preset", config.preset])
        if config.video_bitrate:
            cmd.extend(["-b:v", config.video_bitrate])

        if has_audio:
            cmd.extend([
                "-c:a", config.audio_codec,
                "-b:a", config.audio_bitrate,
                "-ar", str(config.audio_sample_rate),
                "-ac", str(config.audio_channels),
                "-t", f"{duration_seconds:.3f}",
                "-shortest",
            ])
        else:
            # Video-only MP4 for silent scenes
            cmd.extend([
                "-an",
                "-t", f"{duration_seconds:.3f}",
            ])

        if config.faststart and config.container_format == "mp4":
            cmd.extend(["-movflags", "+faststart"])

        cmd.append(str(output_path.resolve()))
        return cmd

    @staticmethod
    def escape_concat_path(path_str: str) -> str:
        """
        Escapes a path for the FFmpeg concat demuxer format.
        Inside single quotes:
        1. Backslash '\\' becomes '\\\\'
        2. Single quote '\\'' becomes "'\\\\''"
        Prohibits raw newlines, carriage returns, and null bytes to prevent directive injection.
        """
        if any(c in path_str for c in ("\x00", "\r", "\n")):
            raise ValueError("File path in concat manifest cannot contain newlines or null bytes")
        escaped = path_str.replace("\\", "\\\\").replace("'", "'\\''")
        return f"file '{escaped}'"

    def format_concat_manifest_line(self, file_path: Path) -> str:
        """Formats a single line for the concat demuxer manifest file."""
        return self.escape_concat_path(str(file_path.resolve())) + "\n"

    def escape_subtitles_filter_path(self, file_path: Path) -> str:
        """
        Escapes a file path for the FFmpeg 'subtitles' video filter argument.
        Inside FFmpeg filter parameters, backslashes are normalized to forward slashes,
        and colons must be escaped (\\:) so they are not parsed as option separators.
        """
        resolved_path = str(file_path.resolve())
        if any(c in resolved_path for c in ("\x00", "\r", "\n")):
            raise ValueError("File path in subtitles filter cannot contain newlines or null bytes")
        escaped = resolved_path.replace("\\", "/").replace(":", "\\:")
        return escaped

    def build_subtitles_filter_string(
        self,
        srt_path: Path,
        style: Optional[str] = None,
    ) -> str:
        """
        Builds the FFmpeg video filter expression for burning subtitles into video frames.
        Styles subtitles for 1920x1080 video:
        - Font size scaled to ~36-38px height (FontSize=10 in libass 288p script resolution).
        - Maximum 2 lines with natural balanced line wrapping (WrapStyle=0).
        - Width limited to ~80% video width (MarginL=50, MarginR=50).
        - Positioned bottom center with a 55-65px safe margin (Alignment=2, MarginV=16).
        - Crisp white text with a subtle dark outline and shadow (PrimaryColour=&H00FFFFFF, Outline=1.2, Shadow=0.5).
        - Transparent background avoiding large opaque boxes (BorderStyle=1, BackColour=&H00000000).
        """
        escaped_path = self.escape_subtitles_filter_path(srt_path)
        default_style = (
            "FontName=Helvetica,FontSize=10,Bold=1,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
            "BorderStyle=1,Outline=1.2,Shadow=0.5,Alignment=2,"
            "MarginV=16,MarginL=50,MarginR=50,Spacing=0.2,WrapStyle=0"
        )
        chosen_style = style or default_style
        return f"subtitles=filename='{escaped_path}':force_style='{chosen_style}'"

    def build_concat_command(
        self,
        concat_list_file: Path,
        output_path: Path,
        config: VideoRenderConfiguration,
        subtitles_file: Optional[Path] = None,
        subtitles_style: Optional[str] = None,
    ) -> List[str]:
        """
        Builds the argument array to concatenate pre-rendered scene segments using the concat demuxer.
        If subtitles_file is provided and exists, burns in subtitles using libass and re-encodes
        video to preserve H.264/AAC at 1920x1080 30fps. Otherwise, performs fast stream-copy.
        """
        cmd: List[str] = [
            self.ffmpeg_executable,
            "-y",
            "-loglevel", "error",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file.resolve()),
        ]

        if subtitles_file and subtitles_file.is_file() and subtitles_file.stat().st_size > 0:
            vf = self.build_subtitles_filter_string(subtitles_file, style=subtitles_style)
            cmd.extend([
                "-vf", vf,
                "-c:v", config.video_codec,
                "-preset", config.preset,
                "-pix_fmt", config.pixel_format,
                "-r", str(config.fps),
                "-c:a", "copy",
            ])
            if config.crf is not None:
                cmd.extend(["-crf", str(config.crf)])
        else:
            cmd.extend(["-c", "copy"])

        if config.faststart and config.container_format == "mp4":
            cmd.extend(["-movflags", "+faststart"])

        cmd.append(str(output_path.resolve()))
        return cmd

    def build_silent_audio_normalization_command(
        self,
        scene_path: Path,
        output_path: Path,
        duration_seconds: float,
        config: VideoRenderConfiguration,
    ) -> List[str]:
        """
        Generates a silent AAC audio track for a silent scene clip so that all scenes
        in a mixed storyboard share the exact same stream layout (video + audio) for concat demuxer.
        Copies the video stream without re-encoding (-c:v copy).
        """
        cmd: List[str] = [
            self.ffmpeg_executable,
            "-y",
            "-loglevel", "error",
            "-i", str(scene_path.resolve()),
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={config.audio_sample_rate}",
            "-c:v", "copy",
            "-c:a", config.audio_codec,
            "-b:a", config.audio_bitrate,
            "-shortest",
            str(output_path.resolve()),
        ]
        return cmd

    def build_synthetic_color_video_command(
        self,
        output_path: Path,
        duration_seconds: float = 2.0,
        config: Optional[VideoRenderConfiguration] = None,
    ) -> List[str]:
        """
        Builds a self-contained synthetic media generation command (color video test source + test tone)
        for local smoke testing without external files or API dependencies.
        """
        cfg = config or VideoRenderConfiguration()
        cmd: List[str] = [
            self.ffmpeg_executable,
            "-y",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c=navy:s={cfg.resolution_width}x{cfg.resolution_height}:r={cfg.fps}:d={duration_seconds:.2f}",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:sample_rate={cfg.audio_sample_rate}:duration={duration_seconds:.2f}",
            "-c:v", cfg.video_codec,
            "-pix_fmt", cfg.pixel_format,
            "-c:a", cfg.audio_codec,
            "-b:a", cfg.audio_bitrate,
            "-t", f"{duration_seconds:.2f}",
        ]
        if cfg.faststart and cfg.container_format == "mp4":
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(output_path.resolve()))
        return cmd


command_builder = FFmpegCommandBuilder()
