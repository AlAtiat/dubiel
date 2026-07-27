"""Molecular-weight ladders and log-linear MW calibration.

A protein ladder gives you (migration distance, known kDa) pairs. Protein
migration in SDS-PAGE is ~linear in log10(MW), so we fit:

    log10(MW) = m * distance + b

and use it to turn any band's migration distance into an estimated kDa.
"""
from __future__ import annotations

import numpy as np

# Bands top -> bottom (heaviest -> lightest), kDa. These are the marker bands
# as printed on the vendor sheet; click them in the same top->bottom order.
LADDERS: dict[str, list[float]] = {
    # Thermo PageRuler Prestained (26616)
    "pageruler_prestained": [180, 130, 100, 70, 55, 40, 35, 25, 15, 10],
    # Thermo PageRuler Plus Prestained (26619)
    "pageruler_plus": [250, 130, 100, 70, 55, 35, 25, 15, 10],
    # Bio-Rad Precision Plus Kaleidoscope / All Blue
    "precision_plus": [250, 150, 100, 75, 50, 37, 25, 20, 15, 10],
    # Thermo PageRuler Unstained (26614)
    "pageruler_unstained": [200, 150, 120, 100, 85, 70, 60, 50, 40, 30, 25, 20, 15, 10],
}

# Human-readable names for UI dropdowns (key -> full label).
LADDER_LABELS: dict[str, str] = {
    "pageruler_prestained": "PageRuler Prestained (10-180 kDa)",
    "pageruler_plus": "PageRuler Plus Prestained (10-250 kDa)",
    "precision_plus": "Precision Plus Protein (10-250 kDa)",
    "pageruler_unstained": "PageRuler Unstained (10-200 kDa)",
}


def resolve_ladder(ladder) -> list[float]:
    """Accept a preset name or a raw list of kDa values."""
    if isinstance(ladder, str):
        try:
            return list(LADDERS[ladder])
        except KeyError:
            raise KeyError(
                f"Unknown ladder {ladder!r}. Presets: {sorted(LADDERS)}, "
                "or pass a list of kDa values."
            )
    kda = [float(x) for x in ladder]
    if len(kda) < 2:
        raise ValueError("A ladder needs at least 2 bands to calibrate MW.")
    return kda


def fit_mw(marker_distances, marker_kda):
    """Fit log10(MW) = m*distance + b.

    Returns (predict, params) where predict(distance) -> kDa (float or array),
    and params = (slope, intercept, r_squared).
    """
    d = np.asarray(marker_distances, dtype=float)
    kda = np.asarray(marker_kda, dtype=float)
    if d.shape != kda.shape:
        raise ValueError(
            f"Got {d.size} marker clicks but {kda.size} ladder values. "
            "Click exactly one point per ladder band, top->bottom."
        )
    if d.size < 2:
        raise ValueError("Need >= 2 marker bands to calibrate MW.")

    y = np.log10(kda)
    m, b = np.polyfit(d, y, 1)
    resid = y - (m * d + b)
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    def predict(distance):
        return 10 ** (m * np.asarray(distance, dtype=float) + b)

    return predict, (float(m), float(b), r2)


def demo() -> None:
    """Self-check: recover known kDa from a synthetic linear-in-log ladder."""
    kda = LADDERS["precision_plus"]
    # Fabricate distances that are exactly linear in log10(MW) (perfect gel).
    true_m, true_b = -0.02, 2.4
    dist = [(np.log10(k) - true_b) / true_m for k in kda]
    predict, (m, b, r2) = fit_mw(dist, kda)
    assert r2 > 0.999, r2
    recovered = predict(dist)
    assert np.allclose(recovered, kda, rtol=1e-6), recovered
    # Mismatched counts must raise (a common user error).
    try:
        fit_mw([1, 2, 3], [10, 20])
    except ValueError:
        pass
    else:
        raise AssertionError("count mismatch should raise")
    print("ladder.py self-check OK")


if __name__ == "__main__":
    demo()
