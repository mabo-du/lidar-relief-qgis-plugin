"""batch_algorithm.py — QGIS Processing wrapper for batch multi-algorithm run.
exports: BatchAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  check feedback.isCanceled() between major steps
  report progress as percentage across enabled algorithms
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

import numpy as np
from ..core.raster_utils import get_cell_size_from_path, process_in_tiles
from ..core.presets import get_preset

from ..core.hillshade import multidirectional_hillshade
from ..core.slrm import simple_local_relief_model
from ..core.svf import sky_view_factor
from ..core.slope import compute_slope
from ..core.openness import topographic_openness
from ..core.mstp import multi_scale_topographic_position
from ..core.vat import compute_vat
from ..core.blend import simple_red_relief
from ..core.local_dominance import compute_local_dominance
from ..core.asvf import anisotropic_sky_view_factor
from ..core.pca import compute_pca_composite
from ..core.emstp import compute_e4mstp
from .help_mixin import HelpUrlMixin


class BatchAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Run multiple LiDAR relief algorithms on the same DEM in one step."""

    INPUT = "INPUT"
    PRESET = "PRESET"

    RUN_HILLSHADE = "RUN_HILLSHADE"
    RUN_SLRM = "RUN_SLRM"
    RUN_SVF = "RUN_SVF"
    RUN_SLOPE = "RUN_SLOPE"
    RUN_OPENNESS = "RUN_OPENNESS"
    RUN_MSTP = "RUN_MSTP"
    RUN_VAT = "RUN_VAT"
    RUN_RED_RELIEF = "RUN_RED_RELIEF"
    RUN_LOCAL_DOMINANCE = "RUN_LOCAL_DOMINANCE"
    RUN_ASVF = "RUN_ASVF"
    RUN_E4MSTP = "RUN_E4MSTP"
    RUN_PCA = "RUN_PCA"

    HILLSHADE_OUTPUT = "HILLSHADE_OUTPUT"
    SLRM_OUTPUT = "SLRM_OUTPUT"
    SVF_OUTPUT = "SVF_OUTPUT"
    SLOPE_OUTPUT = "SLOPE_OUTPUT"
    OPENNESS_OUTPUT = "OPENNESS_OUTPUT"
    MSTP_OUTPUT = "MSTP_OUTPUT"
    VAT_OUTPUT = "VAT_OUTPUT"
    RED_RELIEF_OUTPUT = "RED_RELIEF_OUTPUT"
    LOCAL_DOMINANCE_OUTPUT = "LOCAL_DOMINANCE_OUTPUT"
    ASVF_OUTPUT = "ASVF_OUTPUT"
    E4MSTP_OUTPUT = "E4MSTP_OUTPUT"
    PCA_OUTPUT = "PCA_OUTPUT"

    TILE_SIZE = "TILE_SIZE"

    SVF_NUM_DIRECTIONS = "SVF_NUM_DIRECTIONS"
    OPENNESS_NUM_DIRECTIONS = "OPENNESS_NUM_DIRECTIONS"
    LD_OBSERVER_HEIGHT = "LD_OBSERVER_HEIGHT"
    SVF_RADIUS = "SVF_RADIUS"
    SVF_NOISE = "SVF_NOISE"
    OPENNESS_RADIUS = "OPENNESS_RADIUS"
    SLRM_RADIUS = "SLRM_RADIUS"
    LD_MIN_RAD = "LD_MIN_RAD"
    LD_MAX_RAD = "LD_MAX_RAD"
    MSTP_LOCAL = "MSTP_LOCAL"
    MSTP_MESO = "MSTP_MESO"
    MSTP_BROAD = "MSTP_BROAD"
    ASVF_ANISOTROPY_DIR = "ASVF_ANISOTROPY_DIR"
    ASVF_ANISOTROPY_WEIGHT = "ASVF_ANISOTROPY_WEIGHT"

    _PRESET_OPTIONS = [
        "Manual",
        "Flat / Agricultural",
        "Forested",
        "Upland / Steep",
        "Coastal",
    ]
    _PRESET_KEYS = [None, "flat_agricultural", "forested", "upland_steep", "coastal"]

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "batch_relief"

    def displayName(self):
        return "Batch Relief Visualisation"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Runs multiple relief visualisation algorithms on the same "
            "DEM in a single step using landscape-scale presets. "
            "Disable any algorithms you do not need via the checkboxes."
        )

    def createInstance(self):
        return BatchAlgorithm()

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
                self.PRESET,
                "Landscape Scale Preset",
                options=self._PRESET_OPTIONS,
                defaultValue=1,  # Meso default
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SVF_NUM_DIRECTIONS,
                "SVF Directions",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=16,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OPENNESS_NUM_DIRECTIONS,
                "Openness Directions",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=16,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LD_OBSERVER_HEIGHT,
                "Local Dominance Observer Height (m)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.7,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SVF_RADIUS,
                "SVF Search Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=10,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SVF_NOISE,
                "SVF Noise Level",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OPENNESS_RADIUS,
                "Openness Search Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=15,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLRM_RADIUS,
                "SLRM Trend Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=20,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LD_MIN_RAD,
                "Local Dominance Min Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=10,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LD_MAX_RAD,
                "Local Dominance Max Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=20,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MSTP_LOCAL,
                "MSTP Local Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=3,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MSTP_MESO,
                "MSTP Meso Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=20,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MSTP_BROAD,
                "MSTP Broad Radius (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=100,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ASVF_ANISOTROPY_DIR,
                "ASVF Anisotropy Direction (degrees)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=315.0,
                minValue=0.0,
                maxValue=360.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ASVF_ANISOTROPY_WEIGHT,
                "ASVF Anisotropy Weight (0.0 to 1.0)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=0.5,
                minValue=0.0,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TILE_SIZE,
                "Tile Size (px)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=1024,
                minValue=256,
                maxValue=8192,
            )
        )

        # Toggle switches
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_HILLSHADE, "Run Multi-directional Hillshade", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_SLRM, "Run Simple Local Relief Model", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_SVF, "Run Sky-View Factor", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_SLOPE, "Run Slope", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_OPENNESS, "Run Positive Openness", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_MSTP, "Run Multi-Scale Topographic Position", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_VAT, "Run VAT Composite", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_RED_RELIEF, "Run Simple Red Relief", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_LOCAL_DOMINANCE, "Run Local Dominance", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(self.RUN_ASVF, "Run ASVF", defaultValue=True)
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_E4MSTP, "Run e4MSTP", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUN_PCA, "Run PCA Composite", defaultValue=True
            )
        )

        # Optional outputs
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.HILLSHADE_OUTPUT,
                "Hillshade output",
                optional=True,
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.SLRM_OUTPUT, "SLRM output", optional=True, createByDefault=True
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.SVF_OUTPUT, "SVF output", optional=True, createByDefault=True
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.SLOPE_OUTPUT, "Slope output", optional=True, createByDefault=True
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OPENNESS_OUTPUT,
                "Openness output",
                optional=True,
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.MSTP_OUTPUT, "MSTP output", optional=True, createByDefault=True
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.VAT_OUTPUT, "VAT output", optional=True, createByDefault=True
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.RED_RELIEF_OUTPUT,
                "Red Relief output",
                optional=True,
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.LOCAL_DOMINANCE_OUTPUT,
                "Local Dominance output",
                optional=True,
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.ASVF_OUTPUT,
                "ASVF output",
                optional=True,
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.E4MSTP_OUTPUT,
                "e4MSTP output",
                optional=True,
                createByDefault=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.PCA_OUTPUT,
                "PCA output",
                optional=True,
                createByDefault=True,
            )
        )

    # -- processing ---------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        """Run enabled algorithms sequentially."""
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        preset_idx = self.parameterAsEnum(parameters, self.PRESET, context)
        preset_key = self._PRESET_KEYS[preset_idx]

        # Read manual parameters first
        p_cfg = {
            "svf_num_directions": self.parameterAsInt(
                parameters, self.SVF_NUM_DIRECTIONS, context
            ),
            "openness_num_directions": self.parameterAsInt(
                parameters, self.OPENNESS_NUM_DIRECTIONS, context
            ),
            "ld_observer_height": self.parameterAsDouble(
                parameters, self.LD_OBSERVER_HEIGHT, context
            ),
            "svf_radius": self.parameterAsInt(parameters, self.SVF_RADIUS, context),
            "svf_noise": self.parameterAsInt(parameters, self.SVF_NOISE, context),
            "openness_radius": self.parameterAsInt(
                parameters, self.OPENNESS_RADIUS, context
            ),
            "slrm_radius": self.parameterAsInt(parameters, self.SLRM_RADIUS, context),
            "ld_min_rad": self.parameterAsInt(parameters, self.LD_MIN_RAD, context),
            "ld_max_rad": self.parameterAsInt(parameters, self.LD_MAX_RAD, context),
            "mstp_local": self.parameterAsInt(parameters, self.MSTP_LOCAL, context),
            "mstp_meso": self.parameterAsInt(parameters, self.MSTP_MESO, context),
            "mstp_broad": self.parameterAsInt(parameters, self.MSTP_BROAD, context),
            "asvf_dir": self.parameterAsDouble(
                parameters, self.ASVF_ANISOTROPY_DIR, context
            ),
            "asvf_weight": self.parameterAsDouble(
                parameters, self.ASVF_ANISOTROPY_WEIGHT, context
            ),
        }
        tile_size = self.parameterAsInt(parameters, self.TILE_SIZE, context)

        # Override with preset if not manual.
        #
        # Presets are defined in METRES and converted here using the DEM's
        # real cell size. They used to be stored in pixels, which made them
        # correct only on a 1 m DEM — on 0.25 m LiDAR every preset radius
        # was silently a quarter of its intended real-world size.
        if preset_key is not None:
            preset_cellsize = get_cell_size_from_path(source.source())
            preset = get_preset(preset_key, preset_cellsize)
            feedback.pushInfo(
                f"Preset '{preset_key}' scaled for {preset_cellsize:g} m cells: "
                f"SVF r={preset['svf']['search_radius']} px, "
                f"openness r={preset['openness']['search_radius']} px, "
                f"SLRM r={preset['slrm']['trend_radius']} px"
            )
            p_cfg["svf_radius"] = preset["svf"]["search_radius"]
            p_cfg["svf_noise"] = preset["svf"]["noise_level"]
            p_cfg["openness_radius"] = preset["openness"]["search_radius"]
            p_cfg["slrm_radius"] = preset["slrm"]["trend_radius"]
            p_cfg["ld_min_rad"] = preset["local_dominance"]["min_rad"]
            p_cfg["ld_max_rad"] = preset["local_dominance"]["max_rad"]
            p_cfg["svf_num_directions"] = preset["svf"]["num_directions"]
            p_cfg["openness_num_directions"] = preset["openness"]["num_directions"]
            p_cfg["ld_observer_height"] = preset["local_dominance"]["observer_height"]

        tasks = []
        if self.parameterAsBool(parameters, self.RUN_HILLSHADE, context):
            tasks.append("hillshade")
        if self.parameterAsBool(parameters, self.RUN_SLRM, context):
            tasks.append("slrm")
        if self.parameterAsBool(parameters, self.RUN_SVF, context):
            tasks.append("svf")
        if self.parameterAsBool(parameters, self.RUN_SLOPE, context):
            tasks.append("slope")
        if self.parameterAsBool(parameters, self.RUN_OPENNESS, context):
            tasks.append("openness")
        if self.parameterAsBool(parameters, self.RUN_MSTP, context):
            tasks.append("mstp")
        if self.parameterAsBool(parameters, self.RUN_VAT, context):
            tasks.append("vat")
        if self.parameterAsBool(parameters, self.RUN_RED_RELIEF, context):
            tasks.append("red_relief")
        if self.parameterAsBool(parameters, self.RUN_LOCAL_DOMINANCE, context):
            tasks.append("local_dominance")
        if self.parameterAsBool(parameters, self.RUN_ASVF, context):
            tasks.append("asvf")
        if self.parameterAsBool(parameters, self.RUN_E4MSTP, context):
            tasks.append("e4mstp")
        if self.parameterAsBool(parameters, self.RUN_PCA, context):
            tasks.append("pca")

        if not tasks:
            feedback.reportError("No algorithms selected — nothing to do.")
            return {}

        dict_results = {}
        total = len(tasks)
        done = 0

        source_path = source.source()

        def update_progress():
            nonlocal done
            done += 1
            feedback.setProgress(int(100 * done / total))

        if "hillshade" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing multi-directional hillshade...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.HILLSHADE_OUTPUT, context
            )
            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=multidirectional_hillshade,
                halo_size=1,
                tile_size=tile_size,
                feedback=feedback,
                azimuths=[315.0, 45.0, 135.0, 225.0, 270.0, 0.0],
                altitude=45.0,
            )
            dict_results[self.HILLSHADE_OUTPUT] = out_path
            update_progress()

        if "slrm" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing Simple Local Relief Model...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.SLRM_OUTPUT, context
            )

            def slrm_wrapper(block, cellsize, radius):
                return simple_local_relief_model(block, radius)

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=slrm_wrapper,
                halo_size=p_cfg["slrm_radius"],
                tile_size=tile_size,
                feedback=feedback,
                radius=p_cfg["slrm_radius"],
            )
            dict_results[self.SLRM_OUTPUT] = out_path
            update_progress()

        if "svf" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing Sky-View Factor...")
            out_path = self.parameterAsOutputLayer(parameters, self.SVF_OUTPUT, context)
            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=sky_view_factor,
                halo_size=p_cfg["svf_radius"],
                tile_size=tile_size,
                feedback=feedback,
                num_directions=p_cfg["svf_num_directions"],
                search_radius=p_cfg["svf_radius"],
                noise_level=p_cfg["svf_noise"],
            )
            dict_results[self.SVF_OUTPUT] = out_path
            update_progress()

        if "slope" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing Slope...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.SLOPE_OUTPUT, context
            )
            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=compute_slope,
                halo_size=1,
                tile_size=tile_size,
                feedback=feedback,
                units="degrees",
            )
            dict_results[self.SLOPE_OUTPUT] = out_path
            update_progress()

        if "openness" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing Positive Openness...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.OPENNESS_OUTPUT, context
            )
            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=topographic_openness,
                halo_size=p_cfg["openness_radius"],
                tile_size=tile_size,
                feedback=feedback,
                num_directions=p_cfg["openness_num_directions"],
                search_radius=p_cfg["openness_radius"],
                is_negative=False,
            )
            dict_results[self.OPENNESS_OUTPUT] = out_path
            update_progress()

        if "mstp" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing MSTP...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.MSTP_OUTPUT, context
            )

            def mstp_wrapper(block, cellsize, local_r, meso_r, broad_r, lightness):
                return multi_scale_topographic_position(
                    block, local_r, meso_r, broad_r, lightness, feedback
                )

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=mstp_wrapper,
                halo_size=p_cfg["mstp_broad"],
                tile_size=tile_size,
                feedback=feedback,
                local_r=p_cfg["mstp_local"],
                meso_r=p_cfg["mstp_meso"],
                broad_r=p_cfg["mstp_broad"],
                lightness=1.0,
            )
            dict_results[self.MSTP_OUTPUT] = out_path
            update_progress()

        if "vat" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing VAT Composite...")
            out_path = self.parameterAsOutputLayer(parameters, self.VAT_OUTPUT, context)

            def vat_wrapper(block, cellsize, svf_radius, openness_radius):
                return compute_vat(
                    block, cellsize, svf_radius, openness_radius, feedback
                )

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=vat_wrapper,
                halo_size=max(p_cfg["svf_radius"], p_cfg["openness_radius"]),
                tile_size=tile_size,
                feedback=feedback,
                svf_radius=p_cfg["svf_radius"],
                openness_radius=p_cfg["openness_radius"],
            )
            dict_results[self.VAT_OUTPUT] = out_path
            update_progress()

        if "red_relief" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing Simple Red Relief...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.RED_RELIEF_OUTPUT, context
            )

            def red_relief_wrapper(block, cellsize, slrm_radius):
                return simple_red_relief(block, cellsize, slrm_radius, feedback)

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=red_relief_wrapper,
                halo_size=p_cfg["slrm_radius"],
                tile_size=tile_size,
                feedback=feedback,
                slrm_radius=p_cfg["slrm_radius"],
            )
            dict_results[self.RED_RELIEF_OUTPUT] = out_path
            update_progress()

        if "local_dominance" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing Local Dominance...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.LOCAL_DOMINANCE_OUTPUT, context
            )

            def ld_wrapper(block, cellsize):
                return compute_local_dominance(
                    block,
                    cellsize,
                    min_rad=p_cfg["ld_min_rad"],
                    max_rad=p_cfg["ld_max_rad"],
                    observer_h=p_cfg["ld_observer_height"],
                    feedback=feedback,
                )

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=ld_wrapper,
                halo_size=p_cfg["ld_max_rad"],
                tile_size=tile_size,
                feedback=feedback,
            )
            dict_results[self.LOCAL_DOMINANCE_OUTPUT] = out_path
            update_progress()

        if "asvf" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing ASVF...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.ASVF_OUTPUT, context
            )

            def asvf_wrapper(block, cellsize, radius):
                return anisotropic_sky_view_factor(
                    block,
                    cellsize,
                    num_directions=p_cfg["svf_num_directions"],
                    search_radius=radius,
                    anisotropy_dir=p_cfg["asvf_dir"],
                    anisotropy_weight=p_cfg["asvf_weight"],
                    noise_level=p_cfg["svf_noise"],
                    feedback=feedback,
                )

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=asvf_wrapper,
                halo_size=p_cfg["svf_radius"],
                tile_size=tile_size,
                feedback=feedback,
                radius=p_cfg["svf_radius"],
            )
            dict_results[self.ASVF_OUTPUT] = out_path
            update_progress()

        if "e4mstp" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing e4MSTP...")
            out_path = self.parameterAsOutputLayer(
                parameters, self.E4MSTP_OUTPUT, context
            )

            def e4mstp_wrapper(block, cellsize):
                open_pos_raw = topographic_openness(
                    block,
                    cellsize,
                    num_directions=p_cfg["openness_num_directions"],
                    search_radius=p_cfg["openness_radius"],
                    is_negative=False,
                    feedback=feedback,
                )
                open_pos = (open_pos_raw / 90.0).clip(0, 1)
                open_neg_raw = topographic_openness(
                    block,
                    cellsize,
                    num_directions=p_cfg["openness_num_directions"],
                    search_radius=p_cfg["openness_radius"],
                    is_negative=True,
                    feedback=feedback,
                )
                open_neg = (open_neg_raw / 90.0).clip(0, 1)
                local_dom_raw = compute_local_dominance(
                    block,
                    cellsize,
                    min_rad=p_cfg["ld_min_rad"],
                    max_rad=p_cfg["ld_max_rad"],
                    observer_h=p_cfg["ld_observer_height"],
                    feedback=feedback,
                )
                local_dom = (local_dom_raw / 255.0).clip(0, 1)
                slope = (compute_slope(block, cellsize, units="degrees") / 90.0).clip(
                    0, 1
                )
                mstp = multi_scale_topographic_position(
                    block,
                    local_radius=p_cfg["mstp_local"],
                    meso_radius=p_cfg["mstp_meso"],
                    broad_radius=p_cfg["mstp_broad"],
                    feedback=feedback,
                )
                mstp_norm = mstp.astype(np.float32)
                if mstp_norm.max() > 1.0:
                    mstp_norm /= 255.0
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
                source_path=source_path,
                output_path=out_path,
                algorithm_func=e4mstp_wrapper,
                halo_size=p_cfg["mstp_broad"],
                tile_size=tile_size,
                feedback=feedback,
            )
            dict_results[self.E4MSTP_OUTPUT] = out_path
            update_progress()

        if "pca" in tasks and not feedback.isCanceled():
            feedback.setProgressText("Batch: Computing PCA...")
            out_path = self.parameterAsOutputLayer(parameters, self.PCA_OUTPUT, context)

            def pca_wrapper(block, cellsize):
                svf = sky_view_factor(
                    block,
                    cellsize,
                    num_directions=p_cfg["svf_num_directions"],
                    search_radius=p_cfg["svf_radius"],
                    noise_level=p_cfg["svf_noise"],
                    feedback=feedback,
                )
                openness = topographic_openness(
                    block,
                    cellsize,
                    num_directions=p_cfg["openness_num_directions"],
                    search_radius=p_cfg["openness_radius"],
                    is_negative=False,
                    feedback=feedback,
                )
                slope = compute_slope(block, cellsize, units="degrees")
                ld = compute_local_dominance(
                    block,
                    cellsize,
                    min_rad=p_cfg["ld_min_rad"],
                    max_rad=p_cfg["ld_max_rad"],
                    observer_h=p_cfg["ld_observer_height"],
                    feedback=feedback,
                )
                return compute_pca_composite(
                    svf, openness, slope, ld, feedback=feedback
                )

            process_in_tiles(
                source_path=source_path,
                output_path=out_path,
                algorithm_func=pca_wrapper,
                halo_size=p_cfg["ld_max_rad"],
                tile_size=tile_size,
                feedback=feedback,
            )
            dict_results[self.PCA_OUTPUT] = out_path
            update_progress()

        return dict_results
