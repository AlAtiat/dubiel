"""Results sections: one per analyzed image (cropped bands + table + Z-profile +
trend + 3D). Built as standalone boxes so several can stack in the Results tab.
"""
from __future__ import annotations

import os
from typing import Callable

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN

from .state import ImageEntry


class ResultsView:
    """Builds a results section box for a given analyzed image."""

    def __init__(self, outdir_getter: Callable[[], str],
                 on_open: Callable[[object], None]) -> None:
        self.outdir_getter = outdir_getter
        self.on_open = on_open

    def section(self, entry: ImageEntry) -> toga.Box:
        box = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER,
                                  margin=(4, 8), gap=6))
        df = entry.result_df
        outdir = self.outdir_getter()
        name = os.path.splitext(os.path.basename(entry.path))[0]
        title = entry.protein_label or os.path.basename(entry.path)

        box.add(toga.Button("Open results folder", on_press=self.on_open,
                            style=Pack(margin=(6, 4))))
        box.add(toga.Label(f"▸ {title}", style=Pack(
            font_weight="bold", font_size=14, text_align=CENTER, margin=(4, 2))))
        if df is None or df.empty:
            box.add(toga.Label("No rows produced.", style=Pack(margin=6)))
            return box

        mw = df.attrs.get("mw_fit")
        if mw:
            r2 = mw.get("r2")
            box.add(toga.Label(
                f"MW calibration r² = {r2}" + ("  ⚠ low fit" if r2 and r2 < 0.98 else ""),
                style=Pack(text_align=CENTER, margin=(0, 4))))

        self._image(box, outdir, f"{name}_montage.png", "Marked bands / lanes", 200)
        box.add(toga.Divider(style=Pack(margin=(8, 0))))
        box.add(self._table(df))
        self._image(box, outdir, f"{name}_overlay_profile.png",
                    "Z profile (electropherogram)", 380)
        self._image(box, outdir, f"{name}_profiles.png", "Z profile per box", 340)
        self._image(box, outdir, f"{name}_intensity.png", "Band intensities", 280)
        self._image(box, outdir, f"{name}_trend.png", "Trend across lanes", 260)
        self._image(box, outdir, f"{name}_corr.png", "Correlation (Spearman ρ)", 320)

        surfaces = sorted(f for f in os.listdir(outdir)
                          if f.startswith(f"{name}_surface_") and f.endswith(".png")) \
            if os.path.isdir(outdir) else []
        if surfaces:
            box.add(toga.Divider(style=Pack(margin=(8, 0))))
            box.add(toga.Label("3D intensity (before / after background):", style=Pack(
                font_weight="bold", text_align=CENTER, margin=(6, 4, 0, 4))))
            for f in surfaces:
                box.add(toga.ImageView(toga.Image(os.path.join(outdir, f)),
                                       style=Pack(height=240)))
        return box

    # -- helpers --------------------------------------------------------------
    def _image(self, box, outdir, fname, title, height) -> None:
        path = os.path.join(outdir, fname)
        if not os.path.exists(path):
            return
        box.add(toga.Divider(style=Pack(margin=(8, 0))))
        block = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER, gap=4))
        block.add(toga.Label(title, style=Pack(font_weight="bold", text_align=CENTER)))
        block.add(toga.ImageView(toga.Image(path), style=Pack(height=height)))
        box.add(block)

    def _table(self, df) -> toga.Table:
        columns = [str(c) for c in df.columns]
        data = [tuple("" if v != v else str(v) for v in row)
                for row in df.itertuples(index=False)]
        return toga.Table(columns=columns, data=data, style=Pack(height=240))
