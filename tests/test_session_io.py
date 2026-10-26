"""Export -> import round-trips the whole configuration."""
import os

import numpy as np
from PIL import Image

from dubiel import session_io, state
from dubiel._engine import Transform


def _img(tmp_path, name):
    p = str(tmp_path / name)
    Image.fromarray(np.zeros((40, 30, 3), np.uint8)).save(p)
    return p


def test_export_import_roundtrip(tmp_path):
    e0 = state.ImageEntry(
        path=_img(tmp_path, "p53.png"), protein_label="p53",
        ladder_name="precision_plus", ladder_mode="manual",
        selection=state.Selection(
            lanes=(state.LaneSel(1, 2, 3, 4, "ladder", is_ladder=True),
                   state.LaneSel(10, 20, 30, 40, "MG", auto_bands=False)),
            ladder_points=(state.LadderPoint(5, 6, kda=55.0),),
            crops=(state.BoxSel(0, 0, 20, 20),),
            transform=Transform(rot90=1, flip_h=True, invert=True)))
    e1 = state.ImageEntry(path=_img(tmp_path, "csn5.png"), protein_label="CSN5")
    session = state.Session(entries=(e0, e1))
    combine = {"error_bars": True, "significance": False, "ylabel": "signal"}

    zip_path = str(tmp_path / "sess.zip")
    session_io.export_session(session, combine, zip_path)
    assert os.path.exists(zip_path)

    out, combo = session_io.import_session(zip_path, str(tmp_path / "data"))
    assert combo == combine
    assert len(out.entries) == 2

    a = out.entries[0]
    assert os.path.exists(a.path) and a.protein_label == "p53"
    assert a.ladder_name == "precision_plus" and a.ladder_mode == "manual"
    assert a.selection.transform == Transform(rot90=1, flip_h=True, invert=True)
    lanes = a.selection.lanes
    assert lanes[0].is_ladder and lanes[0].label == "ladder"
    assert lanes[1].auto_bands is False and lanes[1].label == "MG"
    assert a.selection.ladder_points[0].kda == 55.0
    assert a.selection.crops[0] == state.BoxSel(0, 0, 20, 20)
    assert a.result_df is None  # results are not stored
