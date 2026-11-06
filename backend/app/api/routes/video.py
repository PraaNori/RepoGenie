"""
Video System API Endpoints (Milestone 6, Phase 6.1).
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query

from ...services.video.assembly import (
    VideoAssemblySystemStatus,
    video_assembly_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video", tags=["video"])


@router.get("/status", response_model=VideoAssemblySystemStatus)
def get_video_system_status(
    refresh: bool = Query(default=False, description="Force re-inspection of host FFmpeg binaries"),
):
    """
    Returns system-wide status regarding FFmpeg and FFprobe executable availability,
    parsed version information, and default rendering configuration.
    """
    return video_assembly_service.get_system_status(refresh=refresh)
