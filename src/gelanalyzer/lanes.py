"""Box-per-lane analysis with a ladder lane for MW calibration.

The Toga app lets the user draw one box per lane, name each, tag one as the
ladder, and pick a ladder preset. This module turns those boxes into quantified
bands + molecular weights. It reuses the existing detection / integration /
calibration primitives; the only new thing is the orchestration and a shared
image `Transform` (rotate / flip / invert) applied identically for display and
analysis so coordinates always line up.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from . import results
from .detect import band_signal, detect_bands, load_image, smooth_profile
from .ladder import fit_mw, resolve_ladder


@dataclass(frozen=True)
class Transform:
    """Display/analysis transform, applied identically on both sides."""

    rot90: int = 0       # number of counter-clockwise 90° turns
    flip_h: bool = False
    flip_v: bool = False
    invert: bool = False


def apply_transform(rgb: np.ndarray, gray: np.ndarray, t: Transform):
    """Apply rotate -> flips -> invert to (rgb uint8, gray float). Pure."""
    k = t.rot90 % 4
    if k:
        rgb = np.rot90(rgb, k=k)
        gray = np.rot90(gray, k=k)
    if t.flip_h:
        rgb = np.fliplr(rgb)
        gray = np.fliplr(gray)
    if t.flip_v:
        rgb = np.flipud(rgb)
        gray = np.flipud(gray)
    if t.invert:
        rgb = 255 - rgb
        gray = 1.0 - gray
    return np.ascontiguousarray(rgb), np.ascontiguousarray(gray)


def _strongest(profile: np.ndarray, peaks: list[int], n: int) -> list[int]:
    """Keep the n most prominent peaks, restored to positional order."""
    from scipy.signal import peak_prominences

    if len(peaks) <= n:
        return peaks
    prom = peak_prominences(profile, peaks)[0]
    keep = np.array(peaks)[np.argsort(prom)[::-1][:n]]
    return sorted(int(p) for p in keep)


def _lane_bands(sig: np.ndarray, box) -> tuple[np.ndarray, list[int]]:
    """Smoothed profile along migration + detected band y-indices within box."""
    y0, x0, y1, x1 = box
    crop = sig[y0:y1, x0:x1]
    profile = smooth_profile(crop.mean(axis=1))
    return profile, detect_bands(profile)


def _box_volume(sig, box, pad=3):
    """Bio-Rad volume box: raw volume + local-background adjusted volume.

    Local background = mean of the pixels in the ring just outside the box,
    times the box area (rolling-disc analogue for a rectangular ROI).
    """
    by0, bx0, by1, bx1 = box
    h, w = sig.shape
    volume = float(sig[by0:by1, bx0:bx1].sum())
    py0, px0 = max(by0 - pad, 0), max(bx0 - pad, 0)
    py1, px1 = min(by1 + pad, h), min(bx1 + pad, w)
    outer = float(sig[py0:py1, px0:px1].sum())
    box_area = (by1 - by0) * (bx1 - bx0)
    ring_area = (py1 - py0) * (px1 - px0) - box_area
    bg_mean = (outer - volume) / ring_area if ring_area > 0 else 0.0
    adjusted = max(volume - bg_mean * box_area, 0.0)
    return volume, adjusted


def analyze_lanes(path: str, *, lanes: Sequence[dict], ladder=None,
                  manual_ladder: Optional[Sequence[tuple[float, float]]] = None,
                  transform: Transform = Transform(), gel_label: Optional[str] = None,
                  outdir: str = "results", max_dim: int = 2000) -> pd.DataFrame:
    """Quantify one or more analysis boxes; calibrate kDa from a ladder if given.

    lanes : [{"box": (y0,x0,y1,x1), "label": str, "is_ladder": bool,
              "auto_bands": bool}, ...]
        auto_bands True  -> a lane: auto-detect + integrate every band inside.
        auto_bands False -> one band: integrate the whole box (adjusted volume,
                            local background) for a faint / hand-picked signal.
    ladder        : preset name (LADDERS) or kDa list; from the is_ladder box.
    manual_ladder : [(abs_y, kDa), ...]; when given (>=2) overrides ``ladder``.

    A ladder is optional: with neither, bands are quantified with mw_kda = NaN.
    """
    if not lanes:
        raise ValueError("Draw at least one box before analyzing.")

    rgb, gray = load_image(path, max_dim=max_dim)
    rgb, gray = apply_transform(rgb, gray, transform)
    sig = band_signal(gray)
    name = os.path.splitext(os.path.basename(path))[0]

    per_lane = []
    for i, ln in enumerate(lanes):
        box = tuple(int(v) for v in ln["box"])
        profile, bands = _lane_bands(sig, box)  # for ladder calibration + auto boxes
        per_lane.append({
            "box": box, "label": ln.get("label") or f"Box {i + 1}",
            "is_ladder": bool(ln.get("is_ladder")),
            "auto": ln.get("auto_bands", True), "profile": profile, "bands": bands,
        })

    predict, mw_fit = _calibrate(per_lane, ladder, manual_ladder)

    # each box is independent: auto -> its detected bands; else -> one box band.
    groups = []  # (label, box, is_ladder, [records])
    for p in per_lane:
        y0, x0, y1, x1 = p["box"]
        if p["auto"]:
            recs = []
            for b in p["bands"]:
                inten = float(results.integrate_band(p["profile"], b))
                recs.append({"y": y0 + b, "x": (x0 + x1) // 2, "manual": False,
                             "intensity": inten, "volume": inten})
        else:
            volume, adjusted = _box_volume(sig, p["box"])
            recs = [{"y": (y0 + y1) // 2, "x": (x0 + x1) // 2, "manual": True,
                     "intensity": adjusted, "volume": volume}]
        recs.sort(key=lambda r: r["y"])
        groups.append((p["label"], p["box"], p["is_ladder"], recs))

    totals = {label: (sum(r["intensity"] for r in recs) or 1.0)
              for label, _box, _lad, recs in groups}

    rows = []
    for label, box, is_ladder, recs in groups:
        total = totals[label]
        y0 = box[0]
        lanelen = box[2] - box[0]
        for idx, r in enumerate(recs):
            ay = r["y"]
            inten = r["intensity"]
            rows.append({
                "image": name, "gel_label": gel_label or name, "lane_label": label,
                "is_ladder": is_ladder,
                "band_idx": idx, "y_px": int(ay), "band_x": int(r["x"]),
                "mw_kda": round(float(predict(ay)), 2) if predict else np.nan,
                "rf": round((ay - y0) / lanelen, 4) if lanelen else np.nan,
                "manual": r["manual"],
                "raw_intensity": round(inten, 2),
                "volume": round(r.get("volume", inten), 2),
                "adjusted_volume": round(inten, 2),
                "lane_total": round(total, 2),
                "pct_of_lane": round(inten / total * 100, 2),
            })

    df = pd.DataFrame(rows)
    if mw_fit is not None:
        df.attrs["mw_fit"] = mw_fit

    _annotate_lanes(rgb, per_lane, predict,
                    out_path=os.path.join(outdir, f"{name}_overlay.png"))
    if not df.empty:
        results.export(df, outdir, name)
        try:
            results.plot_intensities(
                df, out_path=os.path.join(outdir, f"{name}_intensity.png"))
        except Exception:  # charting must never block the numbers
            pass
    if mw_fit:
        print(f"MW calibration r^2 = {mw_fit['r2']}")
    return df


def _calibrate(per_lane, ladder, manual_ladder):
    """Return (predict, mw_fit). Manual points override a preset ladder lane."""
    manual = [(float(y), float(k)) for y, k in (manual_ladder or [])]
    if len(manual) >= 2:
        predict, (slope, intercept, r2) = fit_mw([y for y, _ in manual],
                                                 [k for _, k in manual])
        return predict, {"slope": slope, "intercept": intercept, "r2": round(r2, 4)}
    if ladder is None:
        return None, None
    kda = resolve_ladder(ladder)
    ladders = [p for p in per_lane if p["is_ladder"]]
    if len(ladders) != 1:
        raise ValueError("Tag exactly one lane as the ladder to calibrate MW.")
    lad = ladders[0]
    bands = lad["bands"]
    if len(bands) < len(kda):
        raise ValueError(
            f"Ladder lane has {len(bands)} detected bands but preset needs "
            f"{len(kda)}. Enlarge the ladder box, pick a matching preset, or use "
            "Manual ladder to click the visible bands and enter their kDa.")
    bands = _strongest(lad["profile"], bands, len(kda))
    abs_y = [lad["box"][0] + b for b in bands]
    predict, (slope, intercept, r2) = fit_mw(abs_y, kda)
    return predict, {"slope": slope, "intercept": intercept, "r2": round(r2, 4)}


def _annotate_lanes(rgb, per_lane, predict, out_path) -> None:
    from matplotlib.patches import Rectangle

    from ._plot import figure

    fig = figure(figsize=(12, 9))
    ax = fig.subplots()
    ax.imshow(rgb)
    ax.axis("off")
    for p in per_lane:
        y0, x0, y1, x1 = p["box"]
        # yellow=ladder, orange=single-band box, cyan=auto lane
        color = "yellow" if p["is_ladder"] else ("cyan" if p["auto"] else "orange")
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                               edgecolor=color, linewidth=2))
        ax.text(x0, y0 - 6, p["label"], color=color, fontsize=9, va="bottom")
        marks = p["bands"] if p["auto"] else [(y1 - y0) // 2]
        for b in marks:
            yy = y0 + b
            ax.plot([x0, x1], [yy, yy], color="red", linewidth=1)
            if p["is_ladder"] and predict is not None:
                ax.text(x1 + 4, yy, f"{float(predict(yy)):.0f}", color="yellow",
                        fontsize=7, va="center")
    fig.tight_layout()
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")


# -----------------------------------------------------------------------------
# self-check
# -----------------------------------------------------------------------------
def demo() -> None:
    import tempfile

    from PIL import Image as PILImage

    # synthetic light gel with dark horizontal bands in 3 lanes.
    h, w = 400, 300
    gray = np.full((h, w), 230, dtype=np.uint8)
    lane_x = [(20, 80), (120, 180), (220, 280)]
    ladder_y = [50, 100, 150, 200, 250]
    sample_y = [120, 220]
    for (x0, x1) in lane_x[:1]:  # ladder lane
        for y in ladder_y:
            gray[y - 3:y + 3, x0:x1] = 40
    for (x0, x1) in lane_x[1:]:
        for y in sample_y:
            gray[y - 3:y + 3, x0:x1] = 40
    rgb = np.stack([gray] * 3, axis=-1)
    path = os.path.join(tempfile.mkdtemp(), "synthetic.png")
    PILImage.fromarray(rgb).save(path)

    kda = [100, 70, 50, 35, 25]
    lanes = [
        {"box": (10, 20, 390, 80), "label": "ladder", "is_ladder": True},
        {"box": (10, 120, 390, 180), "label": "sampleA", "is_ladder": False},
        {"box": (10, 220, 390, 280), "label": "sampleB", "is_ladder": False},
    ]
    out = tempfile.mkdtemp()
    df = analyze_lanes(path, lanes=lanes, ladder=kda, outdir=out)

    assert not df.empty, "no bands quantified"
    lad = df[df["is_ladder"]]
    assert len(lad) == len(kda), f"ladder bands {len(lad)} != {len(kda)}"
    samples = df[~df["is_ladder"]]
    assert len(samples) >= 4, f"expected >=4 sample bands, got {len(samples)}"
    assert df.attrs["mw_fit"]["r2"] > 0.9, df.attrs["mw_fit"]

    # manual ladder: type a few (y, kDa) points -> interpolate, no ladder lane.
    manual = [(50, 100.0), (150, 50.0), (250, 25.0)]
    dfm = analyze_lanes(path, lanes=lanes[1:], ladder=None,
                        manual_ladder=manual, outdir=out)
    assert not dfm.empty and dfm["mw_kda"].notna().all(), "manual ladder failed"
    assert dfm.attrs["mw_fit"]["r2"] > 0.9, dfm.attrs["mw_fit"]

    # ladder is optional: no calibration -> NaN MW but still quantified.
    df0 = analyze_lanes(path, lanes=[dict(lanes[1], is_ladder=False)], outdir=out)
    assert not df0.empty and df0["mw_kda"].isna().all()

    # rf column present and in range.
    dfr = analyze_lanes(path, lanes=lanes, ladder=kda, outdir=out)
    assert dfr["rf"].between(0, 1).all(), "rf out of range"

    # single-band box (auto_bands=False): whole box -> exactly one band.
    band_box = {"box": (100, 120, 140, 180), "label": "faint", "auto_bands": False}
    dfb = analyze_lanes(path, lanes=[band_box], ladder=None, outdir=out)
    assert len(dfb) == 1 and dfb["manual"].all(), f"expected 1 band, got {len(dfb)}"
    mr = dfb.iloc[0]
    assert mr["raw_intensity"] > 0
    assert mr["adjusted_volume"] <= mr["volume"], (mr["adjusted_volume"], mr["volume"])
    # same box with auto on -> may find its own bands (>=1), i.e. lane behaviour.
    dfa = analyze_lanes(path, lanes=[dict(band_box, auto_bands=True)], outdir=out)
    assert not dfa["manual"].any()

    # transform round-trip is pure and shape-consistent
    r2, g2 = apply_transform(rgb, gray.astype(float) / 255, Transform(rot90=1))
    assert r2.shape[0] == w and r2.shape[1] == h
    print("lanes.py self-check OK")


if __name__ == "__main__":
    demo()
