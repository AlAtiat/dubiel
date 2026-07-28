"""Re-exports from the bundled ``gelanalyzer`` engine.

``gelanalyzer`` is bundled *inside* the ``dugiel`` package
(``src/dugiel/gelanalyzer``), so the app ships as one self-contained package and
the engine is always importable — in a dev checkout and in the packaged app alike.
"""
from __future__ import annotations

from . import gelanalyzer
from .gelanalyzer import (
    LADDER_LABELS,
    LADDERS,
    GelBox,
    Transform,
    analyze_lanes,
    analyze_sds,
    analyze_western,
)
from .gelanalyzer import viz
from .gelanalyzer.detect import band_signal, detect_gels, load_image
from .gelanalyzer.lanes import apply_transform

__all__ = [
    "gelanalyzer",
    "LADDERS",
    "LADDER_LABELS",
    "GelBox",
    "Transform",
    "analyze_lanes",
    "analyze_sds",
    "analyze_western",
    "apply_transform",
    "viz",
    "band_signal",
    "detect_gels",
    "load_image",
]
