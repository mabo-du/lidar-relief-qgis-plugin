"""hillshade_algorithm.py — QGIS Processing wrapper for multi-directional hillshade.
exports: HillshadeAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.hillshade
  check feedback.isCanceled() between major steps
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    process_in_tiles,
)
from ..core.hillshade import multidirectional_hillshade
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class HillshadeAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Multi-directional hillshade from a DEM raster layer."""

    INPUT = "INPUT"
    AZIMUTHS = "AZIMUTHS"
    ALTITUDE = "ALTITUDE"
    OUTPUT = "OUTPUT"

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "multidirectional_hillshade"

    def displayName(self):
        return "Multi-directional Hillshade"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Generates a multi-directional hillshade by blending "
            "hillshades from several sun azimuth angles. Useful for "
            "revealing subtle topographic features that a single-"
            "direction hillshade would miss."
        )

    def createInstance(self):
        return HillshadeAlgorithm()

    # -- parameters ---------------------------------------------------------

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.AZIMUTHS,
                "Sun azimuth angles (comma-separated degrees)",
                defaultValue="315,45,135,225,270,360",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALTITUDE,
                "Sun altitude (degrees)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=45.0,
                minValue=0.0,
                maxValue=90.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Hillshade output",
            )
        )

    # -- processing ---------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        """Run multi-directional hillshade.

        Rules:
            Parse AZIMUTHS as comma-separated floats.
            Abort gracefully on cancel.
        """
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        azimuths_str = self.parameterAsString(parameters, self.AZIMUTHS, context)
        float_altitude = self.parameterAsDouble(parameters, self.ALTITUDE, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        # Parse azimuths
        try:
            list_float_azimuths = [
                float(a.strip()) for a in azimuths_str.split(",") if a.strip()
            ]
        except ValueError:
            from qgis.core import QgsProcessingException

            raise QgsProcessingException(
                f"Failed to parse sun azimuth angles string: {azimuths_str!r}. "
                f"Please provide a comma-separated list of numbers (e.g. '315, 45, 135')."
            )

        feedback.setProgressText("Computing multi-directional hillshade in tiles...")

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=multidirectional_hillshade,
            halo_size=1,
            tile_size=2048,
            feedback=feedback,
            azimuths=list_float_azimuths,
            altitude=float_altitude,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
