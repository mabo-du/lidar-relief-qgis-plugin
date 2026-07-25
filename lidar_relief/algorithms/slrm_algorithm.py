"""slrm_algorithm.py — QGIS Processing wrapper for Simple Local Relief Model.
exports: SlrmAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.slrm
  check feedback.isCanceled() between major steps
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterEnum,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    get_cell_size_from_path,
    process_in_tiles,
)
from ..core.scale import RADIUS_UNIT_OPTIONS, RADIUS_UNIT_VALUES, resolve_radius
from ..core.slrm import simple_local_relief_model
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin
from .provenance_mixin import ProvenanceMixin


class SlrmAlgorithm(ProvenanceMixin, HelpUrlMixin, QgsProcessingAlgorithm):
    """Simple Local Relief Model — removes large-scale topography."""

    HELP_ANCHOR = "choosing-a-search-radius"

    INPUT = "INPUT"
    RADIUS = "RADIUS"
    RADIUS_UNITS = "RADIUS_UNITS"
    OUTPUT = "OUTPUT"

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "simple_local_relief_model"

    def displayName(self):
        return "Simple Local Relief Model (SLRM)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Computes a Simple Local Relief Model by subtracting a "
            "smoothed (low-pass) version of the DEM from the original. "
            "This highlights micro-relief features such as ditches, "
            "banks, and ridge-and-furrow while suppressing broad "
            "topographic trends."
        )

    def createInstance(self):
        return SlrmAlgorithm()

    # -- parameters ---------------------------------------------------------

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
                "Smoothing radius",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=20,
                minValue=0.2,
                maxValue=2000,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.RADIUS_UNITS,
                "Smoothing radius units",
                options=RADIUS_UNIT_OPTIONS,
                defaultValue=0,  # index 0 → pixels, preserving old behaviour
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "SLRM output",
            )
        )

    # -- processing ---------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        """Run Simple Local Relief Model.

        Rules:
            Abort gracefully on cancel.
        """
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        float_radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        int_units_index = self.parameterAsEnum(parameters, self.RADIUS_UNITS, context)
        # SLRM's minimum useful radius is 2 px — a 1 px box filter would
        # subtract the surface from itself and return a flat zero raster.
        int_radius = resolve_radius(
            float_radius,
            RADIUS_UNIT_VALUES[int_units_index],
            get_cell_size_from_path(source.source()),
            "SLRM smoothing radius",
            feedback,
            minimum=2,
        )
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing Simple Local Relief Model in tiles...")

        def slrm_wrapper(block, cellsize, radius):
            return simple_local_relief_model(block, radius)

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=slrm_wrapper,
            halo_size=int_radius,
            tile_size=2048,
            feedback=feedback,
            radius=int_radius,
        )

        if feedback.isCanceled():
            return {}

        self.record_provenance(
            output_path,
            parameters={
                "trend_radius_pixels": int_radius,
                "trend_radius_input": float_radius,
                "radius_units": RADIUS_UNIT_VALUES[int_units_index],
            },
            source_path=source.source(),
            feedback=feedback,
        )

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
