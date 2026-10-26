"""Immutable session model + pure update helpers (box/lane model).

Everything is frozen; updates return new copies (house rule: no mutation).
Coordinates are in *transformed downscaled image pixels* — the space the canvas
displays and ``analyze_lanes`` re-creates via the same ``Transform`` — so they
hand straight to the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Optional

import pandas as pd

from ._engine import Transform  # shared with the engine

Mode = Literal["western", "sds"]


@dataclass(frozen=True)
class BoxSel:
    """A membrane/gel crop rectangle in downscaled image pixels."""

    y0: int
    x0: int
    y1: int
    x1: int


@dataclass(frozen=True)
class LaneSel:
    """One analysis box. ``auto_bands`` decides its behaviour:

    True  -> a lane: auto-detect multiple bands inside it.
    False -> a single band: integrate the whole box (faint-signal / band mode).
    """

    y0: int
    x0: int
    y1: int
    x1: int
    label: str = ""
    is_ladder: bool = False
    auto_bands: bool = True


@dataclass(frozen=True)
class LadderPoint:
    """A clicked ladder band (abs image px) + its manually entered kDa."""

    x: int
    y: int
    kda: Optional[float] = None


@dataclass(frozen=True)
class Selection:
    crops: tuple[BoxSel, ...] = ()
    lanes: tuple[LaneSel, ...] = ()
    ladder_points: tuple[LadderPoint, ...] = ()
    transform: Transform = field(default_factory=Transform)


@dataclass(frozen=True, eq=False)  # holds a DataFrame
class ImageEntry:
    path: str
    mode: Mode = "western"
    protein_label: str = ""
    ladder_name: str = ""        # "" = no ladder preset (None) until the user picks one
    ladder_mode: str = "preset"  # kept for import compat; unused
    selection: Selection = field(default_factory=Selection)
    result_df: Optional[pd.DataFrame] = None
    overlay_path: Optional[str] = None


@dataclass(frozen=True, eq=False)
class Session:
    entries: tuple[ImageEntry, ...] = ()
    outdir: str = "results"


# -----------------------------------------------------------------------------
# session-level helpers
# -----------------------------------------------------------------------------
def add_images(session: Session, paths: list[str]) -> Session:
    new = tuple(ImageEntry(path=p) for p in paths)
    return replace(session, entries=session.entries + new)


def replace_entry(session: Session, index: int, entry: ImageEntry) -> Session:
    entries = list(session.entries)
    entries[index] = entry
    return replace(session, entries=tuple(entries))


def remove_image(session: Session, index: int) -> Session:
    entries = list(session.entries)
    del entries[index]
    return replace(session, entries=tuple(entries))


def with_outdir(session: Session, outdir: str) -> Session:
    return replace(session, outdir=outdir)


def update_entry(session: Session, index: int, **changes) -> Session:
    return replace_entry(session, index, replace(session.entries[index], **changes))


# -----------------------------------------------------------------------------
# entry/selection-level helpers (all pure)
# -----------------------------------------------------------------------------
def update_selection(entry: ImageEntry, **changes) -> ImageEntry:
    return replace(entry, selection=replace(entry.selection, **changes))


def add_lane(entry: ImageEntry, lane: LaneSel) -> ImageEntry:
    return update_selection(entry, lanes=entry.selection.lanes + (lane,))


def update_lane(entry: ImageEntry, index: int, **changes) -> ImageEntry:
    lanes = list(entry.selection.lanes)
    lanes[index] = replace(lanes[index], **changes)
    return update_selection(entry, lanes=tuple(lanes))


def remove_lane(entry: ImageEntry, index: int) -> ImageEntry:
    lanes = list(entry.selection.lanes)
    del lanes[index]
    return update_selection(entry, lanes=tuple(lanes))


def set_ladder_lane(entry: ImageEntry, index: int) -> ImageEntry:
    lanes = tuple(replace(ln, is_ladder=(i == index))
                  for i, ln in enumerate(entry.selection.lanes))
    return update_selection(entry, lanes=lanes)


def duplicate_lane(entry: ImageEntry, index: int, gap: int = 6) -> ImageEntry:
    """Copy a box at the same size, offset one width to the right (keeps
    auto_bands so a duplicated band stays a band, a lane stays a lane)."""
    src = entry.selection.lanes[index]
    w = src.x1 - src.x0
    dx = w + gap
    n = len(entry.selection.lanes)
    copy = replace(src, x0=src.x0 + dx, x1=src.x1 + dx,
                   label=f"Box {n + 1}", is_ladder=False)
    return add_lane(entry, copy)


def update_crop(entry: ImageEntry, index: int, **changes) -> ImageEntry:
    crops = list(entry.selection.crops)
    crops[index] = replace(crops[index], **changes)
    return update_selection(entry, crops=tuple(crops))


def remove_crop(entry: ImageEntry, index: int) -> ImageEntry:
    crops = list(entry.selection.crops)
    del crops[index]
    return update_selection(entry, crops=tuple(crops))


def add_ladder_point(entry: ImageEntry, point: LadderPoint) -> ImageEntry:
    return update_selection(
        entry, ladder_points=entry.selection.ladder_points + (point,))


def update_ladder_point(entry: ImageEntry, index: int, **changes) -> ImageEntry:
    pts = list(entry.selection.ladder_points)
    pts[index] = replace(pts[index], **changes)
    return update_selection(entry, ladder_points=tuple(pts))


def remove_ladder_point(entry: ImageEntry, index: int) -> ImageEntry:
    pts = list(entry.selection.ladder_points)
    del pts[index]
    return update_selection(entry, ladder_points=tuple(pts))


def set_transform(entry: ImageEntry, **changes) -> ImageEntry:
    return update_selection(
        entry, transform=replace(entry.selection.transform, **changes))
