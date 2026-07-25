"""test_csf_dem_export.py — Tests for the CSF LAS→DEM rasterisation path.

exports: (test functions)
used_by: pytest runner
rules:
  Covers point_cloud/csf_filter._points_to_dem, the tail of the
  CsfAlgorithm pipeline. Before v2.0.23 nothing exercised it and it
  raised TypeError on every call (zfield was passed as a column index
  instead of a field name, and gdal.Grid was handed a .xyz text file
  that OGR cannot open as a vector datasource).
  These tests need GDAL but NOT the CSF native library — the filtering
  step is covered separately in test_csf_filter.py.
"""

import os

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import gdal  # noqa: E402

from lidar_relief.point_cloud.csf_filter import (  # noqa: E402
    DEM_NODATA,
    MAX_DEM_DIMENSION,
    _points_to_dem,
    _write_points_vrt,
)

gdal.UseExceptions()


@pytest.fixture
def ground_points():
    """Ground points: gentle east-facing slope plus a 1 m mound.

    The mound sits at map coordinate (10, 10) so tests can assert it
    survives interpolation — a DEM that rasterises but loses the relief
    is just as broken as one that crashes.
    """
    rng = np.random.default_rng(7)
    n = 4000
    x = rng.uniform(0, 30, n)
    y = rng.uniform(0, 30, n)
    z = 100.0 + 0.05 * x + 1.0 * np.exp(-((x - 10) ** 2 + (y - 10) ** 2) / 8.0)
    return np.column_stack([x, y, z])


class TestPointsToDem:
    """Tests for rasterising ground points into a DEM."""

    def test_produces_readable_dem(self, ground_points, tmp_path):
        """The happy path must produce an openable, georeferenced raster."""
        out = str(tmp_path / "dem.tif")
        result = _points_to_dem(ground_points, out, cellsize=1.0, crs="EPSG:27700")

        assert result == out
        assert os.path.exists(out)

        ds = gdal.Open(out)
        assert ds is not None, "gdal.Grid produced an unreadable raster"
        assert ds.RasterXSize > 1 and ds.RasterYSize > 1
        assert ds.GetProjection(), "output DEM must carry the requested CRS"
        ds = None

    def test_nodata_is_tagged(self, ground_points, tmp_path):
        """Unreached cells must be tagged, not left as raw sentinel values."""
        out = str(tmp_path / "dem.tif")
        _points_to_dem(ground_points, out, cellsize=1.0, crs="EPSG:27700")

        ds = gdal.Open(out)
        assert ds.GetRasterBand(1).GetNoDataValue() == pytest.approx(DEM_NODATA)
        ds = None

    def test_elevations_are_preserved(self, ground_points, tmp_path):
        """Interpolated elevations must track the source point cloud.

        A silent failure mode of the old global-IDW settings was
        smearing every cell toward the cloud-wide mean.
        """
        out = str(tmp_path / "dem.tif")
        _points_to_dem(ground_points, out, cellsize=1.0, crs="EPSG:27700")

        ds = gdal.Open(out)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        gt = ds.GetGeoTransform()
        valid = arr[arr != DEM_NODATA]

        source_min = ground_points[:, 2].min()
        source_max = ground_points[:, 2].max()
        assert valid.size > 0
        # IDW cannot exceed the input range.
        assert valid.min() >= source_min - 0.01
        assert valid.max() <= source_max + 0.01

        # The mound at (10, 10) must still stand above the mean surface.
        col = int((10.0 - gt[0]) / gt[1])
        row = int((10.0 - gt[3]) / gt[5])
        assert arr[row, col] > valid.mean(), "mound was flattened by interpolation"
        ds = None

    def test_rejects_missing_crs(self, ground_points, tmp_path):
        """A CRS-less DEM would be silently misaligned — refuse to write it."""
        with pytest.raises(ValueError, match="requires an explicit CRS"):
            _points_to_dem(ground_points, str(tmp_path / "d.tif"), crs=None)

    def test_rejects_empty_point_array(self, tmp_path):
        """An empty cloud must fail loudly, not produce a blank raster."""
        with pytest.raises(ValueError, match="empty point array"):
            _points_to_dem(np.empty((0, 3)), str(tmp_path / "d.tif"), crs="EPSG:27700")

    def test_rejects_wrong_shape(self, tmp_path):
        """Guard the (N, 3) contract."""
        with pytest.raises(ValueError, match="Expected"):
            _points_to_dem(np.zeros((10, 2)), str(tmp_path / "d.tif"), crs="EPSG:27700")

    def test_rejects_nonpositive_cellsize(self, ground_points, tmp_path):
        """A zero cell size would divide by zero computing the grid size."""
        with pytest.raises(ValueError, match="cellsize must be positive"):
            _points_to_dem(
                ground_points, str(tmp_path / "d.tif"), cellsize=0.0, crs="EPSG:27700"
            )

    def test_caps_absurd_grid_size(self, ground_points, tmp_path):
        """A tiny cell size over a wide extent must not allocate gigabytes."""
        with pytest.raises(ValueError, match=str(MAX_DEM_DIMENSION)):
            _points_to_dem(
                ground_points,
                str(tmp_path / "d.tif"),
                cellsize=0.0005,
                crs="EPSG:27700",
            )

    def test_search_radius_leaves_gaps_as_nodata(self, tmp_path):
        """Cells beyond the search radius must be nodata, not extrapolated.

        Two point clusters with empty space between them: the gap should
        read nodata rather than being bridged by a smeared interpolation.
        """
        rng = np.random.default_rng(3)
        left = np.column_stack(
            [rng.uniform(0, 5, 400), rng.uniform(0, 30, 400), np.full(400, 100.0)]
        )
        right = np.column_stack(
            [rng.uniform(45, 50, 400), rng.uniform(0, 30, 400), np.full(400, 120.0)]
        )
        pts = np.vstack([left, right])

        out = str(tmp_path / "gap.tif")
        _points_to_dem(pts, out, cellsize=1.0, crs="EPSG:27700", search_radius=3.0)

        ds = gdal.Open(out)
        arr = ds.GetRasterBand(1).ReadAsArray()
        assert (arr == DEM_NODATA).any(), (
            "the empty corridor between clusters should be nodata, not "
            "interpolated across"
        )
        ds = None


class TestPointsVrt:
    """Tests for the CSV+VRT wrapper that makes points readable by OGR."""

    def test_vrt_is_readable_by_ogr(self, ground_points, tmp_path):
        """gdal.Grid needs an OGR vector source — assert we produce one.

        This is the regression guard for the original defect: a bare
        .xyz file fails with "not recognized as being in a supported
        file format".
        """
        ogr = pytest.importorskip("osgeo.ogr")

        vrt_path = _write_points_vrt(ground_points, str(tmp_path))
        assert os.path.exists(vrt_path)

        ds = ogr.Open(vrt_path)
        assert ds is not None, "VRT is not a readable OGR datasource"

        layer = ds.GetLayer(0)
        assert layer.GetFeatureCount() == len(ground_points)

        defn = layer.GetLayerDefn()
        field_names = {
            defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())
        }
        assert "z" in field_names, (
            "the z field name must exist — gdal.GridOptions(zfield=...) "
            "takes a field NAME, and passing an index raises TypeError"
        )
        ds = None
