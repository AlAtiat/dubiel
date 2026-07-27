# Dubiel

Turn **photos of protein gels / Western blots** into numbers and figures: draw a box per
lane, tag a molecular‑weight ladder, hit **Analyze**. It detects and integrates bands,
calibrates molecular weights, and exports labelled tables + publication figures — for one
gel or many at once.

*Dedicated with gratitude to Prof. Dr. rer. nat. habil. Dawadschargal Dubiel.*

---

## Run it


No lab server, no internet — everything runs on your machine. Add one or more gel/blot
images (PNG/JPG/TIFF/BMP); phone photos are fine.

---

## Workflow (6 steps)

1. **Add images** — *Add images…* (or the File menu). Switch between them with the
   thumbnail strip / ◀ ▶.
2. **Line it up** — *Rotate / Flip / Invert* so lanes run top→bottom (wells at top). The
   same transform is applied to display **and** analysis, so coordinates always match.
3. **Crop (optional)** — *Crop* mode: drag a region → it becomes a **new image** (the
   original is kept). Crop several regions → several new images.
4. **Mark it** — *Box* mode: drag one box per lane, name each (Control, MG132, …). Tag one
   box as **ladder** and pick its preset in the **Ladder** section — or use **Manual**:
   click each ladder band and type its kDa. The ladder is optional (without it you still
   get intensities; molecular weights are just blank).
5. **Analyze** — quantifies every box, writes a labelled table + figures per gel into a
   fresh `results/<timestamp>/` folder. With ≥2 gels analyzed it also builds the
   **Combined** comparison.
6. **Use it** — read the **Results** tabs (one per gel + Combined), **Open results
   folder**, or **Export session** to a `.zip` you can reopen later.

---

## What happens in the backend

Every step works on a **signal image** where bands are *bright* and lighting is *flat*:

- **Load & normalize** — image downscaled so its long edge ≤ 2000 px (keeps band *ratios*
  identical, just faster) and forced to 8‑bit (16‑bit/float TIFFs are rescaled, not
  wrapped).
- **Band signal** — invert (dark bands → high), then subtract a heavily blurred copy of
  itself (Gaussian, σ≈40 px) to remove the slow lighting gradient of a photo, then clip at
  0. Result: empty gel ≈ 0, a band rises above it. *Works for any stain, any background.*
- **Lane profile** — for each box, average the signal **across the lane's width** → a 1‑D
  curve of intensity vs. migration distance (an electropherogram of that lane), then
  Gaussian‑smooth it.
- **Band detection** — peaks on that smoothed curve, kept only if their **prominence** is
  ≥ 10 % of the lane's max; peaks touching the well/front edges are dropped. (Turn *Detect
  bands* off to treat a box as a single hand‑picked band.)
- **Integration = band volume** — for each band, `scipy.peak_widths` finds where the peak
  meets the background; a **straight baseline** is drawn between those two points and the
  signal **above** it is summed. That area (background‑subtracted) is the band's intensity.
  For single‑band boxes an **adjusted volume** is used instead: box sum minus the mean of
  the pixel ring just outside the box × box area (a rectangular local‑background /
  rolling‑disc), the classic densitometry "adjusted volume".
- **Molecular weight** — protein migration in SDS‑PAGE is ~linear in `log10(MW)`, so the
  ladder's `(distance, kDa)` points are fit to **`log10(MW) = m·distance + b`** (least
  squares, with an r² reported). Any band's distance → estimated kDa via `10^(m·d+b)`. A
  typed **Manual** ladder overrides the preset; otherwise the tagged ladder box is used.

---

## Per‑gel outputs (one Results tab each)

- **Table** — one row per band: `lane_label`, `band_idx`, `mw_kda` (estimated MW),
  `rf` (relative migration 0–1), `raw_intensity` / `adjusted_volume` (the integrated
  area), `lane_total`, `pct_of_lane` (band as % of its lane).
- **Marked bands** — your boxes + detected band lines drawn on the gel (sanity check).
- **Z‑profile (electropherogram)** — every lane's intensity‑vs‑Rf curve overlaid, with a
  colour strip of each lane beneath and detected bands highlighted. This is the
  densitometry trace behind the numbers.
- **Band intensities** — bar chart of each band's integrated intensity.
- **Trend across lanes** — each lane as **% of the control lane** (control = 100 %); shows
  whether the protein goes up or down across treatments.
- **3D intensity surfaces** — the lane region as a height map (raw vs. after
  background subtraction): peak height = band intensity, so a real band is a sharp ridge
  and noise is flat.
- **Lane correlation** — Spearman ρ heatmap of how similar the lanes' intensity profiles
  are to each other (per‑cell ρ, FDR q‑value, n).

> One gel = one protein. The ladder is never shown in the summary figures.

---

## Combined (when ≥2 gels are analyzed)

Everything is normalized **per gel to that gel's own control lane** (control = 100 %), so
gels shot under different exposures are comparable. `>100 %` means *more* protein
(accumulation), `<100 %` less.

- **Panel** — every gel as one clean strip, lanes aligned in shared columns by name
  (a gel with fewer lanes is simply narrower); lane names labelled once.
- **Panel + 3D + trend** — each gel row: strip │ 3D surface │ %‑of‑control trend │ MW.
- **3D** — one intensity surface per gel, lanes column‑aligned.
- **Intensity bars** — mean % of control per lane per protein (± SEM).
- **Significance bars** — same bars with brackets between lanes that differ significantly
  (**Welch's t‑test**; `*` p<0.05, `**` p<0.01, `***` p<0.001). *Needs ≥2 replicate
  measurements per lane — multiple gels of a protein, or multiple bands in a lane.*
- **Correlation heatmaps** — two ellipse heatmaps (**proteins × proteins**, and
  **treatments × treatments**) using **Spearman rank correlation** with **Benjamini–
  Hochberg FDR** correction; each cell shows ρ, the q‑value, and n. Ellipse tilt = sign,
  narrowness + colour = strength. Robust to outliers and small n.
- **Decay / half‑life** *(timepoint series)* — fits `y = a·e^(−k·t)` and reports the
  half‑life `t½ = ln2 / k` with r².

---

## Sessions & files

- **Export / Import session** (`.zip`) — stores your images + all boxes/labels/ladder/
  transform (results are *regenerated* on re‑analyze, not stored), so you can reopen the
  exact setup anywhere.
- **Results** land in `results/<timestamp>_<protein>/` (a fresh folder per run). **Open
  results folder** from any Results tab or the File menu.
- **Crops** are saved to `results/crops/`.

---

## Notes

- Analysis runs at the working resolution (≤2000 px long edge) — plenty for densitometry,
  and band ratios are unchanged by the downscale.
- No ladder tagged/selected → intensities still computed, `mw_kda` is blank.
- All figures are plain PNGs written to the results folder; the app just displays them.
