"""test_csf_integration.py — End-to-end LAS → CSF → DEM pipeline test.

exports: (test functions)
used_by: pytest runner
rules:
  Exercises filter_las_file, the function CsfAlgorithm.processAlgorithm
  actually calls. Everything below it (reading LAS, cloth filtering,
  rasterising) was previously covered only in pieces, and the
  rasterising step was never covered at all — it raised TypeError on
  every real run from 2.0 through 2.0.22.
  Needs laspy (writes the fixture), CSF (filters), and GDAL (rasterises);
  skips cleanly when any is absent.
  Keep the synthetic cloud small — CSF is a physical simulation and this
  runs on every commit.
"""

import numpy as np
import pytest

pytest.importorskip("laspy")
pytest.importorskip("CSF")
pytest.importorskip("osgeo")

import laspy  # noqa: E402
from osgeo import gdal, osr  # noqa: E402

from lidar_relief.point_cloud.csf_filter import (  # noqa: E402
    DEM_NODATA,
    filter_las_file,
)

gdal.UseExceptions()


def _write_las(path, xyz, epsg=27700):
    """Write an (N, 3) array to a LAS file carrying a real CRS."""
    header = laspy.LasHeader(point_format=3, version="1.4")
    header.offsets = xyz.min(axis=0)
    header.scales = np.array([0.001, 0.001, 0.001])

    if epsg is not None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        header.add_crs(_pyproj_crs(srs))

    las = laspy.LasData(header)
    las.x = xyz[:, 0]
    las.y = xyz[:, 1]
    las.z = xyz[:, 2]
    las.write(str(path))
    return str(path)


def _pyproj_crs(srs):
    """Convert an osr SpatialReference into the pyproj CRS laspy wants."""
    from pyproj import CRS

    return CRS.from_wkt(srs.ExportToWkt())


@pytest.fixture
def wooded_site_cloud():
    """Bare ground with a mound, plus a canopy of vegetation returns.

    Mirrors the archaeological case the presets are tuned for: CSF should
    keep the mound (ground) and discard the canopy (off-ground).
    """
    rng = np.random.default_rng(19)

    # Kept deliberately small: CSF is an iterative cloth simulation and
    # this fixture is rebuilt for every test in the class.
    n_ground = 2500
    gx = rng.uniform(0, 40, n_ground)
    gy = rng.uniform(0, 40, n_ground)
    # Gentle slope + a 1.5 m mound centred on (20, 20)
    gz = (
        50.0
        + 0.02 * gx
        + 1.5 * np.exp(-((gx - 20) ** 2 + (gy - 20) ** 2) / 20.0)
        + rng.normal(0, 0.02, n_ground)
    )

    # Canopy: well above ground, so any sane filter rejects it.
    n_veg = 600
    vx = rng.uniform(0, 40, n_veg)
    vy = rng.uniform(0, 40, n_veg)
    vz = 50.0 + 0.02 * vx + rng.uniform(4.0, 9.0, n_veg)

    ground = np.column_stack([gx, gy, gz])
    veg = np.column_stack([vx, vy, vz])
    return np.vstack([ground, veg]), ground


class TestFilterLasFile:
    """The full LAS → ground filter → DEM path."""

    def test_produces_a_dem(self, wooded_site_cloud, tmp_path):
        """The headline regression: this raised TypeError on every run."""
        cloud, _ground = wooded_site_cloud
        las_path = _write_las(tmp_path / "site.las", cloud)
        out = str(tmp_path / "site_dem.tif")

        result = filter_las_file(
            las_path=las_path,
            output_dem_path=out,
            preset="archaeology_standard",
            cellsize=1.0,
        )

        ds = gdal.Open(result["dem_path"])
        assert ds is not None, "pipeline reported success but wrote no readable DEM"
        assert ds.RasterXSize > 10 and ds.RasterYSize > 10
        assert ds.GetProjection(), "DEM must carry the CRS read from the LAS header"
        ds = None

    def test_reports_consistent_statistics(self, wooded_site_cloud, tmp_path):
        """Every point must land in exactly one of the two classes."""
        cloud, _ground = wooded_site_cloud
        las_path = _write_las(tmp_path / "site.las", cloud)

        result = filter_las_file(
            las_path=las_path,
            output_dem_path=str(tmp_path / "dem.tif"),
            preset="archaeology_standard",
            cellsize=1.0,
        )

        assert result["total_points"] == len(cloud)
        assert result["ground_points"] + result["offground_points"] == len(cloud)
        assert result["ground_points"] > 0
        assert result["preset"] == "archaeology_standard"

    def test_crs_is_read_from_las_header(self, wooded_site_cloud, tmp_path):
        """No explicit CRS passed — it must come from the file, not a default.

        Earlier versions silently assumed EPSG:4326, which put projected
        point clouds hundreds of kilometres from where they belonged.
        """
        cloud, _ground = wooded_site_cloud
        las_path = _write_las(tmp_path / "site.las", cloud, epsg=27700)

        result = filter_las_file(
            las_path=las_path,
            output_dem_path=str(tmp_path / "dem.tif"),
            cellsize=1.0,
        )

        ds = gdal.Open(result["dem_path"])
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        assert srs.GetAuthorityCode(None) == "27700", (
            f"expected EPSG:27700 from the LAS header, got {srs.GetAuthorityCode(None)}"
        )
        ds = None

    def test_vegetation_is_removed_from_the_surface(self, wooded_site_cloud, tmp_path):
        """The DEM must describe the ground, not the canopy.

        Canopy returns sit 4-9 m above ground; if they leaked into the
        raster the surface would be metres too high.
        """
        cloud, ground = wooded_site_cloud
        las_path = _write_las(tmp_path / "site.las", cloud)

        result = filter_las_file(
            las_path=las_path,
            output_dem_path=str(tmp_path / "dem.tif"),
            preset="archaeology_standard",
            cellsize=1.0,
        )

        ds = gdal.Open(result["dem_path"])
        arr = ds.GetRasterBand(1).ReadAsArray()
        ds = None

        valid = arr[arr != DEM_NODATA]
        ground_max = ground[:, 2].max()
        assert valid.max() < ground_max + 1.0, (
            f"DEM peaks at {valid.max():.2f} but bare ground tops out at "
            f"{ground_max:.2f} — canopy returns leaked into the surface"
        )

    def test_mound_survives_filtering(self, wooded_site_cloud, tmp_path):
        """The archaeological point: subtle earthworks must not be filtered out."""
        cloud, _ground = wooded_site_cloud
        las_path = _write_las(tmp_path / "site.las", cloud)

        result = filter_las_file(
            las_path=las_path,
            output_dem_path=str(tmp_path / "dem.tif"),
            preset="archaeology_fine",
            cellsize=1.0,
        )

        ds = gdal.Open(result["dem_path"])
        arr = ds.GetRasterBand(1).ReadAsArray()
        gt = ds.GetGeoTransform()
        ds = None

        valid = arr[arr != DEM_NODATA]
        col = int((20.0 - gt[0]) / gt[1])
        row = int((20.0 - gt[3]) / gt[5])
        assert arr[row, col] > valid.mean(), (
            "the 1.5 m mound was flattened — the fine preset is supposed to "
            "preserve micro-relief"
        )

    def test_unknown_preset_falls_back(self, wooded_site_cloud, tmp_path):
        """An unrecognised preset must warn and continue, not crash."""
        cloud, _ground = wooded_site_cloud
        las_path = _write_las(tmp_path / "site.las", cloud)

        result = filter_las_file(
            las_path=las_path,
            output_dem_path=str(tmp_path / "dem.tif"),
            preset="not_a_real_preset",
            cellsize=1.0,
        )
        assert result["ground_points"] > 0
