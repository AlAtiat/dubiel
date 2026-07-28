"""Dubiel — native lane-annotator blot analyzer.

Left control panel + a tabbed area (Annotate canvas / Results). Add images
(thumbnail strip to switch), draw box-per-lane, mark ladder/reference, add
manual bands, then analyze.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import toga
from PIL import Image as PILImage
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

# The scientific stack (numpy/pandas/scipy/skimage/matplotlib) is pulled in by
# ._engine/.gelanalyzer and the modules below. Importing it takes several seconds,
# so it is deferred to _build_ui() — startup() shows a logo splash first, then the
# background task loads the engine and builds the real UI. These names are filled
# as module globals in _build_ui; every method that uses them runs post-build.
analysis_runner = results_view = session_io = state = None  # type: ignore[assignment]
_toga_image = None  # type: ignore[assignment]

NONE_ITEM = "Manual"
LADDER_ITEMS: list[str] = []          # filled in _build_ui (needs the engine)
LABEL_TO_KEY: dict[str, str] = {}
KEY_TO_LABEL: dict[str, str] = {}
SELECTED_BG = "#3A6EA5"
THUMB_W, THUMB_H = 110, 80


class _LogHandler(logging.Handler):
    """Feeds every log record into the app's in-memory buffer + Log window.

    Records can arrive from the analyze worker thread, so the widget refresh is
    marshalled onto the GUI event loop.
    """

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        self.app._log_lines.append(self.format(record))
        del self.app._log_lines[:-5000]                       # cap memory
        loop = getattr(self.app, "loop", None)
        if loop is not None:
            loop.call_soon_threadsafe(self.app._refresh_log_view)
        else:
            self.app._refresh_log_view()


class _StreamToLog:
    """File-like tee: forwards writes to the original stream (if any) and logs
    each completed line, so engine ``print()`` and stray tracebacks land in the
    Log window too."""

    def __init__(self, original, logger: logging.Logger, level: int) -> None:
        self._original = original
        self._logger = logger
        self._level = level
        self._buf = ""

    def write(self, text: str) -> int:
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line)
        return len(text)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return bool(getattr(self._original, "isatty", lambda: False)())


class Dugiel(toga.App):
    def startup(self) -> None:
        # Write under the app's guaranteed-writable data dir (cwd isn't writable in a
        # packaged/installed app -> Crop + Analyze would silently fail there).
        self._results_root = str(self.paths.data / "results")
        os.makedirs(self._results_root, exist_ok=True)

        # Clamp to the actual screen so the bottom bar stays visible on small laptops.
        w, h = 1300, 860
        try:
            sw, sh = self.screens[0].size
            w, h = min(w, int(sw * 0.92)), min(h, int(sh * 0.90))
        except Exception:
            pass
        self.main_window = toga.MainWindow(
            title=self.formal_name,
            size=(w, h),
        )
        self.main_window.content = self._splash_box()
        self.main_window.show()


    def on_running(self) -> None:
        self._ui_task = asyncio.create_task(self._build_ui_task())


    def _splash_box(self) -> toga.Box:
        """Logo-only loading screen shown while the scientific stack imports."""
        logo = toga.Image(str(Path(__file__).parent / "icons" / "dugiel.png"))

        return toga.Box(
            style=Pack(
                direction=COLUMN,
                flex=1,
                align_items=CENTER,
            ),
            children=[
                toga.Box(style=Pack(flex=1)),

                toga.ImageView(
                    logo,
                    style=Pack(width=240),
                ),

                toga.Label(
                    "If it doesn't work the second time, go home and try again "
                    "tomorrow with a clear, fresh mind.",
                    style=Pack(margin=12),
                ),

                toga.Box(style=Pack(flex=1)),
            ],
        )
    async def _build_ui_task(self, *args, **kwargs) -> None:
        await asyncio.sleep(0.05)     # yield once so the splash actually paints
        self._build_ui()

    # -- logging / log window -------------------------------------------------
    def _setup_logging(self) -> None:
        """Route app messages, warnings and caught exceptions to the Log window
        buffer + a dubiel.log file under the app data dir."""
        self._log_lines: list[str] = []
        self._log_window = None
        self._log_view = None
        root = logging.getLogger()
        if not any(isinstance(h, _LogHandler) for h in root.handlers):   # idempotent
            fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S")
            wh = _LogHandler(self)
            wh.setFormatter(fmt)
            root.addHandler(wh)
            try:
                fh = logging.FileHandler(
                    os.path.join(str(self.paths.data), "dubiel.log"), encoding="utf-8")
                fh.setFormatter(fmt)
                root.addHandler(fh)
            except OSError:
                pass
            root.setLevel(logging.INFO)
            logging.captureWarnings(True)
            # Tee stdout/stderr so engine print()s and tracebacks show in the log.
            if not isinstance(sys.stdout, _StreamToLog):
                sys.stdout = _StreamToLog(sys.stdout, logging.getLogger("stdout"),
                                          logging.INFO)
            if not isinstance(sys.stderr, _StreamToLog):
                sys.stderr = _StreamToLog(sys.stderr, logging.getLogger("stderr"),
                                          logging.ERROR)
        logging.getLogger("dugiel").info("Dubiel started — data dir: %s", self.paths.data)

    def _say(self, msg: str) -> None:
        """Set the status line and record the message in the log."""
        self.status.text = msg
        logging.getLogger("dugiel").info(msg)

    def _fail(self, prefix: str, exc: BaseException) -> None:
        """Status + full traceback in the log for a caught exception."""
        self.status.text = f"{prefix}: {exc}"
        logging.getLogger("dugiel").exception(prefix)

    def _refresh_log_view(self) -> None:
        if self._log_view is not None:
            self._log_view.value = "\n".join(self._log_lines)
            try:
                self._log_view.scroll_to_bottom()
            except AttributeError:
                pass

    def _show_log(self, widget=None) -> None:
        if self._log_window is not None:
            self._log_window.show()
            return
        self._log_view = toga.MultilineTextInput(
            readonly=True, value="\n".join(self._log_lines), style=Pack(flex=1))
        win = toga.Window(title="Dubiel — Log", size=(760, 520))
        win.content = toga.Box(style=Pack(direction=COLUMN, flex=1),
                               children=[self._log_view])
        win.on_close = self._on_log_close
        self._log_window = win
        win.show()

    def _on_log_close(self, window=None) -> bool:
        self._log_window = None
        self._log_view = None
        return True

    def _build_ui(self) -> None:
        # Deferred heavy imports (see module top); publish them as globals so the
        # rest of the methods — which run only after the UI is built — can use them.
        global analysis_runner, results_view, session_io, state, _toga_image
        global LADDER_ITEMS, LABEL_TO_KEY, KEY_TO_LABEL
        from . import analysis_runner, results_view, session_io, state
        from ._engine import LADDER_LABELS, LADDERS
        from .canvas_view import CanvasPanel, _toga_image
        LADDER_ITEMS = [LADDER_LABELS.get(k, k) for k in LADDERS]
        LABEL_TO_KEY = {LADDER_LABELS.get(k, k): k for k in LADDERS}
        KEY_TO_LABEL = {k: LADDER_LABELS.get(k, k) for k in LADDERS}

        self._setup_logging()          # buffer + handlers before the first _say()
        self.session = state.Session(outdir=self._results_root)
        self.current: int | None = None
        self._thumbs: dict[str, toga.Image] = {}
        self._kda_inputs: list[toga.TextInput] = []
        self._marker_count = 0
        self._syncing = False          # suppress on_change while we set widgets
        self._image_labels: list[str] = []
        self._busy = False             # one analyze/combine job at a time
        
        
        # ALL matplotlib rendering runs on this single thread (mpl isn't
        # thread-safe; the default pool would use several threads -> deadlock).
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mpl")

        self._crop_count = 0
        self.canvas = CanvasPanel(on_change=self._on_canvas_change,
                                  on_crop=self._on_crop)
        self.results = results_view.ResultsView(lambda: self.session.outdir,
                                                 self._open_results)

        self.image_select = toga.Selection(items=[], on_change=self._on_pick_image)
        self.protein_input = toga.TextInput(on_change=self._on_meta_change)
        self.marker_select = toga.Selection(  # None by default; pick a preset to use one
            items=[NONE_ITEM] + LADDER_ITEMS, on_change=self._on_marker_mode)
        self.lane_list = toga.Box(style=Pack(direction=COLUMN, gap=2))
        self.ladder_list = toga.Box(style=Pack(direction=COLUMN, gap=2))
        self.thumb_strip = toga.Box(style=Pack(direction=ROW, gap=4))
        self.detect_switch = toga.Switch(  # default "detect bands" for new boxes
            "Detect bands (new boxes)", value=True, on_change=self._on_detect_default)
        self.ylabel_input = toga.TextInput(placeholder="e.g. % of control")
        self.busy = toga.ActivityIndicator(style=Pack(margin=4))
        self.status = toga.Label("Add one or more gel/blot images to begin.",
                                 style=Pack(margin=6))
        self._combined: list[str] = []  # combined output PNG paths
        # Results holds a nested tab bar: one tab per image + a Combined tab.
        self.result_tabs = toga.OptionContainer(content=[
            toga.OptionItem("Results", toga.Box(children=[
                toga.Label("Analyze an image to see results.", style=Pack(margin=10))]))
        ], style=Pack(flex=1))

        self.tabs = toga.OptionContainer(content=[
            toga.OptionItem("Annotate", self.canvas.box),
            toga.OptionItem("Results", self.result_tabs),
        ], style=Pack(flex=1))

        self._build_file_menu()
        top = toga.Box(style=Pack(direction=ROW, flex=1),
                       children=[self._build_panel(), self.tabs])
        # Swap the splash out for the real UI (window already created + shown).
        self.main_window.content = toga.Box(
            style=Pack(direction=COLUMN),
            children=[top, self._build_bottom_bar()])
        self._refresh_controls()

    def _build_file_menu(self) -> None:
        f = toga.Group.FILE
        self.commands.add(
            toga.Command(self._on_add_images, text="Add images…", group=f, order=1),
            toga.Command(self._on_import, text="Import session…", group=f, order=2),
            toga.Command(self._on_export, text="Export session…", group=f, order=3),
            toga.Command(self._open_results, text="Open results folder",
                         group=f, order=4),
            toga.Command(self._show_log, text="Show log", group=f, order=5),
        )

    # -- layout ---------------------------------------------------------------
    def _build_panel(self) -> toga.Box:
        def labelled(label, widget):
            return toga.Box(style=Pack(direction=ROW, margin=(2, 6), gap=6),
                            children=[toga.Label(label, style=Pack(width=70)), widget])

        def sep():
            return toga.Divider(style=Pack(margin=(6, 4)))

        panel = toga.Box(style=Pack(direction=COLUMN, width=430, margin=6, gap=4))

        panel.add(toga.Button("Add images…", on_press=self._on_add_images,
                              style=Pack(margin=(4, 6))))
        panel.add(sep())
        panel.add(labelled("Protein", self.protein_input))
        panel.add(sep())
        panel.add(toga.Label("Boxes (name / detect / ladder / delete):",
                             style=Pack(margin=(6, 6, 0, 6))))
        panel.add(self.detect_switch)
        panel.add(self.lane_list)
        panel.add(sep())
        panel.add(toga.Label("Ladder (pick a preset, or Manual + type each kDa):",
                             style=Pack(margin=(6, 6, 0, 6))))
        panel.add(toga.Box(style=Pack(direction=ROW, margin=(0, 6)),
                           children=[self.marker_select]))
        panel.add(self.ladder_list)
        panel.add(sep())
        panel.add(toga.Box(style=Pack(direction=ROW, margin=(6, 6, 0, 6), gap=6),
                           children=[toga.Label("Y-axis (bars & trend)",
                                                style=Pack(width=130)),
                                     self.ylabel_input]))
        panel.add(sep())
        panel.add(toga.Button("Analyze", on_press=self._on_analyze,
                              style=Pack(margin=(6, 6))))
        panel.add(self.busy)
        panel.add(self.status)
        return panel

    def _build_bottom_bar(self) -> toga.Box:
        """Full-width strip under the image: ◀ / image dropdown / ▶ / thumbnails."""
        return toga.Box(
            style=Pack(direction=ROW, margin=4, gap=6, height=THUMB_H + 20),
            children=[
                toga.Button("◀", on_press=lambda w: self._step(-1),
                            style=Pack(width=44)),
                self.image_select,
                toga.Button("▶", on_press=lambda w: self._step(1),
                            style=Pack(width=44)),
                toga.ScrollContainer(content=self.thumb_strip, horizontal=True,
                                     vertical=False, style=Pack(flex=1)),
            ])

    # -- helpers --------------------------------------------------------------
    def _entry(self) -> state.ImageEntry | None:
        return None if self.current is None else self.session.entries[self.current]

    def _labels(self) -> list[str]:
        return [f"{i + 1}. {os.path.basename(e.path)}"
                for i, e in enumerate(self.session.entries)]

    def _select_current(self, index: int | None) -> None:
        self.current = index
        entry = self._entry()
        self.canvas.load(entry)
        self._marker_count = len(entry.selection.ladder_points) if entry else 0
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        labels = self._labels()
        entry = self._entry()
        enabled = entry is not None
        self._syncing = True
        try:
            if labels != self._image_labels:  # only rebuild when it changed
                self.image_select.items = labels
                self._image_labels = labels
            for w in (self.protein_input, self.marker_select):
                w.enabled = enabled
            if entry:
                if labels:
                    self.image_select.value = labels[self.current]
                self.protein_input.value = entry.protein_label
                self.marker_select.value = (KEY_TO_LABEL.get(entry.ladder_name)
                                            if entry.ladder_name else NONE_ITEM)
        finally:
            self._syncing = False
        self._rebuild_thumbnails()
        self._rebuild_lane_list()
        self._rebuild_ladder_list()

    # -- thumbnail strip ------------------------------------------------------
    def _thumb_image(self, entry) -> toga.Image:
        if entry.path not in self._thumbs:
            rgb = self.canvas.base_rgb(entry.path)

            pil = PILImage.fromarray(rgb)
            pil.thumbnail((THUMB_W * 2, THUMB_H * 2))

            import numpy as np

            self._thumbs[entry.path] = _toga_image(np.asarray(pil))

        return self._thumbs[entry.path]

    def _rebuild_thumbnails(self) -> None:
        for child in list(self.thumb_strip.children):
            self.thumb_strip.remove(child)
        for i, e in enumerate(self.session.entries):
            cv = toga.Canvas(
                style=Pack(width=THUMB_W, height=THUMB_H),
                on_press=lambda w, x, y, idx=i, **k: self._select_current(idx),
                on_resize=lambda w, width, height, en=e, **k: self._draw_thumb(
                    w, en, width, height))
            bg = SELECTED_BG if i == self.current else "#DDDDDD"
            rm = toga.Button("✕", style=Pack(height=22),
                             on_press=lambda w, idx=i: self._on_remove_image(idx))
            self.thumb_strip.add(toga.Box(
                style=Pack(direction=COLUMN, margin=2, background_color=bg),
                children=[rm, cv]))

    def _draw_thumb(self, cv, entry, width, height) -> None:
        img = self._thumb_image(entry)
        cv.root_state.drawing_actions.clear()
        iw, ih = img.size
        s = min(width / iw, height / ih) if iw and ih else 1
        cv.draw_image(img, (width - iw * s) / 2, (height - ih * s) / 2, iw * s, ih * s)
        cv.redraw()

    # -- side lists -----------------------------------------------------------
    def _rebuild_lane_list(self) -> None:
        for child in list(self.lane_list.children):
            self.lane_list.remove(child)
        entry = self._entry()
        if not entry:
            return
        for i, ln in enumerate(entry.selection.lanes):
            name = toga.TextInput(
                value=ln.label, style=Pack(flex=1),
                on_change=lambda w, idx=i: self._on_lane_label(idx, w.value))
            detect = toga.Switch(
                "detect", value=ln.auto_bands,
                on_change=lambda w, idx=i: self._on_lane_detect(idx, w.value))
            ladder = toga.Switch(
                "ladder", value=ln.is_ladder,
                on_change=lambda w, idx=i: self._on_lane_ladder(idx, w.value))
            delete = toga.Button("✕", style=Pack(width=32),
                                 on_press=lambda w, idx=i: self._on_lane_delete(idx))
            self.lane_list.add(toga.Box(style=Pack(direction=ROW, gap=4, margin=(1, 6)),
                                        children=[name, detect, ladder, delete]))

    def _rebuild_ladder_list(self) -> None:
        for child in list(self.ladder_list.children):
            self.ladder_list.remove(child)
        self._kda_inputs = []
        entry = self._entry()
        if not entry:
            return
        for i, p in enumerate(entry.selection.ladder_points):
            pos = toga.Label(f"y={p.y}", style=Pack(width=60))
            kda = toga.TextInput(
                value="" if p.kda is None else f"{p.kda:g}", placeholder="kDa",
                style=Pack(flex=1),
                on_change=lambda w, idx=i: self._on_marker_kda(idx, w.value))
            self._kda_inputs.append(kda)
            delete = toga.Button("✕", style=Pack(width=36),
                                 on_press=lambda w, idx=i: self._on_marker_delete(idx))
            self.ladder_list.add(toga.Box(
                style=Pack(direction=ROW, gap=4, margin=(1, 6)),
                children=[pos, kda, delete]))

    def _commit(self, entry: state.ImageEntry) -> None:
        self.session = state.replace_entry(self.session, self.current, entry)

    def _render_all_results(self) -> None:
        """Results = a clickable tab per analyzed image + a Combined tab."""
        content = self.result_tabs.content
        old = len(content)  # append new first, then drop old (never hit 0 items)
        analyzed = [e for e in self.session.entries if e.result_df is not None]
        if not analyzed:
            content.append("Results", toga.Box(children=[toga.Label(
                "Analyze an image to see results.", style=Pack(margin=10))]))
        else:
            for i, e in enumerate(analyzed, 1):
                title = e.protein_label or os.path.basename(e.path)
                content.append(f"{i}. {title}", toga.ScrollContainer(
                    content=self.results.section(e), style=Pack(flex=1)))
            if self._combined:
                content.append("Combined", toga.ScrollContainer(
                    content=self._combined_box(), style=Pack(flex=1)))
        # select a NEW tab before deleting the old ones (Toga won't delete the
        # currently-selected tab)
        self.result_tabs.current_tab = old
        for _ in range(old):
            del content[0]
        self.result_tabs.current_tab = 0

    def _combined_box(self) -> toga.Box:
        box = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER, margin=8, gap=6))
        box.add(toga.Button("Open results folder", on_press=self._open_results,
                            style=Pack(margin=(6, 4))))
        for i, p in enumerate(self._combined):
            if i:
                box.add(toga.Divider(style=Pack(margin=(8, 0))))
            box.add(toga.ImageView(toga.Image(p), style=Pack(height=360)))
        return box

    def _open_results(self, widget=None) -> None:
        # session.outdir is the root results folder before a run, the timestamped
        # run folder after — so this works whether or not anything was analyzed.
        folder = self.session.outdir
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606 - user-requested
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            self._fail("Could not open results folder", exc)

    def _on_crop(self, crop_array) -> None:
        """A crop region -> a new image entry (the original is kept)."""
        orig = self._entry()
        base = os.path.splitext(os.path.basename(orig.path))[0] if orig else "image"
        crops_dir = os.path.join(self._results_root, "crops")
        os.makedirs(crops_dir, exist_ok=True)
        self._crop_count += 1
        path = os.path.join(crops_dir, f"crop{self._crop_count}_{base}.png")
        try:
            PILImage.fromarray(crop_array).save(path)
        except Exception as exc:  # never crash the canvas on a bad crop
            self._fail("Crop failed", exc)
            return
        self.session = state.add_images(self.session, [path])
        self._image_labels = []          # rebuild the dropdown; stay on the original
        self._refresh_controls()
        self._say(f"Created crop image {self._crop_count} "
                  f"({os.path.basename(path)}).")

    def _on_remove_image(self, index: int) -> None:
        e = self.session.entries[index]
        self._thumbs.pop(e.path, None)
        self.session = state.remove_image(self.session, index)
        self._combined = []
        self._image_labels = []          # force the image dropdown to rebuild
        n = len(self.session.entries)
        self._select_current(None if n == 0 else min(index, n - 1))
        self._render_all_results()
        self._say(f"{n} image(s) loaded.")

    # -- event handlers -------------------------------------------------------
    async def _on_add_images(self, widget) -> None:
        if self._busy:
         return

        try:
            paths = await self.main_window.dialog(toga.OpenFileDialog(
                "Add gel / blot images", multiple_select=True,
                file_types=["png", "jpg", "jpeg", "tif", "tiff", "bmp"]))
        except ValueError:
            paths = None
        if not paths:
            return
        paths = [str(p) for p in (paths if isinstance(paths, list) else [paths])]
        self._busy = True
        self.busy.start()

        # Let Toga paint the spinner/status before loading.
        try:
            # Decode/downscale outside the Toga UI thread.
            for n, path in enumerate(paths, 1):
                self._say(
                    f"Loading {n}/{len(paths)}: "
                    f"{os.path.basename(path)}…"
                )

                await self._run(
                    self.canvas.preload,
                    path,
                )

            # only create ImageEntry objects containing paths.
            start = len(self.session.entries)
            self.session = state.add_images(self.session, paths)

            # canvas.load() now gets the already-cached image.
            self._select_current(start)

            self._say(
                f"{len(self.session.entries)} image(s) loaded."
            )

        except Exception as exc:
            self._fail("Image loading failed", exc)

            await self.main_window.dialog(
                toga.ErrorDialog(
                    "Image loading failed",
                    str(exc),
                )
            )

        finally:
            self.busy.stop()
            self._busy = False

    async def _on_export(self, widget) -> None:
        if not self.session.entries:
            self._say("Add images and configure before exporting.")
            return
        try:
            path = await self.main_window.dialog(toga.SaveFileDialog(
                "Export session", "session.zip", file_types=["zip"]))
        except ValueError:
            path = None
        if not path:
            return
        combine = {"error_bars": True, "significance": True,
                   "ylabel": self.ylabel_input.value or ""}
        try:
            session_io.export_session(self.session, combine, str(path))
        except Exception as exc:
            self._fail("Export failed", exc)
            await self.main_window.dialog(toga.ErrorDialog("Export failed", str(exc)))
            return
        self._say(f"Exported session to {os.path.basename(str(path))}.")

    async def _on_import(self, widget) -> None:
        if self._busy:
            return
        try:
            path = await self.main_window.dialog(toga.OpenFileDialog(
                "Import session", file_types=["zip"]))
        except ValueError:
            path = None
        if not path:
            return
        path = str(path)
        data_dir = os.path.join(os.path.dirname(path),
                                os.path.splitext(os.path.basename(path))[0] + "_data")
        try:
            session, combine = session_io.import_session(path, data_dir)
        except Exception as exc:
            self._fail("Import failed", exc)
            await self.main_window.dialog(toga.ErrorDialog("Import failed", str(exc)))
            return
        if not session.entries:
            self._say("Imported file had no images.")
            return
        # append so several imported sessions sit next to each other
        start = len(self.session.entries)
        self.session = state.Session(
            entries=self.session.entries + session.entries,
            outdir=self._results_root)
        self.ylabel_input.value = combine.get("ylabel", "") or ""
        self._combined = []
        self._image_labels = []   # force the image dropdown to rebuild
        self._marker_count = 0
        self._select_current(start)  # show the first newly imported image
        self._render_all_results()
        self._say(f"Imported {len(session.entries)} image(s).")

    def _on_pick_image(self, widget) -> None:
        if self._syncing:
            return
        labels = self._labels()
        if widget.value in labels and labels.index(widget.value) != self.current:
            self._select_current(labels.index(widget.value))

    def _step(self, delta: int) -> None:
        if not self.session.entries:
            return
        n = len(self.session.entries)
        self._select_current((((self.current or 0) + delta) % n))

    def _on_canvas_change(self, entry: state.ImageEntry) -> None:
        # canvas added/removed a lane/band/marker or changed the transform
        self._commit(entry)
        grew = len(entry.selection.ladder_points) > self._marker_count
        self._marker_count = len(entry.selection.ladder_points)
        self._rebuild_lane_list()
        self._rebuild_ladder_list()
        if grew and self._kda_inputs:  # type the kDa right after clicking a dot
            try:
                self._kda_inputs[-1].focus()
            except Exception:
                pass

    def _on_meta_change(self, widget) -> None:
        if self._syncing or self.current is None:
            return
        self.session = state.update_entry(
            self.session, self.current,
            protein_label=self.protein_input.value.strip())
        self.canvas.entry = self._entry()  # keep canvas building on the latest

    def _on_marker_mode(self, widget) -> None:
        if self._syncing or self.current is None:
            return
        name = "" if widget.value == NONE_ITEM else LABEL_TO_KEY.get(
            widget.value, self._entry().ladder_name)
        self.session = state.update_entry(self.session, self.current, ladder_name=name)
        self.canvas.entry = self._entry()

    def _on_marker_kda(self, index: int, value: str) -> None:
        try:
            kda = float(value) if value.strip() else None
        except ValueError:
            kda = None
        entry = state.update_ladder_point(self._entry(), index, kda=kda)
        self._commit(entry)
        self.canvas.refresh(entry)  # no rebuild -> keep text focus

    def _on_marker_delete(self, index: int) -> None:
        entry = state.remove_ladder_point(self._entry(), index)
        self._marker_count = len(entry.selection.ladder_points)
        self._commit(entry)
        self.canvas.refresh(entry)
        self._rebuild_ladder_list()

    def _on_lane_label(self, index: int, value: str) -> None:
        entry = state.update_lane(self._entry(), index, label=value)
        self._commit(entry)
        self.canvas.refresh(entry)  # no list rebuild -> keep text focus

    def _on_lane_ladder(self, index: int, value: bool) -> None:
        entry = self._entry()
        entry = state.set_ladder_lane(entry, index) if value else \
            state.update_lane(entry, index, is_ladder=False)
        self._commit(entry)
        self.canvas.refresh(entry)
        self._rebuild_lane_list()

    def _on_lane_detect(self, index: int, value: bool) -> None:
        entry = state.update_lane(self._entry(), index, auto_bands=value)
        self._commit(entry)
        self.canvas.refresh(entry)

    def _on_detect_default(self, widget) -> None:
        self.canvas.auto_default = widget.value

    def _on_lane_delete(self, index: int) -> None:
        entry = state.remove_lane(self._entry(), index)
        self._commit(entry)
        self.canvas.refresh(entry)
        self._rebuild_lane_list()

    async def _on_analyze(self, widget) -> None:
        if self._busy:  # ignore double-clicks; one matplotlib job at a time
            return
        # every image whose boxes validate; skip the empty / invalid ones.
        runnable = [i for i, e in enumerate(self.session.entries)
                    if analysis_runner.validate(e) is None]
        if not runnable:
            self._say("No analyzable image (draw a box on at least one).")
            return
        # fresh dated folder per run so outputs don't overwrite / pile up.
        self.session = state.with_outdir(self.session, self._run_dir())
        self._busy = True
        self.busy.start()
        skipped = len(self.session.entries) - len(runnable)
        try:
            for n, i in enumerate(runnable, 1):
                e = self.session.entries[i]
                self._say(f"Analyzing {n}/{len(runnable)}: "
                          f"{os.path.basename(e.path)}…")
                try:
                    df = await self._run(
                        analysis_runner.run_entry, e, self.session.outdir,
                        ylabel=self.ylabel_input.value or "")
                except Exception as exc:
                    self._fail(f"Analysis failed for {os.path.basename(e.path)}", exc)
                    await self.main_window.dialog(
                        toga.ErrorDialog("Analysis failed", f"{e.path}\n\n{exc}"))
                    continue
                self.session = state.update_entry(self.session, i, result_df=df)
            self.tabs.current_tab = 1
            self._say(f"Analyzed {len(runnable)}, skipped {skipped}.")
            if sum(e.result_df is not None for e in self.session.entries) >= 2:
                await self._build_combined()
            self._render_all_results()
        finally:
            self.busy.stop()
            self._busy = False

    def _run_dir(self) -> str:
        """A fresh timestamped output folder (with the current protein if set)."""
        entry = self._entry()
        protein = re.sub(r"[^A-Za-z0-9_-]+", "_", (entry.protein_label or "").strip()) \
            if entry else ""
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        name = f"{stamp}_{protein}" if protein else stamp
        run = os.path.join(self._results_root, name)
        os.makedirs(run, exist_ok=True)
        return run

    async def _run(self, fn, *args, **kwargs):
        """Run blocking (matplotlib) work on the single dedicated thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._pool, functools.partial(fn, *args, **kwargs))

    async def _build_combined(self) -> None:
        analyzed = [e for e in self.session.entries if e.result_df is not None]
        from .gelanalyzer import combine
        self._say("Building combined results…")
        try:
            outputs = await self._run(
                combine.combine_entries, analyzed, self.session.outdir,
                error_bars=True, significance=True,
                ylabel=self.ylabel_input.value or "")
        except Exception as exc:
            self._fail("Combine failed", exc)
            await self.main_window.dialog(toga.ErrorDialog("Combine failed", str(exc)))
            return
        self._combined = [p for p in outputs
                          if p and p.endswith(".png") and os.path.exists(p)]
        self._say(f"Combined results written to {self.session.outdir}.")


def main() -> Dugiel:
    icon_base = Path(__file__).parent / "icons" / "dugiel"
    about = ("Western-blot / SDS-PAGE Analysis "
             "Dedicated with gratitude to "
             "Prof. Dr. rer. nat. habil. Dawadschargal Dubiel.")
    if icon_base.with_suffix(".ico").exists() or icon_base.with_suffix(".png").exists():
        return Dugiel("Dubiel", "com.dugiel", icon=str(icon_base), description=about)
    return Dugiel("Dubiel", "com.dugiel", description=about)
