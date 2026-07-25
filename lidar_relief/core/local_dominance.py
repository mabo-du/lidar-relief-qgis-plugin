"""local_dominance.py — Local Dominance visualization.
exports: compute_local_dominance(dem, cellsize, min_rad, max_rad, rad_inc, anglr_res, observer_h) -> ndarray
used_by: algorithms/local_dominance_algorithm.py → compute_local_dominance
         export/contact_sheet.py → compute_local_dominance
rules:
  Pure NumPy — no QGIS imports.
  Output is the mean depression angle in DEGREES — the angle by which an
  observer standing observer_h above the cell looks DOWN on the
  surrounding terrain. Positive = locally dominant (a summit or bank),
  near zero = flat, negative = dominated (a hollow or ditch floor).
  Do NOT byte-scale in here. Every other core algorithm returns its
  natural physical unit (slope and openness in degrees, SVF in 0..1) and
  lets the QGIS post-processor stretch for display; this one used to
  byte-scale against hard-coded limits and produced an all-zero raster.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Fixed: the function returned arctan(...) in RADIANS (typically
         0.04-0.24 on real terrain) then byte-scaled with
         (v - 0.5) / (1.8 - 0.5) * 255, limits that only make sense for
         a degree-scale quantity. Every pixel fell below 0.5 and clipped
         to zero, so Local Dominance emitted a CONSTANT raster for any
         terrain short of a cliff face. Now returns degrees and leaves
         display stretching to the post-processor.
         message: "found by rendering the new contact sheet — panel 8
         was flat grey while the other ten showed the test earthworks.
         A whole advertised algorithm was silently dead."
"""

import numpy as np


def compute_local_dominance(
    dem: np.ndarray,
    cellsize: float,
    min_rad: float = 10.0,
    max_rad: float = 20.0,
    rad_inc: float = 1.0,
    anglr_res: float = 15.0,
    observer_h: float = 1.7,
    feedback=None,
) -> np.ndarray:
    """Compute Local Dominance using horizon-scanning ray trace.

    For every direction and radius in range, measures the angle from the
    observer's eye (``observer_h`` above the cell) down to the terrain at
    that offset, and averages.

    Returns:
        Float32 array of mean depression angle in DEGREES. Typical bare
        terrain sits within a few degrees of zero; banks, barrows and
        summits read high, ditch floors and hollows read low.
        NaN where the input was nodata.
    """
    if cellsize <= 0:
        raise ValueError("cellsize must be greater than 0")

    rows, cols = dem.shape

    z_obs = dem + observer_h
    pad_w = int(np.ceil(max_rad))
    padded_dem = np.pad(dem, pad_width=pad_w, mode="edge")

    ld_accumulator = np.zeros_like(dem, dtype=np.float32)
    valid_counts = np.zeros_like(dem, dtype=np.float32)

    # Use ceil to ensure we cover the full 360° even when anglr_res
    # doesn't divide 360 evenly (e.g. 7° → 52 directions covers 364°,
    # which is fine — the last direction overlaps the first by 4°).
    # The previous code used int(360/anglr_res) which silently left
    # a gap (e.g. 7° → 51 directions covers only 357°).
    n_directions = max(1, int(np.ceil(360.0 / anglr_res)))
    directions = np.linspace(0, 2 * np.pi, n_directions, endpoint=False)
    radii = np.arange(min_rad, max_rad + rad_inc, rad_inc)

    total_steps = len(directions)

    for i, theta in enumerate(directions):
        if feedback and feedback.isCanceled():
            # Return a full NaN-filled array of the correct shape so
            # callers can handle this consistently with other algorithms.
            # The previous code returned np.array([]) which crashed any
            # downstream code that tried to use the result as a raster.
            return np.full_like(dem, np.nan, dtype=np.float32)

        for r in radii:
            dy = int(np.round(-r * np.cos(theta)))
            dx = int(np.round(r * np.sin(theta)))

            # Slice padded DEM to get target_z
            y1, y2 = pad_w + dy, pad_w + dy + rows
            x1, x2 = pad_w + dx, pad_w + dx + cols
            target_z = padded_dem[y1:y2, x1:x2]

            delta_z = z_obs - target_z
            # dist could be zero if min_rad == 0; guard to avoid
            # ZeroDivisionError in np.arctan below.
            dist = r * cellsize
            if dist == 0:
                continue

            angle_grid = np.arctan(delta_z / dist)

            # valid_counts where neither DEM nor target is NaN
            valid_mask = ~(np.isnan(dem) | np.isnan(target_z))

            # Mask out NaNs so they don't corrupt the accumulator
            angle_grid = np.where(valid_mask, angle_grid, 0)

            ld_accumulator += angle_grid
            valid_counts += valid_mask.astype(np.float32)

        if feedback is not None:
            feedback.setProgress(int((i + 1) / total_steps * 100))

    # To avoid division by zero on entirely NaN inputs
    with np.errstate(invalid="ignore"):
        ld_final = np.where(valid_counts > 0, ld_accumulator / valid_counts, np.nan)

    # Convert the mean angle from radians to degrees. The previous code
    # byte-scaled here with (v - 0.5) / (1.8 - 0.5) * 255; those limits
    # suit a degree-scale quantity, but ld_final is in radians and runs
    # roughly 0.04..0.24 on real terrain, so every pixel clipped to 0.
    return np.degrees(ld_final).astype(np.float32)
