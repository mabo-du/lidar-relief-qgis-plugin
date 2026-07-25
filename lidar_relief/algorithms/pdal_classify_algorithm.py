"""pdal_classify_algorithm.py — QGIS Processing wrapper for PDAL pipelines.

exports: PdalClassifyAlgorithm
used_by: provider.py → loadAlgorithms

rules:
  - Wraps point_cloud.pdal_pipeline.build_pipeline / run_pipeline.
  - All pipelines use the archaeology-tuned presets defined in
    point_cloud/pdal_pipeline.ARCHAEOLOGY_PIPELINES.
  - Output is either a DEM GeoTIFF (default) or a classified LAS file.
  - Refuses to overwrite existing output files.
  - Provides cancellation feedback to the user.
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFileDestination,
    # NOTE: this is an output (algo result), not an input parameter, so the
    # `Parameter` prefix is wrong. `QgsProcessingOutputString` has shipped
    # with QGIS Processing since the QGIS 3.0 API rewrite (2018) and works
    # across 3.x and 4.x.  Using `QgsProcessingParameterOutputString` here
    # produced an ImportError on QGIS 4.0.3 (and would on any 3.x install)
    # because that name does not exist in qgis.core.
    QgsProcessingOutputString,
    QgsProcessingException,
)

from ..point_cloud.pdal_pipeline import (
    pdal_available,
    build_pipeline,
    run_pipeline,
    ARCHAEOLOGY_PIPELINES,
)
from .help_mixin import HelpUrlMixin

PRESET_NAMES = list(ARCHAEOLOGY_PIPELINES.keys())
PRESET_LABELS = [
    f"{name} — {ARCHAEOLOGY_PIPELINES[name]['description']}" for name in PRESET_NAMES
]


class PdalClassifyAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Classify ground points from LAS/LAZ using archaeology-tuned PDAL pipelines."""

    HELP_ANCHOR = "point-cloud-processing"

    INPUT = "INPUT"
    PRESET = "PRESET"
    RESOLUTION = "RESOLUTION"
    OUTPUT_FORMAT = "OUTPUT_FORMAT"
    OUTPUT = "OUTPUT"
    OUTPUT_STATS = "OUTPUT_STATS"

    def name(self):
        return "pdal_classify"

    def displayName(self):
        return "PDAL Ground Classification (LAS/LAZ → DEM/LAS)"

    def group(self):
        return "LiDAR Relief — Point Cloud"

    def groupId(self):
        return "lidar_relief_point_cloud"

    def shortHelpString(self):
        return (
            "Classify ground points from a LAS/LAZ point cloud using a "
            "PDAL pipeline tuned for archaeological applications.\n\n"
            "Four presets are available:\n"
            "  - PMF Archaeology Fine: maximum micro-relief preservation\n"
            "  - PMF Archaeology Standard: balanced for most surveys\n"
            "  - PMF Forested: aggressive ground detection for dense canopy\n"
            "  - Outlier Removal: pre-processing noise removal (outputs LAS)\n\n"
            "Output is either a DEM GeoTIFF (IDW interpolation of ground "
            "points) or a classified LAS file depending on the Output "
            "Format parameter.\n\n"
            "Requires the 'pdal' Python package and a working PDAL "
            "installation."
        )

    def createInstance(self):
        return PdalClassifyAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                "Input LAS/LAZ file",
                fileFilter="LiDAR data (*.las *.laz)",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PRESET,
                "Pipeline preset",
                options=PRESET_LABELS,
                defaultValue=1,  # pmf_archaeology_standard
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RESOLUTION,
                "Output DEM cell size (map units, ignored for LAS output)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.0,
                minValue=0.1,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                "Output format",
                options=["GeoTIFF DEM (IDW)", "Classified LAS"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                "Output file",
                fileFilter="GeoTIFF (*.tif);;LAS (*.las)",
            )
        )
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_STATS, "Processing stats"))

    def processAlgorithm(self, parameters, context, feedback):
        if not pdal_available():
            raise QgsProcessingException(
                "PDAL classification requires the 'pdal' Python package.\n\n"
                "Install it via the OSGeo4W Shell:\n"
                "  pip install pdal\n\n"
                "PDAL also needs to be installed on your system."
            )

        las_path = self.parameterAsFile(parameters, self.INPUT, context)
        if not las_path or not os.path.exists(las_path):
            raise QgsProcessingException(f"LAS/LAZ file not found: {las_path}")

        preset_idx = self.parameterAsEnum(parameters, self.PRESET, context)
        preset = PRESET_NAMES[preset_idx]
        resolution = self.parameterAsDouble(parameters, self.RESOLUTION, context)
        output_format_idx = self.parameterAsEnum(
            parameters, self.OUTPUT_FORMAT, context
        )
        output_format = "gdal" if output_format_idx == 0 else "las"
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        # Refuse to silently destroy an existing output file.
        if output_path and os.path.exists(output_path):
            raise QgsProcessingException(
                f"Output file already exists: {output_path}. "
                f"Delete it first or choose a different output path."
            )

        feedback.setProgressText(f"Building PDAL pipeline ({preset})...")

        try:
            pipeline_json = build_pipeline(
                las_path=las_path,
                output_path=output_path,
                preset=preset,
                resolution=resolution,
                output_format=output_format,
            )
        except Exception as e:
            raise QgsProcessingException(f"Failed to build PDAL pipeline: {e}")

        if feedback.isCanceled():
            return {}

        feedback.setProgressText("Executing PDAL pipeline...")
        try:
            result = run_pipeline(pipeline_json, feedback=feedback)
        except Exception as e:
            raise QgsProcessingException(f"PDAL pipeline execution failed: {e}")

        if feedback.isCanceled():
            return {}

        if not os.path.exists(output_path):
            raise QgsProcessingException(
                f"PDAL pipeline completed but output file was not created: "
                f"{output_path}. Check the PDAL pipeline JSON for errors."
            )

        stats = (
            f"Pipeline preset: {preset}\n"
            f"Points processed: {result.get('point_count', 0)}\n"
            f"Stages: {result.get('stage_count', 0)}\n"
            f"Output: {output_path}\n"
        )
        feedback.pushInfo(stats)

        # Apply auto-styling post-processor to DEM outputs (not LAS).
        # The v2.0.4 changelog promised "output layers are now auto-styled
        # correctly" but PDAL DEM outputs were missed.
        if output_format == "gdal" and context.willLoadLayerOnCompletion(output_path):
            from ..styling import ReliefLayerPostProcessor

            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {
            self.OUTPUT: output_path,
            self.OUTPUT_STATS: stats,
        }
