"""rvt_openness_algorithm.py — QGIS Processing wrapper for rvt-py topographic openness.
exports: RvtOpennessAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  Optional dependency (rvt-py) — surface a clear install hint via feedback
  if the package is missing. Never raise on import; let the QGIS Processing
  framework show the message in the log panel instead.
  all raster I/O through core.raster_utils
  computation through core.rvt_vis
  check feedback.isCanceled() between major steps
  parameter UX mirrors openness_algorithm.py so the two are drop-in swaps
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from ..core.raster_utils import get_cell_size_from_path, process_in_tiles
from ..core.rvt_vis import has_rvt
from ..core.scale import RADIUS_UNIT_OPTIONS, RADIUS_UNIT_VALUES, resolve_radius
from ..styling import ReliefLayerPostProcessor


class RvtOpennessAlgorithm(QgsProcessingAlgorithm):
    """Topographic Openness using the rvt-py (Relief Visualization Toolbox)
    reference implementation.

    rvt-py computes openness as the mean zenith/nadir horizon angle over a
    search radius, returned in degrees after we mirror the native plugin's
    contract. Positive Openness highlights convex features (mounds, ridges);
    Negative Openness highlights concave features (ditches, pits).

    Useful for cross-validating results against other RVT installations
    (QGIS plugin, standalone tool, R package).
    """

    INPUT = "INPUT"
    OPENNESS_TYPE = "OPENNESS_TYPE"
    NUM_DIRECTIONS = "NUM_DIRECTIONS"
    SEARCH_RADIUS = "SEARCH_RADIUS"
    RADIUS_UNITS = "RADIUS_UNITS"
    OUTPUT = "OUTPUT"

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "rvt_openness"

    def displayName(self):
        return "RVT Topographic Openness"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Topographic Openness (Positive or Negative) using the `rvt-py` "
            "(Relief Visualization Toolbox) reference implementation. "
            "Requires the `rvt-py` package to be installed in the QGIS "
            "Python environment (`pip install rvt-py`). Useful for "
            "cross-validating results against other RVT installations."
        )

    def createInstance(self):
        return RvtOpennessAlgorithm()

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
                self.OPENNESS_TYPE,
                "Openness Type",
                options=["Positive (Convex)", "Negative (Concave)"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.NUM_DIRECTIONS,
                "Search Directions",
                options=["8 (fast)", "16 (standard)", "32 (quality)"],
                defaultValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEARCH_RADIUS,
                "Search Radius",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=20,
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
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "RVT openness output",
            )
        )

    # -- processing ---------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        """Run rvt topographic openness.

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
        type_idx = self.parameterAsEnum(parameters, self.OPENNESS_TYPE, context)
        dir_idx = self.parameterAsEnum(parameters, self.NUM_DIRECTIONS, context)
        radius_value = self.parameterAsDouble(parameters, self.SEARCH_RADIUS, context)
        units_idx = self.parameterAsEnum(parameters, self.RADIUS_UNITS, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        is_negative = type_idx == 1
        num_dirs = [8, 16, 32][dir_idx]

        # rvt_openness rejects a radius outside 1..500 px, so clamp here
        # rather than letting a metres value blow past the contract.
        radius = resolve_radius(
            radius_value,
            RADIUS_UNIT_VALUES[units_idx],
            get_cell_size_from_path(source.source()),
            "RVT openness search radius",
            feedback,
            minimum=1,
            maximum=500,
        )

        feedback.setProgressText(
            f"Computing RVT openness ({num_dirs} dirs, r={radius}, "
            f"{'Negative' if is_negative else 'Positive'}) in tiles..."
        )

        # Import lazily so any ImportError surfaces as a clean feedback
        # message rather than a hard QGIS crash at algorithm launch time.
        from ..core.rvt_vis import rvt_openness

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=rvt_openness,
            halo_size=radius,
            tile_size=2048,
            feedback=feedback,
            num_directions=num_dirs,
            search_radius=radius,
            is_negative=is_negative,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
