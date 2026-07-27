"""Re-exports from the bundled ``gelanalyzer`` engine.

``gelanalyzer`` is a top-level package that ships alongside ``dugiel`` under
``src/`` (see ``sources`` in pyproject), so it is always importable — in a dev
checkout and in the packaged app alike.
"""
from __future__ import annotations

import gelanalyzer
from gelanalyzer import (
    LADDER_LABELS,
    LADDERS,
    GelBox,
    Transform,
    analyze_lanes,
    analyze_sds,
    analyze_western,
)
from gelanalyzer import viz
from gelanalyzer.detect import band_signal, detect_gels, load_image
from gelanalyzer.lanes import apply_transform

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
