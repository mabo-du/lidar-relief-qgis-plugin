"""e4mstp_algorithm.py — QGIS Processing wrapper for e4MSTP.
exports: E4MstpAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.emstp
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterRasterDestination,
)

import numpy as np
from ..core.raster_utils import process_in_tiles
from ..core.emstp import compute_e4mstp
from ..core.openness import topographic_openness
from ..core.local_dominance import compute_local_dominance
from ..core.slope import compute_slope
from ..core.mstp import compute_mstp
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class E4MstpAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """e4MSTP algorithm."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

    def name(self):
        return "e4mstp"

    def displayName(self):
        return "Enhanced 4-Scale Topographic Position (e4MSTP)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Enhanced 4-Scale Topographic Position (e4MSTP) uses the Kokalj (2025) "
            "4-step composite process to combine Openness, Local Dominance, Slope, "
            "and MSTP into a highly detailed RGB visualization.\n\n"
            "Note: the implementation also computes dual-scale Sky-View Factor "
            "(SVF_S radius=10, SVF_L radius=50) internally as a multiply-blend "
            "modifier (step 3 of the 4-step composite). SVF is not a user-tunable "
            "parameter for this algorithm.\n\n"
            "Sub-algorithm parameters (openness, LD, slope, MSTP radii) are "
            "currently hardcoded to canonical values; user-tunable exposure is "
            "planned for a future release."
        )

    def createInstance(self):
        return E4MstpAlgorithm()

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
                "e4MSTP output (RGB)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing true e4MSTP (7 sub-metrics) in tiles...")

        def e4mstp_wrapper(block, cellsize):
            # 1. Openness Pos (0 to ~100+ -> normalized roughly to [0,1])
            # But the Openness core function returns float32, we should normalize it.
            # Usually openness is normalized dynamically per tile or using a fixed stretch.
            # Standard openness values are typically between 0 and 120 degrees.
            # Actually RVT openness outputs degrees [0, 90+]. Let's divide by 90.
            open_pos_raw = topographic_openness(
                block,
                cellsize,
                num_directions=16,
                search_radius=10,
                is_negative=False,
                feedback=feedback,
            )
            open_pos = (open_pos_raw / 90.0).clip(0.0, 1.0)

            # 2. Openness Neg
            open_neg_raw = topographic_openness(
                block,
                cellsize,
                num_directions=16,
                search_radius=10,
                is_negative=True,
                feedback=feedback,
            )
            open_neg = (open_neg_raw / 90.0).clip(0.0, 1.0)

            # 3. Local Dominance (already outputting 0-255 byte scaled, convert to 0-1)
            ld_raw = compute_local_dominance(
                block,
                cellsize,
                min_rad=10,
                max_rad=20,
                anglr_res=15.0,
                observer_h=1.7,
                feedback=feedback,
            )
            local_dom = (ld_raw / 255.0).clip(0.0, 1.0)

            # 4. Slope (degrees [0, 90] -> [0, 1])
            slope_raw = compute_slope(block, cellsize, units="degrees")
            slope = (slope_raw / 90.0).clip(0.0, 1.0)

            # 5. MSTP (outputs 3-band RGB [0, 255] -> normalize to [0, 1])
            # Default MSTP radii: micro=3, meso=20, broad=100
            mstp = compute_mstp(
                block,
                local_r=3,
                meso_r=20,
                broad_r=100,
                feedback=feedback,
            )
            mstp_norm = mstp.astype(np.float32) / 255.0

            return compute_e4mstp(
                open_pos,
                open_neg,
                local_dom,
                slope,
                mstp_norm,
                dem=block,
                cellsize=cellsize,
                feedback=feedback,
            )

        # Largest radius needed is 100 (from MSTP broad_r=100)
        # Using a 1024 tile size keeps memory manageable during the heavy 7-algorithm stack.
        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=e4mstp_wrapper,
            halo_size=100,
            tile_size=1024,
            feedback=feedback,
        )

        if feedback.isCanceled():
            return {}

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(
                    "e4MSTP", stretch_type="none"
                )  # e4MSTP is fully rendered, shouldn't be stretched
            )

        return {self.OUTPUT: output_path}
