"""ai_detection_algorithm.py — QGIS Processing wrapper for AI feature detection.

exports: AiDetectionAlgorithm
used_by: provider.py → loadAlgorithms
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterDestination,
    QgsProcessingOutputNumber,
    QgsProcessingException,
)

from ..ml.detector import (
    onnx_available,
    load_model,
    detect_features,
    pixel_bbox_to_map_bbox,
    segment_raster,
)
from ..ml.segmentation_export import polygonise_labels, write_label_raster


class AiDetectionAlgorithm(QgsProcessingAlgorithm):
    """Run AI feature detection on a raster using a user-provided ONNX model."""

    INPUT = "INPUT"
    MODEL_FILE = "MODEL_FILE"
    LABEL_FILE = "LABEL_FILE"
    CONFIDENCE = "CONFIDENCE"
    IOU_THRESHOLD = "IOU_THRESHOLD"
    TILE_SIZE = "TILE_SIZE"
    MIN_SEGMENT_PIXELS = "MIN_SEGMENT_PIXELS"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_LABELS = "OUTPUT_LABELS"
    OUTPUT_COUNT = "OUTPUT_COUNT"

    def name(self):
        return "ai_feature_detection"

    def displayName(self):
        return "AI Feature Detection (ONNX Model)"

    def group(self):
        return "LiDAR Relief — AI/ML"

    def groupId(self):
        return "lidar_relief_ml"

    def shortHelpString(self):
        return (
            "Run object detection on a raster using a user-provided ONNX "
            "model (YOLO, SSD, etc.). Bounding boxes are written to a "
            "GeoPackage in the same CRS as the input raster.\n\n"
            "The plugin acts as an inference engine only — you must "
            "provide a pre-trained model in ONNX format.\n\n"
            "Supported model types (detected automatically from the "
            "model's output signature):\n"
            "  - Object detection (YOLOv5/v7/v8/v11, SSD) → bounding-box "
            "polygons\n"
            "  - Semantic segmentation (U-Net, SegFormer, DeepLab) → a "
            "class-index raster plus per-class polygons. Better suited to "
            "archaeology, where ditches, banks and field systems are "
            "linear or areal rather than box-shaped.\n\n"
            "Training your model:\n"
            "  1. Export your trained model to ONNX format\n"
            "  2. Create a labels.json file with class names\n"
            "  3. Provide both files to this algorithm\n\n"
            "Output is a vector layer with bounding boxes and "
            "confidence scores. The original pixel-space bbox is also "
            "stored in the 'bbox_pixels' attribute for debugging."
        )

    def createInstance(self):
        return AiDetectionAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(self.INPUT, "Input raster layer")
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.MODEL_FILE,
                "ONNX model file (.onnx)",
                fileFilter="ONNX model (*.onnx)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.LABEL_FILE,
                "Labels JSON file (optional)",
                fileFilter="JSON (*.json)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CONFIDENCE,
                "Confidence threshold",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=0.5,
                minValue=0.01,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.IOU_THRESHOLD,
                "IoU threshold (NMS)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=0.45,
                minValue=0.05,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TILE_SIZE,
                "Tile size (pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=640,
                minValue=128,
                maxValue=2048,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_SEGMENT_PIXELS,
                "Minimum segment size (pixels, segmentation models only)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=10,
                minValue=1,
                maxValue=100000,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_VECTOR,
                "Output detection layer (GeoPackage)",
                fileFilter="GeoPackage (*.gpkg)",
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT_LABELS,
                "Output class raster (segmentation models only)",
                optional=True,
                createByDefault=False,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(self.OUTPUT_COUNT, "Number of detections")
        )

    def processAlgorithm(self, parameters, context, feedback):
        if not onnx_available():
            raise QgsProcessingException(
                "AI detection requires 'onnxruntime'.\n\n"
                "Install via OSGeo4W Shell:\n"
                "  pip install onnxruntime"
            )

        raster = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if raster and raster.width() * raster.height() > 50000 * 50000:
            raise QgsProcessingException(
                "Raster is too large (> 2.5 billion pixels). Please clip the raster first."
            )
        model_path = self.parameterAsFile(parameters, self.MODEL_FILE, context)
        label_path = self.parameterAsFile(parameters, self.LABEL_FILE, context)
        confidence = self.parameterAsDouble(parameters, self.CONFIDENCE, context)
        iou = self.parameterAsDouble(parameters, self.IOU_THRESHOLD, context)
        tile_size = self.parameterAsInt(parameters, self.TILE_SIZE, context)
        output_path = self.parameterAsFileOutput(
            parameters, self.OUTPUT_VECTOR, context
        )

        if not model_path or not os.path.exists(model_path):
            raise QgsProcessingException(f"Model file not found: {model_path}")

        feedback.setProgressText("Loading ONNX model...")

        try:
            model = load_model(model_path, label_path)
        except Exception as e:
            raise QgsProcessingException(f"Failed to load model: {e}")

        feedback.pushInfo(
            f"Model: {os.path.basename(model_path)}\n"
            f"Type: {model['model_type']}\n"
            f"Labels: {model['labels'] or 'none'}"
        )

        if model["model_type"] == "semantic_segmentation":
            return self._run_segmentation(
                parameters,
                context,
                feedback,
                raster=raster,
                model=model,
                confidence=confidence,
                tile_size=tile_size,
                output_path=output_path,
            )

        feedback.setProgressText("Running inference...")

        try:
            result = detect_features(
                raster_path=raster.source(),
                model=model,
                confidence_threshold=confidence,
                iou_threshold=iou,
                tile_size=tile_size,
                feedback=feedback,
            )
        except Exception as e:
            raise QgsProcessingException(f"Inference failed: {e}")

        detections = result["detections"]
        count = result["detection_count"]

        feedback.pushInfo(
            f"Detections: {count}\nTiles processed: {result['total_tiles']}"
        )

        # Write detections to GeoPackage if any found
        if detections and output_path:
            geo_transform = result.get("geo_transform")
            projection = result.get("projection")
            if geo_transform is None:
                raise QgsProcessingException(
                    "Internal error: raster GeoTransform missing from detection "
                    "result. Cannot convert pixel-space bboxes to map coordinates."
                )
            _write_detections_gpkg(
                detections,
                output_path,
                raster.source(),
                geo_transform=geo_transform,
                projection=projection,
                feedback=feedback,
            )
            feedback.pushInfo(f"Output: {output_path}")

        return {
            self.OUTPUT_VECTOR: output_path or "",
            self.OUTPUT_COUNT: count,
        }

    def _run_segmentation(
        self,
        parameters,
        context,
        feedback,
        raster,
        model,
        confidence,
        tile_size,
        output_path,
    ):
        """Segment the raster and export a class raster plus polygons.

        Rules:
            The label raster is the primary evidence and the polygons are
            derived from it, so write the raster even when vectorisation
            yields nothing — an empty polygon layer plus a populated
            raster tells the user their min-size threshold was too high,
            whereas no output at all tells them nothing.
        """
        min_segment_pixels = self.parameterAsInt(
            parameters, self.MIN_SEGMENT_PIXELS, context
        )
        labels_output = self.parameterAsOutputLayer(
            parameters, self.OUTPUT_LABELS, context
        )

        feedback.setProgressText("Running segmentation inference...")
        try:
            result = segment_raster(
                raster_path=raster.source(),
                model=model,
                confidence_threshold=confidence,
                tile_size=tile_size,
                feedback=feedback,
            )
        except Exception as e:
            raise QgsProcessingException(f"Segmentation failed: {e}")

        if result["cancelled"]:
            return {}

        labels = result["labels"]
        class_counts = result["class_counts"]
        total_pixels = int(labels.size)

        summary = "\n".join(
            f"  class {cid}: {n} px ({100.0 * n / total_pixels:.2f}%)"
            for cid, n in sorted(class_counts.items())
        )
        feedback.pushInfo(f"Classes present:\n{summary}")

        if labels_output:
            try:
                write_label_raster(
                    labels,
                    labels_output,
                    result["geo_transform"],
                    result["projection"],
                )
                feedback.pushInfo(f"Class raster: {labels_output}")
            except Exception as e:
                raise QgsProcessingException(f"Failed to write class raster: {e}")

        polygon_count = 0
        if output_path:
            if os.path.exists(output_path):
                raise QgsProcessingException(
                    f"Output GeoPackage already exists: {output_path}. "
                    "Delete it first or choose a different output path."
                )
            try:
                polygon_count = polygonise_labels(
                    labels,
                    result["geo_transform"],
                    result["projection"],
                    output_path,
                    labels_map=model.get("labels"),
                    confidence=result["confidence"],
                    min_area_pixels=min_segment_pixels,
                    feedback=feedback,
                )
            except ValueError as e:
                raise QgsProcessingException(str(e))
            except Exception as e:
                raise QgsProcessingException(f"Failed to vectorise segments: {e}")

            feedback.pushInfo(
                f"Wrote {polygon_count} segment polygons to {output_path}"
            )
            if polygon_count == 0 and len(class_counts) > 1:
                feedback.pushWarning(
                    f"The model classified pixels but no segment reached the "
                    f"{min_segment_pixels}-pixel minimum. Lower 'Minimum "
                    f"segment size' to keep smaller features."
                )

        return {
            self.OUTPUT_VECTOR: output_path or "",
            self.OUTPUT_LABELS: labels_output or "",
            self.OUTPUT_COUNT: polygon_count,
        }


def _write_detections_gpkg(
    detections: list,
    output_path: str,
    raster_path: str,
    geo_transform: tuple | None = None,
    projection: str | None = None,
    feedback=None,
) -> None:
    """Write detection results to a GeoPackage vector layer.

    Detection bboxes are produced by the ML detector in **raster pixel
    coordinates**. This function converts them to map coordinates using
    the raster's GeoTransform (which the caller must supply). Without
    this conversion detections land hundreds of kilometres from where
    they were actually detected.

    Raises:
        QgsProcessingException: if ``output_path`` already exists (we refuse
            to silently destroy an existing GeoPackage) or if the raster
            has no CRS.
    """
    from qgis.core import QgsProcessingException
    from osgeo import ogr, osr, gdal

    # Refuse to silently destroy an existing GeoPackage. QGIS parameter
    # validation already asks the user to confirm overwrite for
    # QgsProcessingParameterFileDestination, but we double-check here
    # because this function is also called from batch pipelines.
    if os.path.exists(output_path):
        raise QgsProcessingException(
            f"Output GeoPackage already exists: {output_path}. "
            "Delete it first or choose a different output path."
        )

    driver = ogr.GetDriverByName("GPKG")
    ds = driver.CreateDataSource(output_path)
    if ds is None:
        raise RuntimeError(f"Failed to create GeoPackage: {output_path}")

    srs = osr.SpatialReference()
    # Prefer the projection explicitly passed in (from the detector
    # result dict) — falls back to opening the raster if missing.
    raster_wkt = projection
    if not raster_wkt:
        raster_ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
        if raster_ds:
            raster_wkt = raster_ds.GetProjection()
            raster_ds = None

    if raster_wkt:
        srs.ImportFromWkt(raster_wkt)
    else:
        # Previously this silently fell back to EPSG:4326, which placed
        # detections at wrong coordinates for any raster in a local CRS.
        # Refuse to write garbage instead.
        ds = None
        raise QgsProcessingException(
            "Input raster has no CRS (projection is empty). Refusing to "
            "write detections with an unknown coordinate system — they "
            "would be misplaced by potentially hundreds of kilometres. "
            "Please assign a CRS to the raster before running AI detection."
        )

    layer = ds.CreateLayer("detections", srs, ogr.wkbPolygon)

    # Create fields
    layer.CreateField(ogr.FieldDefn("class_name", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("confidence", ogr.OFTReal))
    layer.CreateField(ogr.FieldDefn("class_id", ogr.OFTInteger))
    # Persist the original pixel-space bbox for traceability/debugging.
    layer.CreateField(ogr.FieldDefn("bbox_pixels", ogr.OFTString))

    for det in detections:
        bbox_pixels = det.get("bbox")
        if not bbox_pixels or len(bbox_pixels) != 4:
            if feedback:
                feedback.reportError(
                    f"Skipping malformed detection (no 4-element bbox): {det}",
                    fatalError=False,
                )
            continue

        # Convert pixel-space bbox to map coordinates.
        if geo_transform is None:
            if feedback:
                feedback.reportError(
                    "Cannot convert detection bbox to map coordinates: "
                    "GeoTransform missing. Skipping detection.",
                    fatalError=False,
                )
            continue
        try:
            x1, y1, x2, y2 = pixel_bbox_to_map_bbox(bbox_pixels, geo_transform)
        except ValueError as e:
            if feedback:
                feedback.reportError(
                    f"Failed to convert bbox {bbox_pixels}: {e}",
                    fatalError=False,
                )
            continue

        # Skip degenerate polygons (zero area).
        if x2 <= x1 or y2 <= y1:
            continue

        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("class_name", det.get("class_name", "unknown"))
        feature.SetField("confidence", float(det.get("confidence", 0)))
        feature.SetField("class_id", int(det.get("class_id", 0)))
        feature.SetField(
            "bbox_pixels",
            ",".join(f"{v:.2f}" for v in bbox_pixels),
        )

        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(x1, y1)
        ring.AddPoint(x2, y1)
        ring.AddPoint(x2, y2)
        ring.AddPoint(x1, y2)
        ring.AddPoint(x1, y1)

        polygon = ogr.Geometry(ogr.wkbPolygon)
        polygon.AddGeometry(ring)
        feature.SetGeometry(polygon)
        layer.CreateFeature(feature)

    ds.FlushCache()
    ds = None
