"""compute_backend.py — GPU-accelerated compute backends with transparent fallback.

exports: get_backend() -> str,
         cupy_available() -> bool,
         to_array_backend(array, backend) -> Array,
         asnumpy(array) -> np.ndarray,
         compute_svf_gpu(dem, cellsize, **kwargs) -> np.ndarray,
         compute_openness_gpu(dem, cellsize, **kwargs) -> np.ndarray

used_by: core/svf.py → compute_svf_gpu (via sky_view_factor(use_gpu=True))
         core/openness.py → compute_openness_gpu
             (via topographic_openness(use_gpu=True))

rules:
  Dynamic dispatch: CuPy if an NVIDIA GPU is available, else NumPy.
  The GPU kernels MUST consume the SAME horizon sample geometry as the
  CPU path — ``core.svf._build_horizon_samples``. Do not re-derive
  directions here. The pre-2.0.23 implementation used
  ``round(cos(theta))``/``round(sin(theta))``, which quantises every
  azimuth to one of 8 integer directions: 16- and 32-direction requests
  silently collapsed to 8, and the ray stepped in whole-pixel units
  instead of the supersampled/deduplicated ray the CPU walks. GPU and
  CPU results disagreed by far more than float error.
  GPU results are **numerically close** to NumPy (typically within 1e-5
  for float32) but NOT bit-identical — CUDA floating-point operations
  are not bit-reproducible across GPU architectures or drivers. Callers
  that require bit-identical output (e.g. reproducible test fixtures)
  should force the NumPy backend via ``get_backend(prefer_cuda=False)``.
  No CUDA-specific code in the main algorithm cores — cores dispatch
  here and this module owns every CuPy reference.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Rewrote the horizon kernels to share _build_horizon_samples so
         GPU == CPU, hardened the CuPy import (a broken driver raised
         out of `cp.is_available()` past the ImportError guard and took
         the module down), and made noise_level fall back to CPU rather
         than silently ignoring it. Wired the backend into
         core/svf.py + core/openness.py — before this it was reachable
         only from tests, so the README's "GPU acceleration" feature
         did not exist for users.
         message: "test_gpu's equivalence tests only run under CUDA, so
         the direction-collapse bug was invisible on CI. Added
         test_gpu_parity.py which asserts the sampling contract on CPU."
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Try importing CuPy.
#
# `cp.is_available()` probes the CUDA runtime and raises (not returns
# False) when CuPy is installed against a driver that is missing, too
# old, or mismatched — e.g. cupy.cuda.runtime.CUDARuntimeError. Catching
# only ImportError let that propagate out of module import, which took
# the whole plugin down at QGIS start-up for anyone with a stale CUDA
# install. Any failure to probe means "no usable GPU".
try:
    import cupy as cp

    _CUDA_AVAILABLE = bool(cp.is_available())
except ImportError:
    _CUDA_AVAILABLE = False
    cp = None
except Exception as exc:  # pragma: no cover — needs a broken CUDA install
    logger.warning(
        "CuPy is installed but the CUDA runtime could not be probed (%s: %s). "
        "Falling back to the NumPy backend.",
        type(exc).__name__,
        exc,
    )
    _CUDA_AVAILABLE = False
    cp = None


# Backend registry
_BACKENDS = {"numpy": np}


def cupy_available() -> bool:
    """Check if CuPy is installed and CUDA is available."""
    return _CUDA_AVAILABLE


def get_backend(prefer_cuda: bool = True) -> str:
    """Return the preferred compute backend ('cupy' or 'numpy').

    Args:
        prefer_cuda: If True and CuPy is available, return 'cupy'.

    Returns:
        'cupy' if CUDA is available and preferred, else 'numpy'.
    """
    if prefer_cuda and _CUDA_AVAILABLE:
        return "cupy"
    return "numpy"


def to_array_backend(
    array: np.ndarray,
    backend: str = "numpy",
) -> np.ndarray:
    """Transfer a NumPy array to the specified backend.

    Args:
        array: NumPy array on CPU.
        backend: 'cupy' or 'numpy'.

    Returns:
        Array on the target backend.
    """
    if backend == "cupy" and _CUDA_AVAILABLE:
        return cp.asarray(array)
    return array


def asnumpy(array) -> np.ndarray:
    """Convert any backend array to NumPy.

    Args:
        array: NumPy or CuPy array.

    Returns:
        NumPy array on CPU.
    """
    if _CUDA_AVAILABLE and isinstance(array, cp.ndarray):
        return cp.asnumpy(array)
    return np.asarray(array)


def _shift_array_gpu(
    arr: "cp.ndarray",
    shift_y: int,
    shift_x: int,
    fill_value: float = 0.0,
) -> "cp.ndarray":
    """CuPy-native array shift (parallel to array_utils._shift_array).

    Rules:
        Semantics must match ``core.array_utils._shift_array`` exactly:
        positive ``shift_y`` moves content DOWN, positive ``shift_x``
        moves content RIGHT, and vacated edges take ``fill_value``
        (no wrap-around).
        The overlap along each axis is ``size - abs(shift)``. The
        pre-2.0.23 code computed it as ``size + min(0, shift)`` minus
        ``max(0, -shift)``, which is ``size`` for a positive shift and
        ``size - 2*abs(shift)`` for a negative one — never right unless
        the shift was zero. Every GPU horizon step therefore raised
        ``ValueError: could not broadcast input array``, so the CuPy
        path could not complete a single run on real CUDA hardware.
    """
    rows, cols = arr.shape
    result = cp.full_like(arr, fill_value)
    if shift_y == 0 and shift_x == 0:
        return arr.copy()

    if shift_y >= 0:
        src_row_start, src_row_end = 0, rows - shift_y
        dst_row_start, dst_row_end = shift_y, rows
    else:
        src_row_start, src_row_end = -shift_y, rows
        dst_row_start, dst_row_end = 0, rows + shift_y

    if shift_x >= 0:
        src_col_start, src_col_end = 0, cols - shift_x
        dst_col_start, dst_col_end = shift_x, cols
    else:
        src_col_start, src_col_end = -shift_x, cols
        dst_col_start, dst_col_end = 0, cols + shift_x

    # Shift larger than the array: nothing overlaps, all fill_value.
    if src_row_end <= src_row_start or src_col_end <= src_col_start:
        return result

    result[dst_row_start:dst_row_end, dst_col_start:dst_col_end] = arr[
        src_row_start:src_row_end, src_col_start:src_col_end
    ]

    return result


def _max_sin_horizon_gpu(
    dem_filled: "cp.ndarray",
    fill_value: float,
    row_shifts,
    col_shifts,
    dists,
    cellsize: float,
    init_val: float,
) -> "cp.ndarray":
    """Maximum sin(horizon angle) along one azimuth, on the GPU.

    Walks the SAME (row_shift, col_shift, distance) samples the CPU
    walks — see ``core.svf._build_horizon_samples`` — so the only
    divergence from the NumPy path is float accumulation order.

    Args:
        dem_filled: DEM on the GPU with NaN already replaced.
        fill_value: Value used for pixels shifted in from outside.
        row_shifts: Integer row offsets along the ray.
        col_shifts: Integer column offsets along the ray.
        dists: True Euclidean distance to each sample, in pixel units.
        cellsize: Pixel size in map units.
        init_val: Starting value (0.0 for SVF, -1.0 for openness).

    Returns:
        CuPy float32 array of max sin(horizon) per pixel.
    """
    max_sin = cp.full(dem_filled.shape, init_val, dtype=cp.float32)

    for row_shift, col_shift, dist_units in zip(row_shifts, col_shifts, dists):
        actual_dist = dist_units * cellsize
        if actual_dist == 0:
            continue

        shifted = _shift_array_gpu(dem_filled, row_shift, col_shift, fill_value)
        delta_z = shifted - dem_filled
        # Mirrors core.array_utils.horizon_sin EXACTLY — not cp.hypot.
        # test_gpu_parity.py asserts bit-equality against the CPU path
        # through a NumPy-backed shim, so the two formulas must match
        # operation for operation, not merely agree to a tolerance.
        dist_sq = cp.float32(actual_dist) * cp.float32(actual_dist)
        denom = cp.sqrt(delta_z * delta_z + dist_sq, dtype=cp.float32)
        denom = cp.where(denom == 0, cp.float32(1.0), denom)
        sin_angle = delta_z / denom

        max_sin = cp.maximum(max_sin, sin_angle)

    return max_sin


def compute_svf_gpu(
    dem: np.ndarray,
    cellsize: float,
    num_directions: int = 16,
    search_radius: int = 10,
    noise_level: int = 0,
    feedback=None,
) -> np.ndarray:
    """Compute Sky-View Factor using GPU acceleration.

    Falls back to the NumPy implementation when CUDA is unavailable, or
    when ``noise_level > 0`` (the look-ahead noise filter is CPU-only —
    running an approximation here would silently change results relative
    to the CPU path, which is worse than being slower).

    Args:
        dem: 2D float32 NumPy array.
        cellsize: Cell size in map units.
        num_directions: Number of azimuth directions.
        search_radius: Search radius in pixels.
        noise_level: Look-ahead noise filter strength. Non-zero forces
            the CPU path.
        feedback: Optional QGIS feedback object for progress/cancellation.

    Returns:
        2D float32 NumPy array (SVF values, 0–1).
    """
    from ..core.svf import _build_horizon_samples, sky_view_factor

    if not _CUDA_AVAILABLE:
        logger.debug("CUDA not available, falling back to NumPy SVF")
        return sky_view_factor(
            dem, cellsize, num_directions, search_radius, noise_level, feedback
        )
    if noise_level > 0:
        logger.info(
            "SVF noise_level=%d requested; the look-ahead filter is CPU-only, "
            "using the NumPy backend to keep results consistent.",
            noise_level,
        )
        return sky_view_factor(
            dem, cellsize, num_directions, search_radius, noise_level, feedback
        )

    nan_mask_cpu = np.isnan(dem)
    dem_mean = float(np.nanmean(dem)) if not nan_mask_cpu.all() else 0.0

    d_dem = cp.asarray(dem, dtype=cp.float32)
    d_nan_mask = cp.asarray(nan_mask_cpu)
    d_dem = cp.where(d_nan_mask, cp.float32(dem_mean), d_dem)

    horizon_samples = _build_horizon_samples(num_directions, search_radius)
    sin_horizon_sum = cp.zeros(d_dem.shape, dtype=cp.float32)

    for dir_idx, row_shifts, col_shifts, dists in horizon_samples:
        if feedback is not None and feedback.isCanceled():
            return np.full_like(dem, np.nan)

        max_sin = _max_sin_horizon_gpu(
            d_dem, dem_mean, row_shifts, col_shifts, dists, cellsize, init_val=0.0
        )
        sin_horizon_sum += cp.maximum(max_sin, cp.float32(0.0))

        if feedback is not None:
            feedback.setProgress(int((dir_idx + 1) / num_directions * 100))

    svf = 1.0 - (sin_horizon_sum / num_directions)
    svf = cp.clip(svf, 0.0, 1.0).astype(cp.float32)
    svf = cp.where(d_nan_mask, cp.float32(np.nan), svf)

    return cp.asnumpy(svf)


def compute_openness_gpu(
    dem: np.ndarray,
    cellsize: float,
    num_directions: int = 16,
    search_radius: int = 10,
    is_negative: bool = False,
    feedback=None,
) -> np.ndarray:
    """Compute Topographic Openness using GPU acceleration.

    Falls back to the NumPy implementation when CUDA is unavailable.

    Args:
        dem: 2D float32 NumPy array.
        cellsize: Cell size in map units.
        num_directions: Number of azimuth directions.
        search_radius: Search radius in pixels.
        is_negative: If True, compute negative openness.
        feedback: Optional QGIS feedback object for progress/cancellation.

    Returns:
        2D float32 NumPy array (degrees).
    """
    from ..core.openness import topographic_openness
    from ..core.svf import _build_horizon_samples

    if not _CUDA_AVAILABLE:
        logger.debug("CUDA not available, falling back to NumPy Openness")
        return topographic_openness(
            dem, cellsize, num_directions, search_radius, is_negative, feedback
        )

    working = -dem if is_negative else dem

    nan_mask_cpu = np.isnan(working)
    dem_mean = float(np.nanmean(working)) if not nan_mask_cpu.all() else 0.0

    d_dem = cp.asarray(working, dtype=cp.float32)
    d_nan_mask = cp.asarray(nan_mask_cpu)
    d_dem = cp.where(d_nan_mask, cp.float32(dem_mean), d_dem)

    horizon_samples = _build_horizon_samples(num_directions, search_radius)
    openness_sum = cp.zeros(d_dem.shape, dtype=cp.float32)

    for dir_idx, row_shifts, col_shifts, dists in horizon_samples:
        if feedback is not None and feedback.isCanceled():
            return np.full_like(dem, np.nan)

        max_sin = _max_sin_horizon_gpu(
            d_dem, dem_mean, row_shifts, col_shifts, dists, cellsize, init_val=-1.0
        )
        # Clamp before arcsin — float drift can push max_sin outside
        # [-1, 1] and arcsin would return NaN for those pixels.
        max_sin = cp.clip(max_sin, -1.0, 1.0)
        openness_sum += cp.pi / 2.0 - cp.arcsin(max_sin)

        if feedback is not None:
            feedback.setProgress(int((dir_idx + 1) / num_directions * 100))

    result_deg = cp.degrees(openness_sum / num_directions).astype(cp.float32)
    result_deg = cp.where(d_nan_mask, cp.float32(np.nan), result_deg)

    return cp.asnumpy(result_deg)
