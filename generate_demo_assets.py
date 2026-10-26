"""Generate real example figures for Dubiel's README/docs by running the actual
analysis engine on synthetic, ground-truth Western-blot images.

Nothing here is a mockup: every PNG is produced by src/dubiel's real code path
(analyze_lanes -> viz.render_entry -> combine.*), exercised on synthetic images
with known band positions/intensities so the output can be checked against the
expected numbers. Run from the project root with:

    python generate_demo_assets.py

Requires the project's src/ on sys.path (added below) and numpy/pandas/scipy/
scikit-image/matplotlib/pillow (already installed in this environment).
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import numpy as np
from PIL import Image

from dubiel.analysis_runner import run_entry
from dubiel.gelanalyzer import combine
from dubiel.state import ImageEntry, LaneSel, Selection

OUT_IMAGES = os.path.join(ROOT, "resources", "images")
TMP_GELS = os.path.join(ROOT, "resources", "demo_gels")
os.makedirs(OUT_IMAGES, exist_ok=True)
os.makedirs(TMP_GELS, exist_ok=True)

rng = np.random.default_rng(42)

# Known-truth ladder: 5 bands, evenly spaced, exact kDa values we will recover.
LADDER_KDA = [100.0, 70.0, 50.0, 35.0, 25.0]
LANES = ["Control", "MG132", "MLN4924", "Bortezomib"]
# True relative band intensity per lane, as % of Control (this is what the
# pipeline must recover from the rendered pixels).
TRUE_PCT = {
    "TargetProtein": [100, 42, 68, 30],
    "LoadingControl": [100, 97, 101, 99],
    "LC3II": [100, 210, 165, 240],
}


def make_blot_png(path: str, lane_intensity: dict[str, float], band_y: int,
                   seed: int) -> dict[str, tuple[int, int, int, int]]:
    """Render a synthetic Western blot: 1 ladder lane + N sample lanes, one band
    each at the same migration position (so lane intensity ratio == band ratio).
    Adds a slow illumination gradient (as a real phone photo would) plus small
    per-lane y-jitter and photon noise, so band_signal's background flattening
    and detect_bands are genuinely exercised, not handed a trivial image.
    """
    h, w = 420, 60 + 90 * (len(lane_intensity) + 1)
    local_rng = np.random.default_rng(seed)
    base = np.full((h, w), 235.0)
    # slow illumination gradient across the photo (what band_signal must remove)
    yy, xx = np.mgrid[0:h, 0:w]
    base -= 18.0 * (xx / w) + 10.0 * (yy / h)
    base += local_rng.normal(0, 1.5, size=base.shape)  # photon noise

    boxes: dict[str, tuple[int, int, int, int]] = {}
    lane_w = 70
    x = 25
    # ladder lane: 5 evenly spaced bands at known y -> known kDa (linear in log10 MW)
    ladder_y0 = 40
    ladder_y1 = h - 40
    ladder_ys = np.linspace(ladder_y0, ladder_y1, len(LADDER_KDA)).astype(int)
    for y in ladder_ys:
        base[y - 4:y + 4, x:x + lane_w] -= 150.0
    boxes["Ladder"] = (ladder_y0 - 15, x, ladder_y1 + 15, x + lane_w)
    x += lane_w + 20

    for name, pct in lane_intensity.items():
        jitter = int(local_rng.normal(0, 2))
        y = band_y + jitter
        depth = 150.0 * min(pct / 100.0, 1.3)  # darker band = more protein
        base[y - 5:y + 5, x:x + lane_w] -= depth
        boxes[name] = (20, x, h - 20, x + lane_w)
        x += lane_w + 20

    img = np.clip(base, 0, 255).astype(np.uint8)
    Image.fromarray(np.stack([img] * 3, axis=-1)).save(path)
    return boxes


def build_entry(protein: str, path: str, boxes: dict, seed_pcts: list[float]) -> ImageEntry:
    lanes = []
    for label, (y0, x0, y1, x1) in boxes.items():
        lanes.append(LaneSel(y0=y0, x0=x0, y1=y1, x1=x1, label=label,
                              is_ladder=(label == "Ladder"), auto_bands=True))
    entry = ImageEntry(path=path, mode="western", protein_label=protein,
                       ladder_name="", selection=Selection(lanes=tuple(lanes)))
    return entry


def main() -> None:
    entries = []
    band_y_by_protein = {"TargetProtein": 150, "LoadingControl": 260, "LC3II": 200}
    # 2 biological replicate gels per protein (independent photon noise + +-5%
    # true-signal jitter), so Welch's t-test has the >=2 replicates/lane it needs
    # to draw significance brackets. Only replicate 1's figures are used in the
    # README gallery (name == protein, no suffix); replicate 2 only contributes
    # to the combined statistics.
    for protein, pcts in TRUE_PCT.items():
        for rep in (1, 2):
            name = protein if rep == 1 else f"{protein}_rep{rep}"
            path = os.path.join(TMP_GELS, f"{name}.png")
            rep_pcts = [p * (1.0 + 0.05 * np.sin(rep + i)) for i, p in enumerate(pcts)]
            lane_intensity = dict(zip(LANES, rep_pcts))
            boxes = make_blot_png(path, lane_intensity, band_y_by_protein[protein],
                                   seed=(hash(protein) + rep) % (2**32))
            entry = build_entry(protein, path, boxes, rep_pcts)
            # Ladder calibration: pass the exact kDa list as the "ladder"
            # (resolve_ladder accepts a raw list), so MW recovery can be
            # checked against LADDER_KDA.
            from dataclasses import replace
            entry = replace(entry, ladder_name="__custom__")
            df = run_entry_with_custom_ladder(entry)
            entries.append(_Entry(protein, path, entry.selection, df))

    # Per-gel outputs are already written by run_entry_with_custom_ladder above
    # (montage, profiles, overlay_profile, surfaces, trend, per-gel correlation).

    # Combined outputs across both "proteins" (panel, 3D, stats, significance, corr).
    combine.combine_entries(entries, OUT_IMAGES, error_bars=True, significance=True,
                             ylabel="% of control (intensity)")

    # Standalone decay/half-life example (independent of the lane pipeline).
    t = np.array([0, 2, 4, 8, 16, 24], dtype=float)
    y = 100.0 * np.exp(-0.085 * t) + rng.normal(0, 1.5, size=t.shape)
    fit = combine.fit_decay(t, y, out_path=os.path.join(OUT_IMAGES, "decay_halflife.png"))
    print("decay fit:", fit)

    print("Demo assets written to", OUT_IMAGES)
    for f in sorted(os.listdir(OUT_IMAGES)):
        print(" -", f)


class _Entry:
    """Minimal duck-typed entry combine.py expects (protein_label/result_df/path)."""

    def __init__(self, protein_label, path, selection, result_df):
        self.protein_label = protein_label
        self.path = path
        self.selection = selection
        self.result_df = result_df


def run_entry_with_custom_ladder(entry):
    """Like analysis_runner.run_entry, but passes our known kDa list directly
    (bypassing the preset-name lookup) so MW calibration is checked against
    LADDER_KDA exactly."""
    import pandas as pd

    from dubiel._engine import analyze_lanes, viz

    lanes = [{"box": (ln.y0, ln.x0, ln.y1, ln.x1), "label": ln.label,
              "is_ladder": ln.is_ladder, "auto_bands": ln.auto_bands}
             for ln in entry.selection.lanes]
    df = analyze_lanes(entry.path, lanes=lanes, ladder=LADDER_KDA,
                        transform=entry.selection.transform,
                        gel_label=entry.protein_label, outdir=OUT_IMAGES)
    fit = df.attrs.get("mw_fit")
    assert fit and fit["r2"] > 0.99, f"ladder calibration r2 too low: {fit}"
    predict = (lambda y: 10 ** (fit["slope"] * y + fit["intercept"]))
    name = os.path.splitext(os.path.basename(entry.path))[0]
    viz.render_entry(entry.path, lanes=lanes, transform=entry.selection.transform,
                      mw_predict=predict, outdir=OUT_IMAGES, name=name,
                      title_label=entry.protein_label, max_dim=2000)
    viz.gel_trend(df, out_path=os.path.join(OUT_IMAGES, f"{name}_trend.png"))

    from dubiel.gelanalyzer import correlate
    fake_entry = _Entry(entry.protein_label, entry.path, entry.selection, df)
    correlate.gel_correlation(fake_entry, os.path.join(OUT_IMAGES, f"{name}_corr.png"))
    return df


if __name__ == "__main__":
    main()
