"""gelanalyzer - automatic SDS-PAGE / Western-blot quantification from photos.

Two entry points:

    analyze_sds(path, ...)      auto-detect gels + lanes + bands, integrate,
                                export labeled results. Manual override optional.

    analyze_western(path, ...)  click marker bands + bands of interest; get
                                molecular weights (from a preset/custom ladder)
                                plus intensities, labeled and exported.

Both run headless if you pass coordinates instead of clicking.
"""
from __future__ import annotations

import os

# Pin matplotlib to the headless Agg backend before it is imported (interactive.py
# imports pyplot, which otherwise picks a GUI backend at import time — a portability
# risk in the packaged app). Every figure the app renders uses _plot.figure (Agg).
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import pandas as pd

from . import interactive, results
from .detect import (
    GelBox, band_signal, build_lanes, detect_bands, detect_gels, detect_lanes,
    lane_profile, load_image,
)
from .ladder import LADDER_LABELS, LADDERS, fit_mw, resolve_ladder
from .lanes import Transform, analyze_lanes

__all__ = ["analyze_sds", "analyze_western", "analyze_lanes", "Transform",
           "LADDERS", "LADDER_LABELS", "GelBox"]


def _basename(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def analyze_sds(path: str, *, gel_labels=None, lane_labels=None,
                expected_lanes=None, boxes=None, interactive_boxes=False,
                outdir="results", max_dim=2000) -> pd.DataFrame:
    """Analyze an SDS-PAGE photo with (possibly several) gels.

    gel_labels     : names per gel, in reading order (top->bottom, left->right).
    lane_labels    : list-of-lists, well names per gel.
    expected_lanes : int or list[int] to pin the lane count per gel.
    boxes          : list[GelBox] to override auto gel detection.
    interactive_boxes : True -> drag boxes in a popup instead of auto-detecting.
    """
    rgb, gray = load_image(path, max_dim=max_dim)

    if boxes is None and interactive_boxes:
        boxes = interactive.pick_boxes(rgb)
    if boxes is None:
        boxes = detect_gels(gray)
    if not boxes:
        raise RuntimeError(
            "No gels detected. Pass boxes=... or interactive_boxes=True to draw them."
        )

    gel_labels = gel_labels or [f"gel{i + 1}" for i in range(len(boxes))]
    rows, gels_lanes = [], []
    for gi, box in enumerate(boxes):
        sig = band_signal(box.crop(gray))
        exp = expected_lanes[gi] if isinstance(expected_lanes, (list, tuple)) else expected_lanes
        lanes = build_lanes(sig, detect_lanes(sig, expected=exp))
        gels_lanes.append((box, lanes))
        rows += results.quantify_gel(
            sig, lanes, image=_basename(path),
            gel_label=gel_labels[gi] if gi < len(gel_labels) else f"gel{gi + 1}",
            lane_labels=lane_labels[gi] if lane_labels and gi < len(lane_labels) else None,
        )

    df = pd.DataFrame(rows)
    name = _basename(path)
    results.annotate(rgb, gels_lanes, gel_labels, lane_labels,
                     out_path=os.path.join(outdir, f"{name}_overlay.png"))
    if not df.empty:
        results.plot_intensities(df, out_path=os.path.join(outdir, f"{name}_intensity.png"))
        results.export(df, outdir, name)
    return df


def analyze_western(path: str, *, ladder, gel_labels=None, lane_labels=None,
                    marker_points=None, band_points=None, boxes=None,
                    interactive_boxes=False, outdir="results", max_dim=2000) -> pd.DataFrame:
    """Analyze a Western membrane: marker -> MW calibration + band intensities.

    ladder        : preset name (see LADDERS) or list of kDa values, top->bottom.
    marker_points : [(x,y), ...] clicks on the ladder bands (top->bottom). If
                    None and an interactive backend is available, you click them.
    band_points   : [(x,y), ...] clicks on the bands of interest. If None, you
                    click them; each gets an MW + intensity.

    Lane detection is auto per membrane; MW comes from the marker calibration,
    so bands are located by your clicks rather than by lane assignment.
    """
    kda = resolve_ladder(ladder)
    rgb, gray = load_image(path, max_dim=max_dim)

    if boxes is None and interactive_boxes:
        boxes = interactive.pick_boxes(rgb)
    if boxes is None:
        boxes = detect_gels(gray)
    gel_labels = gel_labels or [f"membrane{i + 1}" for i in range(len(boxes or [1]))]

    # --- marker calibration (migration measured from the top of the image) ---
    if marker_points is None:
        marker_points = interactive.pick_points(
            rgb, n=len(kda),
            title=f"Click the {len(kda)} ladder bands, heaviest (top) first")
    if len(marker_points) != len(kda):
        raise ValueError(
            f"Clicked {len(marker_points)} marker bands but ladder has {len(kda)}.")
    marker_y = [y for _, y in marker_points]
    predict, (slope, intercept, r2) = fit_mw(marker_y, kda)

    # --- bands of interest ---
    if band_points is None:
        band_points = interactive.pick_points(
            rgb, n=-1, title="Click each band of interest, then press Enter")

    rows = []
    name = _basename(path)
    for bx, by in band_points:
        gi = _which_gel(bx, by, boxes)
        glabel = gel_labels[gi] if gi is not None and gi < len(gel_labels) else "membrane?"
        intensity = _band_intensity_at(gray, bx, by)
        rows.append({
            "image": name, "gel_label": glabel,
            "band_x": int(bx), "band_y": int(by),
            "mw_kda": round(float(predict(by)), 2),
            "raw_intensity": round(intensity, 2),
        })

    df = pd.DataFrame(rows)
    df.attrs["mw_fit"] = {"slope": slope, "intercept": intercept, "r2": round(r2, 4)}

    _annotate_western(rgb, marker_points, kda, band_points, df, predict,
                      out_path=os.path.join(outdir, f"{name}_overlay.png"))
    if not df.empty:
        results.export(df, outdir, name)
    print(f"MW calibration r^2 = {r2:.4f}")
    return df


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------
def _which_gel(x, y, boxes):
    if not boxes:
        return None
    for i, b in enumerate(boxes):
        if b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1:
            return i
    return None


def _band_intensity_at(gray, x, y, half=18):
    """Integrated band signal in a small box around a click (background-flattened)."""
    sig = band_signal(gray)
    x, y = int(x), int(y)
    patch = sig[max(y - half, 0):y + half, max(x - half, 0):x + half]
    return float(patch.sum())


def _annotate_western(rgb, marker_points, kda, band_points, df, predict, out_path):
    import matplotlib
    prev = matplotlib.get_backend()
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 9))
    ax.imshow(rgb)
    ax.axis("off")
    for (x, y), k in zip(marker_points, kda):
        ax.plot(x, y, "c>", markersize=8)
        ax.text(x - 12, y, f"{k}", color="cyan", fontsize=8, ha="right", va="center")
    for (x, y) in band_points:
        ax.plot(x, y, "rx", markersize=9, markeredgewidth=2)
        ax.text(x + 8, y, f"{float(predict(y)):.0f} kDa", color="red", fontsize=8, va="center")
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    matplotlib.use(prev, force=True)
    return fig
