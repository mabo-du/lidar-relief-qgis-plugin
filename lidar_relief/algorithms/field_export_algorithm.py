"""field_export_algorithm.py — QGIS Processing wrapper for Field Survey Export.

exports: FieldExportAlgorithm
used_by: provider.py → loadAlgorithms

rules:
  Packages relief rasters + anomaly detection points for QField/Mergin.
  Uses only QGIS Python API + GDAL (no external dependencies).
"""

import os
from datetime import datetime

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber,
    QgsProcessingException,
)

from ..export.field_packager import package_for_qfield
from .help_mixin import HelpUrlMixin


class FieldExportAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Package visualization rasters and anomaly points for QField/Mergin
    field survey validation."""

    HELP_ANCHOR = "package-for-field-survey-qfieldmergin"

    INPUT_RASTER = "INPUT_RASTER"
    INPUT_ANOMALIES = "INPUT_ANOMALIES"
    ANOMALY_ID_FIELD = "ANOMALY_ID_FIELD"
    CONFIDENCE_FIELD = "CONFIDENCE_FIELD"
    METHOD_FIELD = "METHOD_FIELD"
    PROJECT_NAME = "PROJECT_NAME"
    INCLUDE_RASTER = "INCLUDE_RASTER"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_ANOMALY_COUNT = "OUTPUT_ANOMALY_COUNT"

    def name(self):
        return "field_survey_export"

    def displayName(self):
        return "Package for Field Survey (QField/Mergin)"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def shortHelpString(self):
        return (
            "Packages a relief visualization raster and anomaly detection "
            "points into a GeoPackage + QGIS project for field validation "
            "in QField or Mergin Maps.\n\n"
            "The output GeoPackage uses a structured archaeological schema "
            "(anomaly_id, detection_method, confidence, feature_type, "
            "field_status, observer, photo_path, notes).\n\n"
            "Open the .qgs file in QField on your mobile device to navigate "
            "to anomalies in the field and record validation data."
        )

    def createInstance(self):
        return FieldExportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER, "Relief visualization raster"
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_ANOMALIES,
                "Anomaly points layer (optional)",
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.ANOMALY_ID_FIELD,
                "Anomaly ID field",
                parentLayerParameterName=self.INPUT_ANOMALIES,
                optional=True,
                type=QgsProcessingParameterField.DataType.Any,
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.CONFIDENCE_FIELD,
                "Confidence field (optional)",
                parentLayerParameterName=self.INPUT_ANOMALIES,
                optional=True,
                type=QgsProcessingParameterField.DataType.Numeric,
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.METHOD_FIELD,
                "Detection method field (optional)",
                parentLayerParameterName=self.INPUT_ANOMALIES,
                optional=True,
                type=QgsProcessingParameterField.DataType.Any,
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.PROJECT_NAME,
                "Survey project name",
                defaultValue="LiDAR Survey",
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_RASTER,
                "Copy raster into package (vs. reference)",
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                "Output directory",
            )
        )

        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_ANOMALY_COUNT, "Number of anomalies packaged"
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        raster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        if raster is None:
            raise QgsProcessingException("Input raster layer is required.")

        anomaly_layer = self.parameterAsVectorLayer(
            parameters, self.INPUT_ANOMALIES, context
        )
        project_name = self.parameterAsString(parameters, self.PROJECT_NAME, context)
        if not project_name or project_name == "LiDAR Survey":
            project_name = f"LiDAR Survey {datetime.now().strftime('%Y-%m-%d')}"
        include_raster = self.parameterAsBoolean(
            parameters, self.INCLUDE_RASTER, context
        )
        output_dir = self.parameterAsFileOutput(parameters, self.OUTPUT_DIR, context)

        if not output_dir:
            output_dir = os.path.join(
                os.path.dirname(raster.source()),
                f"{project_name.lower().replace(' ', '_')}_field_package",
            )

        # Extract anomaly points from vector layer
        anomaly_points = []
        if anomaly_layer is not None:
            id_field = self.parameterAsString(
                parameters, self.ANOMALY_ID_FIELD, context
            )
            conf_field = self.parameterAsString(
                parameters, self.CONFIDENCE_FIELD, context
            )
            method_field = self.parameterAsString(
                parameters, self.METHOD_FIELD, context
            )

            features = list(anomaly_layer.getFeatures())
            feedback.setProgressText(f"Processing {len(features)} anomaly features...")

            for i, feat in enumerate(features):
                if feedback.isCanceled():
                    return {}

                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue

                point = geom.centroid().asPoint()
                if point is None:
                    continue

                anom_idx = i + 1
                record = {
                    "x": point.x(),
                    "y": point.y(),
                    "anomaly_id": (
                        str(feat[id_field])
                        if id_field and id_field in feat.fields().names()
                        else f"ANOM-{anom_idx:04d}"
                    ),
                    "confidence": (
                        float(feat[conf_field])
                        if conf_field and conf_field in feat.fields().names()
                        else 0.5
                    ),
                    "detection_method": (
                        str(feat[method_field])
                        if method_field and method_field in feat.fields().names()
                        else "manual"
                    ),
                    "feature_type": "unknown",
                    "field_status": "pending",
                }
                anomaly_points.append(record)

                if i % 100 == 0:
                    feedback.setProgress(int(100 * i / max(len(features), 1)))
        else:
            feedback.pushWarning(
                "No anomaly layer provided. Creating template GeoPackage "
                "only — add points in QField."
            )

        feedback.setProgressText("Packaging for field survey...")

        try:
            result = package_for_qfield(
                raster_path=raster.source(),
                anomaly_points=anomaly_points or [],
                output_dir=output_dir,
                project_name=project_name,
                crs=raster.crs().authid() if raster.crs() else None,
                include_raster_copy=include_raster,
            )
        except Exception as e:
            raise QgsProcessingException(f"Field packaging failed: {e}")

        feedback.pushInfo(
            f"Survey package created: {result['gpkg']}\n"
            f"Anomalies: {result['anomaly_count']}\n"
            f"QGIS project: {result['qgs']}\n\n"
            "To use in the field:\n"
            "1. Copy the output directory to your mobile device\n"
            "2. Open the .qgs file in QField\n"
            "3. Navigate to each anomaly and update the field_status"
        )

        return {
            self.OUTPUT_DIR: output_dir,
            self.OUTPUT_ANOMALY_COUNT: result["anomaly_count"],
        }
