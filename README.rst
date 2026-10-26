Dubiel
======
.. raw:: html

   <div align="center">
       <img src="icons/dubiel-256.png" width="180"><br><br>
       <img src="https://img.shields.io/github/v/release/AlAtiat/dubiel">
       <img src="https://img.shields.io/github/license/AlAtiat/dubiel">
       <img src="https://img.shields.io/badge/python-3.11+-blue">
   </div>

 Author: Aun Al Atiat

Dubiel is a cross-platform desktop application for quantifying protein gels
and Western blots from photographs: draw a box per lane (or per band),
optionally tag a molecular-weight ladder, and it detects and integrates
bands, calibrates molecular weights, and exports labelled tables and figures
— per-gel montages, electropherograms, 3D intensity surfaces, trend lines,
and combined multi-protein panels with Spearman correlation heatmaps and
significance-annotated bar charts.

*Dedicated with gratitude to Prof. Dr. rer. nat. habil. Dawadschargal Dubiel.*


Overview
--------

No lab server, no internet — everything runs on your machine, on one or many
gel/blot photos at once (PNG/JPG/TIFF/BMP, phone photos are fine). The
workflow is six steps: add images, line them up (rotate/flip/invert, applied
identically to display and analysis), optionally crop, draw one box per lane
and tag a ladder, analyze, and read the results — a labelled table plus
figures per gel, and a cross-gel **Combined** comparison once two or more
gels have been analyzed.


The Application
----------------

Screenshots of Dubiel analyzing a real gel photo — two lanes (10%, 12%) boxed
against a 7-point manual ladder (900–100 kDa):

.. raw:: html

   <table align="center"><tr>
   <td align="center"><a href="resources/images/real_gel_source.png"><img src="resources/images/real_gel_source.png" width="180" alt="Source gel photo"/></a><br><sub>Source photo</sub></td>
   <td align="center"><a href="resources/images/app_annotate_real.png"><img src="resources/images/app_annotate_real.png" width="320" alt="Annotate tab: boxes + manual ladder"/></a><br><sub>Annotate — boxes + ladder</sub></td>
   <td align="center"><a href="resources/images/app_invert_real.png"><img src="resources/images/app_invert_real.png" width="220" alt="Invert transform applied"/></a><br><sub>Invert transform</sub></td>
   </tr></table>

   <p align="center"><a href="resources/images/app_results_real.png"><img src="resources/images/app_results_real.png" width="640" alt="Results tab: real Z profile for both lanes"/></a><br><sub>Results — Z profile (electropherogram) for both lanes, bands marked green</sub></p>

Any stain works the same way — here's a second real gel, Coomassie-stained:

.. raw:: html

   <p align="center"><a href="resources/images/real_gel_coomassie.png"><img src="resources/images/real_gel_coomassie.png" width="200" alt="Second real gel example, Coomassie-stained"/></a></p>


Scientific Methodology
-----------------------

Every step works on a **signal image** where bands are *bright* and the
illumination gradient of a photo is *flat*:

- **Load & normalize** — downscaled so the long edge is ≤ 2000 px (keeps band
  *ratios* identical, just faster); 16-bit/float TIFFs are rescaled to 8-bit,
  not wrapped.
- **Band signal** — invert (dark bands become bright), then subtract a
  heavily blurred copy of itself (Gaussian, σ ≈ 40 px) to remove the slow
  lighting gradient of a photo, then clip at 0. Works for any stain, any
  background.
- **Lane profile** — for each box, average the signal across the lane's
  width into a 1-D curve of intensity vs. migration distance (an
  electropherogram of that lane), Gaussian-smoothed.
- **Band detection** — peaks on the smoothed curve, kept only if their
  *prominence* is ≥ 10% of the lane's max; peaks touching the well/front
  edges are dropped.
- **Integration (band volume)** — ``scipy.signal.peak_widths`` finds where a
  peak meets the background; a straight baseline is drawn between those
  points and the signal above it is summed (background-subtracted band
  volume). For single-band boxes, an **adjusted volume** is used instead:
  box sum minus the mean of the pixel ring just outside the box × box area
  — the classic densitometry "adjusted volume" / rolling-disc background
  subtraction.
- **Molecular weight** — protein migration in SDS-PAGE is approximately
  linear in log\ :sub:`10`\ (MW), so the ladder's (distance, kDa) points are
  fit to ``log10(MW) = m*distance + b`` by least squares, with r\ :sup:`2`
  reported. Any band's migration distance maps to an estimated kDa via the
  inverse of that fit. A typed manual ladder (≥ 2 clicked points) overrides
  a preset; otherwise the tagged ladder box is used.

.. raw:: html

   <table align="center"><tr>
   <td align="center"><a href="resources/images/TargetProtein_overlay.png"><img src="resources/images/TargetProtein_overlay.png" width="220" alt="Annotated boxes + detected bands"/></a></td>
   <td align="center"><a href="resources/images/TargetProtein_overlay_profile.png"><img src="resources/images/TargetProtein_overlay_profile.png" width="220" alt="Electropherogram (Z profile)"/></a></td>
   <td align="center"><a href="resources/images/TargetProtein_montage.png"><img src="resources/images/TargetProtein_montage.png" width="220" alt="Cropped band montage"/></a></td>
   </tr></table>

**Cross-lane and cross-gel statistics**

- **Trend across lanes** — each lane as % of that gel's control lane
  (control = 100%).
- **Lane correlation** — Spearman ρ heatmap of how similar lanes' intensity
  profiles are to each other, with Benjamini-Hochberg FDR-corrected q-values
  and n per cell.
- **Combined (≥2 gels)** — every gel is normalized per-gel to its own
  control lane, so gels shot under different exposures are comparable.
  Significance between lanes uses **Welch's t-test** (unequal variances;
  needs ≥ 2 replicate measurements per lane — multiple gels of a protein,
  or multiple bands in a lane), with ``*``/``**``/``***`` at p<0.05/0.01/0.001.
- **Decay / half-life** (timepoint series) — fits ``y = a*exp(-k*t)`` and
  reports the half-life ``t1/2 = ln(2)/k`` with r\ :sup:`2`.

.. raw:: html

   <table align="center"><tr>
   <td align="center"><a href="resources/images/TargetProtein_trend.png"><img src="resources/images/TargetProtein_trend.png" width="200" alt="Trend across lanes"/></a></td>
   <td align="center"><a href="resources/images/TargetProtein_surface_gel.png"><img src="resources/images/TargetProtein_surface_gel.png" width="200" alt="3D intensity surface"/></a></td>
   <td align="center"><a href="resources/images/TargetProtein_corr.png"><img src="resources/images/TargetProtein_corr.png" width="200" alt="Lane correlation heatmap"/></a></td>
   </tr></table>

   <p align="center"><a href="resources/images/combined_panel_3d.png"><img src="resources/images/combined_panel_3d.png" width="640" alt="Combined panel: strip + 3D surface + trend, aligned across proteins"/></a></p>

   <table align="center"><tr>
   <td align="center"><a href="resources/images/combined_stats_sig.png"><img src="resources/images/combined_stats_sig.png" width="260" alt="Significance-annotated bar chart"/></a></td>
   <td align="center"><a href="resources/images/combined_corr_proteins.png"><img src="resources/images/combined_corr_proteins.png" width="260" alt="Protein correlation heatmap"/></a></td>
   <td align="center"><a href="resources/images/decay_halflife.png"><img src="resources/images/decay_halflife.png" width="260" alt="Decay / half-life fit"/></a></td>
   </tr></table>

The example figures above are generated by the real analysis engine on a
synthetic Western-blot image with known, ground-truth band intensities and a
known ladder — not mockups. The ``generate_demo_assets.py`` script that
produced them (and asserts the recovered MW-calibration r\ :sup:`2` and
relative intensities match the ground truth) ships at the project root.


Features
--------

- Box-per-lane or box-per-band annotation, with rotate/flip/invert applied
  identically to display and analysis.
- Automatic band detection (prominence-based peak finding) or manual
  single-band boxes for faint/hand-picked signal.
- Molecular-weight calibration from a ladder preset or manual marker clicks,
  with fit r\ :sup:`2` reported.
- Background-flattened densitometry: band volume via local-baseline
  integration, or adjusted volume via rolling local background.
- Per-gel results: labelled table, marked-bands overlay, electropherogram
  overlay, band-intensity bar chart, trend-across-lanes, 3D intensity
  surfaces (raw and background-subtracted), and a Spearman lane-correlation
  heatmap.
- Combined multi-gel comparison: aligned-column panel figure, 3D panel,
  %-of-control statistics with error bars, Welch's-t-test significance
  bars, Benjamini-Hochberg FDR-corrected protein/treatment correlation
  heatmaps, and exponential decay / half-life fitting.
- Session save/restore (``.zip``) and per-run results folders with plain
  PNG figures and CSV/JSON tables.
- Cross-platform: Windows, macOS, Linux.


Download
--------

.. raw:: html

   <table align="center">
   <tr>
   <td align="center" width="33%">
     <h3>Windows</h3>
     <a href="https://github.com/AlAtiat/dubiel/releases/latest/download/Dubiel.msi">
       <img src="https://img.shields.io/badge/Download%20Installer-.msi-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Download for Windows"/>
     </a>
     <br><br>
     <sub>Windows 10 / 11 · MSI Installer<br>Run the installer</sub>
   </td>
   <td align="center" width="33%">
     <h3>macOS</h3>
     <a href="https://github.com/AlAtiat/dubiel/releases/latest/download/Dubiel-arm64.dmg">
       <img src="https://img.shields.io/badge/Apple_Silicon_(M1%2FM2%2FM3)-DMG-000000?style=for-the-badge&logo=apple&logoColor=white" alt="Download for macOS ARM64"/>
     </a>
     <br>
     <a href="https://github.com/AlAtiat/dubiel/releases/latest/download/Dubiel-x86_64.dmg">
       <img src="https://img.shields.io/badge/Intel_(x86__64)-DMG-000000?style=for-the-badge&logo=apple&logoColor=white" alt="Download for macOS Intel"/>
     </a>
     <br><br>
     <sub>macOS 12+ · DMG · Open the DMG and drag Dubiel to Applications.</sub>
   </td>
   <td align="center" width="33%">
     <h3>Linux (AppImage)</h3>
     <a href="https://github.com/AlAtiat/dubiel/releases/latest/download/Dubiel.AppImage">
       <img src="https://img.shields.io/badge/Download%20AppImage-.AppImage-4CAF50?style=for-the-badge&logo=linux&logoColor=white" alt="Download AppImage for Linux"/>
     </a>
     <br><br>
     <sub>All distributions · No install needed:<br><code>chmod +x Dubiel.AppImage &amp;&amp; ./Dubiel.AppImage</code></sub>
   </td>
   </tr>
   </table>

   <p align="center"><sub>
   Links above always point to the latest release.
   All releases and release notes are on the
   <a href="https://github.com/AlAtiat/dubiel/releases">Releases page</a>.
   </sub></p>


Framework and Build System
---------------------------

Dubiel is implemented in Python and built as a native desktop application
using the BeeWare ecosystem.

The graphical user interface is developed with **BeeWare Toga**, a native
cross-platform GUI toolkit for Python. Packaging and distribution are
handled with **BeeWare Briefcase**, which builds standalone installers
(MSI, DMG, AppImage) that bundle the Python runtime and dependencies — no
separate Python install needed on the target machine.

For more information, see:

- BeeWare: https://beeware.org
- Toga: https://beeware.org/project/projects/libraries/toga/
- Briefcase: https://beeware.org/project/projects/tools/briefcase/

**Core dependencies**

Python 3.11+ — numpy, pandas, scipy, scikit-image, matplotlib, pillow, toga.


License
-------

Copyright (C) 2026 Aun Al Atiat.

This software is distributed under the terms of the
GNU General Public License v3.0 (GPLv3) or any later version.
See the ``LICENSE`` file for the full license text.


Citation
--------

If you use Dubiel in research, please cite as:

    Al Atiat, A. (2026). *Dubiel: A Software Tool for Western-Blot / SDS-PAGE
    Densitometry* (Version 0.0.1) [Computer software]. GitHub.
    https://github.com/AlAtiat/dubiel
