"""rvt_vis.py — Wrappers around the rvt-py Relief Visualization Toolbox.
exports: rvt_multidirectional_hillshade(array, cellsize, nr_directions, feedback)
         has_rvt() -> bool
used_by: algorithms/rvt_algorithm.py → rvt_multidirectional_hillshade
rules:
  Optional dependency — rvt-py is imported lazily so the plugin loads cleanly
  even when the package is missing. Callers should check has_rvt() before
  invoking, or catch RVTNotAvailable and surface an install hint to the user.
  Pure NumPy in/out; no QGIS imports.
  Input array is float32 with nodata as np.nan; output mirrors that convention
  and preserves NaN pixels.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def _unwrap_rvt_output(result: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Pad an rvt result back to ``reference``'s shape when rvt cropped its output.

    Some rvt.vis functions strip one cell from each edge depending on kernel
    mode and rvt's docs don't promise a stable contract on this. We
    defensively re-pad so ``process_in_tiles`` halo math stays aligned with
    the original DEM grid (any cropped edge would otherwise mis-correlate
    tile interiors with the source raster).
    """
    if result.ndim == 3:
        out_ch, out_rows, out_cols = result.shape
    else:
        out_rows, out_cols = result.shape
        out_ch = None

    in_rows, in_cols = reference.shape
    if out_rows == in_rows and out_cols == in_cols:
        return result

    pad_top = (in_rows - out_rows) // 2
    pad_left = (in_cols - out_cols) // 2
    pad_bottom = in_rows - out_rows - pad_top
    pad_right = in_cols - out_cols - pad_left

    if out_ch is not None:
        return np.pad(
            result,
            ((0, 0), (pad_top, pad_bottom), (pad_left, pad_right)),
            mode="edge",
        )
    else:
        return np.pad(
            result,
            ((pad_top, pad_bottom), (pad_left, pad_right)),
            mode="edge",
        )


class RVTNotAvailable(RuntimeError):
    """Raised when rvt-py is requested but not installed.

    The message contains the exact pip install command so the QGIS feedback
    surface can surface it unmodified to the user.
    """

    def __init__(self) -> None:
        super().__init__(
            "The rvt-py package is required for this algorithm but was not "
            "found in the current Python environment. Install it with:\n"
            "    pip install rvt-py"
        )


_RVT_VIS = None
_RVT_IMPORT_ERROR: Optional[Exception] = None


def has_rvt() -> bool:
    """Return True if the rvt.vis module is importable.

    Lazy-imports rvt on first call and caches both the module reference and
    any ImportError so subsequent calls are cheap and silent.
    """
    global _RVT_VIS, _RVT_IMPORT_ERROR
    if _RVT_VIS is not None or _RVT_IMPORT_ERROR is not None:
        return _RVT_VIS is not None
    try:
        import rvt.vis  # type: ignore[import-not-found]

        _RVT_VIS = rvt.vis
    except ImportError as exc:  # pragma: no cover - exercised on fresh env
        _RVT_IMPORT_ERROR = exc
    return _RVT_VIS is not None


def rvt_multidirectional_hillshade(
    array: np.ndarray,
    cellsize: float,
    nr_directions: int = 16,
    feedback=None,
) -> np.ndarray:
    """Multi-directional hillshade via rvt.vis.multi_hillshade.

    rvt-py blends hillshades from ``nr_directions`` evenly spaced solar azimuths
    (altitude fixed at 45°), returning a byte-scaled [0, 255] float32 array.
    We coerce the input NaN sentinel back to a high negative value that rvt
    treats as NoData (-9999), then reapply NaN on the matching output pixels
    so the rest of the pipeline sees a consistent nodata convention.

    Args:
        array: 2D float32 DEM, nodata as np.nan.
        cellsize: Pixel size in map units (metres). Passed as both X and Y
            resolution to rvt — anisotropic rasters should be resampled first.
        nr_directions: Number of azimuth directions (8/16/32 recommended).
            Must be >= 4 and <= 64.
        feedback: Optional QGIS feedback object for cancellation checks.

    Returns:
        Float32 array of illumination values in [0, 255], nodata preserved as
        np.nan. Shape matches input.

    Rules:
        NaN pixels in the input must be NaN in the output.
        Returns 0..255 float32 (rvt's native scale), NOT 0..1 — the per-tile
        writer in raster_utils will hand this back to the GDAL driver as
        GDT_Float32 so the user keeps the full numeric range in the GeoTIFF.
    """
    if not has_rvt():
        raise RVTNotAvailable()

    # 4..64 mirrors the documented contract of rvt.vis.multi_hillshade
    # — outside this range the function errors or returns an unusable fused
    # raster in rvt's reference implementation.
    if nr_directions < 4 or nr_directions > 64:
        raise ValueError(f"nr_directions must be between 4 and 64, got {nr_directions}")
    if cellsize <= 0:
        raise ValueError(f"cellsize must be positive, got {cellsize}")

    nan_mask = np.isnan(array)
    sanitized = array.copy()
    # rvt expects a finite nodata sentinel; -9999 is its default convention.
    sanitized[nan_mask] = -9999.0

    if feedback is not None and feedback.isCanceled():
        return np.full_like(array, np.nan)

    result_float = _RVT_VIS.multi_hillshade(
        dem=sanitized,
        resolution_x=float(cellsize),
        resolution_y=float(cellsize),
        nr_directions=int(nr_directions),
        no_data=-9999.0,
    )

    result = np.asarray(result_float, dtype=np.float32)
    padded = _unwrap_rvt_output(result, array)

    # Transpose from (directions, rows, cols) to (rows, cols, directions)
    padded_transposed = np.transpose(padded, (1, 2, 0))

    # Re-apply NaN where the input was nodata. We use the input mask directly
    # because rvt converts -9999 to its own internal nodata at the edges — we
    # want pixel-exact parity with the source DEM.
    padded_transposed[nan_mask] = np.nan

    return padded_transposed


def rvt_openness(
    array: np.ndarray,
    cellsize: float,
    num_directions: int = 16,
    search_radius: int = 20,
    is_negative: bool = False,
    ve: float = 1.0,
    feedback=None,
) -> np.ndarray:
    """Positive or negative topographic openness via rvt.vis.openness.

    rvt-py returns openness as zenith/nadir angles in radians split into a
    dict with ``pos`` and ``neg`` keys. We extract the requested mode,
    convert to degrees, and mirror the output contract of the native
    ``topographic_openness`` so the two implementations are drop-in
    alternatives for the QGIS Processing layer.

    Args:
        array: 2D float32 DEM, nodata as np.nan.
        cellsize: Pixel size in map units (metres). Passed as both X and Y
            resolution to rvt.
        num_directions: Number of azimuth directions (8/16/32 recommended).
            Must be >= 4 and <= 64.
        search_radius: Maximum search distance in pixels. 10..50 are typical;
            we accept 1..500 to match the native algorithm's bounds.
        is_negative: If True compute Negative Openness (concave features)
            instead of Positive Openness (convex features).
        ve: Vertical exaggeration passed to rvt (1.0 = no exaggeration).
        feedback: Optional QGIS feedback object for cancellation checks.

    Returns:
        Float32 array of openness values in DEGREES, in the Yokoyama
        [0, 180] range for both modes (flat terrain sits near 90). This
        matches the native ``topographic_openness`` contract, so the two
        implementations are interchangeable. Shape matches input.

        Negative mode does NOT return negative numbers — it is positive
        openness computed on an inverted DEM (rvt takes ``ve_factor``
        negative), so concave features read HIGH rather than low.
    """
    if not has_rvt():
        raise RVTNotAvailable()

    if cellsize <= 0:
        raise ValueError(f"cellsize must be positive, got {cellsize}")
    if num_directions < 4 or num_directions > 64:
        raise ValueError(
            f"num_directions must be between 4 and 64, got {num_directions}"
        )
    if search_radius < 1 or search_radius > 500:
        raise ValueError(
            f"search_radius must be between 1 and 500, got {search_radius}"
        )

    nan_mask = np.isnan(array)
    sanitized = array.copy()
    sanitized[nan_mask] = -9999.0

    if feedback is not None and feedback.isCanceled():
        return np.full_like(array, np.nan)

    # In rvt-py version 2.x, openness is calculated via sky_view_factor.
    # To compute negative openness, we compute positive openness on the inverted DEM (ve_factor = -ve).
    ve_factor = -float(ve) if is_negative else float(ve)
    result_obj = _RVT_VIS.sky_view_factor(
        dem=sanitized,
        resolution=float(cellsize),
        compute_svf=False,
        compute_opns=True,
        svf_n_dir=int(num_directions),
        svf_r_max=int(search_radius),
        ve_factor=ve_factor,
        no_data=-9999.0,
    )

    if isinstance(result_obj, dict):
        result_float = result_obj.get("opns")
        if result_float is None:
            raise RuntimeError(
                f"rvt.vis.sky_view_factor did not return an 'opns' array; "
                f"got keys={list(result_obj.keys())}"
            )
    else:
        result_float = result_obj

    # In rvt-py version 2.x, sky_view_factor returns openness values in degrees,
    # in the range [0, 180] (matching the Yokoyama topographic openness contract).
    result = np.asarray(result_float, dtype=np.float32)
    padded = _unwrap_rvt_output(result, array)
    padded[nan_mask] = np.nan
    return padded


def rvt_single_hillshade(
    array: np.ndarray,
    cellsize: float,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
    feedback=None,
) -> np.ndarray:
    """Single-direction hillshade via rvt.vis.hillshade.

    Mirrors ``rvt_multidirectional_hillshade`` but returns a single sun angle.
    Useful for users who want to match rvt's published reference output for
    cross-validation against other RVT installations.
    """
    if not has_rvt():
        raise RVTNotAvailable()

    if cellsize <= 0:
        raise ValueError(f"cellsize must be positive, got {cellsize}")

    nan_mask = np.isnan(array)
    sanitized = array.copy()
    sanitized[nan_mask] = -9999.0

    if feedback is not None and feedback.isCanceled():
        return np.full_like(array, np.nan)

    result_float = _RVT_VIS.hillshade(
        dem=sanitized,
        resolution_x=float(cellsize),
        resolution_y=float(cellsize),
        sun_azimuth=float(azimuth_deg),
        sun_elevation=float(altitude_deg),
        no_data=-9999.0,
    )

    result = np.asarray(result_float, dtype=np.float32)
    padded = _unwrap_rvt_output(result, array)
    padded[nan_mask] = np.nan
    return padded
