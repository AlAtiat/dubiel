"""matplotlib popup pickers (Tk backend) for manual override + Western picking.

Every picker also accepts pre-supplied coordinates, so the whole pipeline can
run headless (tests, batch) by passing coords instead of clicking.
"""
from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.widgets import RectangleSelector

from .detect import GelBox


def _interactive_ok() -> bool:
    return matplotlib.get_backend().lower() not in ("agg", "template")


def pick_boxes(rgb, title="Drag a box around each gel, then close the window"):
    """Let the user drag one rectangle per gel/membrane. Returns [GelBox]."""
    if not _interactive_ok():
        raise RuntimeError(
            "No interactive backend. Run `%matplotlib tk` (or qt) in the "
            "notebook first, or pass boxes= explicitly."
        )
    boxes: list[GelBox] = []
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(rgb)
    ax.set_title(title)

    def on_select(eclick, erelease):
        x0, x1 = sorted((eclick.xdata, erelease.xdata))
        y0, y1 = sorted((eclick.ydata, erelease.ydata))
        box = GelBox(int(y0), int(x0), int(y1), int(x1))
        boxes.append(box)
        ax.add_patch(plt.Rectangle((box.x0, box.y0), box.width, box.height,
                                   fill=False, color="red", lw=2))
        ax.text(box.x0, box.y0 - 5, f"gel{len(boxes)}", color="red")
        fig.canvas.draw_idle()

    selector = RectangleSelector(ax, on_select, useblit=True, interactive=False)
    plt.show(block=True)
    del selector
    return boxes


def pick_points(image, n=-1, title="Click points, then press Enter"):
    """Click points on an image. n=-1 => until Enter/right-click. Returns [(x,y)]."""
    if not _interactive_ok():
        raise RuntimeError(
            "No interactive backend. Run `%matplotlib tk` (or qt) first, "
            "or pass the points explicitly."
        )
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(image)
    ax.set_title(title)
    pts = plt.ginput(n=n, timeout=0)
    plt.close(fig)
    return [(float(x), float(y)) for x, y in pts]


def pick_lane_centers(gel_signal, title="Click each lane center, then Enter"):
    """Click lane centers on a gel crop. Returns sorted x indices."""
    xs = [int(round(x)) for x, _ in pick_points(gel_signal, n=-1, title=title)]
    return sorted(xs)
