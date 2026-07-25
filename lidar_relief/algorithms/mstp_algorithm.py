"""mstp_algorithm.py — QGIS Processing wrapper for Multi-Scale Topographic Position.
exports: MstpAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  output is a multiband raster (3 bands, Byte)
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
from ..core.mstp import multi_scale_topographic_position
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class MstpAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Multi-Scale Topographic Position from a DEM."""

    INPUT = "INPUT"
    LOCAL_RADIUS = "LOCAL_RADIUS"
    MESO_RADIUS = "MESO_RADIUS"
    BROAD_RADIUS = "BROAD_RADIUS"
    LIGHTNESS = "LIGHTNESS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "mstp"

    def displayName(self):
        return "Multi-Scale Topographic Position (MSTP)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Generates an RGB composite of Topographic Position at three scales. "
            "Broad scale (Red) highlights large landforms. "
            "Meso scale (Green) highlights medium features. "
            "Local scale (Blue) highlights micro-topography like walls and ditches."
        )

    def createInstance(self):
        return MstpAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LOCAL_RADIUS,
                "Local Scale Radius (pixels) -> Blue",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=5,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MESO_RADIUS,
                "Meso Scale Radius (pixels) -> Green",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=50,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BROAD_RADIUS,
                "Broad Scale Radius (pixels) -> Red",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=500,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LIGHTNESS,
                "Lightness/Contrast Multiplier",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "MSTP (RGB) output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        local_r = self.parameterAsInt(parameters, self.LOCAL_RADIUS, context)
        meso_r = self.parameterAsInt(parameters, self.MESO_RADIUS, context)
        broad_r = self.parameterAsInt(parameters, self.BROAD_RADIUS, context)
        lightness = self.parameterAsDouble(parameters, self.LIGHTNESS, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing MSTP in tiles...")

        def mstp_wrapper(block, cellsize, local_r, meso_r, broad_r, lightness):
            return multi_scale_topographic_position(
                block, local_r, meso_r, broad_r, lightness, feedback
            )

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=mstp_wrapper,
            halo_size=broad_r,
            tile_size=2048,
            feedback=feedback,
            local_r=local_r,
            meso_r=meso_r,
            broad_r=broad_r,
            lightness=lightness,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
