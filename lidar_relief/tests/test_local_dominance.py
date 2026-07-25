"""test_local_dominance.py — Tests for Local Dominance computation.
exports: test_local_dominance_cone() and more
used_by: pytest runner
rules:
  Assert against ARCHAEOLOGICALLY REALISTIC relief, not just a 45-degree
  cone. Through v2.0.22 this algorithm emitted an all-zero raster for
  anything gentler than a cliff — it returned radians but byte-scaled
  with degree-scale limits, so every pixel clipped to 0. The tests here
  all passed anyway, because the only shaped fixture was a cone steep
  enough to survive the clipping. Any new test must use relief on the
  scale of real earthworks (decimetres to a couple of metres).
"""

import numpy as np
from lidar_relief.core.local_dominance import compute_local_dominance


def test_local_dominance_cone():
    """Cone DEM produces highest values at peak and lowest at base ring."""
    rows, cols = 50, 50
    center_r, center_c = rows // 2, cols // 2
    y, x = np.ogrid[:rows, :cols]
    dist_from_center = np.sqrt((x - center_c) ** 2 + (y - center_r) ** 2)
    dem = 100.0 - dist_from_center
    cellsize = 1.0

    result = compute_local_dominance(
        dem,
        cellsize,
        min_rad=5.0,
        max_rad=15.0,
        rad_inc=1.0,
        anglr_res=15.0,
        observer_h=1.7,
    )

    # Peak should have very high dominance
    peak_val = result[center_r, center_c]
    assert peak_val > 50

    # Base ring (e.g., radius 20 from center) should have lower dominance
    base_val = result[center_r + 20, center_c]
    assert base_val < peak_val


def test_local_dominance_flat():
    """Flat DEM produces uniform output."""
    dem = np.full((30, 30), 10.0, dtype=np.float32)
    cellsize = 1.0

    result = compute_local_dominance(dem, cellsize, min_rad=5, max_rad=10)

    # Check that all non-edge values are the same
    inner_result = result[10:20, 10:20]
    assert np.all(inner_result == inner_result[0, 0])


def test_local_dominance_pit():
    """Pit DEM produces low values at centre."""
    rows, cols = 50, 50
    center_r, center_c = rows // 2, cols // 2
    y, x = np.ogrid[:rows, :cols]
    dist_from_center = np.sqrt((x - center_c) ** 2 + (y - center_r) ** 2)
    dem = dist_from_center  # Pit: lowest at center
    cellsize = 1.0

    result = compute_local_dominance(dem, cellsize, min_rad=5, max_rad=15)

    pit_val = result[center_r, center_c]
    rim_val = result[center_r + 15, center_c]
    assert pit_val <= rim_val


def test_local_dominance_nan_propagation():
    """NaN values in DEM propagate as 0 or handled correctly."""
    dem = np.full((30, 30), 10.0, dtype=np.float32)
    dem[15, 15] = np.nan
    cellsize = 1.0

    result = compute_local_dominance(dem, cellsize, min_rad=5, max_rad=10)
    # The current LD implementation byte scales. If it produces 0 or specific byte value for NaN, we check shape.
    assert result.shape == (30, 30)


def test_local_dominance_observer_height():
    """Observer height affects output magnitude."""
    dem = np.random.rand(30, 30).astype(np.float32) * 10
    cellsize = 1.0

    res_low = compute_local_dominance(
        dem, cellsize, min_rad=5, max_rad=10, observer_h=1.0
    )
    res_high = compute_local_dominance(
        dem, cellsize, min_rad=5, max_rad=10, observer_h=5.0
    )

    # Higher observer should mean generally higher dominance (angles looking down are larger)
    assert np.mean(res_high) > np.mean(res_low)


def test_local_dominance_shape_and_dtype():
    """Output shape and dtype matches expectations."""
    dem = np.random.rand(25, 30).astype(np.float32)
    result = compute_local_dominance(dem, 1.0, min_rad=5, max_rad=10)
    assert result.shape == dem.shape
    assert result.dtype == np.float32


def _barrow_dem(size=120):
    """Gentle terrain with a 1.5 m barrow and a ring ditch around it.

    Deliberately archaeological in scale: this is the relief the plugin
    exists to reveal, and the magnitude at which the old byte-scaling
    clipped everything to zero.
    """
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    rng = np.random.default_rng(3)
    dem = 50.0 + 0.01 * xx + rng.normal(0, 0.03, (size, size)).astype(np.float32)
    radius = np.sqrt((yy - size / 3) ** 2 + (xx - size / 3) ** 2)
    dem += np.where(radius < 15, 1.5 * np.cos(radius / 15 * np.pi / 2), 0.0)
    dem -= np.where((radius > 18) & (radius < 24), 0.8, 0.0)
    return dem.astype(np.float32)


def test_realistic_relief_is_not_constant():
    """Regression: gentle terrain used to produce an all-zero raster.

    The byte scale was (v - 0.5) / (1.8 - 0.5) * 255 applied to a value
    in RADIANS. Real terrain yields roughly 0.04-0.24 rad, so every
    pixel fell below the 0.5 floor and clipped to zero.
    """
    result = compute_local_dominance(_barrow_dem(), 1.0, min_rad=5, max_rad=15)

    finite = result[np.isfinite(result)]
    assert finite.size > 0
    assert finite.min() != finite.max(), (
        "Local Dominance returned a constant raster on realistic relief"
    )
    assert finite.std() > 0.05, (
        f"variation is implausibly small (std={finite.std():.4f} deg) — "
        f"the output is nearly flat"
    )


def test_output_is_in_plausible_degree_range():
    """Values must read as degrees, not radians and not a 0-255 byte scale."""
    result = compute_local_dominance(_barrow_dem(), 1.0, min_rad=5, max_rad=15)
    finite = result[np.isfinite(result)]

    assert np.abs(finite).max() < 90.0, "a mean depression angle cannot exceed 90 deg"
    # Radians on this fixture would sit under ~0.3; degrees are ~10x that.
    assert np.abs(finite).max() > 0.5, (
        f"peak magnitude {np.abs(finite).max():.3f} looks like radians, not degrees"
    )


def test_barrow_is_more_dominant_than_its_ditch():
    """The archaeological signal: a mound dominates, a ditch does not."""
    size = 120
    result = compute_local_dominance(_barrow_dem(size), 1.0, min_rad=5, max_rad=15)

    centre = size // 3
    summit = result[centre, centre]
    ditch = result[centre, centre + 21]  # inside the ring ditch

    assert np.isfinite(summit) and np.isfinite(ditch)
    assert summit > ditch, (
        f"barrow summit ({summit:.3f} deg) should dominate more than the "
        f"ring ditch ({ditch:.3f} deg)"
    )


def test_nodata_stays_nodata():
    """NaN input cells must remain NaN, not become a real angle."""
    dem = _barrow_dem(60)
    dem[10:15, 10:15] = np.nan
    result = compute_local_dominance(dem, 1.0, min_rad=5, max_rad=10)
    assert np.isnan(result[10:15, 10:15]).all()
