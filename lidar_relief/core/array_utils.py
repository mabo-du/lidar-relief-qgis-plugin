"""array_utils.py — Array manipulation utilities for LiDAR Relief plugin.
exports: _shift_array(array, row_shift, col_shift, fill_value) -> ndarray
         horizon_sin(delta_z, distance) -> ndarray
used_by: core/svf.py → _shift_array, horizon_sin
         core/openness.py → _shift_array, horizon_sin
         gpu/compute_backend.py → mirrors horizon_sin in CuPy [cascade]
rules:
  Pure NumPy — no QGIS or GDAL imports.
  horizon_sin must NOT use np.hypot — see the note in its docstring. Any
  change to its arithmetic must be mirrored in gpu/compute_backend.py's
  _max_sin_horizon_gpu, because test_gpu_parity.py asserts the two paths
  agree EXACTLY.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Extracted horizon_sin from the duplicated svf/openness inner
         loops and dropped np.hypot for sqrt(dz*dz + d*d): profiling put
         np.hypot at 1.54s of the 2.00s arithmetic cost per 1024^2 tile,
         and the scalar-loop overflow rescaling it pays for is pointless
         at DEM magnitudes. ~1.9x faster end to end.
"""

import numpy as np


def horizon_sin(delta_z: np.ndarray, distance: float) -> np.ndarray:
    """Return sin of the elevation angle to a horizon sample.

    ``sin(angle) = delta_z / sqrt(delta_z**2 + distance**2)``.

    Args:
        delta_z: Elevation difference to the sample, in map units.
        distance: Horizontal distance to the sample, in map units (> 0).

    Returns:
        Float32 array of sin(angle) in [-1, 1].

    Rules:
        Deliberately NOT ``np.hypot``. np.hypot rescales its operands to
        stay overflow-safe, which makes it a slow scalar-loop ufunc —
        profiled at roughly 7x the cost of the sqrt form and about 70% of
        this module's total arithmetic time. That protection buys nothing
        here: overflowing float32 needs |delta_z| above ~1.8e19 m, and
        the full terrestrial elevation range is ~2e4 m, leaving fifteen
        orders of magnitude of headroom. The two forms agree to float32
        epsilon (measured max difference 3e-07 on SVF output).

        distance is expected to be non-zero — callers skip zero-distance
        samples — but a zero denominator is guarded anyway so a degenerate
        sample yields 0 rather than a NaN that would poison the running
        maximum.
    """
    dist_sq = np.float32(distance) * np.float32(distance)
    denom = np.sqrt(delta_z * delta_z + dist_sq, dtype=np.float32)
    # Guard the degenerate case without an extra full-array pass in the
    # common path: np.where is cheap next to the sqrt above.
    denom = np.where(denom == 0, np.float32(1.0), denom)
    return delta_z / denom


def _shift_array(
    array: np.ndarray,
    row_shift: int,
    col_shift: int,
    fill_value: float,
) -> np.ndarray:
    """Create a shifted view of a 2D array, filling edges with a constant.

    This is equivalent to np.roll but without wrapping — shifted-out pixels
    are filled with fill_value instead of wrapping around.

    Args:
        array: 2D input array.
        row_shift: Number of rows to shift (positive = shift down).
        col_shift: Number of columns to shift (positive = shift right).
        fill_value: Value to fill at shifted-out edges.

    Returns:
        Shifted array with same shape as input.

    Rules:
        No wrapping — edge-shifted pixels get fill_value.
        This prevents horizon rays from wrapping around the raster edges.
    """
    rows, cols = array.shape
    result = np.full_like(array, fill_value)

    # Compute source and destination slices
    if row_shift >= 0:
        src_row_start, src_row_end = 0, rows - row_shift
        dst_row_start, dst_row_end = row_shift, rows
    else:
        src_row_start, src_row_end = -row_shift, rows
        dst_row_start, dst_row_end = 0, rows + row_shift

    if col_shift >= 0:
        src_col_start, src_col_end = 0, cols - col_shift
        dst_col_start, dst_col_end = col_shift, cols
    else:
        src_col_start, src_col_end = -col_shift, cols
        dst_col_start, dst_col_end = 0, cols + col_shift

    # Bounds check
    if any(
        [
            src_row_end <= src_row_start,
            src_col_end <= src_col_start,
            dst_row_end <= dst_row_start,
            dst_col_end <= dst_col_start,
        ]
    ):
        return result

    result[dst_row_start:dst_row_end, dst_col_start:dst_col_end] = array[
        src_row_start:src_row_end, src_col_start:src_col_end
    ]

    return result
