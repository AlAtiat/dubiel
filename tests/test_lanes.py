"""End-to-end lane analysis on a synthetic gel (via the engine self-check)."""
import numpy as np
from PIL import Image

from dubiel import analysis_runner, state
from dubiel._engine import LADDERS
from dubiel.gelanalyzer import lanes


def test_lanes_engine_self_check():
    lanes.demo()  # asserts bands found + MW recovered internally


def _synthetic(tmp_path, ladder_ys):
    h, w = 400, 300
    gray = np.full((h, w), 230, dtype=np.uint8)
    for y in ladder_ys:
        gray[y - 3:y + 3, 20:80] = 40
    for x0, x1 in ((120, 180), (220, 280)):
        for y in (120, 220):
            gray[y - 3:y + 3, x0:x1] = 40
    path = str(tmp_path / "syn.png")
    Image.fromarray(np.stack([gray] * 3, -1)).save(path)
    return path


def test_run_entry_bridge(tmp_path):
    n = len(LADDERS["pageruler_prestained"])  # 10 bands
    ys = list(range(40, 40 + 32 * n, 32))[:n]
    path = _synthetic(tmp_path, ys)

    entry = state.ImageEntry(path=path, protein_label="syn",
                             ladder_name="pageruler_prestained")
    entry = state.add_lane(entry, state.LaneSel(10, 20, 390, 80, "ladder", True))
    entry = state.add_lane(entry, state.LaneSel(10, 120, 390, 180, "A"))
    entry = state.add_lane(entry, state.LaneSel(10, 220, 390, 280, "B"))

    assert analysis_runner.validate(entry) is None
    df = analysis_runner.run_entry(entry, str(tmp_path / "out"))
    assert not df.empty
    assert df.attrs["mw_fit"]["r2"] > 0.9
    samples = df[~df["is_ladder"]]
    assert samples["mw_kda"].notna().all() and len(samples) >= 4


def test_run_entry_manual_ladder(tmp_path):
    # only 5 visible ladder bands, but manual markers calibrate anyway.
    path = _synthetic(tmp_path, [50, 100, 150, 200, 250])
    entry = state.ImageEntry(path=path, protein_label="A", ladder_mode="manual")
    entry = state.add_lane(entry, state.LaneSel(10, 120, 390, 180, "A"))
    for y, k in [(50, 100.0), (150, 50.0), (250, 25.0)]:
        entry = state.add_ladder_point(entry, state.LadderPoint(50, y, kda=k))
    assert analysis_runner.validate(entry) is None
    df = analysis_runner.run_entry(entry, str(tmp_path / "out"))
    assert not df.empty and df["mw_kda"].notna().all()
    assert df.attrs["mw_fit"]["r2"] > 0.9


def test_run_entry_ladder_mismatch_is_friendly(tmp_path):
    path = _synthetic(tmp_path, [50, 100, 150, 200, 250])  # only 5 ladder bands
    entry = state.ImageEntry(path=path, ladder_name="pageruler_prestained")
    entry = state.add_lane(entry, state.LaneSel(10, 20, 390, 80, "ladder", True))
    try:
        analysis_runner.run_entry(entry, str(tmp_path / "out"))
        assert False, "expected a ValueError for ladder band-count mismatch"
    except ValueError as exc:
        assert "preset" in str(exc)
