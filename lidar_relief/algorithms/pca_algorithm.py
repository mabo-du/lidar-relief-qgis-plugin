"""pca_algorithm.py — QGIS Processing wrapper for PCA composite.
exports: PcaAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.pca
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import process_in_tiles
from ..core.pca import compute_pca_composite
from ..core.svf import sky_view_factor
from ..core.openness import topographic_openness
from ..core.slope import compute_slope
from ..core.local_dominance import compute_local_dominance
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class PcaAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """PCA Composite algorithm."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

    def name(self):
        return "pca_composite"

    def displayName(self):
        return "PCA RGB Composite"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Generates a 3-band RGB Principal Component Analysis (PCA) composite "
            "from Sky-View Factor, Positive Openness, Slope, and Local Dominance."
        )

    def createInstance(self):
        return PcaAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "PCA output (RGB)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing PCA Composite in tiles...")

        def pca_wrapper(block, cellsize):
            # Compute the 4 metrics with default/standard parameters
            svf = sky_view_factor(
                block,
                cellsize,
                num_directions=16,
                search_radius=10,
                noise_level=0,
                feedback=feedback,
            )

            openness = topographic_openness(
                block,
                cellsize,
                num_directions=16,
                search_radius=10,
                is_negative=False,
                feedback=feedback,
            )

            slope = compute_slope(block, cellsize, units="degrees")

            ld = compute_local_dominance(
                block, cellsize, min_rad=10, max_rad=20, feedback=feedback
            )

            return compute_pca_composite(svf, openness, slope, ld, feedback=feedback)

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=pca_wrapper,
            # halo_size must be >= max(search_radius, ld_max_rad) so that
            # pixels near tile edges get correct values from all
            # sub-algorithms. The previous value of 10 was too small for
            # the Local Dominance sub-call (max_rad=20) — LD pixels near
            # tile edges had wrong values.
            halo_size=20,
            tile_size=1024,
            feedback=feedback,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
