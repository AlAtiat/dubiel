# Prompt: write Dubiel's Read the Docs page

Paste everything below the line into another AI (with file access to this
repo, or paste the referenced files' contents alongside this prompt) to
generate the full Read the Docs content. The Sphinx/Read the Docs scaffold
(`.readthedocs.yaml`, `resources/docs/conf.py`, `resources/docs/index.rst`)
already exists and works — you are only replacing `resources/docs/content.rst`.

---

You are writing the Read the Docs content page for **Dubiel**, a desktop
scientific-image-analysis tool. Output valid reStructuredText for
`resources/docs/content.rst` (referenced by `resources/docs/index.rst`'s
toctree; built by Sphinx via `resources/docs/conf.py`, theme
`sphinx_rtd_theme`, `extensions = ['sphinx.ext.mathjax']`, `numfig = True`).

## Ground truth — read these before writing anything

- `README.rst` (project root) — accurate overview, full scientific
  methodology, feature list, license, citation. Treat its "Scientific
  Methodology" section as authoritative; do not re-derive or re-describe the
  algorithms from guesswork.
- `src/dubiel/gelanalyzer/detect.py`, `ladder.py`, `lanes.py`, `results.py`,
  `combine.py`, `correlate.py`, `viz.py` — the actual implementation, if you
  want primary-source detail beyond the README (e.g. exact function names,
  default parameters like `flatten_sigma=40`, `min_prominence_frac=0.1`,
  `rel_height=0.9` in `peak_widths`).
- `pyproject.toml` — `[tool.briefcase]` block: app name, version, author,
  license (GPL-3.0), bundle id, dependencies.
- `CHANGELOG` — current version and release notes.

## Hard constraints

1. **Do not invent facts.** Every algorithm, formula, and statistic must
   match the README/source exactly (prominence threshold, baseline
   integration via `scipy.signal.peak_widths`, log-linear MW calibration,
   Spearman + Benjamini-Hochberg FDR, Welch's t-test, exponential decay).
   If something is unclear from the source, write `TODO: confirm — <question>`
   instead of guessing.
2. **Do not fabricate screenshots or citations.** No GUI screenshots exist
   yet (the app has not been run and captured on a live desktop as part of
   this pass) — mark every such spot with
   `.. TODO: insert a real screenshot of <exact screen/state>` rather than
   describing an imagined image. Do not invent academic references; Dubiel's
   README cites no external methodology paper, so the Read the Docs page
   should not add one either unless the user supplies a citation.
3. **Reuse the real example figures already generated** (see list below) —
   do not ask for new ones or describe different ones. They were produced by
   running the actual analysis engine (`generate_demo_assets.py`, project
   root) on a synthetic Western blot with known, ground-truth band
   intensities and a known ladder (recovered MW-calibration r² > 0.999 in
   all cases) — so they are safe to present as genuine algorithm output, not
   mockups.

## Available real figures (already in `resources/images/`)

Copy the ones you use into `resources/docs/_static/img/` (two are already
there: `overview.png` = `TargetProtein_overlay.png`, `combined_panel.png` =
`combined_panel_3d.png`) and reference them with Sphinx `.. figure::`
directives, numbered captions (numfig is on).

| File | What it shows |
|---|---|
| `TargetProtein_overlay.png` | Annotated source image: ladder box (yellow) with 5 marker bands, 4 sample lanes (Control/MG132/MLN4924/Bortezomib) with detected bands marked red |
| `TargetProtein_overlay_profile.png` | Electropherogram: intensity-vs-Rf curve per lane, overlaid, with the source strip beneath each curve |
| `TargetProtein_montage.png` | Cropped band montage, one tile per lane |
| `TargetProtein_trend.png` | Single gel's lanes as % of its control lane |
| `TargetProtein_surface_gel.png` | 3D intensity surface (raw vs. background-subtracted) of the whole gel |
| `TargetProtein_corr.png` | Per-gel Spearman lane-correlation ellipse heatmap (ρ, FDR q, n per cell) |
| `combined_panel.png` | Cross-gel panel: 3 proteins (TargetProtein, LoadingControl, LC3II) × 2 replicates each, lanes aligned in shared columns |
| `combined_panel_3d.png` | Same, with a 3D surface + %-of-control trend line added per row |
| `combined_stats.png` | %-of-control bars with SEM error bars, grouped by protein |
| `combined_stats_sig.png` | Same, with Welch's-t-test significance brackets (`*`/`**`/`***`) between lanes |
| `combined_corr_proteins.png` | Spearman correlation between proteins' responses across treatments, BH-FDR corrected |
| `combined_corr_treatments.png` | Spearman correlation between treatments across proteins, BH-FDR corrected |
| `decay_halflife.png` | Standalone example: exponential decay fit, `y = a·exp(-k·t)`, recovered half-life vs. known synthetic input |
| `TargetProtein.csv` | Example exported results table (one row per band: `lane_label`, `mw_kda`, `rf`, `raw_intensity`, `adjusted_volume`, `lane_total`, `pct_of_lane`, ...) |

Path from `resources/docs/*.rst` to these originals is `../images/<file>`.

## Required page structure (mirror this exact shape)

1. **Overview** — 1 short paragraph: what Dubiel is, who it's for (wet-lab
   researchers quantifying Western blots / SDS-PAGE gels), what makes it
   different (runs fully offline, box-per-lane annotation, automatic MW
   calibration, multi-gel statistical comparison). Lead figure:
   `overview.png`.
2. **How to Download** — Windows (.msi), macOS (arm64 + x86_64 .dmg), Linux
   (.AppImage) — same as the README's Download table, as plain reST links
   (`` `Dubiel.msi <https://github.com/AlAtiat/dubiel/releases/latest/download/Dubiel.msi>`__ ``),
   one subsection per platform, plus a note that links always point to the
   latest GitHub Release.
3. **How to Use** — the 6-step workflow from the README (add images → line
   up → crop → mark lanes/ladder → analyze → read results), as prose with
   `TODO: insert a real screenshot of <step>` placeholders at: the main
   window with images loaded, the box/ladder annotation screen, and the
   Results tabs. Do not describe pixel-level UI layout you haven't seen —
   describe only the behavior documented in the README.
4. **Examples** — walk through the synthetic ground-truth example using the
   real figures listed above, in this order: single-gel overlay → per-lane
   electropherogram → montage → 3D surface → per-gel correlation → combined
   multi-protein panel (`combined_panel_3d.png`) → statistics with
   significance → cross-protein/treatment correlation → decay/half-life.
   For each figure, state what ground truth was used (see
   `generate_demo_assets.py`: `LADDER_KDA`, `TRUE_PCT`, `LANES`) and that the
   recovered values matched it (MW-calibration r² > 0.999; decay r² ≈ 0.998).
5. **Deep Dive** — the full scientific methodology from the README's
   "Scientific Methodology" section, expanded with exact parameter values and
   formulas from the source files (cite file + function name inline, e.g.
   "`detect.band_signal`"): image normalization, background flattening
   (Gaussian σ≈40px), lane profile extraction, band detection (prominence
   ≥10% of lane max via `scipy.signal.find_peaks`), band integration
   (`scipy.signal.peak_widths`, `rel_height=0.9`, straight-baseline
   subtraction) vs. adjusted volume (rolling local background), MW
   calibration (`log10(MW) = m·distance + b`, least squares, r² reported),
   combined-gel normalization (per-gel % of that gel's control lane), Welch's
   t-test significance, Spearman + Benjamini-Hochberg FDR correlation, and
   exponential decay / half-life fitting. Use `:math:` roles for the
   formulas (MathJax is enabled).
6. **Framework and Build System** — Python 3.11+, BeeWare Toga (GUI) +
   Briefcase (packaging), dependencies from `pyproject.toml`. One short
   paragraph, same as the README.
7. Skip a References section unless the user explicitly supplies citations
   to add — do not invent one.

## Style

- Match the tone of a technical user manual, not marketing copy: precise,
  declarative, numbers over adjectives.
- Use `.. figure::` with a one-sentence bold lead-in + explanatory caption,
  same pattern as the Examples section above.
- Section headers use the same reST underline convention already in
  `resources/docs/content.rst` (`=` for H1, `-` for H2, `~` for H3).
- Keep it as one `content.rst` file (do not split into multiple pages) unless
  it exceeds roughly 400 lines, in which case propose a split and ask first.
