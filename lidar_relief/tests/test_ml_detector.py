"""test_ml_detector.py — Tests for ONNX model inference.

exports: (test functions)
used_by: pytest runner
rules:
  Tests use a mock ONNX model created on-the-fly.
  Tests verify preprocessing, postprocessing, and pipeline integrity.
"""

import os
import tempfile

import numpy as np
import pytest

pytest.importorskip("osgeo")
# The ML detector requires onnxruntime in addition to GDAL.
pytest.importorskip("onnxruntime")

from osgeo import gdal  # noqa: E402


@pytest.fixture(autouse=True)
def setup():
    tmpdir = tempfile.mkdtemp(prefix="ml_test_")
    yield tmpdir
    import shutil

    shutil.rmtree(tmpdir)


def _create_test_raster(path, width=200, height=200):
    """Create a single-band test raster."""
    data = np.random.default_rng(42).random((height, width)).astype(np.float32)
    ds = gdal.GetDriverByName("GTiff").Create(
        path,
        width,
        height,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=LZW"],
    )
    ds.SetGeoTransform((500000, 1.0, 0, 6000000, 0, -1.0))
    ds.SetProjection("EPSG:32630")
    ds.GetRasterBand(1).WriteArray(data)
    ds.FlushCache()
    ds = None


def _create_minimal_onnx_model(path):
    """Create a minimal ONNX model for testing.

    This is a tiny ConvNet that takes (1, 3, 64, 64) input and
    produces a single output tensor (1, 3).
    """
    import onnx
    from onnx import helper, TensorProto, numpy_helper

    # Input: (1, 3, 64, 64)
    X = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 64, 64])

    # Weight initializer: 3 filters, 3 input channels, 1x1 kernel
    W_data = np.ones((3, 3, 1, 1), dtype=np.float32)
    W_init = numpy_helper.from_array(W_data, name="W")

    conv = helper.make_node(
        "Conv",
        ["input", "W"],
        ["conv_out"],
        kernel_shape=[1, 1],
    )

    # Global average pool to (3, 1, 1)
    pool = helper.make_node(
        "GlobalAveragePool",
        ["conv_out"],
        ["pool_out"],
    )

    # Flatten to (1, 3)
    flatten = helper.make_node(
        "Flatten",
        ["pool_out"],
        ["output"],
    )

    # Output: (1, 3)
    Y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3])

    graph = helper.make_graph(
        [conv, pool, flatten],
        "test_model",
        [X],
        [Y],
        initializer=[W_init],
    )

    # ONNX 1.22's helper defaults to opset 27, while the matching stable
    # ONNX Runtime 1.27 guarantees support through opset 26. Real models
    # declare their own opset; pin this generated fixture to the newest
    # runtime-supported release so the test exercises a valid contract.
    model = helper.make_model(
        graph,
        producer_name="test",
        opset_imports=[helper.make_opsetid("", 26)],
    )
    onnx.save(model, path)


class TestMLDetector:
    """Tests for ONNX model inference."""

    def test_onnx_available(self):
        """onnxruntime should be available."""
        from lidar_relief.ml.detector import onnx_available

        assert onnx_available()

    def test_load_model(self, setup):
        """Loading a valid ONNX model should succeed."""
        from lidar_relief.ml.detector import load_model

        model_path = os.path.join(setup, "model.onnx")
        _create_minimal_onnx_model(model_path)

        try:
            model = load_model(model_path)
        except Exception as e:
            # Older onnxruntime versions can't load models with newer IR
            # versions. Skip rather than fail — this is an environment
            # issue, not a plugin bug.
            if "IR version" in str(e) or "Unsupported model" in str(e):
                pytest.skip(f"onnxruntime can't load test model (IR version): {e}")
            raise
        assert "session" in model
        assert model["model_type"] in ("object_detection",)
        assert model["input_name"] is not None

    def test_load_model_with_labels(self, setup):
        """Labels should be loaded from JSON file."""
        from lidar_relief.ml.detector import load_model
        import json

        model_path = os.path.join(setup, "model.onnx")
        _create_minimal_onnx_model(model_path)

        label_path = os.path.join(setup, "labels.json")
        with open(label_path, "w") as f:
            json.dump(["barrow", "ditch", "platform"], f)

        try:
            model = load_model(model_path, label_path)
        except Exception as e:
            if "IR version" in str(e) or "Unsupported model" in str(e):
                pytest.skip(f"onnxruntime can't load test model (IR version): {e}")
            raise
        assert model["labels"] == ["barrow", "ditch", "platform"]

    def test_load_model_not_found(self, setup):
        """Missing model file should raise FileNotFoundError."""
        from lidar_relief.ml.detector import load_model

        with pytest.raises(FileNotFoundError):
            load_model("/nonexistent/model.onnx")

    def test_preprocess_tile_rgb(self):
        """RGB tile preprocessing should produce correct shape."""
        from lidar_relief.ml.detector import preprocess_tile

        tile = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        result = preprocess_tile(tile, (64, 64))

        assert result.shape == (1, 3, 64, 64)
        assert result.dtype == np.float32
        # Values should be in [0, 1]
        assert result.max() <= 1.0
        assert result.min() >= 0.0

    def test_preprocess_tile_single_band(self):
        """Single-band tile should be stacked to 3 channels."""
        from lidar_relief.ml.detector import preprocess_tile

        tile = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        result = preprocess_tile(tile, (64, 64))

        assert result.shape == (1, 3, 64, 64)

    def test_inference_pipeline(self, setup):
        """End-to-end inference should produce detection results."""
        from lidar_relief.ml.detector import load_model, detect_features, onnx_available

        if not onnx_available():
            pytest.skip("onnxruntime not installed")

        model_path = os.path.join(setup, "model.onnx")
        _create_minimal_onnx_model(model_path)

        raster_path = os.path.join(setup, "input.tif")
        _create_test_raster(raster_path)

        try:
            model = load_model(model_path)
        except Exception as e:
            if "IR version" in str(e) or "Unsupported model" in str(e):
                pytest.skip(f"onnxruntime can't load test model (IR version): {e}")
            raise
        result = detect_features(
            raster_path,
            model,
            confidence_threshold=0.1,
            tile_size=64,
        )

        assert "detections" in result
        assert "detection_count" in result
        assert result["total_tiles"] > 0

    def test_nms_filtering(self):
        """NMS should remove overlapping detections."""
        from lidar_relief.ml.detector import _apply_nms

        detections = [
            {"bbox": [10, 10, 100, 100], "confidence": 0.9, "class_id": 0},
            {"bbox": [15, 15, 95, 95], "confidence": 0.8, "class_id": 0},
            {"bbox": [200, 200, 300, 300], "confidence": 0.7, "class_id": 0},
        ]

        filtered = _apply_nms(detections, iou_threshold=0.5)
        # The first two overlap heavily, only one should survive
        assert len(filtered) == 2

    def test_iou_computation(self):
        """IoU computation should be correct."""
        from lidar_relief.ml.detector import _compute_iou

        bbox1 = [0, 0, 10, 10]
        bbox2 = [5, 5, 15, 15]
        iou = _compute_iou(bbox1, bbox2)
        # Overlap = 5x5 = 25, Union = 100 + 100 - 25 = 175
        assert abs(iou - 25 / 175) < 0.01

        # No overlap
        bbox3 = [20, 20, 30, 30]
        assert _compute_iou(bbox1, bbox3) == 0.0

        # Identical
        assert _compute_iou(bbox1, bbox1) == 1.0
