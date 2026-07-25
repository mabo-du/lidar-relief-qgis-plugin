"""blend_algorithm.py — QGIS Processing wrapper for Raster Blending.
exports: BlendAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    read_dem_to_array,
    write_array_to_raster,
)
from ..core.blend import blend_rasters
from ..styling import ReliefLayerPostProcessor
import numpy as np
from .help_mixin import HelpUrlMixin


class BlendAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Blends two raster layers."""

    INPUT_A = "INPUT_A"
    INPUT_B = "INPUT_B"
    BLEND_MODE = "BLEND_MODE"
    OPACITY = "OPACITY"
    OUTPUT = "OUTPUT"

    def name(self):
        return "blend_rasters"

    def displayName(self):
        return "Blend Visualizations"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Blends two visualization rasters (e.g., Hillshade and SVF) "
            "using standard blending modes like Multiply, Screen, or Overlay."
        )

    def createInstance(self):
        return BlendAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_A,
                "Base Layer (e.g. Hillshade)",
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_B,
                "Blend Layer (e.g. SVF, SLRM)",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.BLEND_MODE,
                "Blend Mode",
                options=["Multiply", "Screen", "Overlay", "Soft Light"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OPACITY,
                "Opacity (0.0 to 1.0)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.0,
                minValue=0.0,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Blended output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source_a = self.parameterAsRasterLayer(parameters, self.INPUT_A, context)
        source_b = self.parameterAsRasterLayer(parameters, self.INPUT_B, context)
        mode_idx = self.parameterAsEnum(parameters, self.BLEND_MODE, context)
        opacity = self.parameterAsDouble(parameters, self.OPACITY, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        mode_str = ["multiply", "screen", "overlay", "soft_light"][mode_idx]

        # Validate that the two rasters share CRS and extent before
        # blending. The previous code only checked shape match — two
        # rasters with identical dimensions but different projections
        # would be silently blended, producing garbage output.
        if source_a is None or source_b is None:
            raise QgsProcessingException("Both input rasters must be valid layers.")
        crs_a = source_a.crs()
        crs_b = source_b.crs()
        if crs_a is None or crs_b is None:
            feedback.pushWarning(
                "One or both input rasters have no CRS — blend results may "
                "be misaligned if the rasters are in different projections."
            )
        elif crs_a.authid() != crs_b.authid():
            raise QgsProcessingException(
                f"Input rasters have different CRSes: "
                f"layer A is {crs_a.authid()}, layer B is {crs_b.authid()}. "
                f"Please reproject one of the layers to match the other "
                f"before blending."
            )

        ext_a = source_a.extent()
        ext_b = source_b.extent()
        # Allow tiny floating-point differences in extent (sub-pixel).
        tolerance = 1e-6 * max(
            ext_a.width(), ext_a.height(), ext_b.width(), ext_b.height(), 1.0
        )
        extents_aligned = all(
            (
                abs(ext_a.xMinimum() - ext_b.xMinimum()) <= tolerance,
                abs(ext_a.yMinimum() - ext_b.yMinimum()) <= tolerance,
                abs(ext_a.xMaximum() - ext_b.xMaximum()) <= tolerance,
                abs(ext_a.yMaximum() - ext_b.yMaximum()) <= tolerance,
            )
        )
        if not extents_aligned:
            raise QgsProcessingException(
                f"Input rasters have different extents. Please align them "
                f"(e.g. via 'Align rasters' tool) before blending.\n"
                f"  Layer A: {ext_a.toString()}\n"
                f"  Layer B: {ext_b.toString()}"
            )

        feedback.setProgressText("Reading Base Layer...")
        data_a = read_dem_to_array(source_a.source(), feedback)

        feedback.setProgressText("Reading Blend Layer...")
        data_b = read_dem_to_array(source_b.source(), feedback)

        if feedback.isCanceled():
            return {}

        if data_a.array.shape != data_b.array.shape:
            feedback.reportError("Input rasters must have the same dimensions.")
            return {}

        # Scale inputs if they are not 0-255 (e.g. SVF is 0-1, SLRM is negative/positive)
        # SVF is typically [0, 1]. Multiply by 255.
        arr_b = data_b.array
        b_min = np.nanmin(arr_b) if np.isfinite(arr_b).any() else 0.0
        b_max = np.nanmax(arr_b) if np.isfinite(arr_b).any() else 0.0
        if (b_max > b_min and b_max <= 1.0 and b_min >= 0.0) or (
            b_max == b_min and 0.0 < b_min < 1.0
        ):
            arr_b = arr_b * 255.0

        # SLRM could be -5 to 5. We should stretch to 0-255 if it has negative values.
        if np.nanmin(arr_b) < 0:
            min_val = np.nanmin(arr_b)
            max_val = np.nanmax(arr_b)
            if max_val > min_val:
                arr_b = (arr_b - min_val) / (max_val - min_val) * 255.0
            else:
                arr_b = np.full_like(arr_b, 127.0)

        arr_a = data_a.array
        a_min = np.nanmin(arr_a) if np.isfinite(arr_a).any() else 0.0
        a_max = np.nanmax(arr_a) if np.isfinite(arr_a).any() else 0.0
        if (a_max > a_min and a_max <= 1.0 and a_min >= 0.0) or (
            a_max == a_min and 0.0 < a_min < 1.0
        ):
            arr_a = arr_a * 255.0

        feedback.setProgressText(f"Blending layers using {mode_str}...")
        blended = blend_rasters(arr_a, arr_b, mode_str, opacity, feedback)

        if feedback.isCanceled():
            return {}

        feedback.setProgressText("Writing output...")
        write_array_to_raster(
            blended,
            output_path,
            data_a.geotransform,
            data_a.projection,
            data_a.nodata,
        )

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
