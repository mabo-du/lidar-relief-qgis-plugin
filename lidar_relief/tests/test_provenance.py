"""test_provenance.py — Tests for output provenance sidecars.

exports: (test functions)
used_by: pytest runner
rules:
  The load-bearing guarantee is that provenance NEVER costs the user a
  finished result — every failure path must degrade to "no sidecar",
  not to an exception. Test that as hard as the happy path.
"""

import json
import os

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import gdal, osr  # noqa: E402

from lidar_relief.provenance import (  # noqa: E402
    PROVENANCE_VERSION,
    SIDECAR_SUFFIX,
    build_record,
    describe_raster,
    file_checksum,
    read_sidecar,
    sidecar_path_for,
    verify_source,
    write_sidecar,
    write_sidecar_safe,
)

gdal.UseExceptions()


def _write_raster(path, size=32, epsg=27700, cellsize=1.0, seed=1):
    rng = np.random.default_rng(seed)
    arr = (rng.random((size, size)) * 10).astype(np.float32)
    ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((400000.0, cellsize, 0.0, 300000.0, 0.0, -cellsize))
    if epsg is not None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).SetNoDataValue(-9999.0)
    ds.GetRasterBand(1).WriteArray(arr)
    ds = None
    return path


@pytest.fixture
def source_dem(tmp_path):
    return _write_raster(str(tmp_path / "dem.tif"))


class TestSidecarPaths:
    def test_suffix_is_appended_not_substituted(self):
        """Keeps the sidecar beside its raster and collision-free."""
        assert sidecar_path_for("/data/svf.tif") == f"/data/svf.tif{SIDECAR_SUFFIX}"


class TestFileChecksum:
    def test_hashes_a_small_file_completely(self, source_dem):
        result = file_checksum(source_dem)
        assert result["algorithm"] == "sha256"
        assert len(result["value"]) == 64
        assert result["complete"] is True
        assert result["size_bytes"] > 0

    def test_bounded_read_is_marked_incomplete(self, source_dem):
        """A prefix hash must declare itself as such."""
        result = file_checksum(source_dem, max_bytes=128)
        assert result["bytes_hashed"] == 128
        assert result["complete"] is False

    def test_same_content_same_hash(self, tmp_path):
        a = _write_raster(str(tmp_path / "a.tif"), seed=7)
        b = _write_raster(str(tmp_path / "b.tif"), seed=7)
        assert file_checksum(a)["value"] == file_checksum(b)["value"]

    def test_different_content_different_hash(self, tmp_path):
        a = _write_raster(str(tmp_path / "a.tif"), seed=1)
        b = _write_raster(str(tmp_path / "b.tif"), seed=2)
        assert file_checksum(a)["value"] != file_checksum(b)["value"]

    def test_missing_file_returns_empty(self):
        assert file_checksum("/nonexistent/file.tif") == {}


class TestDescribeRaster:
    def test_captures_the_grid(self, source_dem):
        described = describe_raster(source_dem)
        assert described["width"] == 32
        assert described["height"] == 32
        assert described["cell_size_x"] == pytest.approx(1.0)
        assert described["crs_authority"] == "EPSG:27700"
        assert described["nodata"] == pytest.approx(-9999.0)

    def test_non_raster_returns_empty(self, tmp_path):
        text = tmp_path / "notes.txt"
        text.write_text("not a raster")
        assert describe_raster(str(text)) == {}


class TestBuildRecord:
    def test_contains_the_reproduction_essentials(self, source_dem, tmp_path):
        record = build_record(
            "sky_view_factor",
            {"search_radius_pixels": 20, "num_directions": 16},
            source_path=source_dem,
            output_path=str(tmp_path / "svf.tif"),
            algorithm_name="Sky-View Factor (SVF)",
        )

        assert record["provenance_version"] == PROVENANCE_VERSION
        assert record["algorithm"]["id"] == "sky_view_factor"
        assert record["algorithm"]["name"] == "Sky-View Factor (SVF)"
        assert record["parameters"]["search_radius_pixels"] == 20
        assert record["generator"]["version"]
        assert record["created_utc"]
        assert record["source"]["checksum"]["value"]
        assert record["source"]["raster"]["crs_authority"] == "EPSG:27700"

    def test_is_json_serialisable_with_awkward_values(self, tmp_path):
        """QGIS hands back enums and numpy scalars; none may break the write."""

        class Opaque:
            def __repr__(self):
                return "<Opaque>"

        record = build_record(
            "test",
            {
                "numpy_int": np.int32(7),
                "numpy_float": np.float32(1.5),
                "nested": {"list": [np.int64(1), "two"]},
                "opaque": Opaque(),
            },
            output_path=str(tmp_path / "out.tif"),
        )
        encoded = json.dumps(record)
        assert '"numpy_int": 7' in encoded
        assert "<Opaque>" in encoded

    def test_works_without_a_source(self, tmp_path):
        record = build_record("test", {}, output_path=str(tmp_path / "o.tif"))
        assert "source" not in record


class TestWriteAndRead:
    def test_round_trip(self, source_dem, tmp_path):
        output = str(tmp_path / "svf.tif")
        record = build_record("svf", {"radius": 10}, source_dem, output)
        path = write_sidecar(output, record)

        assert path.endswith(SIDECAR_SUFFIX)
        assert os.path.exists(path)
        assert read_sidecar(path)["parameters"]["radius"] == 10

    def test_read_accepts_the_output_path(self, source_dem, tmp_path):
        """Users select the raster, not the sidecar."""
        output = str(tmp_path / "svf.tif")
        write_sidecar(output, build_record("svf", {"radius": 4}, source_dem, output))
        assert read_sidecar(output)["parameters"]["radius"] == 4

    def test_missing_sidecar_raises_with_guidance(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No provenance sidecar"):
            read_sidecar(str(tmp_path / "absent.tif"))

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / f"x.tif{SIDECAR_SUFFIX}"
        bad.write_text("{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            read_sidecar(str(bad))

    def test_foreign_json_is_rejected(self, tmp_path):
        alien = tmp_path / f"x.tif{SIDECAR_SUFFIX}"
        alien.write_text(json.dumps({"something": "else"}))
        with pytest.raises(ValueError, match="not a LiDAR Relief provenance record"):
            read_sidecar(str(alien))


class TestWriteSidecarSafe:
    """Provenance must never destroy the result it describes."""

    def test_unwritable_location_returns_none(self, source_dem):
        record = build_record("svf", {}, source_dem, "/proc/cannot/write.tif")
        assert write_sidecar_safe("/proc/cannot/write.tif", record) is None

    def test_unserialisable_record_returns_none(self, tmp_path):
        """Even a record json cannot encode must not raise."""
        output = str(tmp_path / "o.tif")
        assert write_sidecar_safe(output, {"bad": {1, 2, 3}}) is None

    def test_reports_through_feedback(self, source_dem, tmp_path):
        class Feedback:
            def __init__(self):
                self.info = []

            def pushInfo(self, message):
                self.info.append(message)

        output = str(tmp_path / "o.tif")
        feedback = Feedback()
        write_sidecar_safe(
            output, build_record("svf", {}, source_dem, output), feedback
        )
        assert any("Provenance" in m for m in feedback.info)


class TestVerifySource:
    def test_unchanged_source_matches(self, source_dem, tmp_path):
        record = build_record("svf", {}, source_dem, str(tmp_path / "o.tif"))
        assert verify_source(record, source_dem) == []

    def test_modified_content_is_detected(self, source_dem, tmp_path):
        record = build_record("svf", {}, source_dem, str(tmp_path / "o.tif"))

        ds = gdal.Open(source_dem, gdal.GA_Update)
        arr = ds.GetRasterBand(1).ReadAsArray()
        arr[0, 0] += 100.0
        ds.GetRasterBand(1).WriteArray(arr)
        ds = None

        differences = verify_source(record, source_dem)
        assert differences, "an edited source must not verify clean"

    def test_different_raster_is_detected(self, source_dem, tmp_path):
        record = build_record("svf", {}, source_dem, str(tmp_path / "o.tif"))
        other = _write_raster(str(tmp_path / "other.tif"), size=64, seed=9)

        differences = verify_source(record, other)
        assert any("width" in d or "size" in d.lower() for d in differences)

    def test_crs_change_is_detected(self, source_dem, tmp_path):
        record = build_record("svf", {}, source_dem, str(tmp_path / "o.tif"))
        reprojected = _write_raster(str(tmp_path / "wgs.tif"), epsg=4326, seed=1)
        differences = verify_source(record, reprojected)
        assert any("CRS" in d for d in differences)

    def test_record_without_source_says_so(self, tmp_path):
        record = build_record("svf", {}, output_path=str(tmp_path / "o.tif"))
        assert verify_source(record, str(tmp_path / "o.tif")) == [
            "The record does not name a source raster."
        ]
