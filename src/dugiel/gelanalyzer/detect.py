"""Preprocessing + automatic gel / lane / band detection.

Everything downstream works on a "signal" image where bands are *bright* and the
illumination gradient of a phone photo has been flattened out, so an empty part
of the gel sits near zero and a band rises above it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import binary_fill_holes, gaussian_filter1d
from scipy.signal import find_peaks
from skimage import color, filters, io, measure, morphology, transform


# -----------------------------------------------------------------------------
# loading / preprocessing
# -----------------------------------------------------------------------------
def load_image(path: str, max_dim: int = 2000):
    """Load an image, downscale so the long edge <= max_dim. Returns (rgb, gray).

    rgb is uint8 for display; gray is float [0,1]. Downscaling keeps 24 MP phone
    photos fast; band *ratios* are unaffected.
    """
    rgb = io.imread(path)
    if rgb.ndim == 3 and rgb.shape[-1] not in (1, 3, 4):
        rgb = rgb[0]                       # multipage/stack TIFF -> first page
    if rgb.ndim == 2:
        rgb = np.stack([rgb] * 3, axis=-1)
    rgb = rgb[..., :3]
    if rgb.dtype != np.uint8:              # 16-bit / float TIFF -> scale to 0-255
        r = rgb.astype(np.float64)
        mx = float(r.max())
        rgb = (r / mx * 255.0).astype(np.uint8) if mx > 0 else r.astype(np.uint8)
    scale = max_dim / max(rgb.shape[:2])
    if scale < 1:
        rgb = transform.rescale(
            rgb, scale, channel_axis=-1, anti_aliasing=True, preserve_range=True
        ).astype(np.uint8)
    gray = color.rgb2gray(rgb)  # float [0,1]
    return rgb, gray


def band_signal(gray: np.ndarray, flatten_sigma: float = 40.0) -> np.ndarray:
    """Bands -> bright, background flattened. Works for dark bands on any stain.

    Invert (dark bands become high), then subtract a heavily blurred copy to
    remove the slow illumination gradient. Clipped at 0.
    """
    inv = 1.0 - gray
    background = filters.gaussian(inv, sigma=flatten_sigma, preserve_range=True)
    sig = inv - background
    return np.clip(sig, 0, None)


# -----------------------------------------------------------------------------
# gel-slab detection
# -----------------------------------------------------------------------------
@dataclass
class GelBox:
    """Bounding box of one gel slab in downscaled-image pixels."""
    y0: int
    x0: int
    y1: int
    x1: int

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    def crop(self, img: np.ndarray) -> np.ndarray:
        return img[self.y0:self.y1, self.x0:self.x1]


def _runs(on: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Contiguous True runs in a boolean array, keeping runs >= min_len."""
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    if start is not None and len(on) - start >= min_len:
        out.append((start, len(on)))
    return out


def detect_gels(gray: np.ndarray, min_area_frac: float = 0.02,
                delta: float = 0.02) -> list[GelBox]:
    """Find gel/membrane slabs (stain-agnostic, illumination-flattened).

    A slab reads *darker than its local background* after flattening (the slab
    material, its border, and its bands). We threshold on that, fill the
    rectangle, then split any blob that spans a clear vertical background gap
    so slabs sitting side by side come out separately. Reading order is
    top->bottom, then left->right.

    Very faint slabs (interior indistinguishable from background) may
    under-segment -- that's what the manual-override picker is for.
    """
    h, w = gray.shape
    min_area = min_area_frac * h * w
    background = filters.gaussian(gray, sigma=60, preserve_range=True)
    flat = gray - background

    m = int(0.04 * w)  # ignore the bright frame at the photo edges
    mask = flat < -delta
    mask[:, :m] = False; mask[:, -m:] = False
    mask[:m, :] = False; mask[-m:, :] = False
    mask = morphology.closing(mask, morphology.disk(14))
    mask = binary_fill_holes(mask)
    mask = morphology.opening(mask, morphology.disk(8))
    mask = morphology.remove_small_objects(mask, int(min_area))

    boxes: list[GelBox] = []
    for r in measure.regionprops(measure.label(mask)):
        y0, x0, y1, x1 = r.bbox
        sub = mask[y0:y1, x0:x1]
        cov = gaussian_filter1d(sub.mean(axis=0).astype(float), 5)
        col_runs = _runs(cov > 0.5 * cov.max(), int(0.05 * w)) or [(0, x1 - x0)]
        for cx0, cx1 in col_runs:
            strip = sub[:, cx0:cx1]
            rows = np.where(strip.mean(axis=1) > 0.2 * strip.mean(axis=1).max())[0]
            if len(rows) < 10:
                continue
            b = GelBox(y0 + int(rows[0]), x0 + cx0, y0 + int(rows[-1]), x0 + cx1)
            if b.width * b.height < min_area:
                continue
            if 0.2 < b.width / b.height < 6:  # reject thin edge slivers
                boxes.append(b)

    boxes.sort(key=lambda b: (round(b.y0 / max(h, 1) * 4), b.x0))
    return boxes


# -----------------------------------------------------------------------------
# lane detection
# -----------------------------------------------------------------------------
@dataclass
class Lane:
    center: int          # x within the gel crop
    half_width: int      # sampling half-width in x
    profile: np.ndarray = field(repr=False)  # 1-D signal along migration axis (y)
    bands: list[int] = field(default_factory=list)  # y indices of band peaks


def detect_lanes(gel_signal: np.ndarray, expected: int | None = None,
                 min_spacing_frac: float = 0.6) -> list[int]:
    """Return lane-center x positions from the column-intensity profile."""
    col = gel_signal.sum(axis=0)
    col = gaussian_filter1d(col, sigma=max(gel_signal.shape[1] * 0.004, 1))
    if col.max() <= 0:
        return []
    # rough spacing guess: if we expect N lanes they're ~width/N apart
    guess_n = expected or 12
    min_dist = max(int(gel_signal.shape[1] / guess_n * min_spacing_frac), 3)
    peaks, props = find_peaks(col, distance=min_dist, prominence=col.max() * 0.05)
    if expected and len(peaks) > expected:
        # keep the strongest `expected` peaks, then restore left->right order
        order = np.argsort(props["prominences"])[::-1][:expected]
        peaks = np.sort(peaks[order])
    return list(peaks)


def lane_profile(gel_signal: np.ndarray, center: int, half_width: int) -> np.ndarray:
    """Average signal across a lane's width -> 1-D profile along migration (y)."""
    x0 = max(center - half_width, 0)
    x1 = min(center + half_width + 1, gel_signal.shape[1])
    return gel_signal[:, x0:x1].mean(axis=1)


def smooth_profile(profile: np.ndarray) -> np.ndarray:
    """The single smoothed profile bands are both *detected* and *integrated* on."""
    return gaussian_filter1d(profile, sigma=max(len(profile) * 0.004, 1))


def detect_bands(profile: np.ndarray, min_prominence_frac: float = 0.1,
                 edge_frac: float = 0.03) -> list[int]:
    """Band peak positions along an already-smoothed lane profile.

    Peaks within edge_frac of either end are dropped -- those are the well slot
    and the gel-front / crop edges, not real bands.
    """
    if profile.max() <= 0:
        return []
    peaks, _ = find_peaks(
        profile,
        prominence=profile.max() * min_prominence_frac,
        distance=max(int(len(profile) * 0.02), 2),
    )
    margin = int(len(profile) * edge_frac)
    return [int(p) for p in peaks if margin <= p <= len(profile) - margin]


def build_lanes(gel_signal: np.ndarray, centers: list[int]) -> list[Lane]:
    """Turn lane-center positions into Lane objects with profiles + bands."""
    if len(centers) >= 2:
        spacing = int(np.median(np.diff(sorted(centers))))
    else:
        spacing = gel_signal.shape[1] // 4
    hw = max(int(spacing * 0.35), 2)
    lanes = []
    for c in centers:
        prof = smooth_profile(lane_profile(gel_signal, c, hw))
        lanes.append(Lane(center=int(c), half_width=hw, profile=prof,
                          bands=detect_bands(prof)))
    return lanes


# -----------------------------------------------------------------------------
# self-check
# -----------------------------------------------------------------------------
def demo() -> None:
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def report(name):
        path = os.path.join(here, name)
        if not os.path.exists(path):
            return None
        _, gray = load_image(path)
        gels = detect_gels(gray)
        print(f"{name}: detected {len(gels)} slabs")
        for i, g in enumerate(gels):
            sig = band_signal(g.crop(gray))
            lanes = build_lanes(sig, detect_lanes(sig))
            nbands = sum(len(ln.bands) for ln in lanes)
            print(f"  slab{i+1}: bbox=({g.x0},{g.y0})-({g.x1},{g.y1}) "
                  f"aspect={g.width/g.height:.2f} lanes={len(lanes)} bands={nbands}")
        return gels

    # IMG_8562 (two clear membranes) is the reliable auto-detection check.
    strict = report("IMG_8562.png")
    # IMG_8559 has one near-blank gel; auto may under-segment -> use override.
    report("IMG_8559.png")

    if strict is not None:
        assert len(strict) == 2, f"expected 2 membranes in IMG_8562, got {len(strict)}"
        g0 = strict[0]
        sig = band_signal(g0.crop(load_image(os.path.join(here, "IMG_8562.png"))[1]))
        lanes = build_lanes(sig, detect_lanes(sig))
        assert lanes and any(ln.bands for ln in lanes), "no bands detected in membrane 1"
    print("detect.py self-check OK")


if __name__ == "__main__":
    demo()
