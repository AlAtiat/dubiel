"""Thread-safe matplotlib figures.

Every plot in this package runs inside a worker thread (the app analyzes/combines
off the UI thread). Switching the global backend (`matplotlib.use`) or using
pyplot's global figure manager off the main thread deadlocks. So we never touch
pyplot: build a bare `Figure` wired to the Agg canvas and `savefig` it.
"""
from __future__ import annotations

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


def figure(**kwargs) -> Figure:
    """A standalone Agg-backed Figure (no pyplot, safe from any thread)."""
    fig = Figure(**kwargs)
    FigureCanvasAgg(fig)
    return fig
