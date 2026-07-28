"""Embedded native-canvas annotator (lives in the main window).

One box type: draw a box (Box mode); its "detect bands" flag decides whether it
is a lane (auto-detect bands) or a single band. Ladder mode clicks marker dots.
Crop mode draws a membrane guide. Pan mode + zoom buttons navigate. Click any
box (in Box/Crop mode) to select and drag it. Emits an updated ``ImageEntry``.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import numpy as np
import toga
from PIL import Image as PILImage
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from . import state
from ._engine import apply_transform, load_image
from .state import BoxSel, ImageEntry, LadderPoint, LaneSel

LANE_COLOR = "#0AC2FF"       # auto-detect lane boxes (cyan)
LADDER_COLOR = "#FFD400"     # ladder box (yellow)
BAND_COLOR = "#FF9500"       # single-band boxes (orange)
CROP_COLOR = "#FF3B30"       # membrane crop (red)
LADDER_PT_COLOR = "#FF44FF"  # manual ladder markers (magenta)
SELECT_COLOR = "#FF0000"     # selected-box highlight (red)
MIN_BOX = 6                  # px, ignore tiny drags


@lru_cache(maxsize=8)
def _load_base(path: str, max_dim: int):
    """Cached decode+downscale so re-selecting an image is instant."""
    return load_image(path, max_dim)


def _toga_image(arr: np.ndarray) -> toga.Image:
    pil = PILImage.fromarray(np.ascontiguousarray(arr))
    try:
        return toga.Image(pil)
    except Exception:  # pragma: no cover - backend without PIL src support
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return toga.Image(data=buf.getvalue())


class CanvasPanel:
    """Reusable annotator widget. ``self.box`` is added to the main window."""

    def __init__(self, on_change, on_crop=None, max_dim: int = 2000) -> None:
        self.on_change = on_change
        self.on_crop = on_crop           # called with a cropped rgb array -> new image
        self.max_dim = max_dim
        self.entry: ImageEntry | None = None
        self.mode = "box"  # "box" | "ladder" | "crop"
        self.auto_default = True  # new boxes get this "detect bands" value
        self.selected: tuple[str, int] | None = None  # ("lane"|"crop", index)

        self._path: str | None = None
        self._base_rgb = self._base_gray = self._disp_rgb = None
        self.iw = self.ih = 0
        self._img: toga.Image | None = None

        self.cw = self.ch = 0
        self.scale = 1.0
        self.ox = self.oy = 0.0
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0.0
        self._drag: tuple[float, float, float, float] | None = None
        self._move_orig: tuple[int, int, int, int, float, float] | None = None
        self._move_box: tuple[int, int, int, int] | None = None
        self._zoom_start = None  # (x0, y0, ipx, ipy, zoom, pan_x, pan_y)

        self._build()

    # -- construction ---------------------------------------------------------
    def _build(self) -> None:
        self.canvas = toga.Canvas(
            style=Pack(flex=1, background_color="#E6E6E6"),
            on_resize=self._on_resize, on_press=self._on_press,
            on_drag=self._on_drag, on_release=self._on_release,
            on_alt_press=self._on_alt_press, on_alt_drag=self._on_alt_drag,
            on_alt_release=self._on_alt_release)

        def btn(label, handler):
            return toga.Button(label, on_press=handler, style=Pack(margin=2))

        modes = toga.Box(style=Pack(direction=ROW, margin=(4, 4, 0, 4), gap=4))
        modes.add(btn("Box", lambda w: self._set_mode("box")))
        modes.add(btn("Ladder", lambda w: self._set_mode("ladder")))
        modes.add(btn("Crop", lambda w: self._set_mode("crop")))
        modes.add(btn("Duplicate", lambda w: self._duplicate()))
        modes.add(btn("Delete", lambda w: self._delete()))

        edit = toga.Box(style=Pack(direction=ROW, margin=(2, 4, 4, 4), gap=4))
        edit.add(btn("Rotate ⟳", lambda w: self._rotate()))
        edit.add(btn("Flip ↔", lambda w: self._flip("flip_h")))
        edit.add(btn("Flip ↕", lambda w: self._flip("flip_v")))
        edit.add(btn("Invert", lambda w: self._invert()))
        edit.add(btn("Undo", lambda w: self._undo()))
        edit.add(btn("Clear", lambda w: self._clear()))

        self.status = toga.Label("Add an image to begin.", style=Pack(margin=(0, 6, 4, 6)))
        self.box = toga.Box(style=Pack(direction=COLUMN, flex=1),
                            children=[modes, edit, self.status, self.canvas])
   
    # -- public API -----------------------------------------------------------
    def preload(self, path: str):
        """Decode/downscale an image without touching Toga widgets.

        Safe to run on a worker thread. The result is cached by _load_base().
        """
        return _load_base(path, self.max_dim)
    def base_rgb(self, path: str) -> np.ndarray:
        return _load_base(path, self.max_dim)[0]

    def load(self, entry: ImageEntry | None) -> None:
        self.entry = entry
        self.selected = None
        if entry is None:
            self._img = None
            self._redraw()  # shows the logo + dedication placeholder
            self.status.text = "Add an image to begin."
            return
        if entry.path != self._path:
            self._path = entry.path
            self._base_rgb, self._base_gray = _load_base(entry.path, self.max_dim)
            self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
        self._recompute_display()
        self._fit()
        self._redraw()
        self._update_status()

    def refresh(self, entry: ImageEntry) -> None:
        """Redraw for a label/kDa/flag change that did not alter geometry."""
        self.entry = entry
        self._redraw()
        self._update_status()

    # -- view transform -------------------------------------------------------
    def _recompute_display(self) -> None:
        rgb, _ = apply_transform(self._base_rgb, self._base_gray,
                                 self.entry.selection.transform)
        self._disp_rgb = rgb             # what's shown; crop is sliced from this
        self.ih, self.iw = rgb.shape[:2]
        self._img = _toga_image(rgb)

    def _fit(self) -> None:
        if self.cw <= 0 or self.ch <= 0 or self.iw == 0:
            self.scale, self.ox, self.oy = 1.0, 0.0, 0.0
            return
        base = min(self.cw / self.iw, self.ch / self.ih)
        self.scale = base * self.zoom
        self.ox = (self.cw - self.iw * self.scale) / 2 + self.pan_x
        self.oy = (self.ch - self.ih * self.scale) / 2 + self.pan_y

    # -- right-mouse drag = zoom (vertical, about cursor) + pan (horizontal) ---
    def _on_alt_press(self, widget, x, y, **kw) -> None:
        ipx, ipy = self._to_img(x, y)
        self._zoom_start = (x, y, ipx, ipy, self.zoom, self.pan_x, self.pan_y)

    def _on_alt_drag(self, widget, x, y, **kw) -> None:
        if self._zoom_start is None:
            return
        x0, y0, ipx, ipy, z0, px0, py0 = self._zoom_start
        import math
        self.zoom = min(max(z0 * math.exp(-(y - y0) * 0.004), 0.2), 12.0)
        base = min(self.cw / self.iw, self.ch / self.ih) if self.iw else 1.0
        scale = base * self.zoom
        dx = x - x0  # horizontal drag also pans
        # keep the pressed image point under the original cursor x0, then add dx
        self.pan_x = x0 + dx - ipx * scale - (self.cw - self.iw * scale) / 2
        self.pan_y = y0 - ipy * scale - (self.ch - self.ih * scale) / 2
        self._fit()
        self._redraw()
        self._update_status()

    def _on_alt_release(self, widget, x, y, **kw) -> None:
        self._zoom_start = None

    def _to_img(self, cx, cy):
        return (cx - self.ox) / self.scale, (cy - self.oy) / self.scale

    def _to_canvas(self, ix, iy):
        return ix * self.scale + self.ox, iy * self.scale + self.oy

    def _in_image(self, ix, iy) -> bool:
        return 0 <= ix <= self.iw and 0 <= iy <= self.ih

    def _hit(self, ix, iy) -> tuple[str, int] | None:
        sel = self.entry.selection
        for kind, boxes in (("lane", sel.lanes), ("crop", sel.crops)):
            for i in range(len(boxes) - 1, -1, -1):  # top-most first
                b = boxes[i]
                if b.x0 <= ix <= b.x1 and b.y0 <= iy <= b.y1:
                    return (kind, i)
        return None

    def _coords(self, kind, i, stored):
        if self.selected == (kind, i) and self._move_box is not None:
            return self._move_box
        return stored

    # -- drawing --------------------------------------------------------------
    def _placeholder_logo(self):
        if not hasattr(self, "_ph_logo"):
            p = Path(__file__).parent / "icons" / "dugiel.png"
            try:
                self._ph_logo = toga.Image(str(p)) if p.exists() else None
            except Exception:  # pragma: no cover - decode/backend issue
                self._ph_logo = None
        return self._ph_logo

    def _draw_placeholder(self, c) -> None:
        """Logo + dedication centred on the empty canvas (before any image)."""
        if self.cw <= 0 or self.ch <= 0:
            return
        ty = self.ch / 2
        logo = self._placeholder_logo()
        if logo is not None:
            iw, ih = logo.size
            s = min(self.cw * 0.5 / iw, self.ch * 0.5 / ih, 1.0)
            w, h = iw * s, ih * s
            y = self.ch / 2 - h / 2 - 24
            c.draw_image(logo, (self.cw - w) / 2, y, w, h)
            ty = y + h + 22
        text = "Dedicated to Prof. Dr. rer. nat. habil. Dawadschargal Dubiel"
        try:
            tw = c.measure_text(text)[0]
        except Exception:  # pragma: no cover - backend without measure_text
            tw = len(text) * 6.0
        with c.fill(color="#555555"):
            c.fill_text(text, (self.cw - tw) / 2, ty)

    def _redraw(self) -> None:
        c = self.canvas
        c.root_state.drawing_actions.clear()
        if self._img is None:  # no image yet -> show the placeholder
            self._draw_placeholder(c)
            c.redraw()
            return
        c.draw_image(self._img, self.ox, self.oy,
                     self.iw * self.scale, self.ih * self.scale)
        sel = self.entry.selection if self.entry else None
        if sel:
            for b in sel.crops:
                self._stroke_box(b.y0, b.x0, b.y1, b.x1, CROP_COLOR)
            for i, ln in enumerate(sel.lanes):
                y0, x0, y1, x1 = self._coords("lane", i, (ln.y0, ln.x0, ln.y1, ln.x1))
                color = (LADDER_COLOR if ln.is_ladder
                         else LANE_COLOR if ln.auto_bands else BAND_COLOR)
                self._stroke_box(y0, x0, y1, x1, color)
                tag = (" (ladder)" if ln.is_ladder
                       else "" if ln.auto_bands else " (band)")
                cx, cy = self._to_canvas(x0, y0)
                with c.fill(color=color):
                    c.fill_text((ln.label or f"Box {i + 1}") + tag, cx, cy - 4)
            self._draw_ladder_points(sel.ladder_points)
            self._draw_selection()
        if self._drag is not None:
            color = {"crop": CROP_COLOR}.get(self.mode, LANE_COLOR)
            x0, y0, x1, y1 = self._drag
            self._stroke_box(min(y0, y1), min(x0, x1), max(y0, y1), max(x0, x1), color)
        c.redraw()

    def _draw_ladder_points(self, pts) -> None:
        c = self.canvas
        for i, p in enumerate(pts, 1):
            cx, cy = self._to_canvas(p.x, p.y)
            with c.fill(color=LADDER_PT_COLOR):
                c.arc(cx, cy, 5)
                label = f"{p.kda:g} kDa" if p.kda is not None else f"#{i}?"
                c.fill_text(label, cx + 8, cy)

    def _draw_selection(self) -> None:
        box = self._selected_stored()
        if box is None:
            return
        kind, i = self.selected
        y0, x0, y1, x1 = self._coords(kind, i, box)
        cx, cy = self._to_canvas(x0, y0)
        with self.canvas.stroke(color=SELECT_COLOR, line_width=4):
            self.canvas.rect(cx, cy, (x1 - x0) * self.scale, (y1 - y0) * self.scale)

    def _selected_stored(self):
        if self.selected is None:
            return None
        kind, i = self.selected
        seq = self.entry.selection.lanes if kind == "lane" else self.entry.selection.crops
        if i >= len(seq):
            return None
        o = seq[i]
        return o.y0, o.x0, o.y1, o.x1

    def _stroke_box(self, y0, x0, y1, x1, color) -> None:
        cx, cy = self._to_canvas(x0, y0)
        with self.canvas.stroke(color=color, line_width=2):
            self.canvas.rect(cx, cy, (x1 - x0) * self.scale, (y1 - y0) * self.scale)

    # -- events ---------------------------------------------------------------
    def _on_resize(self, widget, width, height, **kw) -> None:
        self.cw, self.ch = width, height
        self._fit()
        self._redraw()

    def _on_press(self, widget, x, y, **kw) -> None:
        if self.entry is None:
            return
        ix, iy = self._to_img(x, y)
        if not self._in_image(ix, iy):
            return
        hit = self._hit(ix, iy)
        if hit is not None:  # click any box -> select + move it
            self.selected = hit
            box = self._selected_stored()
            self._move_orig = (*box, ix, iy)
            self._move_box = box
            self._redraw()
            return
        if self.mode == "ladder":
            self._emit(state.add_ladder_point(
                self.entry, LadderPoint(int(ix), int(iy))))
            return
        self.selected = None  # empty space -> draw a new box
        self._drag = (ix, iy, ix, iy)
        self._redraw()

    def _on_drag(self, widget, x, y, **kw) -> None:
        ix, iy = self._to_img(x, y)
        if self._move_orig is not None:
            oy0, ox0, oy1, ox1, mx, my = self._move_orig
            dx = ix - mx
            w, h = ox1 - ox0, oy1 - oy0
            nx0 = min(max(ox0 + dx, 0), self.iw - w)
            ny0 = oy0  # horizontal-only: keep the same vertical position + height
            self._move_box = (int(ny0), int(nx0), int(ny0 + h), int(nx0 + w))
            self._redraw()
            return
        if self._drag is not None:
            ix = min(max(ix, 0), self.iw)
            iy = min(max(iy, 0), self.ih)
            x0, y0, _, _ = self._drag
            self._drag = (x0, y0, ix, iy)
            self._redraw()

    def _on_release(self, widget, x, y, **kw) -> None:
        if self._move_orig is not None:
            box, self._move_orig = self._move_box, None
            self._move_box = None
            if self.selected and box:
                kind, i = self.selected
                y0, x0, y1, x1 = box
                mover = state.update_lane if kind == "lane" else state.update_crop
                self._emit(mover(self.entry, i, y0=y0, x0=x0, y1=y1, x1=x1))
            return
        if self._drag is None:
            return
        x0, y0, x1, y1 = self._drag
        self._drag = None
        bx0, bx1 = sorted((int(x0), int(x1)))
        by0, by1 = sorted((int(y0), int(y1)))
        if (bx1 - bx0) < MIN_BOX or (by1 - by0) < MIN_BOX:
            self._redraw()
            return
        if self.mode == "crop":
            if self.on_crop is not None and self._disp_rgb is not None:
                y0, y1 = max(by0, 0), min(by1, self.ih)
                x0, x1 = max(bx0, 0), min(bx1, self.iw)
                if y1 - y0 >= MIN_BOX and x1 - x0 >= MIN_BOX:
                    self.on_crop(np.ascontiguousarray(self._disp_rgb[y0:y1, x0:x1]))
                self._redraw()  # nothing stored on this image
            else:  # fallback: store as a guide box (legacy)
                crops = self.entry.selection.crops + (BoxSel(by0, bx0, by1, bx1),)
                self._emit(state.update_selection(self.entry, crops=crops))
        else:
            n = len(self.entry.selection.lanes)
            self._emit(state.add_lane(self.entry, LaneSel(
                by0, bx0, by1, bx1, label=f"Box {n + 1}",
                auto_bands=self.auto_default)))

    # -- toolbar --------------------------------------------------------------
    def _set_mode(self, mode: str) -> None:
        self.mode = mode  # selection persists so Duplicate/Delete still work
        self._redraw()
        self._update_status()

    def _duplicate(self) -> None:
        if self.entry is None or self.selected is None or self.selected[0] != "lane":
            self.status.text = "Select a box first, then Duplicate."
            return
        i = self.selected[1]
        entry = state.duplicate_lane(self.entry, i)
        j = len(entry.selection.lanes) - 1
        b = entry.selection.lanes[j]
        w, h = b.x1 - b.x0, b.y1 - b.y0  # clamp the copy fully into view
        x0 = min(max(b.x0, 0), max(self.iw - w, 0))
        y0 = min(max(b.y0, 0), max(self.ih - h, 0))
        entry = state.update_lane(entry, j, x0=x0, y0=y0, x1=x0 + w, y1=y0 + h)
        self.selected = ("lane", j)
        self._emit(entry)

    def _delete(self) -> None:
        if self.entry is None or self.selected is None:
            self.status.text = "Select a box first, then Delete."
            return
        kind, i = self.selected
        remover = state.remove_lane if kind == "lane" else state.remove_crop
        self.selected = None
        self._emit(remover(self.entry, i))

    def _rotate(self) -> None:
        if self.entry is None:
            return
        t = self.entry.selection.transform
        self._reset_geometry(state.set_transform(self.entry, rot90=(t.rot90 + 1) % 4))

    def _flip(self, which: str) -> None:
        if self.entry is None:
            return
        cur = getattr(self.entry.selection.transform, which)
        self._reset_geometry(state.set_transform(self.entry, **{which: not cur}))

    def _reset_geometry(self, entry) -> None:
        self.selected = None
        self._emit(state.update_selection(entry, lanes=(), crops=(),
                                          ladder_points=()), reflow=True)

    def _invert(self) -> None:
        if self.entry is None:
            return
        cur = self.entry.selection.transform.invert
        self._emit(state.set_transform(self.entry, invert=not cur), reflow=True)

    def _undo(self) -> None:
        if self.entry is None:
            return
        sel = self.entry.selection
        if self.mode == "crop" and sel.crops:
            self._emit(state.update_selection(self.entry, crops=sel.crops[:-1]))
        elif self.mode == "ladder" and sel.ladder_points:
            self._emit(state.remove_ladder_point(self.entry, len(sel.ladder_points) - 1))
        elif sel.lanes:
            self._emit(state.remove_lane(self.entry, len(sel.lanes) - 1))

    def _clear(self) -> None:
        if self.entry is None:
            return
        key = {"crop": "crops", "ladder": "ladder_points"}.get(self.mode, "lanes")
        self.selected = None
        self._emit(state.update_selection(self.entry, **{key: ()}))

    # -- emit -----------------------------------------------------------------
    def _emit(self, entry: ImageEntry, reflow: bool = False) -> None:
        self.entry = entry
        if reflow:
            self._recompute_display()
            self._fit()
        self._redraw()
        self._update_status()
        self.on_change(entry)

    def _update_status(self) -> None:
        if self.entry is None:
            return
        sel = self.entry.selection
        t = sel.transform
        flags = "".join(f for f, on in
                        [("R", t.rot90), ("H", t.flip_h), ("V", t.flip_v),
                         ("I", t.invert)] if on)
        hints = {
            "box": "Drag empty space for a box; click a box to move it. "
                   "Right-drag = zoom/pan.",
            "ladder": "Click each ladder band, type its kDa on the left. "
                      "Right-drag = zoom/pan.",
            "crop": "Drag a box to crop that region into a new image; "
                    "right-drag = zoom/pan.",
        }
        self.status.text = (
            f"[{self.mode}] {hints.get(self.mode, '')}   boxes: {len(sel.lanes)}   "
            f"markers: {len(sel.ladder_points)}   zoom: {self.zoom:.1f}×   "
            f"transform: {flags or 'none'}")
