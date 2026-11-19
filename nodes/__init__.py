"""Node package exports."""

from __future__ import annotations

from .dsh_video_agent import DSH_FullVideoAgent
from .dsh_video_stages import DSH_VideoSegments, DSH_VideoReverse

NODE_CLASS_MAPPINGS = {"DSH_FullVideoAgent": DSH_FullVideoAgent,
    "DSH_VideoSegments": DSH_VideoSegments, "DSH_VideoReverse": DSH_VideoReverse}
NODE_DISPLAY_NAME_MAPPINGS = {name: cls.define_schema().display_name for name, cls in NODE_CLASS_MAPPINGS.items()}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
