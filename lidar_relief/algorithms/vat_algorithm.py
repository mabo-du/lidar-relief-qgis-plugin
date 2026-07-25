"""vat_algorithm.py — QGIS Processing wrapper for VAT Composite.
exports: VatAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.vat
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
from ..core.vat import compute_vat
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class VatAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Visualisation for Archaeological Topography (VAT)."""

    INPUT = "INPUT"
    SVF_RADIUS = "SVF_RADIUS"
    OPENNESS_RADIUS = "OPENNESS_RADIUS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "vat_composite"

    def displayName(self):
        return "VAT Composite"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Visualisation for Archaeological Topography (VAT). "
            "Blends Hillshade, Slope, Positive Openness, and SVF "
            "into a single composite highlighting both macro and micro topography."
        )

    def createInstance(self):
        return VatAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SVF_RADIUS,
                "SVF Search Radius (pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=50,
                minValue=1,
                maxValue=500,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OPENNESS_RADIUS,
                "Openness Search Radius (pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=50,
                minValue=1,
                maxValue=500,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "VAT output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        svf_r = self.parameterAsInt(parameters, self.SVF_RADIUS, context)
        openness_r = self.parameterAsInt(parameters, self.OPENNESS_RADIUS, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        halo_size = max(svf_r, openness_r)

        feedback.setProgressText("Computing VAT Composite in tiles...")

        def vat_wrapper(block, cellsize, svf_radius, openness_radius):
            return compute_vat(block, cellsize, svf_radius, openness_radius, feedback)

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=vat_wrapper,
            halo_size=halo_size,
            tile_size=2048,
            feedback=feedback,
            svf_radius=svf_r,
            openness_radius=openness_r,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
