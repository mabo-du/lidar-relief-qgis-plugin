"""svf_algorithm.py — QGIS Processing wrapper for Sky-View Factor.
exports: SvfAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  computation through core.svf
  enum index maps to [8, 16, 32] directions
  check feedback.isCanceled() between major steps
  USE_GPU is advisory — core.svf falls back to NumPy when CuPy/CUDA is
  missing, so this parameter must never be able to fail a run.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Exposed the GPU toggle. The CuPy backend shipped since 2.0 but
         nothing in the plugin ever called it, so the README's GPU
         acceleration feature was unreachable from the UI.
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    get_cell_size_from_path,
    process_in_tiles,
)
from ..core.scale import RADIUS_UNIT_OPTIONS, RADIUS_UNIT_VALUES, resolve_radius
from ..core.svf import sky_view_factor
from ..styling import ReliefLayerPostProcessor
from .help_mixin import HelpUrlMixin
from .provenance_mixin import ProvenanceMixin


class SvfAlgorithm(ProvenanceMixin, HelpUrlMixin, QgsProcessingAlgorithm):
    """Sky-View Factor — portion of sky visible from each cell."""

    HELP_ANCHOR = "choosing-a-search-radius"

    INPUT = "INPUT"
    NUM_DIRECTIONS = "NUM_DIRECTIONS"
    SEARCH_RADIUS = "SEARCH_RADIUS"
    RADIUS_UNITS = "RADIUS_UNITS"
    NOISE_LEVEL = "NOISE_LEVEL"
    USE_GPU = "USE_GPU"
    OUTPUT = "OUTPUT"

    _DIRECTION_OPTIONS = ["8 (fast)", "16 (standard)", "32 (quality)"]
    _DIRECTION_VALUES = [8, 16, 32]

    # -- metadata -----------------------------------------------------------

    def name(self):
        return "sky_view_factor"

    def displayName(self):
        return "Sky-View Factor (SVF)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Computes the Sky-View Factor for each cell — the proportion "
            "of the sky hemisphere visible from that point. Values range "
            "from 0 (completely obstructed) to 1 (flat open terrain). "
            "SVF excels at revealing subtle concave features such as "
            "ditches and hollow ways."
        )

    def createInstance(self):
        return SvfAlgorithm()

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
                self.NUM_DIRECTIONS,
                "Number of azimuth directions",
                options=self._DIRECTION_OPTIONS,
                defaultValue=1,  # index 1 → 16 (standard)
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEARCH_RADIUS,
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
            QgsProcessingParameterEnum(
                self.NOISE_LEVEL,
                "Noise removal look-ahead",
                options=["None", "Low", "Medium", "High"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.USE_GPU,
                "Use GPU acceleration (CuPy/CUDA) if available",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "SVF output",
            )
        )

    # -- processing ---------------------------------------------------------

    @staticmethod
    def _resolve_gpu_request(requested: bool, noise_level: int, feedback) -> bool:
        """Decide whether to run on the GPU and explain the decision.

        Rules:
            Never raise. A user who ticks the box on a machine without
            CuPy must still get their SVF — just on the CPU, with a log
            line saying why.
        """
        if not requested:
            return False

        from ..gpu.compute_backend import cupy_available

        if not cupy_available():
            feedback.pushInfo(
                "GPU acceleration requested but CuPy/CUDA is not available. "
                "Running on the CPU. To enable it, install CuPy for your "
                "CUDA version (e.g. `pip install cupy-cuda12x`) into the "
                "Python environment QGIS uses, then restart QGIS."
            )
            return False
        if noise_level > 0:
            feedback.pushInfo(
                "GPU acceleration requested, but the noise-removal "
                "look-ahead filter is CPU-only. Running on the CPU so the "
                "result matches the documented algorithm. Set noise "
                "removal to 'None' to use the GPU."
            )
            return False

        feedback.pushInfo("Using the CuPy GPU backend for Sky-View Factor.")
        return True

    def processAlgorithm(self, parameters, context, feedback):
        """Run Sky-View Factor computation.

        Rules:
            Map enum index to actual direction count via _DIRECTION_VALUES.
            Abort gracefully on cancel.
        """
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        int_dir_index = self.parameterAsEnum(parameters, self.NUM_DIRECTIONS, context)
        float_search_radius = self.parameterAsDouble(
            parameters, self.SEARCH_RADIUS, context
        )
        int_units_index = self.parameterAsEnum(parameters, self.RADIUS_UNITS, context)
        int_noise_level = self.parameterAsEnum(parameters, self.NOISE_LEVEL, context)
        bool_use_gpu = self.parameterAsBoolean(parameters, self.USE_GPU, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        int_num_directions = self._DIRECTION_VALUES[int_dir_index]

        # Convert the radius to pixels and report it in both units, so a
        # radius that is far too small for the DEM's resolution is
        # obvious in the log before the run starts.
        float_cellsize = get_cell_size_from_path(source.source())
        int_search_radius = resolve_radius(
            float_search_radius,
            RADIUS_UNIT_VALUES[int_units_index],
            float_cellsize,
            "SVF search radius",
            feedback,
        )

        bool_use_gpu = self._resolve_gpu_request(
            bool_use_gpu, int_noise_level, feedback
        )

        feedback.setProgressText(
            f"Computing Sky-View Factor ({int_num_directions} directions) in tiles..."
        )

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=sky_view_factor,
            halo_size=int_search_radius,
            tile_size=2048,
            feedback=feedback,
            num_directions=int_num_directions,
            search_radius=int_search_radius,
            noise_level=int_noise_level,
            use_gpu=bool_use_gpu,
        )

        if feedback.isCanceled():
            return {}

        self.record_provenance(
            output_path,
            parameters={
                "num_directions": int_num_directions,
                "search_radius_pixels": int_search_radius,
                "search_radius_input": float_search_radius,
                "radius_units": RADIUS_UNIT_VALUES[int_units_index],
                "noise_level": int_noise_level,
                "cell_size": float_cellsize,
                "use_gpu": bool_use_gpu,
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
