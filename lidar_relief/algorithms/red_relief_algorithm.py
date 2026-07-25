"""red_relief_algorithm.py — QGIS Processing wrapper for Simple Red Relief.
exports: RedReliefAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.blend
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    process_in_tiles,
)
from ..core.blend import simple_red_relief
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class RedReliefAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Simple Red Relief Composite."""

    INPUT = "INPUT"
    RADIUS = "RADIUS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "simple_red_relief"

    def displayName(self):
        return "Simple Red Relief Composite"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Simple Red Relief Composite. "
            "Blends Simple Local Relief Model (SLRM) and Slope "
            "to create a visualization that highlights micro-topography."
        )

    def createInstance(self):
        return RedReliefAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RADIUS,
                "SLRM Smoothing radius (pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=20,
                minValue=2,
                maxValue=500,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Red Relief output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        int_radius = self.parameterAsInt(parameters, self.RADIUS, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing Simple Red Relief in tiles...")

        def red_relief_wrapper(block, cellsize, slrm_radius):
            return simple_red_relief(block, cellsize, slrm_radius, feedback)

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=red_relief_wrapper,
            halo_size=int_radius,
            tile_size=2048,
            feedback=feedback,
            slrm_radius=int_radius,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
