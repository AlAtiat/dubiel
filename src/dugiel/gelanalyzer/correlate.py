"""Spearman correlation ellipse heatmaps (per-gel + combined).

Every pair of variables is correlated with Spearman's rho over the observations
they share (pairwise-complete), p-values are FDR-corrected (Benjamini-Hochberg),
and the result is drawn as an ellipse grid: orientation encodes the sign of rho,
narrowness + colour encode |rho|. Each cell prints rho, the q-value and n.

Three figures:
    gel_correlation        one gel: its lanes correlated by intensity profile
    combined_correlations  proteins-on-axes AND treatments-on-axes, across gels
"""
from __future__ import annotations

import os
import re
from typing import Optional, Sequence

import numpy as np
from scipy.stats import false_discovery_control, spearmanr

from ._plot import figure

_MIN_OBS = 3          # need at least this many shared points to correlate a pair
_N_PROFILE = 100      # profile resample length for the per-gel heatmap


# -----------------------------------------------------------------------------
# core stats (pure numpy/scipy so it is testable without pandas)
# -----------------------------------------------------------------------------
def _corr_matrix(mat: np.ndarray, labels: Sequence[str]):
    """Pairwise Spearman + BH q over columns of ``mat`` ((n_obs, k), NaN=missing).

    Returns (labels, rho, q, n) as k x k arrays (n is int; diagonal rho = 1).
    """
    mat = np.asarray(mat, dtype=float)
    k = mat.shape[1]
    rho = np.full((k, k), np.nan)
    pval = np.full((k, k), np.nan)
    nn = np.zeros((k, k), dtype=int)
    for i in range(k):
        for j in range(i, k):
            a, b = mat[:, i], mat[:, j]
            m = np.isfinite(a) & np.isfinite(b)
            cnt = int(m.sum())
            nn[i, j] = nn[j, i] = cnt
            if i == j:
                rho[i, j] = 1.0
                pval[i, j] = 0.0
                continue
            if cnt >= _MIN_OBS and np.ptp(a[m]) > 0 and np.ptp(b[m]) > 0:
                r, p = spearmanr(a[m], b[m])
                rho[i, j] = rho[j, i] = float(r)
                pval[i, j] = pval[j, i] = float(p)
    # BH across the unique off-diagonal (upper-triangle) p-values
    iu = np.triu_indices(k, 1)
    ps = pval[iu]
    fin = np.isfinite(ps)
    q = np.full((k, k), np.nan)
    if fin.any():
        qv = np.full(ps.shape, np.nan)
        qv[fin] = false_discovery_control(ps[fin], method="bh")
        q[iu] = qv
        q[(iu[1], iu[0])] = qv
    return list(labels), rho, q, nn


# -----------------------------------------------------------------------------
# rendering
# -----------------------------------------------------------------------------
def _ellipse_heatmap(labels, rho, q, nn, out_path: Optional[str] = None,
                     title: str = "", cbar_label: str = "Spearman Correlation (ρ)"):
    """Ellipse grid. Orientation: +rho tilts upper-left (\\), -rho upper-right (/);
    narrower + more saturated = stronger. Cells show rho, q and n."""
    from matplotlib import colormaps
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize
    from matplotlib.patches import Ellipse

    k = len(labels)
    cmap = colormaps["RdBu_r"]
    norm = Normalize(-1.0, 1.0)

    fig = figure(figsize=(1.0 * k + 2.2, 1.0 * k + 1.6))
    ax = fig.subplots()
    ax.set_xlim(-0.5, k - 0.5)
    ax.set_ylim(k - 0.5, -0.5)          # row 0 on top
    ax.set_aspect("equal")
    ax.set_xticks(range(k))
    ax.set_yticks(range(k))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_facecolor("white")
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)

    for i in range(k):
        for j in range(k):
            r = rho[i, j]
            if not np.isfinite(r):
                continue
            mag = abs(r)
            color = cmap(norm(r))
            angle = 135.0 if r >= 0 else 45.0        # + upper-left, - upper-right
            width = 0.85
            height = max(0.85 * (1.0 - mag), 0.30)   # narrow when strong, but floored
            ax.add_patch(Ellipse((j, i), width, height, angle=angle,
                                 facecolor=color, edgecolor="none", alpha=0.9,
                                 zorder=1))
            lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            tcolor = "white" if lum < 0.5 else "black"  # readable on dark or light
            if i == j:
                txt = f"1.00\nn={nn[i, j]}"
            else:
                if not np.isfinite(q[i, j]):
                    qs = "q--"
                elif q[i, j] < 0.001:
                    qs = "q<0.001"
                else:
                    qs = f"q{q[i, j]:.3f}"
                txt = f"{r:.2f}\n{qs}\nn={nn[i, j]}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=5.5,
                    color=tcolor, zorder=2)

    if title:
        ax.set_title(title, fontsize=11)
    sm = ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04).set_label(cbar_label)
    fig.text(0.5, 0.01, "q = FDR-corrected p-value (Benjamini–Hochberg)",
             ha="center", fontsize=7, style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    return fig


# -----------------------------------------------------------------------------
# per-gel: correlate a gel's lanes by their intensity profiles
# -----------------------------------------------------------------------------
def _entry_sig(entry) -> np.ndarray:
    from .detect import band_signal, load_image
    from .lanes import apply_transform

    rgb, gray = load_image(entry.path)
    t = getattr(getattr(entry, "selection", None), "transform", None)
    if t is not None:
        rgb, gray = apply_transform(rgb, gray, t)
    return band_signal(gray)


def gel_correlation(entry, out_path: Optional[str] = None,
                    n_samples: int = _N_PROFILE):
    """Correlation heatmap of one gel's non-ladder lanes by intensity profile."""
    lanes = [ln for ln in getattr(getattr(entry, "selection", None), "lanes", ())
             if not getattr(ln, "is_ladder", False)]
    if len(lanes) < 2:
        return None
    sig = _entry_sig(entry)
    h, w = sig.shape
    grid = np.linspace(0.0, 1.0, n_samples)
    cols, labels = [], []
    for i, ln in enumerate(lanes):
        y0, y1 = sorted((int(ln.y0), int(ln.y1)))
        x0, x1 = sorted((int(ln.x0), int(ln.x1)))
        y0, x0 = max(y0, 0), max(x0, 0)
        y1, x1 = min(y1, h), min(x1, w)
        if y1 - y0 < 2 or x1 - x0 < 1:
            continue
        prof = sig[y0:y1, x0:x1].mean(axis=1)
        cols.append(np.interp(grid, np.linspace(0.0, 1.0, len(prof)), prof))
        labels.append(getattr(ln, "label", "") or f"Box {i + 1}")
    if len(cols) < 2:
        return None
    labels, rho, q, nn = _corr_matrix(np.column_stack(cols), labels)
    title = getattr(entry, "protein_label", "") or os.path.basename(entry.path)
    _ellipse_heatmap(labels, rho, q, nn, out_path=out_path,
                     title=f"{title}: correlation")
    return out_path


# -----------------------------------------------------------------------------
# combined: protein x lane %-of-control table -> two heatmaps
# -----------------------------------------------------------------------------
def _protein_lane_pct(entries: Sequence):
    """(_proteins, lanes, matrix[protein, lane]) of % of each gel's control lane."""
    proteins, lane_order, per = [], [], []
    for e in entries:
        df = getattr(e, "result_df", None)
        if df is None or getattr(df, "empty", True) or "lane_label" not in df.columns:
            continue
        sub = df[~df["is_ladder"]] if "is_ladder" in df.columns else df
        col = "adjusted_volume" if "adjusted_volume" in sub.columns else "raw_intensity"
        sig = {str(lane): float(g[col].sum()) for lane, g in sub.groupby("lane_label")}
        if not sig:
            continue
        ctrl = next((v for k, v in sig.items() if re.search(r"control|ctrl", k, re.I)),
                    next(iter(sig.values())))
        ref = ctrl or (max(sig.values()) or 1.0)
        protein = getattr(e, "protein_label", "") or os.path.basename(e.path)
        proteins.append(protein)
        per.append({k: v / ref * 100.0 for k, v in sig.items()})
        for k in sig:
            if k not in lane_order:
                lane_order.append(k)
    mat = np.full((len(proteins), len(lane_order)), np.nan)
    for r, d in enumerate(per):
        for c, lane in enumerate(lane_order):
            if lane in d:
                mat[r, c] = d[lane]
    return proteins, lane_order, mat


def _valid(rho) -> bool:
    off = rho[~np.eye(rho.shape[0], dtype=bool)]
    return rho.shape[0] >= 2 and np.isfinite(off).any()


def combined_correlations(entries: Sequence, outdir: str) -> list[str]:
    """Write proteins-on-axes and treatments-on-axes heatmaps. Returns paths."""
    proteins, lanes, mat = _protein_lane_pct(entries)
    out: list[str] = []
    # treatments on axes: variables = lanes, observations = proteins (rows of mat)
    if len(lanes) >= 2:
        labels, rho, q, nn = _corr_matrix(mat, lanes)
        if _valid(rho):
            p = os.path.join(outdir, "combined_corr_treatments.png")
            _ellipse_heatmap(labels, rho, q, nn, out_path=p,
                             title="Treatment correlation (across proteins)")
            out.append(p)
    # proteins on axes: variables = proteins, observations = lanes (rows of mat.T)
    if len(proteins) >= 2:
        labels, rho, q, nn = _corr_matrix(mat.T, proteins)
        if _valid(rho):
            p = os.path.join(outdir, "combined_corr_proteins.png")
            _ellipse_heatmap(labels, rho, q, nn, out_path=p,
                             title="Protein correlation (across treatments)")
            out.append(p)
    return out


# -----------------------------------------------------------------------------
# self-check (numpy/scipy only; no pandas needed)
# -----------------------------------------------------------------------------
def demo() -> None:
    rng = np.random.default_rng(0)
    base = rng.normal(size=20)
    mat = np.column_stack([base, base * 2 + 1, -base, rng.normal(size=20)])
    mat[0, 1] = np.nan  # one missing -> pair (0,1) drops to n=19
    labels, rho, q, nn = _corr_matrix(mat, ["a", "b", "c", "d"])

    assert rho.shape == (4, 4)
    assert np.allclose(np.diag(rho), 1.0)
    assert rho[0, 1] > 0.99 and nn[0, 1] == 19, (rho[0, 1], nn[0, 1])
    assert rho[0, 2] < -0.99, rho[0, 2]              # perfectly anti-correlated
    assert np.allclose(rho, rho.T, equal_nan=True)   # symmetric
    off_q = q[~np.eye(4, dtype=bool)]
    fin = np.isfinite(off_q)
    assert np.all((off_q[fin] >= 0) & (off_q[fin] <= 1))
    assert np.isnan(q[0, 0])                          # diagonal has no q
    print("correlate.py self-check OK")


if __name__ == "__main__":
    demo()
