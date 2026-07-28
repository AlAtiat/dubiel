"""Bridge selections -> gelanalyzer.analyze_lanes.

Builds the lane dicts + transform from an :class:`ImageEntry` and reports where
the overlay PNG landed.
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from ._engine import analyze_lanes, viz
from .state import ImageEntry


def _lanes(entry: ImageEntry) -> list[dict]:
    return [
        {"box": (ln.y0, ln.x0, ln.y1, ln.x1), "label": ln.label,
         "is_ladder": ln.is_ladder, "auto_bands": ln.auto_bands}
        for ln in entry.selection.lanes
    ]


def _manual_ladder(entry: ImageEntry) -> list[tuple[float, float]]:
    return [(p.y, p.kda) for p in entry.selection.ladder_points if p.kda is not None]


def validate(entry: ImageEntry) -> Optional[str]:
    """Boundary validation. Returns a user-facing error string, or None if OK.

    A ladder is optional; calibrate via a tagged ladder box + preset OR by
    typing kDa on >=2 manual ladder markers.
    """
    if not entry.path or not os.path.exists(entry.path):
        return f"File not found: {entry.path}"
    lanes = entry.selection.lanes
    if not lanes:
        return "Draw at least one box before analyzing."
    if len([ln for ln in lanes if ln.is_ladder]) > 1:
        return "Only one box can be the ladder."
    return None


def run_entry(entry: ImageEntry, outdir: str, max_dim: int = 2000,
              ylabel: str = "") -> pd.DataFrame:
    """Analyze one image + render its montage / profiles / 3D surfaces to outdir."""
    # A typed manual ladder (>=2 markers with kDa) always overrides; otherwise
    # calibrate from the tagged ladder box (preset). Either can be absent.
    manual = _manual_ladder(entry)
    manual = manual if len(manual) >= 2 else None
    ladder = None
    if manual is None and entry.ladder_name \
            and any(ln.is_ladder for ln in entry.selection.lanes):
        ladder = entry.ladder_name
    lanes = _lanes(entry)
    df = analyze_lanes(
        entry.path, lanes=lanes, ladder=ladder, manual_ladder=manual,
        transform=entry.selection.transform,
        gel_label=entry.protein_label or None, outdir=outdir, max_dim=max_dim)

    fit = df.attrs.get("mw_fit")
    predict = ((lambda y: 10 ** (fit["slope"] * y + fit["intercept"])) if fit
               else None)
    name = os.path.splitext(os.path.basename(entry.path))[0]
    try:  # visuals must never block the numbers
        viz.render_entry(entry.path, lanes=lanes,
                         transform=entry.selection.transform, mw_predict=predict,
                         outdir=outdir, name=name,
                         title_label=entry.protein_label or "", max_dim=max_dim)
        viz.gel_trend(df, out_path=os.path.join(outdir, f"{name}_trend.png"),
                      ylabel=ylabel)
        from .gelanalyzer import correlate
        correlate.gel_correlation(entry, os.path.join(outdir, f"{name}_corr.png"))
    except Exception:
        pass
    return df
