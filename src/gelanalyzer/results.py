"""Band integration, labeled results table, annotated overlay, plots, export."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
from scipy.signal import peak_widths

from .detect import GelBox, Lane


# -----------------------------------------------------------------------------
# integration
# -----------------------------------------------------------------------------
def integrate_band(profile: np.ndarray, peak: int, rel_height: float = 0.9) -> float:
    """Integrated intensity of one band with a local linear baseline.

    Uses peak_widths to find where the peak meets the background, draws a
    straight baseline between those points, and sums the signal above it.
    """
    if not (0 <= peak < len(profile)):
        return 0.0
    _, _, lips, rips = peak_widths(profile, [peak], rel_height=rel_height)
    lo = max(int(np.floor(lips[0])), 0)
    hi = min(int(np.ceil(rips[0])) + 1, len(profile))
    if hi - lo < 2:
        return 0.0
    seg = profile[lo:hi]
    baseline = np.linspace(seg[0], seg[-1], len(seg))
    return float(np.clip(seg - baseline, 0, None).sum())


def quantify_gel(gel_signal, lanes: list[Lane], *, image: str, gel_label: str,
                 lane_labels=None, mw_predict=None) -> list[dict]:
    """Build labeled result rows for one gel/membrane.

    migration is measured in pixels from the top of the gel crop (the well end),
    which is what the MW calibration expects.
    """
    rows: list[dict] = []
    for li, lane in enumerate(lanes):
        lane_label = (lane_labels[li] if lane_labels and li < len(lane_labels)
                      else f"lane{li + 1}")
        areas = [integrate_band(lane.profile, b) for b in lane.bands]
        lane_total = sum(areas) or 1.0
        for bi, (band_y, area) in enumerate(zip(lane.bands, areas)):
            rows.append({
                "image": image,
                "gel_label": gel_label,
                "lane_label": lane_label,
                "band_idx": bi + 1,
                "y_px": int(band_y),
                "migration_px": int(band_y),
                "mw_kda": (round(float(mw_predict(band_y)), 2)
                           if mw_predict is not None else np.nan),
                "raw_intensity": round(area, 2),
                "lane_total": round(lane_total, 2),
                "pct_of_lane": round(area / lane_total * 100, 2),
            })
    return rows


# -----------------------------------------------------------------------------
# outputs
# -----------------------------------------------------------------------------
def annotate(rgb, gels: list[tuple[GelBox, list[Lane]]], gel_labels,
             lane_labels_per_gel=None, out_path=None):
    """Draw gel boxes, lane centers and detected bands with labels on the image."""
    from matplotlib.patches import Rectangle

    from ._plot import figure

    fig = figure(figsize=(12, 9))
    ax = fig.subplots()
    ax.imshow(rgb)
    ax.axis("off")
    for gi, (box, lanes) in enumerate(gels):
        glabel = gel_labels[gi] if gi < len(gel_labels) else f"gel{gi + 1}"
        ax.add_patch(Rectangle((box.x0, box.y0), box.width, box.height,
                               fill=False, color="red", lw=2))
        ax.text(box.x0, box.y0 - 8, glabel, color="red", fontsize=11, weight="bold")
        llabels = (lane_labels_per_gel[gi]
                   if lane_labels_per_gel and gi < len(lane_labels_per_gel) else None)
        for li, lane in enumerate(lanes):
            cx = box.x0 + lane.center
            ax.axvline(cx, box.y0 / rgb.shape[0], box.y1 / rgb.shape[0],
                       color="deepskyblue", lw=0.6, alpha=0.7)
            name = llabels[li] if llabels and li < len(llabels) else f"L{li + 1}"
            ax.text(cx, box.y1 + 12, str(name), color="deepskyblue",
                    fontsize=7, rotation=90, ha="center", va="top")
            for b in lane.bands:
                ax.plot(cx, box.y0 + b, "y_", markersize=8, markeredgewidth=1.5)
    fig.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


def plot_intensities(df: pd.DataFrame, out_path=None):
    """Per-gel grouped bar chart of band intensity by lane."""
    from ._plot import figure

    gels = df["gel_label"].unique()
    fig = figure(figsize=(5 * len(gels), 4))
    axes = fig.subplots(1, len(gels), squeeze=False)
    for ax, glabel in zip(axes[0], gels):
        sub = df[df["gel_label"] == glabel]
        for _, lane_df in sub.groupby("lane_label"):
            ax.bar(lane_df["lane_label"].astype(str) + "." + lane_df["band_idx"].astype(str),
                   lane_df["raw_intensity"])
        ax.set_title(glabel)
        ax.set_ylabel("intensity")
        ax.tick_params(axis="x", rotation=90, labelsize=6)
    fig.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


def export(df: pd.DataFrame, outdir: str, name: str) -> dict:
    """Write CSV + JSON, return the file paths."""
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, f"{name}.csv")
    json_path = os.path.join(outdir, f"{name}.json")
    df.to_csv(csv_path, index=False)
    with open(json_path, "w") as fh:
        json.dump(df.to_dict(orient="records"), fh, indent=2)
    return {"csv": csv_path, "json": json_path}
