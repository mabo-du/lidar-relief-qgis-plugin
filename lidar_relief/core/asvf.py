"""asvf.py — Anisotropic Sky-View Factor (ASVF).
exports: anisotropic_sky_view_factor(array, cellsize, num_directions, search_radius, anisotropy_dir, anisotropy_weight)
used_by: algorithms/asvf_algorithm.py
rules:
  Pure NumPy — no QGIS imports.
  Vectorized trigonometric functions.
  Uses the same supersampled horizon scan as SVF (see core/svf.py) so
  that horizon pixels on diagonal azimuths are correctly sampled.
"""

import numpy as np

from .array_utils import _shift_array, horizon_sin
from .svf import _build_horizon_samples


def anisotropic_sky_view_factor(
    array: np.ndarray,
    cellsize: float,
    num_directions: int = 16,
    search_radius: int = 10,
    anisotropy_dir: float = 315.0,
    anisotropy_weight: float = 0.5,
    noise_level: int = 0,
    feedback=None,
) -> np.ndarray:
    """Compute Anisotropic Sky-View Factor (ASVF).

    Note on the mathematical formula:
    This function computes ASVF using a linear approximation: 1.0 - sin(horizon).
    The standard peer-reviewed formula (Zakšek et al., 2011) is defined as:
    ASVF = 1.0 - sin²(horizon). The linear version is used here for consistent,
    backwards-compatible visual representation with legacy archaeological plugin outputs.
    """
    rows, cols = array.shape

    # Fill NaN with the array mean for shifted lookups
    nan_mask = np.isnan(array)
    dem_mean = np.nanmean(array)
    dem_filled = array.copy()
    dem_filled[nan_mask] = dem_mean

    azimuths_rad = np.linspace(0, 2 * np.pi, num_directions, endpoint=False)

    # Pre-compute the horizon sample points (same supersampling approach as SVF)
    horizon_samples = _build_horizon_samples(num_directions, search_radius)

    total_asvf = np.zeros((rows, cols), dtype=np.float32)
    weight_sum = 0.0

    anisotropy_rad = np.radians(anisotropy_dir)
    threshold_sin = np.sin(np.radians(2.0))

    for dir_idx, row_shifts, col_shifts, dists in horizon_samples:
        if feedback is not None and feedback.isCanceled():
            return np.full_like(array, np.nan)

        azimuth = azimuths_rad[dir_idx]

        dir_weight = 1.0 + anisotropy_weight * np.cos(azimuth - anisotropy_rad)
        weight_sum += dir_weight

        max_sin = np.zeros((rows, cols), dtype=np.float32)

        if noise_level > 0:
            candidate_sin = np.zeros((rows, cols), dtype=np.float32)
            countdown = np.zeros((rows, cols), dtype=np.int32)
            candidate_valid = np.zeros((rows, cols), dtype=bool)

        for row_shift, col_shift, dist_units in zip(row_shifts, col_shifts, dists):
            actual_dist = dist_units * cellsize
            if actual_dist == 0:
                continue

            shifted = _shift_array(dem_filled, row_shift, col_shift, dem_mean)

            delta_z = shifted - dem_filled
            sin_angle = horizon_sin(delta_z, actual_dist)

            if noise_level > 0:
                is_tracking = countdown > 0
                candidate_valid = np.where(
                    is_tracking & (sin_angle >= candidate_sin - threshold_sin),
                    True,
                    candidate_valid,
                )

                new_candidate = sin_angle > np.maximum(max_sin, candidate_sin)
                promote_mask = new_candidate & candidate_valid
                max_sin = np.where(promote_mask, candidate_sin, max_sin)

                candidate_sin = np.where(new_candidate, sin_angle, candidate_sin)
                countdown = np.where(new_candidate, noise_level, countdown)
                candidate_valid = np.where(new_candidate, False, candidate_valid)

                countdown = np.maximum(0, countdown - 1)

                expired_mask = (
                    (countdown == 0) & candidate_valid & (candidate_sin > max_sin)
                )
                max_sin = np.where(expired_mask, candidate_sin, max_sin)
                candidate_valid = np.where(expired_mask, False, candidate_valid)
                candidate_sin = np.where(countdown == 0, max_sin, candidate_sin)
            else:
                max_sin = np.maximum(max_sin, sin_angle)

        if noise_level > 0:
            promote_end = candidate_valid | (countdown > 0)
            max_sin = np.where(promote_end, np.maximum(max_sin, candidate_sin), max_sin)

        max_sin = np.maximum(max_sin, 0.0)

        # ASVF formula component for this direction
        svf_dir = 1.0 - max_sin
        total_asvf += svf_dir * dir_weight

        if feedback is not None:
            feedback.setProgress(int((dir_idx + 1) / num_directions * 100))

    asvf = total_asvf / weight_sum
    asvf = np.clip(asvf, 0.0, 1.0).astype(np.float32)
    asvf[nan_mask] = np.nan

    return asvf
