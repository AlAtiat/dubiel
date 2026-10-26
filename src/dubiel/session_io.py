"""Export / import a configured session as a self-contained zip.

The zip holds ``config.json`` (every entry's boxes/lanes/ladder/labels/transform
+ combine options) and the source images, so importing restores the exact setup
— the only thing left to do is Analyze again. Results are not stored (they are
regenerated). stdlib only; no path traversal on extract.
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import asdict

from ._engine import Transform
from .state import (
    BoxSel,
    ImageEntry,
    LadderPoint,
    LaneSel,
    Selection,
    Session,
)

_VERSION = 1


# -- (de)serialize ------------------------------------------------------------
def _sel_to_dict(sel: Selection) -> dict:
    return {
        "crops": [asdict(b) for b in sel.crops],
        "lanes": [asdict(ln) for ln in sel.lanes],
        "ladder_points": [asdict(p) for p in sel.ladder_points],
        "transform": asdict(sel.transform),
    }


def _sel_from_dict(d: dict) -> Selection:
    return Selection(
        crops=tuple(BoxSel(**b) for b in d.get("crops", [])),
        lanes=tuple(LaneSel(**ln) for ln in d.get("lanes", [])),
        ladder_points=tuple(LadderPoint(**p) for p in d.get("ladder_points", [])),
        transform=Transform(**d.get("transform", {})),
    )


# -- export -------------------------------------------------------------------
def export_session(session: Session, combine: dict, out_zip: str) -> str:
    entries_cfg = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for i, e in enumerate(session.entries):
            stored = f"images/{i}_{os.path.basename(e.path)}"
            if os.path.exists(e.path):
                z.write(e.path, stored)
            entries_cfg.append({
                "image": stored,
                "protein_label": e.protein_label,
                "ladder_name": e.ladder_name,
                "ladder_mode": e.ladder_mode,
                "selection": _sel_to_dict(e.selection),
            })
        cfg = {"version": _VERSION, "combine": combine, "entries": entries_cfg}
        z.writestr("config.json", json.dumps(cfg, indent=2))
    return out_zip


# -- import -------------------------------------------------------------------
def import_session(in_zip: str, data_dir: str) -> tuple[Session, dict]:
    os.makedirs(data_dir, exist_ok=True)
    with zipfile.ZipFile(in_zip) as z:
        cfg = json.loads(z.read("config.json"))
        entries = []
        for ec in cfg.get("entries", []):
            rel = ec["image"]
            target = os.path.join(data_dir, os.path.basename(rel))  # no traversal
            try:
                with z.open(rel) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            except KeyError:
                continue  # image missing from the archive -> skip this entry
            entries.append(ImageEntry(
                path=target,
                protein_label=ec.get("protein_label", ""),
                ladder_name=ec.get("ladder_name", "pageruler_plus"),
                ladder_mode=ec.get("ladder_mode", "preset"),
                selection=_sel_from_dict(ec.get("selection", {})),
            ))
    return Session(entries=tuple(entries)), cfg.get("combine", {})
