"""Combined scientific results across several analyzed membranes / gels.

Three outputs, all reusable from the notebook or the Toga app:

    panel_figure          proteins side-by-side, aligned on a shared kDa axis
    quantify_normalized   master table + bar chart (optionally normalized to a
                          loading control)
    fit_decay             exponential half-life fit across timepoints

Entries are duck-typed: each needs ``.protein_label`` (str), ``.result_df``
(pandas DataFrame, western rows carry ``mw_kda`` + ``df.attrs['mw_fit']``) and
``.path`` (source image). No dependency on the app.
"""
from __future__ import annotations

import os
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from ._plot import figure
from .detect import band_signal, load_image
from .lanes import apply_transform
from .viz import plot_after_surface


def _western_entries(entries: Sequence) -> list:
    out = []
    for e in entries:
        df = getattr(e, "result_df", None)
        if df is not None and not df.empty and "mw_kda" in df.columns \
                and df.attrs.get("mw_fit"):
            out.append(e)
    return out


def _entry_rgb(entry) -> np.ndarray:
    """Load + apply the entry's transform (so it matches how it was analyzed)."""
    rgb, gray = load_image(entry.path)
    t = getattr(getattr(entry, "selection", None), "transform", None)
    if t is not None:
        rgb, _ = apply_transform(rgb, gray, t)
    return rgb


def _entry_sig(entry) -> np.ndarray:
    """Background-flattened signal for the entry (as analyze_lanes uses)."""
    rgb, gray = load_image(entry.path)
    t = getattr(getattr(entry, "selection", None), "transform", None)
    if t is not None:
        rgb, gray = apply_transform(rgb, gray, t)
    return band_signal(gray)


# -----------------------------------------------------------------------------
# panel figure: stacked protein rows (protein left, kDa right, lanes as columns)
# -----------------------------------------------------------------------------
_STRIP_HH = 28   # panel tile half-height (px) — tall enough not to cut bands
_FALLBACK_HW = 90  # panel tile half-width when no lane box is known


def _lane_xrange(entry, band_x, y_px):
    """x-range of the (non-ladder) lane box containing the band, or None."""
    lanes = getattr(getattr(entry, "selection", None), "lanes", ()) or ()
    for ln in lanes:
        if getattr(ln, "is_ladder", False):
            continue
        if ln.x0 <= band_x <= ln.x1 and ln.y0 <= y_px <= ln.y1:
            return int(ln.x0), int(ln.x1)
    return None


def _strip_crop(rgb, x0, x1, y0, y1, fill=255) -> np.ndarray:
    """(y1-y0, x1-x0) crop centred on a region; only true image edges are padded
    (with ``fill``: 255 = white for display images, 0 = flat for signal)."""
    h, w = rgb.shape[:2]
    ch = rgb.shape[2] if rgb.ndim == 3 else 1
    sh, sw = int(y1 - y0), int(x1 - x0)
    strip = np.full((sh, sw, ch), fill, dtype=rgb.dtype).squeeze()
    sy0, sy1 = max(int(y0), 0), min(int(y1), h)
    sx0, sx1 = max(int(x0), 0), min(int(x1), w)
    dy, dx = sy0 - int(y0), sx0 - int(x0)
    strip[dy:dy + (sy1 - sy0), dx:dx + (sx1 - sx0)] = rgb[sy0:sy1, sx0:sx1]
    return strip


def _union_columns(per_protein):
    """Ordered union of lane labels; seed from the widest protein, then extras."""
    order: list[str] = []
    ref = max(per_protein, key=lambda t: len({b[4] for b in t[2]}), default=None)
    for _p, _m, bands in ([ref] if ref else []) + list(per_protein):
        for b in sorted(bands, key=lambda b: b[0]):
            if b[4] not in order:
                order.append(b[4])
    return order


def _span_and_map(bands, columns):
    """Continuous span (X0,X1,Y0,Y1) + linear map ``column = a*x_abs + b`` that sends
    the crop *edges* to column *boundaries* — so a gel spanning n contiguous columns is
    exactly n columns wide, and every same-box-count gel gets the identical width."""
    X0 = min(int(lx0) for _bx, _by, lx0, _lx1, _l, _m in bands)
    X1 = max(int(lx1) for _bx, _by, _lx0, lx1, _l, _m in bands)
    ys = [int(by) for _bx, by, _lx0, _lx1, _l, _m in bands]
    Y0, Y1 = min(ys) - _STRIP_HH, max(ys) + _STRIP_HH
    cols = sorted(columns.index(lane) for lane in {b[4] for b in bands}
                  if lane in columns)
    cf, cl = (cols[0], cols[-1]) if cols else (0, 0)
    a = ((cl + 0.5) - (cf - 0.5)) / max(X1 - X0, 1)   # X0 -> cf-0.5, X1 -> cl+0.5
    b = (cf - 0.5) - a * X0
    return X0, X1, Y0, Y1, float(a), float(b)


def _first_label_row(per_protein):
    """{row: {lanes first appearing at that row}} — name a lane once, at its top row."""
    first = {}
    for r, (_p, _m, bands) in enumerate(per_protein):
        for lane in {b[4] for b in bands}:
            first.setdefault(lane, r)
    rows: dict[int, set] = {}
    for lane, r in first.items():
        rows.setdefault(r, set()).add(lane)
    return rows


def _uniform_scale(per_protein, columns):
    """(Wcol, Hpix): the common lane-cell size — widest per-column width and tallest
    crop across all gels. Every gel is resized to fill ncols x these cells, so all cells
    are the same size and lanes align (fewer-lane gels are simply narrower)."""
    wcol = hpix = 1
    for _p, _m, bands in per_protein:
        X0, X1, Y0, Y1, a, _b = _span_and_map(bands, columns)
        ncols = max(round(a * (X1 - X0)), 1)
        wcol = max(wcol, (X1 - X0) / ncols)
        hpix = max(hpix, Y1 - Y0)
    return float(wcol), int(hpix)


def _draw_strip(ax, rgb, bands, columns, Wcol, Hpix, label_cols=()) -> None:
    """One continuous uncut strip resized to fill its lane cells exactly — same cell
    size everywhere, fewer-lane gels are narrower (aligned), no white padding, no crop."""
    from matplotlib.patches import Rectangle
    from skimage.transform import resize

    ax.set_xticks([])
    ax.set_yticks([])
    X0, X1, Y0, Y1, a, b = _span_and_map(bands, columns)
    cf = a * X0 + b + 0.5                 # left column index (a*X0+b == cf-0.5)
    ncols = max(round(a * (X1 - X0)), 1)
    crop = _strip_crop(rgb, X0, X1, Y0, Y1)
    if crop.ndim == 2:
        crop = np.stack([crop] * 3, axis=-1)
    th, tw = Hpix, max(int(round(ncols * Wcol)), 1)  # fill ncols cells of size Wcol x Hpix
    filled = resize(crop[..., :3], (th, tw), order=1, preserve_range=True,
                    anti_aliasing=True).astype(np.uint8)
    left, right = cf - 0.5, cf - 0.5 + ncols
    ax.imshow(filled, extent=[left, right, 0, 1], aspect="auto", zorder=1)
    k = max(len(columns), 1)
    ax.set_xlim(-0.5, k - 0.5)
    ax.set_ylim(0, 1)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.add_patch(Rectangle((left, 0), right - left, 1, fill=False,
                           edgecolor="black", linewidth=0.8, zorder=3))
    for i, lane in enumerate(columns):
        if lane in label_cols:
            ax.text(i, 1.02, lane, transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", fontsize=7)


def _draw_surface(ax, sig, bands, columns, label_cols=()) -> None:
    """One continuous uncut 3D surface, x-mapped to the shared columns (aligned)."""
    h, w = sig.shape
    X0, X1, Y0, Y1, a, b = _span_and_map(bands, columns)
    x0c, x1c = max(X0, 0), min(X1, w)
    y0c, y1c = max(Y0, 0), min(Y1, h)
    if not plot_after_surface(ax, sig, (y0c, x0c, y1c, x1c)):
        return
    # map the surface mesh (index m -> pixel x0c + m*step) to column units and set the
    # x-limits so lanes land in their columns. step mirrors viz._surfaces downsampling.
    step = max(1, max(y1c - y0c, x1c - x0c) // 110)
    A = a * step
    B = a * x0c + b
    k = max(len(columns), 1)
    if A:
        ax.set_xlim((-0.5 - B) / A, (k - 0.5 - B) / A)
    for i, lane in enumerate(columns):
        if lane in label_cols:
            ax.text2D((i + 0.5) / k, 1.0, lane, transform=ax.transAxes,
                      ha="center", va="bottom", fontsize=7)


def _per_protein_bands(west):
    """[(protein, row_mw, [(band_x, y_px, lx0, lx1, lane_label, mw), ...]), ...]."""
    out = []
    for e in west:
        df = e.result_df
        if "is_ladder" in df.columns:
            df = df[~df["is_ladder"]]           # never show the ladder in the panel
        df = df.sort_values("y_px")
        bands = []
        for _, r in df.iterrows():
            bx, by = int(r["band_x"]), int(r["y_px"])
            rng = _lane_xrange(e, bx, by)
            lx0, lx1 = rng if rng else (bx - _FALLBACK_HW, bx + _FALLBACK_HW)
            bands.append((bx, by, lx0, lx1, str(r["lane_label"]), r["mw_kda"]))
        row_mw = float(np.nanmedian(df["mw_kda"]))
        out.append((e.protein_label or os.path.basename(e.path), row_mw, bands))
    return out


def _kda_on_right(fig, axes, per_protein) -> None:
    """One kDa value per protein row, on the figure's right edge."""
    fig.canvas.draw()  # positions are valid after a draw
    for r, (_protein, row_mw, _bands) in enumerate(per_protein):
        if row_mw != row_mw:
            continue
        pos = axes[r][-1].get_position()
        fig.text(0.995, (pos.y0 + pos.y1) / 2, f"{row_mw:.0f} kDa",
                 va="center", ha="right", fontsize=8)


def panel_figure(entries: Sequence, out_path: Optional[str] = None):
    """Stacked rows = proteins; each row is ONE continuous strip cropped from the
    leftmost lane box to the rightmost, lane names once on top, protein name on the
    left, one kDa per row on the right (like a western figure)."""
    west = _western_entries(entries)
    if not west:
        raise RuntimeError("panel_figure needs western entries with an MW fit.")

    per_protein = _per_protein_bands(west)
    rgbs = [_entry_rgb(e) for e in west]
    nrows = len(per_protein)
    columns = _union_columns(per_protein)
    label_rows = _first_label_row(per_protein)
    Wcol, Hpix = _uniform_scale(per_protein, columns)

    fig = figure(figsize=(6, 0.75 * nrows + 0.4))
    axes = fig.subplots(nrows, 1, squeeze=False,
                        gridspec_kw={"hspace": 0.15})[:, 0]
    for r, (protein, _mw, bands) in enumerate(per_protein):
        ax = axes[r]
        _draw_strip(ax, rgbs[r], bands, columns, Wcol, Hpix,
                    label_cols=label_rows.get(r, set()))
        ax.set_ylabel(protein, rotation=0, ha="right", va="center",
                      fontsize=8, labelpad=8)
    fig.tight_layout(rect=(0, 0, 0.9, 1))
    _kda_on_right(fig, [[ax] for ax in axes], per_protein)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


def combined_3d(entries: Sequence, out_path: Optional[str] = None):
    """One continuous after-background 3D surface per protein, spanning all its
    lanes; lane names once on top, protein name on the left, kDa on the right."""
    west = _western_entries(entries)
    if not west:
        return None
    per_protein = _per_protein_bands(west)
    sigs = [_entry_sig(e) for e in west]
    nrows = len(per_protein)
    columns = _union_columns(per_protein)
    label_rows = _first_label_row(per_protein)
    fig = figure(figsize=(6, 1.5 * nrows + 0.4))
    row_ax = {}
    for r, (protein, _mw, bands) in enumerate(per_protein):
        ax = fig.add_subplot(nrows, 1, r + 1, projection="3d")
        _draw_surface(ax, sigs[r], bands, columns,
                      label_cols=label_rows.get(r, set()))
        row_ax[r] = ax
        ax.text2D(-0.15, 0.5, protein, transform=ax.transAxes,
                  ha="right", va="center", fontsize=9)
    fig.subplots_adjust(hspace=0.05, left=0.12, right=0.9, top=0.98, bottom=0.02)
    fig.canvas.draw()
    for r, (_protein, row_mw, _bands) in enumerate(per_protein):
        if r in row_ax and row_mw == row_mw:
            pos = row_ax[r].get_position()
            fig.text(0.995, (pos.y0 + pos.y1) / 2, f"{row_mw:.0f} kDa",
                     va="center", ha="right", fontsize=8)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=130, bbox_inches="tight")
    return fig


def _lane_pct(entry):
    """(lanes, pct): per-lane summed signal as % of the control lane, order kept."""
    import re

    df = getattr(entry, "result_df", None)
    if df is None or df.empty or "lane_label" not in df.columns:
        return None
    sub = df[~df["is_ladder"]] if "is_ladder" in df.columns else df
    col = "adjusted_volume" if "adjusted_volume" in sub.columns else "raw_intensity"
    series = sub.groupby("lane_label", sort=False)[col].sum()
    if series.empty:
        return None
    ref_label = next((s for s in series.index
                      if re.search(r"control|ctrl", str(s), re.I)), series.index[0])
    ref = float(series.get(ref_label, 0.0)) or float(series.max()) or 1.0
    return [str(s) for s in series.index], (series / ref * 100.0).to_numpy()


def panel_3d_figure(entries: Sequence, out_path: Optional[str] = None):
    """Per protein row: protein name | full-width 2D strip | 3D surface | trend | kDa.
    Lane names are printed once on the top strip when identical across proteins; the
    trend lines share one y-scale, with axes shown only on the bottom trend."""
    west = _western_entries(entries)
    if not west:
        return None
    per_protein = _per_protein_bands(west)
    rgbs = [_entry_rgb(e) for e in west]
    sigs = [_entry_sig(e) for e in west]
    pcts = [_lane_pct(e) for e in west]
    nrows = len(per_protein)
    columns = _union_columns(per_protein)
    label_rows = _first_label_row(per_protein)
    Wcol, Hpix = _uniform_scale(per_protein, columns)

    fig = figure(figsize=(8.5, 1.4 * nrows + 0.4))
    gs = fig.add_gridspec(nrows, 3, width_ratios=[3.0, 1.2, 1.4], right=0.90,
                          hspace=0.15, wspace=0.1)
    strip_ax = {}
    for r, (protein, _mw, bands) in enumerate(per_protein):
        ax_img = fig.add_subplot(gs[r, 0])
        _draw_strip(ax_img, rgbs[r], bands, columns, Wcol, Hpix,
                    label_cols=label_rows.get(r, set()))
        ax_img.set_ylabel(protein, rotation=0, ha="right", va="center",
                          fontsize=9, labelpad=12)
        strip_ax[r] = ax_img
        ax_3d = fig.add_subplot(gs[r, 1], projection="3d")
        _draw_surface(ax_3d, sigs[r], bands, columns)  # names on the strip

        ax_tr = fig.add_subplot(gs[r, 2])
        ax_tr.spines["top"].set_visible(False)
        ax_tr.spines["right"].set_visible(False)
        ax_tr.tick_params(labelsize=7)  # each trend keeps its own y-axis numbers
        if pcts[r] is not None:
            lanes, pct = pcts[r]
            ax_tr.axhline(100, ls="--", color="gray", lw=0.8)
            ax_tr.plot(range(len(pct)), pct, marker="o", ms=3,
                       color="firebrick", lw=1.2)
            ax_tr.set_xticks(range(len(lanes)))
            if r == nrows - 1:  # lane names only on the bottom trend
                ax_tr.set_xticklabels(lanes, rotation=30, ha="right", fontsize=7)
            else:
                ax_tr.set_xticklabels([])
    fig.canvas.draw()
    for r, (_protein, row_mw, _bands) in enumerate(per_protein):
        if r in strip_ax and row_mw == row_mw:
            pos = strip_ax[r].get_position()
            fig.text(0.965, (pos.y0 + pos.y1) / 2, f"{row_mw:.0f} kDa",
                     va="center", ha="right", fontsize=8)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=140, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# decay / half-life
# -----------------------------------------------------------------------------
def fit_decay(times: Sequence[float], intensities: Sequence[float],
              out_path: Optional[str] = None) -> dict:
    """Fit y = a·exp(-k·t); return {a, k, half_life, r2}."""
    from scipy.optimize import curve_fit

    t = np.asarray(times, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if len(t) < 3:
        raise ValueError("Need at least 3 timepoints to fit a decay curve.")

    def model(t, a, k):
        return a * np.exp(-k * t)

    popt, _ = curve_fit(model, t, y, p0=[float(y[0]) or 1.0, 0.1], maxfev=10000)
    a, k = float(popt[0]), float(popt[1])
    resid = y - model(t, *popt)
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    half_life = float(np.log(2) / k) if k > 0 else float("inf")

    if out_path:
        fig = figure(figsize=(5, 4))
        ax = fig.subplots()
        ax.plot(t, y, "ko", label="data")
        ts = np.linspace(t.min(), t.max(), 100)
        ax.plot(ts, model(ts, *popt), "r-",
                label=f"t½={half_life:.2f}, r²={r2:.3f}")
        ax.set_xlabel("time")
        ax.set_ylabel("intensity")
        ax.legend()
        fig.tight_layout()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")

    return {"a": a, "k": k, "half_life": half_life, "r2": round(r2, 4)}


# -----------------------------------------------------------------------------
# intensity differences between lanes, across gels
# -----------------------------------------------------------------------------
def combined_differences(entries: Sequence, out_path: Optional[str] = None):
    """Per-lane total intensity for every protein/gel -> grouped bar chart.

    Shows how lanes (e.g. control / MG / MLN) differ within and across gels.
    Returns (DataFrame, matplotlib.Figure|None).
    """
    rows = []
    for e in entries:
        df = getattr(e, "result_df", None)
        if df is None or df.empty or "lane_label" not in df.columns:
            continue
        protein = getattr(e, "protein_label", "") or os.path.basename(e.path)
        for lane, g in df.groupby("lane_label"):
            ref = g["pct_of_reference"].iloc[0] if "pct_of_reference" in g else np.nan
            rows.append({"protein": protein, "lane": str(lane),
                         "lane_total": float(g["lane_total"].iloc[0]),
                         "pct_of_reference": float(ref) if ref == ref else np.nan})
    tbl = pd.DataFrame(rows)
    if tbl.empty:
        return tbl, None

    pivot = tbl.pivot_table(index="protein", columns="lane", values="lane_total",
                            aggfunc="first")
    fig = figure(figsize=(max(5, 1.2 * len(pivot) + 2), 4))
    ax = fig.subplots()
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel("lane total intensity")
    ax.set_title("Intensity by lane, across gels")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=30, ha="right")
    ax.legend(title="lane", fontsize=8)
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return tbl, fig


# -----------------------------------------------------------------------------
# statistics bar chart (optional: error bars / significance / normalization)
# -----------------------------------------------------------------------------
def _normalized_signal(entries: Sequence):
    """(tbl, agg, proteins, lanes, baseline): per-lane signal normalised to each
    (protein, gel) control lane -> % of control. tbl is empty when no rows."""
    import re

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
                         "signal": float(g[col].sum()), "gel": getattr(e, "path", "")})
    tbl = pd.DataFrame(rows)
    if tbl.empty:
        return tbl, None, [], [], None

    for _key, g in tbl.groupby(["protein", "gel"]):
        ctrl = next((i for i, ln in zip(g.index, g["lane"])
                     if re.search(r"control|ctrl", ln, re.I)), g.index[0])
        ref = float(g.loc[ctrl, "signal"]) or float(g["signal"].max()) or 1.0
        tbl.loc[g.index, "signal"] = g["signal"] / ref * 100.0

    agg = tbl.groupby(["protein", "lane"])["signal"].agg(
        ["mean", "sem", "count"]).reset_index()
    proteins = sorted(agg["protein"].unique())
    lanes = sorted(agg["lane"].unique())
    baseline = next((ln for ln in lanes if re.search(r"control|ctrl", ln, re.I)),
                    lanes[0] if lanes else None)
    return tbl, agg, proteins, lanes, baseline


def sig_barchart(entries: Sequence, out_path: Optional[str] = None):
    """Extra bar chart: for each protein, brackets between significant lane pairs.

    Pairwise Welch t-test on the replicate % values of each lane pair (needs >=2
    replicates per lane); brackets stack upward with */**/*** stars (p<0.05)."""
    from scipy.stats import ttest_ind

    tbl, agg, proteins, lanes, _baseline = _normalized_signal(entries)
    if tbl.empty or len(lanes) < 2:
        return None

    x = np.arange(len(proteins))
    wds = 0.8 / max(len(lanes), 1)
    fig = figure(figsize=(max(5, 1.3 * len(proteins) + 2), 4.5))
    ax = fig.subplots()
    for j, lane in enumerate(lanes):
        sub = agg[agg["lane"] == lane].set_index("protein").reindex(proteins)
        ax.bar(x + j * wds, sub["mean"].to_numpy(), wds,
               yerr=sub["sem"].fillna(0).to_numpy(), capsize=3, label=lane)
    ax.set_xticks(x + wds * (len(lanes) - 1) / 2)
    ax.set_xticklabels(proteins, rotation=30, ha="right")
    ax.set_ylabel("% of control (intensity)")
    ax.legend(title="lane", fontsize=8)

    ymax = float((agg["mean"] + agg["sem"].fillna(0)).max())
    step = max(ymax * 0.08, 1.0)
    for i, protein in enumerate(proteins):
        drawn = 0
        for a in range(len(lanes)):
            for b in range(a + 1, len(lanes)):
                va = tbl[(tbl["protein"] == protein) & (tbl["lane"] == lanes[a])]["signal"]
                vb = tbl[(tbl["protein"] == protein) & (tbl["lane"] == lanes[b])]["signal"]
                if len(va) < 2 or len(vb) < 2:
                    continue
                p = float(ttest_ind(va, vb, equal_var=False).pvalue)
                star = ("***" if p < 0.001 else "**" if p < 0.01
                        else "*" if p < 0.05 else "")
                if not star:
                    continue
                y = ymax + step * (drawn + 1)
                xa, xb = i + a * wds, i + b * wds
                ax.plot([xa, xa, xb, xb], [y - step * 0.25, y, y, y - step * 0.25],
                        lw=1, color="black")
                ax.text((xa + xb) / 2, y, star, ha="center", va="bottom", fontsize=9)
                drawn += 1
    ax.set_title("Significant lane differences per protein (p<0.05)")
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


def stats_barchart(entries: Sequence, *, error_bars: bool = False,
                   significance: bool = False, ylabel: str = "",
                   out_path: Optional[str] = None):
    """Grouped bars of per-lane signal by protein, with optional stats.

    Replicates = same (protein, lane) measured across gels/bands. mean ± SEM.
    Significance (if on) compares each lane to the first (leftmost) lane.
    Returns (aggregated DataFrame, matplotlib.Figure|None).
    """
    tbl, agg, proteins, lanes, baseline = _normalized_signal(entries)
    if tbl.empty:
        return tbl, None

    x = np.arange(len(proteins))
    wds = 0.8 / max(len(lanes), 1)
    fig = figure(figsize=(max(5, 1.3 * len(proteins) + 2), 4))
    ax = fig.subplots()
    for j, lane in enumerate(lanes):
        sub = agg[agg["lane"] == lane].set_index("protein").reindex(proteins)
        yerr = sub["sem"].to_numpy() if error_bars else None
        ax.bar(x + j * wds, sub["mean"].to_numpy(), wds, yerr=yerr, capsize=3,
               label=lane)
    ax.set_xticks(x + wds * (len(lanes) - 1) / 2)
    ax.set_xticklabels(proteins, rotation=30, ha="right")
    ax.set_ylabel(ylabel or "% of control (intensity)")
    ax.legend(title="lane", fontsize=8)

    if significance and baseline is not None:
        from scipy.stats import ttest_ind
        for i, protein in enumerate(proteins):
            ref_vals = tbl[(tbl["protein"] == protein)
                           & (tbl["lane"] == baseline)]["signal"]
            for j, lane in enumerate(lanes):
                if lane == baseline:
                    continue
                vals = tbl[(tbl["protein"] == protein) & (tbl["lane"] == lane)]["signal"]
                if len(ref_vals) >= 2 and len(vals) >= 2:
                    p = float(ttest_ind(ref_vals, vals, equal_var=False).pvalue)
                    star = ("***" if p < 0.001 else "**" if p < 0.01
                            else "*" if p < 0.05 else "")
                    if star:
                        m = agg[(agg["protein"] == protein)
                                & (agg["lane"] == lane)]["mean"].iloc[0]
                        ax.text(i + j * wds, m, star, ha="center", va="bottom",
                                fontsize=10)
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return agg, fig


# -----------------------------------------------------------------------------
# orchestration (called by the app's "Combine & Export")
# -----------------------------------------------------------------------------
def combine_entries(entries: Sequence, outdir: str, *, error_bars: bool = False,
                    significance: bool = False, ylabel: str = "") -> list[str]:
    """Write stacked panel + stats bars + trend lines; return output paths."""
    os.makedirs(outdir, exist_ok=True)
    outputs: list[str] = []

    if _western_entries(entries):
        panel = os.path.join(outdir, "combined_panel.png")
        panel_figure(entries, out_path=panel)
        outputs.append(panel)
        d3 = os.path.join(outdir, "combined_3d.png")
        if combined_3d(entries, out_path=d3) is not None:
            outputs.append(d3)
        p3d = os.path.join(outdir, "combined_panel_3d.png")
        if panel_3d_figure(entries, out_path=p3d) is not None:
            outputs.append(p3d)

    agg, sfig = stats_barchart(
        entries, error_bars=error_bars, significance=significance, ylabel=ylabel,
        out_path=os.path.join(outdir, "combined_stats.png"))
    if not agg.empty:
        agg.to_csv(os.path.join(outdir, "combined_stats.csv"), index=False)
        outputs.append(os.path.join(outdir, "combined_stats.csv"))
        if sfig is not None:
            outputs.append(os.path.join(outdir, "combined_stats.png"))
        p = os.path.join(outdir, "combined_stats_sig.png")
        if sig_barchart(entries, out_path=p) is not None:
            outputs.append(p)

    from . import correlate  # Spearman ellipse heatmaps (proteins + treatments)
    outputs += correlate.combined_correlations(entries, outdir)
    return outputs


# -----------------------------------------------------------------------------
# self-check
# -----------------------------------------------------------------------------
def demo() -> None:
    # decay: recover a known half-life from synthetic data.
    k_true = 0.35
    t = np.array([0, 1, 2, 4, 6, 8], dtype=float)
    y = 100 * np.exp(-k_true * t)
    fit = fit_decay(t, y)
    assert abs(fit["k"] - k_true) < 1e-3, fit
    assert abs(fit["half_life"] - np.log(2) / k_true) < 1e-2, fit
    assert fit["r2"] > 0.999, fit

    # stats bars on two fake membranes (two lanes each).
    class _E:
        def __init__(self, protein, df, path="x.png"):
            self.protein_label = protein
            self.result_df = df
            self.path = path

    def _df(vals):
        return pd.DataFrame({"lane_label": ["ctrl", "MG"], "is_ladder": [False, False],
                             "adjusted_volume": vals, "raw_intensity": vals})

    agg, fig = stats_barchart([_E("target", _df([200.0, 90.0])),
                               _E("tubulin", _df([150.0, 155.0]))],
                              error_bars=True, ylabel="signal")
    assert set(agg["protein"]) == {"target", "tubulin"}
    assert fig is not None

    # aligned-column helpers: two proteins with a mismatched lane set.
    pp = [("p1", 30.0, [(120, 50, 100, 140, "MG", 30.0),
                        (60, 52, 40, 80, "ctrl", 30.0)]),
          ("p2", 25.0, [(60, 50, 40, 80, "ctrl", 25.0),
                        (120, 50, 100, 140, "MG", 25.0),
                        (180, 50, 160, 200, "MLN", 25.0)])]
    cols = _union_columns(pp)
    assert cols == ["ctrl", "MG", "MLN"], cols
    rows = _first_label_row(pp)
    assert {"ctrl", "MG"} <= rows.get(0, set()) and "MLN" in rows.get(1, set()), rows
    # equal width per box count: the 3-box gel spans exactly columns [-0.5, 2.5]
    # (width 3), the 2-box gel [-0.5, 1.5] (width 2) — both left-aligned, regardless
    # of their internal box spacing.
    x0, x1, *_yy, a, b = _span_and_map(pp[1][2], cols)
    assert abs(a * x0 + b + 0.5) < 1e-9 and abs(a * x1 + b - 2.5) < 1e-9
    x0, x1, *_yy, a2, b2 = _span_and_map(pp[0][2], cols)
    assert abs(a2 * x0 + b2 + 0.5) < 1e-9 and abs(a2 * x1 + b2 - 1.5) < 1e-9
    # uniform scale: one (Wcol, Hpix) for both gels regardless of their pixel size.
    Wcol, Hpix = _uniform_scale(pp, cols)
    assert Wcol > 0 and Hpix == 2 * _STRIP_HH, (Wcol, Hpix)
    # _draw_strip resizes to fill exactly ncols cells (no white pad, no crop).
    from ._plot import figure
    ax = figure().subplots()
    _draw_strip(ax, np.zeros((100, 220, 3), dtype=np.uint8), pp[0][2], cols, Wcol, Hpix)
    drawn = ax.images[0].get_array()
    assert drawn.shape == (Hpix, max(round(2 * Wcol), 1), 3), drawn.shape
    assert drawn[:, -1, :3].max() < 255  # far-right column filled, not white
    # crop zero-pads the part that runs past the image edge.
    sig = np.ones((70, 200))
    cell = _strip_crop(sig, 190, 230, 0, 2 * _STRIP_HH, fill=0)
    assert cell.shape == (2 * _STRIP_HH, 40) and (cell[:, :10] == 1).all() \
        and (cell[:, 10:] == 0).all()
    print("combine.py self-check OK")


if __name__ == "__main__":
    demo()
