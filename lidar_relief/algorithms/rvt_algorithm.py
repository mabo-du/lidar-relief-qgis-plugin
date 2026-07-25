"""rvt_algorithm.py — QGIS Processing wrapper for rvt-py multi-directional hillshade.
exports: RvtMultidirectionalHillshadeAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  Optional dependency (rvt-py) — surface a clear install hint via feedback
  if the package is missing. Never raise on import; let the QGIS Processing
  framework show the message in the log panel instead.
  all raster I/O through core.raster_utils
  computation through core.rvt_vis
  check feedback.isCanceled() between major steps
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from ..core.raster_utils import process_in_tiles
from ..core.rvt_vis import has_rvt
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class RvtMultidirectionalHillshadeAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Multi-directional hillshade using the rvt-py reference implementation.

    rvt-py (Relief Visualization Toolbox) is the de-facto reference Python
    implementation used by archaeologists worldwide. This plugin's native
    multi-directional hillshade uses Horn's 3x3 gradient; this one uses rvt's
    reference algorithm so users can cross-validate results against any other
    RVT installation (QGIS plugin, standalone tool, R package).
    """

    INPUT = "INPUT"
    NR_DIRECTIONS = "NR_DIRECTIONS"
    OUTPUT = "OUTPUT"

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "rvt_multidirectional_hillshade"

    def displayName(self):
        return "RVT Multi-directional Hillshade"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Multi-directional hillshade using the rvt-py (Relief Visualization "
            "Toolbox) reference implementation. Requires the `rvt-py` package "
            "to be installed in the QGIS Python environment "
            "(`pip install rvt-py`). Useful for cross-validating results "
            "against other RVT installations."
        )

    def createInstance(self):
        return RvtMultidirectionalHillshadeAlgorithm()

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
                self.NR_DIRECTIONS,
                "Number of azimuth directions",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=16,
                minValue=4,
                maxValue=64,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "RVT multi-directional hillshade output",
            )
        )

    # -- processing ---------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        """Run rvt multi-directional hillshade.

        Rules:
            Fail loudly with an install hint if rvt-py is missing — do NOT
            silently fall back to the native implementation.
        """
        if not has_rvt():
            raise QgsProcessingException(
                "rvt-py is not installed in the QGIS Python environment. "
                "Install it from the OSGeo4W Shell (or your platform's "
                "equivalent) with:\n\n    pip install rvt-py\n\n"
                "Then restart QGIS and re-run this algorithm."
            )

        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        int_num_directions = self.parameterAsInt(
            parameters, self.NR_DIRECTIONS, context
        )
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText(
            f"Computing RVT multi-directional hillshade "
            f"({int_num_directions} directions) in tiles..."
        )

        # Import lazily so any ImportError surfaces as a clean feedback
        # message rather than a hard QGIS crash at algorithm launch time.
        from ..core.rvt_vis import rvt_multidirectional_hillshade

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=rvt_multidirectional_hillshade,
            halo_size=1,
            tile_size=2048,
            feedback=feedback,
            nr_directions=int_num_directions,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(
                    "RVT Multi-directional Hillshade", stretch_type="stddev"
                )
            )

        return {self.OUTPUT: output_path}
