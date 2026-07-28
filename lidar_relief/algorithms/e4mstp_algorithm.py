"""e4mstp_algorithm.py — QGIS Processing wrapper for e4MSTP.
exports: E4MstpAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.emstp
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterNumber,
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
from ..e4mstp_settings import E4MstpSettings
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin


class E4MstpAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """e4MSTP algorithm."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    OPENNESS_RADIUS = "OPENNESS_RADIUS"
    NUM_DIRECTIONS = "NUM_DIRECTIONS"
    LD_MIN_RADIUS = "LD_MIN_RADIUS"
    LD_MAX_RADIUS = "LD_MAX_RADIUS"
    LD_ANGULAR_RESOLUTION = "LD_ANGULAR_RESOLUTION"
    LD_OBSERVER_HEIGHT = "LD_OBSERVER_HEIGHT"
    MSTP_LOCAL_RADIUS = "MSTP_LOCAL_RADIUS"
    MSTP_MESO_RADIUS = "MSTP_MESO_RADIUS"
    MSTP_BROAD_RADIUS = "MSTP_BROAD_RADIUS"
    TILE_SIZE = "TILE_SIZE"

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
            "Advanced parameters expose openness, Local Dominance, MSTP, and "
            "tile controls. Their defaults reproduce the canonical historical "
            "e4MSTP output."
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
        defaults = E4MstpSettings()

        def add_advanced(parameter):
            parameter.setFlags(
                parameter.flags() | QgsProcessingParameterDefinition.Flag.FlagAdvanced
            )
            self.addParameter(parameter)

        controls = (
            (self.OPENNESS_RADIUS, "Openness radius (px)", defaults.openness_radius),
            (self.NUM_DIRECTIONS, "Openness directions", defaults.num_directions),
            (self.LD_MIN_RADIUS, "LD minimum radius (px)", defaults.ld_min_radius),
            (self.LD_MAX_RADIUS, "LD maximum radius (px)", defaults.ld_max_radius),
            (
                self.MSTP_LOCAL_RADIUS,
                "MSTP local radius (px)",
                defaults.mstp_local_radius,
            ),
            (
                self.MSTP_MESO_RADIUS,
                "MSTP meso radius (px)",
                defaults.mstp_meso_radius,
            ),
            (
                self.MSTP_BROAD_RADIUS,
                "MSTP broad radius (px)",
                defaults.mstp_broad_radius,
            ),
            (self.TILE_SIZE, "Tile size (px)", defaults.tile_size),
        )
        for name, label, default in controls:
            add_advanced(
                QgsProcessingParameterNumber(
                    name,
                    label,
                    type=QgsProcessingParameterNumber.Type.Integer,
                    defaultValue=default,
                    minValue=1 if name != self.TILE_SIZE else 256,
                )
            )
        for name, label, default in (
            (
                self.LD_ANGULAR_RESOLUTION,
                "LD angular resolution (degrees)",
                defaults.ld_angular_resolution,
            ),
            (
                self.LD_OBSERVER_HEIGHT,
                "LD observer height",
                defaults.ld_observer_height,
            ),
        ):
            add_advanced(
                QgsProcessingParameterNumber(
                    name,
                    label,
                    type=QgsProcessingParameterNumber.Type.Double,
                    defaultValue=default,
                    minValue=0.1,
                )
            )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        settings = E4MstpSettings(
            openness_radius=self.parameterAsInt(
                parameters, self.OPENNESS_RADIUS, context
            ),
            num_directions=self.parameterAsInt(
                parameters, self.NUM_DIRECTIONS, context
            ),
            ld_min_radius=self.parameterAsInt(parameters, self.LD_MIN_RADIUS, context),
            ld_max_radius=self.parameterAsInt(parameters, self.LD_MAX_RADIUS, context),
            ld_angular_resolution=self.parameterAsDouble(
                parameters, self.LD_ANGULAR_RESOLUTION, context
            ),
            ld_observer_height=self.parameterAsDouble(
                parameters, self.LD_OBSERVER_HEIGHT, context
            ),
            mstp_local_radius=self.parameterAsInt(
                parameters, self.MSTP_LOCAL_RADIUS, context
            ),
            mstp_meso_radius=self.parameterAsInt(
                parameters, self.MSTP_MESO_RADIUS, context
            ),
            mstp_broad_radius=self.parameterAsInt(
                parameters, self.MSTP_BROAD_RADIUS, context
            ),
            tile_size=self.parameterAsInt(parameters, self.TILE_SIZE, context),
        )
        try:
            settings.validate()
        except ValueError as exc:
            raise QgsProcessingException(str(exc)) from exc

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
                num_directions=settings.num_directions,
                search_radius=settings.openness_radius,
                is_negative=False,
                feedback=feedback,
            )
            open_pos = (open_pos_raw / 90.0).clip(0.0, 1.0)

            # 2. Openness Neg
            open_neg_raw = topographic_openness(
                block,
                cellsize,
                num_directions=settings.num_directions,
                search_radius=settings.openness_radius,
                is_negative=True,
                feedback=feedback,
            )
            open_neg = (open_neg_raw / 90.0).clip(0.0, 1.0)

            # 3. Local Dominance (already outputting 0-255 byte scaled, convert to 0-1)
            ld_raw = compute_local_dominance(
                block,
                cellsize,
                min_rad=settings.ld_min_radius,
                max_rad=settings.ld_max_radius,
                anglr_res=settings.ld_angular_resolution,
                observer_h=settings.ld_observer_height,
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
                local_r=settings.mstp_local_radius,
                meso_r=settings.mstp_meso_radius,
                broad_r=settings.mstp_broad_radius,
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

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=e4mstp_wrapper,
            halo_size=settings.halo_size,
            tile_size=settings.tile_size,
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
