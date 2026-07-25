"""ml_export_algorithm.py — QGIS Processing wrapper for ML-Ready Export (VRT Stack).
exports: MlExportAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  uses GDAL to build a VRT stack from multiple input layers
"""

import os
from osgeo import gdal
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterBoolean,
    QgsProcessing,
)
from .help_mixin import HelpUrlMixin

# Note: do NOT call gdal.UseExceptions() at module import time.
# The v2.0.5 changelog promised "Removed global GDAL exceptions" — that
# cleanup was applied to core/raster_utils.py but missed this file.
# Calling gdal.UseExceptions() globally affects every other plugin and
# QGIS itself, which can break code that relies on GDAL's default
# behaviour of returning None on error instead of raising.


class MlExportAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Machine Learning Export algorithm."""

    INPUTS = "INPUTS"
    SEPARATE = "SEPARATE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "ml_export"

    def displayName(self):
        return "ML-Ready Export (VRT Stack)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Builds a Virtual Raster (VRT) stack from multiple selected raster layers. "
            "This is useful for exporting a multi-band image for Machine Learning "
            "purposes without duplicating the raster data on disk."
        )

    def createInstance(self):
        return MlExportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.INPUTS,
                "Input raster layers",
                layerType=QgsProcessing.SourceType.TypeRaster,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SEPARATE,
                "Stack as separate bands (Required for VRT stacks)",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                "Output VRT file",
                "Virtual Raster (*.vrt)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        input_layers = self.parameterAsLayerList(parameters, self.INPUTS, context)
        separate = self.parameterAsBoolean(parameters, self.SEPARATE, context)
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        if not input_layers:
            feedback.reportError("No input layers selected.")
            return {}

        # Extract paths
        layer_paths = []
        for layer in input_layers:
            source = layer.source()
            if os.path.exists(source):
                layer_paths.append(source)
            else:
                feedback.reportError(f"Layer source does not exist on disk: {source}")

        if not layer_paths:
            feedback.reportError("No valid file paths found for inputs.")
            return {}

        feedback.setProgressText(f"Building VRT stack for {len(layer_paths)} layers...")

        try:
            # Build VRT
            vrt_options = gdal.BuildVRTOptions(separate=separate)
            vrt = gdal.BuildVRT(output_path, layer_paths, options=vrt_options)
            if vrt is None:
                raise RuntimeError(
                    "GDAL BuildVRT returned None. Verify that the output path is writable and input files are valid."
                )
            vrt.FlushCache()
            vrt = None
        except Exception as e:
            feedback.reportError(f"GDAL BuildVRT failed: {str(e)}")
            return {}

        return {self.OUTPUT: output_path}
