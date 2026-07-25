"""asvf_algorithm.py — QGIS Processing wrapper for ASVF.
exports: AsvfAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.asvf
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import get_cell_size_from_path, process_in_tiles
from ..core.asvf import anisotropic_sky_view_factor
from ..core.scale import RADIUS_UNIT_OPTIONS, RADIUS_UNIT_VALUES, resolve_radius
from ..styling import ReliefLayerPostProcessor


class AsvfAlgorithm(QgsProcessingAlgorithm):
    """Anisotropic Sky-View Factor algorithm."""

    INPUT = "INPUT"
    DIRECTIONS = "DIRECTIONS"
    RADIUS = "RADIUS"
    RADIUS_UNITS = "RADIUS_UNITS"
    ANISOTROPY_DIR = "ANISOTROPY_DIR"
    ANISOTROPY_WEIGHT = "ANISOTROPY_WEIGHT"
    NOISE = "NOISE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "asvf"

    def displayName(self):
        return "Anisotropic Sky-View Factor (ASVF)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Anisotropic Sky-View Factor (ASVF) modifies the standard SVF "
            "by applying a directional weight, simulating anisotropic lighting "
            "conditions (e.g., strong NW illumination)."
        )

    def createInstance(self):
        return AsvfAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DIRECTIONS,
                "Number of search directions",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=16,
                minValue=4,
                maxValue=64,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RADIUS,
                "Search radius",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=10,
                minValue=0.1,
                maxValue=1000,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.RADIUS_UNITS,
                "Search radius units",
                options=RADIUS_UNIT_OPTIONS,
                defaultValue=0,  # index 0 → pixels, preserving old behaviour
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ANISOTROPY_DIR,
                "Anisotropy Direction (degrees)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=315.0,
                minValue=0.0,
                maxValue=360.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ANISOTROPY_WEIGHT,
                "Anisotropy Weight (0.0 to 1.0)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=0.5,
                minValue=0.0,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.NOISE,
                "Noise reduction (1D look-ahead)",
                options=["None (0)", "Low (1)", "Medium (2)", "High (3)"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "ASVF output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        int_directions = self.parameterAsInt(parameters, self.DIRECTIONS, context)
        float_radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        int_units_index = self.parameterAsEnum(parameters, self.RADIUS_UNITS, context)
        int_radius = resolve_radius(
            float_radius,
            RADIUS_UNIT_VALUES[int_units_index],
            get_cell_size_from_path(source.source()),
            "ASVF search radius",
            feedback,
        )
        float_dir = self.parameterAsDouble(parameters, self.ANISOTROPY_DIR, context)
        float_weight = self.parameterAsDouble(
            parameters, self.ANISOTROPY_WEIGHT, context
        )
        int_noise = self.parameterAsEnum(parameters, self.NOISE, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing ASVF in tiles...")

        def asvf_wrapper(block, cellsize, dirs, radius, a_dir, a_weight, noise):
            return anisotropic_sky_view_factor(
                block, cellsize, dirs, radius, a_dir, a_weight, noise, feedback
            )

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=asvf_wrapper,
            halo_size=int_radius,
            tile_size=2048,
            feedback=feedback,
            dirs=int_directions,
            radius=int_radius,
            a_dir=float_dir,
            a_weight=float_weight,
            noise=int_noise,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor("ASVF", stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
