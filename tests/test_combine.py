"""Combined outputs: stacked panel + stats bar chart write without error."""
import os
import types

import numpy as np
from PIL import Image

from dubiel.gelanalyzer import combine
from dubiel.gelanalyzer.lanes import Transform, analyze_lanes


def _entry(tmp_path, protein):
    h, w = 400, 300
    gray = np.full((h, w), 230, np.uint8)
    for y in (50, 100, 150, 200, 250):
        gray[y - 3:y + 3, 20:80] = 40
    for x0, x1 in ((120, 180), (220, 280)):
        for y in (120, 220):
            gray[y - 3:y + 3, x0:x1] = 40
    p = str(tmp_path / f"{protein}.png")
    Image.fromarray(np.stack([gray] * 3, -1)).save(p)
    lanes = [{"box": (10, 20, 390, 80), "label": "ladder", "is_ladder": True},
             {"box": (10, 120, 390, 180), "label": "ctrl", "is_ladder": False},
             {"box": (10, 220, 390, 280), "label": "MG", "is_ladder": False}]
    df = analyze_lanes(p, lanes=lanes, ladder=[100, 70, 50, 35, 25],
                       outdir=str(tmp_path / "o"))
    return types.SimpleNamespace(result_df=df, protein_label=protein, path=p,
                                 selection=types.SimpleNamespace(transform=Transform()))


def test_combine_entries_writes_panel_and_stats(tmp_path):
    entries = [_entry(tmp_path, "p53"), _entry(tmp_path, "CSN5")]
    out = str(tmp_path / "combined")
    paths = combine.combine_entries(entries, out, error_bars=True,
                                    significance=True, ylabel="signal")
    names = {os.path.basename(p) for p in paths}
    assert "combined_panel.png" in names
    assert "combined_stats.png" in names
    assert os.path.exists(os.path.join(out, "combined_panel.png"))
