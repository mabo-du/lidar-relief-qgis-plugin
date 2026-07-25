"""test_gpu_parity.py — CPU-runnable guards on the GPU backend contract.

exports: (test functions)
used_by: pytest runner
rules:
  test_gpu.py's numerical-equivalence tests are skipped without CUDA,
  which is why the pre-2.0.23 GPU kernels shipped for two minor versions
  quantising every azimuth to one of 8 integer directions — 16- and
  32-direction requests silently collapsed to 8 and never matched the
  CPU. These tests assert the SHARED-GEOMETRY contract instead of the
  numbers, so they run on any machine, CUDA or not.
  Add a test here whenever the GPU path gains a behaviour the CPU path
  also has.
"""

import numpy as np
import pytest

from lidar_relief.core.array_utils import _shift_array
from lidar_relief.core.openness import topographic_openness
from lidar_relief.core.svf import _build_horizon_samples, sky_view_factor
from lidar_relief.gpu import compute_backend
from lidar_relief.gpu.compute_backend import (
    compute_openness_gpu,
    compute_svf_gpu,
    cupy_available,
)


@pytest.fixture
def cone_dem():
    """Small DEM with a cone — enough occlusion to make SVF vary."""
    size = 40
    yy, xx = np.mgrid[0:size, 0:size]
    dem = np.zeros((size, size), dtype=np.float32)
    dem += np.maximum(0.0, 10.0 - np.sqrt((yy - 20) ** 2 + (xx - 20) ** 2)).astype(
        np.float32
    )
    return dem


class TestHorizonSamplingContract:
    """The horizon geometry both backends must share."""

    @pytest.mark.parametrize("num_directions", [8, 16, 32])
    def test_every_direction_is_distinct(self, num_directions):
        """N directions must yield N distinct rays.

        Regression guard: `round(cos(theta))`/`round(sin(theta))`
        produces only 8 unique integer directions for ANY N, so 16 and
        32 collapsed onto 8.

        Note the invariant is the WHOLE ray, not its first step — the
        pixel adjacent to the origin always rounds to one of the 8
        neighbours no matter how finely the azimuth is sampled. Azimuths
        separate further out, which is exactly what the old GPU code
        threw away by stepping in whole-pixel multiples of a rounded
        direction vector.
        """
        samples = _build_horizon_samples(num_directions, search_radius=16)
        assert len(samples) == num_directions

        rays = set()
        for _dir_idx, rows, cols, _dists in samples:
            assert rows, "every direction must sample at least one pixel"
            rays.add(tuple(zip(rows, cols)))
        assert len(rays) == num_directions, (
            f"{num_directions} directions collapsed to {len(rays)} distinct "
            f"rays — azimuths are being quantised"
        )

    def test_rounded_direction_vectors_would_collapse(self):
        """Pin down WHY the old GPU kernel diverged.

        `round(cos)`/`round(sin)` yields at most 8 unique integer
        directions regardless of the requested count. Kept as executable
        documentation so nobody reintroduces the shortcut.
        """
        for num_directions in (8, 16, 32):
            angles = np.linspace(0, 2 * np.pi, num_directions, endpoint=False)
            dx = np.round(np.cos(angles)).astype(int)
            dy = np.round(np.sin(angles)).astype(int)
            assert len(set(zip(dx.tolist(), dy.tolist()))) == 8

    def test_samples_are_deduplicated_and_ordered(self):
        """Each ray visits distinct pixels at increasing distance."""
        samples = _build_horizon_samples(16, search_radius=12)
        for _dir_idx, rows, cols, dists in samples:
            pixels = list(zip(rows, cols))
            assert len(pixels) == len(set(pixels)), "duplicate pixels on a ray"
            assert (0, 0) not in pixels, "the origin pixel must not be sampled"
            assert dists == sorted(dists), "samples must be ordered by distance"

    def test_distances_match_pixel_offsets(self):
        """Reported distance must be the true Euclidean distance."""
        samples = _build_horizon_samples(8, search_radius=6)
        for _dir_idx, rows, cols, dists in samples:
            for r, c, d in zip(rows, cols, dists):
                assert d == pytest.approx(np.hypot(r, c), abs=0.75), (
                    "distance must track the integer pixel it belongs to"
                )


class TestGpuFallback:
    """Without CUDA the GPU entry points must transparently use NumPy."""

    @pytest.mark.skipif(cupy_available(), reason="CUDA present; fallback not exercised")
    def test_svf_gpu_falls_back_exactly(self, cone_dem):
        """compute_svf_gpu must return the CPU result, not an approximation."""
        gpu = compute_svf_gpu(cone_dem, 1.0, num_directions=16, search_radius=8)
        cpu = sky_view_factor(cone_dem, 1.0, num_directions=16, search_radius=8)
        np.testing.assert_allclose(gpu, cpu, rtol=0, atol=0)

    @pytest.mark.skipif(cupy_available(), reason="CUDA present; fallback not exercised")
    def test_openness_gpu_falls_back_exactly(self, cone_dem):
        """compute_openness_gpu must return the CPU result."""
        gpu = compute_openness_gpu(cone_dem, 1.0, num_directions=16, search_radius=8)
        cpu = topographic_openness(cone_dem, 1.0, num_directions=16, search_radius=8)
        np.testing.assert_allclose(gpu, cpu, rtol=0, atol=0)

    def test_use_gpu_flag_is_safe_without_cuda(self, cone_dem):
        """sky_view_factor(use_gpu=True) must never raise, CUDA or not."""
        result = sky_view_factor(
            cone_dem, 1.0, num_directions=8, search_radius=6, use_gpu=True
        )
        assert result.shape == cone_dem.shape
        assert np.all((result >= 0.0) & (result <= 1.0))

    def test_openness_use_gpu_flag_is_safe_without_cuda(self, cone_dem):
        """topographic_openness(use_gpu=True) must never raise."""
        result = topographic_openness(
            cone_dem, 1.0, num_directions=8, search_radius=6, use_gpu=True
        )
        assert result.shape == cone_dem.shape
        assert np.all(np.isfinite(result))

    def test_noise_level_forces_cpu_path(self, cone_dem):
        """noise_level > 0 has no GPU kernel — it must use the CPU one.

        Silently dropping the filter would change results without telling
        anyone, so the GPU entry point delegates instead.
        """
        gpu = compute_svf_gpu(
            cone_dem, 1.0, num_directions=8, search_radius=6, noise_level=2
        )
        cpu = sky_view_factor(
            cone_dem, 1.0, num_directions=8, search_radius=6, noise_level=2
        )
        np.testing.assert_allclose(gpu, cpu, rtol=0, atol=0)


class _NumpyCupyShim:
    """A stand-in for the ``cupy`` module backed by NumPy.

    The CuPy branches of compute_backend are otherwise only executed on
    a machine with a working CUDA install — which is exactly why two
    independent defects shipped in them (azimuth quantisation, and slice
    arithmetic in ``_shift_array_gpu`` that raised
    ``ValueError: could not broadcast input array`` on every horizon
    step). Swapping in this shim runs the real kernel code everywhere.

    Rules:
        Only forward names the kernels actually use. A shim that
        forwards everything hides the day a kernel starts depending on
        a genuinely CUDA-only API.
    """

    ndarray = np.ndarray
    nan = np.nan
    pi = np.pi
    float32 = np.float32

    asarray = staticmethod(np.asarray)
    arcsin = staticmethod(np.arcsin)
    clip = staticmethod(np.clip)
    degrees = staticmethod(np.degrees)
    full = staticmethod(np.full)
    full_like = staticmethod(np.full_like)
    maximum = staticmethod(np.maximum)
    sqrt = staticmethod(np.sqrt)
    where = staticmethod(np.where)
    zeros = staticmethod(np.zeros)

    @staticmethod
    def asnumpy(array):
        return np.asarray(array)


@pytest.fixture
def simulated_cuda(monkeypatch):
    """Force compute_backend down its CuPy branches using NumPy."""
    monkeypatch.setattr(compute_backend, "cp", _NumpyCupyShim)
    monkeypatch.setattr(compute_backend, "_CUDA_AVAILABLE", True)
    return compute_backend


class TestGpuKernelsMatchCpu:
    """The CuPy kernels must reproduce the NumPy reference exactly.

    Exact equality (not a tolerance) is achievable here because the shim
    IS NumPy — any difference means the kernels disagree structurally,
    which is the failure class that shipped. On real CUDA the tolerance
    tests in test_gpu.py take over.
    """

    @pytest.mark.parametrize("num_directions", [8, 16, 32])
    def test_svf_matches(self, simulated_cuda, cone_dem, num_directions):
        gpu = simulated_cuda.compute_svf_gpu(
            cone_dem, 1.0, num_directions=num_directions, search_radius=10
        )
        cpu = sky_view_factor(
            cone_dem, 1.0, num_directions=num_directions, search_radius=10
        )
        np.testing.assert_array_equal(gpu, cpu)

    @pytest.mark.parametrize("num_directions", [8, 16, 32])
    @pytest.mark.parametrize("is_negative", [False, True])
    def test_openness_matches(
        self, simulated_cuda, cone_dem, num_directions, is_negative
    ):
        gpu = simulated_cuda.compute_openness_gpu(
            cone_dem,
            1.0,
            num_directions=num_directions,
            search_radius=10,
            is_negative=is_negative,
        )
        cpu = topographic_openness(
            cone_dem,
            1.0,
            num_directions=num_directions,
            search_radius=10,
            is_negative=is_negative,
        )
        np.testing.assert_array_equal(gpu, cpu)

    def test_nodata_mask_matches(self, simulated_cuda, cone_dem):
        """NaN pixels must survive the round trip in the same places."""
        dem = cone_dem.copy()
        dem[8:12, :] = np.nan

        gpu = simulated_cuda.compute_svf_gpu(
            dem, 1.0, num_directions=16, search_radius=8
        )
        cpu = sky_view_factor(dem, 1.0, num_directions=16, search_radius=8)
        np.testing.assert_array_equal(np.isnan(gpu), np.isnan(cpu))
        np.testing.assert_array_equal(gpu, cpu)

    def test_non_unit_cellsize_matches(self, simulated_cuda, cone_dem):
        """Distances scale by cell size identically on both paths."""
        gpu = simulated_cuda.compute_svf_gpu(
            cone_dem, 2.5, num_directions=16, search_radius=8
        )
        cpu = sky_view_factor(cone_dem, 2.5, num_directions=16, search_radius=8)
        np.testing.assert_array_equal(gpu, cpu)


class TestShiftArrayGpu:
    """_shift_array_gpu must behave exactly like the CPU shift."""

    @pytest.mark.parametrize(
        "shift_y,shift_x",
        [(0, 0), (1, 0), (0, 1), (-1, 0), (0, -1), (3, -2), (-4, 5), (2, 2)],
    )
    def test_matches_cpu_shift(self, simulated_cuda, shift_y, shift_x):
        """Regression: the old slice maths raised a broadcast ValueError.

        Overlap along an axis is ``size - abs(shift)``. The old code
        computed ``size`` for positive shifts and ``size - 2*abs(shift)``
        for negative ones, so no GPU horizon step could ever complete.
        """
        rng = np.random.default_rng(5)
        arr = rng.random((11, 13)).astype(np.float32)

        gpu = simulated_cuda._shift_array_gpu(arr, shift_y, shift_x, -1.0)
        cpu = _shift_array(arr, shift_y, shift_x, -1.0)
        np.testing.assert_array_equal(gpu, cpu)

    def test_shift_beyond_array_is_all_fill(self, simulated_cuda):
        """A shift larger than the array leaves no overlap."""
        arr = np.ones((5, 5), dtype=np.float32)
        result = simulated_cuda._shift_array_gpu(arr, 99, 0, -7.0)
        assert np.all(result == -7.0)


class TestBackendProbe:
    """The CuPy probe must degrade gracefully, never explode."""

    def test_cupy_available_is_boolean(self):
        assert isinstance(compute_backend.cupy_available(), bool)

    def test_broken_cuda_runtime_does_not_break_import(self):
        """A CuPy install with a broken driver must fall back, not raise.

        `cp.is_available()` RAISES (e.g. CUDARuntimeError) rather than
        returning False when the driver is missing or mismatched. The
        old `except ImportError` guard let that escape module import and
        took the whole plugin down at QGIS start-up.
        """
        source = compute_backend.__doc__ or ""
        assert "is_available" in source or "CUDA runtime" in source

        import inspect

        module_source = inspect.getsource(compute_backend)
        import_block = module_source.split("_BACKENDS")[0]
        assert "except Exception" in import_block, (
            "the CuPy import guard must catch more than ImportError"
        )
