"""test_ml_segmentation.py — Tests for semantic segmentation support.

exports: (test functions)
used_by: pytest runner
rules:
  Through v2.0.22 SUPPORTED_MODEL_TYPES had one entry and U-Net models
  were detected then silently dropped, so the whole path is new and
  needs coverage at every stage: model-type inference, logit
  postprocessing, tile compositing, raster export and vectorisation.
  Where onnx is available these tests build a REAL tiny segmentation
  model rather than mocking the session, so the ONNX plumbing is
  genuinely exercised.
"""

import numpy as np
import pytest

pytest.importorskip("osgeo")

from osgeo import gdal, ogr, osr  # noqa: E402

from lidar_relief.ml.detector import (  # noqa: E402
    SEGMENTATION_BACKGROUND_CLASS,
    SUPPORTED_MODEL_TYPES,
    detect_model_type,
    postprocess_segmentation,
)
from lidar_relief.ml.segmentation_export import (  # noqa: E402
    LABEL_NODATA,
    polygonise_labels,
    write_label_raster,
)

gdal.UseExceptions()

_GT = (400000.0, 1.0, 0.0, 300000.0, 0.0, -1.0)


def _wkt(epsg=27700):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    return srs.ExportToWkt()


@pytest.fixture
def label_map():
    """40x40 map: background, one square of class 1, one blob of class 2."""
    labels = np.zeros((40, 40), dtype=np.uint8)
    labels[5:15, 5:15] = 1
    labels[25:33, 22:30] = 2
    labels[38, 38] = 1  # single-pixel speckle, should be filtered out
    return labels


class TestModelTypeDetection:
    """Inferring what kind of head a model has."""

    def test_four_dim_single_output_is_segmentation(self):
        assert (
            detect_model_type(["output"], [[1, 3, 256, 256]]) == "semantic_segmentation"
        )

    def test_dynamic_axes_still_read_as_segmentation(self):
        assert (
            detect_model_type(["output"], [["batch", 2, "height", "width"]])
            == "semantic_segmentation"
        )

    def test_named_label_map_is_segmentation(self):
        assert detect_model_type(["label_map"], None) == "semantic_segmentation"

    def test_three_dim_single_output_is_detection(self):
        """YOLOv8 emits (1, N, 6)."""
        assert detect_model_type(["output0"], [[1, 8400, 6]]) == "object_detection"

    def test_multi_output_is_detection(self):
        names = ["num_dets", "det_boxes", "det_scores", "det_classes"]
        assert detect_model_type(names, [[1], [1, 100, 4], [1, 100], [1, 100]]) == (
            "object_detection"
        )

    def test_unknown_shapes_default_to_detection(self):
        assert detect_model_type(["output"], None) == "object_detection"

    def test_segmentation_is_a_supported_type(self):
        """Regression: this key was absent, so U-Nets returned nothing."""
        assert "semantic_segmentation" in SUPPORTED_MODEL_TYPES


class TestPostprocessSegmentation:
    """Turning logits into a label map."""

    def test_multiclass_argmax(self):
        logits = np.full((1, 3, 8, 8), -5.0, dtype=np.float32)
        logits[0, 1, :4, :] = 10.0  # top half → class 1
        logits[0, 2, 4:, :] = 10.0  # bottom half → class 2

        labels, confidence = postprocess_segmentation([logits], 0.5, (8, 8))
        assert labels.shape == (8, 8)
        assert set(np.unique(labels)) == {1, 2}
        assert np.all(labels[:4, :] == 1)
        assert np.all(labels[4:, :] == 2)
        assert confidence.min() > 0.9

    def test_low_confidence_falls_back_to_background(self):
        """An unsure model must not assert a class."""
        logits = np.zeros((1, 3, 6, 6), dtype=np.float32)  # uniform → p = 1/3
        labels, confidence = postprocess_segmentation([logits], 0.9, (6, 6))
        assert np.all(labels == SEGMENTATION_BACKGROUND_CLASS)
        assert confidence.max() < 0.9

    def test_binary_head(self):
        """(1, 1, H, W) is a sigmoid head, not a one-class softmax."""
        logits = np.full((1, 1, 6, 6), -8.0, dtype=np.float32)
        logits[0, 0, :3, :] = 8.0
        labels, confidence = postprocess_segmentation([logits], 0.5, (6, 6))
        assert np.all(labels[:3, :] == 1)
        assert np.all(labels[3:, :] == 0)
        assert confidence.min() > 0.9, "confidence must describe the CHOSEN class"

    def test_resizes_to_tile_shape(self):
        """Model grid and raster grid differ; output must be on the raster's."""
        logits = np.zeros((1, 2, 16, 16), dtype=np.float32)
        logits[0, 1] = 10.0
        labels, confidence = postprocess_segmentation([logits], 0.5, (40, 30))
        assert labels.shape == (40, 30)
        assert confidence.shape == (40, 30)
        assert np.all(labels == 1)

    def test_labels_are_never_interpolated(self):
        """Nearest-neighbour only — averaging class 1 and 3 would invent 2."""
        logits = np.full((1, 4, 4, 4), -9.0, dtype=np.float32)
        logits[0, 1, :, :2] = 9.0
        logits[0, 3, :, 2:] = 9.0
        labels, _ = postprocess_segmentation([logits], 0.5, (16, 16))
        assert set(np.unique(labels)) <= {1, 3}, (
            f"interpolation invented classes: {np.unique(labels)}"
        )

    def test_rejects_non_4d_output(self):
        with pytest.raises(ValueError, match="4-D"):
            postprocess_segmentation([np.zeros((1, 100, 6))], 0.5, (8, 8))


class TestWriteLabelRaster:
    def test_writes_georeferenced_byte_raster(self, label_map, tmp_path):
        out = str(tmp_path / "labels.tif")
        write_label_raster(label_map, out, _GT, _wkt())

        ds = gdal.Open(out)
        assert ds.RasterCount == 1
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Byte
        assert ds.GetGeoTransform() == pytest.approx(_GT)
        assert ds.GetProjection()
        ds = None

    def test_background_becomes_nodata(self, label_map, tmp_path):
        """Otherwise QGIS renders the unclassified area as a solid block."""
        out = str(tmp_path / "labels.tif")
        write_label_raster(label_map, out, _GT, _wkt())

        ds = gdal.Open(out)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        assert band.GetNoDataValue() == pytest.approx(LABEL_NODATA)
        assert np.all(arr[label_map == 0] == LABEL_NODATA)
        assert np.all(arr[label_map == 1] == 1)
        ds = None

    def test_rejects_3d_input(self, tmp_path):
        with pytest.raises(ValueError, match="2D label map"):
            write_label_raster(
                np.zeros((4, 4, 3), dtype=np.uint8),
                str(tmp_path / "x.tif"),
                _GT,
                _wkt(),
            )


class TestPolygoniseLabels:
    def test_writes_one_polygon_per_region(self, label_map, tmp_path):
        out = str(tmp_path / "segs.gpkg")
        count = polygonise_labels(label_map, _GT, _wkt(), out, min_area_pixels=5)
        assert count == 2, "expected the class-1 square and the class-2 blob"

        ds = ogr.Open(out)
        layer = ds.GetLayer(0)
        assert layer.GetFeatureCount() == 2
        assert {f.GetField("class_id") for f in layer} == {1, 2}
        ds = None

    def test_background_is_excluded(self, label_map, tmp_path):
        """One polygon covering every unclassified pixel is useless."""
        out = str(tmp_path / "segs.gpkg")
        polygonise_labels(label_map, _GT, _wkt(), out, min_area_pixels=1)

        ds = ogr.Open(out)
        layer = ds.GetLayer(0)
        assert 0 not in {f.GetField("class_id") for f in layer}
        ds = None

    def test_min_area_filters_speckle(self, label_map, tmp_path):
        """The single-pixel class-1 dot is model noise, not archaeology."""
        strict = str(tmp_path / "strict.gpkg")
        loose = str(tmp_path / "loose.gpkg")
        assert polygonise_labels(label_map, _GT, _wkt(), strict, min_area_pixels=5) == 2
        assert polygonise_labels(label_map, _GT, _wkt(), loose, min_area_pixels=1) == 3

    def test_attributes_are_populated(self, label_map, tmp_path):
        out = str(tmp_path / "segs.gpkg")
        confidence = np.full(label_map.shape, 0.75, dtype=np.float32)
        polygonise_labels(
            label_map,
            _GT,
            _wkt(),
            out,
            labels_map=["background", "ditch", "bank"],
            confidence=confidence,
            min_area_pixels=5,
        )

        ds = ogr.Open(out)
        layer = ds.GetLayer(0)
        by_class = {f.GetField("class_id"): f for f in layer}
        assert by_class[1].GetField("class_name") == "ditch"
        assert by_class[2].GetField("class_name") == "bank"
        # 10x10 cells at 1 m
        assert by_class[1].GetField("area_m2") == pytest.approx(100.0)
        assert by_class[1].GetField("pixel_count") == 100
        assert by_class[1].GetField("mean_confidence") == pytest.approx(0.75)
        ds = None

    def test_unnamed_classes_get_a_fallback_name(self, label_map, tmp_path):
        out = str(tmp_path / "segs.gpkg")
        polygonise_labels(label_map, _GT, _wkt(), out, min_area_pixels=5)
        ds = ogr.Open(out)
        names = {f.GetField("class_name") for f in ds.GetLayer(0)}
        assert names == {"class_1", "class_2"}
        ds = None

    def test_refuses_to_write_without_crs(self, label_map, tmp_path):
        """A CRS-less layer would be misplaced against every other layer."""
        with pytest.raises(ValueError, match="no CRS"):
            polygonise_labels(label_map, _GT, "", str(tmp_path / "x.gpkg"))

    def test_empty_label_map_writes_no_polygons(self, tmp_path):
        empty = np.zeros((20, 20), dtype=np.uint8)
        out = str(tmp_path / "none.gpkg")
        assert polygonise_labels(empty, _GT, _wkt(), out) == 0


class TestSegmentRasterEndToEnd:
    """Drive segment_raster with a real ONNX model."""

    @pytest.fixture
    def onnx_threshold_model(self, tmp_path):
        """A model that classifies pixels above a threshold as class 1.

        Built with the onnx helper API so the test exercises genuine
        onnxruntime inference rather than a stubbed session.
        """
        onnx = pytest.importorskip("onnx")
        pytest.importorskip("onnxruntime")
        from onnx import TensorProto, helper

        # input (1,3,H,W) -> take band 0, compare to 0.5 -> 2-channel logits
        node_slice = helper.make_node(
            "Slice",
            ["input", "starts", "ends", "axes"],
            ["band0"],
        )
        node_sub = helper.make_node("Sub", ["band0", "half"], ["centred"])
        node_scale = helper.make_node("Mul", ["centred", "gain"], ["fg"])
        node_neg = helper.make_node("Neg", ["fg"], ["bg"])
        node_concat = helper.make_node("Concat", ["bg", "fg"], ["output"], axis=1)

        graph = helper.make_graph(
            [node_slice, node_sub, node_scale, node_neg, node_concat],
            "threshold_segmenter",
            [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 32, 32])],
            [
                helper.make_tensor_value_info(
                    "output", TensorProto.FLOAT, [1, 2, 32, 32]
                )
            ],
            initializer=[
                helper.make_tensor("starts", TensorProto.INT64, [1], [0]),
                helper.make_tensor("ends", TensorProto.INT64, [1], [1]),
                helper.make_tensor("axes", TensorProto.INT64, [1], [1]),
                helper.make_tensor("half", TensorProto.FLOAT, [1], [0.5]),
                helper.make_tensor("gain", TensorProto.FLOAT, [1], [40.0]),
            ],
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        model.ir_version = 8
        path = str(tmp_path / "seg.onnx")
        onnx.save(model, path)
        return path

    @pytest.fixture
    def bright_square_raster(self, tmp_path):
        """Raster whose upper-left quadrant is bright."""
        size = 64
        arr = np.zeros((size, size), dtype=np.float32)
        arr[:32, :32] = 1.0
        path = str(tmp_path / "scene.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Float32)
        ds.SetGeoTransform(_GT)
        ds.SetProjection(_wkt())
        ds.GetRasterBand(1).WriteArray(arr)
        ds = None
        return path

    def test_segments_the_bright_region(
        self, onnx_threshold_model, bright_square_raster, tmp_path
    ):
        from lidar_relief.ml.detector import load_model, segment_raster

        model = load_model(onnx_threshold_model)
        assert model["model_type"] == "semantic_segmentation", (
            "a (1, C, H, W) output must be recognised as segmentation"
        )

        result = segment_raster(
            bright_square_raster,
            model,
            confidence_threshold=0.5,
            tile_size=32,
            overlap=0,
        )

        labels = result["labels"]
        assert labels.shape == (64, 64)
        assert not result["cancelled"]
        # The bright quadrant should be class 1, the rest background.
        assert labels[:32, :32].mean() > 0.9
        assert labels[32:, 32:].mean() < 0.1

    def test_uniform_tiles_still_classify(
        self, onnx_threshold_model, bright_square_raster
    ):
        """Regression: per-tile normalisation blanked uniform tiles.

        With tile_size equal to the bright quadrant, every tile is
        internally constant. Scaling each tile by its own min/max mapped
        them all to zeros, so identical input reached the model for
        bright and dark ground alike and the whole raster came back as
        background. segment_raster now normalises against raster-wide
        percentiles instead.
        """
        from lidar_relief.ml.detector import load_model, segment_raster

        model = load_model(onnx_threshold_model)
        result = segment_raster(
            bright_square_raster,
            model,
            confidence_threshold=0.5,
            tile_size=32,
            overlap=0,
        )
        labels = result["labels"]

        assert labels.max() > 0, (
            "every tile was uniform and all classified as background — "
            "tiles are being normalised in isolation again"
        )
        assert labels[:32, :32].mean() > 0.9
        assert labels[32:, :32].mean() < 0.1

    def test_result_carries_georeferencing(
        self, onnx_threshold_model, bright_square_raster
    ):
        from lidar_relief.ml.detector import load_model, segment_raster

        model = load_model(onnx_threshold_model)
        result = segment_raster(bright_square_raster, model, tile_size=32, overlap=0)
        assert result["geo_transform"] == pytest.approx(_GT)
        assert result["projection"]
        assert result["class_counts"]

    def test_full_export_chain(
        self, onnx_threshold_model, bright_square_raster, tmp_path
    ):
        """segment → label raster → polygons, as the algorithm does it."""
        from lidar_relief.ml.detector import load_model, segment_raster

        model = load_model(onnx_threshold_model)
        result = segment_raster(bright_square_raster, model, tile_size=32, overlap=0)

        raster_out = str(tmp_path / "labels.tif")
        write_label_raster(
            result["labels"], raster_out, result["geo_transform"], result["projection"]
        )
        assert gdal.Open(raster_out) is not None

        vector_out = str(tmp_path / "segs.gpkg")
        count = polygonise_labels(
            result["labels"],
            result["geo_transform"],
            result["projection"],
            vector_out,
            confidence=result["confidence"],
            min_area_pixels=10,
        )
        assert count >= 1

        ds = ogr.Open(vector_out)
        layer = ds.GetLayer(0)
        feature = layer.GetNextFeature()
        # The bright quadrant is 32x32 = 1024 cells of 1 m.
        assert feature.GetField("area_m2") == pytest.approx(1024.0, rel=0.05)
        ds = None
