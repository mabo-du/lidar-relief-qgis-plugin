"""test_contact_sheet.py — Tests for the multi-panel comparison sheet.

exports: (test functions)
used_by: pytest runner
rules:
  The sheet is a preview, so these tests check structure and robustness
  rather than pixel values: correct mosaic geometry, independent panel
  stretching, graceful degradation when Pillow is missing, and that one
  failing visualisation does not cost the user the others.
"""

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import gdal, osr  # noqa: E402

from lidar_relief.core.raster_utils import read_dem_downsampled  # noqa: E402
from lidar_relief.export import contact_sheet as cs  # noqa: E402

gdal.UseExceptions()


@pytest.fixture
def small_dem():
    """Cone, pit and ridge — enough structure for every visualisation."""
    size = 60
    yy, xx = np.mgrid[0:size, 0:size]
    rng = np.random.default_rng(4)
    dem = (rng.random((size, size)) * 0.3).astype(np.float32)
    dem += np.maximum(0.0, 8.0 - np.sqrt((yy - 15) ** 2 + (xx - 15) ** 2)).astype(
        np.float32
    )
    dem -= np.maximum(0.0, 5.0 - np.sqrt((yy - 45) ** 2 + (xx - 45) ** 2)).astype(
        np.float32
    )
    dem[30, :] += 2.0
    return dem.astype(np.float32)


class TestVisualisationCatalogue:
    def test_names_are_unique_and_nonempty(self):
        names = cs.visualisation_names()
        assert names
        assert len(names) == len(set(names))

    def test_catalogue_entries_are_well_formed(self):
        for name, func, is_rgb in cs.VISUALISATIONS:
            assert isinstance(name, str) and name
            assert callable(func)
            assert isinstance(is_rgb, bool)


class TestComputePanels:
    def test_computes_requested_panels(self, small_dem):
        wanted = ["Sky-View Factor", "Slope (degrees)"]
        panels = cs.compute_panels(small_dem, 1.0, wanted)
        assert [label for label, _ in panels] == wanted
        for _label, array in panels:
            assert array.shape[:2] == small_dem.shape

    def test_preserves_requested_order(self, small_dem):
        """Panels must follow the user's selection order, not catalogue order."""
        wanted = ["Slope (degrees)", "Multi-directional Hillshade"]
        panels = cs.compute_panels(small_dem, 1.0, wanted)
        assert [label for label, _ in panels] == wanted

    def test_unknown_name_is_ignored(self, small_dem):
        panels = cs.compute_panels(small_dem, 1.0, ["Sky-View Factor", "Nonexistent"])
        assert [label for label, _ in panels] == ["Sky-View Factor"]

    def test_all_catalogue_entries_run(self, small_dem):
        """Every advertised visualisation must actually produce a panel.

        Guards against a catalogue entry whose signature drifts from the
        core function it wraps.
        """
        panels = cs.compute_panels(small_dem, 1.0, cs.visualisation_names())
        assert len(panels) == len(cs.VISUALISATIONS), (
            f"only {len(panels)} of {len(cs.VISUALISATIONS)} panels computed"
        )

    def test_one_failure_does_not_lose_the_sheet(self, small_dem, monkeypatch):
        """A broken visualisation is skipped, the rest still render."""

        def explode(dem, cellsize):
            raise RuntimeError("simulated optional-dependency failure")

        patched = [("Sky-View Factor", explode, False)] + [
            entry for entry in cs.VISUALISATIONS if entry[0] != "Sky-View Factor"
        ]
        monkeypatch.setattr(cs, "VISUALISATIONS", patched)

        panels = cs.compute_panels(
            small_dem, 1.0, ["Sky-View Factor", "Slope (degrees)"]
        )
        assert [label for label, _ in panels] == ["Slope (degrees)"]


class TestNormalisePanel:
    def test_greyscale_becomes_rgb_uint8(self, small_dem):
        out = cs.normalise_panel(small_dem)
        assert out.dtype == np.uint8
        assert out.shape == (*small_dem.shape, 3)

    def test_uses_full_range(self, small_dem):
        out = cs.normalise_panel(small_dem)
        assert out.min() < 40 and out.max() > 215, "stretch did not use the range"

    def test_constant_input_is_mid_grey(self):
        """A flat array must not divide by zero or come out black."""
        out = cs.normalise_panel(np.full((10, 10), 5.0, dtype=np.float32))
        assert out.dtype == np.uint8
        assert np.all(out == 127)

    def test_nan_does_not_poison_the_stretch(self, small_dem):
        dem = small_dem.copy()
        dem[0:5, :] = np.nan
        out = cs.normalise_panel(dem)
        assert np.isfinite(out).all()
        assert out.min() < 40 and out.max() > 215

    def test_all_nan_is_survivable(self):
        out = cs.normalise_panel(np.full((8, 8), np.nan, dtype=np.float32))
        assert out.shape == (8, 8, 3)
        assert out.dtype == np.uint8

    def test_uint8_rgb_passes_through(self):
        rgb = np.zeros((6, 6, 3), dtype=np.uint8)
        rgb[..., 0] = 200
        np.testing.assert_array_equal(cs.normalise_panel(rgb), rgb)


class TestBuildContactSheet:
    def test_geometry_matches_grid(self, small_dem):
        panels = cs.compute_panels(
            small_dem, 1.0, ["Sky-View Factor", "Slope (degrees)"]
        )
        sheet = cs.build_contact_sheet(panels, columns=2, gutter=4, label_height=0)

        rows, cols = small_dem.shape
        assert sheet.shape == (rows + 2 * 4, 2 * cols + 3 * 4, 3)
        assert sheet.dtype == np.uint8

    def test_wraps_onto_multiple_rows(self, small_dem):
        panels = cs.compute_panels(
            small_dem,
            1.0,
            ["Sky-View Factor", "Slope (degrees)", "Positive Openness"],
        )
        sheet = cs.build_contact_sheet(panels, columns=2, gutter=4, label_height=0)
        rows = small_dem.shape[0]
        assert sheet.shape[0] == 2 * rows + 3 * 4, "three panels need two rows"

    def test_label_strip_adds_height(self, small_dem):
        panels = cs.compute_panels(small_dem, 1.0, ["Slope (degrees)"])
        bare = cs.build_contact_sheet(panels, columns=1, gutter=0, label_height=0)
        labelled = cs.build_contact_sheet(panels, columns=1, gutter=0, label_height=20)
        assert labelled.shape[0] == bare.shape[0] + 20

    def test_empty_panels_rejected(self):
        with pytest.raises(ValueError, match="at least one visualisation"):
            cs.build_contact_sheet([])

    def test_mismatched_shapes_rejected(self):
        panels = [
            ("a", np.zeros((10, 10), dtype=np.float32)),
            ("b", np.zeros((12, 10), dtype=np.float32)),
        ]
        with pytest.raises(ValueError, match="inconsistent shapes"):
            cs.build_contact_sheet(panels)

    def test_rgb_panel_mixes_with_greyscale(self, small_dem):
        """MSTP returns RGB; it must tile alongside greyscale panels."""
        panels = cs.compute_panels(small_dem, 1.0, ["Slope (degrees)", "MSTP (RGB)"])
        assert len(panels) == 2
        sheet = cs.build_contact_sheet(panels, columns=2, label_height=0)
        assert sheet.shape[2] == 3


class TestWritePng:
    def test_writes_a_readable_png(self, small_dem, tmp_path):
        panels = cs.compute_panels(small_dem, 1.0, ["Slope (degrees)"])
        sheet = cs.build_contact_sheet(panels, columns=1)
        out = str(tmp_path / "sheet.png")
        cs.write_png(sheet, out)

        ds = gdal.Open(out)
        assert ds is not None
        assert ds.RasterCount == 3
        assert (ds.RasterYSize, ds.RasterXSize) == sheet.shape[:2]
        ds = None

    def test_rejects_non_rgb(self, tmp_path):
        with pytest.raises(ValueError, match="RGB array"):
            cs.write_png(np.zeros((5, 5), dtype=np.uint8), str(tmp_path / "x.png"))


class TestDownsampledRead:
    """The preview read that keeps the sheet fast."""

    def _write(self, path, size=400, cellsize=0.5):
        rng = np.random.default_rng(2)
        arr = (rng.random((size, size)) * 10).astype(np.float32)
        ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((400000.0, cellsize, 0.0, 300000.0, 0.0, -cellsize))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(27700)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).SetNoDataValue(-9999.0)
        ds.GetRasterBand(1).WriteArray(arr)
        ds = None
        return path

    def test_respects_max_dimension(self, tmp_path):
        src = self._write(str(tmp_path / "big.tif"), size=400)
        array, _cellsize = read_dem_downsampled(src, max_dimension=100)
        assert max(array.shape) <= 100

    def test_cellsize_is_scaled_with_the_grid(self, tmp_path):
        """The returned cell size must describe the DECIMATED grid.

        Otherwise every distance-based panel silently uses the wrong
        scale — a 10 px radius would mean a different real distance than
        the caller intends.
        """
        src = self._write(str(tmp_path / "big.tif"), size=400, cellsize=0.5)
        array, cellsize = read_dem_downsampled(src, max_dimension=100)
        assert cellsize == pytest.approx(0.5 * 400 / array.shape[1], rel=1e-6)

    def test_small_raster_is_not_upsampled(self, tmp_path):
        src = self._write(str(tmp_path / "small.tif"), size=50, cellsize=1.0)
        array, cellsize = read_dem_downsampled(src, max_dimension=800)
        assert array.shape == (50, 50)
        assert cellsize == pytest.approx(1.0)

    def test_nodata_becomes_nan(self, tmp_path):
        src = str(tmp_path / "nod.tif")
        ds = gdal.GetDriverByName("GTiff").Create(src, 40, 40, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
        arr = np.ones((40, 40), dtype=np.float32)
        arr[0:5, :] = -9999.0
        ds.GetRasterBand(1).SetNoDataValue(-9999.0)
        ds.GetRasterBand(1).WriteArray(arr)
        ds = None

        array, _ = read_dem_downsampled(src, max_dimension=800)
        assert np.isnan(array[0:5, :]).all()
        assert np.isfinite(array[10:, :]).all()

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="Cannot open raster"):
            read_dem_downsampled("/nonexistent/dem.tif")
