"""detector.py — ONNX model inference for AI feature detection.

exports: onnx_available() -> bool,
         load_model(model_path, label_path) -> dict,
         detect_features(raster_path, model, **kwargs) -> dict,
         preprocess_tile(tile, input_size) -> np.ndarray,
         postprocess_detections(outputs, confidence_threshold, labels, ...) -> list

used_by: algorithms/ai_detection_algorithm.py

rules:
  User provides their own ONNX model — no training in plugin.
  Plugin acts as inference engine only.
  Lightweight dependency: onnxruntime + numpy.
  Tiled processing for large rasters.
  Bounding boxes are returned in RASTER PIXEL coordinates and MUST be
  converted to map coordinates by the caller (see pixel_bbox_to_map_bbox).
  Only object_detection (YOLO/SSD) is supported. Semantic segmentation
  (U-Net) is detected but not post-processed — see SUPPORTED_MODEL_TYPES.
"""

import json
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort

    _ONNX_AVAILABLE = True
except ImportError:
    _ONNX_AVAILABLE = False

# Supported model types and their expected output formats.
SUPPORTED_MODEL_TYPES = {
    "object_detection": {
        "description": "Bounding box detection (YOLO, SSD, etc.)",
        "expected_outputs": ["num_dets", "det_boxes", "det_scores", "det_classes"],
        "postprocess": "yolo",
    },
    "semantic_segmentation": {
        "description": "Per-pixel class map (U-Net, SegFormer, DeepLab, etc.)",
        "expected_outputs": ["logits (N, C, H, W) or (N, 1, H, W)"],
        "postprocess": "segmentation",
    },
}

# Class index treated as "not a feature" in a segmentation label map.
# Near-universal convention for segmentation training sets.
SEGMENTATION_BACKGROUND_CLASS = 0


def onnx_available() -> bool:
    """Check if onnxruntime is installed."""
    return _ONNX_AVAILABLE


def check_dependencies() -> None:
    """Raise ImportError if onnxruntime missing."""
    if not _ONNX_AVAILABLE:
        raise ImportError(
            "AI feature detection requires 'onnxruntime'.\n\n"
            "Install via OSGeo4W Shell:\n"
            "  pip install onnxruntime\n\n"
            "For faster CPU inference with Intel CPUs:\n"
            "  pip install onnxruntime-openvino"
        )


def detect_model_type(output_names, output_shapes=None) -> str:
    """Infer whether an ONNX model detects boxes or segments pixels.

    Args:
        output_names: Output tensor names from the session.
        output_shapes: Matching shapes, where known. Entries may contain
            strings for dynamic dimensions.

    Returns:
        ``'semantic_segmentation'`` or ``'object_detection'``.

    Rules:
        Shape is the reliable signal; names are only a hint. A
        segmentation head emits ONE 4-D tensor (N, C, H, W) whose last
        two dims are the spatial grid. A detector emits either several
        tensors or a single 3-D (N, boxes, attrs) tensor.
        The previous version only looked for the substring 'label_map'
        in an output name, so ordinary U-Net exports — whose output is
        usually just called 'output' — were misread as detectors, run
        through the YOLO postprocessor, and silently produced nothing.
    """
    for name in output_names:
        lowered = name.lower()
        if "label_map" in lowered or "segmentation" in lowered:
            return "semantic_segmentation"

    if output_shapes and len(output_shapes) == 1:
        shape = output_shapes[0]
        if shape is not None and len(shape) == 4:
            # (N, C, H, W): the trailing dims are a pixel grid. Dynamic
            # axes come through as strings, which is itself typical of a
            # segmentation export with variable input size.
            return "semantic_segmentation"

    return "object_detection"


def load_model(
    model_path: str,
    label_path: Optional[str] = None,
) -> dict:
    """Load an ONNX model and its label map.

    Args:
        model_path: Path to the .onnx model file.
        label_path: Optional path to labels.json file.

    Returns:
        dict with:
            - 'session': ONNX Runtime InferenceSession
            - 'input_name': str
            - 'input_shape': tuple (batch, channels, height, width)
            - 'output_names': list of str
            - 'labels': list of class names (empty if no label file)
            - 'model_type': str ('object_detection' or 'semantic_segmentation')
    """
    check_dependencies()

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    # Load labels
    labels = []
    if label_path and os.path.exists(label_path):
        try:
            with open(label_path) as f:
                label_data = json.load(f)
                if isinstance(label_data, list):
                    labels = label_data
                elif isinstance(label_data, dict):
                    # Support {0: "barrow", 1: "ditch"} format, mapping to correct class ID indices
                    max_idx = -1
                    int_keys = {}
                    for k, v in label_data.items():
                        try:
                            ik = int(k)
                            int_keys[ik] = v
                            if ik > max_idx:
                                max_idx = ik
                        except ValueError:
                            pass
                    if int_keys:
                        labels = [
                            int_keys.get(i, f"class_{i}") for i in range(max_idx + 1)
                        ]
                    else:
                        labels = []
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load labels: %s", e)

    # Create inference session
    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_options.enable_cpu_mem_arena = True

    providers = ort.get_available_providers()
    session = ort.InferenceSession(
        model_path,
        sess_options,
        providers=providers,
    )

    # Get model metadata
    input_info = session.get_inputs()[0]
    input_name = input_info.name
    input_shape = input_info.shape  # (N, C, H, W)

    outputs = session.get_outputs()
    output_names = [o.name for o in outputs]
    output_shapes = [getattr(o, "shape", None) for o in outputs]

    model_type = detect_model_type(output_names, output_shapes)

    if model_type not in SUPPORTED_MODEL_TYPES:  # pragma: no cover - defensive
        logger.warning(
            "Model '%s' was detected as '%s', which has no postprocessor. "
            "Inference will run but results will be empty.",
            os.path.basename(model_path),
            model_type,
        )

    logger.info(
        "Loaded ONNX model: %s, type=%s, inputs=%s, outputs=%s",
        os.path.basename(model_path),
        model_type,
        input_shape,
        output_names,
    )

    return {
        "session": session,
        "input_name": input_name,
        "input_shape": input_shape,
        "output_names": output_names,
        "labels": labels,
        "model_type": model_type,
    }


def preprocess_tile(
    tile: np.ndarray,
    input_size: tuple[int, int],
    norm_range: Optional[tuple] = None,
) -> np.ndarray:
    """Preprocess a raster tile for model inference.

    Args:
        tile: 2D (H, W) or 3D (H, W, C) numpy array.
        input_size: Model input size (height, width).
        norm_range: Optional ``(low, high)`` used to scale floating-point
            input to [0, 1]. When ``None`` each tile is scaled by its own
            min and max.

    Returns:
        Preprocessed array of shape (1, C, H, W) as float32.

    Rules:
        Pass an explicit ``norm_range`` for any job that stitches tiles
        back together. Per-tile min/max scaling makes the SAME terrain
        present differently depending on which tile it landed in, and a
        uniform tile — flat ground, or a solid patch of a large feature —
        normalises to all zeros regardless of its actual elevation. That
        is tolerable for independent bounding boxes but it wrecks a
        segmentation mosaic, so segment_raster computes raster-wide
        percentiles once and passes them in.
    """
    # Handle single-band → 3-channel by stacking
    if tile.ndim == 2:
        tile = np.stack([tile] * 3, axis=-1)
    elif tile.ndim == 3 and tile.shape[2] == 1:
        tile = np.repeat(tile, 3, axis=2)

    # Resize to input size using bilinear interpolation (cv2 preferred).
    h, w = input_size
    src_h, src_w = tile.shape[:2]

    try:
        import cv2

        tile_resized = cv2.resize(tile, (w, h), interpolation=cv2.INTER_LINEAR)
    except ImportError:
        # Pure-NumPy bilinear fallback — the previous nearest-neighbour
        # fallback aliasing was flagged in the v2.0.5 changelog as fixed,
        # but only the cv2 path was actually bilinear. This fallback now
        # matches the cv2 path's behaviour for non-uint8 inputs.
        tile_resized = _bilinear_resize(tile, (h, w))

    # Normalize to [0, 1]. The previous heuristic (`if max > 1: /=`)
    # silently destroyed information for legitimate float rasters whose
    # value range is 0..90 (slope degrees), 0..120 (openness), -1..1
    # (SLRM). We now use a more conservative rule: only auto-scale
    # integer-typed inputs (which are conventionally 0..255 image data).
    tile_float = tile_resized.astype(np.float32)
    if np.issubdtype(tile_resized.dtype, np.integer):
        tile_float /= 255.0
    else:
        if norm_range is not None:
            t_min, t_max = float(norm_range[0]), float(norm_range[1])
        else:
            # Per-tile min-max fallback. See the rules above for why this
            # is unsuitable when tiles are stitched back together.
            finite = tile_float[np.isfinite(tile_float)]
            if finite.size > 0:
                t_min = float(finite.min())
                t_max = float(finite.max())
            else:
                t_min = t_max = 0.0

        if t_max - t_min > 1e-6:
            tile_float = (tile_float - t_min) / (t_max - t_min)
            tile_float = np.clip(tile_float, 0.0, 1.0)
        else:
            tile_float = np.zeros_like(tile_float)
        tile_float = np.nan_to_num(tile_float, nan=0.0, posinf=1.0, neginf=0.0)

    # Convert to (C, H, W) format and add batch dimension
    tile_nhwc = np.transpose(tile_float, (2, 0, 1))  # (C, H, W)
    tile_batch = np.expand_dims(tile_nhwc, axis=0)  # (1, C, H, W)

    return tile_batch


def _bilinear_resize(tile: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """Pure-NumPy bilinear resize. Matches cv2.INTER_LINEAR for 2D and 3D inputs.

    Args:
        tile: (H, W) or (H, W, C) array.
        target_size: (out_h, out_w).

    Returns:
        Resized array with dtype preserved.
    """
    out_h, out_w = target_size
    src_h, src_w = tile.shape[:2]
    if tile.ndim == 2:
        return _bilinear_resize(tile[..., np.newaxis], target_size)[..., 0]

    # Compute source coordinates for each output pixel (align_corners=False,
    # half-pixel shift — matches cv2/OpenCV semantics).
    y_ratio = src_h / out_h
    x_ratio = src_w / out_w
    y_src = (np.arange(out_h) + 0.5) * y_ratio - 0.5
    x_src = (np.arange(out_w) + 0.5) * x_ratio - 0.5
    y_src = np.clip(y_src, 0.0, src_h - 1.0)
    x_src = np.clip(x_src, 0.0, src_w - 1.0)
    y0 = np.floor(y_src).astype(np.int32)
    x0 = np.floor(x_src).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, src_h - 1)
    x1 = np.clip(x0 + 1, 0, src_w - 1)
    wy = (y_src - y0)[:, np.newaxis]
    wx = (x_src - x0)[np.newaxis, :]

    # Gather four neighbours and interpolate.
    tile_00 = tile[y0[:, np.newaxis], x0[np.newaxis, :], :]
    tile_01 = tile[y0[:, np.newaxis], x1[np.newaxis, :], :]
    tile_10 = tile[y1[:, np.newaxis], x0[np.newaxis, :], :]
    tile_11 = tile[y1[:, np.newaxis], x1[np.newaxis, :], :]

    top = tile_00 * (1 - wx)[..., np.newaxis] + tile_01 * wx[..., np.newaxis]
    bot = tile_10 * (1 - wx)[..., np.newaxis] + tile_11 * wx[..., np.newaxis]
    out = top * (1 - wy)[..., np.newaxis] + bot * wy[..., np.newaxis]
    return out.astype(tile.dtype, copy=False)


def _nearest_resize_labels(labels: np.ndarray, target_size: tuple) -> np.ndarray:
    """Resize a label map with nearest-neighbour sampling.

    Rules:
        Label maps must NEVER be interpolated. Averaging class index 1
        and class index 3 yields 2, inventing a class that the model
        never predicted at that pixel.
    """
    out_h, out_w = target_size
    src_h, src_w = labels.shape[:2]
    if (src_h, src_w) == (out_h, out_w):
        return labels

    rows = np.clip(
        ((np.arange(out_h) + 0.5) * src_h / out_h).astype(np.int32), 0, src_h - 1
    )
    cols = np.clip(
        ((np.arange(out_w) + 0.5) * src_w / out_w).astype(np.int32), 0, src_w - 1
    )
    return labels[rows[:, None], cols[None, :]]


def _softmax(logits: np.ndarray, axis: int = 0) -> np.ndarray:
    """Numerically stable softmax."""
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=axis, keepdims=True)


def postprocess_segmentation(
    outputs: list,
    confidence_threshold: float,
    tile_shape: tuple,
) -> tuple:
    """Turn a segmentation head's logits into a label map for one tile.

    Handles the two shapes archaeological segmentation models actually
    ship in: multi-class ``(1, C, H, W)`` logits, and single-channel
    ``(1, 1, H, W)`` binary logits.

    Args:
        outputs: Raw ONNX outputs; the first is used.
        confidence_threshold: Pixels whose winning class scores below
            this become background.
        tile_shape: ``(rows, cols)`` of the source tile, so the label map
            comes back on the raster's grid rather than the model's.

    Returns:
        ``(labels, confidence)`` — uint8 class indices and float32 scores,
        both shaped ``tile_shape``.

    Raises:
        ValueError: If the output is not a 4-D tensor.
    """
    logits = np.asarray(outputs[0])
    if logits.ndim != 4:
        raise ValueError(
            f"Expected a 4-D (N, C, H, W) segmentation output, got shape "
            f"{logits.shape}. This model does not look like a segmentation "
            f"head."
        )

    logits = logits[0]  # drop batch → (C, H, W)
    channels = logits.shape[0]

    if channels == 1:
        # Binary head: one logit per pixel, sigmoid to a probability.
        probability = 1.0 / (1.0 + np.exp(-logits[0]))
        labels = (probability >= confidence_threshold).astype(np.uint8)
        # Confidence in the CHOSEN class, so background is reported with
        # its own certainty rather than the foreground probability.
        confidence = np.where(labels == 1, probability, 1.0 - probability)
    else:
        probabilities = _softmax(logits, axis=0)
        labels = np.argmax(probabilities, axis=0).astype(np.uint8)
        confidence = np.max(probabilities, axis=0)
        # Low-confidence wins fall back to background rather than
        # asserting a class the model was unsure about.
        labels = np.where(
            confidence >= confidence_threshold, labels, SEGMENTATION_BACKGROUND_CLASS
        ).astype(np.uint8)

    labels = _nearest_resize_labels(labels, tile_shape)
    confidence = _nearest_resize_labels(
        confidence.astype(np.float32), tile_shape
    ).astype(np.float32)

    return labels, confidence


def _global_norm_range(dataset, sample_max: int = 1024):
    """Compute a raster-wide (low, high) scaling range from a decimated read.

    Uses the 2nd and 98th percentiles of a subsampled read rather than
    band statistics, so the range is robust to a handful of spike cells
    and cheap even on a very large raster.

    Returns:
        ``(low, high)``, or ``None`` if the raster has no usable values
        (the caller then falls back to per-tile scaling).
    """
    band = dataset.GetRasterBand(1)
    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize
    scale = max(1.0, max(x_size, y_size) / float(sample_max))
    out_x = max(1, int(x_size / scale))
    out_y = max(1, int(y_size / scale))

    try:
        sample = band.ReadAsArray(
            0, 0, x_size, y_size, buf_xsize=out_x, buf_ysize=out_y
        )
    except Exception:  # pragma: no cover - unreadable raster
        return None
    if sample is None:
        return None

    sample = np.asarray(sample, dtype=np.float32)
    if sample.ndim == 3:
        sample = sample[0]

    nodata = band.GetNoDataValue()
    finite = np.isfinite(sample)
    if nodata is not None:
        finite &= ~np.isclose(sample, nodata, atol=1e-5, rtol=0.0)
    values = sample[finite]
    if values.size == 0:
        return None

    low, high = np.percentile(values, [2, 98])
    if high - low <= 1e-6:
        low, high = float(values.min()), float(values.max())
    if high - low <= 1e-6:
        return None
    return float(low), float(high)


def segment_raster(
    raster_path: str,
    model: dict,
    confidence_threshold: float = 0.5,
    tile_size: int = 512,
    overlap: int = 64,
    feedback=None,
) -> dict:
    """Run semantic segmentation over a raster, tile by tile.

    Args:
        raster_path: Raster to segment.
        model: Model dict from :func:`load_model`.
        confidence_threshold: Minimum winning-class score to keep.
        tile_size: Tile size in pixels.
        overlap: Overlap between tiles. Half of it is trimmed from each
            interior edge before compositing.
        feedback: Optional progress callback.

    Returns:
        dict with ``labels`` (uint8 H x W), ``confidence`` (float32),
        ``geo_transform``, ``projection``, ``class_counts``, ``labels_present``
        and ``cancelled``.

    Rules:
        Interior tile edges are trimmed by half the overlap before being
        written into the mosaic. A segmentation head is least reliable at
        its receptive-field boundary, so keeping the full tile would
        stitch the worst pixels straight into the seam.
    """
    check_dependencies()

    try:
        from osgeo import gdal
    except ImportError:
        raise RuntimeError("GDAL is required for raster I/O.")

    session = model["session"]
    input_name = model["input_name"]
    input_shape = model["input_shape"]
    output_names = model["output_names"]

    if len(input_shape) >= 2:
        model_h, model_w = input_shape[-2], input_shape[-1]
    else:  # pragma: no cover - malformed export
        model_h = model_w = None
    if isinstance(model_h, int) and isinstance(model_w, int):
        model_input_size = (model_h, model_w)
    else:
        model_input_size = (tile_size, tile_size)

    ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {raster_path}")

    raster_x = ds.RasterXSize
    raster_y = ds.RasterYSize
    geo_transform = ds.GetGeoTransform()
    projection = ds.GetProjection()

    # One raster-wide normalisation range for every tile, so the mosaic
    # is coherent. Percentiles rather than min/max so a single spike
    # cannot compress the terrain into a narrow band.
    norm_range = _global_norm_range(ds)
    if norm_range is not None:
        logger.info(
            "Normalising all tiles against raster range %.4f..%.4f",
            norm_range[0],
            norm_range[1],
        )

    labels = np.zeros((raster_y, raster_x), dtype=np.uint8)
    confidence = np.zeros((raster_y, raster_x), dtype=np.float32)

    stride = max(1, tile_size - overlap)
    trim = overlap // 2
    n_tiles_x = max(1, (raster_x - overlap + stride - 1) // stride)
    n_tiles_y = max(1, (raster_y - overlap + stride - 1) // stride)
    total_tiles = n_tiles_x * n_tiles_y
    tiles_processed = 0
    cancelled = False

    for ty in range(n_tiles_y):
        for tx in range(n_tiles_x):
            if feedback and feedback.isCanceled():
                cancelled = True
                break

            x_off = tx * stride
            y_off = ty * stride
            x_size = min(tile_size, raster_x - x_off)
            y_size = min(tile_size, raster_y - y_off)
            if x_size <= 0 or y_size <= 0:
                continue

            tile_data = ds.ReadAsArray(x_off, y_off, x_size, y_size)
            if tile_data is None:  # pragma: no cover - unreadable block
                continue

            if tile_data.ndim == 3:
                tile_array = np.transpose(tile_data, (1, 2, 0))
            else:
                tile_array = tile_data

            input_tensor = preprocess_tile(
                tile_array, model_input_size, norm_range=norm_range
            )
            raw = session.run(output_names, {input_name: input_tensor})
            tile_labels, tile_conf = postprocess_segmentation(
                raw, confidence_threshold, tile_array.shape[:2]
            )

            # Trim half the overlap from interior edges only — the raster
            # boundary has no neighbour to blend with.
            top = trim if ty > 0 else 0
            left = trim if tx > 0 else 0
            bottom = y_size - trim if (y_off + y_size) < raster_y else y_size
            right = x_size - trim if (x_off + x_size) < raster_x else x_size
            if bottom <= top or right <= left:  # pragma: no cover - tiny raster
                top, left, bottom, right = 0, 0, y_size, x_size

            # Bounds hoisted into locals so the slice expressions stay
            # simple — black formats `a + b : c + d` with spaces around
            # the colon, which the QGIS plugin scanner rejects as E203.
            dst_y0 = y_off + top
            dst_y1 = y_off + bottom
            dst_x0 = x_off + left
            dst_x1 = x_off + right
            labels[dst_y0:dst_y1, dst_x0:dst_x1] = tile_labels[top:bottom, left:right]
            confidence[dst_y0:dst_y1, dst_x0:dst_x1] = tile_conf[top:bottom, left:right]

            tiles_processed += 1
            if feedback:
                feedback.setProgress(int(100 * tiles_processed / total_tiles))
        if cancelled:
            break

    ds = None

    present, counts = np.unique(labels, return_counts=True)
    class_counts = {int(c): int(n) for c, n in zip(present, counts)}

    return {
        "labels": labels,
        "confidence": confidence,
        "geo_transform": geo_transform,
        "projection": projection,
        "class_counts": class_counts,
        "labels_present": [int(c) for c in present],
        "total_tiles": total_tiles,
        "tiles_processed": tiles_processed,
        "model_type": "semantic_segmentation",
        "cancelled": cancelled,
    }


def detect_features(
    raster_path: str,
    model: dict,
    confidence_threshold: float = 0.5,
    iou_threshold: float = 0.45,
    tile_size: int = 640,
    overlap: int = 32,
    feedback=None,
) -> dict:
    """Run object detection on a raster using the loaded model.

    Processes the raster in tiles to handle large images, then merges
    overlapping detections using NMS.

    Args:
        raster_path: Path to the raster file to analyze.
        model: Model dict from load_model().
        confidence_threshold: Minimum confidence for detections.
        iou_threshold: IoU threshold for NMS.
        tile_size: Tile size in pixels for processing.
        overlap: Overlap between adjacent tiles.
        feedback: Optional progress callback.

    Returns:
        dict with:
            - 'detections': list of dicts with 'bbox', 'confidence',
              'class_id', 'class_name'
            - 'detection_count': int
            - 'total_tiles': int
    """
    check_dependencies()

    try:
        from osgeo import gdal
    except ImportError:
        raise RuntimeError("GDAL is required for raster I/O.")

    session = model["session"]
    input_name = model["input_name"]
    input_shape = model["input_shape"]
    output_names = model["output_names"]
    labels = model["labels"]
    model_type = model["model_type"]

    # Expected input size from model (H, W). The shape is typically
    # (N, C, H, W) but ONNX exports with dynamic batch / channel dims
    # may return fewer or more elements; only unpack the last two.
    if len(input_shape) >= 2:
        model_h, model_w = input_shape[-2], input_shape[-1]
    else:
        model_h = model_w = None
    if isinstance(model_h, int) and isinstance(model_w, int):
        model_input_size = (model_h, model_w)
    else:
        logger.info(
            "Dynamic input shape %s, using tile_size %sx%s",
            input_shape,
            tile_size,
            tile_size,
        )
        model_input_size = (tile_size, tile_size)

    # Open raster
    ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {raster_path}")

    raster_x = ds.RasterXSize
    raster_y = ds.RasterYSize
    # GeoTransform — needed by the caller to convert pixel-space bboxes
    # into map-space polygons. We attach it to the result dict.
    geo_transform = ds.GetGeoTransform()
    raster_projection = ds.GetProjection()

    all_detections = []
    tiles_processed = 0

    stride = tile_size - overlap
    n_tiles_x = max(1, (raster_x - overlap + stride - 1) // stride)
    n_tiles_y = max(1, (raster_y - overlap + stride - 1) // stride)
    total_tiles = n_tiles_x * n_tiles_y

    for ty in range(n_tiles_y):
        for tx in range(n_tiles_x):
            if feedback and feedback.isCanceled():
                ds = None
                return {
                    "detections": all_detections,
                    "detection_count": len(all_detections),
                    # In the cancelled path we report the total tile count
                    # (consistent with the non-cancelled return) so callers
                    # can compute a meaningful progress percentage.
                    "total_tiles": total_tiles,
                    "tiles_processed": tiles_processed,
                    "geo_transform": geo_transform,
                    "projection": raster_projection,
                    "model_type": model_type,
                    "cancelled": True,
                }

            # Compute tile window
            x_off = tx * stride
            y_off = ty * stride
            x_size = min(tile_size, raster_x - x_off)
            y_size = min(tile_size, raster_y - y_off)

            # Read tile
            tile_data = ds.ReadAsArray(x_off, y_off, x_size, y_size)
            if tile_data is None:
                continue

            # Handle band dimension
            if tile_data.ndim == 3:
                tile_array = np.transpose(tile_data, (1, 2, 0))  # (H, W, C)
            else:
                tile_array = tile_data  # (H, W)

            # Preprocess
            input_tensor = preprocess_tile(tile_array, model_input_size)

            # Postprocess — only object_detection is supported in v2.0.4
            if model_type == "object_detection":
                # Run inference
                outputs = session.run(output_names, {input_name: input_tensor})
                detections = _postprocess_yolo(
                    outputs,
                    confidence_threshold,
                    iou_threshold,
                    labels,
                    x_off,
                    y_off,
                    tile_size,
                    tile_array.shape,
                    model_input_size,
                )
                all_detections.extend(detections)
            elif tiles_processed == 0:
                # Log once per run for unsupported model types
                logger.warning(
                    "Skipping inference: model type '%s' has no "
                    "postprocessor in v2.0.4. Only 'object_detection' "
                    "is supported. Returning zero detections.",
                    model_type,
                )

            tiles_processed += 1
            if feedback:
                feedback.setProgress(int(100 * tiles_processed / total_tiles))

    ds = None

    # Apply global NMS across all tiles
    if model_type == "object_detection" and len(all_detections) > 1:
        all_detections = _apply_nms(all_detections, iou_threshold)

    return {
        "detections": all_detections,
        "detection_count": len(all_detections),
        "total_tiles": total_tiles,
        # Pass the raster geotransform/projection so callers can convert
        # pixel-space bboxes (returned in each detection['bbox']) to map
        # coordinates before writing to a vector layer. Without this
        # conversion detections land hundreds of kilometres from where
        # they were actually detected.
        "geo_transform": geo_transform,
        "projection": raster_projection,
        "model_type": model_type,
        "cancelled": False,
    }


def pixel_bbox_to_map_bbox(
    bbox_pixels,
    geo_transform,
):
    """Convert a pixel-space bbox (x1, y1, x2, y2) to map-space coordinates.

    GDAL GeoTransform layout (6-tuple):
        [0] top-left x
        [1] pixel width  (W-E; positive for north-up rasters)
        [2] row rotation (typically 0; north-up)
        [3] top-left y
        [4] column rotation (typically 0; north-up)
        [5] pixel height (N-S; NEGATIVE for north-up rasters)

    Returns:
        Tuple ``(x1, y1, x2, y2)`` in the same coordinate system as the
        source raster, with ``(x1, y1)`` as the south-west corner and
        ``(x2, y2)`` as the north-east corner regardless of axis
        orientation.
    """
    if not geo_transform or len(geo_transform) < 6:
        raise ValueError("Invalid GeoTransform")
    gt_x, gt_pw, gt_rx, gt_y, gt_ry, gt_ph = geo_transform
    px1, py1, px2, py2 = bbox_pixels
    mx1 = gt_x + px1 * gt_pw + py1 * gt_rx
    my1 = gt_y + px1 * gt_ry + py1 * gt_ph
    mx2 = gt_x + px2 * gt_pw + py2 * gt_rx
    my2 = gt_y + px2 * gt_ry + py2 * gt_ph
    x1, x2 = (mx1, mx2) if mx1 <= mx2 else (mx2, mx1)
    y1, y2 = (my1, my2) if my1 <= my2 else (my2, my1)
    return (x1, y1, x2, y2)


def _postprocess_yolo(
    outputs: list,
    confidence_threshold: float,
    iou_threshold: float,
    labels: list,
    x_off: int,
    y_off: int,
    tile_size: int,
    tile_shape: tuple,
    model_input_size: tuple,
) -> list:
    """Postprocess YOLO model outputs to detection dicts.

    Handles different YOLO output formats (v5/v8/v11).
    """
    detections = []

    # Try standard YOLO output format
    try:
        # YOLOv8/v11: single output tensor (1, N, 6) — [x1, y1, x2, y2, conf, class]
        if len(outputs) == 1 and outputs[0].ndim == 3 and outputs[0].shape[-1] == 6:
            out = outputs[0][0]  # (N, 6)
            for det in out:
                x1, y1, x2, y2, conf, cls_id = det
                if conf >= confidence_threshold:
                    detections.append(
                        _make_detection(
                            x1,
                            y1,
                            x2,
                            y2,
                            float(conf),
                            int(cls_id),
                            labels,
                            x_off,
                            y_off,
                            tile_size,
                            tile_shape,
                            model_input_size,
                        )
                    )

        # YOLOv5/v7: single output tensor with layout
        # (1, N, 5 + num_classes) — [x_center, y_center, w, h, obj_conf, ...class_scores]
        # The original code hard-coded 85 (= 5 + 80 COCO classes); we now
        # accept any width >= 6 so custom YOLOv5 models with fewer or
        # more classes are supported.
        # exclude the v8/v11 layout (which has exactly 6 cols)
        elif len(outputs) == 1 and outputs[0].ndim == 3 and outputs[0].shape[-1] > 6:
            out = outputs[0][0]
            for det in out:
                scores = det[5:]
                cls_id = int(np.argmax(scores))
                conf = float(det[4] * scores[cls_id])
                if conf >= confidence_threshold:
                    cx, cy, w, h = det[0:4]
                    x1 = cx - w / 2
                    y1 = cy - h / 2
                    x2 = cx + w / 2
                    y2 = cy + h / 2
                    detections.append(
                        _make_detection(
                            x1,
                            y1,
                            x2,
                            y2,
                            conf,
                            cls_id,
                            labels,
                            x_off,
                            y_off,
                            tile_size,
                            tile_shape,
                            model_input_size,
                        )
                    )

        # Multi-output: num_dets + boxes + scores + classes
        elif len(outputs) >= 4:
            num = int(outputs[0][0]) if outputs[0].ndim > 0 else 0
            boxes = outputs[1][0] if outputs[1].ndim > 1 else outputs[1]
            scores = outputs[2][0] if outputs[2].ndim > 1 else outputs[2]
            classes = outputs[3][0] if outputs[3].ndim > 1 else outputs[3]

            for i in range(min(num, len(boxes))):
                conf = float(scores[i])
                if conf >= confidence_threshold:
                    x1, y1, x2, y2 = boxes[i]
                    cls_id = int(classes[i])
                    detections.append(
                        _make_detection(
                            x1,
                            y1,
                            x2,
                            y2,
                            conf,
                            cls_id,
                            labels,
                            x_off,
                            y_off,
                            tile_size,
                            tile_shape,
                            model_input_size,
                        )
                    )

    except Exception as e:
        logger.warning("Postprocessing error: %s", e)

    valid_detections = []
    for det in detections:
        bx1, by1, bx2, by2 = det["bbox"]
        if bx2 > bx1 and by2 > by1:
            valid_detections.append(det)

    return valid_detections


def _make_detection(
    x1,
    y1,
    x2,
    y2,
    confidence,
    class_id,
    labels,
    x_off,
    y_off,
    tile_size,
    tile_shape,
    model_input_size,
) -> dict:
    """Create a detection dict with proper coordinate scaling.

    Bounding boxes are returned in **raster pixel coordinates** (col0, row0,
    col1, row1) including tile offset. Callers must convert these to map
    coordinates via :func:`pixel_bbox_to_map_bbox` before writing to a
    vector layer — see ``algorithms/ai_detection_algorithm.py``.
    """
    # Scale from model input size back to tile size
    mh, mw = model_input_size
    th, tw = tile_shape[:2]

    scale_x = tw / mw
    scale_y = th / mh

    # Map to tile coordinates
    tx1 = float(x1) * scale_x + x_off
    ty1 = float(y1) * scale_y + y_off
    tx2 = float(x2) * scale_x + x_off
    ty2 = float(y2) * scale_y + y_off

    tx1 = max(x_off, min(tx1, x_off + tw))
    ty1 = max(y_off, min(ty1, y_off + th))
    tx2 = max(x_off, min(tx2, x_off + tw))
    ty2 = max(y_off, min(ty2, y_off + th))

    class_name = (
        str(labels[class_id]) if 0 <= class_id < len(labels) else f"class_{class_id}"
    )

    return {
        "bbox": [round(tx1, 2), round(ty1, 2), round(tx2, 2), round(ty2, 2)],
        "confidence": round(confidence, 4),
        "class_id": class_id,
        "class_name": class_name,
        "tile_offset": (x_off, y_off),
        # Mark coordinate space so downstream code can assert.
        "bbox_crs": "raster_pixels",
    }


def _apply_nms(detections: list, iou_threshold: float) -> list:
    """Apply Non-Maximum Suppression to remove duplicate detections.

    Args:
        detections: List of detection dicts.
        iou_threshold: IoU threshold for suppression.

    Returns:
        Filtered list of detections.
    """
    if not detections:
        return []

    # Group by class
    by_class = {}
    for det in detections:
        cls_id = det["class_id"]
        if cls_id not in by_class:
            by_class[cls_id] = []
        by_class[cls_id].append(det)

    result = []
    for cls_id, class_dets in by_class.items():
        # Sort by confidence descending
        class_dets.sort(key=lambda d: d["confidence"], reverse=True)

        keep = []
        while class_dets:
            best = class_dets.pop(0)
            keep.append(best)
            # Remove overlapping
            bbox = best["bbox"]
            class_dets = [
                d for d in class_dets if _compute_iou(bbox, d["bbox"]) < iou_threshold
            ]
        result.extend(keep)

    return result


def _compute_iou(bbox1: list, bbox2: list) -> float:
    """Compute Intersection over Union between two bounding boxes."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    if x2 < x1 or y2 < y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0
