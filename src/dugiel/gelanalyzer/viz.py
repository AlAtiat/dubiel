"""Bio-Rad-style scientific visuals: cropped montage, lane-profile chromatograms,
3D intensity surfaces (before/after background), and cross-gel trend lines.

Everything recomputes from the image + marked boxes so it stays independent of
the app. All figures use the thread-safe ``_plot.figure`` (no pyplot).
"""
from __future__ import annotations

import os
from typing import Optional, Sequence

import numpy as np

from ._plot import figure
from .detect import band_signal, detect_bands, load_image, smooth_profile
from .lanes import Transform, apply_transform
from .results import integrate_band


def _load(path, transform, max_dim=2000):
    rgb, gray = load_image(path, max_dim)
    rgb, gray = apply_transform(rgb, gray, transform)
    return rgb, gray, band_signal(gray)


# -----------------------------------------------------------------------------
# cropped montage: marked bands / lanes side by side, labeled with kDa
# -----------------------------------------------------------------------------
def band_montage(rgb, items: Sequence[dict], out_path: Optional[str] = None):
    """items: [{"box": (y0,x0,y1,x1), "label": str}]. Crops tiled left->right."""
    items = list(items)
    if not items:
        return None
    fig = figure(figsize=(max(4, 1.6 * len(items)), 3))
    axes = fig.subplots(1, len(items), squeeze=False)[0]
    for ax, it in zip(axes, items):
        y0, x0, y1, x1 = it["box"]
        ax.imshow(rgb[y0:y1, x0:x1])
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(it.get("label", ""), fontsize=8)
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# lane-profile chromatograms (intensity vs Rf, bands filled, baseline drawn)
# -----------------------------------------------------------------------------
def lane_profiles(sig, lanes: Sequence[dict], out_path: Optional[str] = None):
    """One panel per lane: profile vs Rf, detected bands filled, baseline line."""
    from scipy.signal import peak_widths

    lanes = [ln for ln in lanes if not ln.get("is_ladder")] or list(lanes)
    if not lanes:
        return None
    fig = figure(figsize=(5, 2.2 * len(lanes)))
    axes = fig.subplots(len(lanes), 1, squeeze=False)[:, 0]
    for ax, ln in zip(axes, lanes):
        y0, x0, y1, x1 = [int(v) for v in ln["box"]]
        prof = smooth_profile(sig[y0:y1, x0:x1].mean(axis=1))
        rf = np.linspace(0, 1, len(prof))
        ax.plot(rf, prof, color="firebrick", lw=1)
        bands = detect_bands(prof)
        for b in bands:  # fill each band above its local baseline
            _, _, lip, rip = peak_widths(prof, [b], rel_height=0.9)
            lo, hi = max(int(lip[0]), 0), min(int(rip[0]) + 1, len(prof))
            base = np.linspace(prof[lo], prof[hi - 1], hi - lo)
            ax.fill_between(rf[lo:hi], base, prof[lo:hi],
                            where=prof[lo:hi] > base, color="limegreen", alpha=0.8)
        ax.set_ylabel(ln.get("label", ""), fontsize=8)
        ax.set_yticks([])
    axes[-1].set_xlabel("Rf")
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# 3D intensity surface (raw vs background-subtracted), gel patch on the base
# -----------------------------------------------------------------------------
def _surfaces(sig, box):
    """Downsampled, gaussian-smoothed (before, after-bg) patches + mesh."""
    from scipy.ndimage import gaussian_filter
    y0, x0, y1, x1 = [int(v) for v in box]
    patch = sig[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    pad = 3
    h, w = sig.shape
    outer = sig[max(y0 - pad, 0):min(y1 + pad, h), max(x0 - pad, 0):min(x1 + pad, w)]
    bg = float(outer.mean())
    adjusted = np.clip(patch - bg, 0, None)
    step = max(1, max(patch.shape) // 110)
    p = gaussian_filter(patch[::step, ::step].astype(float), 1.0)
    a = gaussian_filter(adjusted[::step, ::step].astype(float), 1.0)
    yy, xx = np.mgrid[0:p.shape[0], 0:p.shape[1]]
    return p, a, xx, yy


def plot_after_surface(ax, sig, box, title: str = "") -> bool:
    """Draw the after-background smoothed surface onto a supplied 3D axis."""
    parts = _surfaces(sig, box)
    if parts is None:
        return False
    p, a, xx, yy = parts
    ax.plot_surface(xx, yy, a, cmap="inferno", rstride=1, cstride=1,
                    linewidth=0, antialiased=True, shade=True)
    ax.contourf(xx, yy, a, zdir="z", offset=0, cmap="gray", alpha=0.5)
    ax.set_zlim(0, max(float(p.max()), 1e-6))
    ax.view_init(elev=45, azim=-120)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    if title:
        ax.set_title(title, fontsize=8)
    return True


def surface_3d(sig, box, out_path: Optional[str] = None, title: str = ""):
    """Two 3D surfaces of a region's intensity: raw and background-subtracted."""
    parts = _surfaces(sig, box)
    if parts is None:
        return None
    p, a, xx, yy = parts
    zmax = max(float(p.max()), 1e-6)
    fig = figure(figsize=(10, 4.2))
    fig.suptitle(title or "region", fontsize=11)
    for i, (z, sub) in enumerate([(p, "before background"), (a, "after background")], 1):
        ax = fig.add_subplot(1, 2, i, projection="3d")
        ax.plot_surface(xx, yy, z, cmap="inferno", rstride=1, cstride=1,
                        linewidth=0, antialiased=True, shade=True)
        ax.contourf(xx, yy, z, zdir="z", offset=0, cmap="gray", alpha=0.5)
        ax.set_zlim(0, zmax)
        ax.view_init(elev=45, azim=-120)
        ax.set_title(sub, fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_zticks([])
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=130, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# electropherogram overlay: every lane/band on one Rf axis + strip underneath
# -----------------------------------------------------------------------------
def profile_overlay(sig, lanes, rgb, out_path: Optional[str] = None,
                    title: str = "Z profile"):
    """Z-profile overlay: every box's intensity vs Rf on one axis, and beneath it
    each box's strip bordered in that box's colour with its bands highlighted.
    """
    from matplotlib import colormaps
    from skimage.transform import resize

    lanes = [ln for ln in lanes if not ln.get("is_ladder")] or list(lanes)
    if not lanes:
        return None
    colors = colormaps["tab10"]
    n = len(lanes)
    fig = figure(figsize=(8, 3.2 + 0.5 * n))
    gs = fig.add_gridspec(1 + n, 1, height_ratios=[3.5] + [0.6] * n, hspace=0.12)
    ax = fig.add_subplot(gs[0])

    for k, ln in enumerate(lanes):
        y0, x0, y1, x1 = [int(v) for v in ln["box"]]
        color = colors(k % 10)
        label = ln.get("label") or f"box {k + 1}"
        prof = smooth_profile(sig[y0:y1, x0:x1].mean(axis=1))
        rf = np.linspace(0, 1, len(prof))
        bands = detect_bands(prof)
        ax.plot(rf, prof, color=color, lw=1.4, label=label)
        for b in bands:
            lo, hi = max(b - 4, 0), min(b + 5, len(prof))
            ax.fill_between(rf[lo:hi], 0, prof[lo:hi], color=color, alpha=0.25)

        # strip beneath: bordered in the box colour, bands highlighted
        axs = fig.add_subplot(gs[k + 1], sharex=ax)
        strip = resize(np.rot90(rgb[y0:y1, x0:x1]), (24, 400),
                       preserve_range=True, anti_aliasing=True).astype(np.uint8)
        axs.imshow(strip, aspect="auto", extent=[0, 1, 0, 1], cmap="gray")
        for b in bands:
            axs.axvline(b / max(len(prof) - 1, 1), color="lime", lw=1.2, alpha=0.8)
        axs.set_yticks([])
        for sp in axs.spines.values():  # thin coloured border matching the curve
            sp.set_edgecolor(color)
            sp.set_linewidth(1.2)
        axs.tick_params(labelbottom=(k == n - 1))
        if k == n - 1:
            axs.set_xlabel("Rf")

    ax.set_ylabel("Intensity (bg-subtracted)")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, ncol=max(1, n // 3))
    ax.tick_params(labelbottom=False)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# per-gel trend ("degradation"): this gel's signal across its lanes
# -----------------------------------------------------------------------------
def gel_trend(df, out_path: Optional[str] = None, ylabel: str = ""):
    import re
    if df is None or df.empty:
        return None
    sub = df[~df["is_ladder"]] if "is_ladder" in df.columns else df
    col = "adjusted_volume" if "adjusted_volume" in sub.columns else "raw_intensity"
    series = sub.groupby("lane_label", sort=False)[col].sum()
    if series.empty:
        return None
    # reference (100%) = a lane named control/ctrl, else the first lane
    ref_label = next((s for s in series.index
                      if re.search(r"control|ctrl", str(s), re.I)), series.index[0])
    ref = float(series.get(ref_label, 0.0)) or float(series.max()) or 1.0
    pct = series / ref * 100.0

    fig = figure(figsize=(max(4, 0.8 * len(pct) + 1.5), 3.2))
    ax = fig.subplots()
    ax.axhline(100, ls="--", color="gray", lw=0.8)  # control = 100%
    ax.plot(range(len(pct)), pct.to_numpy(), marker="o", color="firebrick")
    ax.set_xticks(range(len(pct)))
    ax.set_xticklabels([str(s) for s in pct.index], rotation=30, ha="right")
    ax.set_ylabel(ylabel or "% of control")
    ax.set_title("Trend across lanes")
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# cross-gel trend lines (per protein across lane labels; mean +/- SEM)
# -----------------------------------------------------------------------------
def trend_lines(entries: Sequence, ylabel: str = "",
                out_path: Optional[str] = None):
    import pandas as pd

    rows = []
    for e in entries:
        df = getattr(e, "result_df", None)
        if df is None or df.empty:
            continue
        protein = getattr(e, "protein_label", "") or os.path.basename(e.path)
        col = "adjusted_volume" if "adjusted_volume" in df.columns else "raw_intensity"
        sub = df[~df["is_ladder"]] if "is_ladder" in df.columns else df
        for lane, g in sub.groupby("lane_label"):
            rows.append({"protein": protein, "lane": str(lane),
                         "signal": float(g[col].sum())})
    tbl = pd.DataFrame(rows)
    if tbl.empty:
        return None
    agg = tbl.groupby(["protein", "lane"])["signal"].agg(["mean", "sem"]).reset_index()
    lanes = sorted(agg["lane"].unique())
    fig = figure(figsize=(max(4, 0.8 * len(lanes) + 2), 4))
    ax = fig.subplots()
    for protein, g in agg.groupby("protein"):
        g = g.set_index("lane").reindex(lanes)
        ax.errorbar(range(len(lanes)), g["mean"], yerr=g["sem"].fillna(0),
                    marker="o", capsize=3, label=protein)
    ax.set_xticks(range(len(lanes)))
    ax.set_xticklabels(lanes, rotation=30, ha="right")
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=8)
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# orchestration used by the app after an analysis
# -----------------------------------------------------------------------------
def render_entry(path, *, lanes, transform=Transform(), mw_predict=None,
                 outdir="results", name="gel", title_label="",
                 max_dim=2000) -> list[str]:
    """Write montage + lane profiles + 3D surfaces for one analyzed image.

    Every non-ladder box is cropped into the montage / 3D; lane-profile
    chromatograms are drawn only for auto-detect (lane) boxes.
    """
    rgb, gray, sig = _load(path, transform, max_dim)
    os.makedirs(outdir, exist_ok=True)
    out = []

    marked = [ln for ln in lanes if not ln.get("is_ladder")]
    items = [{"box": tuple(int(v) for v in ln["box"]),
              "label": (ln.get("label")
                        or (f"{mw_predict((ln['box'][0] + ln['box'][2]) / 2):.0f} kDa"
                            if mw_predict else ""))}
             for ln in marked]
    auto_lanes = [ln for ln in marked if ln.get("auto_bands", True)]

    p = os.path.join(outdir, f"{name}_montage.png")
    if band_montage(rgb, items, out_path=p) is not None:
        out.append(p)

    p = os.path.join(outdir, f"{name}_profiles.png")
    if auto_lanes and lane_profiles(sig, auto_lanes, out_path=p) is not None:
        out.append(p)

    # electropherogram overlay of every box + the whole gel's lanes.
    p = os.path.join(outdir, f"{name}_overlay_profile.png")
    if profile_overlay(sig, marked or lanes, rgb, out_path=p,
                       title=f"{title_label or name}: Z profile") is not None:
        out.append(p)

    # 3D: whole gel + each marked item (capped so we don't dump dozens).
    gel_box = (0, 0, sig.shape[0], sig.shape[1])
    p = os.path.join(outdir, f"{name}_surface_gel.png")
    if surface_3d(sig, gel_box, out_path=p, title=f"{name} — whole gel") is not None:
        out.append(p)
    for i, it in enumerate(items[:6], 1):
        p = os.path.join(outdir, f"{name}_surface_{i}.png")
        label = it["label"] or f"box {i}"
        if surface_3d(sig, it["box"], out_path=p, title=label) is not None:
            out.append(p)
    return out


def demo() -> None:
    import tempfile

    from PIL import Image

    h, w = 200, 240
    gray = np.full((h, w), 230, np.uint8)
    for x0, x1 in ((30, 90), (150, 210)):
        gray[90:110, x0:x1] = 40
    path = os.path.join(tempfile.mkdtemp(), "g.png")
    Image.fromarray(np.stack([gray] * 3, -1)).save(path)
    lanes = [{"box": (10, 30, 190, 90), "label": "ctrl", "auto_bands": True},
             {"box": (85, 150, 115, 210), "label": "band", "auto_bands": False}]
    out = tempfile.mkdtemp()
    files = render_entry(path, lanes=lanes, outdir=out, name="g")
    assert any("montage" in f for f in files)
    assert any("surface_gel" in f for f in files)
    print("viz.py self-check OK:", len(files), "files")


if __name__ == "__main__":
    demo()
