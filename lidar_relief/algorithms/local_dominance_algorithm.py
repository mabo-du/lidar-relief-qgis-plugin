"""local_dominance_algorithm.py — QGIS Processing wrapper for Local Dominance.
exports: LocalDominanceAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.local_dominance
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import process_in_tiles
from ..core.local_dominance import compute_local_dominance
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class LocalDominanceAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Local Dominance algorithm."""

    INPUT = "INPUT"
    MIN_RAD = "MIN_RAD"
    MAX_RAD = "MAX_RAD"
    ANGLR_RES = "ANGLR_RES"
    OBSERVER_H = "OBSERVER_H"
    OUTPUT = "OUTPUT"

    def name(self):
        return "local_dominance"

    def displayName(self):
        return "Local Dominance"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Local Dominance uses horizon-scanning ray trace to determine whether "
            "a pixel is locally dominant (mound, ridge) or dominated (ditch). "
            "Outputs normalized byte values [0-255]."
        )

    def createInstance(self):
        return LocalDominanceAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_RAD,
                "Minimum search radius (pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=10,
                minValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_RAD,
                "Maximum search radius (pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=20,
                minValue=2,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ANGLR_RES,
                "Angular resolution (degrees)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=15.0,
                minValue=1.0,
                maxValue=90.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OBSERVER_H,
                "Observer height (map units)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.7,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Local Dominance output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        int_min_rad = self.parameterAsInt(parameters, self.MIN_RAD, context)
        int_max_rad = self.parameterAsInt(parameters, self.MAX_RAD, context)
        float_anglr_res = self.parameterAsDouble(parameters, self.ANGLR_RES, context)
        float_observer_h = self.parameterAsDouble(parameters, self.OBSERVER_H, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing Local Dominance in tiles...")

        def ld_wrapper(block, cellsize):
            return compute_local_dominance(
                block,
                cellsize,
                min_rad=int_min_rad,
                max_rad=int_max_rad,
                anglr_res=float_anglr_res,
                observer_h=float_observer_h,
                feedback=feedback,
            )

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=ld_wrapper,
            halo_size=int_max_rad,
            tile_size=2048,
            feedback=feedback,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            # Local Dominance now returns degrees, not a 0-255 byte scale,
            # so use the same std-dev stretch as the other angular
            # visualisations. A min/max stretch would let one outlier
            # cell flatten the rest of the image.
            details.setPostProcessor(
                ReliefLayerPostProcessor("Local Dominance", stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
