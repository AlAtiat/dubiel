"""State updates must be pure (return new copies, never mutate)."""
from dubiel import state


def test_add_images_is_immutable():
    s0 = state.Session()
    s1 = state.add_images(s0, ["a.png", "b.png"])
    assert s0.entries == ()
    assert len(s1.entries) == 2
    assert s1.entries[0].path == "a.png"


def test_add_lane_copies():
    e = state.ImageEntry(path="a.png")
    e2 = state.add_lane(e, state.LaneSel(0, 0, 10, 5, label="Lane 1"))
    assert e.selection.lanes == ()
    assert len(e2.selection.lanes) == 1
    assert e2.selection.lanes[0].label == "Lane 1"


def test_set_ladder_lane_is_exclusive():
    e = state.ImageEntry(path="a.png")
    e = state.add_lane(e, state.LaneSel(0, 0, 10, 5))
    e = state.add_lane(e, state.LaneSel(0, 6, 10, 11))
    e = state.set_ladder_lane(e, 1)
    assert [ln.is_ladder for ln in e.selection.lanes] == [False, True]
    e = state.set_ladder_lane(e, 0)
    assert [ln.is_ladder for ln in e.selection.lanes] == [True, False]


def test_remove_lane():
    e = state.ImageEntry(path="a.png")
    e = state.add_lane(e, state.LaneSel(0, 0, 10, 5, label="keep"))
    e = state.add_lane(e, state.LaneSel(0, 6, 10, 11, label="drop"))
    e = state.remove_lane(e, 1)
    assert [ln.label for ln in e.selection.lanes] == ["keep"]


def test_set_transform_copies():
    e = state.ImageEntry(path="a.png")
    e2 = state.set_transform(e, rot90=1, invert=True)
    assert e.selection.transform.rot90 == 0
    assert e2.selection.transform.rot90 == 1 and e2.selection.transform.invert is True


def test_duplicate_lane_offsets_same_size():
    e = state.ImageEntry(path="a.png")
    e = state.add_lane(e, state.LaneSel(10, 20, 90, 60, "Lane 1"))  # width 40
    e = state.duplicate_lane(e, 0, gap=6)
    a, b = e.selection.lanes
    assert (b.x1 - b.x0) == (a.x1 - a.x0)  # same width
    assert b.x0 == a.x0 + 40 + 6 and not b.is_ladder


def test_duplicate_keeps_auto_bands():
    e = state.ImageEntry(path="a.png")
    e = state.add_lane(e, state.LaneSel(10, 20, 30, 60, "band", auto_bands=False))
    e = state.duplicate_lane(e, 0)
    assert e.selection.lanes[1].auto_bands is False  # a band stays a band


def test_ladder_point_helpers():
    e = state.ImageEntry(path="a.png")
    e = state.add_ladder_point(e, state.LadderPoint(5, 10))
    assert e.selection.ladder_points[0].kda is None
    e = state.update_ladder_point(e, 0, kda=55.0)
    assert e.selection.ladder_points[0].kda == 55.0
    e = state.remove_ladder_point(e, 0)
    assert e.selection.ladder_points == ()
