"""slope_algorithm.py — QGIS Processing wrapper for Slope computation.
exports: SlopeAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.slope
  enum index maps to ['degrees', 'percent']
  check feedback.isCanceled() between major steps
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    process_in_tiles,
)
from ..core.slope import compute_slope
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class SlopeAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Slope — terrain gradient in degrees or percent."""

    INPUT = "INPUT"
    UNITS = "UNITS"
    METHOD = "METHOD"
    OUTPUT = "OUTPUT"

    _UNIT_OPTIONS = ["Degrees", "Percent"]
    _UNIT_VALUES = ["degrees", "percent"]

    _METHOD_OPTIONS = [
        "Horn's 3×3 (default, QGIS/ArcGIS)",
        "Finite difference (rvt-py / ESRI legacy)",
    ]
    _METHOD_VALUES = ["horn", "finite_difference"]

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "slope"

    def displayName(self):
        return "Slope"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Computes terrain slope from a DEM. Output can be in "
            "degrees (0–90) or percent (0–∞). Slope highlights "
            "edges of features such as banks, scarps, and walls.\n\n"
            "Two gradient methods are available:\n"
            "  - Horn's 3×3 (default): standard QGIS/ArcGIS method. "
            "Smoother on noisy data.\n"
            "  - Finite difference: matches rvt-py and ESRI's older "
            "tools. Sharper on noisy data. Use this if you need to "
            "compare against ESRI outputs."
        )

    def createInstance(self):
        return SlopeAlgorithm()

    # -- parameters ---------------------------------------------------------

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.UNITS,
                "Output units",
                options=self._UNIT_OPTIONS,
                defaultValue=0,  # Degrees
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.METHOD,
                "Gradient method",
                options=self._METHOD_OPTIONS,
                defaultValue=0,  # Horn's
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Slope output",
            )
        )

    # -- processing ---------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        """Run slope computation.

        Rules:
            Map enum index to unit string via _UNIT_VALUES.
            Map enum index to method string via _METHOD_VALUES.
            Abort gracefully on cancel.
        """
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        int_unit_index = self.parameterAsEnum(parameters, self.UNITS, context)
        int_method_index = self.parameterAsEnum(parameters, self.METHOD, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        str_units = self._UNIT_VALUES[int_unit_index]
        str_method = self._METHOD_VALUES[int_method_index]

        feedback.setProgressText(
            f"Computing slope ({str_units}, {str_method}) in tiles..."
        )

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=compute_slope,
            halo_size=1,
            tile_size=2048,
            feedback=feedback,
            units=str_units,
            method=str_method,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
