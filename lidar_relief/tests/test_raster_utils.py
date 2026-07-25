"""test_raster_utils.py — Tests for tiled raster I/O and DEM validation.

exports: (test functions)
used_by: pytest runner
rules:
  Covers two things nothing else did: the nodata contract of
  process_in_tiles (it used to write bare NaN into an untagged float
  band whenever the SOURCE raster declared no nodata) and
  check_dem_geometry, which warns about geographic CRS and non-square
  pixels before an algorithm burns minutes on a meaningless result.
"""

import os

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import gdal, osr  # noqa: E402

from lidar_relief.core.raster_utils import (  # noqa: E402
    DEFAULT_TILE_WORKERS,
    FALLBACK_NODATA,
    check_dem_geometry,
    process_in_tiles,
    resolve_worker_count,
)
from lidar_relief.core.slrm import simple_local_relief_model  # noqa: E402

gdal.UseExceptions()


class _RecordingFeedback:
    """Minimal stand-in for QgsProcessingFeedback."""

    def __init__(self):
        self.warnings = []
        self.info = []

    def pushWarning(self, message):
        self.warnings.append(message)

    def pushInfo(self, message):
        self.info.append(message)

    def setProgressText(self, message):
        self.info.append(message)

    def setProgress(self, value):
        pass

    def isCanceled(self):
        return False


def _write_dem(path, epsg=27700, nodata=None, pixel=(1.0, -1.0), nan_patch=False):
    """Write a small synthetic DEM with controllable georeferencing."""
    size = 40
    yy, xx = np.mgrid[0:size, 0:size]
    arr = (100.0 + 0.1 * xx + 0.05 * yy).astype(np.float32)
    if nan_patch:
        arr[5:9, 5:9] = np.nan

    ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((400000.0, pixel[0], 0.0, 300000.0, 0.0, pixel[1]))
    if epsg is not None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    ds.GetRasterBand(1).WriteArray(arr)
    ds = None
    return path


def _slrm(dem, cellsize, **kwargs):
    return simple_local_relief_model(dem, radius=4)


class TestProcessInTilesNodata:
    """The output band must always declare a nodata value."""

    def test_source_without_nodata_still_tags_output(self, tmp_path):
        """Regression: NaN was written into an untagged float band.

        QGIS then folds NaN into layer statistics and the contrast
        stretch collapses, so the layer renders flat grey.
        """
        src = _write_dem(str(tmp_path / "src.tif"), nodata=None, nan_patch=True)
        out = str(tmp_path / "out.tif")

        process_in_tiles(src, out, _slrm, halo_size=4, tile_size=16)

        ds = gdal.Open(out)
        band = ds.GetRasterBand(1)
        assert band.GetNoDataValue() == pytest.approx(FALLBACK_NODATA)

        arr = band.ReadAsArray()
        assert not np.isnan(arr).any(), (
            "raw NaN must not reach the file when the band advertises a "
            "numeric nodata value"
        )
        ds = None

    def test_source_nodata_is_preserved(self, tmp_path):
        """An explicit source nodata must carry through unchanged."""
        src = _write_dem(str(tmp_path / "src.tif"), nodata=-32768.0, nan_patch=True)
        out = str(tmp_path / "out.tif")

        process_in_tiles(src, out, _slrm, halo_size=4, tile_size=16)

        ds = gdal.Open(out)
        assert ds.GetRasterBand(1).GetNoDataValue() == pytest.approx(-32768.0)
        ds = None

    def test_output_is_finite_everywhere(self, tmp_path):
        """No NaN should survive into any tile, including edge tiles."""
        src = _write_dem(str(tmp_path / "src.tif"), nodata=None, nan_patch=True)
        out = str(tmp_path / "out.tif")

        # tile_size smaller than the raster forces multiple tiles + halos.
        process_in_tiles(src, out, _slrm, halo_size=4, tile_size=13)

        ds = gdal.Open(out)
        arr = ds.GetRasterBand(1).ReadAsArray()
        assert np.isfinite(arr).all()
        ds = None


class TestTileParallelism:
    """Concurrency must change speed, never results."""

    @pytest.mark.parametrize("workers", [1, 2, 4, 8])
    def test_output_is_identical_regardless_of_workers(self, workers, tmp_path):
        """The whole safety argument: parallel output == serial output.

        Tiles are independent by construction (each carries its own halo),
        so any divergence means the batching or crop maths is wrong.
        """
        src = _write_dem(str(tmp_path / "src.tif"), nodata=None, nan_patch=True)

        serial = str(tmp_path / "serial.tif")
        process_in_tiles(src, serial, _slrm, halo_size=4, tile_size=13, max_workers=1)

        parallel = str(tmp_path / f"p{workers}.tif")
        process_in_tiles(
            src, parallel, _slrm, halo_size=4, tile_size=13, max_workers=workers
        )

        ds_a = gdal.Open(serial)
        ds_b = gdal.Open(parallel)
        np.testing.assert_array_equal(
            ds_a.GetRasterBand(1).ReadAsArray(),
            ds_b.GetRasterBand(1).ReadAsArray(),
        )
        ds_a = None
        ds_b = None

    def test_more_workers_than_tiles_is_safe(self, tmp_path):
        """A small raster has fewer tiles than workers — must not hang."""
        src = _write_dem(str(tmp_path / "src.tif"))
        out = str(tmp_path / "out.tif")
        process_in_tiles(src, out, _slrm, halo_size=2, tile_size=2048, max_workers=8)

        ds = gdal.Open(out)
        assert ds is not None
        assert ds.RasterXSize == 40
        ds = None

    def test_progress_reaches_100(self, tmp_path):
        """Batching must not lose the final progress update."""

        class ProgressFeedback(_RecordingFeedback):
            def __init__(self):
                super().__init__()
                self.progress = []

            def setProgress(self, value):
                self.progress.append(value)

        src = _write_dem(str(tmp_path / "src.tif"))
        feedback = ProgressFeedback()
        process_in_tiles(
            src,
            str(tmp_path / "out.tif"),
            _slrm,
            halo_size=2,
            tile_size=13,
            feedback=feedback,
            max_workers=3,
        )
        assert feedback.progress, "no progress was reported"
        assert feedback.progress[-1] == 100
        assert feedback.progress == sorted(feedback.progress), "progress went backwards"

    def test_cancellation_removes_partial_output(self, tmp_path):
        """Cancelling must not leave a half-written raster on disk."""

        class CancelledFeedback(_RecordingFeedback):
            def isCanceled(self):
                return True

        src = _write_dem(str(tmp_path / "src.tif"))
        out = str(tmp_path / "cancelled.tif")
        process_in_tiles(
            src,
            out,
            _slrm,
            halo_size=2,
            tile_size=13,
            feedback=CancelledFeedback(),
            max_workers=4,
        )
        assert not os.path.exists(out), "cancelled run left a partial raster behind"

    def test_closures_are_supported(self, tmp_path):
        """Several Processing wrappers pass local closures.

        This is why the pool uses threads: a closure cannot be pickled,
        so a ProcessPoolExecutor would raise here.
        """
        radius = 3

        def local_wrapper(block, cellsize, **kwargs):
            return simple_local_relief_model(block, radius)

        src = _write_dem(str(tmp_path / "src.tif"))
        out = str(tmp_path / "out.tif")
        process_in_tiles(
            src, out, local_wrapper, halo_size=3, tile_size=13, max_workers=4
        )
        assert gdal.Open(out) is not None

    def test_multiband_output_is_identical(self, tmp_path):
        """RGB composites take the 3-band path through the crop logic."""

        def rgb(block, cellsize, **kwargs):
            base = simple_local_relief_model(block, 3)
            scaled = np.clip((base + 1) * 100, 0, 255).astype(np.uint8)
            return np.dstack([scaled, scaled, scaled])

        src = _write_dem(str(tmp_path / "src.tif"))
        serial = str(tmp_path / "s.tif")
        parallel = str(tmp_path / "p.tif")
        process_in_tiles(src, serial, rgb, halo_size=3, tile_size=13, max_workers=1)
        process_in_tiles(src, parallel, rgb, halo_size=3, tile_size=13, max_workers=4)

        ds_a = gdal.Open(serial)
        ds_b = gdal.Open(parallel)
        assert ds_a.RasterCount == 3
        for b in range(1, 4):
            np.testing.assert_array_equal(
                ds_a.GetRasterBand(b).ReadAsArray(),
                ds_b.GetRasterBand(b).ReadAsArray(),
            )
        ds_a = None
        ds_b = None


class TestResolveWorkerCount:
    """Worker-count policy."""

    def test_explicit_value_wins(self):
        assert resolve_worker_count(3) == 3

    def test_none_uses_bounded_default(self):
        workers = resolve_worker_count(None)
        assert 1 <= workers <= DEFAULT_TILE_WORKERS

    @pytest.mark.parametrize("value", [0, -1, 1])
    def test_never_below_one(self, value):
        assert resolve_worker_count(value) == 1


class TestCheckDemGeometry:
    """Warnings for DEMs that will silently produce meaningless output."""

    def test_projected_square_dem_is_clean(self, tmp_path):
        """A well-formed DEM must produce no warnings at all."""
        src = _write_dem(str(tmp_path / "ok.tif"), epsg=27700)
        ds = gdal.Open(src)
        assert check_dem_geometry(ds) == []
        ds = None

    def test_geographic_crs_warns(self, tmp_path):
        """A lat/lon DEM gives cell sizes in degrees — the classic trap."""
        src = _write_dem(str(tmp_path / "wgs84.tif"), epsg=4326)
        ds = gdal.Open(src)
        feedback = _RecordingFeedback()
        warnings = check_dem_geometry(ds, feedback)
        ds = None

        assert any("geographic CRS" in w for w in warnings)
        assert any("degrees" in w for w in warnings)
        assert feedback.warnings, "the warning must reach the QGIS log"

    def test_missing_crs_warns(self, tmp_path):
        """A CRS-less DEM cannot be aligned with anything."""
        src = _write_dem(str(tmp_path / "nocrs.tif"), epsg=None)
        ds = gdal.Open(src)
        warnings = check_dem_geometry(ds)
        ds = None
        assert any("no coordinate reference system" in w for w in warnings)

    def test_non_square_pixels_warn(self, tmp_path):
        """Anisotropic pixels bias every distance-based algorithm."""
        src = _write_dem(str(tmp_path / "aniso.tif"), pixel=(1.0, -2.5))
        ds = gdal.Open(src)
        warnings = check_dem_geometry(ds)
        ds = None
        assert any("non-square pixels" in w for w in warnings)

    def test_tiny_pixel_difference_is_tolerated(self, tmp_path):
        """Sub-1% float drift in the geotransform must not cry wolf."""
        src = _write_dem(str(tmp_path / "close.tif"), pixel=(1.0, -1.000001))
        ds = gdal.Open(src)
        warnings = check_dem_geometry(ds)
        ds = None
        assert not any("non-square" in w for w in warnings)

    def test_feedback_is_optional(self, tmp_path):
        """check_dem_geometry must work with no feedback object."""
        src = _write_dem(str(tmp_path / "wgs84.tif"), epsg=4326)
        ds = gdal.Open(src)
        assert check_dem_geometry(ds, None)
        ds = None

    def test_warnings_surface_through_process_in_tiles(self, tmp_path):
        """The guard must fire for every algorithm that tiles, not just direct calls."""
        src = _write_dem(str(tmp_path / "wgs84.tif"), epsg=4326)
        out = str(tmp_path / "out.tif")
        feedback = _RecordingFeedback()

        process_in_tiles(src, out, _slrm, halo_size=4, tile_size=16, feedback=feedback)

        assert any("geographic CRS" in w for w in feedback.warnings)

    def test_repeat_warnings_are_suppressed(self, tmp_path):
        """Batch Relief tiles a dozen times — say it once, not twelve times."""
        src = _write_dem(str(tmp_path / "wgs84.tif"), epsg=4326)
        feedback = _RecordingFeedback()

        for i in range(5):
            process_in_tiles(
                src,
                str(tmp_path / f"out{i}.tif"),
                _slrm,
                halo_size=4,
                tile_size=16,
                feedback=feedback,
            )

        geographic = [w for w in feedback.warnings if "geographic CRS" in w]
        assert len(geographic) == 1, (
            f"expected the CRS warning once per run, got {len(geographic)}"
        )

    def test_distinct_warnings_are_all_reported(self, tmp_path):
        """Deduplication must not swallow a second, different problem."""
        src = _write_dem(str(tmp_path / "bad.tif"), epsg=4326, pixel=(1.0, -3.0))
        feedback = _RecordingFeedback()

        process_in_tiles(
            src,
            str(tmp_path / "out.tif"),
            _slrm,
            halo_size=4,
            tile_size=16,
            feedback=feedback,
        )

        assert any("geographic CRS" in w for w in feedback.warnings)
        assert any("non-square pixels" in w for w in feedback.warnings)
