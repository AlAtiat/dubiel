"""16-bit TIFF must load as displayable uint8, not wrap mod 256."""
import numpy as np
from skimage import io

from dubiel.gelanalyzer.detect import load_image


def test_uint16_tiff_scales_to_uint8_without_wrap(tmp_path):
    # a monotonic 16-bit gradient across the width
    row = np.linspace(0, 65535, 256).astype(np.uint16)
    img = np.tile(row, (32, 1))
    p = tmp_path / "grad.tif"
    io.imsave(str(p), img)

    rgb, gray = load_image(str(p))

    assert rgb.dtype == np.uint8
    assert rgb.max() <= 255
    line = rgb[0, :, 0].astype(int)
    assert np.all(np.diff(line) >= 0), "gradient wrapped -> bit-depth not normalized"
    assert line[-1] > line[0]
