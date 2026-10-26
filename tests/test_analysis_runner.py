"""Boundary validation + selection->engine translation (no image needed)."""
from dubiel import analysis_runner, state


def _entry(lanes=(), ladder="pageruler_prestained", path=__file__,
           ladder_mode="preset"):
    return state.ImageEntry(path=path, ladder_name=ladder, ladder_mode=ladder_mode,
                            selection=state.Selection(lanes=lanes))


def _lane(is_ladder=False, label="Lane 1"):
    return state.LaneSel(0, 0, 100, 20, label=label, is_ladder=is_ladder)


def test_missing_file_reports_error():
    e = _entry(lanes=(_lane(),), path="does_not_exist.png")
    assert "not found" in analysis_runner.validate(e).lower()


def test_no_lanes_error():
    assert "box" in analysis_runner.validate(_entry()).lower()


def test_ladder_is_optional():
    # no ladder lane, no markers -> allowed (intensities-only)
    e = _entry(lanes=(_lane(), _lane(label="Lane 2")))
    assert analysis_runner.validate(e) is None


def test_only_one_ladder_lane():
    e = _entry(lanes=(_lane(is_ladder=True), _lane(is_ladder=True)))
    assert "one box" in analysis_runner.validate(e).lower()


def test_manual_markers_need_kda():
    e = _entry(lanes=(_lane(),), ladder_mode="manual")
    e = state.add_ladder_point(e, state.LadderPoint(5, 10, kda=100.0))
    e = state.add_ladder_point(e, state.LadderPoint(5, 20, kda=None))
    assert "kDa" in analysis_runner.validate(e)


def test_lanes_carry_auto_bands():
    e = _entry(lanes=(state.LaneSel(0, 0, 100, 20, "band", auto_bands=False),))
    assert analysis_runner._lanes(e)[0]["auto_bands"] is False


def test_valid_passes():
    e = _entry(lanes=(_lane(is_ladder=True), _lane(label="Lane 2")))
    assert analysis_runner.validate(e) is None


def test_lanes_translate_to_dicts():
    e = _entry(lanes=(state.LaneSel(1, 2, 3, 4, label="p53", is_ladder=True),))
    lanes = analysis_runner._lanes(e)
    assert lanes[0]["box"] == (1, 2, 3, 4)
    assert lanes[0]["label"] == "p53" and lanes[0]["is_ladder"] is True
